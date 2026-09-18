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
    create_user(db, email, name, password_hash, phone=None, interests=None)
    find_user_by_email(db, email)
    get_user_by_id(db, user_id)
    update_user_password(db, user_id, password_hash)
    list_users(db)
    find_user_by_google_sub(db, google_sub)
    create_google_user(db, email, name, google_sub)
    link_google_identity(db, user, google_sub)
    set_email_verification_token(db, user, token_hash, expires_at)
    find_user_by_verification_token_hash(db, token_hash)
    set_email_verified(db, user)
    create_lead(db, name, email, phone, interest, country, country_code, source)
    list_leads(db, limit, offset)
    count_leads(db)

Every one of these takes a SQLAlchemy `Session` as its first argument
(conventionally named `db`) — see get_db() below for where that comes from.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

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

# Vercel's Neon integration (and most managed-Postgres providers) hand back
# DATABASE_URL in Postgres' own native URI form -- "postgres://..." or bare
# "postgresql://..." -- not SQLAlchemy's dialect+driver spelling. SQLAlchemy
# resolves the driver from the URL scheme the moment create_engine() is
# called, so left as-is this fails immediately at import time: "postgres://"
# isn't a dialect SQLAlchemy knows at all, and bare "postgresql://" defaults
# to the psycopg2 driver, which isn't installed (this project uses psycopg 3
# -- see requirements.txt). Rewriting just the scheme/driver here -- leaving
# the host, credentials, database name, and query string (e.g. Neon's
# ?sslmode=require) untouched -- points SQLAlchemy at the psycopg 3 driver
# that's actually installed, without touching DATABASE_URL itself as Vercel
# set it.
if DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = make_url(DATABASE_URL).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)

_connect_args = {}
_engine_kwargs: dict = {}
if DATABASE_URL.startswith("sqlite"):
    # SQLite's default driver refuses to share a connection across threads;
    # FastAPI/Starlette can (and does) run request handlers on different
    # worker threads, so this flag is required for local dev to work at all.
    _connect_args["check_same_thread"] = False
elif DATABASE_URL.startswith("postgresql+psycopg://"):
    # Vercel's Neon integration hands back a *pooled* connection string
    # (PgBouncer, in transaction-pooling mode). psycopg 3 uses server-side
    # prepared statements by default, but a transaction-pooling PgBouncer
    # can route consecutive statements from the same "prepared" session to
    # different backend Postgres connections -- the prepared statement isn't
    # there on the connection PgBouncer picks next, which surfaces as
    # errors like "prepared statement ... does not exist" or
    # "DuplicatePreparedStatement". Setting prepare_threshold=None tells
    # psycopg to never promote a statement to a server-side prepared one,
    # which is the documented fix for using psycopg 3 behind a
    # transaction-pooling PgBouncer (i.e. Neon's pooled DATABASE_URL).
    _connect_args["prepare_threshold"] = None

    # Vercel's Python runtime sometimes reuses a "warm" function instance
    # (and therefore this same module-level `engine`) across multiple
    # invocations, minutes apart. SQLAlchemy's default pool (QueuePool)
    # would then hand a *previously opened* connection back to a later
    # request -- but Neon (and/or the PgBouncer pooler in front of it)
    # closes idle server-side connections after its own timeout, so that
    # reused connection's TLS session is already dead by the time the next
    # request tries to use it. That's exactly this bug's traceback:
    # "psycopg.OperationalError: consuming input failed: SSL connection
    # has been closed unexpectedly", raised the moment a stale pooled
    # connection is reused.
    #
    # NullPool makes every checkout open a brand-new physical connection
    # and closes it again as soon as the request finishes -- nothing is
    # ever kept alive (or reused) between invocations, so there is no
    # stale connection left for a later request to trip over. This is the
    # standard fix for SQLAlchemy + Postgres on serverless platforms.
    #
    # pool_pre_ping adds a second, cheaper line of defense: right before a
    # connection is handed out, SQLAlchemy pings it with a trivial query
    # and transparently reconnects if that fails (e.g. Neon's compute
    # briefly suspending/resuming mid-request), instead of surfacing the
    # error to the caller. With NullPool every connection is already new,
    # so this mostly matters for that suspend/resume edge case, not for
    # the stale-reuse bug above -- but it's a cheap, appropriate safety
    # net on top of NullPool, not a replacement for it.
    _engine_kwargs["poolclass"] = NullPool
    _engine_kwargs["pool_pre_ping"] = True

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create tables if they don't exist yet. Safe to call on every cold
    start — CREATE TABLE IF NOT EXISTS semantics, so it's a no-op once the
    schema is already there (this mirrors what db.js did with its
    `CREATE TABLE IF NOT EXISTS` statements)."""
    Base.metadata.create_all(bind=engine)
    _ensure_user_columns()
    _ensure_google_and_verification_columns()


def _ensure_user_columns() -> None:
    """Adds the `phone` and `interests` columns to an ALREADY-EXISTING
    `users` table if they aren't there yet.

    create_all() above only issues CREATE TABLE IF NOT EXISTS -- it never
    alters a table that already exists. These two columns were added to
    the User model alongside the self-serve signup flow (POST
    /api/auth/signup), after Neon's `users` table had already been created
    by an earlier deployment, so a plain create_all() would silently never
    add them. This is a small, additive, non-destructive ALTER TABLE that
    only runs when a column is actually missing -- it never touches
    existing rows, the `leads` table, or drops/recreates anything."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        # Table doesn't exist yet -- create_all() just created it (with
        # these columns already included via the model), so there's
        # nothing to add.
        return
    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    for column_name in ("phone", "interests"):
        if column_name in existing_columns:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} VARCHAR(200)"))


def _ensure_google_and_verification_columns() -> None:
    """Adds the Google sign-in + email verification columns to an
    ALREADY-EXISTING `users` table if they aren't there yet -- the same
    additive, non-destructive pattern as `_ensure_user_columns` above, run
    right after it. Never touches existing rows beyond backfilling the new
    columns themselves, never touches `leads`, never drops/recreates
    anything.

    Two things here need more care than a plain `ADD COLUMN`:

    1. `email_verified` is backfilled to TRUE for every row that already
       exists at the moment this migration runs. That is deliberate, not
       an oversight: those are real accounts created under the OLD signup
       flow, before email verification existed at all, and none of them
       ever got a verification email to click. Treating them as verified
       (rather than suddenly locking real people out of accounts they've
       already been using) is the safe default -- see backend/models.py's
       User.email_verified docstring. Only accounts created AFTER this
       migration, through the new signup flow, start out False (that
       value comes from the ORM's own insert, not from this column's
       database-level default, which only matters for the backfill and
       for any row inserted by raw SQL outside the ORM).

    2. `password_hash` drops its NOT NULL constraint, because a Google-only
       account (see backend/models.py) is never given one. Postgres can do
       this with a plain ALTER TABLE ... ALTER COLUMN. SQLite cannot --
       there is no ALTER COLUMN at all, so the only way to drop a NOT NULL
       constraint is SQLite's own documented rebuild pattern (new table,
       copy rows, drop old, rename) -- see `_sqlite_make_password_hash_nullable`
       below. This matters even for a "disposable" local dev database: a
       developer who already has a local.db from BEFORE this feature was
       added would otherwise hit a NOT NULL crash the first time a
       Google-only account is created locally, which is exactly the
       scenario the user's own "test locally first" requirement needs to
       actually work.
    """
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    dialect = engine.dialect.name  # "sqlite" or "postgresql"
    existing_columns = {col["name"] for col in inspector.get_columns("users")}

    if "google_sub" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN google_sub VARCHAR(255)"))
    # A UNIQUE index (rather than a UNIQUE column constraint added via a
    # separate ALTER) so this is one statement that works the same way on
    # both dialects, and so multiple rows with google_sub=NULL (i.e. every
    # email/password account that never used Google) don't conflict with
    # each other -- both Postgres and SQLite treat NULL as distinct from
    # every other NULL in a unique index.
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("users")}
    if "ix_users_google_sub_unique" not in existing_indexes:
        with engine.begin() as conn:
            conn.execute(text("CREATE UNIQUE INDEX ix_users_google_sub_unique ON users (google_sub)"))

    if "auth_provider" not in existing_columns:
        with engine.begin() as conn:
            # Every row that already exists was, definitionally, created
            # through the email/password flow (Google sign-in is what
            # this migration is adding), so backfilling 'email' here is
            # simply the true, correct value for those rows -- not a
            # policy choice like email_verified below.
            conn.execute(text("ALTER TABLE users ADD COLUMN auth_provider VARCHAR(20) NOT NULL DEFAULT 'email'"))

    if "email_verified" not in existing_columns:
        with engine.begin() as conn:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT true"))
            else:
                # SQLite has no native BOOLEAN type -- it stores 0/1 via
                # integer affinity, which is exactly what SQLAlchemy's
                # Boolean type already reads/writes for this dialect.
                conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 1"))

    if "email_verify_token_hash" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN email_verify_token_hash VARCHAR(64)"))

    if "email_verify_expires_at" not in existing_columns:
        with engine.begin() as conn:
            column_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME"
            conn.execute(text(f"ALTER TABLE users ADD COLUMN email_verify_expires_at {column_type}"))

    password_hash_col = next((c for c in inspector.get_columns("users") if c["name"] == "password_hash"), None)
    if password_hash_col is not None and not password_hash_col["nullable"]:
        if dialect == "postgresql":
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL"))
        else:
            _sqlite_make_password_hash_nullable()


def _sqlite_make_password_hash_nullable() -> None:
    """SQLite has no ALTER COLUMN, so the only way to drop a NOT NULL
    constraint is SQLite's own documented rebuild recipe: create a new table
    with the desired schema, copy every existing row across via an explicit
    column list (safer than `SELECT *`, which depends on column order),
    drop the old table, and rename the new one into its place. All of it
    runs inside one transaction (engine.begin()), so a failure partway
    through rolls back completely rather than leaving the table half
    migrated -- no row is ever lost or duplicated.

    The column list/types mirror backend/models.py's User table exactly (as
    of the Google sign-in + email verification columns being added, all of
    which are already present on `users` by the time this runs -- the
    earlier ADD COLUMN steps in `_ensure_google_and_verification_columns`
    always run first). If User ever gains another column, this hardcoded
    list needs updating too -- it intentionally does not try to generate
    the new table's DDL generically from the inspector, since SQLite's type
    affinity makes that more fragile than just mirroring the model, which
    is the single source of truth anyway.
    """
    column_names = [
        "id", "email", "name", "password_hash", "phone", "interests",
        "google_sub", "auth_provider", "email_verified",
        "email_verify_token_hash", "email_verify_expires_at",
        "created_at", "updated_at",
    ]
    cols_sql = ", ".join(column_names)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                """
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(320) UNIQUE NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    password_hash VARCHAR(300),
                    phone VARCHAR(200),
                    interests VARCHAR(200),
                    google_sub VARCHAR(255) UNIQUE,
                    auth_provider VARCHAR(20) NOT NULL DEFAULT 'email',
                    email_verified BOOLEAN NOT NULL DEFAULT 1,
                    email_verify_token_hash VARCHAR(64),
                    email_verify_expires_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(text(f"INSERT INTO users_new ({cols_sql}) SELECT {cols_sql} FROM users"))
        conn.execute(text("DROP TABLE users"))
        conn.execute(text("ALTER TABLE users_new RENAME TO users"))
        # The inline `UNIQUE` on google_sub above creates SQLite's own
        # auto-named index, not one named "ix_users_google_sub_unique" --
        # drop whatever SQLite made and recreate the explicitly-named index
        # so later runs of this migration (which check for that exact name)
        # still recognize it as already present.
        conn.execute(text("DROP INDEX IF EXISTS ix_users_google_sub_unique"))
        conn.execute(text("CREATE UNIQUE INDEX ix_users_google_sub_unique ON users (google_sub)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


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

def create_user(
    db: Session,
    *,
    email: str,
    name: str,
    password_hash: str,
    phone: str | None = None,
    interests: str | None = None,
    email_verified: bool = False,
) -> User:
    """Insert a new user row. Raises sqlalchemy.exc.IntegrityError if the
    email is already taken (the `unique=True` on User.email enforces this at
    the database level, not just in Python).

    `phone`/`interests` are optional and default to None so this stays
    backward compatible with backend/create_user.py's CLI usage, which
    doesn't collect either.

    `email_verified` defaults to False, matching the public self-serve
    signup flow (POST /api/auth/signup, which relies on this default and
    does not pass the argument) -- a real address that nobody has clicked
    a verification link for yet must not be trusted. backend/create_user.py
    (the CLI provisioning script) explicitly passes True instead: an
    account created directly against the database by the app's own owner
    is already a trusted, deliberate action, same trust level as Google's
    own verified-email claim -- there is no public form step to verify
    against, and requiring one would make the CLI create permanently
    unusable accounts under POST /api/login's verification gate."""
    user = User(
        email=email.lower().strip(),
        name=name,
        password_hash=password_hash,
        phone=phone,
        interests=interests,
        email_verified=email_verified,
    )
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


# ---- Google sign-in + email verification -----------------------------------
#
# These all operate on the columns added by
# `_ensure_google_and_verification_columns` above. See backend/models.py's
# User class for the full rationale behind each column; the short version
# repeated at each function below is just the part that matters for THIS
# function's own behavior.

def find_user_by_google_sub(db: Session, google_sub: str) -> Optional[User]:
    """Returns the User already linked to this Google account (identified by
    Google's own stable `sub` claim), or None if no Zoey user has ever signed
    in with this Google account before."""
    stmt = select(User).where(User.google_sub == google_sub)
    return db.execute(stmt).scalar_one_or_none()


def create_google_user(db: Session, *, email: str, name: str, google_sub: str) -> User:
    """Insert a brand-new account created via "Continue with Google" --
    used only when no existing Zoey user is linked to this Google sub AND no
    existing Zoey user has this (verified) email either (see
    link_google_identity below for that second case).

    password_hash stays None: nothing to hash, this account has no Zoey
    password (see backend/models.py's User.password_hash docstring).
    email_verified starts True because Google's own verified `email_verified`
    claim already established that the address belongs to this person --
    callers must only pass an email that came from that verified claim, never
    an unverified one (see backend/google_auth.py)."""
    user = User(
        email=email.lower().strip(),
        name=name,
        password_hash=None,
        google_sub=google_sub,
        auth_provider="google",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def link_google_identity(db: Session, user: User, google_sub: str) -> User:
    """Attaches a Google identity to an EXISTING account instead of creating
    a duplicate -- used when a Google sign-in's verified email matches an
    account that was originally created through the email/password flow.

    Deliberately does NOT change auth_provider (it records how the account
    ORIGINATED, not every method it can currently authenticate with) and does
    NOT clear password_hash (the person keeps being able to log in with
    their original Zoey password too, alongside Google from now on). Marks
    email_verified True: a successful Google sign-in with a matching
    VERIFIED email is itself proof of ownership of that address, even if
    this person never clicked Zoey's own verification email."""
    user.google_sub = google_sub
    user.email_verified = True
    db.commit()
    db.refresh(user)
    return user


def set_email_verification_token(db: Session, user: User, *, token_hash: str, expires_at: datetime) -> None:
    """Stores a freshly-generated verification token's hash (never the raw
    token itself -- see backend/models.py's User.email_verify_token_hash)
    and its expiry. Overwrites any previous token, which is exactly what a
    "resend verification email" action should do: only the newest link
    still works, the old one is superseded (find_user_by_verification_token_hash
    below simply won't find it anymore, once this call has replaced it)."""
    user.email_verify_token_hash = token_hash
    user.email_verify_expires_at = expires_at
    db.commit()


def find_user_by_verification_token_hash(db: Session, token_hash: str) -> Optional[User]:
    """Returns the user this (already-hashed) verification token currently
    belongs to, or None if no user has this exact hash on file right now.

    Deliberately does NOT decide "expired" vs "already used" itself -- the
    caller (GET /api/auth/verify-email) needs to tell those apart to show two
    different messages ("link expired" vs "already verified"), and a None
    result here is ambiguous between "token never existed", "already used and
    cleared", and "superseded by a resend". Callers should look the token up
    fresh, and if this returns None, show the "already verified / invalid
    link" message rather than "expired"."""
    stmt = select(User).where(User.email_verify_token_hash == token_hash)
    return db.execute(stmt).scalar_one_or_none()


def set_email_verified(db: Session, user: User) -> None:
    """Marks the account verified and invalidates the token that was just
    used, so the same emailed link can't be replayed a second time -- a
    repeat click will find email_verify_token_hash already cleared (None)
    and the caller can return the "already verified" message instead of
    silently re-verifying (harmless) or erroring (confusing)."""
    user.email_verified = True
    user.email_verify_token_hash = None
    user.email_verify_expires_at = None
    db.commit()


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
