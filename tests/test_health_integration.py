"""Integration tests for health check endpoint.

Tests the enhanced /health endpoint with comprehensive metrics:
- System metrics (CPU, memory, disk usage)
- Database health (connection, signal count, size)
- Backup status (count, latest backup info)
- Environment detection (Railway vs local)
- Error handling when components are unavailable
"""
from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from rot.app.server import create_app
from rot.core.config import Settings


@pytest.fixture
async def test_app():
    """Create test app with health endpoint."""
    with TemporaryDirectory() as tmpdir:
        settings = Settings(
            storage={"root": tmpdir},
            web={
                "secret_key": "test-secret-key-for-health-endpoint-tests-32chars",
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
async def test_health_endpoint_basic_structure(test_app):
    """Test that health endpoint returns expected basic structure."""
    client = TestClient(test_app)
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()

    # Basic fields
    assert "status" in data
    assert "version" in data
    assert "uptime_seconds" in data

    assert data["status"] == "healthy"
    assert isinstance(data["version"], str)
    assert isinstance(data["uptime_seconds"], int)
    assert data["uptime_seconds"] >= 0


@pytest.mark.asyncio
async def test_health_database_metrics(test_app):
    """Test that health endpoint returns database metrics."""
    client = TestClient(test_app)

    # Store some test signals first
    db = test_app.state.db
    await db.store_signal(
        ticker="AAPL",
        stance="bullish",
        confidence=0.8,
        event_type="earnings_beat",
        post_id="test123",
        subreddit="wallstreetbets",
        post_title="Test signal",
        reasoning="Test",
    )

    response = client.get("/health")
    data = response.json()

    assert "database" in data
    db_info = data["database"]

    assert "status" in db_info
    assert "signals_stored" in db_info
    assert "size_mb" in db_info

    assert db_info["status"] == "connected"
    assert db_info["signals_stored"] >= 1  # At least our test signal
    assert isinstance(db_info["size_mb"], (int, float))
    assert db_info["size_mb"] > 0


@pytest.mark.asyncio
async def test_health_system_metrics(test_app):
    """Test that health endpoint returns system metrics."""
    client = TestClient(test_app)
    response = client.get("/health")
    data = response.json()

    assert "system" in data
    sys_info = data["system"]

    # Memory metrics
    assert "memory_rss_mb" in sys_info
    assert "memory_percent" in sys_info
    assert isinstance(sys_info["memory_rss_mb"], (int, float))
    assert sys_info["memory_rss_mb"] > 0
    assert isinstance(sys_info["memory_percent"], (int, float))
    assert 0 <= sys_info["memory_percent"] <= 100

    # CPU metrics
    assert "cpu_percent" in sys_info
    assert isinstance(sys_info["cpu_percent"], (int, float))
    assert sys_info["cpu_percent"] >= 0

    # Thread count
    assert "num_threads" in sys_info
    assert isinstance(sys_info["num_threads"], int)
    assert sys_info["num_threads"] > 0

    # Platform info
    assert "python_version" in sys_info
    assert "platform" in sys_info
    assert isinstance(sys_info["python_version"], str)
    assert isinstance(sys_info["platform"], str)
    assert sys_info["platform"] in ["Windows", "Linux", "Darwin"]


@pytest.mark.asyncio
async def test_health_disk_usage_metrics(test_app):
    """Test that health endpoint returns disk usage metrics."""
    client = TestClient(test_app)
    response = client.get("/health")
    data = response.json()

    sys_info = data.get("system", {})

    # Disk metrics may not always be present (depends on system)
    if "disk_usage_percent" in sys_info:
        assert isinstance(sys_info["disk_usage_percent"], (int, float))
        assert 0 <= sys_info["disk_usage_percent"] <= 100

    if "disk_free_gb" in sys_info:
        assert isinstance(sys_info["disk_free_gb"], (int, float))
        assert sys_info["disk_free_gb"] >= 0


@pytest.mark.asyncio
async def test_health_backup_status_no_backups(test_app):
    """Test health endpoint when no backups exist yet."""
    client = TestClient(test_app)
    response = client.get("/health")
    data = response.json()

    assert "backups" in data
    backup_info = data["backups"]

    # Should indicate no backups yet
    assert backup_info.get("count") == 0
    assert backup_info.get("status") == "no_backups_yet"


@pytest.mark.asyncio
async def test_health_backup_status_with_backups(test_app):
    """Test health endpoint when backups exist."""
    from rot.storage.backup import BackupManager

    # Create a backup first
    settings = test_app.state.settings
    backup_mgr = BackupManager(
        db_path=f"{settings.storage.root}/rot.db",
        backup_dir=f"{settings.storage.root}/backups",
    )
    await backup_mgr.create_backup()

    client = TestClient(test_app)
    response = client.get("/health")
    data = response.json()

    backup_info = data["backups"]

    assert "count" in backup_info
    assert "total_size_mb" in backup_info
    assert "latest_backup" in backup_info

    assert backup_info["count"] >= 1
    assert isinstance(backup_info["total_size_mb"], (int, float))
    assert backup_info["total_size_mb"] > 0

    latest = backup_info["latest_backup"]
    assert "filename" in latest
    assert "age_hours" in latest
    assert "size_mb" in latest

    assert isinstance(latest["filename"], str)
    assert isinstance(latest["age_hours"], (int, float))
    assert isinstance(latest["size_mb"], (int, float))
    assert latest["age_hours"] >= 0  # Just created


@pytest.mark.asyncio
async def test_health_environment_detection_local(test_app):
    """Test that health endpoint detects local environment."""
    # Ensure RAILWAY_ENVIRONMENT is not set
    railway_env = os.environ.pop("RAILWAY_ENVIRONMENT", None)

    try:
        client = TestClient(test_app)
        response = client.get("/health")
        data = response.json()

        assert "environment" in data
        env_info = data["environment"]

        assert "deployment" in env_info
        assert env_info["deployment"] == "local"
        assert env_info.get("railway_env") == "n/a"

    finally:
        # Restore original value
        if railway_env:
            os.environ["RAILWAY_ENVIRONMENT"] = railway_env


@pytest.mark.asyncio
async def test_health_environment_detection_railway(test_app):
    """Test that health endpoint detects Railway environment."""
    # Set Railway environment variable
    original_env = os.environ.get("RAILWAY_ENVIRONMENT")
    os.environ["RAILWAY_ENVIRONMENT"] = "production"

    try:
        client = TestClient(test_app)
        response = client.get("/health")
        data = response.json()

        env_info = data.get("environment", {})

        assert env_info.get("deployment") == "railway"
        assert env_info.get("railway_env") == "production"

    finally:
        # Restore original
        if original_env:
            os.environ["RAILWAY_ENVIRONMENT"] = original_env
        else:
            os.environ.pop("RAILWAY_ENVIRONMENT", None)


@pytest.mark.asyncio
async def test_health_database_error_handling(test_app):
    """Test health endpoint when database is unavailable."""
    client = TestClient(test_app)

    # Close database to simulate failure
    await test_app.state.db.close()

    response = client.get("/health")
    data = response.json()

    # Should still return 200 but indicate database issue
    assert response.status_code == 200
    assert "database" in data

    db_info = data["database"]
    # Should show as initializing or error
    assert db_info.get("status") in ["initializing", "error"]
    if "error" in db_info:
        assert isinstance(db_info["error"], str)


@pytest.mark.asyncio
async def test_health_uptime_increases(test_app):
    """Test that uptime increases between calls."""
    import time

    client = TestClient(test_app)

    response1 = client.get("/health")
    uptime1 = response1.json()["uptime_seconds"]

    time.sleep(1)

    response2 = client.get("/health")
    uptime2 = response2.json()["uptime_seconds"]

    assert uptime2 > uptime1
    assert uptime2 - uptime1 >= 1


@pytest.mark.asyncio
async def test_health_response_time(test_app):
    """Test that health endpoint responds quickly."""
    import time

    client = TestClient(test_app)

    start = time.time()
    response = client.get("/health")
    duration = time.time() - start

    assert response.status_code == 200
    # Health check should complete quickly (< 2 seconds)
    assert duration < 2.0


@pytest.mark.asyncio
async def test_health_concurrent_requests(test_app):
    """Test that health endpoint handles concurrent requests."""
    import asyncio

    client = TestClient(test_app)

    async def make_request():
        response = client.get("/health")
        return response.status_code

    # Make 10 concurrent health check requests
    tasks = [make_request() for _ in range(10)]
    results = await asyncio.gather(*tasks)

    # All should succeed
    assert all(code == 200 for code in results)


@pytest.mark.asyncio
async def test_health_database_size_increases(test_app):
    """Test that database size metric increases when data is added."""
    client = TestClient(test_app)
    db = test_app.state.db

    # Get initial size
    response1 = client.get("/health")
    initial_size = response1.json()["database"]["size_mb"]

    # Add significant data
    for i in range(100):
        await db.store_signal(
            ticker=f"TEST{i}",
            stance="bullish",
            confidence=0.8,
            event_type="test",
            post_id=f"test{i}",
            subreddit="test",
            post_title="Test signal" * 100,  # Make it larger
            reasoning="Test reasoning" * 50,
        )

    # Get new size
    response2 = client.get("/health")
    new_size = response2.json()["database"]["size_mb"]

    # Size should have increased
    assert new_size > initial_size


@pytest.mark.asyncio
async def test_health_backup_age_calculation(test_app):
    """Test that backup age is calculated correctly."""
    import time
    from rot.storage.backup import BackupManager

    settings = test_app.state.settings
    backup_mgr = BackupManager(
        db_path=f"{settings.storage.root}/rot.db",
        backup_dir=f"{settings.storage.root}/backups",
    )

    # Create backup and wait
    await backup_mgr.create_backup()
    time.sleep(1)

    client = TestClient(test_app)
    response = client.get("/health")
    data = response.json()

    latest_backup = data["backups"]["latest_backup"]
    age_hours = latest_backup["age_hours"]

    # Should be very recent (< 1 minute = 0.0167 hours)
    assert 0 <= age_hours < 0.02  # Less than ~1 minute old


@pytest.mark.asyncio
async def test_health_json_format(test_app):
    """Test that health endpoint returns valid JSON."""
    import json

    client = TestClient(test_app)
    response = client.get("/health")

    # Should be valid JSON
    assert response.headers["content-type"] == "application/json"

    # Should parse without errors
    data = json.loads(response.text)
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_health_no_authentication_required(test_app):
    """Test that health endpoint doesn't require authentication."""
    client = TestClient(test_app)

    # Make request without any auth headers
    response = client.get("/health")

    # Should succeed without authentication
    assert response.status_code == 200
    assert "status" in response.json()


@pytest.mark.asyncio
async def test_health_cache_headers(test_app):
    """Test that health endpoint has appropriate cache headers."""
    client = TestClient(test_app)
    response = client.get("/health")

    # Health endpoint should not be cached (data changes frequently)
    # FastAPI may set cache-control headers
    if "cache-control" in response.headers:
        cache_control = response.headers["cache-control"]
        # Should either have no-cache or a very short max-age
        assert "no-cache" in cache_control or "max-age=0" in cache_control or "max-age=1" in cache_control
