"""
Comprehensive tests for Wall of Shame route (public access).

Routes tested:
- GET /wall-of-shame

Coverage:
- Public access (unauthenticated & all tiers)
- HTML response format
- Content validation (historic raids data)
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-raid-tests!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes


@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-raid-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-raid-tests!!"},
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


# ============================================================================
# GET /wall-of-shame - Wall of Shame Tests
# ============================================================================

class TestWallOfShame:
    @pytest.mark.asyncio
    async def test_wall_of_shame_public_access(self, client):
        """Unauthenticated users can access Wall of Shame."""
        response = client.get("/wall-of-shame")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_wall_of_shame_html_content(self, client):
        """Wall of Shame returns HTML."""
        response = client.get("/wall-of-shame")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_wall_of_shame_contains_institutions(self, client):
        """Wall of Shame contains institution names."""
        response = client.get("/wall-of-shame")
        assert response.status_code == 200
        content = response.content.lower()
        # Check for some famous raided institutions
        institutions = [b"enron", b"lehman", b"bear stearns", b"worldcom"]
        matches = sum(1 for inst in institutions if inst in content)
        assert matches >= 2

    @pytest.mark.asyncio
    async def test_wall_of_shame_contains_agencies(self, client):
        """Wall of Shame mentions enforcement agencies."""
        response = client.get("/wall-of-shame")
        assert response.status_code == 200
        content = response.content.lower()
        # Check for enforcement agencies
        agencies = [b"sec", b"doj", b"fbi", b"federal"]
        matches = sum(1 for agency in agencies if agency in content)
        assert matches >= 2

    @pytest.mark.asyncio
    async def test_wall_of_shame_contains_penalties(self, client):
        """Wall of Shame displays penalty amounts."""
        response = client.get("/wall-of-shame")
        assert response.status_code == 200
        content = response.content.lower()
        # Should mention penalties or dollar amounts
        assert b"billion" in content or b"million" in content or b"$" in content

    @pytest.mark.asyncio
    async def test_wall_of_shame_contains_years(self, client):
        """Wall of Shame contains year information."""
        response = client.get("/wall-of-shame")
        assert response.status_code == 200
        content = response.content.lower()
        # Should mention years of major financial crises
        years = [b"2008", b"2001", b"1989", b"2012"]
        matches = sum(1 for year in years if year in content)
        assert matches >= 2

    @pytest.mark.asyncio
    async def test_wall_of_shame_contains_action_types(self, client):
        """Wall of Shame mentions action types."""
        response = client.get("/wall-of-shame")
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference types of enforcement actions
        actions = [b"raid", b"seizure", b"settlement", b"indictment", b"guilty"]
        matches = sum(1 for action in actions if action in content)
        assert matches >= 2

    @pytest.mark.asyncio
    async def test_wall_of_shame_contains_executives(self, client):
        """Wall of Shame mentions executives charged."""
        response = client.get("/wall-of-shame")
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference executives or convictions
        assert b"executive" in content or b"charged" in content or b"convicted" in content

    @pytest.mark.asyncio
    async def test_wall_of_shame_contains_historic_data(self, client):
        """Wall of Shame contains historic enforcement data."""
        response = client.get("/wall-of-shame")
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference fraud or financial crimes
        assert b"fraud" in content or b"crime" in content or b"enforcement" in content
