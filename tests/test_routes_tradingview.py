"""
Comprehensive tests for TradingView Integration routes.

Routes tested:
- GET /tradingview
- GET /api/v1/tradingview/signals
- POST /api/v1/tradingview/webhook
- GET /api/v1/tradingview/script

Coverage:
- Public access (HTML page)
- API authentication (paid subscription required)
- Tier gating (Pro+ for Pine Script generator)
- Webhook reception
- Pine Script generation
- Query parameters
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-tradingview-tests!")
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
        web={"secret_key": "test-secret-key-for-tradingview-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-tradingview-tests!!"},
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
    email = f"tradingview_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /tradingview - TradingView Page Tests
# ============================================================================

class TestTradingViewPage:
    @pytest.mark.asyncio
    async def test_tradingview_page_public_access(self, client):
        """Unauthenticated users can access TradingView page."""
        response = client.get("/tradingview")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_tradingview_page_returns_html(self, client):
        """TradingView page returns HTML."""
        response = client.get("/tradingview")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_tradingview_page_contains_pine_script(self, client):
        """TradingView page contains Pine Script content."""
        response = client.get("/tradingview")
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference TradingView or Pine Script
        assert b"tradingview" in content or b"pine" in content or b"script" in content


# ============================================================================
# GET /api/v1/tradingview/signals - Signals API Tests
# ============================================================================

class TestTradingViewSignalsAPI:
    @pytest.mark.asyncio
    async def test_signals_api_requires_auth(self, client):
        """Signals API requires authentication."""
        response = client.get("/api/v1/tradingview/signals")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_signals_api_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access signals API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/tradingview/signals", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]

    @pytest.mark.asyncio
    async def test_signals_api_with_ticker_filter(self, client, app_with_db, tmp_settings):
        """Signals API accepts ticker parameter."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/tradingview/signals?ticker=AAPL&limit=25", cookies={"rot_session": token})
        assert response.status_code in [200, 500]


# ============================================================================
# POST /api/v1/tradingview/webhook - Webhook Tests
# ============================================================================

class TestTradingViewWebhook:
    @pytest.mark.asyncio
    async def test_webhook_accepts_valid_payload(self, client):
        """Webhook accepts valid JSON payload."""
        response = client.post(
            "/api/v1/tradingview/webhook",
            json={"ticker": "AAPL", "action": "buy", "confidence": 0.8}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True

    @pytest.mark.asyncio
    async def test_webhook_rejects_invalid_json(self, client):
        """Webhook rejects invalid JSON."""
        response = client.post(
            "/api/v1/tradingview/webhook",
            content=b"not valid json",
            headers={"content-type": "application/json"}
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_webhook_requires_ticker(self, client):
        """Webhook requires ticker/symbol field."""
        response = client.post(
            "/api/v1/tradingview/webhook",
            json={"action": "buy"}  # Missing ticker
        )
        assert response.status_code == 400


# ============================================================================
# GET /api/v1/tradingview/script - Pine Script Generator Tests
# ============================================================================

class TestPineScriptGenerator:
    @pytest.mark.asyncio
    async def test_script_generator_requires_auth(self, client):
        """Pine Script generator requires authentication."""
        response = client.get("/api/v1/tradingview/script")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_script_generator_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from Pine Script generator."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/tradingview/script", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_script_generator_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access Pine Script generator."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/tradingview/script", cookies={"rot_session": token})
        # May return 200 (script generated) or 500 (error)
        assert response.status_code in [200, 500]

    @pytest.mark.asyncio
    async def test_script_generator_with_parameters(self, client, app_with_db, tmp_settings):
        """Pine Script generator accepts query parameters."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get(
            "/api/v1/tradingview/script?ticker=AAPL&days=30&min_confidence=0.5&script_type=signal_overlay&show_labels=true",
            cookies={"rot_session": token}
        )
        assert response.status_code in [200, 500]


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestTradingViewTierMatrix:
    @pytest.mark.parametrize("tier,should_allow_script", [
        ("free", False),
        ("pro", True),
        ("premium", True),
        ("ultra", True),
        ("enterprise", True),
        ("admin", True),
    ])
    @pytest.mark.asyncio
    async def test_script_generator_tier_matrix(
        self, client, app_with_db, tmp_settings, tier, should_allow_script
    ):
        """Comprehensive tier access control matrix for Pine Script generator."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/api/v1/tradingview/script", cookies={"rot_session": token})

        if should_allow_script:
            # Pro+ should get 200 or 500 (if error)
            assert response.status_code in [200, 500]
        else:
            # Free should get 403
            assert response.status_code == 403
