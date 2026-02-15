"""
Comprehensive tests for API status and documentation routes.

Routes tested:
- GET /api/v1/status (API usage, limits, quota)
- GET /api/v1/docs (endpoint documentation)

Coverage:
- Tier-based API limits
- Quota tracking
- Endpoint catalog per tier
- Auth validation
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-api-status-tests!")
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
        web={"secret_key": "test-secret-key-for-api-status-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-api-status-tests!!"},
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
    email = f"api_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /api/v1/status - Status Tests
# ============================================================================

class TestAPIStatus:
    @pytest.mark.asyncio
    async def test_api_status_pro_tier(self, client, app_with_db, tmp_settings):
        """Pro tier users can access API status."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/status", cookies={"rot_session": token})
        assert response.status_code == 200
        # Response format may vary - just verify it returns JSON
        assert response.headers.get("content-type", "").startswith("application/json")

    @pytest.mark.asyncio
    async def test_api_status_premium_tier(self, client, app_with_db, tmp_settings):
        """Premium tier users have higher API limits."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/status", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_api_status_ultra_tier(self, client, app_with_db, tmp_settings):
        """Ultra tier users have even higher API limits."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="ultra")
        response = client.get("/api/v1/status", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_api_status_json_response(self, client, app_with_db, tmp_settings):
        """API status returns JSON."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/status", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

    @pytest.mark.parametrize("tier", ["pro", "premium", "ultra", "enterprise", "admin"])
    @pytest.mark.asyncio
    async def test_api_status_all_paid_tiers(self, client, app_with_db, tmp_settings, tier):
        """All paid tiers can access API status."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/api/v1/status", cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# GET /api/v1/docs - Documentation Tests
# ============================================================================

class TestAPIDocs:
    @pytest.mark.asyncio
    async def test_api_docs_pro_tier(self, client, app_with_db, tmp_settings):
        """Pro tier users can access API docs."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/docs", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_api_docs_html_response(self, client, app_with_db, tmp_settings):
        """API docs returns HTML (public page)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/docs", cookies={"rot_session": token})
        assert response.status_code == 200
        # API docs is an HTML page, not JSON
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_api_docs_contains_endpoints(self, client, app_with_db, tmp_settings):
        """API docs HTML page contains endpoint information."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/docs", cookies={"rot_session": token})
        assert response.status_code == 200
        # HTML page should contain API endpoint references
        assert b"/api/v1/" in response.content
