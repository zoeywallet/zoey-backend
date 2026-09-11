# Zoey Wallet — backend (Python/FastAPI)

This is the same `zoey-backend` project that powers the public site at
`https://zoey-wallet-website-hosting.vercel.app/` — the backend has been
migrated in place from Node.js to Python/FastAPI. The frontend (this
README's `index.html`, `login.html`, `dashboard.html`, and every visual
detail in them) is unchanged from before the migration.

## Why this migration happened

Three production problems, all backend-side:

1. **`/login` → 404.** There was no Vercel routing configured to turn the
   bare path `/login` into `login.html`, and no backend deployed to serve
   it dynamically either.
2. **The lead form said "We couldn't reach our servers."** The frontend's
   `fetch('/api/leads', ...)` call was hitting Vercel's generic 404 page
   (no `/api/leads` function existed), and trying to parse that HTML page
   as JSON threw an error — which the frontend correctly reported as "can't
   reach our servers."
3. **A previous attempt to deploy the Node backend crashed:**
   ```
   TypeError: db.listUsers is not a function
       at Object.<anonymous> (/var/task/src/server.js:46:8)
   ```
   `src/server.js` calls `db.listUsers()` at module load time (line 46, to
   log a warning if no accounts exist yet). `db.listUsers` *is* exported
   from the local `src/db.js` — so this wasn't a missing function in the
   source, it was a **stale/mismatched deployment bundle**: whatever got
   uploaded to Vercel didn't match the local `db.js`. On top of that,
   `src/server.js` calls `server.listen(PORT)` — a permanently-running
   server process — which fundamentally cannot work on Vercel's serverless
   runtime regardless of that bug: there is no persistent process for a
   port to stay bound to. And separately, the logger tried to
   `mkdir('/var/task/logs')`, which fails because Vercel's deployment
   filesystem is read-only outside `/tmp`.

Rather than patch around these one at a time, the backend is rebuilt in
Python/FastAPI, designed from the ground up for how Vercel actually runs
serverless functions (see "Serverless, explained" below).

## What changed vs. what didn't

**Unchanged:** every pixel of `index.html`, `login.html`, and
`dashboard.html` — typography, colors, layout, animations, the hero and
About and Infrastructure sections, the lead-capture modal, the dashboard
cards and chart. Nothing here was redesigned.

**Changed in the frontend (5 lines total, across 3 files):**
- `index.html`: the `file://`-protocol guard's alert text now says
  `uvicorn api.index:app --reload` / `http://127.0.0.1:8000` instead of
  `npm start` / port 3001 (the actual local-dev command changed; nothing
  else about that guard changed). The comment above
  `ZOEY_LEADS_API_BASE` now references the Python backend. The lead-form
  submission code itself (the fetch call, payload, success/error UI) was
  **not** touched — it already used a relative `/api/leads` URL.
- `login.html`: `fetch('/api/auth/login', ...)` → `fetch('/api/login', ...)`.
- `dashboard.html`: `fetch('/api/auth/logout', ...)` → `fetch('/api/logout', ...)`,
  and `fetch('/api/auth/me')` → `fetch('/api/me')`.

**Removed:** the Node backend (`src/`, `node_modules/`, `package.json`,
`package-lock.json`) and the now-empty `public/` folder. `index.html`,
`login.html`, and `dashboard.html` moved from `public/` to the repo root —
that's a deliberate, disclosed fix: it makes this project match Vercel's
default "serve static files from the repo root" behavior with no reliance
on a specific "Output Directory" dashboard setting, which is one plausible
reason `/login` wasn't resolving. **These old files weren't deleted** (this
session didn't have permission to delete on your machine) — they were
moved into `_to_delete/` inside this same folder. Open that folder, confirm
you don't need anything from it, and delete it yourself whenever you like.

**Not carried over, disclosed:** the admin lead-viewing dashboard, CSV
export, and Gmail lead-notification email that existed in the old Node
backend aren't in this rewrite, because they weren't in the migration spec.
`list_leads()` / `count_leads()` already exist in `backend/database.py` as
a foundation if you want these back later.

**Added, not yet wired up (per your request to prepare for it):**
`backend/services/market_data.py` and `backend/services/claude.py` — empty
placeholders with docstrings explaining where a future market-data feed and
a future Claude integration would plug in. Nothing calls Anthropic's API
yet, and nothing should ever put an Anthropic key in frontend JavaScript
when you do build it — see the docstring in `claude.py`.

## Final project structure

```
zoey-backend/
├── index.html              # homepage — visually unchanged
├── login.html               # 1 fetch URL changed
├── dashboard.html            # 2 fetch URLs changed
├── assets/                   # placeholder for future static assets
├── api/
│   └── index.py               # the FastAPI app — Vercel calls this directly
├── backend/
│   ├── __init__.py
│   ├── models.py               # SQLAlchemy tables: User, Lead
│   ├── database.py              # DB access layer (explicit named functions)
│   ├── auth.py                   # password hashing + JWT session tokens
│   ├── schemas.py                  # Pydantic request validation
│   ├── dashboard_data.py            # mock portfolio data (same values as before)
│   ├── create_user.py                # CLI: provision/reset a login account
│   └── services/
│       ├── market_data.py              # placeholder for a future price feed
│       └── claude.py                    # placeholder for a future Claude integration
├── tests/
│   └── test_api.py           # pytest suite
├── requirements.txt            # production deps
├── requirements-dev.txt         # + pytest/httpx for local testing
├── vercel.json
├── .env.example
├── .gitignore
├── README.md                     # this file
├── data/  logs/                    # left over from the old Node backend — gitignored,
│                                     harmless, safe to delete whenever you like
└── _to_delete/                       # old Node backend files, moved (not deleted) — see above
```

## Serverless, explained (for a Python developer new to Vercel)

Vercel doesn't keep your Python process running the way `python app.py`
does on your own machine. Instead, it takes the `app` object your code
defines (a FastAPI instance — an ASGI application) and calls it directly,
per request, on whatever instance happens to be warm (or a brand-new one).
Concretely, that means:

- **No `app.listen()` / no port.** `uvicorn` is only for *your own machine*
  (`uvicorn api.index:app --reload`). Vercel never runs that command —
  it imports `api/index.py`, finds the `app` variable, and calls it as an
  ASGI callable itself.
- **No shared memory between requests.** Two requests might hit two
  completely different instances of your code with nothing in common.
  That's why login sessions here are signed JWT tokens in a cookie
  (`backend/auth.py`) rather than an in-memory or DB-backed session table —
  the token itself carries everything needed to verify who's logged in,
  so no server-side state has to persist between requests.
- **No writable filesystem** (outside `/tmp`, which is wiped between
  invocations and shouldn't be relied on either). That's the direct fix for
  the `/var/task/logs` crash: this backend never tries to create a log
  directory — it just uses normal `print()`/exceptions, which Vercel
  captures as your function's logs automatically.
- **No background jobs / scheduled tasks** run inside this app. Anything
  like that would need a separate mechanism (e.g. Vercel Cron, or an
  external worker) — out of scope here.

## Database, in Python terms

`backend/database.py` is the *only* file that touches the database
directly. Every other file calls one of its named functions:
`create_user`, `find_user_by_email`, `get_user_by_id`,
`update_user_password`, `list_users`, `create_lead`, `list_leads`,
`count_leads`. Nothing calls a function that doesn't exist — which is
exactly what the old `db.listUsers is not a function` crash was: code
calling a function that, in whatever got deployed, wasn't there.

It uses SQLAlchemy, pointed at whatever `DATABASE_URL` says:

- Locally, if you don't set `DATABASE_URL`, it defaults to a SQLite file
  (`sqlite:///./local.db`) — zero setup, good enough for development.
- In production, **set `DATABASE_URL` to a real Postgres connection
  string** (Vercel Postgres, Neon, Supabase, Railway — any of these work).
  Vercel's filesystem is not a place to keep a permanent SQLite file: it's
  wiped/rebuilt on every deploy and isn't shared across function instances,
  so SQLite there would silently lose data or behave inconsistently.

The old Node backend's `data/leads.db` (SQLite) is **not** automatically
migrated into the new database — it uses a different schema/library and
this backend starts fresh. If you need those old leads, they're still
sitting in `data/leads.db` (still on disk, untouched) and can be exported
with any SQLite browser if you ever want them.

## Authentication, in Python terms

- **Password hashing:** `backend/auth.py` uses Python's built-in
  `hashlib.scrypt` (no extra dependency) to hash passwords, and
  `hmac.compare_digest` to check them — this is a memory-hard hash
  designed to resist brute-forcing, and the same real algorithm family the
  old Node backend used (`crypto.scryptSync`), just written in Python.
  Plaintext passwords are never stored, ever.
- **Sessions:** logging in creates a signed JWT (`PyJWT`) containing the
  user's id/email/name and an expiry, stored in an `HttpOnly` cookie named
  `zw_session` (JavaScript can't read it, which protects it from XSS). The
  backend verifies that signature on every request to a protected route
  (`/api/me`, `/api/dashboard`) rather than looking anything up in a
  database — consistent with the serverless "no shared memory" constraint
  above.
  - **Trade-off worth knowing:** logging out clears the cookie, but the
    JWT itself would still be technically valid (if someone had captured
    it) until it naturally expires (`SESSION_TTL_HOURS`, default 168
    hours / 7 days). If you ever need true instant revocation, the
    upgrade path is a small `revoked_tokens` table checked alongside the
    signature — not built now because it wasn't asked for, but
    straightforward to add later.
- **No plaintext passwords, no password hashes sent to the frontend, no
  internal database ids sent to the frontend** — `/api/login` and
  `/api/me` return only `name` and `email`.

## API endpoints

| Method & path | Purpose | Success response | Failure response |
|---|---|---|---|
| `POST /api/leads` | "Get started" lead-capture form | `{"ok": true, "success": true, "status": "created", "message": "..."}` | `422` with `{"ok": false, "success": false, "message": "...", "errors": {...}}` |
| `POST /api/login` | Email + password sign-in | `{"ok": true, "success": true, "message": "...", "user": {"name", "email"}}` + sets `zw_session` cookie | `401` `{"ok": false, "success": false, "message": "Incorrect email or password."}` |
| `POST /api/logout` | Clears the session cookie | `{"ok": true, "success": true}` | — |
| `GET /api/me` | Who's currently signed in | `{"ok": true, "user": {"name", "email"}}` | `401` if not signed in |
| `GET /api/dashboard` | Mock portfolio data | `{"ok": true, "data": {...}}` | `401` if not signed in |
| `GET /api/healthz` | Liveness check | `{"ok": true}` | — |

Every response includes both `ok` and `success` with the same meaning —
the existing frontend JS already checks `data.ok`, and your spec asked for
`{"success": true/false, ...}`; this satisfies both without touching the
frontend's working logic.

## Routing (`vercel.json`)

```json
{
  "rewrites": [
    { "source": "/login", "destination": "/login.html" },
    { "source": "/dashboard", "destination": "/dashboard.html" },
    { "source": "/api/:path*", "destination": "/api/index" }
  ]
}
```

This is deliberately narrow — it does **not** rewrite everything to
`index.html` (which would break `/api/*`). `/login` and `/dashboard` map to
their static HTML files; everything under `/api/` reaches the FastAPI app
(`api/index` is Vercel's auto-generated name for the function built from
`api/index.py`), which does its own internal routing from there
(`/api/leads`, `/api/login`, etc.).

## Running locally

```bash
cd zoey-backend            # this project's folder
python -m venv .venv

# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements-dev.txt   # includes pytest for testing
cp .env.example .env
# open .env and set SECRET_KEY — generate one with:
python -c "import secrets; print(secrets.token_hex(32))"

pytest                       # run the test suite
uvicorn api.index:app --reload
# open http://127.0.0.1:8000
```

## Creating/updating a dashboard login account

There's no self-serve signup — same as before. Provision or reset an
account with:

```bash
python -m backend.create_user "email@example.com" "PASSWORD" "Full Name"
```

Re-running it for an email that already exists updates that account's
password instead of erroring. **Never hard-code a real email/password into
source** — always pass them on the command line like this, and never commit
`.env`.

To create a **production** account (Vercel can't run one-off scripts),
run this same command from your own machine with `DATABASE_URL`
temporarily set to your production Postgres string:

```bash
DATABASE_URL="<your-production-postgres-url>" python -m backend.create_user "email@example.com" "PASSWORD" "Full Name"
```

## Testing

`pytest` (in `tests/test_api.py`) covers: successful lead capture, missing
name, invalid email, invalid phone when one is supplied, phone/interest
being optional, duplicate-email upsert behavior, successful login (and that
the response never contains a password or password hash), incorrect
password, unknown email (same generic error message as wrong password —
deliberately, so an attacker can't tell which one it was), missing fields,
`/api/me` and `/api/dashboard` requiring login, and `/api/logout` actually
clearing the session.

This was also verified against a real running server (not just the test
suite): `uvicorn` was started, a real account was created via
`python -m backend.create_user`, and the homepage lead form, login page,
dashboard, and logout were driven through an actual browser end to end —
including confirming the dashboard renders identically to before.

## Deploying to Vercel

1. Commit and push (see Git commands below).
2. In the Vercel dashboard, open the project connected to this repo (or
   import it fresh if it isn't connected yet). Vercel auto-detects
   `api/index.py` as a Python serverless function — no build command
   needed, and no "Output Directory" setting needed either now that the
   static pages live at the repo root.
3. Under Project Settings → Environment Variables, add the variables in
   the table below.
4. Set `DATABASE_URL` to a real Postgres connection string (see "Database"
   above) — this is required for production; don't leave it unset there.
5. Create your production login account (see the command above), run from
   your own machine.
6. Deploy (push to the connected branch, or `vercel --prod`). Then verify
   directly against the live site: homepage loads, `/login` no longer
   404s, log in with the account you just created, `/dashboard` renders,
   log out, and re-visiting `/dashboard` bounces back to `/login`.

### Environment variables to set in Vercel

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | Yes | Postgres connection string in production. |
| `SECRET_KEY` | Yes | Signs the session cookie. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. The app refuses to start without it. |
| `SESSION_TTL_HOURS` | No | Default `168` (7 days). |
| `COOKIE_SECURE` | No | Default `true` — leave alone in production (Vercel serves HTTPS). |
| `RATE_LIMIT_MAX` | No | Default `5` login/lead-submit attempts per window per IP. |
| `RATE_LIMIT_WINDOW_MIN` | No | Default `10` minutes. |

`ADMIN_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, and `NOTIFY_TO` from the
old Node backend are **not** needed by this rewrite — the admin dashboard
and Gmail notifications weren't carried over (see "What changed" above).

## Git commands to commit this

```bash
git add -A
git commit -m "Migrate backend to Python/FastAPI for Vercel serverless"
git push
```
