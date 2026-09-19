"""
SQLAlchemy ORM models — the Python equivalent of the old db.js schema.

If you're used to Django models, this will feel familiar: each class below
is a table, each class attribute is a column. SQLAlchemy's declarative style
(the `Base` class + `Mapped[...]` type hints) is the modern (2.0+) way to
write this, and it gives you real Python types (str, int, datetime) instead
of hand-written SQL everywhere.

Two tables back the app's live functionality today:
  - User    — one row per login account (password_hash, never plaintext)
  - Lead    — one row per "Get started" form submission

Five more tables (BrokerageAccount, CashBalance, Position, Transaction,
Order) are defined below this point purely as a database FOUNDATION for
future real brokerage data. They are additive, reserved schema only --
nothing in api/index.py or backend/dashboard_data.py references them
yet, no route creates rows in them, and the dashboard keeps serving its
existing mock data exactly as before. See each class's own docstring
for how it's meant to be used once that integration actually happens.

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

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
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
    #
    # Nullable as of the Google sign-in addition: an account created via
    # "Continue with Google" never sets a Zoey password at all (see
    # backend/google_auth.py + POST /api/auth/google in api/index.py) --
    # there's nothing wrong to hash, so this column is simply empty for
    # that account until/unless the person later sets one. Every
    # password-login code path (backend/auth.verify_password via
    # POST /api/login) already treats "no usable hash" as a clean
    # authentication failure rather than a crash -- see verify_password's
    # None handling.
    password_hash: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Both optional -- the signup form's phone/interest fields are optional,
    # same as the existing Lead model just below. Added alongside the
    # self-serve signup flow; see backend/database.py's `_ensure_user_columns`
    # for how these get added to an ALREADY-DEPLOYED users table in Neon
    # without dropping or recreating it.
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    interests: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ---- Google sign-in + email verification (added together; see
    # backend/database.py's `_ensure_user_columns` for how these land on an
    # ALREADY-DEPLOYED `users` table in Neon without dropping or recreating
    # it, and how existing rows are safely defaulted so nobody already using
    # the app gets locked out) ----
    #
    # The Google *subject* (`sub` claim) is the stable, permanent identity
    # Google guarantees for an account -- unlike an email address, it can
    # never be changed, reused, or reassigned to someone else, which is
    # exactly why it's the join key here instead of email. unique=True
    # because at most one Zoey user may ever be linked to a given Google
    # account. Nullable because most rows (plain email/password accounts
    # that never used Google) will never have one.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    # Which method created this account -- "email" or "google". Informational
    # only (support/analytics); every actual authorization decision in this
    # file is made from password_hash/google_sub being present or absent, not
    # from this field, so a wrong/legacy value here can never make an account
    # more or less able to authenticate than it actually is.
    auth_provider: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    # True once this address is confirmed to actually belong to the person
    # who created the account. New email/password signups start False (see
    # POST /api/auth/signup) until they click the emailed verification link
    # (POST /api/auth/verify-email); Google signups start True immediately,
    # since Google's own verified `email_verified` claim already established
    # that from the identity provider itself (see backend/google_auth.py).
    #
    # IMPORTANT: this column GATES email/password login -- POST /api/login
    # (api/index.py) refuses to authenticate ("Please verify your email
    # before signing in.") when this is False, checked only after the
    # password itself has already been confirmed correct (so the check
    # itself can't be used to enumerate accounts). This does NOT apply to
    # "Continue with Google" at all -- a Google-authenticated account
    # always starts (or becomes, if linked) email_verified=True the moment
    # it's created/linked, since Google's own verified claim already
    # established ownership of the address; see backend/google_auth.py and
    # backend/database.py's create_google_user / link_google_identity.
    # POST /api/auth/signup also does NOT auto-authenticate the new
    # account, for the same reason -- see that endpoint's own docstring.
    # Existing pre-migration accounts are grandfathered to True by
    # backend/database.py's migration specifically so this gate never
    # locks out someone who was already using the app.
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # A verification link's token is only ever stored here as a SHA-256
    # hash (see backend/email_verification.py) -- never in plaintext -- so
    # that reading this column out of a database backup/leak can't be used
    # to mint a working verification link, the same reasoning as
    # password_hash above. Cleared (set back to None) the moment the token
    # is used or superseded by a newer one (resend).
    email_verify_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_verify_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
# ---------------------------------------------------------------------------
# Brokerage data foundation (schema only -- see module docstring above)
# ---------------------------------------------------------------------------
#
# None of the five tables below are wired into any route yet. No code
# anywhere creates a row in any of them. They exist so that when a real
# DriveWealth integration is built, there's an obvious, already-reviewed
# place for its data to live, with ownership enforced the same way this
# whole app already enforces it: every row traces back to exactly one
# users.id, and nothing downstream of BrokerageAccount stores user_id
# directly -- ownership is always reached by joining through
# brokerage_account_id, never duplicated onto every child table.
#
# No relationship()/backref definitions are used here, matching User/Lead
# above -- this codebase's existing architecture always queries explicitly
# via select() in backend/database.py rather than traversing ORM
# relationships, so adding relationship() here would be inconsistent with
# how every other model in this file already works.


class BrokerageAccount(Base):
    """A Zoey user's account at an external brokerage provider (e.g.
    DriveWealth). Not created by anything yet -- this table is the
    foundation a future integration will insert into.

    The uq_brokerage_accounts_user_provider constraint below encodes today's
    intended rule -- one account per provider per user -- as a single,
    separately-named constraint rather than baking it into the primary key
    or a composite id. If that rule ever needs to relax (e.g. a user gets
    two DriveWealth accounts), dropping just this one named constraint is
    the entire migration; nothing else about this table's shape changes.
    """

    __tablename__ = "brokerage_accounts"
    __table_args__ = (
        # Global: a given provider's external account can only ever map to
        # one Zoey brokerage_accounts row, full stop.
        UniqueConstraint(
            "provider", "external_account_id", name="uq_brokerage_accounts_provider_external_id"
        ),
        # Today's rule: one account per provider per user -- see class
        # docstring above for how to relax this later.
        UniqueConstraint("user_id", "provider", name="uq_brokerage_accounts_user_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CashBalance(Base):
    """One row per (brokerage account, currency/asset) -- e.g. a single
    account's USDT balance and USDC balance are two separate rows, not two
    columns, so a new supported currency later never needs a schema
    change.

    available_balance/total_balance are NUMERIC (Python Decimal), never
    Float -- money must never be stored as binary floating point (the
    classic 0.1 + 0.2 != 0.3 problem). Every monetary/quantity column on
    every table below follows this same rule.
    """

    __tablename__ = "cash_balances"
    __table_args__ = (
        UniqueConstraint("brokerage_account_id", "currency", name="uq_cash_balances_account_currency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brokerage_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("brokerage_accounts.id"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    available_balance: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    total_balance: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Position(Base):
    """One row per (brokerage account, symbol) currently held.

    quantity uses 8 decimal places (not the 2-4 used by the money columns
    elsewhere in this file) specifically so a fractional share is never
    silently rounded or truncated.

    market_value and unrealized_gain_loss are nullable, unlike
    quantity/average_cost (which are true the instant a position exists):
    both depend on a live market price, and this project deliberately does
    not fetch real market data yet (see backend/services/market_data.py,
    still an empty placeholder). A position row can exist with these left
    NULL until a real market-data integration fills them in -- nothing here
    computes them.
    """

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("brokerage_account_id", "symbol", name="uq_positions_account_symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brokerage_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("brokerage_accounts.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    unrealized_gain_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Transaction(Base):
    """One row per brokerage transaction (deposit, withdrawal, buy, sell,
    dividend, fee, ...). Named `transaction_type`, not `type`, so it never
    shadows Python's builtin -- a plain string with no enforced set of
    values at the database level, the same style as User.auth_provider
    elsewhere in this file.

    external_transaction_id is how a future DriveWealth sync would stay
    idempotent -- safe to process the same webhook/sync delivery twice
    without creating a duplicate row. The unique constraint below is
    NULL-safe: both Postgres and SQLite treat NULL as distinct from every
    other NULL in a unique constraint (see User.google_sub's own unique
    index above for the same reasoning already used elsewhere in this
    codebase), so any number of locally-pending rows with no external id
    yet can coexist under the same brokerage_account_id without
    conflicting -- no partial/filtered index is needed to get that
    behavior, a plain composite UniqueConstraint already has it.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "brokerage_account_id", "external_transaction_id", name="uq_transactions_account_external_id"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brokerage_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("brokerage_accounts.id"), nullable=False, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    external_transaction_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Order(Base):
    """One row per brokerage order (a request to buy/sell) -- distinct from
    Transaction, which records what actually settled. external_order_id
    follows the same NULL-safe composite-uniqueness reasoning as
    Transaction.external_transaction_id above."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("brokerage_account_id", "external_order_id", name="uq_orders_account_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brokerage_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("brokerage_accounts.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    external_order_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
