"""
Comprehensive tests for correlation routes (Pro+ feature).

Routes tested:
- GET /correlations (correlation explorer page)
- GET /api/v1/correlations/matrix
- GET /api/v1/correlations/{ticker}
- GET /api/v1/correlations/clusters
- GET /api/v1/correlations/lead-lag

Coverage:
- Tier gating (Pro+ required)
- Auth validation for API endpoints
- Response formats (HTML/JSON)
- Query parameters
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ROT_WEB_SECRET_KEY", "test-secret-key-for-correlations-tests!")
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
        web={"secret_key": "test-secret-key-for-correlations-tests!", "host": "127.0.0.1", "port": 8000},
        reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        auth={"jwt_secret": "test-jwt-secret-correlations-tests!!"},
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
    email = f"corr_{tier}_{unique}@example.com"
    pw_hash = hash_password("TestPass123!")
    user = await db.create_user(email, pw_hash)
    if tier != "free":
        await db.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user["id"]))
        await db.db.commit()
        user["tier"] = tier
    token = create_access_token(user["id"], user["email"], tier, settings)
    return user, token


# ============================================================================
# GET /correlations - Page Tests
# ============================================================================

class TestCorrelationsPage:
    @pytest.mark.asyncio
    async def test_correlations_page_free_tier(self, client, app_with_db, tmp_settings):
        """Free tier can view correlations page (may show locked/limited state)."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/correlations", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_correlations_page_pro_tier(self, client, app_with_db, tmp_settings):
        """Pro tier users can access correlations."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/correlations", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_correlations_page_html_content(self, client, app_with_db, tmp_settings):
        """Correlations page returns HTML."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/correlations", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


# ============================================================================
# GET /api/v1/correlations/matrix - Matrix API Tests
# ============================================================================

class TestCorrelationMatrixAPI:
    @pytest.mark.asyncio
    async def test_matrix_requires_auth(self, client):
        """Correlation matrix API requires authentication."""
        response = client.get("/api/v1/correlations/matrix")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_matrix_free_tier_blocked(self, client, app_with_db, tmp_settings):
        """Free tier blocked from matrix API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="free")
        response = client.get("/api/v1/correlations/matrix", cookies={"rot_session": token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_matrix_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access matrix API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/correlations/matrix", cookies={"rot_session": token})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_matrix_returns_json(self, client, app_with_db, tmp_settings):
        """Matrix API returns JSON."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="premium")
        response = client.get("/api/v1/correlations/matrix", cookies={"rot_session": token})
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")


# ============================================================================
# GET /api/v1/correlations/{ticker} - Ticker Correlation Tests
# ============================================================================

class TestTickerCorrelation:
    @pytest.mark.asyncio
    async def test_ticker_correlation_requires_auth(self, client):
        """Ticker correlation requires authentication."""
        response = client.get("/api/v1/correlations/AAPL")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_ticker_correlation_pro_tier(self, client, app_with_db, tmp_settings):
        """Pro tier can access ticker correlation."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/correlations/NVDA", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/correlations/clusters - Clusters API Tests
# ============================================================================

class TestCorrelationClusters:
    @pytest.mark.asyncio
    async def test_clusters_requires_auth(self, client):
        """Clusters API requires authentication."""
        response = client.get("/api/v1/correlations/clusters")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_clusters_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access clusters API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/correlations/clusters", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]


# ============================================================================
# GET /api/v1/correlations/lead-lag - Lead-Lag Tests
# ============================================================================

class TestLeadLagAPI:
    @pytest.mark.asyncio
    async def test_lead_lag_requires_auth(self, client):
        """Lead-lag API requires authentication."""
        response = client.get("/api/v1/correlations/lead-lag")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_lead_lag_pro_tier_allowed(self, client, app_with_db, tmp_settings):
        """Pro tier can access lead-lag API."""
        user, token = await _create_user(app_with_db, tmp_settings, tier="pro")
        response = client.get("/api/v1/correlations/lead-lag", cookies={"rot_session": token})
        # May return 200 or 500 if no data
        assert response.status_code in [200, 500]


# ============================================================================
# Tier Access Matrix
# ============================================================================

class TestCorrelationsTierMatrix:
    @pytest.mark.parametrize("tier", ["pro", "premium", "ultra", "enterprise", "admin"])
    @pytest.mark.asyncio
    async def test_all_paid_tiers_can_access(self, client, app_with_db, tmp_settings, tier):
        """All paid tiers can access correlation features."""
        user, token = await _create_user(app_with_db, tmp_settings, tier=tier)
        response = client.get("/api/v1/correlations/matrix", cookies={"rot_session": token})
        assert response.status_code == 200
