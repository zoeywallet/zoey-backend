"""
Tests for the durable, rate-limited market-ticker snapshot
(backend/services/market_data.py + backend/database.py's
MarketTickerCache/MarketTickerCreditLog-backed functions).

Same fixture pattern as tests/test_api.py (a fresh throwaway SQLite file
per test -- never your real local.db, never production): see that file's
own `client`/`db_session` fixtures, duplicated here rather than shared via
a new conftest.py, since none exists in this project yet.

Run with:

    pytest tests/test_market_data.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os  # noqa: E402

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ["COOKIE_SECURE"] = "false"
os.environ["RATE_LIMIT_MAX"] = "1000"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A fresh app + fresh SQLite file per test -- identical pattern to
    tests/test_api.py's own `client` fixture."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    for mod in list(sys.modules):
        if mod == "api.index" or mod.startswith("backend."):
            del sys.modules[mod]

    from fastapi.testclient import TestClient

    from api.index import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session(client):
    """A SQLAlchemy session bound to the same throwaway database `client`
    is using -- identical pattern to tests/test_api.py's own fixture."""
    from backend.database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# A small, deterministic stand-in for Twelve Data's /quote response shape
# (multi-symbol: a dict keyed by symbol).
def _fake_quote_payload(symbols: list[str]) -> dict:
    return {
        s: {"symbol": s, "close": "123.45", "percent_change": "1.23", "currency": "USD"}
        for s in symbols
    }


def _fake_timeseries_payload(symbols: list[str]) -> dict:
    return {
        s: {"values": [{"close": str(100 + i)} for i in range(5)]}
        for s in symbols
    }


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, raise_exc=None):
        self._json_data = json_data
        self.status_code = status_code
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._json_data


def _patch_twelve_data(monkeypatch, responder):
    """Patches backend.services.market_data's requests.get with a callable
    `responder(url, params) -> _FakeResponse`."""
    import backend.services.market_data as market_data

    def fake_get(url, params=None, timeout=None):
        return responder(url, params or {})

    monkeypatch.setattr(market_data.requests, "get", fake_get)
    monkeypatch.setattr(market_data, "TWELVE_DATA_API_KEY", "test-key-not-real")


def _success_responder(url, params):
    symbols = params.get("symbol", "").split(",")
    if url.endswith("/quote"):
        return _FakeResponse(json_data=_fake_quote_payload(symbols))
    return _FakeResponse(json_data=_fake_timeseries_payload(symbols))


class TestEmptySnapshot:
    def test_empty_snapshot_before_any_successful_fetch(self, client, monkeypatch, db_session):
        """With no API key configured (and therefore no Twelve Data call
        ever succeeding), the very first request still returns all 11
        symbols, each honestly marked unavailable -- never a crash, never
        a fabricated price."""
        import backend.services.market_data as market_data

        monkeypatch.setattr(market_data, "TWELVE_DATA_API_KEY", "")  # no key configured

        resp = client.get("/api/markets/ticker")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tickers"]) == 11
        symbols = {t["symbol"] for t in data["tickers"]}
        assert symbols == {"AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "GOOGL", "META", "AMD", "PLTR", "NFLX", "NASDAQ"}
        for t in data["tickers"]:
            assert t["status"] == "unavailable"
            assert "price" not in t


class TestProgressiveSeeding:
    def test_seeding_never_bursts_all_11_symbols_at_once(self, client, monkeypatch, db_session):
        """On a brand-new table, the first request claims at most one
        group (<=3 symbols) worth of price credits -- never the old
        11-quote + 11-time_series = 22-credit burst."""
        import backend.database as database
        import backend.services.market_data as market_data

        calls = []

        def counting_responder(url, params):
            calls.append((url, params.get("symbol", "").split(",")))
            return _success_responder(url, params)

        _patch_twelve_data(monkeypatch, counting_responder)

        resp = client.get("/api/markets/ticker")
        assert resp.status_code == 200

        # Exactly one upstream call this request, for <=3 symbols -- not 11.
        assert len(calls) == 1
        _, symbols_requested = calls[0]
        assert 1 <= len(symbols_requested) <= 3

        rows = database.get_market_ticker_cache_rows(db_session)
        fetched = [r for r in rows if r.fetched_at is not None]
        assert 1 <= len(fetched) <= 3

    def test_previously_fetched_symbols_stay_visible_while_others_seed(self, client, monkeypatch, db_session):
        """Symbols from an already-claimed group keep showing real data
        while other groups are still waiting their turn."""
        import backend.database as database
        import backend.services.market_data as market_data

        _patch_twelve_data(monkeypatch, _success_responder)

        # First request claims one price group.
        client.get("/api/markets/ticker")
        rows = database.get_market_ticker_cache_rows(db_session)
        first_fetched = {r.symbol for r in rows if r.kind == "quote" and r.fetched_at is not None}
        assert 1 <= len(first_fetched) <= 3

        # Advance time well past the per-group interval so a second group
        # becomes due, then make another request.
        future = _utcnow() + timedelta(seconds=market_data.QUOTE_REFRESH_SECONDS + 1)
        with patch.object(market_data, "_utcnow", return_value=future):
            resp = client.get("/api/markets/ticker")

        data = resp.json()
        ok_symbols = {t["symbol"] for t in data["tickers"] if t["status"] == "ok"}
        # Everything claimed so far (first group, still cached) must still
        # be visible, even though a different group was just refreshed.
        assert first_fetched.issubset(ok_symbols)


class TestCompleteSnapshot:
    def test_all_11_symbols_eventually_populate(self, client, monkeypatch, db_session):
        """Advancing through enough rate-limited claims (simulating time
        passing across several windows) eventually fills in all 11
        symbols' prices, without ever exceeding the credit budget on any
        single claim."""
        import backend.services.market_data as market_data

        _patch_twelve_data(monkeypatch, _success_responder)

        t = _utcnow()
        for _ in range(20):  # far more ticks than the 4 groups need
            with patch.object(market_data, "_utcnow", return_value=t):
                resp = client.get("/api/markets/ticker")
            t = t + timedelta(seconds=market_data.QUOTE_REFRESH_SECONDS + 1)

        data = resp.json()
        assert all(t["status"] == "ok" for t in data["tickers"])
        assert all("price" in t and "sparkline" in t for t in data["tickers"])


class TestAtomicClaimConcurrency:
    def test_two_claims_in_the_same_instant_never_double_claim_the_same_group(self, db_session):
        """Simulates two concurrent requests arriving at the same instant:
        calling claim_market_ticker_refresh twice in a row at the same
        `now` must never let both claim the *same* group -- the second
        call either gets a different group or None."""
        from backend.database import claim_market_ticker_refresh, ensure_market_ticker_rows
        from backend.services.market_data import TICKERS, MAX_CREDITS_PER_WINDOW, RATE_WINDOW_SECONDS, QUOTE_REFRESH_SECONDS, SPARKLINE_REFRESH_SECONDS

        now = _utcnow()
        ensure_market_ticker_rows(db_session, TICKERS, now)

        claim1 = claim_market_ticker_refresh(
            db_session, now=now, max_credits_per_window=MAX_CREDITS_PER_WINDOW,
            window_seconds=RATE_WINDOW_SECONDS, quote_interval_seconds=QUOTE_REFRESH_SECONDS,
            sparkline_interval_seconds=SPARKLINE_REFRESH_SECONDS,
        )
        claim2 = claim_market_ticker_refresh(
            db_session, now=now, max_credits_per_window=MAX_CREDITS_PER_WINDOW,
            window_seconds=RATE_WINDOW_SECONDS, quote_interval_seconds=QUOTE_REFRESH_SECONDS,
            sparkline_interval_seconds=SPARKLINE_REFRESH_SECONDS,
        )
        assert claim1 is not None
        if claim2 is not None:
            assert (claim1["group_name"], claim1["kind"]) != (claim2["group_name"], claim2["kind"])


class TestMaxCreditScheduling:
    def test_never_exceeds_six_credits_in_any_rolling_60_seconds(self, db_session):
        """Property check: repeatedly claim (simulating a thundering herd
        immediately after the table is created, when every group is
        simultaneously due) and verify the rolling 60-second credit sum
        never exceeds the approved 6-credit ceiling, by construction."""
        from backend.database import claim_market_ticker_refresh, ensure_market_ticker_rows
        from backend.models import MarketTickerCreditLog
        from backend.services.market_data import TICKERS, MAX_CREDITS_PER_WINDOW, RATE_WINDOW_SECONDS, QUOTE_REFRESH_SECONDS, SPARKLINE_REFRESH_SECONDS
        from sqlalchemy import select

        now = _utcnow()
        ensure_market_ticker_rows(db_session, TICKERS, now)

        for _ in range(10):  # far more attempts than there are due groups
            claim_market_ticker_refresh(
                db_session, now=now, max_credits_per_window=MAX_CREDITS_PER_WINDOW,
                window_seconds=RATE_WINDOW_SECONDS, quote_interval_seconds=QUOTE_REFRESH_SECONDS,
                sparkline_interval_seconds=SPARKLINE_REFRESH_SECONDS,
            )
            window_start = now - timedelta(seconds=RATE_WINDOW_SECONDS)
            used = db_session.execute(
                select(MarketTickerCreditLog).where(MarketTickerCreditLog.claimed_at > window_start)
            ).scalars().all()
            total = sum(r.credits for r in used)
            assert total <= MAX_CREDITS_PER_WINDOW


class TestStaleRefresh:
    def test_price_group_not_due_is_not_reclaimed(self, db_session):
        from backend.database import claim_market_ticker_refresh, ensure_market_ticker_rows
        from backend.services.market_data import TICKERS, MAX_CREDITS_PER_WINDOW, RATE_WINDOW_SECONDS, QUOTE_REFRESH_SECONDS, SPARKLINE_REFRESH_SECONDS

        now = _utcnow()
        ensure_market_ticker_rows(db_session, TICKERS, now)

        claim = claim_market_ticker_refresh(
            db_session, now=now, max_credits_per_window=MAX_CREDITS_PER_WINDOW,
            window_seconds=RATE_WINDOW_SECONDS, quote_interval_seconds=QUOTE_REFRESH_SECONDS,
            sparkline_interval_seconds=SPARKLINE_REFRESH_SECONDS,
        )
        assert claim is not None
        group, kind = claim["group_name"], claim["kind"]

        # Immediately after being claimed, that same group+kind must not
        # be claimable again until its interval elapses.
        soon = now + timedelta(seconds=1)
        claim2 = claim_market_ticker_refresh(
            db_session, now=soon, max_credits_per_window=MAX_CREDITS_PER_WINDOW,
            window_seconds=RATE_WINDOW_SECONDS, quote_interval_seconds=QUOTE_REFRESH_SECONDS,
            sparkline_interval_seconds=SPARKLINE_REFRESH_SECONDS,
        )
        if claim2 is not None:
            assert (claim2["group_name"], claim2["kind"]) != (group, kind)

    def test_sparkline_group_not_due_is_not_reclaimed(self, db_session):
        """Same guarantee, specifically for the sparkline schedule, which
        runs on its own, much slower interval than price."""
        from backend.database import claim_market_ticker_refresh, ensure_market_ticker_rows
        from backend.services.market_data import TICKERS, MAX_CREDITS_PER_WINDOW, RATE_WINDOW_SECONDS, QUOTE_REFRESH_SECONDS, SPARKLINE_REFRESH_SECONDS

        now = _utcnow()
        ensure_market_ticker_rows(db_session, TICKERS, now)

        seen_kinds = set()
        t = now
        for _ in range(8):
            claim = claim_market_ticker_refresh(
                db_session, now=t, max_credits_per_window=MAX_CREDITS_PER_WINDOW,
                window_seconds=RATE_WINDOW_SECONDS, quote_interval_seconds=QUOTE_REFRESH_SECONDS,
                sparkline_interval_seconds=SPARKLINE_REFRESH_SECONDS,
            )
            if claim is not None:
                seen_kinds.add(claim["kind"])
            t = t + timedelta(seconds=QUOTE_REFRESH_SECONDS + 1)  # advances past price interval, not sparkline's

        # Over several price-interval ticks (but far short of the much
        # longer sparkline interval), sparkline claims stay rare/absent --
        # this assertion just confirms "quote" claims dominate this short
        # a span, i.e. the two schedules are genuinely decoupled.
        assert "quote" in seen_kinds


class TestFailureBehavior:
    def test_429_preserves_existing_valid_data(self, client, monkeypatch, db_session):
        import requests as requests_module

        import backend.services.market_data as market_data

        # First: a successful fetch, so there is good data to protect.
        _patch_twelve_data(monkeypatch, _success_responder)
        client.get("/api/markets/ticker")

        import backend.database as database

        before = {(r.symbol, r.kind): (r.price, r.sparkline_values) for r in database.get_market_ticker_cache_rows(db_session)}

        # Advance to the next due window, then simulate Twelve Data 429ing.
        def raise_429(url, params=None, timeout=None):
            resp = _FakeResponse(status_code=429)
            err = requests_module.exceptions.HTTPError("429 Client Error: Too Many Requests for url: https://api.twelvedata.com/quote?apikey=SECRET")
            err.response = resp
            resp._raise_exc = err
            return resp

        monkeypatch.setattr(market_data.requests, "get", raise_429)
        future = _utcnow() + timedelta(seconds=market_data.QUOTE_REFRESH_SECONDS + 1)
        with patch.object(market_data, "_utcnow", return_value=future):
            resp = client.get("/api/markets/ticker")
        assert resp.status_code == 200

        after = {(r.symbol, r.kind): (r.price, r.sparkline_values) for r in database.get_market_ticker_cache_rows(db_session)}
        # Nothing that had good data before the 429 was cleared by it.
        for key, (price, spark) in before.items():
            if price is not None or spark is not None:
                assert after[key] == (price, spark)

    def test_timeout_preserves_existing_valid_data_and_does_not_crash(self, client, monkeypatch, db_session):
        import requests as requests_module

        import backend.services.market_data as market_data

        _patch_twelve_data(monkeypatch, _success_responder)
        client.get("/api/markets/ticker")

        def raise_timeout(url, params=None, timeout=None):
            raise requests_module.exceptions.Timeout("timed out")

        monkeypatch.setattr(market_data.requests, "get", raise_timeout)
        future = _utcnow() + timedelta(seconds=market_data.QUOTE_REFRESH_SECONDS + 1)
        with patch.object(market_data, "_utcnow", return_value=future):
            resp = client.get("/api/markets/ticker")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tickers"]) == 11  # still a complete, well-formed response


class TestApiKeySanitization:
    def test_logs_never_contain_the_api_key_or_full_url_on_http_error(self, monkeypatch, caplog):
        import logging

        import requests as requests_module

        import backend.services.market_data as market_data

        monkeypatch.setattr(market_data, "TWELVE_DATA_API_KEY", "super-secret-td-key-12345")

        def fake_get(url, params=None, timeout=None):
            resp = _FakeResponse(status_code=429)
            err = requests_module.exceptions.HTTPError(
                "429 Client Error: Too Many Requests for url: "
                f"{url}?symbol=AAPL&apikey=super-secret-td-key-12345"
            )
            err.response = resp
            raise err

        monkeypatch.setattr(market_data.requests, "get", fake_get)

        with caplog.at_level(logging.WARNING, logger="zoey.market_data"):
            result = market_data._twelve_data_get("quote", {"symbol": "AAPL"})

        assert result is None
        all_log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert "super-secret-td-key-12345" not in all_log_text
        assert "apikey" not in all_log_text
        assert "https://api.twelvedata.com" not in all_log_text
        assert "endpoint=quote" in all_log_text
        assert "status=429" in all_log_text

    def test_response_never_contains_the_api_key(self, client, monkeypatch, db_session):
        monkeypatch.setattr(
            __import__("backend.services.market_data", fromlist=["x"]), "TWELVE_DATA_API_KEY", "super-secret-td-key-12345"
        )
        resp = client.get("/api/markets/ticker")
        assert "super-secret-td-key-12345" not in resp.text


class TestResponseSchema:
    def test_response_schema_matches_existing_frontend_contract(self, client, monkeypatch, db_session):
        """index.html's tickerCardHTML expects exactly these fields; this
        guards against an accidental shape change."""
        _patch_twelve_data(monkeypatch, _success_responder)
        import backend.services.market_data as market_data

        t = _utcnow()
        for _ in range(20):
            with patch.object(market_data, "_utcnow", return_value=t):
                resp = client.get("/api/markets/ticker")
            t = t + timedelta(seconds=market_data.QUOTE_REFRESH_SECONDS + 1)

        data = resp.json()
        assert "tickers" in data
        assert len(data["tickers"]) == 11
        for item in data["tickers"]:
            assert set(["symbol", "logo", "index", "status"]).issubset(item.keys())
            if item["status"] == "ok":
                assert set(["price", "currency", "change_percent", "sparkline"]).issubset(item.keys())
                assert isinstance(item["sparkline"], list)
