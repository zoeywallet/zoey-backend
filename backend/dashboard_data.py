"""
Mock portfolio data for the dashboard, exactly matching what the previous
Node backend served (same numbers, same shape) so dashboard.html's
JavaScript needs zero changes.

This is clearly-labeled placeholder data, not a real market feed — swapping
it for something real later is a matter of replacing get_dashboard_data()'s
body; nothing in api/index.py or dashboard.html needs to change, since they
only care about the shape this function returns.
"""

from __future__ import annotations

_HOLDINGS = [
    {"symbol": "NVDA", "name": "NVIDIA Corp.", "price": 201.30, "changePct": 2.05},
    {"symbol": "TSLA", "name": "Tesla Inc.", "price": 256.90, "changePct": 1.48},
    {"symbol": "PLTR", "name": "Palantir Tech.", "price": 168.44, "changePct": -0.62},
    {"symbol": "AMD", "name": "Advanced Micro", "price": 142.18, "changePct": 0.94},
    {"symbol": "MSFT", "name": "Microsoft Corp.", "price": 415.20, "changePct": 0.72},
]

_CHART_POINTS = [58, 61, 59, 64, 62, 68, 66, 71, 69, 75, 73, 78, 80]


def get_dashboard_data() -> dict:
    return {
        "portfolioValue": 12450.82,
        "todayChangeAbs": 184.20,
        "todayChangePct": 1.51,
        "chartPoints": list(_CHART_POINTS),
        "holdings": [dict(h) for h in _HOLDINGS],
        "stablecoins": {"USDT": 1240.00, "USDC": 860.50},
    }
