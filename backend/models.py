"""
SQLAlchemy ORM models — the Python equivalent of the old db.js schema.

If you're used to Django models, this will feel familiar: each class below
is a table, each class attribute is a column. SQLAlchemy's declarative style
(the `Base` class + `Mapped[...]` type hints) is the modern (2.0+) way to
write this, and it gives you real Python types (str, int, datetime) instead
of hand-written SQL everywhere.

Two tables, matching the two things this app actually needs to persist:
  - User    — one row per login account (password_hash, never plaintext)
  - Lead    — one row per "Get started" form submission

There is intentionally NO "sessions" table here. The old Node backend
stored sessions in SQLite and looked them up on every request. That works
fine on a long-running server, but on Vercel your backend is a stack of
short-lived, independent function invocations — there's no guarantee two
requests even hit the same instance, and Vercel's own filesystem is
read-only/ephemeral outside of /tmp. Instead, this rewrite uses signed JWTs
(see backend/auth.py) as the "session": the token itself carries the
logged-in user's identity, cryptographically signed with SECRET_KEY, and is
handed to the browser as an httpOnly cookie. No server-side session storage
needed, which is exactly what a serverless deployment wants.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Every ORM model inherits from this. SQLAlchemy uses it to know which
    classes are tables it should know how to CREATE TABLE / query."""
    pass


class User(Base):
    """A login account. One row per person who can sign in to the dashboard.

    Accounts are created two ways: the self-serve signup flow
    (POST /api/auth/signup, see api/index.py) that backs the homepage's
    "Create your Zoey account" modal, or by hand with the `create_user` CLI
    script (backend/create_user.py) — the Python equivalent of the old
    `npm run create-user`, still useful for provisioning an account without
    going through the public form.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Never a plaintext password — see backend/auth.py's hash_password().
    # Stored as "scrypt:N:r:p:<salt-hex>:<hash-hex>", same design as before,
    # just implemented with Python's stdlib hashlib.scrypt instead of Node's
    # crypto.scryptSync.
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    # Both optional -- the signup form's phone/interest fields are optional,
    # same as the existing Lead model just below. Added alongside the
    # self-serve signup flow; see backend/database.py's `_ensure_user_columns`
    # for how these get added to an ALREADY-DEPLOYED users table in Neon
    # without dropping or recreating it.
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    interests: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Lead(Base):
    """One "Get started" form submission from the public website.

    `email` is UNIQUE — a repeat submission from the same address updates
    the existing row (latest info wins) and increments duplicate_count,
    rather than creating a second row. See backend/database.py's
    create_lead() for the exact upsert policy.
    """

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    interest: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Free-form extras the existing frontend still sends (country, the
    # country calling code, where on the site the form was, and the
    # browser's own submitted_at timestamp). Kept for continuity with the
    # working frontend rather than silently dropped; none of them are
    # required or validated.
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
