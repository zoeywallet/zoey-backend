"""
Tests for the Day 1 Alpaca Broker API Sandbox integration:
backend/services/alpaca.py (the HTTP client) and backend/routes/alpaca.py
(the two authenticated FastAPI routes).

Same fixture pattern as tests/test_api.py / tests/test_market_data.py -- a
fresh throwaway SQLite file per test, never local.db, never production.

Run with:

    pytest tests/test_alpaca.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os  # noqa: E402

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ["COOKIE_SECURE"] = "false"
os.environ["RATE_LIMIT_MAX"] = "1000"

_REAL_KEY_ID = "AKFAKE00000000000TEST"
_REAL_SECRET = "super-secret-alpaca-key-should-never-leak-in-logs-or-responses"


# ---------------------------------------------------------------------------
# Service-level fixtures/helpers (direct calls into backend.services.alpaca,
# no FastAPI/TestClient involved -- these don't need the app or a database)
# ---------------------------------------------------------------------------


@pytest.fixture()
def alpaca_module(monkeypatch):
    """A freshly re-imported backend.services.alpaca with sandbox-valid
    config, so each test starts from a known-good baseline and only
    overrides what it's actually testing."""
    for mod in list(sys.modules):
        if mod == "backend.services.alpaca":
            del sys.modules[mod]
    monkeypatch.setenv("ALPACA_ENABLED", "true")
    monkeypatch.setenv("ALPACA_API_KEY_ID", _REAL_KEY_ID)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", _REAL_SECRET)
    monkeypatch.setenv("ALPACA_BASE_URL", "https://broker-api.sandbox.alpaca.markets")

    import backend.services.alpaca as alpaca

    return alpaca


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data


def _fake_account(**overrides) -> dict:
    """A realistically-shaped Alpaca account object -- including the kind
    of KYC/PII fields (identity, contact, ssn-like, disclosures) that
    _sanitize_account must strip out. Nothing here is a real person's
    data; it's shaped like Alpaca's sandbox docs purely to prove the
    allowlist actually filters it."""
    base = {
        "id": "4a9b7c1e-aaaa-bbbb-cccc-000000000001",
        "account_number": "900000001",
        "status": "ACTIVE",
        "crypto_status": "ACTIVE",
        "currency": "USD",
        "created_at": "2026-01-01T00:00:00Z",
        "account_type": "trading",
        # ---- fields that must NEVER survive sanitization ----
        "contact": {"email_address": "person@example.com", "phone_number": "+10000000000"},
        "identity": {
            "given_name": "Test",
            "family_name": "Person",
            "tax_id": "900-00-0000",
            "date_of_birth": "1990-01-01",
        },
        "disclosures": {"is_control_person": False},
        "agreements": [{"agreement": "account_agreement", "signed_at": "2026-01-01T00:00:00Z"}],
        "trusted_contact": {"given_name": "Someone", "email_address": "someone@example.com"},
        "documents": [{"document_type": "identity_verification"}],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# backend.services.alpaca -- configuration / safety-rule enforcement
# ---------------------------------------------------------------------------


class TestConfigAndSandboxEnforcement:
    def test_disabled_raises_config_error_and_makes_no_request(self, alpaca_module, monkeypatch):
        monkeypatch.setattr(alpaca_module, "ALPACA_ENABLED", False)
        called = []
        monkeypatch.setattr(alpaca_module.requests, "get", lambda *a, **k: called.append(1))

        with pytest.raises(alpaca_module.AlpacaConfigError):
            alpaca_module.check_connectivity()
        assert called == [], "a disabled integration must never make a network call"

    def test_missing_credentials_raises_config_error(self, alpaca_module, monkeypatch):
        monkeypatch.setattr(alpaca_module, "ALPACA_API_KEY_ID", "")
        monkeypatch.setattr(alpaca_module, "ALPACA_API_SECRET_KEY", "")
        called = []
        monkeypatch.setattr(alpaca_module.requests, "get", lambda *a, **k: called.append(1))

        with pytest.raises(alpaca_module.AlpacaConfigError):
            alpaca_module.check_connectivity()
        assert called == []

    def test_non_sandbox_host_is_rejected_and_makes_no_request(self, alpaca_module, monkeypatch):
        # Alpaca's real LIVE Broker API host -- must never be reachable
        # from this integration during this phase, even if someone sets
        # it by mistake (or on purpose) in the environment.
        monkeypatch.setattr(alpaca_module, "ALPACA_BASE_URL", "https://broker-api.alpaca.markets")
        called = []
        monkeypatch.setattr(alpaca_module.requests, "get", lambda *a, **k: called.append(1))

        with pytest.raises(alpaca_module.AlpacaConfigError):
            alpaca_module.check_connectivity()
        assert called == [], "a non-sandbox host must never be called, not even once"

    def test_sandbox_host_with_http_not_https_is_rejected(self, alpaca_module, monkeypatch):
        monkeypatch.setattr(alpaca_module, "ALPACA_BASE_URL", "http://broker-api.sandbox.alpaca.markets")
        with pytest.raises(alpaca_module.AlpacaConfigError):
            alpaca_module.check_connectivity()


# ---------------------------------------------------------------------------
# backend.services.alpaca -- upstream failure handling
# ---------------------------------------------------------------------------


class TestUpstreamFailureHandling:
    def test_invalid_credentials_401_raises_request_error_without_retry(self, alpaca_module, monkeypatch):
        calls = []

        def fake_get(url, params=None, auth=None, timeout=None):
            calls.append(1)
            return _FakeResponse(status_code=401)

        monkeypatch.setattr(alpaca_module.requests, "get", fake_get)

        with pytest.raises(alpaca_module.AlpacaRequestError):
            alpaca_module.check_connectivity()
        assert len(calls) == 1, "an auth failure must never be retried"

    def test_forbidden_403_raises_request_error(self, alpaca_module, monkeypatch):
        monkeypatch.setattr(
            alpaca_module.requests, "get",
            lambda url, params=None, auth=None, timeout=None: _FakeResponse(status_code=403),
        )
        with pytest.raises(alpaca_module.AlpacaRequestError):
            alpaca_module.check_connectivity()

    def test_rate_limited_429_raises_request_error(self, alpaca_module, monkeypatch):
        calls = []

        def fake_get(url, params=None, auth=None, timeout=None):
            calls.append(1)
            return _FakeResponse(status_code=429)

        monkeypatch.setattr(alpaca_module.requests, "get", fake_get)

        with pytest.raises(alpaca_module.AlpacaRequestError):
            alpaca_module.check_connectivity()
        assert len(calls) == 1, "a rate-limit response must never be retried (would make it worse)"

    def test_timeout_is_retried_up_to_the_bound_then_raises(self, alpaca_module, monkeypatch):
        calls = []

        def fake_get(url, params=None, auth=None, timeout=None):
            calls.append(1)
            raise requests.exceptions.Timeout("simulated timeout")

        monkeypatch.setattr(alpaca_module.requests, "get", fake_get)

        with pytest.raises(alpaca_module.AlpacaRequestError):
            alpaca_module.check_connectivity()
        assert len(calls) == alpaca_module.MAX_RETRIES + 1

    def test_connection_error_is_retried_then_raises_without_crashing(self, alpaca_module, monkeypatch):
        def fake_get(url, params=None, auth=None, timeout=None):
            raise requests.exceptions.ConnectionError("simulated connection error")

        monkeypatch.setattr(alpaca_module.requests, "get", fake_get)

        with pytest.raises(alpaca_module.AlpacaRequestError):
            alpaca_module.check_connectivity()

    def test_server_error_500_is_retried_then_raises(self, alpaca_module, monkeypatch):
        calls = []

        def fake_get(url, params=None, auth=None, timeout=None):
            calls.append(1)
            return _FakeResponse(status_code=500)

        monkeypatch.setattr(alpaca_module.requests, "get", fake_get)

        with pytest.raises(alpaca_module.AlpacaRequestError):
            alpaca_module.check_connectivity()
        assert len(calls) == alpaca_module.MAX_RETRIES + 1

    def test_malformed_json_body_raises_request_error_not_a_crash(self, alpaca_module, monkeypatch):
        class _BadJsonResponse(_FakeResponse):
            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(
            alpaca_module.requests, "get",
            lambda url, params=None, auth=None, timeout=None: _BadJsonResponse(status_code=200),
        )
        with pytest.raises(alpaca_module.AlpacaRequestError):
            alpaca_module.check_connectivity()


# ---------------------------------------------------------------------------
# backend.services.alpaca -- sanitization (the core safety property)
# ---------------------------------------------------------------------------


class TestSanitization:
    def test_connectivity_check_never_returns_account_data(self, alpaca_module, monkeypatch):
        """Even if Alpaca's response body contains full account/PII data,
        check_connectivity()'s return value must be the fixed, minimal
        shape only."""
        monkeypatch.setattr(
            alpaca_module.requests, "get",
            lambda url, params=None, auth=None, timeout=None: _FakeResponse(
                json_data=[_fake_account()], status_code=200
            ),
        )
        result = alpaca_module.check_connectivity()
        assert result == {"ok": True, "sandbox_reachable": True}

    def test_list_accounts_strips_pii_and_keeps_only_safe_fields(self, alpaca_module, monkeypatch):
        monkeypatch.setattr(
            alpaca_module.requests, "get",
            lambda url, params=None, auth=None, timeout=None: _FakeResponse(
                json_data=[_fake_account()], status_code=200
            ),
        )
        accounts = alpaca_module.list_accounts_sanitized()
        assert len(accounts) == 1
        account = accounts[0]

        for forbidden in ("contact", "identity", "disclosures", "agreements", "trusted_contact", "documents"):
            assert forbidden not in account, f"{forbidden!r} must never survive sanitization"

        assert set(account.keys()) <= set(alpaca_module._ACCOUNT_SAFE_FIELDS)
        assert account["id"] == "4a9b7c1e-aaaa-bbbb-cccc-000000000001"
        assert account["status"] == "ACTIVE"

    def test_list_accounts_handles_non_list_payload_gracefully(self, alpaca_module, monkeypatch):
        monkeypatch.setattr(
            alpaca_module.requests, "get",
            lambda url, params=None, auth=None, timeout=None: _FakeResponse(json_data={"not": "a list"}, status_code=200),
        )
        assert alpaca_module.list_accounts_sanitized() == []

    def test_secret_key_never_appears_in_logs_on_any_failure_path(self, alpaca_module, monkeypatch, caplog):
        import logging

        scenarios = [
            lambda: _FakeResponse(status_code=401),
            lambda: _FakeResponse(status_code=429),
            lambda: (_ for _ in ()).throw(requests.exceptions.Timeout("x")),
            lambda: (_ for _ in ()).throw(requests.exceptions.ConnectionError("x")),
        ]
        with caplog.at_level(logging.WARNING, logger="zoey.alpaca"):
            for make_result in scenarios:
                def fake_get(url, params=None, auth=None, timeout=None, _make=make_result):
                    result = _make()
                    return result

                monkeypatch.setattr(alpaca_module.requests, "get", fake_get)
                try:
                    alpaca_module.check_connectivity()
                except alpaca_module.AlpacaRequestError:
                    pass

        all_log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert _REAL_SECRET not in all_log_text
        assert _REAL_KEY_ID not in all_log_text
        assert "broker-api.sandbox.alpaca.markets" not in all_log_text or "Authorization" not in all_log_text

    def test_exception_messages_raised_to_callers_never_contain_the_secret(self, alpaca_module, monkeypatch):
        monkeypatch.setattr(
            alpaca_module.requests, "get",
            lambda url, params=None, auth=None, timeout=None: _FakeResponse(status_code=401),
        )
        with pytest.raises(alpaca_module.AlpacaRequestError) as exc_info:
            alpaca_module.check_connectivity()
        assert _REAL_SECRET not in str(exc_info.value)
        assert _REAL_KEY_ID not in str(exc_info.value)

    def test_auth_uses_http_basic_not_query_params(self, alpaca_module, monkeypatch):
        """The Alpaca Broker API uses HTTP Basic Auth, not a query-param
        key like Twelve Data -- confirm the credential is passed via
        requests' `auth=` kwarg, never folded into `params`."""
        seen = {}

        def fake_get(url, params=None, auth=None, timeout=None):
            seen["auth"] = auth
            seen["params"] = params
            return _FakeResponse(json_data=[], status_code=200)

        monkeypatch.setattr(alpaca_module.requests, "get", fake_get)
        alpaca_module.check_connectivity()

        assert seen["auth"] == (_REAL_KEY_ID, _REAL_SECRET)
        assert "apikey" not in (seen["params"] or {})
        assert _REAL_SECRET not in str(seen["params"])


# ---------------------------------------------------------------------------
# Route-level tests (FastAPI TestClient) -- authentication/authorization
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_alpaca_enabled(tmp_path, monkeypatch):
    """Same app+DB fixture pattern as tests/test_api.py / test_market_data.py,
    with ALPACA_ENABLED (and valid-looking sandbox config) turned on BEFORE
    the app module is (re-)imported, so api/index.py actually registers the
    router for this test."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ALPACA_ENABLED", "true")
    monkeypatch.setenv("ALPACA_API_KEY_ID", _REAL_KEY_ID)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", _REAL_SECRET)
    monkeypatch.setenv("ALPACA_BASE_URL", "https://broker-api.sandbox.alpaca.markets")
    monkeypatch.delenv("ADMIN_KEY", raising=False)

    for mod in list(sys.modules):
        if mod == "api.index" or mod.startswith("backend."):
            del sys.modules[mod]

    from fastapi.testclient import TestClient

    from api.index import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def client_alpaca_disabled(tmp_path, monkeypatch):
    """Same as above but with ALPACA_ENABLED left at its default (unset
    -> false), to prove the routes are absent, not merely refusing."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ALPACA_ENABLED", raising=False)
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)

    for mod in list(sys.modules):
        if mod == "api.index" or mod.startswith("backend."):
            del sys.modules[mod]

    from fastapi.testclient import TestClient

    from api.index import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session_enabled(client_alpaca_enabled):
    from backend.database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _create_test_user(db_session, email="jane@example.com", password="correct-horse-battery"):
    from backend.auth import hash_password
    from backend.database import create_user

    return create_user(db_session, email=email, name="Jane Doe", password_hash=hash_password(password), email_verified=True)


def _login(client, email="jane@example.com", password="correct-horse-battery"):
    resp = client.post("/api/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp


class TestRoutesAbsentWhenDisabled:
    def test_healthz_route_does_not_exist_when_disabled(self, client_alpaca_disabled):
        resp = client_alpaca_disabled.get("/api/alpaca/healthz")
        assert resp.status_code == 404

    def test_accounts_route_does_not_exist_when_disabled(self, client_alpaca_disabled):
        resp = client_alpaca_disabled.get("/api/alpaca/accounts")
        assert resp.status_code == 404


class TestHealthzAuthenticationAndSafety:
    """/healthz is now gated the same way as /accounts -- signed in AND
    an internal-testing ADMIN_KEY -- restricted to authorized internal
    testers, not merely any signed-in user (tightened this round)."""

    def test_requires_authentication_before_the_admin_key_check(self, client_alpaca_enabled):
        resp = client_alpaca_enabled.get("/api/alpaca/healthz", headers={"X-Zoey-Admin-Key": "anything"})
        assert resp.status_code == 401

    def test_ordinary_authenticated_user_without_admin_key_is_rejected(self, client_alpaca_enabled, db_session_enabled, monkeypatch):
        monkeypatch.setenv("ADMIN_KEY", "a-real-internal-test-key")
        _create_test_user(db_session_enabled)
        _login(client_alpaca_enabled)

        resp = client_alpaca_enabled.get("/api/alpaca/healthz")
        assert resp.status_code == 403

    def test_ordinary_authenticated_user_with_wrong_admin_key_is_rejected(self, client_alpaca_enabled, db_session_enabled, monkeypatch):
        monkeypatch.setenv("ADMIN_KEY", "a-real-internal-test-key")
        _create_test_user(db_session_enabled)
        _login(client_alpaca_enabled)

        resp = client_alpaca_enabled.get("/api/alpaca/healthz", headers={"X-Zoey-Admin-Key": "wrong-key"})
        assert resp.status_code == 403

    def test_endpoint_is_unreachable_entirely_when_admin_key_not_configured(self, client_alpaca_enabled, db_session_enabled, monkeypatch):
        # ADMIN_KEY deliberately left unset (client_alpaca_enabled fixture
        # already does monkeypatch.delenv) -- must fail CLOSED, not open.
        _create_test_user(db_session_enabled)
        _login(client_alpaca_enabled)

        resp = client_alpaca_enabled.get("/api/alpaca/healthz", headers={"X-Zoey-Admin-Key": "anything"})
        assert resp.status_code == 503

    def test_authorized_internal_tester_gets_sanitized_ok_response(self, client_alpaca_enabled, db_session_enabled, monkeypatch):
        monkeypatch.setenv("ADMIN_KEY", "a-real-internal-test-key")
        _create_test_user(db_session_enabled)
        _login(client_alpaca_enabled)

        import backend.services.alpaca as alpaca_service

        monkeypatch.setattr(
            alpaca_service.requests, "get",
            lambda url, params=None, auth=None, timeout=None: _FakeResponse(json_data=[_fake_account()], status_code=200),
        )

        resp = client_alpaca_enabled.get("/api/alpaca/healthz", headers={"X-Zoey-Admin-Key": "a-real-internal-test-key"})
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"ok": True, "sandbox_reachable": True}
        # Explicitly confirm no account/PII field leaked through the route.
        for forbidden in ("accounts", "identity", "contact", "id", "account_number"):
            assert forbidden not in body

    def test_authorized_internal_tester_gets_safe_503_when_misconfigured(self, client_alpaca_enabled, db_session_enabled, monkeypatch):
        monkeypatch.setenv("ADMIN_KEY", "a-real-internal-test-key")
        _create_test_user(db_session_enabled)
        _login(client_alpaca_enabled)

        import backend.services.alpaca as alpaca_service

        monkeypatch.setattr(alpaca_service, "ALPACA_API_KEY_ID", "")
        monkeypatch.setattr(alpaca_service, "ALPACA_API_SECRET_KEY", "")

        resp = client_alpaca_enabled.get("/api/alpaca/healthz", headers={"X-Zoey-Admin-Key": "a-real-internal-test-key"})
        assert resp.status_code == 503
        assert _REAL_SECRET not in resp.text

    def test_authorized_internal_tester_gets_safe_502_on_upstream_failure(self, client_alpaca_enabled, db_session_enabled, monkeypatch):
        monkeypatch.setenv("ADMIN_KEY", "a-real-internal-test-key")
        _create_test_user(db_session_enabled)
        _login(client_alpaca_enabled)

        import backend.services.alpaca as alpaca_service

        monkeypatch.setattr(
            alpaca_service.requests, "get",
            lambda url, params=None, auth=None, timeout=None: _FakeResponse(status_code=401),
        )

        resp = client_alpaca_enabled.get("/api/alpaca/healthz", headers={"X-Zoey-Admin-Key": "a-real-internal-test-key"})
        assert resp.status_code == 502
        assert _REAL_SECRET not in resp.text
        assert _REAL_KEY_ID not in resp.text


class TestAccountsEndpointIsNotExposedToOrdinaryUsers:
    def test_ordinary_authenticated_user_cannot_list_accounts_without_admin_key(
        self, client_alpaca_enabled, db_session_enabled, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_KEY", "a-real-internal-test-key")
        _create_test_user(db_session_enabled)
        _login(client_alpaca_enabled)

        resp = client_alpaca_enabled.get("/api/alpaca/accounts")
        assert resp.status_code == 403
        assert "accounts" not in resp.json()

    def test_ordinary_authenticated_user_with_wrong_admin_key_is_rejected(
        self, client_alpaca_enabled, db_session_enabled, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_KEY", "a-real-internal-test-key")
        _create_test_user(db_session_enabled)
        _login(client_alpaca_enabled)

        resp = client_alpaca_enabled.get(
            "/api/alpaca/accounts", headers={"X-Zoey-Admin-Key": "wrong-key"}
        )
        assert resp.status_code == 403

    def test_endpoint_is_unreachable_entirely_when_admin_key_not_configured(
        self, client_alpaca_enabled, db_session_enabled, monkeypatch
    ):
        # ADMIN_KEY deliberately left unset (client_alpaca_enabled fixture
        # already does monkeypatch.delenv) -- must fail CLOSED, not open.
        _create_test_user(db_session_enabled)
        _login(client_alpaca_enabled)

        resp = client_alpaca_enabled.get(
            "/api/alpaca/accounts", headers={"X-Zoey-Admin-Key": "anything"}
        )
        assert resp.status_code == 503

    def test_unauthenticated_request_is_rejected_before_the_admin_key_check(self, client_alpaca_enabled, monkeypatch):
        monkeypatch.setenv("ADMIN_KEY", "a-real-internal-test-key")
        resp = client_alpaca_enabled.get(
            "/api/alpaca/accounts", headers={"X-Zoey-Admin-Key": "a-real-internal-test-key"}
        )
        assert resp.status_code == 401

    def test_correct_admin_key_returns_sanitized_accounts_only(
        self, client_alpaca_enabled, db_session_enabled, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_KEY", "a-real-internal-test-key")
        _create_test_user(db_session_enabled)
        _login(client_alpaca_enabled)

        import backend.services.alpaca as alpaca_service

        monkeypatch.setattr(
            alpaca_service.requests, "get",
            lambda url, params=None, auth=None, timeout=None: _FakeResponse(json_data=[_fake_account()], status_code=200),
        )

        resp = client_alpaca_enabled.get(
            "/api/alpaca/accounts", headers={"X-Zoey-Admin-Key": "a-real-internal-test-key"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["accounts"]) == 1
        account = body["accounts"][0]
        for forbidden in ("contact", "identity", "disclosures", "agreements", "trusted_contact", "documents"):
            assert forbidden not in account
