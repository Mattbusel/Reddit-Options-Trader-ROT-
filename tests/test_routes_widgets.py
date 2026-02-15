"""
Comprehensive tests for Embed Widget routes.

Routes tested:
- GET /widgets
- GET /widget/{ticker}
- GET /api/v1/widgets/{ticker}/json

Coverage:
- Public access (all routes)
- HTML response format
- JSON API response
- Ticker filtering
- Embed widget rendering
- Query parameters
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-widgets-tests!")
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
        web={"secret_key": "test-secret-key-for-widgets-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-widgets-tests!!"},
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
    email = f"widgets_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /widgets - Widget Generator Page Tests
# ============================================================================

class TestWidgetsGeneratorPage:
    @pytest.mark.asyncio
    async def test_widgets_page_public_access(self, client):
        """Unauthenticated users can access widgets generator page."""
        response = client.get("/widgets")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_widgets_page_returns_html(self, client):
        """Widgets generator page returns HTML."""
        response = client.get("/widgets")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_widgets_page_contains_content(self, client):
        """Widgets page contains widget-related content."""
        response = client.get("/widgets")
        assert response.status_code == 200
        content = response.content.lower()
        # Should reference widgets or embed concepts
        assert b"widget" in content or b"embed" in content

    @pytest.mark.asyncio
    async def test_widgets_page_authenticated_access(self, client, app_with_db, tmp_settings):
        """Authenticated users can access widgets generator page."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/widgets", cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# GET /widget/{ticker} - Ticker Widget Embed Tests
# ============================================================================

class TestTickerWidgetEmbed:
    @pytest.mark.asyncio
    async def test_ticker_widget_public_access(self, client):
        """Unauthenticated users can access ticker widget."""
        response = client.get("/widget/AAPL")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ticker_widget_returns_html(self, client):
        """Ticker widget returns HTML."""
        response = client.get("/widget/TSLA")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_ticker_widget_uppercase_normalization(self, client):
        """Ticker symbols are normalized to uppercase."""
        response = client.get("/widget/aapl")
        assert response.status_code == 200
        # Widget should render successfully

    @pytest.mark.asyncio
    async def test_ticker_widget_various_tickers(self, client):
        """Ticker widget works for various ticker symbols."""
        tickers = ["AAPL", "TSLA", "GME", "SPY", "QQQ"]
        for ticker in tickers:
            response = client.get(f"/widget/{ticker}")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ticker_widget_contains_ticker_data(self, client):
        """Ticker widget contains ticker-specific content."""
        response = client.get("/widget/GME")
        assert response.status_code == 200
        content = response.content.upper()
        # Should reference the ticker or widget
        assert b"GME" in content or b"WIDGET" in content or b"SIGNAL" in content


# ============================================================================
# GET /api/v1/widgets/{ticker}/json - Widget JSON API Tests
# ============================================================================

class TestWidgetJSONAPI:
    @pytest.mark.asyncio
    async def test_widget_json_public_access(self, client):
        """Widget JSON API is publicly accessible."""
        response = client.get("/api/v1/widgets/AAPL/json")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_widget_json_returns_json(self, client):
        """Widget JSON API returns JSON."""
        response = client.get("/api/v1/widgets/TSLA/json")
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_widget_json_contains_ticker(self, client):
        """Widget JSON API includes ticker in response."""
        response = client.get("/api/v1/widgets/AAPL/json")
        assert response.status_code == 200
        data = response.json()
        assert "ticker" in data
        assert data["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_widget_json_contains_signals(self, client):
        """Widget JSON API includes signals array."""
        response = client.get("/api/v1/widgets/GME/json")
        assert response.status_code == 200
        data = response.json()
        assert "signals" in data
        assert isinstance(data["signals"], list)

    @pytest.mark.asyncio
    async def test_widget_json_contains_count(self, client):
        """Widget JSON API includes count field."""
        response = client.get("/api/v1/widgets/SPY/json")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert isinstance(data["count"], int)

    @pytest.mark.asyncio
    async def test_widget_json_with_limit_parameter(self, client):
        """Widget JSON API accepts limit parameter."""
        response = client.get("/api/v1/widgets/AAPL/json?limit=3")
        assert response.status_code == 200
        data = response.json()
        # Limit is capped at 10, minimum 1
        assert len(data["signals"]) <= 3

    @pytest.mark.asyncio
    async def test_widget_json_limit_validation(self, client):
        """Widget JSON API validates limit parameter."""
        # Test minimum limit (1)
        response = client.get("/api/v1/widgets/AAPL/json?limit=1")
        assert response.status_code == 200

        # Test maximum limit (10)
        response = client.get("/api/v1/widgets/AAPL/json?limit=10")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_widget_json_uppercase_normalization(self, client):
        """Widget JSON API normalizes ticker to uppercase."""
        response = client.get("/api/v1/widgets/aapl/json")
        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_widget_json_powered_by_field(self, client):
        """Widget JSON API includes powered_by attribution."""
        response = client.get("/api/v1/widgets/TSLA/json")
        assert response.status_code == 200
        data = response.json()
        assert "powered_by" in data
        assert "ROT" in data["powered_by"]


# ============================================================================
# All Tiers Access Matrix
# ============================================================================

class TestWidgetsTierMatrix:
    @pytest.mark.parametrize("tier", [
        "free",
        "pro",
        "premium",
        "ultra",
        "enterprise",
        "admin",
    ])
    @pytest.mark.asyncio
    async def test_widgets_all_tiers_allowed(self, client, app_with_db, tmp_settings, tier):
        """All tiers can access widget routes (public)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)

        # Generator page
        response = client.get("/widgets", cookies={"rot_session": token})
        assert response.status_code == 200

        # Ticker widget
        response = client.get("/widget/AAPL", cookies={"rot_session": token})
        assert response.status_code == 200

        # JSON API
        response = client.get("/api/v1/widgets/AAPL/json", cookies={"rot_session": token})
        assert response.status_code == 200
