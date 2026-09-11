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


def _create_test_user(db_session, email="jane@example.com", password="correct-horse-battery", name="Jane Doe"):
    from backend.auth import hash_password
    from backend.database import create_user

    return create_user(db_session, email=email, name=name, password_hash=hash_password(password))


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
