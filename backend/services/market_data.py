"""
Placeholder for a future market-data provider integration (e.g. a stock/
equities price feed for the dashboard's live holdings).

Nothing here is wired up yet — backend/dashboard_data.py still returns fixed
mock numbers. This module exists so that when you're ready to add a real
provider, there's an obvious, single place for it:

    def get_quote(symbol: str) -> dict:
        ...  # call the provider's API, return {"symbol", "price", "changePct"}

    def get_quotes(symbols: list[str]) -> dict[str, dict]:
        ...

Keep provider API keys out of the frontend entirely — this module runs only
on the backend, and any API key it needs should come from an environment
variable (add it to .env.example and to Vercel's env vars), never from
frontend JavaScript.
"""

from __future__ import annotations
