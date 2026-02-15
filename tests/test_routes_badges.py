"""
Comprehensive tests for badge system routes.

Routes tested:
- GET /badges (badge showcase page)
- GET /api/v1/badges/progress
- GET /api/v1/badges/leaderboard
- GET /api/v1/badges/check

Coverage:
- Public vs authenticated access
- Badge progress tracking
- Leaderboard functionality
- Auth validation
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-badges-tests!")
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
        web={"secret_key": "test-secret-key-for-badges-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-badges-tests!!"},
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
    email = f"badge_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /badges - Badge Showcase Page Tests
# ============================================================================

class TestBadgesPage:
    @pytest.mark.asyncio
    async def test_badges_page_unauthenticated(self, client):
        """Unauthenticated users can view badges page (shows locked badges)."""
        response = client.get("/badges")
        assert response.status_code == 200
        assert b"badge" in response.content.lower()

    @pytest.mark.asyncio
    async def test_badges_page_authenticated(self, client, app_with_db, tmp_settings):
        """Authenticated users can view badges page with progress."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/badges", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_badges_page_html_content(self, client):
        """Badges page returns HTML."""
        response = client.get("/badges")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.parametrize("tier", ["free", "pro", "premium", "ultra", "enterprise", "admin"])
    @pytest.mark.asyncio
    async def test_badges_page_all_tiers(self, client, app_with_db, tmp_settings, tier):
        """All tiers can view badges page."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/badges", cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# GET /api/v1/badges/progress - Badge Progress Tests
# ============================================================================

class TestBadgeProgress:
    @pytest.mark.asyncio
    async def test_badge_progress_requires_auth(self, client):
        """Badge progress requires authentication."""
        response = client.get("/api/v1/badges/progress")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_badge_progress_success(self, client, app_with_db, tmp_settings):
        """Authenticated user can get badge progress."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/badges/progress", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_badge_progress_returns_array(self, client, app_with_db, tmp_settings):
        """Badge progress returns array of badge progress objects."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/badges/progress", cookies={"rot_session": token})
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


# ============================================================================
# GET /api/v1/badges/leaderboard - Leaderboard Tests
# ============================================================================

class TestBadgeLeaderboard:
    @pytest.mark.asyncio
    async def test_leaderboard_public_access(self, client):
        """Leaderboard is publicly accessible."""
        response = client.get("/api/v1/badges/leaderboard")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_leaderboard_returns_json(self, client):
        """Leaderboard returns JSON."""
        response = client.get("/api/v1/badges/leaderboard")
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_leaderboard_with_limit(self, client):
        """Leaderboard accepts limit parameter."""
        response = client.get("/api/v1/badges/leaderboard?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_leaderboard_with_sort_by(self, client):
        """Leaderboard accepts sort_by parameter."""
        response = client.get("/api/v1/badges/leaderboard?sort_by=points")
        assert response.status_code == 200


# ============================================================================
# GET /api/v1/badges/check - Badge Check Tests
# ============================================================================

class TestBadgeCheck:
    @pytest.mark.asyncio
    async def test_badge_check_requires_auth(self, client):
        """Badge check requires authentication."""
        response = client.get("/api/v1/badges/check")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_badge_check_success(self, client, app_with_db, tmp_settings):
        """Authenticated user can check badges."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/badges/check", cookies={"rot_session": token})
        assert response.status_code == 200
        data = response.json()
        assert "ok" in data
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_badge_check_returns_earned_dict(self, client, app_with_db, tmp_settings):
        """Badge check returns earned badge dict."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/badges/check", cookies={"rot_session": token})
        assert response.status_code == 200
        data = response.json()
        assert "earned" in data
        assert isinstance(data["earned"], dict)

    @pytest.mark.asyncio
    async def test_badge_check_returns_stats(self, client, app_with_db, tmp_settings):
        """Badge check returns streak and points stats."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="ultra")
        response = client.get("/api/v1/badges/check", cookies={"rot_session": token})
        assert response.status_code == 200
        data = response.json()
        assert "streak_count" in data
        assert "streak_best" in data
        assert "total_points" in data
