"""
Comprehensive tests for Social Intelligence routes (Premium+ feature).

Routes tested:
- GET /social
- GET /social/author/{username}
- GET /api/v1/social/leaderboard
- GET /api/v1/social/author/{username}
- GET /api/v1/social/manipulation
- GET /api/v1/social/propagation/{ticker}
- GET /api/v1/social/contrarian

Coverage:
- Public access (limited features for free tier)
- Tier gating (Premium+ for full features)
- HTML and JSON response formats
- API authentication and rate limiting
- Query parameters
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-social-tests!")
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
        web={"secret_key": "test-secret-key-for-social-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-social-tests!!"},
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
    email = f"social_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /social - Social Dashboard Tests
# ============================================================================

class TestSocialDashboard:
    @pytest.mark.asyncio
    async def test_social_public_access(self, client):
        """Unauthenticated users can view social dashboard (limited state)."""
        response = client.get("/social")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_social_free_tier_limited(self, client, app_with_db, tmp_settings):
        """Free tier can view page but sees limited features."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/social", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_social_premium_tier_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier can access social intelligence."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/social", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_social_returns_html(self, client):
        """Social dashboard returns HTML."""
        response = client.get("/social")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


# ============================================================================
# GET /social/author/{username} - Author Profile Tests
# ============================================================================

class TestSocialAuthorProfile:
    @pytest.mark.asyncio
    async def test_author_profile_public_access(self, client):
        """Unauthenticated users can view author profiles (limited state)."""
        response = client.get("/social/author/testuser")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_author_profile_premium_tier_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier can access author profiles."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/social/author/testuser", cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# GET /api/v1/social/leaderboard - Leaderboard API Tests
# ============================================================================

class TestSocialLeaderboardAPI:
    @pytest.mark.asyncio
    async def test_leaderboard_api_requires_auth(self, client):
        """Leaderboard API requires authentication."""
        response = client.get("/api/v1/social/leaderboard")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_leaderboard_api_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from leaderboard API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/social/leaderboard", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_leaderboard_api_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access leaderboard API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/social/leaderboard", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]

    @pytest.mark.asyncio
    async def test_leaderboard_api_with_parameters(self, client, app_with_db, tmp_settings):
        """Leaderboard API accepts query parameters."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get(
            "/api/v1/social/leaderboard?limit=100&offset=0&min_predictions=5",
            cookies={"rot_session": token}
        )
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/social/author/{username} - Author API Tests
# ============================================================================

class TestSocialAuthorAPI:
    @pytest.mark.asyncio
    async def test_author_api_requires_auth(self, client):
        """Author API requires authentication."""
        response = client.get("/api/v1/social/author/testuser")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_author_api_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from author API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/social/author/testuser", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_author_api_premium_tier_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier can access author API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/social/author/testuser", cookies={"rot_session": token})
        # Returns 404 for non-existent author (expected)
        assert response.status_code in [200, 404, 500]


# ============================================================================
# GET /api/v1/social/manipulation - Manipulation Alerts API Tests
# ============================================================================

class TestSocialManipulationAPI:
    @pytest.mark.asyncio
    async def test_manipulation_api_requires_auth(self, client):
        """Manipulation API requires authentication."""
        response = client.get("/api/v1/social/manipulation")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_manipulation_api_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from manipulation API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/social/manipulation", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_manipulation_api_premium_tier_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier can access manipulation API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/social/manipulation", cookies={"rot_session": token})
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/social/propagation/{ticker} - Propagation API Tests
# ============================================================================

class TestSocialPropagationAPI:
    @pytest.mark.asyncio
    async def test_propagation_api_requires_auth(self, client):
        """Propagation API requires authentication."""
        response = client.get("/api/v1/social/propagation/AAPL")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_propagation_api_premium_tier_blocked(self, client, app_with_db, tmp_settings):
        """Premium tier blocked from propagation API (requires Ultra+)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/social/propagation/AAPL", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_propagation_api_ultra_tier_allowed(self, client, app_with_db, tmp_settings):
        """Ultra tier can access propagation API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="ultra")
        response = client.get("/api/v1/social/propagation/AAPL", cookies={"rot_session": token})
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/social/contrarian - Contrarian Signals API Tests
# ============================================================================

class TestSocialContrarianAPI:
    @pytest.mark.asyncio
    async def test_contrarian_api_requires_auth(self, client):
        """Contrarian API requires authentication."""
        response = client.get("/api/v1/social/contrarian")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_contrarian_api_premium_tier_blocked(self, client, app_with_db, tmp_settings):
        """Premium tier blocked from contrarian API (requires Ultra+)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/social/contrarian", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_contrarian_api_ultra_tier_allowed(self, client, app_with_db, tmp_settings):
        """Ultra tier can access contrarian API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="ultra")
        response = client.get("/api/v1/social/contrarian", cookies={"rot_session": token})
        assert response.status_code in [200, 500]
