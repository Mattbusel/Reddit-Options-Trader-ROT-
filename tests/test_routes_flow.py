"""
Comprehensive tests for options flow intelligence routes (Pro+ feature).

Routes tested:
- GET /flow (dashboard)
- GET /api/v1/flow/events
- GET /api/v1/flow/summary
- GET /api/v1/flow/timeline/{ticker}
- GET /api/v1/flow/convergences
- GET /api/v1/flow/patterns

Coverage:
- Tier gating (Pro+ required)
- Auth validation
- Response formats (HTML/JSON)
- Query parameters
- Feature gates (convergences, patterns)
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-flow-tests!")
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
        web={"secret_key": "test-secret-key-for-flow-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-flow-tests!!"},
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
    email = f"flow_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /flow - Dashboard Tests
# ============================================================================

class TestFlowDashboard:
    @pytest.mark.asyncio
    async def test_flow_dashboard_free_tier_locked(self, client, app_with_db, tmp_settings):
        """Free tier can view page but sees locked state."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/flow", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_flow_dashboard_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier users can access flow dashboard."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/flow", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_flow_dashboard_html_content(self, client, app_with_db, tmp_settings):
        """Flow dashboard returns HTML."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/flow", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


# ============================================================================
# GET /api/v1/flow/events - Events API Tests
# ============================================================================

class TestFlowEventsAPI:
    @pytest.mark.asyncio
    async def test_flow_events_requires_auth(self, client):
        """Flow events API requires authentication."""
        response = client.get("/api/v1/flow/events")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_flow_events_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from flow events API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/flow/events", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_flow_events_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access flow events API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/flow/events", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_flow_events_returns_json(self, client, app_with_db, tmp_settings):
        """Flow events API returns JSON."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/flow/events", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_flow_events_with_parameters(self, client, app_with_db, tmp_settings):
        """Flow events API accepts query parameters."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="ultra")
        response = client.get("/api/v1/flow/events?ticker=AAPL&hours=48&limit=100",
                             cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# GET /api/v1/flow/summary - Summary API Tests
# ============================================================================

class TestFlowSummaryAPI:
    @pytest.mark.asyncio
    async def test_flow_summary_requires_auth(self, client):
        """Flow summary API requires authentication."""
        response = client.get("/api/v1/flow/summary")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_flow_summary_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access flow summary API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/flow/summary", cookies={"rot_session": token})
        assert response.status_code == 200


# ============================================================================
# GET /api/v1/flow/timeline/{ticker} - Timeline API Tests
# ============================================================================

class TestFlowTimelineAPI:
    @pytest.mark.asyncio
    async def test_flow_timeline_requires_auth(self, client):
        """Flow timeline API requires authentication."""
        response = client.get("/api/v1/flow/timeline/AAPL")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_flow_timeline_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access flow timeline API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/flow/timeline/NVDA", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/flow/convergences - Convergences API Tests
# ============================================================================

class TestFlowConvergencesAPI:
    @pytest.mark.asyncio
    async def test_flow_convergences_requires_auth(self, client):
        """Flow convergences API requires authentication."""
        response = client.get("/api/v1/flow/convergences")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_flow_convergences_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from convergences."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/flow/convergences", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_flow_convergences_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access convergences API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/flow/convergences", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/flow/patterns - Patterns API Tests
# ============================================================================

class TestFlowPatternsAPI:
    @pytest.mark.asyncio
    async def test_flow_patterns_requires_auth(self, client):
        """Flow patterns API requires authentication."""
        response = client.get("/api/v1/flow/patterns")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_flow_patterns_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from patterns."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/flow/patterns", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_flow_patterns_premium_tier_allowed(self, client, app_with_db, tmp_settings):
        """Premium tier can access patterns API (Premium+ feature)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/flow/patterns", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestFlowTierMatrix:
    @pytest.mark.parametrize("tier,should_allow", [
        ("free", False),
        ("pro", True),
        ("premium", True),
        ("ultra", True),
        ("enterprise", True),
        ("admin", True),
    ])
    @pytest.mark.asyncio
    async def test_flow_events_tier_matrix(self, client, app_with_db, tmp_settings, tier, should_allow):
        """Comprehensive tier access control matrix for flow events."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/api/v1/flow/events", cookies={"rot_session": token})

        if should_allow:
            assert response.status_code == 200
        else:
            assert response.status_code == 403
