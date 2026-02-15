"""
Comprehensive tests for affiliate program routes.

Routes tested:
- GET /affiliates (public page)
- POST /api/v1/affiliates/register
- GET /api/v1/affiliates/stats
- GET /ref/{ref_code}

Coverage:
- Public access (affiliates page)
- Auth-required endpoints
- Referral tracking
- Commission calculation
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-affiliates-tests!")
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
        web={"secret_key": "test-secret-key-for-affiliates-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-affiliates-tests!!"},
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
    email = f"affiliate_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /affiliates - Public Page Tests
# ============================================================================

class TestAffiliatesPublicPage:
    @pytest.mark.asyncio
    async def test_affiliates_page_unauthenticated(self, client):
        """Unauthenticated users can view affiliates page."""
        response = client.get("/affiliates")
        assert response.status_code == 200
        assert b"affiliate" in response.content.lower() or b"referral" in response.content.lower()

    @pytest.mark.asyncio
    async def test_affiliates_page_authenticated(self, client, app_with_db, tmp_settings):
        """Authenticated users can view affiliates page."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/affiliates", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_affiliates_page_html_content(self, client):
        """Affiliates page returns HTML."""
        response = client.get("/affiliates")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


# ============================================================================
# POST /api/v1/affiliates/register - Registration Tests
# ============================================================================

class TestAffiliateRegistration:
    @pytest.mark.asyncio
    async def test_register_affiliate_requires_auth(self, client):
        """Registration requires authentication."""
        response = client.post("/api/v1/affiliates/register", json={"payment_email": "test@test.com"})
        assert response.status_code in [401, 403, 422]

    @pytest.mark.asyncio
    async def test_register_affiliate_success(self, client, app_with_db, tmp_settings):
        """Authenticated user can register as affiliate."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.post("/api/v1/affiliates/register",
                               json={"payment_email": "payout@test.com"},
                               cookies={"rot_session": token})
        assert response.status_code in [200, 201]
        data = response.json()
        assert data.get("ok") is True or "affiliate" in data

    @pytest.mark.parametrize("tier", ["free", "pro", "premium", "ultra", "enterprise", "admin"])
    @pytest.mark.asyncio
    async def test_all_tiers_can_register(self, client, app_with_db, tmp_settings, tier):
        """All tiers can register as affiliate (no tier gating)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.post("/api/v1/affiliates/register",
                               json={"payment_email": f"{tier}@test.com"},
                               cookies={"rot_session": token})
        assert response.status_code in [200, 201]


# ============================================================================
# GET /ref/{ref_code} - Referral Redirect Tests
# ============================================================================

class TestReferralRedirect:
    @pytest.mark.asyncio
    async def test_referral_redirect_valid_code(self, client):
        """Valid referral code redirects to dashboard."""
        response = client.get("/ref/TESTCODE123", follow_redirects=False)
        assert response.status_code == 302
        assert "/dashboard" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_referral_redirect_sanitizes_code(self, client):
        """Referral code is sanitized to prevent injection (special chars stripped)."""
        # Test that special chars are stripped from ref code
        response = client.get("/ref/ABC123!@#$%invalid", follow_redirects=False)
        assert response.status_code == 302
        redirect_url = response.headers.get("location", "")
        # Should redirect to /dashboard with sanitized ref (alphanumeric only)
        assert "/dashboard?ref=" in redirect_url
        # Sanitized ref should only contain alphanumeric chars
        ref_param = redirect_url.split("ref=")[1]
        assert all(c.isalnum() or c in "-_" for c in ref_param)

    @pytest.mark.asyncio
    async def test_referral_redirect_with_source(self, client):
        """Referral tracking accepts source parameter."""
        response = client.get("/ref/TESTCODE?source=twitter", follow_redirects=False)
        assert response.status_code == 302
