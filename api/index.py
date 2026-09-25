"""
The FastAPI application — this single module IS the backend. Vercel's
Python runtime finds the `app` object below and calls it directly as an
ASGI application (the same interface `uvicorn` uses to run it locally) —
there is no `app.listen()`, no port number, and no long-running process:
Vercel starts a fresh instance of this module, calls `app` once per
incoming request (or a short-lived batch of them on a warm instance), and
throws the instance away when it's done. That's what "serverless" means in
practice, and it's why backend/database.py never assumes anything is still
in memory between requests, and why sessions here are signed JWTs
(backend/auth.py) rather than a lookup table.

Routes:
    GET  /api/healthz                     liveness check
    POST /api/leads                       "Get started" form submissions
    POST /api/auth/signup                 real account creation (unverified) -> no session cookie yet
    GET  /api/auth/verify-email           emailed link target -> marks the account verified
    POST /api/auth/resend-verification    re-sends a fresh verification email
    POST /api/auth/google                 "Continue with Google" -> sets the session cookie
    POST /api/login                       email + password (must be verified) -> sets the session cookie
    POST /api/logout                      clears the session cookie
    GET  /api/me                           who's currently logged in (401 if nobody)
    GET  /api/dashboard                    the authenticated user's own account data from Neon (401 if not logged in)

Local development also serves the static pages (index.html, login.html,
dashboard.html) directly from this same app, purely for convenience so
`uvicorn api.index:app --reload` is a complete local server on its own.
In production on Vercel, those files are served straight from the static
file host per vercel.json — this app is only ever invoked for /api/*
there, so the static routes below are simply unused (and harmless) in
production.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import quote

# Load variables from a local .env file into os.environ, for local
# development only (the same job src/loadEnv.js did in the old Node
# backend). This MUST run before importing anything from backend/ below —
# those modules read os.environ.get(...) at *import time* (DATABASE_URL,
# SECRET_KEY, etc.), so if .env were loaded any later, this app would start
# up having already missed those values. On Vercel this call is a no-op:
# there is no .env file deployed, and Vercel injects real environment
# variables directly, before your code ever runs.
from dotenv import load_dotenv

load_dotenv()

from fastapi import Cookie, Depends, FastAPI, Request, Response  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.auth import (  # noqa: E402
    COOKIE_NAME,
    SESSION_TTL_HOURS,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from backend.dashboard_data import get_dashboard_data
from backend.database import (
    create_google_user,
    create_lead,
    create_user,
    find_user_by_email,
    find_user_by_google_sub,
    find_user_by_verification_token_hash,
    get_db,
    init_db,
    link_google_identity,
    set_email_verification_token,
    set_email_verified,
)
from backend.email_sender import send_verification_email
from backend.email_verification import generate_verification_token, hash_token, is_expired
from backend.google_auth import GOOGLE_CLIENT_ID, GoogleAuthError, verify_google_id_token
from backend.schemas import GoogleAuthIn, LeadIn, LoginIn, ResendVerificationIn, SignupIn

logger = logging.getLogger("zoey.api")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Zoey Wallet API")

# Tables are created (if missing) once, at module import time — this runs
# once per cold start, which is exactly the right frequency: cheap, and
# `CREATE TABLE IF NOT EXISTS` is a no-op on every subsequent warm
# invocation that reuses this same module instance.
init_db()


# ---------------------------------------------------------------------------
# Best-effort in-memory rate limiting
# ---------------------------------------------------------------------------
# Same sliding-window design as the previous Node backend, kept intentionally
# simple. Be upfront about its one real limitation on Vercel: this dict lives
# in one function instance's memory, and Vercel may run several instances of
# this app concurrently (or spin up a fresh one at any time), so a client
# COULD get more than RATE_LIMIT_MAX attempts by getting routed to different
# instances. For a low-traffic marketing site this is a reasonable
# trade-off; if you need airtight limits later, move this state into Redis
# (e.g. Upstash, which has a generous free tier and integrates with Vercel)
# so every instance shares the same counters.

def _env_number(name: str, default: float, *, cast):
    """Reads a numeric environment variable, falling back to `default` when
    it's absent, blank, or not a valid number -- a misconfigured value in
    Vercel's env vars should degrade to the default, not raise and crash
    the whole app at import time (this is what happened when RATE_LIMIT_MAX
    was set but not a valid integer)."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return cast(raw)
    except ValueError:
        return default


RATE_LIMIT_MAX = _env_number("RATE_LIMIT_MAX", 5, cast=int)
RATE_LIMIT_WINDOW_SECONDS = _env_number("RATE_LIMIT_WINDOW_MIN", 10, cast=float) * 60

_attempts: dict[str, deque] = defaultdict(deque)


def _rate_limited(key: str) -> bool:
    now = time.time()
    bucket = _attempts[key]
    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_MAX:
        return True
    bucket.append(now)
    return False


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def get_current_claims(zw_session: str | None = Cookie(default=None)) -> dict | None:
    """FastAPI dependency: decodes the session cookie (if any) and returns
    its claims dict, or None if there's no cookie / it's invalid / expired.
    Route handlers decide for themselves whether None means "401" (protected
    routes) — this dependency never raises on its own, it just reports."""
    return decode_access_token(zw_session)


def _set_session_cookie(response: Response, token: str, *, remember: bool) -> None:
    cookie_kwargs = dict(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE", "true").lower() != "false",
        path="/",
    )
    if remember:
        # Persistent cookie: survives closing the browser, for
        # SESSION_TTL_HOURS (same window the JWT itself is valid for).
        cookie_kwargs["max_age"] = int(SESSION_TTL_HOURS * 3600)
    response.set_cookie(**cookie_kwargs)


def _issue_and_send_verification_email(request: Request, db: Session, user) -> bool:
    """Generates a fresh verification token for `user`, stores its hash
    (see backend/email_verification.py + backend/database.py's
    set_email_verification_token), and emails the link. Returns whether the
    email was actually sent -- callers (signup, resend-verification) use
    this to decide what to tell the user, but NEVER to decide whether the
    request itself succeeded: account creation must not fail just because
    mail delivery is unavailable (e.g. SMTP_HOST/SMTP_USER/SMTP_PASSWORD/
    SMTP_FROM are still blank in this project's .env today -- see
    backend/email_sender.py).

    The verify URL is built from THIS request's own base_url (not a
    hardcoded/env-configured domain) so it's automatically correct in every
    environment this app runs in -- http://127.0.0.1:8000 locally,
    whatever preview/production domain Vercel serves it from later -- since
    vercel.json already routes every /api/* path (including this new one)
    to this same app in both places.
    """
    raw_token, token_hash, expires_at = generate_verification_token()
    set_email_verification_token(db, user, token_hash=token_hash, expires_at=expires_at)
    verify_url = f"{str(request.base_url).rstrip('/')}/api/auth/verify-email?token={quote(raw_token)}"
    return send_verification_email(to_email=user.email, name=user.name, verify_url=verify_url)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/api/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/api/leads")
async def api_create_lead(request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    if _rate_limited(f"leads:{ip}"):
        return JSONResponse(
            status_code=429,
            content={"ok": False, "success": False, "message": "Too many attempts. Please try again in a few minutes."},
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        lead_in = LeadIn.model_validate(body)
    except ValidationError as exc:
        # Turn Pydantic's error list into the {field: message} shape the
        # existing frontend already knows how to render as inline errors
        # (see index.html's submitLead()/catch handler).
        errors: dict[str, str] = {}
        for err in exc.errors():
            field = str(err["loc"][0]) if err.get("loc") else "form"
            errors.setdefault(field, err["msg"])
        return JSONResponse(
            status_code=422,
            content={"ok": False, "success": False, "message": "Please check the highlighted fields.", "errors": errors},
        )

    lead, is_new = create_lead(
        db,
        name=lead_in.name,
        email=lead_in.email,
        phone=lead_in.phone,
        interest=lead_in.interest,
        country=lead_in.country,
        country_code=lead_in.country_code,
        source=lead_in.source,
    )

    message = "You're on the list." if is_new else "You're already on the list — we've updated your info."
    return {
        "ok": True,
        "success": True,
        "status": "created" if is_new else "duplicate",
        "message": message,
    }


@app.get("/api/auth/config")
def api_auth_config() -> dict:
    """Tells the frontend (index.html/login.html) whether real Google
    sign-in is configured, and with which client ID -- fetched at page load
    instead of hardcoding GOOGLE_CLIENT_ID into the static HTML files, so
    the same deployed page works correctly in every environment (local,
    Vercel preview, Vercel production) without a manual per-environment
    HTML edit, exactly like GET /api/auth/verify-email already builds its
    link from the current request instead of a hardcoded domain.

    A Google OAuth client ID is not a secret -- Google's own documentation
    describes it as safe to expose in client-side code (it identifies
    which app is asking, not a credential that authorizes anything by
    itself); see backend/google_auth.py's own docstring. An empty string
    means Google sign-in isn't configured yet, and the frontend shows its
    existing "isn't connected yet" fallback button instead.
    """
    return {"googleClientId": GOOGLE_CLIENT_ID}


@app.post("/api/auth/signup")
async def api_auth_signup(request: Request, response: Response, db: Session = Depends(get_db)):
    """Creates a real login account from the homepage's "Create your Zoey
    account" modal.

    IMPORTANT: this does NOT authenticate the new user. The account is
    created with email_verified=False (see backend/database.create_user's
    default) and a verification email is sent, but no session cookie is
    ever set here -- POST /api/login already refuses to authenticate an
    unverified email/password account (see its "Please verify your email
    before signing in." gate), so auto-logging in here would just hand out
    a session that /api/me and /api/dashboard would otherwise never accept
    for this same account yet. The person must click the emailed
    verification link and then log in normally, same as any other
    unverified account.

    This is a distinct endpoint from /api/leads on purpose -- the waitlist
    form's existing behavior (upsert-by-email into `leads`, no password)
    must keep working completely unchanged. This endpoint only ever writes
    to the `users` table; it never reads or writes `leads` at all, so an
    existing waitlist submission is untouched (and not required) for a new
    account to be created here.
    """
    ip = _client_ip(request)
    if _rate_limited(f"signup:{ip}"):
        return JSONResponse(
            status_code=429,
            content={"ok": False, "success": False, "message": "Too many attempts. Please try again in a few minutes."},
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        signup_in = SignupIn.model_validate(body)
    except ValidationError as exc:
        # Same {field: message} error shape /api/leads already uses, so the
        # existing frontend error-rendering code can be reused as-is.
        errors: dict[str, str] = {}
        for err in exc.errors():
            field = str(err["loc"][0]) if err.get("loc") else "form"
            errors.setdefault(field, err["msg"])
        return JSONResponse(
            status_code=422,
            content={"ok": False, "success": False, "message": "Please check the highlighted fields.", "errors": errors},
        )

    # Checked up front so a duplicate email gets a clear, specific error
    # (rather than a generic 500) in the common case. The unique constraint
    # on User.email (see backend/models.py) is still the real guarantee --
    # the IntegrityError handler below catches the rare race where two
    # signups for the same email land at almost the same instant.
    if find_user_by_email(db, signup_in.email) is not None:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "success": False,
                "message": "An account with this email already exists. Try logging in instead.",
                "errors": {"email": "An account with this email already exists."},
            },
        )

    password_hash = hash_password(signup_in.password)
    try:
        user = create_user(
            db,
            email=signup_in.email,
            name=signup_in.name,
            password_hash=password_hash,
            phone=signup_in.phone,
            interests=signup_in.interest,
        )
    except IntegrityError:
        db.rollback()
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "success": False,
                "message": "An account with this email already exists. Try logging in instead.",
                "errors": {"email": "An account with this email already exists."},
            },
        )

    # Deliberately NOT auto-authenticated: no create_access_token /
    # _set_session_cookie call here. The account is created with
    # email_verified=False (create_user's default), and POST /api/login
    # already refuses to authenticate an unverified email/password account
    # -- so issuing a session cookie here would leave the browser holding a
    # cookie that represents an account /api/login itself wouldn't yet
    # allow in, and /api/me / /api/dashboard would suddenly need their own
    # separate opinion about it. The single source of truth for "is this
    # session allowed" stays POST /api/login's existing gate. The person
    # verifies their email, then logs in normally, same as any other
    # unverified account (see TestSignupDoesNotAutoLogin in
    # tests/test_api.py for the exact contract this endpoint promises).
    email_sent = _issue_and_send_verification_email(request, db, user)
    message = (
        "Account created. We've sent a verification link to your email. "
        "Please verify your email before signing in."
        if email_sent
        else "Account created, but we couldn't send the verification email. "
        "You can request a new one anytime from the login page, then verify "
        "before signing in."
    )

    return {
        "ok": True,
        "success": True,
        "message": message,
        "verification_email_sent": email_sent,
        "requires_verification": True,
        "user": {"name": user.name, "email": user.email},
    }


@app.get("/api/auth/verify-email")
async def api_auth_verify_email(request: Request, token: str = "", db: Session = Depends(get_db)):
    """The link target inside the verification email
    (_issue_and_send_verification_email above). Never returns raw JSON to
    the browser here -- this is always reached by a person clicking a link
    in their inbox, so it redirects to the existing login page with a
    query param, and login.html (unchanged in layout, see task #48) shows a
    small banner from it -- no new page to build, nothing about the login
    page's design changes.

    Three distinct outcomes, each a different query param, matching the
    task's required distinct copy:
      - ?verified=1        newly verified just now
      - ?verify_error=expired        token found, but past its expiry
      - ?verify_error=used_or_invalid    token not found at all (already
        used and cleared by a previous click, superseded by a later resend,
        or simply never existed / was tampered with) -- these are
        indistinguishable from each other by design (see
        find_user_by_verification_token_hash's own docstring), so they
        share the "Your email is already verified." message, which is
        accurate for the common real case and harmless otherwise.
    """
    ip = _client_ip(request)
    if _rate_limited(f"verify-email:{ip}"):
        return Response(status_code=302, headers={"Location": "/login?verify_error=rate_limited"})

    if not token:
        return Response(status_code=302, headers={"Location": "/login?verify_error=used_or_invalid"})

    token_hash = hash_token(token)
    user = find_user_by_verification_token_hash(db, token_hash)
    if user is None:
        return Response(status_code=302, headers={"Location": "/login?verify_error=used_or_invalid"})

    if is_expired(user.email_verify_expires_at):
        return Response(status_code=302, headers={"Location": "/login?verify_error=expired"})

    set_email_verified(db, user)
    return Response(status_code=302, headers={"Location": "/login?verified=1"})


@app.post("/api/auth/resend-verification")
async def api_auth_resend_verification(request: Request, db: Session = Depends(get_db)):
    """Re-sends a fresh verification email. Always returns the SAME
    generic success message regardless of whether the address belongs to
    an account, is already verified, or is a Google-only account -- the
    same non-enumeration principle /api/login already uses for "incorrect
    email or password" (see that endpoint's own comment), extended here so
    this endpoint can't be used to probe which emails have Zoey accounts.
    """
    ip = _client_ip(request)
    if _rate_limited(f"resend-verification:{ip}"):
        return JSONResponse(
            status_code=429,
            content={"ok": False, "success": False, "message": "Too many attempts. Please try again in a few minutes."},
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        resend_in = ResendVerificationIn.model_validate(body)
    except ValidationError:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "success": False, "message": "Enter a valid email address."},
        )

    generic_response = {
        "ok": True,
        "success": True,
        "message": "If an account with that email exists and isn't verified yet, we've sent a new verification link.",
    }

    user = find_user_by_email(db, resend_in.email)
    if user is not None and not user.email_verified:
        _issue_and_send_verification_email(request, db, user)
        # Deliberately not branching the response on whether the send
        # itself succeeded -- doing so would let a caller distinguish
        # "exists and unverified" from "doesn't exist" by watching for a
        # delivery-failure message, defeating the whole point of this
        # generic response.

    return generic_response


@app.post("/api/auth/google")
async def api_auth_google(request: Request, response: Response, db: Session = Depends(get_db)):
    """"Continue with Google" -- verifies the credential Google's Identity
    Services JS library handed the frontend (backend/google_auth.py does
    the actual signature/issuer/audience/expiry verification), then finds
    or creates the matching Zoey user and issues the SAME kind of session
    cookie /api/login and /api/auth/signup already issue -- there is no
    separate "Google session" system.

    Account matching, in order (see backend/database.py for each):
      1. An existing user already linked to this exact Google account
         (google_sub) -- the common case for a returning Google user.
      2. An existing email/password account whose email matches Google's
         OWN VERIFIED email claim -- linked (not duplicated) via
         link_google_identity. Never linked on an unverified Google email
         claim (checked below) -- see this project's security requirements
         for why.
      3. Otherwise, a brand-new Google-only account (no Zoey password).
    """
    ip = _client_ip(request)
    if _rate_limited(f"google-auth:{ip}"):
        return JSONResponse(
            status_code=429,
            content={"ok": False, "success": False, "message": "Too many attempts. Please try again in a few minutes."},
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        google_in = GoogleAuthIn.model_validate(body)
    except ValidationError:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "success": False, "message": "We couldn't complete Google sign-in. Please try again."},
        )

    try:
        identity = verify_google_id_token(google_in.credential)
    except GoogleAuthError as exc:
        # The specific reason (bad signature, wrong audience, expired,
        # server not configured, package missing) is for server-side logs
        # only -- the user only ever sees the one generic message, same
        # posture as backend/email_sender.py's SMTP errors.
        logger.warning("POST /api/auth/google: verification failed: %s", exc)
        return JSONResponse(
            status_code=401,
            content={"ok": False, "success": False, "message": "We couldn't complete Google sign-in. Please try again."},
        )

    if not identity.email_verified:
        # Google itself is telling us it cannot vouch for this address --
        # never create or link an account off the back of that. This is
        # rare in practice (most Google accounts have a verified email),
        # but the one case this actually protects against is real: linking
        # or creating a Zoey account on an email Google won't stand behind.
        logger.warning("POST /api/auth/google: Google reported email_verified=False for sub=%s", identity.sub)
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "success": False,
                "message": "Google couldn't verify your email address. Try signing up with email and password instead.",
            },
        )

    user = find_user_by_google_sub(db, identity.sub)
    if user is None:
        existing_by_email = find_user_by_email(db, identity.email)
        try:
            if existing_by_email is not None:
                user = link_google_identity(db, existing_by_email, identity.sub)
            else:
                user = create_google_user(db, email=identity.email, name=identity.name, google_sub=identity.sub)
        except IntegrityError:
            # Rare race: two concurrent Google sign-ins for the same brand
            # new account, or a google_sub that got linked elsewhere a
            # moment ago. Roll back and re-read rather than guessing.
            db.rollback()
            user = find_user_by_google_sub(db, identity.sub)
            if user is None:
                logger.exception("POST /api/auth/google: IntegrityError with no resolvable user for sub=%s", identity.sub)
                return JSONResponse(
                    status_code=401,
                    content={"ok": False, "success": False, "message": "We couldn't complete Google sign-in. Please try again."},
                )

    token = create_access_token(user_id=user.id, email=user.email, name=user.name, remember=True)
    _set_session_cookie(response, token, remember=True)

    return {
        "ok": True,
        "success": True,
        "message": "Signed in with Google.",
        "user": {"name": user.name, "email": user.email},
    }


@app.post("/api/login")
async def api_login(request: Request, response: Response, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    if _rate_limited(f"login:{ip}"):
        return JSONResponse(
            status_code=429,
            content={"ok": False, "success": False, "message": "Too many attempts. Please try again in a few minutes."},
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        login_in = LoginIn.model_validate(body)
    except ValidationError:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "success": False, "message": "Enter a valid email and password."},
        )

    user = find_user_by_email(db, login_in.email)
    # Same generic message whether the email doesn't exist or the password
    # is wrong — never reveal which one it was (that would let an attacker
    # enumerate real accounts by trying emails one at a time).
    generic_failure = JSONResponse(
        status_code=401,
        content={"ok": False, "success": False, "message": "Incorrect email or password."},
    )
    if user is None:
        return generic_failure
    if not verify_password(login_in.password, user.password_hash):
        return generic_failure

    # Email/password accounts must verify their address before they can
    # authenticate into the dashboard -- checked only AFTER the password
    # has already been confirmed correct (so this can never be used to
    # probe which emails have Zoey accounts; someone who doesn't already
    # know the password sees the same generic "Incorrect email or
    # password." above, same as always). This does not apply to Google
    # sign-in at all: POST /api/auth/google never calls this function, and
    # every Google-authenticated account already starts email_verified=True
    # the moment it's created/linked (see backend/database.py's
    # create_google_user / link_google_identity).
    if not user.email_verified:
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "success": False,
                "message": "Please verify your email before signing in.",
            },
        )

    token = create_access_token(user_id=user.id, email=user.email, name=user.name, remember=login_in.remember)
    _set_session_cookie(response, token, remember=login_in.remember)

    # Deliberately excludes password_hash and the internal integer id —
    # only what the frontend actually needs to render (name, email).
    return {"ok": True, "success": True, "message": "Logged in successfully.", "user": {"name": user.name, "email": user.email}}


@app.post("/api/logout")
def api_logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True, "success": True}


@app.get("/api/me")
def api_me(claims: dict | None = Depends(get_current_claims)):
    if claims is None:
        return JSONResponse(status_code=401, content={"ok": False, "message": "Not signed in."})
    return {"ok": True, "user": {"name": claims.get("name"), "email": claims.get("email")}}


@app.get("/api/dashboard")
def api_dashboard(claims: dict | None = Depends(get_current_claims), db: Session = Depends(get_db)):
    """Returns the CURRENTLY AUTHENTICATED user's own dashboard data --
    never a shared/demo fixture. Identity comes only from the signed
    session cookie's claims (get_current_claims) -- never from anything
    the browser could supply directly -- so this can never return one
    user's data to a different user. See backend/dashboard_data.py for
    why every financial figure here is either real (queried from Neon) or
    honestly zero/empty; DriveWealth is not integrated yet, so nothing
    here is invented.
    """
    if claims is None:
        return JSONResponse(status_code=401, content={"ok": False, "message": "Not signed in."})
    try:
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError):
        # A validly-issued session token always has an integer `sub` (see
        # backend/auth.py's create_access_token) -- this only guards
        # against a malformed/foreign token slipping past decode_access_token,
        # the same defensive posture as this app's other claims consumers.
        return JSONResponse(status_code=401, content={"ok": False, "message": "Not signed in."})
    return {"ok": True, "data": get_dashboard_data(db, user_id)}


# ---------------------------------------------------------------------------
# Local-dev-only static routes (see module docstring — unused in production)
# ---------------------------------------------------------------------------

def _serve(filename: str) -> FileResponse:
    return FileResponse(PROJECT_ROOT / filename)


@app.get("/")
def serve_index():
    return _serve("index.html")


@app.get("/login")
def serve_login(claims: dict | None = Depends(get_current_claims)):
    if claims is not None:
        return Response(status_code=302, headers={"Location": "/dashboard"})
    return _serve("login.html")


@app.get("/dashboard")
def serve_dashboard(claims: dict | None = Depends(get_current_claims)):
    if claims is None:
        return Response(status_code=302, headers={"Location": "/login"})
    return _serve("dashboard.html")


_assets_dir = PROJECT_ROOT / "assets"
if _assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")
