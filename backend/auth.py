"""
Password hashing + stateless session tokens (JWT).

Two unrelated jobs live in this one file because they're both "the auth
system" from a caller's point of view:

1. hash_password() / verify_password()
   Turns a password into something safe to store, using Python's stdlib
   `hashlib.scrypt` — no extra dependency, no C-extension wheel to worry
   about on Vercel's build image. This is functionally the same algorithm
   the previous Node backend used (`crypto.scryptSync`), just called
   through Python's own standard library. A password is NEVER stored or
   logged in plaintext; only the output of this function touches the
   database (see backend/models.py's User.password_hash column).

2. create_access_token() / decode_access_token()
   Issues and verifies a JWT (JSON Web Token) — a signed, tamper-proof
   string that says "this is user #4 (a@b.com), and this claim is valid
   until <timestamp>". It's signed with SECRET_KEY (an environment
   variable), so anyone holding it can prove who they are without the
   server needing to look anything up in a database or in-memory store.

   Why JWTs instead of the previous design (a `sessions` table you look up
   on every request)? Because Vercel runs this app as a stack of
   short-lived, independent function invocations with no shared memory and
   no persistent local disk. A JWT carries its own proof of validity, so
   there's nothing to "look up" — which is exactly what a stateless
   serverless deployment wants. The trade-off, to be upfront about it:
   logging out means the browser stops sending the cookie, not that the
   token is cryptographically destroyed — if someone had stolen a copy of
   the raw token before logout, it would still verify until it expires
   (SESSION_TTL_HOURS). That's a standard, accepted trade-off for
   short-lived tokens (a few hours to a few days) over HTTPS-only cookies;
   if you later want true server-side revocation, the fix is storing
   sessions in Postgres (the same DATABASE_URL this project already uses)
   and checking a "revoked" flag on each request — a small, well-understood
   change, not mentioned further here because it isn't needed yet.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt  # PyJWT

# ---------------------------------------------------------------------------
# Password hashing (scrypt, stdlib-only)
# ---------------------------------------------------------------------------

_SCRYPT_N = 2**14  # CPU/memory cost factor
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_LEN = 32


def hash_password(password: str) -> str:
    """Returns a string safe to store in User.password_hash, in the form
    "scrypt:N:r:p:<salt-hex>:<hash-hex>". The cost parameters travel with
    the hash itself, so they can be tuned later (e.g. raising N as hardware
    gets faster) without breaking verification of passwords hashed under
    the old parameters."""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_LEN
    )
    return f"scrypt:{_SCRYPT_N}:{_SCRYPT_R}:{_SCRYPT_P}:{salt.hex()}:{derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Re-derives the hash using the SAME salt and cost parameters recorded
    inside stored_hash, then compares in constant time (hmac.compare_digest)
    so that how-many-bytes-matched can't leak through response timing."""
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored_hash.split(":")
        if scheme != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        # Malformed/unexpected stored_hash — never raise from here, just
        # treat it as "does not match" so a bad DB row can't crash a login.
        return False

    candidate = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected))
    return hmac.compare_digest(candidate, expected)


# ---------------------------------------------------------------------------
# JWT session tokens
# ---------------------------------------------------------------------------

SECRET_KEY = os.environ.get("SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
SESSION_TTL_HOURS = float(os.environ.get("SESSION_TTL_HOURS", "168"))  # 7 days, same default as before
COOKIE_NAME = "zw_session"


def _require_secret_key() -> str:
    if not SECRET_KEY:
        # Fail loudly rather than silently signing tokens with an empty/
        # predictable key — an empty SECRET_KEY would make every issued
        # token forgeable. This should only ever happen if someone forgot
        # to set the environment variable.
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. Generate one with: "
            "python -c \"import secrets; print(secrets.token_hex(32))\" "
            "and set it locally in .env and in your Vercel project settings."
        )
    return SECRET_KEY


def create_access_token(*, user_id: int, email: str, name: str, remember: bool = False) -> str:
    """Returns a signed JWT string encoding who this user is. `remember`
    doesn't change the token's own expiry (SESSION_TTL_HOURS is the same
    either way, matching the previous design) — it only affects how long
    the *cookie* persists in the browser; see set_session_cookie() below."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "iat": now,
        "exp": now + timedelta(hours=SESSION_TTL_HOURS),
    }
    return jwt.encode(payload, _require_secret_key(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Returns the token's claims dict if the signature and expiry are
    valid, or None otherwise (never raises — every caller treats None as
    'not logged in')."""
    if not token:
        return None
    try:
        return jwt.decode(token, _require_secret_key(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
