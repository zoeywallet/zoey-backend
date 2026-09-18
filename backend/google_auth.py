"""
Google Identity Services (OpenID Connect) verification.

This is the ONE piece of "Continue with Google" that must never be
hand-rolled: verifying a Google ID token's signature, issuer, audience, and
expiry. That's exactly what the maintained `google-auth` library's
`google.oauth2.id_token.verify_oauth2_token()` does, using Google's own
current public signing keys (fetched from Google's JWKS endpoint and
cached/rotated by the library) -- this module is a thin wrapper around that
one call, not a reimplementation of JWT/JWKS verification.

Every other place in this codebase that needs to know "did Google actually
vouch for this person, and what's their stable identity + verified email"
calls verify_google_id_token() below and only ever sees its return value (a
GoogleIdentity, or a raised GoogleAuthError) -- never the raw
`response.credential` JWT payload, and never a hand-decoded/unverified copy
of it. This is deliberately a single, small, swappable seam: the
account-linking, session-issuance, and error-handling logic that surrounds
it (in api/index.py) can be exercised in a test by substituting a fake for
just this one function, without needing a real Google credential or the
google-auth package physically installed to test everything else.

Scope note: this is authentication only. The verified claims used here are
limited to `sub` (Google's permanent, unchangeable user id -- the actual
join key, see backend/database.py's google_sub column), `email` +
`email_verified`, and `name`. Nothing here requests or touches Gmail,
Drive, Calendar, or Contacts access -- the frontend's
google.accounts.id.initialize() (see index.html/login.html) only ever asks
for the default OpenID Connect scope (identity), never a broader OAuth
scope.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# The frontend's Google Identity Services JS library also needs this same
# value (see index.html/login.html's `GOOGLE_CLIENT_ID` constant) -- a
# Google OAuth client ID is not a secret; Google's own docs describe it as
# safe to expose in client-side code, since it only identifies which app is
# asking, not a credential that authorizes anything by itself. What MUST
# stay server-side is this verification step: checking that a given
# credential's *audience* claim actually matches this client ID (done
# inside verify_google_id_token below) -- something a browser can be
# tricked into skipping, but a server-side check cannot.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")


@dataclass(frozen=True)
class GoogleIdentity:
    """What this app is allowed to know about a person after Google itself
    has vouched for them. Nothing here comes from the browser unchecked --
    every field is a claim out of a signature-verified token."""

    sub: str  # Google's permanent, stable user id -- see backend/models.py's User.google_sub.
    email: str
    email_verified: bool  # Google's own claim -- see the account-linking policy in api/index.py.
    name: str


class GoogleAuthError(Exception):
    """Raised for ANY reason a Google credential can't be trusted: bad
    signature, wrong audience, expired, malformed, wrong issuer, or the
    server itself not being configured for Google sign-in yet. Callers
    (api/index.py's POST /api/auth/google) catch this and show the user the
    generic "We couldn't complete Google sign-in. Please try again."
    message -- the specific reason is for server-side logs only, the same
    non-leaking posture as backend/email_sender.py's SMTP errors."""


def verify_google_id_token(credential: str) -> GoogleIdentity:
    """Verifies a Google ID token -- the credential string Google's
    Identity Services JS library hands the frontend after a successful
    sign-in (see index.html/login.html's `handleGoogleCredential`) -- and
    returns the identity it vouches for, or raises GoogleAuthError.

    `google.oauth2.id_token.verify_oauth2_token(credential, request, GOOGLE_CLIENT_ID)`
    itself:
      - Verifies the token's signature against Google's current public
        keys.
      - Confirms the issuer is exactly "accounts.google.com" or
        "https://accounts.google.com".
      - Confirms the token's audience matches GOOGLE_CLIENT_ID -- without
        this check, a token Google issued for a completely different app
        could be replayed here to impersonate a Zoey sign-in.
      - Confirms the token has not expired.

    This function never returns a half-trusted identity: any failure at
    any of the above raises GoogleAuthError instead.
    """
    if not GOOGLE_CLIENT_ID:
        raise GoogleAuthError(
            "GOOGLE_CLIENT_ID is not configured on the server -- Google sign-in cannot "
            "be verified without it. Set it in .env for local dev, or as a Vercel "
            "Environment Variable in production."
        )

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as exc:
        # google-auth is listed in requirements.txt but may not be
        # installed in every environment this code runs in (see the
        # sandbox limitation noted in this project's implementation
        # report) -- fail with a clear, actionable message rather than a
        # bare ImportError traceback reaching the HTTP layer.
        #
        # Preserve the *actual* ImportError text (exc) rather than always
        # emitting the same generic sentence -- this is what actually
        # distinguishes "google-auth itself is absent" from "google-auth is
        # present but one of its own transitive dependencies (cachetools,
        # pyasn1, pyasn1-modules, rsa) failed to import", which otherwise
        # look identical in the logs.
        raise GoogleAuthError(
            f"google-auth import failed ({exc.__class__.__name__}: {exc}). "
            "Install project dependencies with: pip install -r requirements.txt"
        ) from exc

    try:
        claims = id_token.verify_oauth2_token(credential, google_requests.Request(), GOOGLE_CLIENT_ID)
    except ValueError as exc:
        # google-auth deliberately raises a plain ValueError for every kind
        # of verification failure (bad signature, wrong audience, expired,
        # malformed input) -- there is no finer-grained exception type to
        # distinguish them by.
        raise GoogleAuthError(f"Google credential failed verification: {exc}") from exc

    sub = claims.get("sub")
    email = claims.get("email")
    email_verified = bool(claims.get("email_verified", False))
    name = (claims.get("name") or "").strip() or (email.split("@")[0] if email else "Zoey user")

    if not sub or not email:
        raise GoogleAuthError("Google credential is missing required claims (sub/email).")

    return GoogleIdentity(sub=sub, email=email, email_verified=email_verified, name=name)
