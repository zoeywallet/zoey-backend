# Zoey Wallet — Backend

Connects the Zoey Wallet website's existing "Get started" lead form to a
real database and a Gmail notification, without changing anything about
how the form looks or behaves — and adds a dedicated Login page + User
Dashboard behind real, server-side session authentication.

```
Website Lead Form  →  Backend/API  →  SQLite Database  →  Gmail Notification

Homepage "Log In"  →  /login (dedicated page)  →  session cookie  →  /dashboard
```

## What was already there, and what this adds

The site (`public/index.html`, same file as `zoeywalletwebsitev2.html`)
already had a fully-built lead form — name, email, phone (with country
selector), and an optional "what are you interested in" field — with
client-side validation, a loading state, and a success state. Its JavaScript
already called a `submitLead()` function that POSTed JSON to
`` `${ZOEY_LEADS_API_BASE}/api/leads` `` and expected back `{ ok, status,
message }` on success, `{ ok:false, errors:{...} }` on a 422 validation
failure, or a 429 on rate-limiting. **There was no backend behind it yet** —
`ZOEY_LEADS_API_BASE` was blank, so every submission failed with an
on-brand "couldn't reach our servers" message and nothing was ever stored.

This project *is* that backend, built to the exact contract the frontend
already expected — so the only frontend change needed was flipping on the
fetch call (a few lines in one `<script>` block; see "Frontend change"
below). No HTML, CSS, layout, copy, or animation changed.

## Why zero (well, one) npm dependencies

This was built in a sandboxed environment whose egress policy blocked
`registry.npmjs.org` entirely (every package request came back `403`,
including trivial ones like `lodash`) but allowed plain `git clone` against
`github.com`. So:

- The server, router, SQLite access, validation, rate limiting, admin auth,
  and CSV export are all written on Node's built-in modules
  (`node:http`, `node:sqlite`, `node:crypto`, `node:fs`) — nothing to
  install for any of that.
- The one place a battle-tested library matters — Gmail SMTP + MIME — uses
  **Nodemailer**, vendored directly from its GitHub source
  (`nodemailer@6.9.15`, the last version published as plain CommonJS with
  no build step, and it has zero dependencies of its own) into
  `node_modules/nodemailer` so this runs as-is.

On a normal host with normal registry access, you can ignore all of that and
just run `npm install` — `package.json` lists `nodemailer` as a real
dependency and npm will fetch the genuine published package the normal way.
The vendored copy is only there so this project runs immediately without
that step.

**Node version:** requires **Node.js 22.5 or newer** (for `node:sqlite`).
Run `node --version` to check. If you're on an older Node, the fix is
either upgrading Node, or swapping `src/db.js` to use `better-sqlite3` from
npm instead (same API shape — `db.prepare(...).run()/.get()/.all()`).

## Setup

### 1. Install

```bash
cd zoey-backend
npm install     # fetches the real nodemailer from npm; harmless if it
                 # can't reach the registry, since a working copy is
                 # already vendored in node_modules/
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Then edit `.env`. At minimum, for leads to actually save and an admin
dashboard to exist:

```
ADMIN_KEY=<any long random string>
```

Generate one with:

```bash
node -e "console.log(require('crypto').randomBytes(24).toString('hex'))"
```

For Gmail notifications (App Password method — see below for why):

```
GMAIL_USER=youraddress@gmail.com
GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
NOTIFY_TO=youraddress@gmail.com
```

**Getting a Gmail App Password (~2 minutes):**

1. Turn on 2-Step Verification on the Google account you want to send
   from: <https://myaccount.google.com/security>
2. Go to <https://myaccount.google.com/apppasswords>
3. Create a new app password (name it something like "Zoey Wallet
   backend"). Google shows you a 16-character password once — copy it.
4. Paste it into `GMAIL_APP_PASSWORD` in `.env` (spaces are fine, they're
   stripped automatically). Paste the Gmail address itself into
   `GMAIL_USER`.
5. Set `NOTIFY_TO` to whichever inbox should receive lead notifications —
   it can be the same address, or a different one entirely.

If you'd rather use OAuth2 (Client ID / Secret / Refresh Token) instead of
an App Password — more setup, but avoids storing a password at all — see
"Switching to OAuth2" near the bottom.

**Until Gmail is configured, nothing breaks** — leads still save correctly,
the mailer just logs a warning and marks the notification
`skipped_no_credentials`. As soon as you add real credentials and restart,
the next lead (or the background retry sweep, or a manual resend) will send
successfully.

### 3. Run it

```bash
npm start
```

By default this serves **both** the website and the API on
`http://localhost:3001` — open that URL, click "Get started," submit the
form, and it will hit the same-origin `/api/leads` endpoint.

### 4. View collected leads

```
http://localhost:3001/admin?key=<your ADMIN_KEY>
```

Shows every lead, their notification status, and a "Resend" button for
any that haven't successfully notified you yet. There's also a CSV export
link on that page, or directly at:

```
http://localhost:3001/api/leads/export.csv?key=<your ADMIN_KEY>
```

(The key can also be sent as an `X-Admin-Key` header or `Authorization:
Bearer <key>` header instead of a query string, if you're scripting
against it.)

## Deploying

This is a single Node process with a single SQLite file — it runs anywhere
that runs Node 22.5+: a small VPS, Render, Railway, Fly.io, an EC2/Lightsail
instance, etc. A few things to know:

- **Persistent disk matters.** SQLite lives at `LEADS_DB_PATH`
  (`./data/leads.db` by default). On a platform with an ephemeral
  filesystem (some serverless/container platforms wipe disk on redeploy),
  point `LEADS_DB_PATH` at a mounted persistent volume, or your leads will
  vanish on the next deploy.
- **Outbound SMTP (port 465) must be allowed.** Gmail's App Password
  method sends over `smtp.gmail.com:465`. Most VPS/PaaS hosts allow this;
  a few free-tier serverless platforms block outbound SMTP ports
  specifically to fight spam. If yours does, you'll see notification
  emails fail with a connection error — the "Switching to OAuth2" section
  below doesn't fix that specific problem (OAuth2 still uses SMTP for
  Nodemailer), so on a host that blocks SMTP entirely you'd need the Gmail
  **API** (HTTPS, not SMTP) with OAuth2, which is a further step up in
  complexity — ask if you hit this and want it built.
- **Set `APP_BASE_URL`** to your real deployed URL — it's used to build
  the "View all leads" link inside notification emails.
- Copy your `.env` values into the platform's environment-variable
  settings (never commit `.env` — it's already gitignored).

### If the frontend is hosted separately from this backend

The recommended setup serves `public/index.html` (the site) and the API
from this same process, so there's no cross-origin request at all. If you
instead host the HTML elsewhere (e.g. a static host or CDN) and only run
this backend for the API:

1. Set `ALLOWED_ORIGIN` in this backend's `.env` to the site's real origin
   (e.g. `https://zoeywallet.com`).
2. In the site's HTML, find `const ZOEY_LEADS_API_BASE = '';` (inside the
   `<script>` block, in the "Submission layer" section) and set it to this
   backend's URL, e.g. `'https://api.zoeywallet.com'`.

## How a submission flows through the system

1. **Frontend validates** (existing behavior, unchanged) — name, email,
   and phone format are checked client-side before the request is even
   sent, purely for instant UX feedback.
2. **POST `/api/leads`** — the visitor's browser sends the same JSON
   payload the form already built (`name`, `email`, `phone_e164`,
   `country`, `country_code`, `interest`, `source`, `submitted_at`).
3. **Rate limit check** — max 5 submissions per 10 minutes per IP by
   default (`RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW_MIN`), keyed by a salted
   hash of the IP (the raw IP is never stored).
4. **Server-side validation** (`src/validate.js`) — re-checks everything
   the browser checked, because browser checks are trivially bypassable.
   A failure returns `422` with the same `{errors:{name,email,phone}}`
   shape the frontend already knows how to render as inline field errors.
5. **Database write** (`src/db.js`, SQLite, table `leads`) — if this
   fails, the visitor gets a generic error and **the lead is not
   considered submitted**, full stop. If the email address already
   exists, the existing row is updated (latest info wins) and
   `duplicate_count` increments, rather than creating a second row.
6. **Gmail notification** — sent only after the database write succeeds.
   If this fails, the lead **stays saved** (nothing is rolled back or
   deleted); the failure is logged, `notification_status` is set to
   `failed`, and it becomes eligible for automatic retry (see below). The
   visitor still sees the normal success screen — an internal email
   hiccup is never their problem.
7. **Success response** — `{ ok:true, status:'created'|'duplicate',
   message:"You're on the list." }`, which is exactly what the existing
   frontend code expects to swap the modal into its existing success
   state.

## Duplicate and invalid submissions

- **Invalid email / name / phone** → `422` with field-level errors, no
  database write, no email.
- **Duplicate email** → not rejected (a returning visitor shouldn't see an
  error) — the existing lead row is updated with whatever new info came
  in, `duplicate_count` increments, and by default **no second
  notification email is sent** for a lead you were already successfully
  told about (so your inbox doesn't get spammed by someone submitting the
  form five times). The one exception: if the *previous* attempt(s) never
  actually reached your inbox (still `pending`, `failed`, or
  `skipped_no_credentials`), a resubmission is treated as a natural retry
  opportunity and a notification is attempted again.

## If the Gmail notification fails

This is handled deliberately, per the requirement that a saved lead must
never be lost or hidden just because an email didn't go out:

- The lead **stays in the database** either way.
- The failure (and the error message) is logged to `logs/app-YYYY-MM-DD.log`
  and to stdout.
- The lead's row gets `notification_status = 'failed'` and
  `notification_last_error` set, visible on the `/admin` dashboard.
- **Automatic retry:** a background sweep runs every `RETRY_INTERVAL_MIN`
  minutes (15 by default) inside the running server, retrying every lead
  whose notification hasn't succeeded yet, up to `RETRY_MAX_ATTEMPTS`
  attempts (5 by default).
- **Manual retry:** click "Resend" next to any such lead on `/admin`, or
  run `npm run retry-failed` as a one-off (e.g. from a cron job hitting a
  long-running deployment, or just by hand after fixing a credentials
  typo).
- Visitors never see any of this — no technical error, no credential
  detail, nothing beyond the same generic "something went wrong, try
  again" copy the form already had for network failures.

## Security

- No Gmail credentials, API keys, or admin keys anywhere in
  `public/index.html`, its JavaScript, or any other browser-reachable
  file. Everything sensitive is read from environment variables inside
  `src/`, which only ever runs server-side.
- `.env` is gitignored. `.env.example` documents every variable with no
  real values.
- `/admin`, `GET /api/leads`, `/api/leads/export.csv`, and the resend
  endpoint all require `ADMIN_KEY` — with nothing configured, they fail
  closed (return `401`) rather than defaulting open.
- The admin key comparison uses `crypto.timingSafeEqual` to avoid leaking
  timing information.
- Submitter IPs are only ever stored as a salted SHA-256 hash
  (`ip_hash` column), never in the clear.
- All lead input is validated and length-capped server-side before it
  touches the database or an email.
- Same rules apply to auth: no password, hash, session token, or admin key
  ever appears in any file the browser downloads. See the dedicated
  section below for the auth-specific details.

## Login, sessions & dashboard

A completely separate login page (`/login`) and authenticated dashboard
(`/dashboard`) sit alongside the lead-capture system above, sharing the same
process, same SQLite file, and same visual design tokens — but a fully
independent, real (not simulated) authentication path.

### How it works

- **Passwords** are never stored in plain text. `src/auth/password.js`
  hashes them with Node's built-in `crypto.scryptSync` and stores them as
  `scrypt:N:r:p:<saltHex>:<hashHex>` in the `users` table — the cost
  parameters travel with the hash so they can be tuned later without
  breaking existing accounts. Verification uses
  `crypto.timingSafeEqual`, not `===`, to avoid leaking timing
  information.
- **Sessions, not JWTs.** On successful login, `src/auth/session.js`
  generates an opaque 32-byte random token, stores it server-side in a
  `sessions` table (joined to `users`), and sends the browser only an
  `HttpOnly; SameSite=Lax` cookie (`zw_session`) containing that token.
  Client-side JavaScript can never read this cookie — there is nothing in
  `localStorage`, `sessionStorage`, or the page source to steal. Checking
  "Remember me" sets a persistent `Max-Age` (`SESSION_TTL_HOURS`, 7 days by
  default) on the cookie; leaving it off makes the cookie session-only in
  the browser, while the server-side session itself is still valid for the
  same window either way (so closing the tab doesn't silently log people
  out server-side — only closing the browser without "remember me" does).
- **Route gating happens on the server**, not just in the page's
  JavaScript, so it can't be bypassed by disabling JS: `GET /login` and
  `GET /dashboard` are handled specially in `src/server.js` before the
  static-file fallback. An unauthenticated visitor to `/dashboard` gets a
  `302` to `/login`; an already-authenticated visitor to `/login` gets a
  `302` to `/dashboard`. `dashboard.html`'s own JS adds a second,
  belt-and-suspenders check (`GET /api/auth/me`) on load, mainly to catch a
  stale bfcache view right after logging out.
- **No self-serve signup yet** (out of scope per the spec this was built
  from — "Sign Up" on the homepage still points at the existing
  onboarding flow, untouched). Accounts are created with a CLI instead:

  ```bash
  npm run create-user -- someone@example.com "a strong password" "Display Name"
  # or: node src/createUser.js someone@example.com "a strong password" "Display Name"
  ```

  Re-running it for an existing email updates that user's password (also
  useful for resetting one by hand). It refuses passwords under 8
  characters and obviously-invalid emails.

- **Dashboard data is currently mock data** (`src/dashboardData.js`) —
  portfolio value, holdings (NVDA/TSLA/PLTR/AMD/MSFT), a chart series, and
  USDT/USDC balances — served from `GET /api/dashboard` (auth required,
  `401` without a valid session). Swapping in real portfolio data later
  means editing that one file's return shape; nothing else needs to
  change. Nav items other than "Overview" (Markets, Portfolio,
  Transactions, Watchlist, Settings) and the Buy/Sell/Deposit buttons are
  intentionally inert placeholders that show a "coming soon" toast —
  they're real UI, just not wired to anything yet.

### Routes this adds

| Route | Method | Behavior |
|---|---|---|
| `/login` | GET | Serves `public/login.html`. Redirects to `/dashboard` if already authenticated. |
| `/dashboard` | GET | Serves `public/dashboard.html`. Redirects to `/login` if not authenticated. |
| `/api/auth/login` | POST | `{ email, password, remember }` → sets session cookie, `{ ok:true, user }`, or `401` with a generic "Incorrect email or password." (rate-limited like `/api/leads`). |
| `/api/auth/logout` | POST | Destroys the server-side session and clears the cookie. |
| `/api/auth/me` | GET | `{ ok:true, user }` if authenticated, else `401`. |
| `/api/dashboard` | GET | Mock portfolio/holdings/stablecoin data. `401` without a valid session. |

### Environment variables

No new required variables beyond what the lead-capture system already
uses:

- `SESSION_TTL_HOURS` (optional, default `168` = 7 days) — how long a
  session stays valid server-side either way.
- `COOKIE_SECURE` (optional; `true`/`false`) — forces the `Secure` flag on
  the session cookie. Left unset, it defaults to on when the request looks
  HTTPS (respecting `TRUST_PROXY`, the same flag the rate limiter already
  uses for `X-Forwarded-For`) and off for plain local HTTP so `npm start`
  works out of the box over `http://localhost`.

### Regenerating login.html / dashboard.html

`build_login_page.py` and `build_dashboard_page.py` are source-of-truth
generators kept around so the pages can be regenerated consistently (they
embed a large inline logo SVG) — edit the Python source and re-run it
rather than hand-editing the generated HTML, so the two stay in sync.

### Testing this part by hand

```bash
npm run create-user -- you@example.com "a-real-password" "Your Name"
npm start
# visit http://localhost:3001/login
```

- [ ] Visiting `/dashboard` while logged out redirects to `/login`.
- [ ] Wrong password shows "Incorrect email or password." without
      revealing which field was wrong, and without claiming a filled-in
      field is empty or malformed.
- [ ] Correct login redirects to `/dashboard` and shows your name, animated
      portfolio value/chart, holdings, and stablecoin balances.
- [ ] Visiting `/login` while already logged in redirects straight to
      `/dashboard`.
- [ ] "Log out" (desktop profile menu or mobile menu) clears the session
      and redirects to `/login`; `/dashboard` immediately redirects again.
- [ ] View page source / devtools on `/login` and `/dashboard` → no
      password hash, session token, or any other secret ever appears.

## File map

```
zoey-backend/
├── public/
│   ├── index.html              # the site (same as zoeywalletwebsitev2.html)
│   ├── login.html               # dedicated login page (generated — see below)
│   └── dashboard.html           # authenticated dashboard (generated — see below)
├── src/
│   ├── server.js                # http server, routing, static file serving
│   ├── db.js                    # SQLite schema + queries (node:sqlite) — leads, users, sessions
│   ├── validate.js              # server-side input validation (leads)
│   ├── mailer.js                # Gmail sending (Nodemailer, App Password)
│   ├── render/
│   │   ├── emailTemplate.js     # the notification email's subject/text/html
│   │   └── adminDashboard.js    # the /admin page's HTML
│   ├── csv.js                   # CSV export
│   ├── rateLimit.js             # in-memory sliding-window rate limiter
│   ├── adminAuth.js             # ADMIN_KEY check for admin-only routes
│   ├── retryFailedNotifications.js  # retry sweep, used by server + CLI
│   ├── logger.js                # console + logs/app-*.log
│   ├── loadEnv.js               # minimal .env parser
│   ├── auth/
│   │   ├── password.js          # scrypt hashing + timing-safe verification
│   │   └── session.js           # session tokens, cookie set/parse/clear
│   ├── dashboardData.js         # mock portfolio/holdings/stablecoin data
│   └── createUser.js            # CLI: create or reset a login account
├── build_login_page.py          # generates public/login.html (dev-time tool)
├── build_dashboard_page.py      # generates public/dashboard.html (dev-time tool)
├── data/                        # leads.db lives here (gitignored) — also holds users/sessions tables
├── logs/                        # app-*.log files (gitignored)
├── .env.example
└── package.json
```

## Switching to OAuth2 (optional)

If you'd rather not store a password at all, Nodemailer supports Gmail via
OAuth2 too. It's more setup:

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project, enable the Gmail API, and configure an OAuth consent screen.
2. Create an OAuth Client ID (type "Desktop app" is easiest for generating
   a refresh token by hand).
3. Use Google's [OAuth 2.0 Playground](https://developers.google.com/oauthplayground)
   with your own Client ID/Secret (gear icon → "Use your own OAuth
   credentials") to authorize the `https://mail.google.com/` scope and
   obtain a refresh token.
4. In `src/mailer.js`, change the `nodemailer.createTransport({...})` call
   from the current SMTP/App-Password config to:
   ```js
   nodemailer.createTransport({
     service: 'gmail',
     auth: {
       type: 'OAuth2',
       user: process.env.GMAIL_USER,
       clientId: process.env.GMAIL_CLIENT_ID,
       clientSecret: process.env.GMAIL_CLIENT_SECRET,
       refreshToken: process.env.GMAIL_REFRESH_TOKEN,
     },
   })
   ```
5. Set `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN`
   in `.env` instead of `GMAIL_APP_PASSWORD`.

## Testing checklist

- [ ] `npm start`, open `http://localhost:3001`, submit the form with a
      real-looking name/email/phone → see the existing success screen.
- [ ] Row appears at `http://localhost:3001/admin?key=...`.
- [ ] With `GMAIL_USER`/`GMAIL_APP_PASSWORD`/`NOTIFY_TO` set, the
      notification email arrives with the correct name/email/country/
      interest/timestamp.
- [ ] Submit the same email twice → only one row (with `duplicate_count`
      incremented), only one notification email.
- [ ] Submit an invalid email → inline field error, nothing saved.
- [ ] Submit 6+ times quickly → 429 after the 5th.
- [ ] View page source / devtools network tab on the live site → no Gmail
      address, password, or admin key ever appears in any HTML, JS, or
      response the browser can see.
