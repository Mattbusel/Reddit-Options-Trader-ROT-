"""
Comprehensive tests for broker integration routes.

Routes tested:
- GET /brokers (broker connection page)
- POST /api/v1/brokers/connect
- POST /api/v1/brokers/disconnect
- POST /api/v1/brokers/preview
- POST /api/v1/brokers/execute

Coverage:
- Tier gating (Pro+ required for broker features)
- Auth validation
- Broker connection management
- Order preview and execution
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-brokers-tests!")
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
        web={"secret_key": "test-secret-key-for-brokers-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-brokers-tests!!"},
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
    email = f"broker_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /brokers - Broker Page Tests
# ============================================================================

class TestBrokersPage:
    @pytest.mark.asyncio
    async def test_brokers_page_unauthenticated(self, client):
        """Unauthenticated users can view brokers page (shows connection prompt)."""
        response = client.get("/brokers")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_brokers_page_authenticated(self, client, app_with_db, tmp_settings):
        """Authenticated users can view brokers page."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/brokers", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_brokers_page_html_content(self, client):
        """Brokers page returns HTML."""
        response = client.get("/brokers")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


# ============================================================================
# POST /api/v1/brokers/connect - Connection Tests
# ============================================================================

class TestBrokerConnect:
    @pytest.mark.asyncio
    async def test_connect_requires_auth(self, client):
        """Connecting broker requires authentication."""
        response = client.post("/api/v1/brokers/connect", json={"broker": "robinhood", "credentials": {}})
        assert response.status_code in [401, 403, 422]

    @pytest.mark.asyncio
    async def test_connect_requires_pro_tier(self, client, app_with_db, tmp_settings):
        """Free tier cannot connect brokers."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.post("/api/v1/brokers/connect",
                               json={"broker": "robinhood", "credentials": {}},
                               cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.parametrize("tier", ["pro", "premium", "ultra", "enterprise"])
    @pytest.mark.asyncio
    async def test_connect_pro_plus_allowed(self, client, app_with_db, tmp_settings, tier):
        """Pro+ tiers can connect brokers."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.post("/api/v1/brokers/connect",
                               json={"broker": "tastytrade", "credentials": {}},
                               cookies={"rot_session": token})
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True

    @pytest.mark.asyncio
    async def test_connect_unsupported_broker(self, client, app_with_db, tmp_settings):
        """Connecting unsupported broker returns 400."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.post("/api/v1/brokers/connect",
                               json={"broker": "invalid_broker", "credentials": {}},
                               cookies={"rot_session": token})
        assert response.status_code == 400


# ============================================================================
# POST /api/v1/brokers/disconnect - Disconnection Tests
# ============================================================================

class TestBrokerDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_requires_auth(self, client):
        """Disconnecting broker requires authentication."""
        response = client.post("/api/v1/brokers/disconnect", json={"broker": "robinhood"})
        assert response.status_code in [401, 403, 422]

    @pytest.mark.asyncio
    async def test_disconnect_success(self, client, app_with_db, tmp_settings):
        """Authenticated user can disconnect broker."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.post("/api/v1/brokers/disconnect",
                               json={"broker": "robinhood"},
                               cookies={"rot_session": token})
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True


# ============================================================================
# POST /api/v1/brokers/preview - Order Preview Tests
# ============================================================================

class TestOrderPreview:
    @pytest.mark.asyncio
    async def test_preview_requires_auth(self, client):
        """Order preview requires authentication."""
        response = client.post("/api/v1/brokers/preview", json={"signal_id": "test", "broker": "robinhood"})
        assert response.status_code in [401, 403, 422]

    @pytest.mark.asyncio
    async def test_preview_requires_pro_tier(self, client, app_with_db, tmp_settings):
        """Free tier cannot preview orders."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.post("/api/v1/brokers/preview",
                               json={"signal_id": "test", "broker": "robinhood"},
                               cookies={"rot_session": token})
        assert response.status_code == 403


# ============================================================================
# POST /api/v1/brokers/execute - Order Execution Tests
# ============================================================================

class TestOrderExecution:
    @pytest.mark.asyncio
    async def test_execute_requires_auth(self, client):
        """Order execution requires authentication."""
        response = client.post("/api/v1/brokers/execute", json={"signal_id": "test", "broker": "robinhood", "dry_run": True})
        assert response.status_code in [401, 403, 422]

    @pytest.mark.asyncio
    async def test_execute_requires_pro_tier(self, client, app_with_db, tmp_settings):
        """Free tier cannot execute orders."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.post("/api/v1/brokers/execute",
                               json={"signal_id": "test", "broker": "robinhood", "dry_run": True},
                               cookies={"rot_session": token})
        assert response.status_code == 403
