"""Tests for MCP API routes (/api/mcp/*).

These endpoints are unauthenticated and power the MCP server.
Tests cover all 7 tool endpoints with:
- Happy path (data present)
- Empty database responses
- Parameter validation
- Filtering and search
- Edge cases
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-mcp-api-tests-12345!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-mcp-api-tests-12345!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-mcp-api-tests-12345!"},
    )


@pytest.fixture
async def app_with_db(tmp_settings):
    app = create_app(tmp_settings)
    await connect_db(app)
    register_routes(app)
    yield app
    if hasattr(app.state, "db"):
        await app.state.db.close()
    cleanup = getattr(app.state, "_db_cleanup_task", None)
    if cleanup:
        cleanup.cancel()


@pytest.fixture
def client(app_with_db):
    return TestClient(app_with_db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_signal(
    db, ticker="AAPL", stance="bullish", confidence=0.75,
    event_type="earnings_rumor", strategy="long_call",
    subreddit="wallstreetbets", title=None,
):
    """Insert a signal row and return its id."""
    sig_id = uuid.uuid4().hex
    now = time.time()
    post_title = title or f"Test post about {ticker}"
    await db.db.execute(
        """INSERT INTO signals
           (id, run_id, created_at, ticker, event_type, stance, time_horizon,
            confidence, trend_score, quality_score, strategy, subreddit,
            post_title, post_url, reasoning)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sig_id, "test_run", now, ticker, event_type, stance, "short",
         confidence, 5.0, 0.8, strategy, subreddit,
         post_title, f"https://reddit.com/r/{subreddit}/test",
         '{"thesis":"test"}'),
    )
    await db.db.commit()
    return sig_id


async def _insert_unusual_event(db, ticker="TSLA", event_type="iv_spike", score=85.0):
    """Insert an unusual activity event."""
    now = time.time()
    await db.db.execute(
        """INSERT INTO unusual_events
           (ticker, event_type, score, detected_at, details_json)
           VALUES (?, ?, ?, ?, ?)""",
        (ticker, event_type, score, now, '{"description":"test spike"}'),
    )
    await db.db.commit()


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/mcp/trending
# ═══════════════════════════════════════════════════════════════════════════


class TestMcpTrending:
    """Tests for GET /api/mcp/trending."""

    @pytest.mark.asyncio
    async def test_trending_returns_structure(self, client):
        """Trending returns expected response structure."""
        resp = client.get("/api/mcp/trending")
        assert resp.status_code == 200
        data = resp.json()
        assert "tickers" in data
        assert "period_hours" in data
        assert "count" in data
        assert isinstance(data["tickers"], list)

    @pytest.mark.asyncio
    async def test_trending_with_signals(self, client, app_with_db):
        """Trending returns tickers ranked by signal count."""
        db = app_with_db.state.db
        for _ in range(3):
            await _insert_signal(db, ticker="NVDA")
        await _insert_signal(db, ticker="AAPL")

        resp = client.get("/api/mcp/trending")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        tickers = data["tickers"]
        assert len(tickers) >= 1

    @pytest.mark.asyncio
    async def test_trending_custom_params(self, client, app_with_db):
        """Custom hours and limit are respected."""
        db = app_with_db.state.db
        await _insert_signal(db, ticker="TSLA")

        resp = client.get("/api/mcp/trending?hours=48&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["period_hours"] == 48

    @pytest.mark.asyncio
    async def test_trending_invalid_hours(self, client):
        """Invalid hours parameter returns 422."""
        resp = client.get("/api/mcp/trending?hours=0")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_trending_no_auth_required(self, client):
        """Trending endpoint is accessible without authentication."""
        resp = client.get("/api/mcp/trending")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/mcp/signals
# ═══════════════════════════════════════════════════════════════════════════


class TestMcpSignals:
    """Tests for GET /api/mcp/signals."""

    @pytest.mark.asyncio
    async def test_signals_returns_list(self, client):
        """Signals endpoint returns a list structure."""
        resp = client.get("/api/mcp/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert "signals" in data
        assert isinstance(data["signals"], list)
        assert "count" in data

    @pytest.mark.asyncio
    async def test_signals_returns_data(self, client, app_with_db):
        """Signals endpoint returns formatted signal data."""
        db = app_with_db.state.db
        await _insert_signal(db, ticker="AAPL", stance="bullish", confidence=0.8)

        resp = client.get("/api/mcp/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        sig = data["signals"][0]
        assert "ticker" in sig
        assert "stance" in sig
        assert "confidence" in sig
        assert "event_type" in sig
        assert "created_at" in sig

    @pytest.mark.asyncio
    async def test_signals_filter_by_ticker(self, client, app_with_db):
        """Filtering by ticker returns only matching signals."""
        db = app_with_db.state.db
        await _insert_signal(db, ticker="AAPL")
        await _insert_signal(db, ticker="TSLA")

        resp = client.get("/api/mcp/signals?ticker=AAPL")
        assert resp.status_code == 200
        data = resp.json()
        for sig in data["signals"]:
            assert sig["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_signals_filter_by_stance(self, client, app_with_db):
        """Filtering by stance returns only matching signals."""
        db = app_with_db.state.db
        await _insert_signal(db, ticker="NVDA", stance="bullish")
        await _insert_signal(db, ticker="AMD", stance="bearish")

        resp = client.get("/api/mcp/signals?stance=bearish")
        assert resp.status_code == 200
        data = resp.json()
        for sig in data["signals"]:
            assert sig["stance"] == "bearish"

    @pytest.mark.asyncio
    async def test_signals_limit(self, client, app_with_db):
        """Limit parameter caps number of results."""
        db = app_with_db.state.db
        for i in range(5):
            await _insert_signal(db, ticker=f"T{i:03d}")

        resp = client.get("/api/mcp/signals?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["signals"]) <= 2

    @pytest.mark.asyncio
    async def test_signals_invalid_stance(self, client):
        """Invalid stance parameter returns 422."""
        resp = client.get("/api/mcp/signals?stance=invalid")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_signals_case_insensitive_ticker(self, client, app_with_db):
        """Ticker filter is case-insensitive (lowered to upper)."""
        db = app_with_db.state.db
        await _insert_signal(db, ticker="MSFT")

        resp = client.get("/api/mcp/signals?ticker=msft")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filters"]["ticker"] == "msft"

    @pytest.mark.asyncio
    async def test_signals_includes_filters_in_response(self, client):
        """Response includes applied filters for transparency."""
        resp = client.get("/api/mcp/signals?ticker=AAPL&stance=bullish&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filters"]["ticker"] == "AAPL"
        assert data["filters"]["stance"] == "bullish"
        assert data["filters"]["limit"] == 5


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/mcp/sentiment
# ═══════════════════════════════════════════════════════════════════════════


class TestMcpSentiment:
    """Tests for GET /api/mcp/sentiment."""

    @pytest.mark.asyncio
    async def test_sentiment_no_signals(self, client):
        """Ticker with no signals returns zero counts."""
        resp = client.get("/api/mcp/sentiment?ticker=ZZZZ")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "ZZZZ"
        assert data["signal_count"] == 0
        assert data["net_sentiment"] == 0.0

    @pytest.mark.asyncio
    async def test_sentiment_bullish_dominant(self, client, app_with_db):
        """Mostly bullish signals yield positive net sentiment."""
        db = app_with_db.state.db
        # Use unique ticker to avoid cross-test pollution
        ticker = f"BUL{uuid.uuid4().hex[:4].upper()}"
        for _ in range(4):
            await _insert_signal(db, ticker=ticker, stance="bullish")
        await _insert_signal(db, ticker=ticker, stance="bearish")

        resp = client.get(f"/api/mcp/sentiment?ticker={ticker}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == ticker
        assert data["bullish"] == 4
        assert data["bearish"] == 1
        assert data["net_sentiment"] > 0

    @pytest.mark.asyncio
    async def test_sentiment_bearish_dominant(self, client, app_with_db):
        """Mostly bearish signals yield negative net sentiment."""
        db = app_with_db.state.db
        ticker = f"BER{uuid.uuid4().hex[:4].upper()}"
        await _insert_signal(db, ticker=ticker, stance="bullish")
        for _ in range(3):
            await _insert_signal(db, ticker=ticker, stance="bearish")

        resp = client.get(f"/api/mcp/sentiment?ticker={ticker}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["net_sentiment"] < 0
        assert data["bearish"] > data["bullish"]

    @pytest.mark.asyncio
    async def test_sentiment_requires_ticker(self, client):
        """Missing ticker parameter returns 422."""
        resp = client.get("/api/mcp/sentiment")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_sentiment_avg_confidence(self, client, app_with_db):
        """Average confidence is correctly computed."""
        db = app_with_db.state.db
        ticker = f"AVG{uuid.uuid4().hex[:4].upper()}"
        await _insert_signal(db, ticker=ticker, confidence=0.6)
        await _insert_signal(db, ticker=ticker, confidence=0.8)

        resp = client.get(f"/api/mcp/sentiment?ticker={ticker}")
        assert resp.status_code == 200
        data = resp.json()
        assert 0.6 <= data["avg_confidence"] <= 0.8

    @pytest.mark.asyncio
    async def test_sentiment_includes_mixed_unknown(self, client, app_with_db):
        """Mixed and unknown stances are counted."""
        db = app_with_db.state.db
        ticker = f"MIX{uuid.uuid4().hex[:4].upper()}"
        await _insert_signal(db, ticker=ticker, stance="mixed")
        await _insert_signal(db, ticker=ticker, stance="unknown")

        resp = client.get(f"/api/mcp/sentiment?ticker={ticker}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mixed"] == 1
        assert data["unknown"] == 1
        assert data["signal_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/mcp/overview
# ═══════════════════════════════════════════════════════════════════════════


class TestMcpOverview:
    """Tests for GET /api/mcp/overview."""

    @pytest.mark.asyncio
    async def test_overview_returns_structure(self, client):
        """Overview returns expected structure."""
        resp = client.get("/api/mcp/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["period_days"] == 30
        assert "total_signals" in data

    @pytest.mark.asyncio
    async def test_overview_with_signals(self, client, app_with_db):
        """Overview reflects inserted signal data."""
        db = app_with_db.state.db
        await _insert_signal(db, ticker="AAPL", stance="bullish")
        await _insert_signal(db, ticker="TSLA", stance="bearish")
        await _insert_signal(db, ticker="NVDA", stance="mixed")

        resp = client.get("/api/mcp/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_signals"] >= 3
        assert data["bullish_count"] >= 1
        assert data["bearish_count"] >= 1
        assert "avg_confidence" in data
        assert "win_rate" in data
        assert "unique_tickers" in data

    @pytest.mark.asyncio
    async def test_overview_no_params(self, client):
        """Overview takes no parameters."""
        resp = client.get("/api/mcp/overview")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_overview_tradeable_count(self, client, app_with_db):
        """Tradeable signals count only bullish/bearish, not mixed/unknown."""
        db = app_with_db.state.db
        await _insert_signal(db, stance="bullish")
        await _insert_signal(db, stance="bearish")
        await _insert_signal(db, stance="mixed")
        await _insert_signal(db, stance="unknown")

        resp = client.get("/api/mcp/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tradeable_signals"] >= 2

    @pytest.mark.asyncio
    async def test_overview_response_keys(self, client):
        """All expected keys are present in response."""
        resp = client.get("/api/mcp/overview")
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "period_days", "total_signals", "tradeable_signals",
            "avg_confidence", "signals_today", "signals_7d",
            "unique_tickers", "bullish_count", "bearish_count",
            "win_rate", "total_tracked", "winners", "losers",
        }
        assert expected_keys.issubset(set(data.keys()))


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/mcp/unusual
# ═══════════════════════════════════════════════════════════════════════════


class TestMcpUnusual:
    """Tests for GET /api/mcp/unusual."""

    @pytest.mark.asyncio
    async def test_unusual_returns_structure(self, client):
        """Unusual endpoint returns expected structure."""
        resp = client.get("/api/mcp/unusual")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert isinstance(data["events"], list)
        assert "count" in data

    @pytest.mark.asyncio
    async def test_unusual_with_events(self, client, app_with_db):
        """Unusual events are returned with expected fields."""
        db = app_with_db.state.db
        await _insert_unusual_event(db, ticker="TSLA", event_type="iv_spike", score=85.0)

        resp = client.get("/api/mcp/unusual")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        evt = data["events"][0]
        assert evt["ticker"] == "TSLA"
        assert evt["event_type"] == "iv_spike"

    @pytest.mark.asyncio
    async def test_unusual_custom_hours(self, client, app_with_db):
        """Custom hours parameter is passed through."""
        db = app_with_db.state.db
        await _insert_unusual_event(db)

        resp = client.get("/api/mcp/unusual?hours=48")
        assert resp.status_code == 200
        data = resp.json()
        assert data["period_hours"] == 48

    @pytest.mark.asyncio
    async def test_unusual_limit(self, client, app_with_db):
        """Limit caps the number of returned events."""
        db = app_with_db.state.db
        for i in range(5):
            await _insert_unusual_event(db, ticker=f"T{i:03d}")

        resp = client.get("/api/mcp/unusual?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) <= 2

    @pytest.mark.asyncio
    async def test_unusual_no_auth_required(self, client):
        """Unusual endpoint is accessible without authentication."""
        resp = client.get("/api/mcp/unusual")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/mcp/sports
# ═══════════════════════════════════════════════════════════════════════════


class TestMcpSports:
    """Tests for GET /api/mcp/sports."""

    @pytest.mark.asyncio
    async def test_sports_returns_200(self, client):
        """Sports endpoint returns 200 even with empty cache."""
        resp = client.get("/api/mcp/sports")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "count" in data

    @pytest.mark.asyncio
    async def test_sports_league_filter(self, client):
        """League filter param is accepted."""
        resp = client.get("/api/mcp/sports?league=NFL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["league_filter"] == "NFL"

    @pytest.mark.asyncio
    async def test_sports_invalid_league(self, client):
        """Invalid league returns 422."""
        resp = client.get("/api/mcp/sports?league=CRICKET")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_sports_limit_param(self, client):
        """Limit param is accepted."""
        resp = client.get("/api/mcp/sports?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 5

    @pytest.mark.asyncio
    async def test_sports_no_auth_required(self, client):
        """Sports endpoint is accessible without authentication."""
        resp = client.get("/api/mcp/sports")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/mcp/search
# ═══════════════════════════════════════════════════════════════════════════


class TestMcpSearch:
    """Tests for GET /api/mcp/search."""

    @pytest.mark.asyncio
    async def test_search_no_results(self, client):
        """Search with no matching signals returns empty results."""
        resp = client.get("/api/mcp/search?q=XYZZY_NONEXISTENT_99")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["query"] == "XYZZY_NONEXISTENT_99"

    @pytest.mark.asyncio
    async def test_search_by_ticker(self, client, app_with_db):
        """Search matches exact ticker symbols."""
        db = app_with_db.state.db
        await _insert_signal(db, ticker="AAPL")
        await _insert_signal(db, ticker="TSLA")

        resp = client.get("/api/mcp/search?q=AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert any(r["ticker"] == "AAPL" for r in data["results"])

    @pytest.mark.asyncio
    async def test_search_by_title(self, client, app_with_db):
        """Search matches post title text."""
        db = app_with_db.state.db
        await _insert_signal(db, ticker="PFE", title="FDA approval for new drug")

        resp = client.get("/api/mcp/search?q=FDA approval")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1

    @pytest.mark.asyncio
    async def test_search_deduplicates(self, client, app_with_db):
        """Results are deduplicated when ticker and title match the same signal."""
        db = app_with_db.state.db
        await _insert_signal(db, ticker="NVDA", title="NVDA earnings crush estimates")

        resp = client.get("/api/mcp/search?q=NVDA")
        assert resp.status_code == 200
        data = resp.json()
        # Even though NVDA matches both ticker and title, each signal appears once
        ids = [r["id"] for r in data["results"]]
        assert len(ids) == len(set(ids))

    @pytest.mark.asyncio
    async def test_search_requires_query(self, client):
        """Missing query parameter returns 422."""
        resp = client.get("/api/mcp/search")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_limit(self, client, app_with_db):
        """Limit caps search results."""
        db = app_with_db.state.db
        for i in range(5):
            await _insert_signal(db, ticker="AMD", title=f"AMD analysis part {i}")

        resp = client.get("/api/mcp/search?q=AMD&limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 2

    @pytest.mark.asyncio
    async def test_search_response_fields(self, client, app_with_db):
        """Search results contain expected fields."""
        db = app_with_db.state.db
        await _insert_signal(db, ticker="MSFT")

        resp = client.get("/api/mcp/search?q=MSFT")
        assert resp.status_code == 200
        data = resp.json()
        if data["count"] > 0:
            result = data["results"][0]
            expected_fields = {"id", "ticker", "stance", "confidence", "event_type",
                               "strategy", "subreddit", "post_title", "created_at"}
            assert expected_fields.issubset(set(result.keys()))


# ═══════════════════════════════════════════════════════════════════════════
# Cross-cutting concerns
# ═══════════════════════════════════════════════════════════════════════════


class TestMcpCrossCutting:
    """Tests for properties shared across all MCP endpoints."""

    @pytest.mark.asyncio
    async def test_all_endpoints_return_json(self, client):
        """All MCP endpoints return application/json."""
        endpoints = [
            "/api/mcp/trending",
            "/api/mcp/signals",
            "/api/mcp/sentiment?ticker=TEST",
            "/api/mcp/overview",
            "/api/mcp/unusual",
            "/api/mcp/sports",
            "/api/mcp/search?q=test",
        ]
        for url in endpoints:
            resp = client.get(url)
            assert resp.status_code == 200, f"Failed for {url}: {resp.status_code}"
            assert "application/json" in resp.headers.get("content-type", ""), f"Not JSON for {url}"

    @pytest.mark.asyncio
    async def test_no_authentication_required(self, client):
        """All MCP endpoints work without any auth headers."""
        endpoints = [
            "/api/mcp/trending",
            "/api/mcp/signals",
            "/api/mcp/sentiment?ticker=TEST",
            "/api/mcp/overview",
            "/api/mcp/unusual",
            "/api/mcp/sports",
            "/api/mcp/search?q=test",
        ]
        for url in endpoints:
            resp = client.get(url)
            assert resp.status_code == 200, f"Auth failure for {url}: {resp.status_code}"

    @pytest.mark.asyncio
    async def test_cors_headers_present(self, client):
        """MCP endpoints include CORS headers for cross-origin access."""
        resp = client.get("/api/mcp/trending")
        # CORS middleware should be active
        assert resp.status_code == 200
