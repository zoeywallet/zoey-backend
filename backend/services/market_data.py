"""
Server-side Twelve Data client + cache for the floating market-ticker
cards on the landing page (index.html's .ticker-section).

This fills in the placeholder this file used to be (see git history --
it reserved this exact spot for "a future market-data provider
integration"). Note the scope: this only serves the landing-page ticker
strip. backend/dashboard_data.py's holdings still return fixed mock
numbers -- wiring real prices into the dashboard is a separate,
not-yet-built piece of work (see backend/models.py's Position docstring).

Twelve Data's REST API (https://api.twelvedata.com) is read with an API
key that must never reach the browser -- this module is the ONLY thing
that reads TWELVE_DATA_API_KEY from the environment (a local .env file
in dev -- see .env.example -- or a real Vercel environment variable in
production). The frontend only ever calls our own GET /api/markets/ticker
(api/index.py), which calls this module; Twelve Data is never contacted
from client-side JavaScript.

Caching: Twelve Data's free plan caps out at 8 API credits/minute and
800/day, and each symbol in a request costs 1 credit. This module tracks
11 symbols, so one quote refresh + one sparkline (time_series) refresh
together cost 22 credits. A single in-process cache, shared by every
visitor hitting this server instance, means visitor traffic no longer
determines how often Twelve Data gets called -- only these TTLs do:

    11 symbols / 1800s quote TTL      -> ~528 credits/day
    11 symbols / 5400s sparkline TTL  -> ~176 credits/day
    total                             -> ~704 credits/day (under the 800 cap,
                                          leaving headroom for local dev reloads)

That means on the free plan prices refresh roughly every 30 minutes and
the sparkline roughly every 90 minutes -- not continuously live. If a
paid Twelve Data plan is adopted later, lowering QUOTE_TTL_SECONDS and
SPARKLINE_TTL_SECONDS below is the only change needed for fresher data.

A lock makes sure that if many requests arrive at once right as a cache
entry goes stale, only one of them actually calls Twelve Data; the rest
reuse its result instead of each firing their own upstream request.

On any failure (network error, timeout, missing/invalid API key, rate
limit, Twelve Data error payload, unrecognized symbol) this NEVER
fabricates a price. It falls back to the last good cached value if one
exists, or marks that symbol "unavailable" if it doesn't -- the frontend
renders that state, this module just never invents numbers.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import requests

logger = logging.getLogger("zoey.market_data")

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "").strip()
TWELVE_DATA_BASE = "https://api.twelvedata.com"

# One entry per floating ticker card. `td_symbol` is what gets sent to
# Twelve Data; `symbol` is what the card displays. NASDAQ's `td_symbol`
# (IXIC, the Nasdaq Composite) is the standard ticker used by most market
# data providers for this index -- if it is not what this Twelve Data
# plan recognizes, that one card simply renders as "unavailable" (each
# symbol is fetched/validated independently; one bad symbol can't take
# the rest down or produce a fake number for itself).
TICKERS = [
    {"symbol": "AAPL", "td_symbol": "AAPL", "logo": "aapl.jpg"},
    {"symbol": "NVDA", "td_symbol": "NVDA", "logo": "nvda.jpg"},
    {"symbol": "MSFT", "td_symbol": "MSFT", "logo": "msft.jpg"},
    {"symbol": "TSLA", "td_symbol": "TSLA", "logo": "tsla.jpg"},
    {"symbol": "AMZN", "td_symbol": "AMZN", "logo": "amzn.jpg"},
    {"symbol": "GOOGL", "td_symbol": "GOOGL", "logo": "googl.jpg"},
    {"symbol": "META", "td_symbol": "META", "logo": "meta.jpg"},
    {"symbol": "AMD", "td_symbol": "AMD", "logo": "amd.jpg"},
    {"symbol": "PLTR", "td_symbol": "PLTR", "logo": "pltr.jpg"},
    {"symbol": "NFLX", "td_symbol": "NFLX", "logo": "nflx.jpg"},
    {"symbol": "NASDAQ", "td_symbol": "IXIC", "logo": "nasdaq.jpg", "index": True},
]

_SYMBOLS_PARAM = ",".join(t["td_symbol"] for t in TICKERS)

QUOTE_TTL_SECONDS = 1800      # ~30 min -- see module docstring for the credit budget
SPARKLINE_TTL_SECONDS = 5400  # ~90 min
HTTP_TIMEOUT_SECONDS = 6
SPARKLINE_INTERVAL = "15min"
SPARKLINE_OUTPUTSIZE = 20

_cache_lock = threading.Lock()
_quote_cache: dict = {"data": None, "fetched_at": 0.0}
_sparkline_cache: dict = {"data": None, "fetched_at": 0.0}


def _twelve_data_get(path: str, params: dict) -> dict | None:
    if not TWELVE_DATA_API_KEY:
        logger.warning(
            "TWELVE_DATA_API_KEY is not set; the market ticker will show "
            "as unavailable until it is configured."
        )
        return None
    try:
        resp = requests.get(
            f"{TWELVE_DATA_BASE}/{path}",
            params={**params, "apikey": TWELVE_DATA_API_KEY},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # network error, timeout, bad JSON, HTTP error status
        logger.warning("Twelve Data request to %s failed: %s", path, exc)
        return None
    if isinstance(payload, dict) and payload.get("status") == "error":
        logger.warning("Twelve Data returned an error for %s: %s", path, payload.get("message"))
        return None
    return payload


def _fetch_quotes() -> dict[str, dict]:
    payload = _twelve_data_get("quote", {"symbol": _SYMBOLS_PARAM})
    if payload is None:
        return {}
    if "symbol" in payload:
        payload = {payload["symbol"]: payload}
    out: dict[str, dict] = {}
    for t in TICKERS:
        row = payload.get(t["td_symbol"])
        if not isinstance(row, dict) or row.get("status") == "error" or row.get("close") is None:
            continue
        try:
            out[t["symbol"]] = {
                "price": float(row["close"]),
                "change_percent": float(row.get("percent_change", 0.0)),
                "currency": row.get("currency") or "USD",
            }
        except (TypeError, ValueError):
            continue
    return out


def _fetch_sparklines() -> dict[str, list[float]]:
    payload = _twelve_data_get(
        "time_series",
        {
            "symbol": _SYMBOLS_PARAM,
            "interval": SPARKLINE_INTERVAL,
            "outputsize": SPARKLINE_OUTPUTSIZE,
        },
    )
    if payload is None:
        return {}
    if "values" in payload:
        payload = {TICKERS[0]["td_symbol"]: payload}
    out: dict[str, list[float]] = {}
    for t in TICKERS:
        row = payload.get(t["td_symbol"])
        values = row.get("values") if isinstance(row, dict) else None
        if not values:
            continue
        try:
            closes = [float(v["close"]) for v in reversed(values) if v.get("close") is not None]
        except (TypeError, ValueError):
            continue
        if closes:
            out[t["symbol"]] = closes
    return out


def _refresh_if_stale(cache: dict, ttl: float, fetch_fn) -> None:
    now = time.time()
    if cache["data"] is not None and (now - cache["fetched_at"]) < ttl:
        return
    with _cache_lock:
        now = time.time()
        if cache["data"] is not None and (now - cache["fetched_at"]) < ttl:
            return
        fresh = fetch_fn()
        if fresh:
            cache["data"] = fresh
            cache["fetched_at"] = now
        elif cache["data"] is None:
            cache["data"] = {}
            cache["fetched_at"] = now


def get_market_snapshot() -> list[dict]:
    """Returns one entry per TICKERS item. Never raises, never fabricates
    a price -- a symbol with no good cached data comes back with
    status="unavailable" and no price/change/sparkline fields."""
    _refresh_if_stale(_quote_cache, QUOTE_TTL_SECONDS, _fetch_quotes)
    _refresh_if_stale(_sparkline_cache, SPARKLINE_TTL_SECONDS, _fetch_sparklines)

    quotes = _quote_cache["data"] or {}
    sparklines = _sparkline_cache["data"] or {}

    out = []
    for t in TICKERS:
        q = quotes.get(t["symbol"])
        entry = {
            "symbol": t["symbol"],
            "logo": t["logo"],
            "index": bool(t.get("index")),
        }
        if q:
            entry.update(
                status="ok",
                price=q["price"],
                currency=q["currency"],
                change_percent=q["change_percent"],
                sparkline=sparklines.get(t["symbol"]) or [],
            )
        else:
            entry["status"] = "unavailable"
        out.append(entry)
    return out
