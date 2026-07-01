# Membership Pipeline CRM
### Operated by TheCRMCompany.info

A two-role CRM for tracking membership leads. Built so that **only the
administrator can add leads** — the agent can only work the leads you give
him, log calls, and move them through the pipeline. You run a weekly
verification pass to confirm who actually became an active member.

This version is **multi-user**: you and the agent log in from different
computers and see the same shared data, backed by a real database.

---

## What each role can do

| Action | Admin (you) | Agent |
|---|:---:|:---:|
| See all leads & timelines | ✅ | ✅ |
| Log calls / texts / notes | ✅ | ✅ |
| Move a lead through pipeline stages | ✅ | ✅ |
| **Import / add new leads** | ✅ | ❌ |
| **Weekly verification (active / not active)** | ✅ | ❌ |
| Reports & sign-up reconciliation | ✅ | ❌ |

The agent restrictions are enforced **on the server**, not just hidden in the
interface. Even if the agent opens the browser dev tools and tries to call the
API directly, lead creation and verification return "Not permitted" (403).

---

## Run it locally (to test before deploying)

You need Python 3.11+.

```bash
cd membership-crm
pip install -r requirements.txt
python app.py
```

Open <http://localhost:5000>. With no configuration it uses a local SQLite
file and these default codes:

- Admin code: `calabasas2026`
- Agent code: `pipeline99`

**Change these before going live** (see below).

---

## Deploy to the web (Railway + Neon Postgres)

This is the same stack you've used before. ~10 minutes.

**1. Put the code on GitHub**
Create a new repo and push this folder to it.

**2. Create a database (Neon)**
- Sign in at neon.tech, create a project.
- Copy the connection string (starts with `postgresql://`).

**3. Create the app (Railway)**
- New Project → Deploy from GitHub repo → pick your repo.
- Railway auto-detects Python and uses the included `Procfile`.

**4. Set environment variables** in Railway's **Variables** tab:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Neon connection string from step 2 |
| `SECRET_KEY` | a long random string (see below) |
| `ADMIN_CODE` | your private admin code |
| `AGENT_CODE` | the code you give the agent |

Generate a SECRET_KEY:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**5. Deploy.** Railway gives you a URL like `https://your-app.up.railway.app`.
The database tables are created automatically on first boot.

**6. Point your domain (optional).**
In Railway → Settings → Networking, add `thecrmcompany.info` (or a subdomain
like `app.thecrmcompany.info`) and follow the DNS instructions.

---

## Day-to-day use

1. **You** log in as Administrator → **Lead Manager** → import leads (one at a
   time, or paste a list in bulk as `Name, Phone, Email, Source`).
2. **The agent** logs in as Agent, works only those leads, logs every call,
   and moves people toward "Signed Up."
3. **Once a week**, you open **Weekly Verification**, and for each person the
   agent marked "Signed Up," confirm against PlayByPoint whether they're a
   real active member (Active / Not Active).
4. **Reports** shows claimed sign-ups vs. verified-active, and flags anyone
   marked signed but not actually active — your check before paying commission.

---

## Changing access codes later

Just update `ADMIN_CODE` / `AGENT_CODE` in Railway's Variables and redeploy.
Anyone currently signed in stays signed in until they log out; new logins use
the new codes.

---

## Files

```
app.py             Flask backend: models, auth, role-enforced API
static/index.html  The full interface (single page)
requirements.txt   Python dependencies
Procfile           Tells Railway how to start the app
runtime.txt        Python version
.env.example       Template for local environment variables
```

---

## Notes & limits

- Login uses simple shared access codes (one for you, one for the agent),
  which is appropriate for a two-person tool. If you ever want per-person
  accounts, password resets, or an audit log of *who* logged in when, that's a
  straightforward upgrade.
- All lead activity is timestamped and attributed to "Admin" or "Agent."
- Data lives in your database; back it up periodically (Neon has automatic
  backups on paid tiers).
