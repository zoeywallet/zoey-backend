"""
Tests for the FastAPI backend. Run with:

    pytest

(from the project root, with your virtualenv active and requirements-dev.txt
installed). This uses FastAPI's TestClient (httpx under the hood) — it
calls the `app` object directly in-process, no real network involved, so it
runs the exact same code path a real request would without needing a
server running.

Each test gets its own throwaway SQLite database (a temp file, deleted
automatically at the end of the test session) via the `db_url` /
`client` fixtures below, so tests never touch your real local.db and never
depend on what any other test already did.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make sure the project root (which contains the `backend` and `api`
# packages) is importable regardless of what directory pytest is invoked
# from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ["COOKIE_SECURE"] = "false"  # TestClient doesn't use real HTTPS
# The rate limiter is keyed by client IP, and every request from TestClient
# shares the same fake IP — without raising this, a test file that makes
# more than RATE_LIMIT_MAX calls in a row would start tripping 429s that
# have nothing to do with what's actually being tested.
os.environ["RATE_LIMIT_MAX"] = "1000"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A fresh app + fresh SQLite file per test."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    # backend.database reads DATABASE_URL at *import time*, so every test
    # needs its own freshly-imported copy of the app/database modules
    # rather than reusing whatever was imported by an earlier test.
    for mod in list(sys.modules):
        if mod == "api.index" or mod.startswith("backend."):
            del sys.modules[mod]

    from fastapi.testclient import TestClient

    from api.index import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session(client):
    """A SQLAlchemy session bound to the same throwaway database `client`
    is using, for tests that need to seed a user directly."""
    from backend.database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _create_test_user(db_session, email="jane@example.com", password="correct-horse-battery", name="Jane Doe", email_verified=True):
    from backend.auth import hash_password
    from backend.database import create_user

    # Defaults to already-verified: this helper seeds a user directly
    # against the database (like backend/create_user.py's CLI script), not
    # through the public self-serve signup form, so most existing tests
    # here are testing generic login/session mechanics and should not be
    # spuriously blocked by POST /api/login's new "please verify your
    # email" gate. Tests that specifically exercise that gate pass
    # email_verified=False explicitly (see TestLoginRequiresVerification).
    return create_user(db_session, email=email, name=name, password_hash=hash_password(password), email_verified=email_verified)


# ---------------------------------------------------------------------------
# POST /api/leads
# ---------------------------------------------------------------------------

class TestLeads:
    def test_successful_lead_capture(self, client):
        resp = client.post(
            "/api/leads",
            json={"name": "Alex Rivera", "email": "alex@example.com", "phone": "+12025550123", "interest": "Growth"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["ok"] is True
        assert body["status"] == "created"
        assert "message" in body

    def test_lead_missing_name_is_rejected(self, client):
        resp = client.post("/api/leads", json={"email": "alex@example.com"})
        assert resp.status_code == 422
        body = resp.json()
        assert body["success"] is False
        assert "name" in body["errors"]

    def test_lead_invalid_email_is_rejected(self, client):
        resp = client.post("/api/leads", json={"name": "Alex Rivera", "email": "not-an-email"})
        assert resp.status_code == 422
        body = resp.json()
        assert body["success"] is False
        assert "email" in body["errors"]

    def test_lead_invalid_phone_is_rejected_when_supplied(self, client):
        resp = client.post(
            "/api/leads", json={"name": "Alex Rivera", "email": "alex@example.com", "phone": "abc"}
        )
        assert resp.status_code == 422
        assert "phone" in resp.json()["errors"]

    def test_lead_phone_and_interest_are_optional(self, client):
        resp = client.post("/api/leads", json={"name": "Alex Rivera", "email": "alex2@example.com"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_duplicate_email_updates_rather_than_errors(self, client):
        payload = {"name": "Alex Rivera", "email": "dup@example.com", "interest": "Growth"}
        first = client.post("/api/leads", json=payload)
        second = client.post("/api/leads", json={**payload, "name": "Alex R. Rivera"})
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["status"] == "created"
        assert second.json()["status"] == "duplicate"

    def test_frontend_alias_phone_e164_is_accepted(self, client):
        """The live 'Get started' form on index.html sends `phone_e164`, not
        `phone` — this must keep working without any frontend changes."""
        resp = client.post(
            "/api/leads",
            json={"name": "Alex Rivera", "email": "alex3@example.com", "phone_e164": "+12025550123"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# POST /api/login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_successful_login(self, client, db_session):
        _create_test_user(db_session, email="jane@example.com", password="correct-horse-battery")
        resp = client.post("/api/login", json={"email": "jane@example.com", "password": "correct-horse-battery"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["user"]["email"] == "jane@example.com"
        # Never leak the password hash or the internal numeric id.
        assert "password_hash" not in body["user"]
        assert "id" not in body["user"]
        # The session cookie must actually be set.
        assert "zw_session" in resp.cookies

    def test_incorrect_password_is_rejected(self, client, db_session):
        _create_test_user(db_session, email="jane@example.com", password="correct-horse-battery")
        resp = client.post("/api/login", json={"email": "jane@example.com", "password": "wrong-password"})
        assert resp.status_code == 401
        assert resp.json()["success"] is False

    def test_unknown_email_gives_same_generic_message(self, client):
        resp = client.post("/api/login", json={"email": "nobody@example.com", "password": "whatever123"})
        assert resp.status_code == 401
        assert resp.json()["message"] == "Incorrect email or password."

    def test_missing_fields_rejected(self, client):
        resp = client.post("/api/login", json={"email": "jane@example.com"})
        assert resp.status_code == 422

    def test_invalid_email_format_rejected(self, client):
        resp = client.post("/api/login", json={"email": "not-an-email", "password": "whatever123"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Session-gated routes: /api/me, /api/dashboard, /api/logout
# ---------------------------------------------------------------------------

class TestSession:
    def test_me_requires_login(self, client):
        resp = client.get("/api/me")
        assert resp.status_code == 401

    def test_dashboard_requires_login(self, client):
        resp = client.get("/api/dashboard")
        assert resp.status_code == 401

    def test_me_and_dashboard_work_after_login(self, client, db_session):
        _create_test_user(db_session, email="jane@example.com", password="correct-horse-battery")
        login_resp = client.post("/api/login", json={"email": "jane@example.com", "password": "correct-horse-battery"})
        assert login_resp.status_code == 200

        me_resp = client.get("/api/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["user"]["email"] == "jane@example.com"

        dash_resp = client.get("/api/dashboard")
        assert dash_resp.status_code == 200
        data = dash_resp.json()["data"]
        assert "portfolioValue" in data
        assert "holdings" in data and len(data["holdings"]) == 5

    def test_logout_clears_session(self, client, db_session):
        _create_test_user(db_session, email="jane@example.com", password="correct-horse-battery")
        client.post("/api/login", json={"email": "jane@example.com", "password": "correct-horse-battery"})
        assert client.get("/api/me").status_code == 200

        logout_resp = client.post("/api/logout")
        assert logout_resp.status_code == 200
        assert client.get("/api/me").status_code == 401


# ---------------------------------------------------------------------------
# Email verification: POST /api/auth/signup + GET /api/auth/verify-email +
# POST /api/auth/resend-verification
# ---------------------------------------------------------------------------
#
# GMAIL_USER/GMAIL_APP_PASSWORD are blank in this project's .env today (see
# .env.example), so these tests monkeypatch api.index.send_verification_email
# rather than sending real mail -- that's a deliberate substitute for a mail
# server, not a shortcut around testing the surrounding logic (token
# generation/storage/expiry, the actual HTTP responses, and the DB state)
# for real. Once real Gmail credentials are set, the exact same request
# flow will additionally send a real email; nothing about that requires a
# different code path.

def _capture_sent_emails(monkeypatch):
    """Patches api.index.send_verification_email to record calls instead of
    talking to smtplib, and returns the list it appends to."""
    import api.index as api_index

    sent: list[dict] = []

    def _fake_send(*, to_email, name, verify_url):
        sent.append({"to_email": to_email, "name": name, "verify_url": verify_url})
        return True

    monkeypatch.setattr(api_index, "send_verification_email", _fake_send)
    return sent


def _extract_token(verify_url: str) -> str:
    import re

    m = re.search(r"token=([^&]+)", verify_url)
    assert m is not None, f"no token= query param in {verify_url!r}"
    return m.group(1)


class TestSignupVerification:
    def test_signup_creates_unverified_user_and_sends_verification_email(self, client, monkeypatch):
        sent = _capture_sent_emails(monkeypatch)

        resp = client.post(
            "/api/auth/signup",
            json={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "password": "correct-horse-1",
                "confirm_password": "correct-horse-1",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["verification_email_sent"] is True
        assert body["requires_verification"] is True
        assert "verif" in body["message"].lower()
        # Signup must NOT auto-authenticate -- the new account is
        # unverified, and POST /api/login already refuses to authenticate
        # an unverified email/password account, so no session cookie is
        # issued here either. See TestSignupDoesNotAutoLogin below for the
        # dedicated regression tests on this contract.
        assert "zw_session" not in resp.cookies

        assert len(sent) == 1
        assert sent[0]["to_email"] == "jane@example.com"

        from backend.database import find_user_by_email

        # Needs its own db session bound to the same throwaway database.
        from backend.database import SessionLocal

        db = SessionLocal()
        try:
            user = find_user_by_email(db, "jane@example.com")
            assert user is not None
            assert user.email_verified is False
            assert user.auth_provider == "email"
        finally:
            db.close()

    def test_signup_still_succeeds_when_email_sending_fails(self, client, monkeypatch):
        """Account creation must never fail just because mail delivery is
        unavailable (e.g. GMAIL_USER/GMAIL_APP_PASSWORD not configured)."""
        import api.index as api_index

        monkeypatch.setattr(api_index, "send_verification_email", lambda **kw: False)

        resp = client.post(
            "/api/auth/signup",
            json={
                "name": "No Mail",
                "email": "nomail@example.com",
                "password": "correct-horse-1",
                "confirm_password": "correct-horse-1",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["verification_email_sent"] is False
        assert "zw_session" not in resp.cookies  # account still created, but never auto-authenticated


# ---------------------------------------------------------------------------
# POST /api/auth/signup must never leave an authenticated session behind --
# the person must verify their email and then log in normally, exactly like
# any other unverified email/password account (see POST /api/login's
# "Please verify your email before signing in." gate, tested below in
# TestLoginRequiresVerification).
# ---------------------------------------------------------------------------

class TestSignupDoesNotAutoLogin:
    def test_signup_response_has_no_session_cookie(self, client, monkeypatch):
        _capture_sent_emails(monkeypatch)
        resp = client.post(
            "/api/auth/signup",
            json={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "password": "correct-horse-1",
                "confirm_password": "correct-horse-1",
            },
        )
        assert resp.status_code == 200
        assert "zw_session" not in resp.cookies
        body = resp.json()
        assert body["requires_verification"] is True
        assert "verify your email" in body["message"].lower()

    def test_me_and_dashboard_are_unauthenticated_immediately_after_signup(self, client, monkeypatch):
        _capture_sent_emails(monkeypatch)
        client.post(
            "/api/auth/signup",
            json={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "password": "correct-horse-1",
                "confirm_password": "correct-horse-1",
            },
        )
        # No cookie was ever set for this client, so both of these must
        # behave exactly as they do for any anonymous visitor.
        assert client.get("/api/me").status_code == 401
        assert client.get("/api/dashboard").status_code == 401

    def test_google_signup_still_auto_authenticates(self, client, monkeypatch):
        """Sanity check that this change is scoped to email/password
        signup only -- "Continue with Google" must keep creating a normal
        session immediately, since a Google identity is already verified
        server-side before the Zoey account even exists."""
        from backend.google_auth import GoogleIdentity

        _patch_google_identity(
            monkeypatch,
            GoogleIdentity(sub="google-sub-signup-unaffected", email="googleuser-signup@example.com", email_verified=True, name="Google User"),
        )
        resp = client.post("/api/auth/google", json={"credential": "fake-credential"})
        assert resp.status_code == 200
        assert "zw_session" in resp.cookies
        assert client.get("/api/dashboard").status_code == 200


class TestVerifyEmail:
    def test_clicking_the_link_marks_the_account_verified(self, client, monkeypatch):
        sent = _capture_sent_emails(monkeypatch)
        client.post(
            "/api/auth/signup",
            json={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "password": "correct-horse-1",
                "confirm_password": "correct-horse-1",
            },
        )
        token = _extract_token(sent[0]["verify_url"])

        resp = client.get(f"/api/auth/verify-email?token={token}", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?verified=1"

        from backend.database import SessionLocal, find_user_by_email

        db = SessionLocal()
        try:
            user = find_user_by_email(db, "jane@example.com")
            assert user.email_verified is True
            assert user.email_verify_token_hash is None
        finally:
            db.close()

    def test_replaying_the_same_link_is_reported_as_already_verified(self, client, monkeypatch):
        sent = _capture_sent_emails(monkeypatch)
        client.post(
            "/api/auth/signup",
            json={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "password": "correct-horse-1",
                "confirm_password": "correct-horse-1",
            },
        )
        token = _extract_token(sent[0]["verify_url"])
        client.get(f"/api/auth/verify-email?token={token}", follow_redirects=False)

        resp = client.get(f"/api/auth/verify-email?token={token}", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?verify_error=used_or_invalid"

    def test_missing_token_is_reported_as_invalid(self, client):
        resp = client.get("/api/auth/verify-email", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?verify_error=used_or_invalid"

    def test_expired_token_is_reported_as_expired(self, client, db_session):
        from datetime import datetime, timedelta, timezone

        from backend.database import set_email_verification_token
        from backend.email_verification import hash_token

        user = _create_test_user(db_session, email="jane@example.com", password="correct-horse-battery")
        raw_token = "manually-issued-token"
        set_email_verification_token(
            db_session, user, token_hash=hash_token(raw_token), expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )

        resp = client.get(f"/api/auth/verify-email?token={raw_token}", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?verify_error=expired"


# ---------------------------------------------------------------------------
# POST /api/login must refuse an unverified email/password account
# ---------------------------------------------------------------------------

class TestLoginRequiresVerification:
    def test_unverified_email_password_login_is_blocked(self, client, db_session):
        _create_test_user(db_session, email="jane@example.com", password="correct-horse-battery", email_verified=False)

        resp = client.post("/api/login", json={"email": "jane@example.com", "password": "correct-horse-battery"})
        assert resp.status_code == 403
        assert resp.json()["message"] == "Please verify your email before signing in."
        assert "zw_session" not in resp.cookies

    def test_wrong_password_still_wins_over_verification_state(self, client, db_session):
        """The password must be checked BEFORE the verification gate --
        otherwise this endpoint would leak "this email exists and is
        unverified" to someone who doesn't even know the password."""
        _create_test_user(db_session, email="jane@example.com", password="correct-horse-battery", email_verified=False)

        resp = client.post("/api/login", json={"email": "jane@example.com", "password": "totally-wrong"})
        assert resp.status_code == 401
        assert resp.json()["message"] == "Incorrect email or password."

    def test_existing_verified_user_logs_in_normally(self, client, db_session):
        _create_test_user(db_session, email="verified@example.com", password="correct-horse-battery")
        resp = client.post("/api/login", json={"email": "verified@example.com", "password": "correct-horse-battery"})
        assert resp.status_code == 200
        assert "zw_session" in resp.cookies

    def test_verifying_then_logging_in_works(self, client, monkeypatch):
        sent = _capture_sent_emails(monkeypatch)
        client.post(
            "/api/auth/signup",
            json={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "password": "correct-horse-1",
                "confirm_password": "correct-horse-1",
            },
        )

        # Signup itself does not authenticate (see TestSignupDoesNotAutoLogin),
        # so this is already a genuine, fresh POST /api/login attempt.
        blocked = client.post("/api/login", json={"email": "jane@example.com", "password": "correct-horse-1"})
        assert blocked.status_code == 403

        token = _extract_token(sent[0]["verify_url"])
        verify_resp = client.get(f"/api/auth/verify-email?token={token}", follow_redirects=False)
        assert verify_resp.headers["location"] == "/login?verified=1"

        allowed = client.post("/api/login", json={"email": "jane@example.com", "password": "correct-horse-1"})
        assert allowed.status_code == 200
        assert "zw_session" in allowed.cookies
        assert client.get("/api/dashboard").status_code == 200

    def test_resend_then_verify_then_login_works(self, client, monkeypatch):
        """The existing resend-verification mechanism (rate-limited,
        non-enumerating -- see TestResendVerification below) is the
        unverified user's way out of this gate, without weakening either
        property."""
        sent = _capture_sent_emails(monkeypatch)
        client.post(
            "/api/auth/signup",
            json={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "password": "correct-horse-1",
                "confirm_password": "correct-horse-1",
            },
        )
        assert client.post("/api/login", json={"email": "jane@example.com", "password": "correct-horse-1"}).status_code == 403

        resend_resp = client.post("/api/auth/resend-verification", json={"email": "jane@example.com"})
        assert resend_resp.status_code == 200
        assert len(sent) == 2  # the original signup email, plus this resend

        token = _extract_token(sent[-1]["verify_url"])
        client.get(f"/api/auth/verify-email?token={token}", follow_redirects=False)

        allowed = client.post("/api/login", json={"email": "jane@example.com", "password": "correct-horse-1"})
        assert allowed.status_code == 200

    def test_google_login_is_never_subject_to_this_gate(self, client, monkeypatch):
        """Sanity check for the explicit requirement that this verification
        gate applies ONLY to email/password login. A Google-authenticated
        account is always email_verified=True the moment it's created/
        linked (see backend/database.py), so there is nothing to block --
        this test exists to make that guarantee explicit and regression-
        tested, not just true by construction."""
        from backend.google_auth import GoogleIdentity

        _patch_google_identity(
            monkeypatch,
            GoogleIdentity(sub="google-sub-verify-gate", email="googleuser-login@example.com", email_verified=True, name="Google User"),
        )
        resp = client.post("/api/auth/google", json={"credential": "fake-credential"})
        assert resp.status_code == 200
        assert "zw_session" in resp.cookies
        assert client.get("/api/dashboard").status_code == 200


class TestResendVerification:
    def test_response_is_identical_whether_or_not_the_account_exists(self, client, monkeypatch):
        _capture_sent_emails(monkeypatch)
        resp_unknown = client.post("/api/auth/resend-verification", json={"email": "nobody@example.com"})
        resp_known_setup = client.post(
            "/api/auth/signup",
            json={
                "name": "Resend Me",
                "email": "resend@example.com",
                "password": "correct-horse-1",
                "confirm_password": "correct-horse-1",
            },
        )
        assert resp_known_setup.status_code == 200
        resp_known = client.post("/api/auth/resend-verification", json={"email": "resend@example.com"})

        assert resp_unknown.status_code == 200
        assert resp_known.status_code == 200
        assert resp_unknown.json() == resp_known.json()

    def test_does_not_resend_once_already_verified(self, client, monkeypatch):
        sent = _capture_sent_emails(monkeypatch)
        client.post(
            "/api/auth/signup",
            json={
                "name": "Resend Me",
                "email": "resend@example.com",
                "password": "correct-horse-1",
                "confirm_password": "correct-horse-1",
            },
        )
        assert len(sent) == 1  # the signup itself

        from backend.database import SessionLocal, find_user_by_email, set_email_verified

        db = SessionLocal()
        try:
            user = find_user_by_email(db, "resend@example.com")
            set_email_verified(db, user)
        finally:
            db.close()

        resp = client.post("/api/auth/resend-verification", json={"email": "resend@example.com"})
        assert resp.status_code == 200
        assert len(sent) == 1  # unchanged -- no second send for an already-verified account


# ---------------------------------------------------------------------------
# POST /api/auth/google
# ---------------------------------------------------------------------------
#
# The real google-auth verification call (backend/google_auth.py's
# verify_google_id_token) is monkeypatched here rather than exercised for
# real -- these tests are about THIS app's own account-linking/session
# logic once Google has vouched for someone, not about re-testing Google's
# own library. See that module's docstring for what it actually verifies.

def _patch_google_identity(monkeypatch, identity):
    import api.index as api_index

    monkeypatch.setattr(api_index, "verify_google_id_token", lambda credential: identity)


class TestGoogleAuth:
    def test_new_account_is_created_and_session_issued(self, client, monkeypatch):
        from backend.google_auth import GoogleIdentity

        _patch_google_identity(
            monkeypatch,
            GoogleIdentity(sub="google-sub-1", email="google.user@example.com", email_verified=True, name="Google User"),
        )

        resp = client.post("/api/auth/google", json={"credential": "fake-credential"})
        assert resp.status_code == 200
        assert "zw_session" in resp.cookies
        assert resp.json()["user"]["email"] == "google.user@example.com"

        from backend.database import SessionLocal, find_user_by_google_sub

        db = SessionLocal()
        try:
            user = find_user_by_google_sub(db, "google-sub-1")
            assert user is not None
            assert user.password_hash is None
            assert user.email_verified is True
            assert user.auth_provider == "google"
        finally:
            db.close()

        # Dashboard is reachable immediately -- same session system as
        # email/password login.
        assert client.get("/api/dashboard").status_code == 200

    def test_repeat_sign_in_reuses_the_same_account_no_password_needed(self, client, monkeypatch):
        from backend.google_auth import GoogleIdentity

        _patch_google_identity(
            monkeypatch,
            GoogleIdentity(sub="google-sub-2", email="repeat@example.com", email_verified=True, name="Repeat User"),
        )
        first = client.post("/api/auth/google", json={"credential": "fake-credential-1"})
        assert first.status_code == 200
        client.post("/api/logout")
        assert client.get("/api/dashboard").status_code == 401

        second = client.post("/api/auth/google", json={"credential": "fake-credential-2"})
        assert second.status_code == 200
        assert client.get("/api/dashboard").status_code == 200

        from backend.database import SessionLocal, list_users

        db = SessionLocal()
        try:
            matching = [u for u in list_users(db) if u.google_sub == "google-sub-2"]
            assert len(matching) == 1  # no duplicate account created on the second sign-in
        finally:
            db.close()

    def test_links_to_existing_email_password_account_by_verified_email(self, client, monkeypatch, db_session):
        from backend.google_auth import GoogleIdentity

        existing = _create_test_user(db_session, email="both@example.com", password="correct-horse-battery", name="Both Ways")
        original_hash = existing.password_hash

        _patch_google_identity(
            monkeypatch,
            GoogleIdentity(sub="google-sub-link", email="both@example.com", email_verified=True, name="Both Ways"),
        )
        resp = client.post("/api/auth/google", json={"credential": "fake-credential"})
        assert resp.status_code == 200

        from backend.database import SessionLocal, find_user_by_email, list_users

        db = SessionLocal()
        try:
            matching = [u for u in list_users(db) if u.email == "both@example.com"]
            assert len(matching) == 1  # linked, not duplicated
            linked = find_user_by_email(db, "both@example.com")
            assert linked.google_sub == "google-sub-link"
            assert linked.auth_provider == "email"  # origin unchanged
            assert linked.password_hash == original_hash  # original password still usable
        finally:
            db.close()

        # The original Zoey password still works after linking.
        client.post("/api/logout")
        pw_login = client.post("/api/login", json={"email": "both@example.com", "password": "correct-horse-battery"})
        assert pw_login.status_code == 200

    def test_unverified_google_email_is_rejected(self, client, monkeypatch):
        from backend.google_auth import GoogleIdentity

        _patch_google_identity(
            monkeypatch,
            GoogleIdentity(sub="google-sub-3", email="unverified@example.com", email_verified=False, name="Unverified"),
        )
        resp = client.post("/api/auth/google", json={"credential": "fake-credential"})
        assert resp.status_code == 401

        from backend.database import SessionLocal, find_user_by_email

        db = SessionLocal()
        try:
            assert find_user_by_email(db, "unverified@example.com") is None
        finally:
            db.close()

    def test_failed_verification_returns_generic_message(self, client, monkeypatch):
        import api.index as api_index
        from backend.google_auth import GoogleAuthError

        def _raise(credential):
            raise GoogleAuthError("signature verification failed")

        monkeypatch.setattr(api_index, "verify_google_id_token", _raise)
        resp = client.post("/api/auth/google", json={"credential": "bad-credential"})
        assert resp.status_code == 401
        assert resp.json()["message"] == "We couldn't complete Google sign-in. Please try again."

    def test_missing_credential_is_rejected(self, client):
        resp = client.post("/api/auth/google", json={})
        assert resp.status_code == 422
