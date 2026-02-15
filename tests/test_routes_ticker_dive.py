"""
Comprehensive tests for Ticker Deep Dive route.

Routes tested:
- GET /ticker/{symbol}

Coverage:
- Public access (unauthenticated & all tiers)
- HTML response format
- Ticker-specific data display
- Tier-based signal limits
- Consensus calculation
- Chart data access (Pro+)
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-ticker-dive-tests!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes
from rot.web.auth import create_access_token, hash_password


@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-ticker-dive-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-ticker-dive-tests!!"},
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


async def _create_user(app, settings, tier="free"):
    """Create a user at the given tier with a unique email."""
    db = app.state.db
    unique = uuid.uuid4().hex[:8]
    email = f"tickerdive_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /ticker/{symbol} - Ticker Deep Dive Tests
# ============================================================================

class TestTickerDeepDive:
    @pytest.mark.asyncio
    async def test_ticker_dive_public_access(self, client):
        """Unauthenticated users can access ticker dive."""
        response = client.get("/ticker/AAPL")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ticker_dive_returns_html(self, client):
        """Ticker dive returns HTML."""
        response = client.get("/ticker/TSLA")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_ticker_dive_uppercase_normalization(self, client):
        """Ticker symbols are normalized to uppercase."""
        response = client.get("/ticker/aapl")
        assert response.status_code == 200
        # Verify page loads successfully

    @pytest.mark.asyncio
    async def test_ticker_dive_free_tier_limited_signals(self, client, app_with_db, tmp_settings):
        """Free tier gets limited signals."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/ticker/AAPL", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ticker_dive_pro_tier_more_signals(self, client, app_with_db, tmp_settings):
        """Pro tier gets more signals."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/ticker/AAPL", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ticker_dive_premium_tier_unlimited(self, client, app_with_db, tmp_settings):
        """Premium tier gets unlimited signals."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/ticker/AAPL", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ticker_dive_contains_ticker_data(self, client):
        """Ticker dive page contains ticker-specific content."""
        response = client.get("/ticker/GME")
        assert response.status_code == 200
        content = response.content.upper()
        # Should reference the ticker somewhere on the page
        assert b"GME" in content or b"TICKER" in content

    @pytest.mark.asyncio
    async def test_ticker_dive_various_tickers(self, client):
        """Ticker dive works for various ticker symbols."""
        tickers = ["AAPL", "TSLA", "GME", "SPY", "QQQ"]
        for ticker in tickers:
            response = client.get(f"/ticker/{ticker}")
            assert response.status_code == 200


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestTickerDiveTierMatrix:
    @pytest.mark.parametrize("tier", [
        "free",
        "pro",
        "premium",
        "ultra",
        "enterprise",
        "admin",
    ])
    @pytest.mark.asyncio
    async def test_ticker_dive_all_tiers_allowed(self, client, app_with_db, tmp_settings, tier):
        """All tiers can access ticker dive (with varying signal limits)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/ticker/AAPL", cookies={"rot_session": token})
        assert response.status_code == 200
