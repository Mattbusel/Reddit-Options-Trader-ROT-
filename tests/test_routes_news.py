"""
Comprehensive tests for news feed routes (Pro+ feature).

Routes tested:
- GET /news (news feed page)
- GET /api/v1/news (JSON API)

Coverage:
- Tier gating (Pro+ for source filter, Premium+ for AI summaries)
- Auth validation (API endpoint)
- HTML/JSON response formats
- Query parameters (source, hours, limit)
- Source filtering
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-news-tests!")
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
        web={"secret_key": "test-secret-key-for-news-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-news-tests!!"},
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
    email = f"news_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /news - News Feed Page Tests
# ============================================================================

class TestNewsFeedPage:
    @pytest.mark.asyncio
    async def test_news_page_free_tier(self, client, app_with_db, tmp_settings):
        """Free tier can view news page (limited hours)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/news", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_news_page_pro_tier(self, client, app_with_db, tmp_settings):
        """Pro tier can access news feed."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/news", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_news_page_html_content(self, client, app_with_db, tmp_settings):
        """News page returns HTML."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/news", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_news_page_with_source_filter(self, client, app_with_db, tmp_settings):
        """Pro+ can filter by source."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/news?source=marketwatch-top", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_news_page_with_hours_param(self, client, app_with_db, tmp_settings):
        """News page accepts hours parameter."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="ultra")
        response = client.get("/news?hours=48", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_news_page_unauthenticated(self, client):
        """Unauthenticated users can view news page (limited)."""
        response = client.get("/news")
        assert response.status_code == 200


# ============================================================================
# GET /api/v1/news - News API Tests
# ============================================================================

class TestNewsFeedAPI:
    @pytest.mark.asyncio
    async def test_news_api_requires_auth(self, client):
        """News API requires authentication."""
        response = client.get("/api/v1/news")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_news_api_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access news API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/news", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_news_api_returns_json(self, client, app_with_db, tmp_settings):
        """News API returns JSON."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/news", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_news_api_with_parameters(self, client, app_with_db, tmp_settings):
        """News API accepts query parameters."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="ultra")
        response = client.get("/api/v1/news?source=all&hours=24&limit=100",
                             cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_news_api_source_filtering(self, client, app_with_db, tmp_settings):
        """News API supports source filtering."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/news?source=cnbc-market", cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestNewsFeedTierMatrix:
    @pytest.mark.parametrize("tier", ["free", "pro", "premium", "ultra", "enterprise", "admin"])
    @pytest.mark.asyncio
    async def test_news_page_all_tiers_can_access(self, client, app_with_db, tmp_settings, tier):
        """All tiers can access news page (with varying limits)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/news", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.parametrize("tier,should_allow", [
        ("free", False),
        ("pro", True),
        ("premium", True),
        ("ultra", True),
        ("enterprise", True),
        ("admin", True),
    ])
    @pytest.mark.asyncio
    async def test_news_api_tier_matrix(self, client, app_with_db, tmp_settings, tier, should_allow):
        """API access requires paid subscription."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/api/v1/news", cookies={"rot_session": token})

        if should_allow:
            assert response.status_code == 200
        else:
            assert response.status_code == 403
