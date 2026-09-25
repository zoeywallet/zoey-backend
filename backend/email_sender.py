"""
Sends the app's own transactional email (right now: just the "verify your
email" message) via SMTP, using provider-neutral environment variable
names -- SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM -- so
this module works against any STARTTLS-capable SMTP provider rather than
being hard-wired to one. SMTP_USER is the SMTP login name; SMTP_FROM is
the address that appears in the "From" header. They're kept as two
separate settings (rather than reusing SMTP_USER for both, as the earlier
Gmail-specific implementation did) since not every provider requires the
authenticated account and the From address to be identical -- some allow
sending as a verified alias distinct from the login name.

This module deliberately has ONLY authentication-adjacent scope: it sends
mail that this server itself composes and signs (a verification link), via
plain SMTP credentials. It does not use any provider's HTTP API, does not
request any OAuth scope, and has nothing to do with the separate
"Continue with Google" SIGN-IN feature in backend/google_auth.py -- that's
Google *identity* verification (who is this person), this is Zoey's own
outbound mail (an email *to* that person). See backend/google_auth.py's
own docstring for the identity side.

Every function here fails soft: a misconfigured or down mail server must
never crash the request that triggered it (a signup, a resend). Technical
detail (the real SMTP exception) is logged server-side only; nothing about
*why* delivery failed is ever returned to the caller/HTTP response -- see
api/index.py's use of these functions for the generic
"we couldn't send the verification email" message shown to the user instead.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("zoey.email")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "")


def _parse_smtp_port(raw: str) -> int | None:
    """Safely converts the SMTP_PORT env var (always a string, since env
    vars are strings) to an int. Returns None -- rather than raising, or
    silently falling back to a guessed port -- for anything that isn't a
    valid integer, so a typo'd SMTP_PORT reliably shows up as "not
    configured" (see is_email_configured() below) instead of either
    crashing this module's import or quietly trying to connect on the
    wrong port."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# STARTTLS, not implicit TLS (465) -- this project's confirmed SMTP
# configuration uses STARTTLS on 587, and that's what the send below
# performs regardless of what SMTP_PORT is set to.
SMTP_PORT = _parse_smtp_port(os.environ.get("SMTP_PORT", "587"))


def is_email_configured() -> bool:
    """True once real SMTP configuration is present: SMTP_HOST, SMTP_USER,
    SMTP_PASSWORD, and SMTP_FROM must all be non-blank, and SMTP_PORT must
    have parsed to a valid integer. Callers use this to decide whether to
    even attempt a send, and to log a clear, specific reason rather than an
    SMTP stack trace when nothing is configured yet."""
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and SMTP_FROM and SMTP_PORT is not None)


def send_verification_email(*, to_email: str, name: str, verify_url: str) -> bool:
    """Sends the "verify your email" message. Returns True if the message
    was handed off to the configured SMTP server successfully, False
    otherwise -- never raises. A False return means the caller should tell
    the user something went wrong (without SMTP internals) and that they
    can use "resend verification email" to try again once delivery is
    fixed."""
    if not is_email_configured():
        logger.error(
            "send_verification_email: SMTP is not fully configured "
            "(SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/SMTP_FROM) -- "
            "cannot send to %s. Set all five in .env for local dev, or as "
            "Vercel Environment Variables in production.",
            to_email,
        )
        # Temporary diagnostic: logs ONLY whether each of the five SMTP_*
        # settings is present (True/False) -- never their actual values,
        # never the password, username, host, or any email address. Safe
        # to leave in server-side logs; remove once the missing/misscoped
        # variable is identified.
        logger.error(
            "send_verification_email: presence check -- "
            "SMTP_HOST=%s SMTP_PORT=%s SMTP_USER=%s SMTP_PASSWORD=%s SMTP_FROM=%s",
            bool(SMTP_HOST), SMTP_PORT is not None, bool(SMTP_USER), bool(SMTP_PASSWORD), bool(SMTP_FROM),
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = "Verify your email for Zoey Wallet"
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg.set_content(
        f"Hi {name},\n\n"
        f"Click the link below to verify your email address for Zoey Wallet:\n\n"
        f"{verify_url}\n\n"
        f"This link expires in a few hours. If you didn't create a Zoey Wallet "
        f"account, you can safely ignore this email.\n\n"
        f"— Zoey Wallet"
    )
    msg.add_alternative(
        f"""\
<html>
  <body style="font-family: -apple-system, Helvetica, Arial, sans-serif; color: #111; line-height: 1.5;">
    <p>Hi {name},</p>
    <p>Click the button below to verify your email address for Zoey Wallet:</p>
    <p>
      <a href="{verify_url}"
         style="display: inline-block; background: #111; color: #fff; text-decoration: none;
                padding: 12px 24px; border-radius: 6px; font-weight: 600;">
        Verify email
      </a>
    </p>
    <p style="color: #666; font-size: 13px;">
      Or paste this link into your browser: <br>{verify_url}
    </p>
    <p style="color: #666; font-size: 13px;">
      This link expires in a few hours. If you didn't create a Zoey Wallet
      account, you can safely ignore this email.
    </p>
    <p>— Zoey Wallet</p>
  </body>
</html>
""",
        subtype="html",
    )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception:
        # Never let a mail-server hiccup surface as a 500 on someone's
        # signup request, and never leak SMTP internals (server responses
        # can include the account's own login name, connection details,
        # etc.) into the HTTP response -- log the full exception here, for
        # an operator to read, and let the caller show its own generic
        # message.
        logger.exception("send_verification_email: failed to send to %s", to_email)
        return False
