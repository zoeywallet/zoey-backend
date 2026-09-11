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
    GET  /api/healthz          liveness check
    POST /api/leads            "Get started" form submissions
    POST /api/login            email + password -> sets the session cookie
    POST /api/logout           clears the session cookie
    GET  /api/me                who's currently logged in (401 if nobody)
    GET  /api/dashboard         mock portfolio data (401 if not logged in)

Local development also serves the static pages (index.html, login.html,
dashboard.html) directly from this same app, purely for convenience so
`uvicorn api.index:app --reload` is a complete local server on its own.
In production on Vercel, those files are served straight from the static
file host per vercel.json — this app is only ever invoked for /api/*
there, so the static routes below are simply unused (and harmless) in
production.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from pathlib import Path

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
from sqlalchemy.orm import Session  # noqa: E402

from backend.auth import (  # noqa: E402
    COOKIE_NAME,
    SESSION_TTL_HOURS,
    create_access_token,
    decode_access_token,
    verify_password,
)
from backend.dashboard_data import get_dashboard_data
from backend.database import create_lead, find_user_by_email, get_db, init_db
from backend.schemas import LeadIn, LoginIn

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
def api_dashboard(claims: dict | None = Depends(get_current_claims)):
    if claims is None:
        return JSONResponse(status_code=401, content={"ok": False, "message": "Not signed in."})
    return {"ok": True, "data": get_dashboard_data()}


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
