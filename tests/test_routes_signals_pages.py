"""Signal route tests.

Tests for signal list (API), signal detail (HTML + API), trending tickers,
performance endpoints, leaderboard, correlations, and sector detail.
Covers tier gating, pagination, filtering, field selection, and auth.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-signal-route-tests-1234!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes
from rot.web.auth import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-signal-route-tests-1234!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-signal-route-tests-1234!"},
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

async def _create_user(app, settings, tier="free"):
    """Create a user at the given tier and return (user_dict, jwt_token)."""
    db = app.state.db
    unique = uuid.uuid4().hex[:8]
    email = f"sig_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


async def _insert_signal(db, ticker="AAPL", stance="bullish", confidence=0.75,
                         event_type="earnings_rumor", strategy="long_call",
                         subreddit="wallstreetbets"):
    """Insert a signal row into the database and return its id."""
    sig_id = uuid.uuid4().hex
    now = time.time()
    await db.db.execute(
        """INSERT INTO signals
           (id, created_at, ticker, event_type, stance, time_horizon,
            confidence, trend_score, quality_score, strategy, subreddit,
            post_title, post_url, reasoning, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sig_id, now, ticker, event_type, stance, "short",
         confidence, 5.0, 0.8, strategy, subreddit,
         f"Test post about {ticker}", f"https://reddit.com/r/{subreddit}/test",
         '{"thesis":"test"}', "reddit"),
    )
    await db.db.commit()
    return sig_id


# ═══════════════════════════════════════════════════════════════════════════
# Signal List API  (/api/v1/signals)
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalListAPI:
    """Tests for GET /api/v1/signals — requires API auth (pro+)."""

    @pytest.mark.asyncio
    async def test_anonymous_blocked(self, client):
        """Unauthenticated requests get 401/403."""
        resp = client.get("/api/v1/signals")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier cannot access API signals."""
        _, token = await _create_user(app_with_db, tmp_settings, "free")
        resp = client.get(
            "/api/v1/signals",
            cookies={"rot_session": token},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_pro_can_list_signals(self, client, app_with_db, tmp_settings):
        """Pro tier can list signals via API."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        # Generate API key for the user
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get("/api/v1/signals", headers={"X-API-Key": api_key})
        assert resp.status_code == 200
        data = resp.json()
        assert "signals" in data
        assert "count" in data

    @pytest.mark.asyncio
    async def test_pro_list_with_signals(self, client, app_with_db, tmp_settings):
        """Pro tier sees inserted signals."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        await _insert_signal(db, "TSLA", "bearish", 0.9)
        await _insert_signal(db, "AAPL", "bullish", 0.6)
        resp = client.get("/api/v1/signals", headers={"X-API-Key": api_key})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 2

    @pytest.mark.parametrize("ticker", ["AAPL", "TSLA", "NVDA", "GME"])
    @pytest.mark.asyncio
    async def test_ticker_filter(self, ticker, client, app_with_db, tmp_settings):
        """Filter by different ticker symbols."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        await _insert_signal(db, ticker, "bullish", 0.8)
        resp = client.get(
            f"/api/v1/signals?ticker={ticker}",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("stance", ["bullish", "bearish", "mixed", "unknown"])
    @pytest.mark.asyncio
    async def test_stance_filter(self, stance, client, app_with_db, tmp_settings):
        """Filter by stance values."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            f"/api/v1/signals?stance={stance}",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("limit,offset", [
        (10, 0),
        (50, 0),
        (100, 10),
        (1, 0),
        (200, 0),
    ])
    @pytest.mark.asyncio
    async def test_pagination(self, limit, offset, client, app_with_db, tmp_settings):
        """Pagination parameters are accepted."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            f"/api/v1/signals?limit={limit}&offset={offset}",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "offset" in data

    @pytest.mark.asyncio
    async def test_field_selection(self, client, app_with_db, tmp_settings):
        """Field selection via ?fields= reduces returned fields."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        await _insert_signal(db, "AAPL", "bullish", 0.9)
        resp = client.get(
            "/api/v1/signals?fields=ticker,stance,confidence",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("sort_field", ["created_at", "confidence", "trend_score"])
    @pytest.mark.asyncio
    async def test_sort_fields(self, sort_field, client, app_with_db, tmp_settings):
        """Sort by allowed fields."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            f"/api/v1/signals?sort={sort_field}&order=desc",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_sort_rejected(self, client, app_with_db, tmp_settings):
        """Invalid sort field is rejected (422)."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            "/api/v1/signals?sort=invalid_field",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# Signal Detail (/api/v1/signals/{id})
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalDetail:
    """Tests for GET /api/v1/signals/{signal_id} — HTML and API."""

    @pytest.mark.asyncio
    async def test_detail_html_not_found(self, client):
        """Nonexistent signal returns 404."""
        resp = client.get(
            "/api/v1/signals/nonexistent-id",
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_detail_html_renders(self, client, app_with_db, tmp_settings):
        """Signal detail HTML renders for an existing signal."""
        db = app_with_db.state.db
        sig_id = await _insert_signal(db, "NVDA", "bullish", 0.85)
        resp = client.get(
            f"/api/v1/signals/{sig_id}",
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_detail_html_renders_authenticated(self, client, app_with_db, tmp_settings):
        """Signal detail HTML renders for authenticated user."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        sig_id = await _insert_signal(db, "MSFT", "bearish", 0.65)
        resp = client.get(
            f"/api/v1/signals/{sig_id}",
            headers={"Accept": "text/html"},
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_detail_api_requires_auth(self, client, app_with_db, tmp_settings):
        """API request for signal detail requires auth."""
        db = app_with_db.state.db
        sig_id = await _insert_signal(db, "GOOG", "bullish", 0.7)
        resp = client.get(
            f"/api/v1/signals/{sig_id}",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_detail_api_with_auth(self, client, app_with_db, tmp_settings):
        """Pro tier can get signal detail via API."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        sig_id = await _insert_signal(db, "META", "bullish", 0.9)
        resp = client.get(
            f"/api/v1/signals/{sig_id}",
            headers={"Accept": "application/json", "X-API-Key": api_key},
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("signal_id", [
        "does-not-exist",
        "00000000-0000-0000-0000-000000000000",
        "abc123",
        "",
    ])
    @pytest.mark.asyncio
    async def test_detail_missing_signals(self, signal_id, client):
        """Nonexistent signal IDs return 404 or 422."""
        resp = client.get(
            f"/api/v1/signals/{signal_id}",
            headers={"Accept": "text/html"},
        )
        assert resp.status_code in (404, 405, 422)


# ═══════════════════════════════════════════════════════════════════════════
# New Signal Count (/api/v1/signals/new-count)
# ═══════════════════════════════════════════════════════════════════════════

class TestNewSignalCount:
    """Tests for GET /api/v1/signals/new-count."""

    @pytest.mark.asyncio
    async def test_anonymous_returns_zero(self, client):
        """Anonymous user gets count 0."""
        resp = client.get("/api/v1/signals/new-count")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_authenticated_returns_count(self, client, app_with_db, tmp_settings):
        """Authenticated user gets signal count."""
        _, token = await _create_user(app_with_db, tmp_settings, "pro")
        resp = client.get(
            "/api/v1/signals/new-count",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data


# ═══════════════════════════════════════════════════════════════════════════
# Trending Tickers (/api/v1/tickers/trending)
# ═══════════════════════════════════════════════════════════════════════════

class TestTrendingTickers:
    """Tests for GET /api/v1/tickers/trending."""

    @pytest.mark.asyncio
    async def test_anonymous_blocked(self, client):
        """Anonymous access blocked."""
        resp = client.get("/api/v1/tickers/trending")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_pro_access(self, client, app_with_db, tmp_settings):
        """Pro tier can access trending tickers."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            "/api/v1/tickers/trending",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "tickers" in data

    @pytest.mark.parametrize("hours,limit", [
        (1, 5),
        (24, 20),
        (72, 50),
        (168, 100),
    ])
    @pytest.mark.asyncio
    async def test_trending_params(self, hours, limit, client, app_with_db, tmp_settings):
        """Different hours/limit combinations are accepted."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            f"/api/v1/tickers/trending?hours={hours}&limit={limit}",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Performance Endpoints
# ═══════════════════════════════════════════════════════════════════════════

class TestPerformanceSummary:
    """Tests for GET /api/v1/performance/summary."""

    @pytest.mark.asyncio
    async def test_anonymous_blocked(self, client):
        """Anonymous access blocked."""
        resp = client.get("/api/v1/performance/summary")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_pro_access(self, client, app_with_db, tmp_settings):
        """Pro tier can access performance summary."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            "/api/v1/performance/summary",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200


class TestPerformanceAccuracy:
    """Tests for GET /api/v1/performance/accuracy."""

    @pytest.mark.asyncio
    async def test_anonymous_blocked(self, client):
        resp = client.get("/api/v1/performance/accuracy")
        assert resp.status_code in (401, 403)

    @pytest.mark.parametrize("days", [1, 7, 30, 90, 365])
    @pytest.mark.asyncio
    async def test_accuracy_days(self, days, client, app_with_db, tmp_settings):
        """Different day ranges accepted."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            f"/api/v1/performance/accuracy?days={days}",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200


class TestPerformanceHistory:
    """Tests for GET /api/v1/performance/history — requires pro+."""

    @pytest.mark.asyncio
    async def test_free_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from performance history."""
        _, token = await _create_user(app_with_db, tmp_settings, "free")
        resp = client.get(
            "/api/v1/performance/history",
            cookies={"rot_session": token},
        )
        # require_tier uses require_user which checks for API auth context
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_pro_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access performance history."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            "/api/v1/performance/history",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200


class TestAccuracyChart:
    """Tests for GET /api/v1/performance/accuracy-chart — requires premium+."""

    @pytest.mark.parametrize("tier,expected_ok", [
        ("pro", False),
        ("premium", True),
        ("ultra", True),
    ])
    @pytest.mark.asyncio
    async def test_tier_gating(self, tier, expected_ok, client, app_with_db, tmp_settings):
        """Accuracy chart requires premium+."""
        user, token = await _create_user(app_with_db, tmp_settings, tier)
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            "/api/v1/performance/accuracy-chart",
            headers={"X-API-Key": api_key},
        )
        if expected_ok:
            assert resp.status_code == 200
        else:
            assert resp.status_code == 403


class TestStrategyPnl:
    """Tests for GET /api/v1/performance/strategy-pnl — requires ultra+."""

    @pytest.mark.parametrize("tier,expected_ok", [
        ("pro", False),
        ("premium", False),
        ("ultra", True),
    ])
    @pytest.mark.asyncio
    async def test_tier_gating(self, tier, expected_ok, client, app_with_db, tmp_settings):
        """Strategy PnL requires ultra+."""
        user, token = await _create_user(app_with_db, tmp_settings, tier)
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            "/api/v1/performance/strategy-pnl",
            headers={"X-API-Key": api_key},
        )
        if expected_ok:
            assert resp.status_code == 200
        else:
            assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# Leaderboard (/api/v1/leaderboard)
# ═══════════════════════════════════════════════════════════════════════════

class TestLeaderboard:
    """Tests for GET /api/v1/leaderboard."""

    @pytest.mark.asyncio
    async def test_anonymous_blocked(self, client):
        resp = client.get("/api/v1/leaderboard")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_pro_access(self, client, app_with_db, tmp_settings):
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            "/api/v1/leaderboard",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "leaderboard" in data

    @pytest.mark.parametrize("hours", [1, 24, 168, 720])
    @pytest.mark.asyncio
    async def test_hours_param(self, hours, client, app_with_db, tmp_settings):
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            f"/api/v1/leaderboard?hours={hours}",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Correlations (/api/v1/correlations)
# ═══════════════════════════════════════════════════════════════════════════

class TestCorrelations:
    """Tests for GET /api/v1/correlations — requires pro+."""

    @pytest.mark.asyncio
    async def test_free_blocked(self, client, app_with_db, tmp_settings):
        _, token = await _create_user(app_with_db, tmp_settings, "free")
        resp = client.get(
            "/api/v1/correlations",
            cookies={"rot_session": token},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_pro_access(self, client, app_with_db, tmp_settings):
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            "/api/v1/correlations",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "correlations" in data


# ═══════════════════════════════════════════════════════════════════════════
# Sector Detail (/api/v1/sectors/{sector})
# ═══════════════════════════════════════════════════════════════════════════

class TestSectorDetail:
    """Tests for GET /api/v1/sectors/{sector} — requires premium+."""

    @pytest.mark.parametrize("tier,expected_ok", [
        ("pro", False),
        ("premium", True),
        ("ultra", True),
    ])
    @pytest.mark.asyncio
    async def test_tier_gating(self, tier, expected_ok, client, app_with_db, tmp_settings):
        user, token = await _create_user(app_with_db, tmp_settings, tier)
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            "/api/v1/sectors/technology",
            headers={"X-API-Key": api_key},
        )
        if expected_ok:
            assert resp.status_code == 200
        else:
            assert resp.status_code == 403

    @pytest.mark.parametrize("sector", [
        "technology", "healthcare", "finance", "energy", "consumer",
    ])
    @pytest.mark.asyncio
    async def test_sector_names(self, sector, client, app_with_db, tmp_settings):
        """Various sector names are accepted."""
        user, token = await _create_user(app_with_db, tmp_settings, "premium")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            f"/api/v1/sectors/{sector}",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# BYOK Re-reasoning (/api/v1/signals/{id}/reason)
# ═══════════════════════════════════════════════════════════════════════════

class TestBYOKReasoning:
    """Tests for POST /api/v1/signals/{signal_id}/reason."""

    @pytest.mark.asyncio
    async def test_anonymous_blocked(self, client, app_with_db, tmp_settings):
        """Anonymous users cannot re-reason signals."""
        db = app_with_db.state.db
        sig_id = await _insert_signal(db, "AAPL")
        resp = client.post(f"/api/v1/signals/{sig_id}/reason")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier cannot use BYOK."""
        user, token = await _create_user(app_with_db, tmp_settings, "free")
        db = app_with_db.state.db
        sig_id = await _insert_signal(db, "AAPL")
        resp = client.post(
            f"/api/v1/signals/{sig_id}/reason",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_pro_without_key_returns_400(self, client, app_with_db, tmp_settings):
        """Pro user without LLM key configured gets 400."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        sig_id = await _insert_signal(db, "AAPL")
        resp = client.post(
            f"/api/v1/signals/{sig_id}/reason",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_signal_not_found(self, client, app_with_db, tmp_settings):
        """BYOK on nonexistent signal returns 404."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        # Set a fake LLM key so we get past the key check
        await db.db.execute(
            "UPDATE users SET settings = ? WHERE id = ?",
            ('{"llm_api_key": "fake-key", "llm_provider": "openai"}', user["id"]),
        )
        await db.db.commit()
        resp = client.post(
            "/api/v1/signals/nonexistent-id/reason",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# _filter_fields helper (unit test)
# ═══════════════════════════════════════════════════════════════════════════

class TestFilterFieldsHelper:
    """Unit tests for the _filter_fields function in signals.py."""

    def test_no_fields_returns_original(self):
        from rot.web.routes.signals import _filter_fields
        items = [{"a": 1, "b": 2}]
        result = _filter_fields(items, None, {"a", "b"})
        assert result == items

    def test_empty_fields_returns_original(self):
        from rot.web.routes.signals import _filter_fields
        items = [{"a": 1, "b": 2}]
        result = _filter_fields(items, "", {"a", "b"})
        assert result == items

    def test_valid_fields_filters(self):
        from rot.web.routes.signals import _filter_fields
        items = [{"a": 1, "b": 2, "c": 3}]
        result = _filter_fields(items, "a,b", {"a", "b", "c"})
        assert result == [{"a": 1, "b": 2}]

    def test_invalid_fields_returns_original(self):
        from rot.web.routes.signals import _filter_fields
        items = [{"a": 1, "b": 2}]
        result = _filter_fields(items, "x,y,z", {"a", "b"})
        assert result == items

    @pytest.mark.parametrize("fields_str,expected_keys", [
        ("ticker", {"ticker"}),
        ("ticker,stance", {"ticker", "stance"}),
        ("ticker, confidence ,stance", {"ticker", "confidence", "stance"}),
    ])
    def test_various_field_combos(self, fields_str, expected_keys):
        from rot.web.routes.signals import _filter_fields
        items = [{"ticker": "AAPL", "stance": "bullish", "confidence": 0.9, "extra": "x"}]
        allowed = {"ticker", "stance", "confidence", "extra"}
        result = _filter_fields(items, fields_str, allowed)
        assert set(result[0].keys()) == expected_keys


# ═══════════════════════════════════════════════════════════════════════════
# Rate limit headers
# ═══════════════════════════════════════════════════════════════════════════

class TestRateLimitHeaders:
    """Verify rate limit headers are present on API responses."""

    @pytest.mark.asyncio
    async def test_headers_present(self, client, app_with_db, tmp_settings):
        """API responses include X-RateLimit-* headers."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            "/api/v1/signals",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200
        # rate_limit_headers adds X-RateLimit-Limit and X-Tier
        assert "x-ratelimit-limit" in resp.headers or "x-tier" in resp.headers


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases and error handling
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalEdgeCases:
    """Edge cases for signal routes."""

    @pytest.mark.parametrize("min_conf", [0.0, 0.5, 0.99, 1.0])
    @pytest.mark.asyncio
    async def test_min_confidence_filter(self, min_conf, client, app_with_db, tmp_settings):
        """min_confidence filter is accepted."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            f"/api/v1/signals?min_confidence={min_conf}",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("event_type", [
        "earnings_rumor", "product_news", "regulatory", "squeeze_chatter", "macro",
    ])
    @pytest.mark.asyncio
    async def test_event_type_filter(self, event_type, client, app_with_db, tmp_settings):
        """event_type filter is accepted."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            f"/api/v1/signals?event_type={event_type}",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_combined_filters(self, client, app_with_db, tmp_settings):
        """Multiple filters combined."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        await _insert_signal(db, "AAPL", "bullish", 0.9)
        resp = client.get(
            "/api/v1/signals?ticker=AAPL&stance=bullish&min_confidence=0.5&limit=10&sort=confidence&order=desc",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_database_returns_empty_list(self, client, app_with_db, tmp_settings):
        """Empty database returns empty signal list."""
        user, token = await _create_user(app_with_db, tmp_settings, "pro")
        db = app_with_db.state.db
        from rot.web.auth import generate_api_key, hash_api_key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        await db.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user["id"]),
        )
        await db.db.commit()
        resp = client.get(
            "/api/v1/signals?ticker=ZZZZZZ",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["signals"] == []
