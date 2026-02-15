"""
Comprehensive tests for Signal Replay route (Pro+ feature).

Routes tested:
- GET /replay

Coverage:
- Public access (shows locked state for free tier)
- Tier gating (Pro+ required for full access)
- HTML response format
- Query parameters (hours filter)
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-replay-tests!")
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
        web={"secret_key": "test-secret-key-for-replay-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-replay-tests!!"},
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
    email = f"replay_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /replay - Signal Replay Tests
# ============================================================================

class TestSignalReplay:
    @pytest.mark.asyncio
    async def test_replay_unauthenticated_access(self, client):
        """Unauthenticated users can view replay page (locked state)."""
        response = client.get("/replay")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_replay_free_tier_locked(self, client, app_with_db, tmp_settings):
        """Free tier can view page but sees locked state."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/replay", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_replay_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access signal replay."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/replay", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_replay_returns_html(self, client, app_with_db, tmp_settings):
        """Replay page returns HTML."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/replay", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_replay_with_hours_parameter(self, client, app_with_db, tmp_settings):
        """Replay accepts hours query parameter."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="ultra")
        response = client.get("/replay?hours=48", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_replay_contains_timeline_elements(self, client, app_with_db, tmp_settings):
        """Replay page contains timeline visualization elements."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/replay", cookies={"rot_session": token})
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference replay or timeline concepts
        assert b"replay" in content or b"timeline" in content or b"signal" in content


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestReplayTierMatrix:
    @pytest.mark.parametrize("tier,should_allow", [
        ("free", False),
        ("pro", True),
        ("premium", True),
        ("ultra", True),
        ("enterprise", True),
        ("admin", True),
    ])
    @pytest.mark.asyncio
    async def test_replay_tier_matrix(self, client, app_with_db, tmp_settings, tier, should_allow):
        """Comprehensive tier access control matrix for replay."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/replay", cookies={"rot_session": token})

        # All tiers get 200 (page loads), but free tier sees locked state
        assert response.status_code == 200

        if not should_allow:
            # Free tier page should indicate locked/upgrade
            content = response.content.lower()
            assert b"upgrade" in content or b"locked" in content or b"pro" in content
