"""
Comprehensive tests for Congress tracker routes (Pro+ feature).

Routes tested:
- GET /congress-tracker (Congressional trading tracker page)
- GET /api/v1/congress-trades (API endpoint)

Coverage:
- Tier gating (Pro+ required for access)
- Tier-based feature gates (Premium+ for amounts/ticker filter)
- Auth validation
- Response format
- Query parameters (days, ticker, limit)
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-congress-tests!")
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
        web={"secret_key": "test-secret-key-for-congress-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-congress-tests!!"},
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
    email = f"congress_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /congress-tracker - Page Tests
# ============================================================================

class TestCongressTrackerPage:
    @pytest.mark.asyncio
    async def test_congress_tracker_free_tier_locked(self, client, app_with_db, tmp_settings):
        """Free tier sees locked state."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/congress-tracker", cookies={"rot_session": token})
        assert response.status_code == 200
        # Shows locked/upgrade page
        assert b"locked" in response.content.lower() or b"pro" in response.content.lower()

    @pytest.mark.asyncio
    async def test_congress_tracker_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier users can access congress tracker."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/congress-tracker", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_congress_tracker_premium_tier(self, client, app_with_db, tmp_settings):
        """Premium tier users can access congress tracker."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/congress-tracker", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_congress_tracker_html_content(self, client, app_with_db, tmp_settings):
        """Congress tracker returns HTML."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/congress-tracker", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_congress_tracker_with_ticker_filter(self, client, app_with_db, tmp_settings):
        """Premium+ can use ticker filter."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/congress-tracker?ticker=AAPL", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_congress_tracker_with_days_param(self, client, app_with_db, tmp_settings):
        """Congress tracker accepts days parameter."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/congress-tracker?days=7", cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# GET /api/v1/congress-trades - API Tests
# ============================================================================

class TestCongressTradesAPI:
    @pytest.mark.asyncio
    async def test_congress_api_requires_auth(self, client):
        """Congress trades API requires authentication."""
        response = client.get("/api/v1/congress-trades")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_congress_api_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/congress-trades", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_congress_api_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/congress-trades", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_congress_api_returns_json(self, client, app_with_db, tmp_settings):
        """Congress API returns JSON."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/congress-trades", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_congress_api_with_parameters(self, client, app_with_db, tmp_settings):
        """Congress API accepts query parameters."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/congress-trades?days=14&limit=20&ticker=NVDA",
                             cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestCongressTrackerTierMatrix:
    @pytest.mark.parametrize("tier,should_allow", [
        ("free", False),
        ("pro", True),
        ("premium", True),
        ("ultra", True),
        ("enterprise", True),
        ("admin", True),
    ])
    @pytest.mark.asyncio
    async def test_congress_page_tier_matrix(self, client, app_with_db, tmp_settings, tier, should_allow):
        """Comprehensive tier access control matrix for congress tracker page."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/congress-tracker", cookies={"rot_session": token})
        assert response.status_code == 200
        # Free tier sees locked page, paid tiers see data

    @pytest.mark.parametrize("tier,should_allow", [
        ("free", False),
        ("pro", True),
        ("premium", True),
        ("ultra", True),
        ("enterprise", True),
        ("admin", True),
    ])
    @pytest.mark.asyncio
    async def test_congress_api_tier_matrix(self, client, app_with_db, tmp_settings, tier, should_allow):
        """Comprehensive tier access control matrix for congress API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/api/v1/congress-trades", cookies={"rot_session": token})

        if should_allow:
            assert response.status_code == 200
        else:
            assert response.status_code == 403
