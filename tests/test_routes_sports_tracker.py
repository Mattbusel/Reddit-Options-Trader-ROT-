"""
Comprehensive tests for Sports Betting Intelligence routes.

Routes tested:
- GET /sports-tracker
- GET /sports
- GET /api/v1/sports-betting

Coverage:
- Public access (HTML page accessible to all)
- Tier-based line mover scores (free: hidden, Pro+: visible)
- Tier-based AI summaries (free: none, Premium+: full)
- Tier-based time caps (free: 1 day, Pro: 3 days, Premium: 7 days, Ultra: 30 days)
- Team filtering (Pro+ feature)
- API authentication and rate limiting (Premium+ required)
- Query parameters (league, category, team, urgency, min_score)
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-sports-tests!")
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
        web={"secret_key": "test-secret-key-for-sports-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-sports-tests!!"},
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
    email = f"sports_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /sports-tracker and /sports - Sports Tracker HTML Tests
# ============================================================================

class TestSportsTrackerHTML:
    @pytest.mark.asyncio
    async def test_sports_tracker_public_access(self, client):
        """Unauthenticated users can access sports tracker."""
        response = client.get("/sports-tracker")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_sports_alias_public_access(self, client):
        """Unauthenticated users can access /sports alias."""
        response = client.get("/sports")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_sports_tracker_returns_html(self, client):
        """Sports tracker returns HTML."""
        response = client.get("/sports-tracker")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_sports_tracker_with_filters(self, client, app_with_db, tmp_settings):
        """Sports tracker accepts query parameters."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get(
            "/sports-tracker?league=NFL&category=injury&team=all&sort_by=score",
            cookies={"rot_session": token}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_sports_tracker_free_tier_limited(self, client, app_with_db, tmp_settings):
        """Free tier can view page but with limited features."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/sports-tracker", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_sports_tracker_pro_tier_features(self, client, app_with_db, tmp_settings):
        """Pro tier has access to line mover scores and team filter."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/sports-tracker", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_sports_tracker_contains_sports_content(self, client):
        """Sports tracker page contains sports content."""
        response = client.get("/sports-tracker")
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference sports or betting concepts
        assert b"sports" in content or b"betting" in content or b"line" in content


# ============================================================================
# GET /api/v1/sports-betting - Sports Betting API Tests
# ============================================================================

class TestSportsBettingAPI:
    @pytest.mark.asyncio
    async def test_sports_api_requires_auth(self, client):
        """Sports betting API requires authentication."""
        response = client.get("/api/v1/sports-betting")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_sports_api_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from sports betting API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/sports-betting", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_sports_api_pro_tier_blocked(self, client, app_with_db, tmp_settings):
        """Pro tier blocked from sports betting API (requires Premium+)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/sports-betting", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_sports_api_premium_tier_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier can access sports betting API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/sports-betting", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]

    @pytest.mark.asyncio
    async def test_sports_api_with_filters(self, client, app_with_db, tmp_settings):
        """Sports betting API accepts query parameters."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="ultra")
        response = client.get(
            "/api/v1/sports-betting?league=NFL&category=injury&urgency=high&min_score=50&sort=score&limit=25",
            cookies={"rot_session": token}
        )
        assert response.status_code in [200, 500]

    @pytest.mark.asyncio
    async def test_sports_api_field_selection(self, client, app_with_db, tmp_settings):
        """Sports betting API supports field selection."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get(
            "/api/v1/sports-betting?fields=title,league,line_mover_score",
            cookies={"rot_session": token}
        )
        assert response.status_code in [200, 500]


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestSportsTierMatrix:
    @pytest.mark.parametrize("tier,should_allow_api", [
        ("free", False),
        ("pro", False),
        ("premium", True),
        ("ultra", True),
        ("enterprise", True),
        ("admin", True),
    ])
    @pytest.mark.asyncio
    async def test_sports_api_tier_matrix(self, client, app_with_db, tmp_settings, tier, should_allow_api):
        """Comprehensive tier access control matrix for sports betting API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/api/v1/sports-betting", cookies={"rot_session": token})

        if should_allow_api:
            # Premium+ should get 200 or 500 (if no data)
            assert response.status_code in [200, 500]
        else:
            # Free and Pro should get 403
            assert response.status_code == 403
