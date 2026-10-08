"""
Server-side Alpaca Broker API Sandbox client.

Scope of this module, deliberately: READ-ONLY sandbox connectivity and
account listing. It does not create brokerage accounts, submit orders,
simulate deposits/withdrawals, or touch any endpoint beyond
GET /v1/accounts and GET /v1/accounts/{id}. See api/index.py's own
module docstring and backend/routes/alpaca.py for the two routes this
backs.

Design mirrors backend/services/market_data.py's existing, already-reviewed
pattern for an external financial-data API:
    Frontend  --(fetch to /api/alpaca/...)-->  FastAPI (backend/routes/alpaca.py)
                                                        |
                                                        v
                                             backend/services/alpaca.py (this file)
                                                        |
                                                        v
                                           Alpaca Broker API Sandbox

The frontend never talks to Alpaca directly and never sees an Alpaca
credential -- ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY live only in
server-side environment variables, read once at import time (same
pattern this codebase already uses for TWELVE_DATA_API_KEY,
GOOGLE_CLIENT_ID, SECRET_KEY, etc.).

Authentication: the Alpaca Broker API (unlike Alpaca's Trading API) uses
plain HTTP Basic Auth -- the key id as the username, the secret key as the
password. `requests` builds that Authorization header itself from the
`auth=(key_id, secret_key)` tuple; neither credential is ever placed in the
URL or in query params (contrast with Twelve Data, which requires the key
as a query param -- see market_data.py's own comment on why its logging has
to be more careful as a result). That means a request's URL here never
contains a secret in the first place, which is a stronger starting point
than market_data.py had, but every failure path below still logs only a
status code / exception class / sanitized upstream message, never the
Authorization header, never request/response objects, and never a full
response body -- the same discipline, applied just as strictly.

SAFETY RULES ENFORCED BY THIS MODULE (do not relax without a separate,
explicit review):
  1. ALPACA_BASE_URL must resolve to the Alpaca sandbox host
     (broker-api.sandbox.alpaca.markets). Any other host -- including
     Alpaca's live/production Broker API host -- is refused before any
     request is made. This is a deliberate, hard-coded guard for this
     phase of the integration (see module docstring section in
     backend/routes/alpaca.py), not just a default.
  2. Only GET requests are made. Nothing in this module can create,
     modify, or delete anything at Alpaca.
  3. Account data returned to callers is always passed through
     _sanitize_account() below -- never the raw Alpaca response -- so a
     KYC/PII-bearing field (legal identity, contact info, SSN fragments,
     disclosures, agreements, documents, trusted contact, etc.) can never
     reach a route handler, a log line, or the frontend from here.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger("zoey.alpaca")

# ---------------------------------------------------------------------------
# Configuration (read once at import time, same pattern as every other
# external-API integration in this codebase)
# ---------------------------------------------------------------------------

_SANDBOX_HOST = "broker-api.sandbox.alpaca.markets"
_DEFAULT_BASE_URL = f"https://{_SANDBOX_HOST}"

ALPACA_ENABLED = os.environ.get("ALPACA_ENABLED", "false").strip().lower() == "true"
ALPACA_API_KEY_ID = os.environ.get("ALPACA_API_KEY_ID", "")
ALPACA_API_SECRET_KEY = os.environ.get("ALPACA_API_SECRET_KEY", "")
ALPACA_BASE_URL = os.environ.get("ALPACA_BASE_URL", "").strip() or _DEFAULT_BASE_URL

HTTP_TIMEOUT_SECONDS = 6
# Read-only GETs are safe to retry (no financial side effect can ever be
# duplicated by retrying a GET) -- but still capped and never retried on an
# auth failure, so a bad credential doesn't spin.
MAX_RETRIES = 2


class AlpacaConfigError(Exception):
    """Raised when this integration is disabled, unconfigured, or pointed
    at a non-sandbox host. Always safe to show the resulting message to an
    authenticated caller -- it never contains a credential value."""


class AlpacaRequestError(Exception):
    """Raised when a request to Alpaca itself fails (network error, bad
    status, malformed body). Always constructed with a sanitized message
    only -- see _alpaca_get's except blocks."""


def _is_sandbox_url(base_url: str) -> bool:
    """True only for the Alpaca sandbox host, over https. Deliberately
    strict (exact host match, not a substring/prefix check) so a typo or a
    copy-pasted production URL can never slip through as "close enough."
    """
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(base_url)
    except ValueError:
        return False
    return parts.scheme == "https" and parts.netloc == _SANDBOX_HOST


def _require_config() -> tuple[str, str, str]:
    """Returns (base_url, key_id, secret_key) or raises AlpacaConfigError
    with a message that is always safe to return to an authenticated
    caller -- never includes the credential values themselves."""
    if not ALPACA_ENABLED:
        raise AlpacaConfigError("Alpaca integration is not enabled.")
    if not ALPACA_API_KEY_ID or not ALPACA_API_SECRET_KEY:
        raise AlpacaConfigError("Alpaca credentials are not configured.")
    if not _is_sandbox_url(ALPACA_BASE_URL):
        # Deliberately vague about *why* beyond "sandbox" -- never echoes
        # the misconfigured value, which could itself be operator-supplied
        # and end up in a log/response otherwise.
        logger.warning("Alpaca request refused: ALPACA_BASE_URL is not the sandbox host")
        raise AlpacaConfigError(
            "Alpaca integration is restricted to the sandbox host during this phase."
        )
    return ALPACA_BASE_URL, ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY


def _alpaca_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GETs one Alpaca Broker API Sandbox endpoint. Never logs the
    Authorization header, the secret key, or a full request/response
    object -- only the endpoint path and a sanitized status/error
    description. Returns the parsed JSON body on success (200).

    Raises AlpacaConfigError if not configured / not sandbox, or
    AlpacaRequestError on any upstream failure. Never returns partially
    on error -- callers get either a real parsed body or an exception,
    never a guessed/fabricated value.
    """
    base_url, key_id, secret_key = _require_config()
    url = f"{base_url}{path}"

    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.get(
                url,
                params=params,
                auth=(key_id, secret_key),
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except requests.exceptions.Timeout:
            if attempt <= MAX_RETRIES:
                logger.warning("Alpaca request timed out, retrying: endpoint=%s attempt=%s", path, attempt)
                continue
            logger.warning("Alpaca request failed: endpoint=%s error=timeout", path)
            raise AlpacaRequestError("Alpaca sandbox request timed out.") from None
        except requests.exceptions.RequestException as exc:
            # Network/connection error -- log only the exception class
            # name, never str(exc) (which can embed the request URL).
            if attempt <= MAX_RETRIES:
                logger.warning(
                    "Alpaca request error, retrying: endpoint=%s attempt=%s error=%s",
                    path, attempt, type(exc).__name__,
                )
                continue
            logger.warning("Alpaca request failed: endpoint=%s error=%s", path, type(exc).__name__)
            raise AlpacaRequestError("Alpaca sandbox request failed.") from None

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                logger.warning("Alpaca request failed: endpoint=%s error=invalid_response_body", path)
                raise AlpacaRequestError("Alpaca sandbox returned an invalid response.") from None

        if resp.status_code in (401, 403):
            # Never retried -- a bad/revoked credential will not become
            # valid by trying again, and retrying auth failures is exactly
            # the kind of behavior that could trip Alpaca's own abuse
            # detection for no benefit.
            logger.warning("Alpaca request failed: endpoint=%s status=%s", path, resp.status_code)
            raise AlpacaRequestError("Alpaca sandbox rejected the configured credentials.")

        if resp.status_code == 429:
            logger.warning("Alpaca request failed: endpoint=%s status=429 error=rate_limited", path)
            raise AlpacaRequestError("Alpaca sandbox rate limit was reached. Please try again shortly.")

        if resp.status_code >= 500 and attempt <= MAX_RETRIES:
            logger.warning(
                "Alpaca request server error, retrying: endpoint=%s status=%s attempt=%s",
                path, resp.status_code, attempt,
            )
            continue

        logger.warning("Alpaca request failed: endpoint=%s status=%s", path, resp.status_code)
        raise AlpacaRequestError(f"Alpaca sandbox request failed (status {resp.status_code}).")


# ---------------------------------------------------------------------------
# Sanitization -- the only way account data is allowed to leave this module
# ---------------------------------------------------------------------------

# Deliberately an allowlist, not a denylist: a new field Alpaca adds to
# their account object in the future is excluded by default, not included
# by default. Every one of these is operational/status metadata, never
# identity, contact, disclosure, agreement, document, or trusted-contact
# data (all of which Alpaca's real account object also carries, and none
# of which this integration is permitted to surface -- see module
# docstring's safety rule #3).
_ACCOUNT_SAFE_FIELDS = (
    "id",
    "account_number",
    "status",
    "crypto_status",
    "currency",
    "created_at",
    "account_type",
)


def _sanitize_account(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {field: raw.get(field) for field in _ACCOUNT_SAFE_FIELDS if field in raw}


# ---------------------------------------------------------------------------
# Public API used by backend/routes/alpaca.py
# ---------------------------------------------------------------------------


def check_connectivity() -> dict[str, Any]:
    """Proves Alpaca sandbox credentials/connectivity work WITHOUT
    disclosing any brokerage account information -- the response is a
    fixed, fully sanitized shape regardless of how many accounts exist or
    what they contain. This is the only thing backend/routes/alpaca.py's
    connectivity-diagnostic endpoint is allowed to return.

    Raises AlpacaConfigError / AlpacaRequestError on failure -- the route
    handler is responsible for turning those into a safe HTTP response.
    """
    # limit=1 only to keep the upstream call itself cheap -- the count is
    # discarded entirely below, never returned, never logged.
    _alpaca_get("/v1/accounts", params={"limit": 1})
    return {"ok": True, "sandbox_reachable": True}


def list_accounts_sanitized(limit: int = 25) -> list[dict[str, Any]]:
    """Returns a sanitized, structured list of sandbox accounts (see
    _sanitize_account) for authorized internal testing only -- the caller
    (backend/routes/alpaca.py) is responsible for ensuring the request is
    both authenticated AND separately authorized for internal testing
    before ever calling this. Never a per-Zoey-user listing -- Alpaca's
    GET /v1/accounts is the BROKER's own account list, not scoped to any
    one end customer, which is exactly why this must not be exposed to
    ordinary authenticated users (see backend/routes/alpaca.py's own
    docstring)."""
    limit = max(1, min(int(limit), 100))
    payload = _alpaca_get("/v1/accounts", params={"limit": limit})
    if not isinstance(payload, list):
        return []
    return [_sanitize_account(item) for item in payload if isinstance(item, dict)]
