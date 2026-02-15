"""
Comprehensive tests for performance dashboard routes (Premium+ feature).

Routes tested:
- GET /performance

Coverage:
- Auth requirement (login required)
- Tier gating (Premium+ required)
- HTML response format
- Redirect behavior for unauthenticated/low-tier users
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-performance-tests!")
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
        web={"secret_key": "test-secret-key-for-performance-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-performance-tests!!"},
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
    email = f"perf_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /performance - Performance Dashboard Tests
# ============================================================================

class TestPerformanceDashboard:
    @pytest.mark.asyncio
    async def test_performance_requires_login(self, client):
        """Unauthenticated users redirected to login."""
        response = client.get("/performance", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_performance_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier redirected to pricing."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/performance", cookies={"rot_session": token}, follow_redirects=False)
        assert response.status_code == 302
        assert "/pricing" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_performance_pro_tier_blocked(self, client, app_with_db, tmp_settings):
        """Pro tier redirected to pricing (Premium+ required)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/performance", cookies={"rot_session": token}, follow_redirects=False)
        assert response.status_code == 302
        assert "/pricing" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_performance_premium_tier_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier can access performance dashboard."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/performance", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_performance_ultra_tier_allowed(self, client, app_with_db, tmp_settings):
        """Ultra tier can access performance dashboard."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="ultra")
        response = client.get("/performance", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_performance_returns_html(self, client, app_with_db, tmp_settings):
        """Performance dashboard returns HTML."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/performance", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_performance_contains_accuracy_data(self, client, app_with_db, tmp_settings):
        """Performance dashboard includes accuracy data."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/performance", cookies={"rot_session": token})
        assert response.status_code == 200
        content = response.content.lower()
        assert b"accuracy" in content or b"performance" in content


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestPerformanceTierMatrix:
    @pytest.mark.parametrize("tier,should_allow", [
        ("free", False),
        ("pro", False),
        ("premium", True),
        ("ultra", True),
        ("enterprise", True),
        ("admin", True),
    ])
    @pytest.mark.asyncio
    async def test_performance_tier_matrix(self, client, app_with_db, tmp_settings, tier, should_allow):
        """Comprehensive tier access control matrix for performance dashboard."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/performance", cookies={"rot_session": token}, follow_redirects=False)

        if should_allow:
            assert response.status_code == 200
        else:
            assert response.status_code == 302
            assert "/pricing" in response.headers.get("location", "")
