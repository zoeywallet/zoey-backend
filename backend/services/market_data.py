"""
Server-side Twelve Data client for the floating market-ticker cards on the
landing page (index.html's .ticker-section), backed by a durable snapshot
in Neon/Postgres rather than process memory.

The frontend only ever calls our own GET /api/markets/ticker (api/index.py),
which calls get_market_snapshot() below; Twelve Data is never contacted
from client-side JavaScript, and TWELVE_DATA_API_KEY is read ONLY here.

WHY NOT AN IN-MEMORY CACHE (the previous version of this file used one):
Vercel's Python functions are stateless and ephemeral -- every cold start
begins with empty process memory, and Vercel can run multiple concurrent
instances of the same function that share nothing. A module-level dict/
lock/timestamp cannot be the authority on "have we already fetched this
symbol recently" or "are we within our credit budget," because a different
instance -- or the same instance after a cold start -- has no way to know
what any other instance has done. The durable state lives in Postgres
instead (backend/models.py's MarketTickerCache / MarketTickerCreditLog,
read and written exclusively through the named functions in
backend/database.py -- this module never touches a Session directly,
matching that file's own convention).

CREDIT BUDGET: Twelve Data's Basic 8 plan meters 1 credit PER SYMBOL in a
request, even when symbols are batched into one HTTP call -- batching
reduces HTTP calls, not credits. All 11 symbols in one call (11 credits)
already exceeds the 8-credits/minute cap by itself. The fix here is to
never request more than a few symbols at a time, spread across a rotating
schedule, gated by a durable rolling-60-second credit count
(backend/database.py's claim_market_ticker_refresh) that is shared across
every Vercel instance and enforced atomically -- see that function's own
docstring for exactly how.

REFRESH SCHEDULE: the 11 symbols are split into 4 groups (TICKER_GROUPS
below). Price (/quote) and sparkline (/time_series) are refreshed on
independent schedules -- sparkline needs to be fresh far less often than
price -- one group at a time:

    price:     one group (<=3 symbols) every QUOTE_REFRESH_SECONDS
               -> full rotation (all 11 symbols) every 30 min
               -> 11 credits / 30 min  = ~22 credits/hour  = ~528 credits/day
    sparkline: one group (<=3 symbols) every SPARKLINE_REFRESH_SECONDS
               -> full rotation (all 11 symbols) every 150 min (2.5h)
               -> 11 credits / 150 min = ~4.4 credits/hour = ~105.6 credits/day
    total                                                 ~ 633.6 credits/day
                                                             (under the 800/day
                                                              cap, ~166 credits
                                                              of headroom)

MAX_CREDITS_PER_WINDOW (6, over a rolling 60 seconds, enforced in
claim_market_ticker_refresh) is the hard ceiling -- never schedule more
than this many credits in any rolling 60-second period, including during
first-ever seeding of an empty table (ensure_market_ticker_rows seeds every
row as immediately-eligible, so seeding goes through the exact same
rate-limited claim path as any later refresh -- never the old
11-quote + 11-time_series = 22-credit burst).

FAILURE HANDLING: on any failure (network error, timeout, 429, 5xx,
missing/invalid API key, unrecognized symbol) this NEVER fabricates a
price and NEVER erases a symbol's last good cached value -- a failed claim
simply isn't recorded (see get_market_snapshot below), and
next_eligible_at was already advanced as part of the claim itself, so a
failure does not trigger an immediate retry that could spend further
credits -- the next attempt waits for the normal schedule.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session

from backend.database import (
    claim_market_ticker_refresh,
    ensure_market_ticker_rows,
    get_market_ticker_cache_rows,
    record_market_ticker_quote,
    record_market_ticker_sparkline,
)

logger = logging.getLogger("zoey.market_data")

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "").strip()
TWELVE_DATA_BASE = "https://api.twelvedata.com"

# One entry per floating ticker card. `td_symbol` is what gets sent to
# Twelve Data; `symbol` is what the card displays. NASDAQ's `td_symbol`
# (IXIC, the Nasdaq Composite) is the standard ticker used by most market
# data providers for this index -- if it is not what this Twelve Data plan
# recognizes, that one card simply renders as "unavailable" (each symbol is
# fetched/validated independently; one bad symbol can't take the rest down
# or produce a fake number for itself). `group` assigns each symbol to one
# of the 4 rotating refresh groups below -- see module docstring.
TICKERS = [
    {"symbol": "AAPL", "td_symbol": "AAPL", "logo": "aapl.jpg", "group": "group_1"},
    {"symbol": "NVDA", "td_symbol": "NVDA", "logo": "nvda.jpg", "group": "group_1"},
    {"symbol": "MSFT", "td_symbol": "MSFT", "logo": "msft.jpg", "group": "group_1"},
    {"symbol": "TSLA", "td_symbol": "TSLA", "logo": "tsla.jpg", "group": "group_2"},
    {"symbol": "AMZN", "td_symbol": "AMZN", "logo": "amzn.jpg", "group": "group_2"},
    {"symbol": "GOOGL", "td_symbol": "GOOGL", "logo": "googl.jpg", "group": "group_2"},
    {"symbol": "META", "td_symbol": "META", "logo": "meta.jpg", "group": "group_3"},
    {"symbol": "AMD", "td_symbol": "AMD", "logo": "amd.jpg", "group": "group_3"},
    {"symbol": "PLTR", "td_symbol": "PLTR", "logo": "pltr.jpg", "group": "group_3"},
    {"symbol": "NFLX", "td_symbol": "NFLX", "logo": "nflx.jpg", "group": "group_4"},
    {"symbol": "NASDAQ", "td_symbol": "IXIC", "logo": "nasdaq.jpg", "group": "group_4", "index": True},
]
_BY_SYMBOL = {t["symbol"]: t for t in TICKERS}

# ---- Rate-limit / schedule configuration (see module docstring) ----
MAX_CREDITS_PER_WINDOW = 6   # hard ceiling, enforced atomically in claim_market_ticker_refresh
RATE_WINDOW_SECONDS = 60     # a true rolling window, not a fixed/resetting bucket
QUOTE_REFRESH_SECONDS = 450       # 7.5 min/group -> full 11-symbol rotation every 30 min
SPARKLINE_REFRESH_SECONDS = 2250  # 37.5 min/group -> full 11-symbol rotation every 150 min
HTTP_TIMEOUT_SECONDS = 6
SPARKLINE_INTERVAL = "15min"
SPARKLINE_OUTPUTSIZE = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _twelve_data_get(path: str, params: dict) -> dict | None:
    """GETs one Twelve Data endpoint. Never logs the API key, the request
    URL/query string, or any request/response object that could contain
    them -- only the endpoint path and a sanitized status/error description
    (see module docstring's "FAILURE HANDLING" and the project's security
    requirements for this file)."""
    if not TWELVE_DATA_API_KEY:
        logger.warning("Twelve Data request skipped: endpoint=%s reason=no_api_key_configured", path)
        return None
    try:
        resp = requests.get(
            f"{TWELVE_DATA_BASE}/{path}",
            params={**params, "apikey": TWELVE_DATA_API_KEY},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.exceptions.HTTPError as exc:
        # str(exc) / exc.response.url would include the full request URL,
        # apikey included -- log only the numeric status code instead.
        status = exc.response.status_code if exc.response is not None else "unknown"
        logger.warning("Twelve Data request failed: endpoint=%s status=%s", path, status)
        return None
    except requests.exceptions.Timeout:
        logger.warning("Twelve Data request failed: endpoint=%s error=timeout", path)
        return None
    except requests.exceptions.RequestException as exc:
        # Network error, connection error, etc. -- log only the exception's
        # class name, never str(exc) (which can embed the request URL).
        logger.warning("Twelve Data request failed: endpoint=%s error=%s", path, type(exc).__name__)
        return None
    except ValueError:
        # resp.json() couldn't parse the response body.
        logger.warning("Twelve Data request failed: endpoint=%s error=invalid_response_body", path)
        return None
    if isinstance(payload, dict) and payload.get("status") == "error":
        logger.warning("Twelve Data request failed: endpoint=%s error=api_error", path)
        return None
    return payload


def _fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """Fetches /quote for exactly `symbols` (a claimed group, <=3 symbols
    today -- never all 11 at once). Returns {symbol: {price, change_percent,
    currency}}, only for symbols Twelve Data actually returned good data
    for."""
    td_symbols = [_BY_SYMBOL[s]["td_symbol"] for s in symbols]
    payload = _twelve_data_get("quote", {"symbol": ",".join(td_symbols)})
    if payload is None:
        return {}
    if "symbol" in payload:
        payload = {payload["symbol"]: payload}
    out: dict[str, dict] = {}
    for s in symbols:
        td_symbol = _BY_SYMBOL[s]["td_symbol"]
        row = payload.get(td_symbol)
        if not isinstance(row, dict):
            logger.warning("Twelve Data symbol missing from response: symbol=%s endpoint=quote", td_symbol)
            continue
        if row.get("status") == "error":
            # row.get("message") is Twelve Data's own per-symbol error text in
            # the RESPONSE body -- never the request URL, query params, or API
            # key (those only ever appear request-side, in _twelve_data_get's
            # already-sanitized failure path above) -- safe to log verbatim.
            logger.warning(
                "Twelve Data symbol error: symbol=%s endpoint=quote message=%s",
                td_symbol, row.get("message"),
            )
            continue
        if row.get("close") is None:
            logger.warning("Twelve Data symbol has no close price: symbol=%s endpoint=quote", td_symbol)
            continue
        try:
            out[s] = {
                "price": float(row["close"]),
                "change_percent": float(row.get("percent_change", 0.0)),
                "currency": row.get("currency") or "USD",
            }
        except (TypeError, ValueError):
            continue
    return out


def _fetch_sparklines(symbols: list[str]) -> dict[str, list[float]]:
    """Fetches /time_series for exactly `symbols` (a claimed group).
    Returns {symbol: [closes, oldest-to-newest]}, only for symbols Twelve
    Data actually returned good data for."""
    td_symbols = [_BY_SYMBOL[s]["td_symbol"] for s in symbols]
    payload = _twelve_data_get(
        "time_series",
        {
            "symbol": ",".join(td_symbols),
            "interval": SPARKLINE_INTERVAL,
            "outputsize": SPARKLINE_OUTPUTSIZE,
        },
    )
    if payload is None:
        return {}
    if "values" in payload and len(symbols) == 1:
        # Twelve Data returns the single-symbol shape (no outer symbol key)
        # only when exactly one symbol was requested -- safe to attribute
        # directly to that one symbol (every ticker group has >=2 symbols
        # today, so this branch is defensive, not the normal path).
        payload = {td_symbols[0]: payload}
    out: dict[str, list[float]] = {}
    for s in symbols:
        td_symbol = _BY_SYMBOL[s]["td_symbol"]
        row = payload.get(td_symbol)
        if not isinstance(row, dict):
            logger.warning("Twelve Data symbol missing from response: symbol=%s endpoint=time_series", td_symbol)
            continue
        if row.get("status") == "error":
            # Same sanitization guarantee as _fetch_quotes above: this is
            # Twelve Data's own response-body message, never a URL/key.
            logger.warning(
                "Twelve Data symbol error: symbol=%s endpoint=time_series message=%s",
                td_symbol, row.get("message"),
            )
            continue
        values = row.get("values")
        if not values:
            logger.warning("Twelve Data symbol has no time_series values: symbol=%s endpoint=time_series", td_symbol)
            continue
        try:
            closes = [float(v["close"]) for v in reversed(values) if v.get("close") is not None]
        except (TypeError, ValueError):
            continue
        if closes:
            out[s] = closes
    return out


def _perform_claim(db: Session, claim: dict, now: datetime) -> None:
    """Calls Twelve Data for exactly the symbols in `claim` and records
    whatever succeeded. Never raises -- a failed fetch simply records
    nothing, leaving each symbol's previous good value (if any) in place;
    see module docstring's FAILURE HANDLING."""
    symbols = claim["symbols"]
    if claim["kind"] == "quote":
        quotes = _fetch_quotes(symbols)
        for symbol, q in quotes.items():
            record_market_ticker_quote(
                db,
                symbol=symbol,
                price=q["price"],
                change_percent=q["change_percent"],
                currency=q["currency"],
                now=now,
            )
    else:
        sparklines = _fetch_sparklines(symbols)
        for symbol, values in sparklines.items():
            record_market_ticker_sparkline(db, symbol=symbol, values=values, now=now)


def _build_snapshot(rows) -> list[dict]:
    """Turns the durable MarketTickerCache rows into the exact response
    shape the frontend already expects (see index.html's tickerCardHTML) --
    unchanged from before this change, so the frontend needs no update."""
    by_symbol: dict[str, dict] = {}
    for row in rows:
        entry = by_symbol.setdefault(row.symbol, {})
        if row.kind == "quote" and row.price is not None:
            entry["price"] = float(row.price)
            entry["change_percent"] = float(row.change_percent) if row.change_percent is not None else 0.0
            entry["currency"] = row.currency or "USD"
        elif row.kind == "sparkline" and row.sparkline_values:
            try:
                entry["sparkline"] = [float(v) for v in row.sparkline_values.split(",") if v]
            except ValueError:
                entry["sparkline"] = []

    out = []
    for t in TICKERS:
        cached = by_symbol.get(t["symbol"], {})
        item = {"symbol": t["symbol"], "logo": t["logo"], "index": bool(t.get("index"))}
        if "price" in cached:
            item.update(
                status="ok",
                price=cached["price"],
                currency=cached["currency"],
                change_percent=cached["change_percent"],
                sparkline=cached.get("sparkline") or [],
            )
        else:
            item["status"] = "unavailable"
        out.append(item)
    return out


def get_market_snapshot(db: Session) -> list[dict]:
    """Returns one entry per TICKERS item. Never raises, never fabricates a
    price -- a symbol with no good cached data comes back with
    status="unavailable" and no price/change/sparkline fields.

    On every call: makes sure every (symbol, kind) row exists (seeding, if
    this is the very first call ever -- progressively rate-limited, see
    module docstring), claims EVERY durably rate-limited refresh that
    still fits the rolling credit budget right now (not just one -- see
    claim_market_ticker_refresh's docstring for why), performs each claim
    won, then reads and returns the full current snapshot regardless of
    how many claims happened. All Twelve Data traffic is driven by this
    function; nothing else in the app calls Twelve Data."""
    now = _utcnow()
    ensure_market_ticker_rows(db, TICKERS, now)
    claims = claim_market_ticker_refresh(
        db,
        now=now,
        max_credits_per_window=MAX_CREDITS_PER_WINDOW,
        window_seconds=RATE_WINDOW_SECONDS,
        quote_interval_seconds=QUOTE_REFRESH_SECONDS,
        sparkline_interval_seconds=SPARKLINE_REFRESH_SECONDS,
    )
    for claim in claims:
        _perform_claim(db, claim, now)
    rows = get_market_ticker_cache_rows(db)
    return _build_snapshot(rows)
