"""
TheCRM — Membership Pipeline (backend)
Operated by TheCRMCompany.info

A small, deployable Flask + SQLAlchemy API with server-side role enforcement.
- Admin (you): can import leads, run weekly verification, view reports.
- Agent (freelancer): can ONLY work existing leads (log calls, move stages).
  Lead creation and verification are blocked server-side, so the agent cannot
  seed his own contacts even by calling the API directly.

Runs on SQLite locally with zero config; uses Postgres (Neon/Railway) in prod
via the DATABASE_URL environment variable.
"""

import os
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static")

# Secret used to sign login tokens. MUST be set in production.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-insecure-secret-change-me")

# Access codes. Override these in production via environment variables.
ADMIN_CODE = os.environ.get("ADMIN_CODE", "calabasas2026")
AGENT_CODE = os.environ.get("AGENT_CODE", "pipeline99")

# Database URL. Falls back to local SQLite if DATABASE_URL is not set.
db_url = os.environ.get("DATABASE_URL", "sqlite:///crm.db")
# Some providers hand out the legacy "postgres://" scheme; SQLAlchemy wants "postgresql://".
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
signer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="thecrm-auth")

TOKEN_MAX_AGE = 60 * 60 * 24 * 14  # 14 days


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
def new_id():
    return "L" + uuid.uuid4().hex[:12]


def utcnow():
    return datetime.now(timezone.utc)


class Lead(db.Model):
    __tablename__ = "leads"
    id = db.Column(db.String(20), primary_key=True, default=new_id)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(60), default="")
    email = db.Column(db.String(200), default="")
    source = db.Column(db.String(300), default="")
    stage = db.Column(db.String(20), default="new")       # new/contacted/interested/tour/signed/lost
    verify = db.Column(db.String(20), default="none")     # none/pending/active/inactive
    created = db.Column(db.DateTime, default=utcnow)
    activity = db.relationship(
        "Activity", backref="lead", cascade="all, delete-orphan",
        order_by="Activity.at"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone or "",
            "email": self.email or "",
            "source": self.source or "",
            "stage": self.stage,
            "verify": self.verify,
            "created": iso(self.created),
            "activity": [a.to_dict() for a in self.activity],
        }


class Activity(db.Model):
    __tablename__ = "activities"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.String(20), db.ForeignKey("leads.id"), nullable=False)
    type = db.Column(db.String(20), nullable=False)   # call/text/email/note/stage/verify/import
    note = db.Column(db.Text, default="")
    to_value = db.Column(db.String(20), default="")    # stage id or verify value
    by = db.Column(db.String(20), default="")          # Admin / Agent
    at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        d = {"type": self.type, "at": iso(self.at), "by": self.by}
        if self.note:
            d["note"] = self.note
        if self.to_value:
            d["to"] = self.to_value
        return d


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def make_token(role):
    return signer.dumps({"role": role})


def read_token():
    """Return the role from the Authorization header, or None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    tok = auth[7:].strip()
    try:
        data = signer.loads(tok, max_age=TOKEN_MAX_AGE)
        return data.get("role")
    except (BadSignature, SignatureExpired):
        return None


def require_role(*allowed):
    """Decorator: enforce that the caller holds one of the allowed roles."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            role = read_token()
            if role is None:
                return jsonify(error="Not authenticated"), 401
            if role not in allowed:
                return jsonify(error="Not permitted for your role"), 403
            request.role = role
            return fn(*a, **kw)
        return wrapper
    return deco


def actor():
    return "Admin" if getattr(request, "role", "") == "admin" else "Agent"


# ---------------------------------------------------------------------------
# API — auth
# ---------------------------------------------------------------------------
@app.post("/api/login")
def login():
    body = request.get_json(silent=True) or {}
    role = body.get("role")
    code = (body.get("code") or "").strip()
    if role == "admin" and code == ADMIN_CODE:
        return jsonify(token=make_token("admin"), role="admin")
    if role == "agent" and code == AGENT_CODE:
        return jsonify(token=make_token("agent"), role="agent")
    return jsonify(error="Invalid access code"), 401


# ---------------------------------------------------------------------------
# API — leads (read: both roles)
# ---------------------------------------------------------------------------
@app.get("/api/leads")
@require_role("admin", "agent")
def list_leads():
    leads = Lead.query.order_by(Lead.created.desc()).all()
    return jsonify(leads=[l.to_dict() for l in leads])


# ---------------------------------------------------------------------------
# API — lead creation (ADMIN ONLY — this is the whole point)
# ---------------------------------------------------------------------------
def _create_lead(name, phone="", email="", source=""):
    lead = Lead(
        id=new_id(), name=name.strip(),
        phone=(phone or "").strip(), email=(email or "").strip(),
        source=(source or "").strip(), stage="new", verify="none",
        created=utcnow(),
    )
    db.session.add(lead)
    db.session.add(Activity(lead_id=lead.id, type="import", by="Admin", at=utcnow()))
    return lead


@app.post("/api/leads")
@require_role("admin")
def create_lead():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify(error="Name is required"), 400
    lead = _create_lead(name, body.get("phone"), body.get("email"), body.get("source"))
    db.session.commit()
    return jsonify(lead=lead.to_dict()), 201


@app.post("/api/leads/bulk")
@require_role("admin")
def create_bulk():
    body = request.get_json(silent=True) or {}
    rows = body.get("rows") or []
    added = 0
    for r in rows:
        name = (r.get("name") or "").strip()
        if name:
            _create_lead(name, r.get("phone"), r.get("email"), r.get("source"))
            added += 1
    if not added:
        return jsonify(error="No valid rows"), 400
    db.session.commit()
    return jsonify(added=added), 201


# ---------------------------------------------------------------------------
# API — work a lead (stage + activity: both roles)
# ---------------------------------------------------------------------------
VALID_STAGES = {"new", "contacted", "interested", "tour", "signed", "lost"}
VALID_ACT = {"call", "text", "email", "note"}


@app.post("/api/leads/<lid>/stage")
@require_role("admin", "agent")
def set_stage(lid):
    lead = db.session.get(Lead, lid)
    if not lead:
        return jsonify(error="Lead not found"), 404
    body = request.get_json(silent=True) or {}
    stage = body.get("stage")
    if stage not in VALID_STAGES:
        return jsonify(error="Invalid stage"), 400
    if lead.stage != stage:
        lead.stage = stage
        if stage == "signed" and lead.verify in ("none", "", None):
            lead.verify = "pending"
        db.session.add(Activity(lead_id=lead.id, type="stage", to_value=stage,
                                by=actor(), at=utcnow()))
        db.session.commit()
    return jsonify(lead=lead.to_dict())


@app.post("/api/leads/<lid>/activity")
@require_role("admin", "agent")
def add_activity(lid):
    lead = db.session.get(Lead, lid)
    if not lead:
        return jsonify(error="Lead not found"), 404
    body = request.get_json(silent=True) or {}
    atype = body.get("type")
    note = (body.get("note") or "").strip()
    if atype not in VALID_ACT:
        return jsonify(error="Invalid activity type"), 400
    db.session.add(Activity(lead_id=lead.id, type=atype, note=note,
                            by=actor(), at=utcnow()))
    db.session.commit()
    return jsonify(lead=lead.to_dict())


# ---------------------------------------------------------------------------
# API — weekly verification (ADMIN ONLY)
# ---------------------------------------------------------------------------
@app.post("/api/leads/<lid>/verify")
@require_role("admin")
def verify_lead(lid):
    lead = db.session.get(Lead, lid)
    if not lead:
        return jsonify(error="Lead not found"), 404
    body = request.get_json(silent=True) or {}
    val = body.get("verify")
    if val not in ("active", "inactive"):
        return jsonify(error="Invalid verification value"), 400
    lead.verify = val
    db.session.add(Activity(lead_id=lead.id, type="verify", to_value=val,
                            by="Admin", at=utcnow()))
    db.session.commit()
    return jsonify(lead=lead.to_dict())


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/health")
def health():
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
with app.app_context():
    db.create_all()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
