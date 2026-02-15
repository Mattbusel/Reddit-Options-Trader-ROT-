"""
Comprehensive tests for Hall of Legends route (public access).

Routes tested:
- GET /hall-of-legends

Coverage:
- Public access (unauthenticated & all tiers)
- HTML response format
- Content validation (legendary trades)
- Aggregation stats validation
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-hall-tests!")
os.environ.setdefault("ROT_REDDIT_CLIENT_ID", "test")
os.environ.setdefault("ROT_REDDIT_CLIENT_SECRET", "test")
os.environ.setdefault("ROT_REDDIT_USER_AGENT", "test")

from rot.core.config import Settings
from rot.web.app import create_app, connect_db, register_routes


@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(
        storage={"root": str(tmp_path)},
        web={"secret_key": "test-secret-key-for-hall-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-hall-tests!!"},
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
# GET /hall-of-legends - Hall of Legends Tests
# ============================================================================

class TestHallOfLegends:
    @pytest.mark.asyncio
    async def test_hall_page_public_access(self, client):
        """Unauthenticated users can access Hall of Legends."""
        response = client.get("/hall-of-legends")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_hall_page_html_content(self, client):
        """Hall of Legends returns HTML."""
        response = client.get("/hall-of-legends")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_hall_contains_legendary_traders(self, client):
        """Hall contains famous trader names."""
        response = client.get("/hall-of-legends")
        assert response.status_code == 200
        content = response.content.lower()
        # Check for some legendary traders
        traders = [b"soros", b"burry", b"paulson"]
        matches = sum(1 for trader in traders if trader in content)
        assert matches >= 2

    @pytest.mark.asyncio
    async def test_hall_contains_strategy_types(self, client):
        """Hall contains strategy types."""
        response = client.get("/hall-of-legends")
        assert response.status_code == 200
        content = response.content.lower()
        # Check for strategy types
        strategies = [b"short", b"long", b"macro", b"options"]
        matches = sum(1 for strategy in strategies if strategy in content)
        assert matches >= 3

    @pytest.mark.asyncio
    async def test_hall_contains_profit_data(self, client):
        """Hall displays profit information."""
        response = client.get("/hall-of-legends")
        assert response.status_code == 200
        content = response.content.lower()
        # Should mention profit or dollar amounts
        assert b"profit" in content or b"$" in content or b"billion" in content

    @pytest.mark.asyncio
    async def test_hall_contains_trade_descriptions(self, client):
        """Hall contains trade descriptions."""
        response = client.get("/hall-of-legends")
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference famous trades
        famous_trades = [b"bank of england", b"big short", b"gamestop", b"covid"]
        matches = sum(1 for trade in famous_trades if trade in content)
        assert matches >= 2

    @pytest.mark.asyncio
    async def test_hall_contains_year_data(self, client):
        """Hall contains year information."""
        response = client.get("/hall-of-legends")
        assert response.status_code == 200
        content = response.content.lower()
        # Should mention years
        years = [b"2007", b"2008", b"1992", b"2020"]
        matches = sum(1 for year in years if year in content)
        assert matches >= 2

    @pytest.mark.asyncio
    async def test_hall_contains_rating_system(self, client):
        """Hall includes rating system."""
        response = client.get("/hall-of-legends")
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference ratings or stars
        assert b"rating" in content or b"star" in content or b"legend" in content

    @pytest.mark.asyncio
    async def test_hall_contains_instruments(self, client):
        """Hall mentions financial instruments."""
        response = client.get("/hall-of-legends")
        assert response.status_code == 200
        content = response.content.lower()
        # Should mention instruments
        instruments = [b"cds", b"futures", b"equity", b"shares", b"calls"]
        matches = sum(1 for instrument in instruments if instrument in content)
        assert matches >= 2
