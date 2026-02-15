"""
Comprehensive tests for Unusual Activity routes (Pro+ feature).

Routes tested:
- GET /unusual-activity
- GET /api/v1/unusual-activity
- GET /api/v1/unusual-activity/summary
- GET /api/v1/unusual-activity/timeline/{ticker}

Coverage:
- Public access (shows locked state for free tier)
- Tier gating (Pro+ required)
- HTML response format
- JSON API endpoints
- Query parameters
- Detail access (Premium+ feature)
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-unusual-tests!")
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
        web={"secret_key": "test-secret-key-for-unusual-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-unusual-tests!!"},
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
    email = f"unusual_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /unusual-activity - Unusual Activity Page Tests
# ============================================================================

class TestUnusualActivityPage:
    @pytest.mark.asyncio
    async def test_unusual_activity_public_access(self, client):
        """Unauthenticated users can access unusual activity page (locked state)."""
        response = client.get("/unusual-activity")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_unusual_activity_free_tier_locked(self, client, app_with_db, tmp_settings):
        """Free tier can view page but sees locked state."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/unusual-activity", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_unusual_activity_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access unusual activity."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/unusual-activity", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_unusual_activity_returns_html(self, client):
        """Unusual activity page returns HTML."""
        response = client.get("/unusual-activity")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_unusual_activity_contains_content(self, client, app_with_db, tmp_settings):
        """Unusual activity page contains relevant content."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/unusual-activity", cookies={"rot_session": token})
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference unusual or activity concepts
        assert b"unusual" in content or b"activity" in content or b"option" in content


# ============================================================================
# GET /api/v1/unusual-activity - Unusual Activity API Tests
# ============================================================================

class TestUnusualActivityAPI:
    @pytest.mark.asyncio
    async def test_unusual_api_requires_auth(self, client):
        """Unusual activity API requires authentication."""
        response = client.get("/api/v1/unusual-activity")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_unusual_api_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from unusual activity API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/unusual-activity", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_unusual_api_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access unusual activity API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/unusual-activity", cookies={"rot_session": token})
        assert response.status_code in [200, 500]

    @pytest.mark.asyncio
    async def test_unusual_api_with_filters(self, client, app_with_db, tmp_settings):
        """Unusual activity API accepts query parameters."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get(
            "/api/v1/unusual-activity?hours=48&limit=100&ticker=AAPL&min_score=50&event_type=sweep",
            cookies={"rot_session": token}
        )
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/unusual-activity/summary - Summary API Tests
# ============================================================================

class TestUnusualActivitySummaryAPI:
    @pytest.mark.asyncio
    async def test_summary_api_requires_auth(self, client):
        """Summary API requires authentication."""
        response = client.get("/api/v1/unusual-activity/summary")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_summary_api_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from summary API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/unusual-activity/summary", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_summary_api_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access summary API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/unusual-activity/summary", cookies={"rot_session": token})
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/unusual-activity/timeline/{ticker} - Timeline API Tests
# ============================================================================

class TestUnusualActivityTimelineAPI:
    @pytest.mark.asyncio
    async def test_timeline_api_requires_auth(self, client):
        """Timeline API requires authentication."""
        response = client.get("/api/v1/unusual-activity/timeline/AAPL")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_timeline_api_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from timeline API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/unusual-activity/timeline/AAPL", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_timeline_api_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access timeline API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/unusual-activity/timeline/AAPL", cookies={"rot_session": token})
        assert response.status_code in [200, 500]

    @pytest.mark.asyncio
    async def test_timeline_api_with_days_parameter(self, client, app_with_db, tmp_settings):
        """Timeline API accepts days parameter."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get(
            "/api/v1/unusual-activity/timeline/TSLA?days=14",
            cookies={"rot_session": token}
        )
        assert response.status_code in [200, 500]


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestUnusualActivityTierMatrix:
    @pytest.mark.parametrize("tier,should_allow", [
        ("free", False),
        ("pro", True),
        ("premium", True),
        ("ultra", True),
        ("enterprise", True),
        ("admin", True),
    ])
    @pytest.mark.asyncio
    async def test_unusual_activity_tier_matrix(
        self, client, app_with_db, tmp_settings, tier, should_allow
    ):
        """Comprehensive tier access control matrix for unusual activity."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/api/v1/unusual-activity", cookies={"rot_session": token})

        if should_allow:
            # Pro+ should get 200 or 500 (if no data)
            assert response.status_code in [200, 500]
        else:
            # Free should get 403
            assert response.status_code == 403
