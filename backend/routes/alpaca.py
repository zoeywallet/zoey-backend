"""
Authenticated, READ-ONLY Alpaca Broker API Sandbox routes.

Day 1 scope only (see the approved Zoey Wallet Alpaca + Zoey AI inspection
report): a connectivity diagnostic and a sandbox account listing. Nothing
here creates a brokerage account, submits an order, or simulates a
deposit/withdrawal -- backend/services/alpaca.py (the only module this file
calls into) doesn't expose anything beyond those two read operations
either.

Routes:
    GET /api/alpaca/healthz   connectivity check -- returns ONLY
                              {"ok": bool, "sandbox_reachable": bool},
                              never any brokerage account data, regardless
                              of caller. Gated behind BOTH normal Zoey
                              authentication AND the same internal-testing
                              key as /accounts below (see
                              _require_internal_test_access) -- restricted
                              to authorized internal testers, not merely
                              any signed-in user, per the current phase of
                              this integration.
    GET /api/alpaca/accounts  sandbox account listing, SANITIZED (see
                              backend/services/alpaca.py's
                              _ACCOUNT_SAFE_FIELDS) -- gated behind BOTH
                              normal Zoey authentication AND the same
                              internal-testing key (see
                              _require_internal_test_access below).

Why BOTH routes need a second gate beyond "signed in": Alpaca's
GET /v1/accounts is the BROKER's own account list -- every sandbox account
under Zoey's Alpaca correspondent, not scoped to any one end customer.
There is today no verified mapping from a Zoey user to a specific Alpaca
account (see backend/models.py's BrokerageAccount docstring + the
inspection report's database section) -- the mapping table doesn't exist
yet. Until it does, there is no safe way to let an ordinary authenticated
Zoey user call /accounts and automatically get only "their" account,
because there is no "their account" to scope to -- exposing the broker's
full account list to any logged-in Zoey user would leak every *other*
sandbox account's (sanitized, but still not theirs) data to them, exactly
what the approved plan says never to do. /healthz doesn't leak account
data even to an ordinary user (its response is a fixed, content-free
shape -- see backend/services/alpaca.py's check_connectivity), but it was
tightened to the same gate anyway: during active sandbox testing, even a
"does this work" probe against a live, rate-limited, real external API
should be limited to people actually doing that testing, not every
ordinary signed-in Zoey user, so the same ADMIN_KEY-based gate (an env var
this project already reserved for exactly this kind of use -- see
.env.example) now applies to both routes until a real per-user mapping
exists and a follow-up change can scope /accounts properly.

Registration: api/index.py includes this router ONLY when
backend.services.alpaca.ALPACA_ENABLED is true (see that module), so with
the flag unset/false (the default) these two routes do not exist at all --
not "exist but refuse," actually absent from the route table.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Cookie, Depends, Header
from fastapi.responses import JSONResponse

from backend.auth import decode_access_token
from backend.services import alpaca as alpaca_service

router = APIRouter(prefix="/api/alpaca", tags=["alpaca"])


def _get_current_claims(zw_session: str | None = Cookie(default=None)) -> dict | None:
    """Deliberately an independent copy of api/index.py's
    get_current_claims (same cookie, same decode_access_token call, same
    "never raises, caller decides what None means" contract) -- NOT
    imported from api/index.py, to avoid a circular import (api/index.py
    is what includes this router) and to avoid touching that file's
    existing, already-approved auth code at all. If api/index.py's
    get_current_claims ever changes, this should be revisited to match,
    but nothing here depends on or alters that existing function."""
    return decode_access_token(zw_session)


def _unauthenticated() -> JSONResponse:
    return JSONResponse(status_code=401, content={"ok": False, "message": "Not signed in."})


def _require_signed_in_user_id(claims: dict | None) -> int | None:
    """Returns the integer user id from a valid claims dict, or None if
    the caller isn't validly signed in (missing/invalid/expired cookie, or
    a malformed `sub`). Every route below treats None the same way --
    401, no further processing -- matching api/index.py's existing
    GET /api/dashboard pattern exactly."""
    if claims is None:
        return None
    try:
        return int(claims["sub"])
    except (KeyError, TypeError, ValueError):
        return None


def _require_internal_test_access(provided_key: str | None) -> JSONResponse | None:
    """Second gate for BOTH /api/alpaca/healthz and /api/alpaca/accounts
    -- see module docstring for why each endpoint needs more than "signed
    in." Reuses ADMIN_KEY,
    an env var this project already reserved (.env.example: "no route in
    this FastAPI backend currently reads ADMIN_KEY ... set here now so
    it's ready if that feature gets built later") for exactly this kind of
    internal-only operation -- a new env var was not introduced for this.

    Fails CLOSED: if ADMIN_KEY is not set at all, this endpoint is
    unreachable by anyone (503), rather than treating "no key configured"
    as "no check needed." Comparison is a plain equality check against a
    server-side-only value; the provided key is never logged."""
    admin_key = os.environ.get("ADMIN_KEY", "")
    if not admin_key:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "message": "Internal testing access is not configured."},
        )
    if not provided_key or provided_key != admin_key:
        return JSONResponse(
            status_code=403,
            content={"ok": False, "message": "Not authorized for this endpoint."},
        )
    return None


@router.get("/healthz")
def alpaca_healthz(
    claims: dict | None = Depends(_get_current_claims),
    x_zoey_admin_key: str | None = Header(default=None),
):
    """Restricted to authorized internal testers (same ADMIN_KEY gate as
    /accounts) -- not merely any signed-in Zoey user. See module
    docstring for why this was tightened from "just signed in" during
    this phase."""
    user_id = _require_signed_in_user_id(claims)
    if user_id is None:
        return _unauthenticated()
    gate_error = _require_internal_test_access(x_zoey_admin_key)
    if gate_error is not None:
        return gate_error
    try:
        result = alpaca_service.check_connectivity()
    except alpaca_service.AlpacaConfigError as exc:
        return JSONResponse(status_code=503, content={"ok": False, "message": str(exc)})
    except alpaca_service.AlpacaRequestError as exc:
        return JSONResponse(status_code=502, content={"ok": False, "message": str(exc)})
    return {"ok": True, **result}


@router.get("/accounts")
def alpaca_list_accounts(
    claims: dict | None = Depends(_get_current_claims),
    x_zoey_admin_key: str | None = Header(default=None),
):
    user_id = _require_signed_in_user_id(claims)
    if user_id is None:
        return _unauthenticated()
    gate_error = _require_internal_test_access(x_zoey_admin_key)
    if gate_error is not None:
        return gate_error
    try:
        accounts = alpaca_service.list_accounts_sanitized()
    except alpaca_service.AlpacaConfigError as exc:
        return JSONResponse(status_code=503, content={"ok": False, "message": str(exc)})
    except alpaca_service.AlpacaRequestError as exc:
        return JSONResponse(status_code=502, content={"ok": False, "message": str(exc)})
    return {"ok": True, "accounts": accounts}
