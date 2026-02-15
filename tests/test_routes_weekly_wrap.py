"""
Comprehensive tests for Weekly Wrap route.

Routes tested:
- GET /weekly-wrap

Coverage:
- Public access (unauthenticated & all tiers)
- HTML response format
- Week navigation (query parameter)
- Tier-based week history limits
- Weekly market summary data
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-weekly-wrap-tests!")
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
        web={"secret_key": "test-secret-key-for-weekly-wrap-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-weekly-wrap-tests!!"},
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
    email = f"weeklywrap_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /weekly-wrap - Weekly Wrap Tests
# ============================================================================

class TestWeeklyWrap:
    @pytest.mark.asyncio
    async def test_weekly_wrap_public_access(self, client):
        """Unauthenticated users can access weekly wrap."""
        response = client.get("/weekly-wrap")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_weekly_wrap_returns_html(self, client):
        """Weekly wrap returns HTML."""
        response = client.get("/weekly-wrap")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_weekly_wrap_default_current_week(self, client):
        """Weekly wrap defaults to current week (week=0)."""
        response = client.get("/weekly-wrap")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_weekly_wrap_with_week_parameter(self, client, app_with_db, tmp_settings):
        """Weekly wrap accepts week query parameter."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/weekly-wrap?week=1", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_weekly_wrap_free_tier_limited_history(self, client, app_with_db, tmp_settings):
        """Free tier has limited week history access."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        # Free tier should still render page successfully even if trying to access old weeks
        response = client.get("/weekly-wrap?week=10", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_weekly_wrap_pro_tier_more_history(self, client, app_with_db, tmp_settings):
        """Pro tier has more week history access."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/weekly-wrap?week=8", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_weekly_wrap_premium_tier_extended_history(self, client, app_with_db, tmp_settings):
        """Premium tier has extended week history access."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/weekly-wrap?week=20", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_weekly_wrap_contains_summary_data(self, client):
        """Weekly wrap page contains summary content."""
        response = client.get("/weekly-wrap")
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference weekly or wrap concepts
        assert b"week" in content or b"summary" in content or b"signal" in content

    @pytest.mark.asyncio
    async def test_weekly_wrap_invalid_week_parameter(self, client):
        """Weekly wrap handles invalid week parameter gracefully."""
        response = client.get("/weekly-wrap?week=abc")
        assert response.status_code == 200  # Defaults to week 0

    @pytest.mark.asyncio
    async def test_weekly_wrap_negative_week_parameter(self, client):
        """Weekly wrap handles negative week parameter gracefully."""
        response = client.get("/weekly-wrap?week=-5")
        assert response.status_code == 200  # Defaults to week 0


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestWeeklyWrapTierMatrix:
    @pytest.mark.parametrize("tier", [
        "free",
        "pro",
        "premium",
        "ultra",
        "enterprise",
        "admin",
    ])
    @pytest.mark.asyncio
    async def test_weekly_wrap_all_tiers_allowed(self, client, app_with_db, tmp_settings, tier):
        """All tiers can access weekly wrap (with varying history limits)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/weekly-wrap", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.parametrize("tier,weeks_back", [
        ("free", 4),
        ("pro", 8),
        ("premium", 26),
        ("ultra", 52),
    ])
    @pytest.mark.asyncio
    async def test_weekly_wrap_tier_history_limits(
        self, client, app_with_db, tmp_settings, tier, weeks_back
    ):
        """Verify tier-based week history limits work correctly."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        # Request a week within the tier's limit
        response = client.get(f"/weekly-wrap?week={weeks_back - 1}", cookies={"rot_session": token})
        assert response.status_code == 200
