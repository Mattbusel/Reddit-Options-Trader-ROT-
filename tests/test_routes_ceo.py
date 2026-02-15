"""
Comprehensive tests for CEO Rap Sheet routes.

Routes tested:
- GET /ceo-rap-sheet (scandal tracker page)
- GET /ceo-rap-sheet?category=fraud

Coverage:
- Public access (no auth required)
- Category filtering
- Response format
- HTML content validation
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-ceo-tests!")
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
        web={"secret_key": "test-secret-key-for-ceo-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-ceo-tests!!"},
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
    email = f"ceo_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /ceo-rap-sheet - CEO Rap Sheet Page Tests
# ============================================================================

class TestCEORapSheet:
    @pytest.mark.asyncio
    async def test_ceo_rap_sheet_public_access(self, client):
        """CEO rap sheet is publicly accessible."""
        response = client.get("/ceo-rap-sheet")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ceo_rap_sheet_authenticated(self, client, app_with_db, tmp_settings):
        """Authenticated users can view CEO rap sheet."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/ceo-rap-sheet", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ceo_rap_sheet_html_content(self, client):
        """CEO rap sheet returns HTML."""
        response = client.get("/ceo-rap-sheet")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_ceo_rap_sheet_contains_data(self, client):
        """CEO rap sheet contains scandal data."""
        response = client.get("/ceo-rap-sheet")
        assert response.status_code == 200
        # Should contain references to known scandals
        assert b"ceo" in response.content.lower() or b"scandal" in response.content.lower()

    @pytest.mark.asyncio
    async def test_ceo_rap_sheet_category_filter(self, client):
        """CEO rap sheet accepts category filter."""
        response = client.get("/ceo-rap-sheet?category=fraud")
        assert response.status_code == 200

    @pytest.mark.parametrize("category", ["all", "fraud", "insider_trading", "crypto"])
    @pytest.mark.asyncio
    async def test_ceo_rap_sheet_valid_categories(self, client, category):
        """CEO rap sheet accepts valid category filters."""
        response = client.get(f"/ceo-rap-sheet?category={category}")
        assert response.status_code == 200

    @pytest.mark.parametrize("tier", ["free", "pro", "premium", "ultra", "enterprise", "admin"])
    @pytest.mark.asyncio
    async def test_ceo_rap_sheet_all_tiers(self, client, app_with_db, tmp_settings, tier):
        """All tiers can view CEO rap sheet (public feature)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/ceo-rap-sheet", cookies={"rot_session": token})
        assert response.status_code == 200
