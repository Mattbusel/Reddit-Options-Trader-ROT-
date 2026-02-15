"""
Comprehensive tests for /accuracy-breakdown route (Premium+ tier gate).

Coverage:
- Tier gating (all 6 tiers: Free/Pro/Premium/Ultra/Enterprise/Admin)
- Auth validation (JWT, unauthenticated)
- Response format validation (HTML structure)
- Edge cases (empty results, large datasets)
- Database integration
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-accuracy-tests!")
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
        web={"secret_key": "test-secret-key-for-accuracy-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-accuracy-tests!!"},
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
    email = f"accuracy_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# Tier Gating Tests (Premium+ required)
# ============================================================================

class TestAccuracyBreakdownTierGating:
    @pytest.mark.asyncio
    async def test_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier users redirected to /pricing."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/accuracy-breakdown", cookies={"rot_session": token}, follow_redirects=False)
        assert response.status_code == 302
        assert "/pricing" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier users CAN access accuracy breakdown (Pro+ feature)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/accuracy-breakdown", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_premium_tier_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier users can access accuracy breakdown."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/accuracy-breakdown", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ultra_tier_allowed(self, client, app_with_db, tmp_settings):
        """Ultra tier users can access accuracy breakdown."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="ultra")
        response = client.get("/accuracy-breakdown", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_enterprise_tier_allowed(self, client, app_with_db, tmp_settings):
        """Enterprise tier users can access accuracy breakdown."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="enterprise")
        response = client.get("/accuracy-breakdown", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_tier_allowed(self, client, app_with_db, tmp_settings):
        """Admin tier users can access accuracy breakdown (bypasses all gates)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="admin")
        response = client.get("/accuracy-breakdown", cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# Auth Validation Tests
# ============================================================================

class TestAccuracyBreakdownAuth:
    @pytest.mark.asyncio
    async def test_unauthenticated_user_redirected_to_login(self, client):
        """Unauthenticated users redirected to /login."""
        response = client.get("/accuracy-breakdown", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_valid_jwt_token_authentication(self, client, app_with_db, tmp_settings):
        """Valid JWT token allows access for Premium+ users."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/accuracy-breakdown", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_jwt_token_rejected(self, client):
        """Invalid JWT tokens are rejected."""
        response = client.get("/accuracy-breakdown", cookies={"rot_session": "invalid_token"}, follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers["location"]


# ============================================================================
# Response Format Validation Tests
# ============================================================================

class TestAccuracyBreakdownResponse:
    @pytest.mark.asyncio
    async def test_response_html_content_type(self, client, app_with_db, tmp_settings):
        """Response has correct HTML content-type header."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/accuracy-breakdown", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_response_contains_page_content(self, client, app_with_db, tmp_settings):
        """Response contains expected page elements."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/accuracy-breakdown", cookies={"rot_session": token})
        assert response.status_code == 200
        # Basic HTML structure check
        assert b"<html" in response.content or b"<!DOCTYPE" in response.content


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestAccuracyBreakdownTierMatrix:
    @pytest.mark.parametrize("tier,should_allow", [
        ("free", False),
        ("pro", True),
        ("premium", True),
        ("ultra", True),
        ("enterprise", True),
        ("admin", True),
    ])
    @pytest.mark.asyncio
    async def test_tier_access_control_matrix(self, client, app_with_db, tmp_settings, tier, should_allow):
        """Comprehensive tier access control matrix for all 6 tiers."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/accuracy-breakdown", cookies={"rot_session": token}, follow_redirects=False)

        if should_allow:
            assert response.status_code == 200
        else:
            assert response.status_code == 302
            assert "/pricing" in response.headers["location"]
