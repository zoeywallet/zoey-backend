"""
Database access layer — every database operation the app is allowed to
perform lives here, as an explicitly-named function. Nothing outside this
file ever writes raw SQL or touches a SQLAlchemy Session directly.

This is a deliberate reaction to the exact bug that broke the previous
deployment: server.js called `db.listUsers()`, a function that had never
been defined anywhere in db.js. Because JavaScript doesn't check at
"compile time" that a function exists, that typo only surfaced when a real
request hit it in production, as a crash. Python doesn't fully save you
from that (it's not statically typed either at runtime), but by keeping
every DB operation as one clearly-named, single-purpose function in one
file, it becomes trivial to `grep` for a name before calling it, and the
test suite (tests/test_api.py) exercises every one of them.

Functions defined here:
    create_user(db, email, name, password_hash)
    find_user_by_email(db, email)
    get_user_by_id(db, user_id)
    update_user_password(db, user_id, password_hash)
    list_users(db)
    create_lead(db, name, email, phone, interest, country, country_code, source)
    list_leads(db, limit, offset)
    count_leads(db)

Every one of these takes a SQLAlchemy `Session` as its first argument
(conventionally named `db`) — see get_db() below for where that comes from.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Optional

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.models import Base, Lead, User

# ---------------------------------------------------------------------------
# Engine setup
# ---------------------------------------------------------------------------
#
# DATABASE_URL controls everything:
#
#   - Not set at all (local dev, zero setup)
#       -> falls back to a SQLite file (./local.db) next to the project.
#          Fine for developing on your own laptop. NOT used in production —
#          Vercel's filesystem is read-only outside of /tmp, and /tmp is
#          wiped between invocations, so SQLite there would silently lose
#          data (or corrupt under concurrent requests). This is exactly the
#          "assume a persistent SQLite database inside the Vercel deployment
#          filesystem" mistake the migration spec called out to avoid.
#
#   - Set to a real Postgres URL (production, i.e. on Vercel)
#       e.g. postgresql+psycopg://user:password@host:5432/dbname
#       Any managed Postgres works: Vercel Postgres / Neon / Supabase all
#       hand you a connection string in this shape. Set it as an
#       environment variable in the Vercel project settings — never commit
#       it to the repo.
#
# SQLAlchemy's engine is what actually knows how to talk to either database
# through the *same* Python code above (backend/database.py never needs an
# `if postgres: ... else: ...` branch) — that's the whole point of using an
# ORM/Core layer instead of hand-rolling sqlite3 vs. psycopg calls.

DATABASE_URL = os.environ.get("DATABASE_URL") or "sqlite:///./local.db"

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    # SQLite's default driver refuses to share a connection across threads;
    # FastAPI/Starlette can (and does) run request handlers on different
    # worker threads, so this flag is required for local dev to work at all.
    _connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create tables if they don't exist yet. Safe to call on every cold
    start — CREATE TABLE IF NOT EXISTS semantics, so it's a no-op once the
    schema is already there (this mirrors what db.js did with its
    `CREATE TABLE IF NOT EXISTS` statements)."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: `db: Session = Depends(get_db)` in a route handler
    gets you a fresh Session for that one request, and this generator closes
    it afterwards no matter what (success or exception) via the `finally`.
    This is the standard FastAPI + SQLAlchemy pattern — if you've used
    Flask's `g` object or Django's implicit per-request connection, this
    `Depends(get_db)` is doing the same job, just explicit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(db: Session, *, email: str, name: str, password_hash: str) -> User:
    """Insert a new user row. Raises sqlalchemy.exc.IntegrityError if the
    email is already taken (the `unique=True` on User.email enforces this at
    the database level, not just in Python)."""
    user = User(email=email.lower().strip(), name=name, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def find_user_by_email(db: Session, email: str) -> Optional[User]:
    """Returns the User row for this email, or None if no such account
    exists. Callers must not assume the return value is not None."""
    stmt = select(User).where(User.email == email.lower().strip())
    return db.execute(stmt).scalar_one_or_none()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.get(User, user_id)


def update_user_password(db: Session, user_id: int, password_hash: str) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise ValueError(f"No user with id={user_id}")
    user.password_hash = password_hash
    db.commit()


def list_users(db: Session) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc())
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

def create_lead(
    db: Session,
    *,
    name: str,
    email: str,
    phone: str | None = None,
    interest: str | None = None,
    country: str | None = None,
    country_code: str | None = None,
    source: str | None = None,
) -> tuple[Lead, bool]:
    """Insert a new lead, or — if this email has already submitted before —
    update the existing row with the latest info and bump duplicate_count.

    Returns (lead, is_new). is_new is False for a resubmission from an
    email already on file; the frontend still shows the same success
    screen either way (a returning visitor should never see an error), but
    it lets a caller decide whether e.g. a notification email is warranted.
    """
    email = email.lower().strip()
    existing = db.execute(select(Lead).where(Lead.email == email)).scalar_one_or_none()

    if existing is None:
        lead = Lead(
            name=name,
            email=email,
            phone=phone,
            interest=interest,
            country=country,
            country_code=country_code,
            source=source,
            duplicate_count=0,
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead, True

    existing.name = name
    existing.phone = phone or existing.phone
    existing.interest = interest or existing.interest
    existing.country = country or existing.country
    existing.country_code = country_code or existing.country_code
    existing.source = source or existing.source
    existing.duplicate_count += 1
    db.commit()
    db.refresh(existing)
    return existing, False


def list_leads(db: Session, *, limit: int = 500, offset: int = 0) -> list[Lead]:
    stmt = select(Lead).order_by(Lead.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def count_leads(db: Session) -> int:
    return db.execute(select(func.count()).select_from(Lead)).scalar_one()
