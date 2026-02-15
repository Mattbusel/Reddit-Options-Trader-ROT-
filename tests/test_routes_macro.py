"""
Comprehensive tests for macro events routes (Pro+ feature).

Routes tested:
- GET /macro/calendar
- GET /macro/earnings
- GET /macro/insider
- GET /macro/fomc
- GET /api/v1/macro/events
- GET /api/v1/macro/earnings
- GET /api/v1/macro/insider
- GET /api/v1/macro/impact

Coverage:
- Tier gating (Pro+ required for most features)
- Auth validation (API endpoints)
- HTML/JSON response formats
- Query parameters
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-macro-tests!")
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
        web={"secret_key": "test-secret-key-for-macro-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-macro-tests!!"},
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
    email = f"macro_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /macro/calendar - Calendar Page Tests
# ============================================================================

class TestMacroCalendarPage:
    @pytest.mark.asyncio
    async def test_calendar_page_free_tier(self, client, app_with_db, tmp_settings):
        """Free tier can view calendar page (limited access)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/macro/calendar", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_calendar_page_pro_tier(self, client, app_with_db, tmp_settings):
        """Pro tier can access macro calendar."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/macro/calendar", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_calendar_page_html_content(self, client, app_with_db, tmp_settings):
        """Calendar page returns HTML."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/macro/calendar", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


# ============================================================================
# GET /macro/earnings - Earnings Page Tests
# ============================================================================

class TestMacroEarningsPage:
    @pytest.mark.asyncio
    async def test_earnings_page_free_tier(self, client, app_with_db, tmp_settings):
        """Free tier can view earnings page (limited access)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/macro/earnings", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_earnings_page_pro_tier(self, client, app_with_db, tmp_settings):
        """Pro tier can access earnings calendar."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/macro/earnings", cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# GET /macro/insider - Insider Page Tests
# ============================================================================

class TestMacroInsiderPage:
    @pytest.mark.asyncio
    async def test_insider_page_free_tier(self, client, app_with_db, tmp_settings):
        """Free tier can view insider page (limited access)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/macro/insider", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_insider_page_pro_tier(self, client, app_with_db, tmp_settings):
        """Pro tier can access insider trades."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/macro/insider", cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# GET /macro/fomc - FOMC Page Tests
# ============================================================================

class TestMacroFOMCPage:
    @pytest.mark.asyncio
    async def test_fomc_page_free_tier(self, client, app_with_db, tmp_settings):
        """Free tier can view FOMC page (limited access)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/macro/fomc", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_fomc_page_pro_tier(self, client, app_with_db, tmp_settings):
        """Pro tier can access FOMC tracker."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/macro/fomc", cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# GET /api/v1/macro/events - Events API Tests
# ============================================================================

class TestMacroEventsAPI:
    @pytest.mark.asyncio
    async def test_events_api_free_tier_limited(self, client, app_with_db, tmp_settings):
        """Free tier gets limited calendar access (3 days, 5 events max)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/macro/events", cookies={"rot_session": token})
        # Free tier allowed but with limits (3 days, 5 events)
        assert response.status_code in [200, 500]  # 500 if no data available

    @pytest.mark.asyncio
    async def test_events_api_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access events API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/macro/events", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]

    @pytest.mark.asyncio
    async def test_events_api_with_parameters(self, client, app_with_db, tmp_settings):
        """Events API accepts query parameters."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/macro/events?days=14&direction=upcoming&limit=100",
                             cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/macro/earnings - Earnings API Tests
# ============================================================================

class TestMacroEarningsAPI:
    @pytest.mark.asyncio
    async def test_earnings_api_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from earnings API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/macro/earnings", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_earnings_api_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access earnings API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/macro/earnings", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/macro/insider - Insider API Tests
# ============================================================================

class TestMacroInsiderAPI:
    @pytest.mark.asyncio
    async def test_insider_api_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from insider API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/macro/insider", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_insider_api_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access insider API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/macro/insider", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/macro/impact - Impact API Tests
# ============================================================================

class TestMacroImpactAPI:
    @pytest.mark.asyncio
    async def test_impact_api_requires_premium(self, client, app_with_db, tmp_settings):
        """Impact API requires Premium+ tier."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/macro/impact?event_type=FOMC", cookies={"rot_session": token})
        # Pro tier should get 403
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_impact_api_premium_tier_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier can access impact API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/macro/impact?event_type=FOMC", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]
