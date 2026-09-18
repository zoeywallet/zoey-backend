"""
Email-verification tokens: generation, hashing, and expiry checking.

A verification link (GET /api/auth/verify-email?token=...) has to prove two
things: that it was genuinely issued by this server (not guessed), and that
it hasn't expired or already been used. The token itself is a long random
string handed to the user inside the emailed link; only its SHA-256 HASH is
ever stored in the database (see backend/models.py's
User.email_verify_token_hash and backend/database.py's
set_email_verification_token) -- mirroring how password_hash never stores a
real password. If the database were ever read by someone unauthorized (a
backup leak, a misconfigured admin tool), they would see that some token was
issued, not a value that lets them mint a working verification link.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

# How long a freshly-issued verification link stays valid. An env var (with
# a sane default) for the same reason SESSION_TTL_HOURS is one in
# backend/auth.py -- an operator may reasonably want this tunable without a
# code change -- and because a hardcoded "forever" link is exactly what the
# spec this was built from explicitly ruled out ("no permanent links").
EMAIL_VERIFY_TTL_HOURS = float(os.environ.get("EMAIL_VERIFY_TTL_HOURS", "24"))

_TOKEN_BYTES = 32  # 256 bits of entropy in the raw token -- not guessable/brute-forceable.


def generate_verification_token() -> tuple[str, str, datetime]:
    """Returns (raw_token, token_hash, expires_at).

    raw_token is what actually goes in the emailed link -- it is never
    stored anywhere, only returned here so the caller can put it straight
    into an email and then forget it. token_hash is what
    backend/database.py's set_email_verification_token() persists.
    expires_at is timezone-aware UTC, ready to store directly in
    User.email_verify_expires_at."""
    raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
    token_hash = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=EMAIL_VERIFY_TTL_HOURS)
    return raw_token, token_hash, expires_at


def hash_token(raw_token: str) -> str:
    """SHA-256 is the appropriate choice here (unlike password hashing,
    which deliberately uses the slow scrypt in backend/auth.py) because this
    token already IS 256 bits of uniform random entropy -- there's no
    guessable structure or human-chosen pattern for an attacker to
    dictionary/rainbow-table against, so a slow KDF would only add cost with
    no real security benefit. What actually protects this token is its
    length/randomness and its expiry, not the hash algorithm's slowness."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def is_expired(expires_at: datetime | None) -> bool:
    """True if this token's expiry has already passed, OR if expires_at is
    missing entirely. A row with no recorded expiry is treated as expired,
    never as "never expires" -- there is no legitimate state where a real
    verification token exists without an expiry alongside it (see
    set_email_verification_token, which always sets both together)."""
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        # Defensive only: every column this reads from is a tz-aware
        # TIMESTAMP WITH TIME ZONE / SQLite DATETIME populated via this
        # module's own timezone-aware datetimes, so a naive value shouldn't
        # occur in practice -- but comparing naive-vs-aware datetimes raises
        # TypeError rather than just being wrong, and a raised exception
        # here would surface as a 500 on someone's verification-link click,
        # which is worse than treating an unexpected naive value as UTC.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= expires_at
