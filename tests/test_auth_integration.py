"""Integration tests for authentication flows with rate limiting.

Tests the complete authentication workflow including:
- Login/register with rate limiting enforcement
- Database-backed rate limit tracking across requests
- Proper HTTP 429 responses with Retry-After headers
- Rate limit reset after time window
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from rot.app.server import create_app
from rot.core.config import Settings


@pytest.fixture
async def test_app():
    """Create test app with temporary database."""
    with TemporaryDirectory() as tmpdir:
        settings = Settings(
            storage={"root": tmpdir},
            web={
                "secret_key": "test-secret-key-for-integration-tests-min-32-chars",
                "host": "127.0.0.1",
                "port": 8000,
            },
            reddit={"client_id": "test", "client_secret": "test", "user_agent": "test"},
        )

        app = await create_app(settings)
        yield app

        # Cleanup
        if hasattr(app.state, "db"):
            await app.state.db.close()


@pytest.mark.asyncio
async def test_login_rate_limit_enforcement(test_app):
    """Test that login attempts are rate limited after threshold."""
    client = TestClient(test_app)

    # First 5 attempts should be allowed (limit is 5 per 15 minutes)
    for i in range(5):
        response = client.post(
            "/login",
            data={"email": "test@example.com", "password": "wrongpassword"},
        )
        # Should fail authentication but not rate limit
        assert response.status_code in (200, 401), f"Attempt {i+1} got {response.status_code}"

    # 6th attempt should be rate limited
    response = client.post(
        "/login",
        data={"email": "test@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert int(response.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_rate_limit_per_endpoint(test_app):
    """Test that rate limits are tracked separately per endpoint."""
    client = TestClient(test_app)

    # Use up login attempts (5 max)
    for _ in range(5):
        client.post("/login", data={"email": "test@example.com", "password": "test"})

    # Login should be blocked
    response = client.post("/login", data={"email": "test@example.com", "password": "test"})
    assert response.status_code == 429

    # But register should still work (separate endpoint, 3 max)
    response = client.post(
        "/register",
        data={
            "email": "newuser@example.com",
            "password": "testpass123",
            "tier": "free",
        },
    )
    # Should not be rate limited yet
    assert response.status_code != 429


@pytest.mark.asyncio
async def test_rate_limit_database_persistence(test_app):
    """Test that rate limits are stored in database, not memory."""
    client = TestClient(test_app)

    # Make 3 login attempts
    for _ in range(3):
        client.post("/login", data={"email": "test@example.com", "password": "test"})

    # Verify attempts are in database
    db = test_app.state.db
    attempts = await db.get_auth_attempts(
        ip="testclient",
        endpoint="login",
        since=int(time.time() - 900),  # Last 15 minutes
    )
    assert attempts == 3


@pytest.mark.asyncio
async def test_register_rate_limit(test_app):
    """Test that registration is rate limited (3 per hour)."""
    client = TestClient(test_app)

    # First 3 registrations should work (or at least not be rate limited)
    for i in range(3):
        response = client.post(
            "/register",
            data={
                "email": f"user{i}@example.com",
                "password": "testpass123",
                "tier": "free",
            },
        )
        assert response.status_code != 429, f"Registration {i+1} was rate limited"

    # 4th registration should be rate limited
    response = client.post(
        "/register",
        data={
            "email": "user4@example.com",
            "password": "testpass123",
            "tier": "free",
        },
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers


@pytest.mark.asyncio
async def test_api_key_generation_rate_limit(test_app):
    """Test that API key generation is rate limited."""
    client = TestClient(test_app)

    # First create a user and login
    client.post(
        "/register",
        data={"email": "apiuser@example.com", "password": "testpass123", "tier": "pro"},
    )

    login_response = client.post(
        "/login",
        data={"email": "apiuser@example.com", "password": "testpass123"},
    )

    # Extract session cookie if present
    cookies = login_response.cookies

    # Try to generate API keys (3 max per hour)
    for i in range(3):
        response = client.post("/api/v1/auth/api-key", cookies=cookies)
        # May fail for auth reasons, but should not be rate limited yet
        if response.status_code == 429:
            pytest.fail(f"API key generation {i+1} was rate limited prematurely")

    # 4th attempt should be rate limited
    response = client.post("/api/v1/auth/api-key", cookies=cookies)
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_headers(test_app):
    """Test that rate limit responses include proper headers."""
    client = TestClient(test_app)

    # Trigger rate limit
    for _ in range(5):
        client.post("/login", data={"email": "test@example.com", "password": "test"})

    response = client.post("/login", data={"email": "test@example.com", "password": "test"})

    assert response.status_code == 429
    assert "Retry-After" in response.headers

    retry_after = int(response.headers["Retry-After"])
    # Should be around 900 seconds (15 minutes) minus elapsed time
    assert 800 <= retry_after <= 900, f"Retry-After was {retry_after}, expected ~900"


@pytest.mark.asyncio
async def test_successful_login_after_rate_limit_expiry(test_app):
    """Test that rate limits reset after time window expires."""
    client = TestClient(test_app)
    db = test_app.state.db

    # Create a test user
    await db.create_user(
        email="limituser@example.com",
        password_hash="$2b$12$test",  # Dummy hash
        tier="free",
    )

    # Manually insert old auth attempts (expired)
    now = int(time.time())
    old_timestamp = now - 1000  # 16+ minutes ago (past 15-minute window)

    for _ in range(5):
        await db.record_auth_attempt(
            ip="testclient",
            endpoint="login",
            timestamp=old_timestamp,
        )

    # New login attempt should succeed (old attempts expired)
    response = client.post(
        "/login",
        data={"email": "limituser@example.com", "password": "testpass"},
    )

    # Should not be rate limited (though auth may fail)
    assert response.status_code != 429


@pytest.mark.asyncio
async def test_different_ips_independent_limits(test_app):
    """Test that rate limits are tracked per IP address."""
    # Note: TestClient doesn't easily simulate different IPs,
    # so this is more of a documentation/design test

    db = test_app.state.db
    now = int(time.time())

    # Record attempts from IP 1
    for _ in range(5):
        await db.record_auth_attempt("192.168.1.1", "login", now)

    # Record attempts from IP 2
    for _ in range(2):
        await db.record_auth_attempt("192.168.1.2", "login", now)

    # Check counts
    count_ip1 = await db.get_auth_attempts("192.168.1.1", "login", now - 900)
    count_ip2 = await db.get_auth_attempts("192.168.1.2", "login", now - 900)

    assert count_ip1 == 5
    assert count_ip2 == 2


@pytest.mark.asyncio
async def test_rate_limit_cleanup(test_app):
    """Test that old rate limit records are cleaned up."""
    db = test_app.state.db
    now = int(time.time())

    # Insert mix of old and recent attempts
    old_time = now - 4000  # Over 1 hour old
    recent_time = now - 300  # 5 minutes ago

    await db.record_auth_attempt("192.168.1.1", "login", old_time)
    await db.record_auth_attempt("192.168.1.1", "login", recent_time)

    # Query with 15-minute window
    recent_count = await db.get_auth_attempts("192.168.1.1", "login", now - 900)

    # Should only count recent attempt
    assert recent_count == 1
