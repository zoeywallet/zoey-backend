"""
Sends the app's own transactional email (right now: just the "verify your
email" message) via Gmail SMTP, reusing this project's EXISTING env var
names (GMAIL_USER / GMAIL_APP_PASSWORD) rather than inventing new ones --
those two were already present in .env / .env.example, added earlier for a
lead-notification feature that was never built, and are reused here exactly
as they are: GMAIL_USER doubles as both the SMTP login name and the "From"
address (Gmail requires the From address to be the authenticated account or
one of its verified aliases anyway, so there's no separate EMAIL_FROM to
configure).

This module deliberately has ONLY authentication-adjacent scope: it sends
mail that this server itself composes and signs (a verification link), via
plain SMTP credentials. It does not use the Gmail API, does not request any
Gmail/Drive/Calendar/Contacts OAuth scope, and has nothing to do with the
separate "Continue with Google" SIGN-IN feature in backend/google_auth.py --
that's Google *identity* verification (who is this person), this is Zoey's
own outbound mail (an email *to* that person). See backend/google_auth.py's
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

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587  # STARTTLS, not implicit TLS (465) -- Gmail's documented default for app passwords.


def is_email_configured() -> bool:
    """True once real Gmail credentials are present. Both GMAIL_USER and
    GMAIL_APP_PASSWORD are blank in this project's .env today (per its own
    "configure later" comment) -- callers use this to decide whether to even
    attempt a send, and to log a clear, specific reason rather than an SMTP
    stack trace when nothing is configured yet."""
    return bool(GMAIL_USER and GMAIL_APP_PASSWORD)


def send_verification_email(*, to_email: str, name: str, verify_url: str) -> bool:
    """Sends the "verify your email" message. Returns True if the message
    was handed off to Gmail's SMTP server successfully, False otherwise --
    never raises. A False return means the caller should tell the user
    something went wrong (without SMTP internals) and that they can use
    "resend verification email" to try again once delivery is fixed."""
    if not is_email_configured():
        logger.error(
            "send_verification_email: GMAIL_USER/GMAIL_APP_PASSWORD are not "
            "configured (both blank) -- cannot send to %s. Set both in .env "
            "for local dev, or as Vercel Environment Variables in production.",
            to_email,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = "Verify your email for Zoey Wallet"
    msg["From"] = GMAIL_USER
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
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
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
