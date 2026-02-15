"""Tests for authentication rate limiting (brute-force protection).

Tests database-backed auth rate limiting for multi-instance deployments.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rot.web.rate_limit import check_auth_rate_limit
from rot.storage.database import Database
from fastapi import HTTPException


@pytest.fixture
async def db():
    """Create a temporary test database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        database = Database(db_path=str(db_path))
        await database.connect()
        yield database
        await database.close()


@pytest.fixture
def mock_request(db):
    """Create a mock FastAPI request with a client IP and database."""
    request = MagicMock()
    request.client.host = "192.168.1.1"
    request.app.state.db = db
    return request


async def test_login_rate_limit_allows_first_five_attempts(mock_request):
    """Test that 5 login attempts are allowed within 15 minutes."""
    # First 5 attempts should pass
    for i in range(5):
        await check_auth_rate_limit(mock_request, "login")


async def test_login_rate_limit_blocks_sixth_attempt(mock_request):
    """Test that 6th login attempt within 15 minutes is blocked."""
    # First 5 attempts pass
    for i in range(5):
        await check_auth_rate_limit(mock_request, "login")

    # 6th attempt should be blocked
    with pytest.raises(HTTPException) as exc_info:
        await check_auth_rate_limit(mock_request, "login")

    assert exc_info.value.status_code == 429
    assert "Too many login attempts" in exc_info.value.detail
    assert "Retry-After" in exc_info.value.headers


async def test_register_rate_limit_allows_three_attempts(mock_request):
    """Test that 3 register attempts are allowed within 1 hour."""
    # First 3 attempts should pass
    for i in range(3):
        await check_auth_rate_limit(mock_request, "register")


async def test_register_rate_limit_blocks_fourth_attempt(mock_request):
    """Test that 4th register attempt within 1 hour is blocked."""
    # First 3 attempts pass
    for i in range(3):
        await check_auth_rate_limit(mock_request, "register")

    # 4th attempt should be blocked
    with pytest.raises(HTTPException) as exc_info:
        await check_auth_rate_limit(mock_request, "register")

    assert exc_info.value.status_code == 429
    assert "Too many register attempts" in exc_info.value.detail


async def test_api_key_rate_limit_allows_three_attempts(mock_request):
    """Test that 3 API key attempts are allowed within 1 hour."""
    # First 3 attempts should pass
    for i in range(3):
        await check_auth_rate_limit(mock_request, "api-key")


async def test_api_key_rate_limit_blocks_fourth_attempt(mock_request):
    """Test that 4th API key attempt within 1 hour is blocked."""
    # First 3 attempts pass
    for i in range(3):
        await check_auth_rate_limit(mock_request, "api-key")

    # 4th attempt should be blocked
    with pytest.raises(HTTPException) as exc_info:
        await check_auth_rate_limit(mock_request, "api-key")

    assert exc_info.value.status_code == 429
    assert "Too many api-key attempts" in exc_info.value.detail


async def test_different_ips_have_independent_limits(db):
    """Test that different IPs have independent rate limits."""
    request1 = MagicMock()
    request1.client.host = "192.168.1.1"
    request1.app.state.db = db

    request2 = MagicMock()
    request2.client.host = "192.168.1.2"
    request2.app.state.db = db

    # IP 1: Use up all 5 login attempts
    for i in range(5):
        await check_auth_rate_limit(request1, "login")

    # IP 1: 6th attempt should be blocked
    with pytest.raises(HTTPException):
        await check_auth_rate_limit(request1, "login")

    # IP 2: Should still have all 5 attempts available
    for i in range(5):
        await check_auth_rate_limit(request2, "login")


async def test_retry_after_header_is_set(mock_request):
    """Test that Retry-After header is present and reasonable."""
    # Use up all attempts
    for i in range(5):
        await check_auth_rate_limit(mock_request, "login")

    # Next attempt should have Retry-After header
    with pytest.raises(HTTPException) as exc_info:
        await check_auth_rate_limit(mock_request, "login")

    retry_after = int(exc_info.value.headers["Retry-After"])
    # Should be between 1 second and 15 minutes (900 seconds)
    assert 1 <= retry_after <= 900


async def test_different_endpoints_have_separate_limits(mock_request):
    """Test that login and register have independent rate limits."""
    # Use up login attempts
    for i in range(5):
        await check_auth_rate_limit(mock_request, "login")

    # Login should be blocked
    with pytest.raises(HTTPException):
        await check_auth_rate_limit(mock_request, "login")

    # Register should still work (different endpoint)
    for i in range(3):
        await check_auth_rate_limit(mock_request, "register")
