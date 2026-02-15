"""
Comprehensive tests for Sector Rotation routes (Pro+ feature).

Routes tested:
- GET /sector-rotation

Coverage:
- Auth requirement (login required)
- Tier gating (Pro+ required)
- HTML response format
- Redirect behavior for unauthenticated/low-tier users
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-sector-tests!")
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
        web={"secret_key": "test-secret-key-for-sector-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-sector-tests!!"},
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
    email = f"sector_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /sector-rotation - Sector Rotation Dashboard Tests
# ============================================================================

class TestSectorRotation:
    @pytest.mark.asyncio
    async def test_sector_requires_login(self, client):
        """Unauthenticated users redirected to login."""
        response = client.get("/sector-rotation", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_sector_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier redirected to pricing."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/sector-rotation", cookies={"rot_session": token}, follow_redirects=False)
        assert response.status_code == 302
        assert "/pricing" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_sector_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access sector rotation."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/sector-rotation", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_sector_premium_tier_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier can access sector rotation."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/sector-rotation", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_sector_returns_html(self, client, app_with_db, tmp_settings):
        """Sector rotation returns HTML."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/sector-rotation", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_sector_contains_sector_data(self, client, app_with_db, tmp_settings):
        """Sector rotation page contains sector-related data."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/sector-rotation", cookies={"rot_session": token})
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference sectors or rotation
        assert b"sector" in content or b"rotation" in content or b"momentum" in content


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestSectorTierMatrix:
    @pytest.mark.parametrize("tier,should_allow", [
        ("free", False),
        ("pro", True),
        ("premium", True),
        ("ultra", True),
        ("enterprise", True),
        ("admin", True),
    ])
    @pytest.mark.asyncio
    async def test_sector_tier_matrix(self, client, app_with_db, tmp_settings, tier, should_allow):
        """Comprehensive tier access control matrix for sector rotation."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/sector-rotation", cookies={"rot_session": token}, follow_redirects=False)

        if should_allow:
            assert response.status_code == 200
        else:
            assert response.status_code == 302
            assert "/pricing" in response.headers.get("location", "")
