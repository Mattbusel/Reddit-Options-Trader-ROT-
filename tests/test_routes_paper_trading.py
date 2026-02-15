"""Paper trading route tests.

Tests for the paper trading API — execute trades, close positions,
portfolio retrieval, and edge cases.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-paper-trading-routes!!")
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
        web={"secret_key": "test-secret-key-for-paper-trading-routes!!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-paper-trading-routes-test!"},
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
    """Create a user at a given tier with a unique email."""
    db = app.state.db
    unique = uuid.uuid4().hex[:8]
    email = f"paper_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ---------------------------------------------------------------------------
# Paper trading HTML page
# ---------------------------------------------------------------------------

class TestPaperTradingPage:
    @pytest.mark.asyncio
    async def test_page_loads_unauthenticated(self, client):
        """Paper trading page accessible without login."""
        resp = client.get("/paper-trading")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_page_loads_authenticated(self, client, app_with_db, tmp_settings):
        """Paper trading page accessible with login."""
        user, token = await _create_user(app_with_db, tmp_settings)
        resp = client.get("/paper-trading", cookies={"rot_session": token})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Paper trading API — auth required
# ---------------------------------------------------------------------------

class TestPaperTradingAuth:
    def test_execute_trade_requires_auth(self, client):
        """POST /api/v1/paper-trading/trade requires authentication."""
        resp = client.post("/api/v1/paper-trading/trade", json={
            "signal_id": "fake-id",
            "dollars": 500.0,
        })
        assert resp.status_code in (401, 403)

    def test_close_trade_requires_auth(self, client):
        """POST /api/v1/paper-trading/close/{id} requires authentication."""
        resp = client.post("/api/v1/paper-trading/close/fake-trade-id", json={})
        assert resp.status_code in (401, 403)

    def test_portfolio_requires_auth(self, client):
        """GET /api/v1/paper-trading/portfolio requires authentication."""
        resp = client.get("/api/v1/paper-trading/portfolio")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Paper trading API — trade execution
# ---------------------------------------------------------------------------

class TestPaperTradeExecution:
    @pytest.mark.asyncio
    async def test_execute_trade_signal_not_found(self, client, app_with_db, tmp_settings):
        """Execute trade with nonexistent signal returns 404."""
        user, token = await _create_user(app_with_db, tmp_settings)
        resp = client.post(
            "/api/v1/paper-trading/trade",
            json={"signal_id": "nonexistent-signal", "dollars": 500.0},
            cookies={"rot_session": token},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_close_trade_not_found(self, client, app_with_db, tmp_settings):
        """Close trade with nonexistent trade ID returns 404."""
        user, token = await _create_user(app_with_db, tmp_settings)
        resp = client.post(
            "/api/v1/paper-trading/close/nonexistent-trade",
            json={},
            cookies={"rot_session": token},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Paper trading API — portfolio
# ---------------------------------------------------------------------------

class TestPaperPortfolio:
    @pytest.mark.asyncio
    async def test_portfolio_initializes_on_first_access(self, client, app_with_db, tmp_settings):
        """Portfolio endpoint creates portfolio on first access."""
        user, token = await _create_user(app_with_db, tmp_settings)
        resp = client.get(
            "/api/v1/paper-trading/portfolio",
            cookies={"rot_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "portfolio" in data
        assert "open_positions" in data

    @pytest.mark.asyncio
    async def test_portfolio_returns_consistent_data(self, client, app_with_db, tmp_settings):
        """Calling portfolio twice returns same portfolio."""
        user, token = await _create_user(app_with_db, tmp_settings)
        r1 = client.get("/api/v1/paper-trading/portfolio", cookies={"rot_session": token})
        r2 = client.get("/api/v1/paper-trading/portfolio", cookies={"rot_session": token})
        assert r1.json()["portfolio"]["balance"] == r2.json()["portfolio"]["balance"]
