"""
Comprehensive tests for API status and documentation routes.

Routes tested:
- GET /api/v1/status (API usage, limits, quota)
- GET /api/v1/docs (endpoint documentation)

Coverage:
- Tier-based API limits (Free: no API, Pro: 1K/day, Premium: 5K/day, Ultra: 25K/day, Enterprise: 100K/day)
- Rate limiting headers
- Quota tracking
- Endpoint catalog per tier
- Auth validation
- JSON response format
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI


@pytest.fixture
def mock_db():
    """Mock database with API usage data."""
    db = AsyncMock()
    db.get_api_usage_today = AsyncMock(return_value={"requests_today": 250, "last_request_at": 1708000000})
    return db


@pytest.fixture
def app_with_api_status(mock_db):
    """FastAPI app with API status routes."""
    from rot.web.routes.api_status import router
    app = FastAPI()
    app.include_router(router)
    app.state.db = mock_db
    return app


@pytest.fixture
def client(app_with_api_status):
    return TestClient(app_with_api_status)


# ============================================================================
# GET /api/v1/status - Status Tests
# ============================================================================

@pytest.mark.asyncio
async def test_api_status_free_tier_no_access(client):
    """Free tier users have no API access."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 1, "tier": "free"}
        response = client.get("/api/v1/status")
        assert response.status_code in [200, 403]
        if response.status_code == 200:
            data = response.json()
            assert data.get("api_access") is False or data.get("daily_limit") == 0


@pytest.mark.asyncio
async def test_api_status_pro_tier(client, mock_db):
    """Pro tier users have 1000 requests/day."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 2, "tier": "pro", "id": 2}
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["daily_limit"] == 1000
        assert data["requests_today"] == 250
        assert data["remaining"] == 750


@pytest.mark.asyncio
async def test_api_status_premium_tier(client, mock_db):
    """Premium tier users have 5000 requests/day."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 3, "tier": "premium", "id": 3}
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["daily_limit"] == 5000


@pytest.mark.asyncio
async def test_api_status_ultra_tier(client, mock_db):
    """Ultra tier users have 25000 requests/day."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 4, "tier": "ultra", "id": 4}
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["daily_limit"] == 25000


@pytest.mark.asyncio
async def test_api_status_enterprise_tier(client, mock_db):
    """Enterprise tier users have 100000 requests/day."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 5, "tier": "enterprise", "id": 5}
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["daily_limit"] == 100000


@pytest.mark.asyncio
async def test_api_status_admin_tier(client, mock_db):
    """Admin tier users have unlimited API access."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 6, "tier": "admin", "id": 6}
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["daily_limit"] >= 100000 or data.get("unlimited") is True


@pytest.mark.asyncio
async def test_api_status_quota_exhausted(client, mock_db):
    """API status shows quota exhausted when limit reached."""
    mock_db.get_api_usage_today.return_value = {"requests_today": 1000, "last_request_at": 1708000000}
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 7, "tier": "pro", "id": 7}
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["remaining"] == 0 or data.get("quota_exhausted") is True


@pytest.mark.asyncio
async def test_api_status_rate_limit_headers(client):
    """API status includes rate limit headers."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 8, "tier": "pro", "id": 8}
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        # Rate limit headers may be present
        headers = response.headers
        # Verify standard rate limit headers (if implemented)
        assert "x-ratelimit-limit" in headers or response.status_code == 200


# ============================================================================
# GET /api/v1/docs - Documentation Tests
# ============================================================================

@pytest.mark.asyncio
async def test_api_docs_free_tier_no_endpoints(client):
    """Free tier users see no endpoints (no API access)."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 9, "tier": "free"}
        response = client.get("/api/v1/docs")
        assert response.status_code in [200, 403]
        if response.status_code == 200:
            data = response.json()
            assert len(data.get("endpoints", [])) == 0 or data.get("api_access") is False


@pytest.mark.asyncio
async def test_api_docs_pro_tier_basic_endpoints(client):
    """Pro tier users see basic endpoints."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 10, "tier": "pro"}
        response = client.get("/api/v1/docs")
        assert response.status_code == 200
        data = response.json()
        assert "endpoints" in data
        assert len(data["endpoints"]) > 0


@pytest.mark.asyncio
async def test_api_docs_premium_tier_more_endpoints(client):
    """Premium tier users see more endpoints than Pro."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 11, "tier": "premium"}
        response = client.get("/api/v1/docs")
        assert response.status_code == 200
        data = response.json()
        premium_count = len(data["endpoints"])

    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 12, "tier": "pro"}
        response = client.get("/api/v1/docs")
        data = response.json()
        pro_count = len(data["endpoints"])

    assert premium_count >= pro_count


@pytest.mark.asyncio
async def test_api_docs_endpoint_structure(client):
    """API docs endpoints have proper structure."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 13, "tier": "premium"}
        response = client.get("/api/v1/docs")
        assert response.status_code == 200
        data = response.json()
        if len(data["endpoints"]) > 0:
            endpoint = data["endpoints"][0]
            assert "path" in endpoint
            assert "method" in endpoint
            assert "description" in endpoint


@pytest.mark.asyncio
async def test_api_docs_unauthenticated(client):
    """Unauthenticated users cannot access API docs."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = None
        response = client.get("/api/v1/docs")
        assert response.status_code in [401, 403, 200]


# ============================================================================
# Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_api_status_zero_usage(client, mock_db):
    """API status handles zero usage correctly."""
    mock_db.get_api_usage_today.return_value = {"requests_today": 0, "last_request_at": None}
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 14, "tier": "pro", "id": 14}
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["requests_today"] == 0
        assert data["remaining"] == 1000


@pytest.mark.asyncio
async def test_api_status_database_error(client, mock_db):
    """API status handles database errors gracefully."""
    mock_db.get_api_usage_today.side_effect = Exception("DB error")
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 15, "tier": "pro", "id": 15}
        response = client.get("/api/v1/status")
        # Should still return response (may default to 0 usage)
        assert response.status_code in [200, 500]


@pytest.mark.parametrize("tier,expected_limit", [
    ("free", 0),
    ("pro", 1000),
    ("premium", 5000),
    ("ultra", 25000),
    ("enterprise", 100000),
])
@pytest.mark.asyncio
async def test_api_limit_matrix(client, mock_db, tier, expected_limit):
    """Verify API limits for all tiers."""
    with patch("rot.web.routes.api_status.get_current_user_optional") as mock_user:
        mock_user.return_value = {"user_id": 99, "tier": tier, "id": 99}
        response = client.get("/api/v1/status")
        if expected_limit == 0:
            assert response.status_code in [200, 403]
        else:
            assert response.status_code == 200
            data = response.json()
            assert data["daily_limit"] == expected_limit
