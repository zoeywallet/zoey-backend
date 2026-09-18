"""
CLI script to create (or reset the password of) a login account.

There is no self-serve signup in this project — same as the previous
Node version — so this is how you provision the account(s) you'll actually
log in with.

Usage (from the project root, with your virtualenv active):

    python -m backend.create_user you@example.com "a-real-password" "Your Name"

Re-running it for an email that already exists updates that user's
password instead of erroring — handy for resetting one by hand.

IMPORTANT: this script connects using whatever DATABASE_URL is set in your
current shell / .env file. To create a user in your PRODUCTION database
(the one Vercel is using), run this from your own machine with
DATABASE_URL temporarily set to your production Postgres connection
string — there is no way to run a one-off script "on Vercel" itself, since
Vercel only runs your app in response to HTTP requests.
"""

from __future__ import annotations

import re
import sys

# Same reasoning as api/index.py: load .env into os.environ BEFORE
# backend.auth / backend.database are imported, since those read
# DATABASE_URL / SECRET_KEY at import time. This lets you run
#   python -m backend.create_user ...
# against whatever DATABASE_URL your .env points at, without having to
# re-export it by hand in every terminal.
from dotenv import load_dotenv

load_dotenv()

from backend.auth import hash_password  # noqa: E402
from backend.database import SessionLocal, create_user, find_user_by_email, init_db, update_user_password  # noqa: E402

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        print('Error: expected at least: <email> <password> ["Full Name"]', file=sys.stderr)
        return 1

    email, password = args[0].strip(), args[1]
    name = args[2].strip() if len(args) > 2 else email.split("@")[0]

    if not _EMAIL_RE.match(email):
        print(f"Error: '{email}' doesn't look like a valid email address.", file=sys.stderr)
        return 1
    if len(password) < 8:
        print("Error: password must be at least 8 characters.", file=sys.stderr)
        return 1

    init_db()
    db = SessionLocal()
    try:
        existing = find_user_by_email(db, email)
        password_hash = hash_password(password)
        if existing:
            update_user_password(db, existing.id, password_hash)
            print(f"Updated password for existing account: {email} (id {existing.id})")
        else:
            # email_verified=True: this account is being created directly
            # against the database by the app's own owner running this
            # script -- a deliberate, trusted action, not the public
            # self-serve signup form (which starts accounts unverified and
            # emails a link -- see api/index.py's POST /api/auth/signup).
            # Since POST /api/login now refuses to authenticate an
            # unverified email/password account, leaving this False would
            # create an account nobody could ever actually log into.
            user = create_user(db, email=email, name=name, password_hash=password_hash, email_verified=True)
            print(f'Created account: {user.email} (id {user.id}, name "{user.name}")')
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
