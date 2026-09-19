"""
Dashboard data for the CURRENTLY AUTHENTICATED user's own account.

DriveWealth is not integrated yet (see backend/models.py's BrokerageAccount
docstring) -- no signup/onboarding flow anywhere in this codebase creates a
row in brokerage_accounts, so every authenticated user has zero brokerage
accounts today. There is therefore no legitimate source yet for portfolio
value, holdings, performance history, or funding balances, and this module
must never invent one.

get_dashboard_data(db, user_id) always queries Neon (via
backend/database.py) for THIS user's own data -- never another user's, and
never a shared/mock fixture. When it finds no brokerage account (true for
every user today), it returns the shape below with hasBrokerageAccount:
False and every financial figure honestly at zero/empty --
dashboard.html's JS uses that flag to render its empty states instead of
fabricated numbers. This is not a placeholder for "we didn't bother
fetching real data" -- it IS the real data; there simply isn't any yet.

When a real brokerage account eventually exists for a user (once a future
DriveWealth integration creates one), this same function starts returning
real aggregated CashBalance/Position rows for hasBrokerageAccount: True
instead -- nothing in api/index.py's GET /api/dashboard route or
dashboard.html's fetch('/api/dashboard') call needs to change for that,
only this function's body. Note that even in that branch, todayChangeAbs/
todayChangePct/chartPoints are left at 0/empty rather than computed: there
is no historical snapshot table in this schema yet, so a real day-over-day
change genuinely cannot be calculated, and this module fabricates figures
no more in that branch than in the empty-state one.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from backend.database import get_brokerage_account_for_user, list_cash_balances, list_positions

# The only currencies the (approved, existing) dashboard design has a
# funding pill for -- see dashboard.html's #dashUsdt / #dashUsdc. Any other
# currency a future CashBalance row might use simply isn't shown here yet;
# it is not lost data, just not wired into this particular card.
_DASHBOARD_STABLECOINS = ("USDT", "USDC")


def _empty_stablecoins() -> dict:
    return {currency: 0.0 for currency in _DASHBOARD_STABLECOINS}


def get_dashboard_data(db: Session, user_id: int) -> dict:
    account = get_brokerage_account_for_user(db, user_id)

    if account is None:
        # The honest, universal state today. See module docstring.
        return {
            "hasBrokerageAccount": False,
            "portfolioValue": 0.0,
            "todayChangeAbs": 0.0,
            "todayChangePct": 0.0,
            "chartPoints": [],
            "holdings": [],
            "stablecoins": _empty_stablecoins(),
        }

    # Not reachable today -- see get_brokerage_account_for_user's docstring
    # -- but written to be correct the moment it is: every row read below
    # is scoped to THIS account.id, which get_brokerage_account_for_user
    # already scoped to THIS user_id, so none of this can ever surface
    # another user's data.
    cash_balances = list_cash_balances(db, account.id)
    stablecoins = _empty_stablecoins()
    for balance in cash_balances:
        if balance.currency in stablecoins:
            stablecoins[balance.currency] = float(balance.available_balance)

    positions = list_positions(db, account.id)
    holdings = []
    portfolio_value = Decimal("0")
    for position in positions:
        # market_value is nullable (see Position's own docstring in
        # backend/models.py) -- this project does not fetch live market
        # data yet, so a position can exist with it still NULL. Left out
        # of portfolio_value entirely rather than guessed at.
        if position.market_value is not None:
            portfolio_value += position.market_value
        holdings.append(
            {
                "symbol": position.symbol,
                "quantity": float(position.quantity),
                "averageCost": float(position.average_cost),
                "marketValue": float(position.market_value) if position.market_value is not None else None,
            }
        )

    return {
        "hasBrokerageAccount": True,
        "portfolioValue": float(portfolio_value),
        # No historical snapshot table exists yet to compute a real
        # day-over-day change from -- left at 0 rather than fabricated.
        "todayChangeAbs": 0.0,
        "todayChangePct": 0.0,
        "chartPoints": [],
        "holdings": holdings,
        "stablecoins": stablecoins,
    }
