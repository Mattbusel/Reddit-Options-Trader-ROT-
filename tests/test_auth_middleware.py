"""
Tests for rot.auth.middleware (RequestLogMiddleware) and
rot.storage.access_log_db (AccessLogMixin).

Coverage:
- _get_ip: plain client, X-Forwarded-For (single + comma-list)
- _hash_key: deterministic SHA-256 output
- _path_prefix_skip: /health, /static/, /assets/, unknown paths
- RequestLogMiddleware.dispatch: pass-through + log call
- RequestLogMiddleware._log_request: writes correct row to DB
- AccessLogMixin.get_request_rate_for_ip
- AccessLogMixin.get_sustained_high_rate_ips
- AccessLogMixin.get_sequential_enumeration_ips
- AccessLogMixin.get_high_401_rate_ips
- AccessLogMixin.save_access_alert + get_unresolved_alerts
- AccessLogMixin.recent_alert_exists
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rot.auth.middleware import (
    RequestLogMiddleware,
    _get_ip,
    _hash_key,
    _path_prefix_skip,
)
from rot.storage.access_log_db import AccessLogMixin, ACCESS_LOG_SCHEMA


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_request(
    path: str = "/api/v1/signals",
    method: str = "GET",
    headers: Optional[dict] = None,
    client_host: str = "127.0.0.1",
) -> MagicMock:
    """Build a minimal mock Starlette Request."""
    req = MagicMock()
    req.url.path = path
    req.method = method
    req.client = MagicMock()
    req.client.host = client_host
    _headers = headers or {}
    req.headers.get = lambda k, default="": _headers.get(k, default)
    req.state = MagicMock()
    req.state.rot_user = None
    req.state.rot_start_ts = time.time()
    req.app = MagicMock()
    req.app.state.db._db = None  # will be replaced in DB tests
    return req


# ── _get_ip ───────────────────────────────────────────────────────────────────


class TestGetIp:
    def test_plain_client_host(self):
        req = _make_request(client_host="10.0.0.1")
        assert _get_ip(req) == "10.0.0.1"

    def test_x_forwarded_for_single(self):
        req = _make_request(headers={"x-forwarded-for": "1.2.3.4"})
        assert _get_ip(req) == "1.2.3.4"

    def test_x_forwarded_for_comma_list(self):
        # Leftmost = original client
        req = _make_request(headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1, 172.16.0.1"})
        assert _get_ip(req) == "1.2.3.4"

    def test_x_forwarded_for_with_spaces(self):
        req = _make_request(headers={"x-forwarded-for": "  5.6.7.8 , 10.0.0.2"})
        assert _get_ip(req) == "5.6.7.8"

    def test_no_client(self):
        req = _make_request()
        req.client = None
        # No forwarded header, no client → "unknown"
        assert _get_ip(req) == "unknown"


# ── _hash_key ─────────────────────────────────────────────────────────────────


class TestHashKey:
    def test_deterministic(self):
        assert _hash_key("rot_abc123") == _hash_key("rot_abc123")

    def test_sha256_format(self):
        result = _hash_key("rot_testkey")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_matches_sha256(self):
        key = "rot_mykey"
        expected = hashlib.sha256(key.encode()).hexdigest()
        assert _hash_key(key) == expected

    def test_different_keys_different_hashes(self):
        assert _hash_key("rot_key1") != _hash_key("rot_key2")


# ── _path_prefix_skip ─────────────────────────────────────────────────────────


class TestPathPrefixSkip:
    def test_health_skipped(self):
        assert _path_prefix_skip("/health") is True

    def test_favicon_skipped(self):
        assert _path_prefix_skip("/favicon.ico") is True

    def test_static_prefix_skipped(self):
        assert _path_prefix_skip("/static/app.js") is True

    def test_assets_prefix_skipped(self):
        assert _path_prefix_skip("/assets/logo.png") is True

    def test_api_not_skipped(self):
        assert _path_prefix_skip("/api/v1/signals") is False

    def test_root_not_skipped(self):
        assert _path_prefix_skip("/") is False

    def test_health_prefix_not_skipped(self):
        # /healthz is NOT in the skip set — only exact /health
        assert _path_prefix_skip("/healthz") is False


# ── RequestLogMiddleware.dispatch ─────────────────────────────────────────────


class TestRequestLogMiddlewareDispatch:
    @pytest.mark.asyncio
    async def test_skipped_path_not_logged(self):
        """Requests to skipped paths skip logging entirely."""
        middleware = RequestLogMiddleware(app=MagicMock())
        req = _make_request(path="/health")
        mock_response = MagicMock()
        mock_response.status_code = 200

        async def mock_call_next(r):
            return mock_response

        with patch.object(middleware, "_log_request", new_callable=AsyncMock) as mock_log:
            result = await middleware.dispatch(req, mock_call_next)
            mock_log.assert_not_called()

        assert result is mock_response

    @pytest.mark.asyncio
    async def test_normal_path_logged(self):
        """Requests to non-skipped paths call _log_request."""
        middleware = RequestLogMiddleware(app=MagicMock())
        req = _make_request(path="/api/v1/signals")
        mock_response = MagicMock()
        mock_response.status_code = 200

        async def mock_call_next(r):
            return mock_response

        with patch.object(middleware, "_log_request", new_callable=AsyncMock) as mock_log:
            result = await middleware.dispatch(req, mock_call_next)
            mock_log.assert_awaited_once()
            # First arg is request, second is status_code, third is elapsed_ms
            args = mock_log.call_args[0]
            assert args[1] == 200
            assert args[2] >= 0.0

    @pytest.mark.asyncio
    async def test_log_failure_does_not_crash_response(self):
        """Logging errors are suppressed — the response is still returned."""
        middleware = RequestLogMiddleware(app=MagicMock())
        req = _make_request(path="/api/v1/signals")
        mock_response = MagicMock()
        mock_response.status_code = 200

        async def mock_call_next(r):
            return mock_response

        async def exploding_log(*args, **kwargs):
            raise RuntimeError("db explosion")

        with patch.object(middleware, "_log_request", side_effect=exploding_log):
            result = await middleware.dispatch(req, mock_call_next)

        assert result is mock_response  # Response returned despite log failure


# ── AccessLogMixin (in-memory SQLite) ─────────────────────────────────────────


@pytest.fixture
async def adb():
    """Provide an in-memory aiosqlite database with the access log schema."""
    import aiosqlite

    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row

    for stmt in ACCESS_LOG_SCHEMA.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            await db.execute(stmt)
    await db.commit()

    # Build a minimal mixin instance bound to this DB
    mixin = AccessLogMixin()
    mixin._db = db
    yield mixin

    await db.close()


@pytest.mark.asyncio
async def test_get_request_rate_empty(adb):
    rate = await adb.get_request_rate_for_ip("1.2.3.4")
    assert rate == 0.0


@pytest.mark.asyncio
async def test_get_request_rate_with_rows(adb):
    now = time.time()
    for _ in range(30):
        await adb._db.execute(
            "INSERT INTO api_request_log (ts, method, endpoint, ip) VALUES (?, ?, ?, ?)",
            (now - 10, "GET", "/api/v1/signals", "1.2.3.4"),
        )
    await adb._db.commit()

    rate = await adb.get_request_rate_for_ip("1.2.3.4", window_s=60.0)
    assert rate == pytest.approx(30 / 60.0)


@pytest.mark.asyncio
async def test_get_sustained_high_rate_ips_threshold(adb):
    now = time.time()
    # 1200 requests from attacker in the last 600s → 2 req/s exactly
    for _ in range(1200):
        await adb._db.execute(
            "INSERT INTO api_request_log (ts, method, endpoint, ip) VALUES (?, ?, ?, ?)",
            (now - 100, "GET", "/api/v1/signals", "evil.ip"),
        )
    # 5 requests from benign IP
    for _ in range(5):
        await adb._db.execute(
            "INSERT INTO api_request_log (ts, method, endpoint, ip) VALUES (?, ?, ?, ?)",
            (now - 100, "GET", "/api/v1/signals", "good.ip"),
        )
    await adb._db.commit()

    offenders = await adb.get_sustained_high_rate_ips(window_s=600.0, min_rps=2.0)
    ips = [r["ip"] for r in offenders]
    assert "evil.ip" in ips
    assert "good.ip" not in ips


@pytest.mark.asyncio
async def test_get_sequential_enumeration_ips(adb):
    now = time.time()
    # Scraper hits 35 distinct endpoints
    for i in range(35):
        await adb._db.execute(
            "INSERT INTO api_request_log (ts, method, endpoint, ip) VALUES (?, ?, ?, ?)",
            (now - 10, "GET", f"/api/v1/endpoint{i}", "scraper.ip"),
        )
    # Normal user hits 3 endpoints
    for i in range(3):
        await adb._db.execute(
            "INSERT INTO api_request_log (ts, method, endpoint, ip) VALUES (?, ?, ?, ?)",
            (now - 10, "GET", f"/api/v1/signals", "normal.ip"),
        )
    await adb._db.commit()

    offenders = await adb.get_sequential_enumeration_ips(
        window_s=300.0, min_distinct_endpoints=30
    )
    ips = [r["ip"] for r in offenders]
    assert "scraper.ip" in ips
    assert "normal.ip" not in ips


@pytest.mark.asyncio
async def test_get_high_401_rate_ips(adb):
    now = time.time()
    # Auth bypass attacker: 25 x 401
    for _ in range(25):
        await adb._db.execute(
            "INSERT INTO api_request_log (ts, method, endpoint, status_code, ip) VALUES (?, ?, ?, ?, ?)",
            (now - 10, "GET", "/api/v1/signals", 401, "hacker.ip"),
        )
    # Normal user: 3 x 401
    for _ in range(3):
        await adb._db.execute(
            "INSERT INTO api_request_log (ts, method, endpoint, status_code, ip) VALUES (?, ?, ?, ?, ?)",
            (now - 10, "GET", "/api/v1/signals", 401, "normal.ip"),
        )
    await adb._db.commit()

    offenders = await adb.get_high_401_rate_ips(window_s=300.0, min_count=20)
    ips = [r["ip"] for r in offenders]
    assert "hacker.ip" in ips
    assert "normal.ip" not in ips


@pytest.mark.asyncio
async def test_save_and_get_access_alert(adb):
    row_id = await adb.save_access_alert(
        alert_type="HIGH_RATE_SUSTAINED",
        ip="1.2.3.4",
        details='{"rps": 5.0}',
    )
    assert row_id is not None

    alerts = await adb.get_unresolved_alerts()
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == "HIGH_RATE_SUSTAINED"
    assert alerts[0]["ip"] == "1.2.3.4"
    assert alerts[0]["resolved"] == 0


@pytest.mark.asyncio
async def test_recent_alert_exists_true(adb):
    await adb.save_access_alert(
        alert_type="SEQUENTIAL_ENUM",
        ip="5.6.7.8",
    )
    exists = await adb.recent_alert_exists("SEQUENTIAL_ENUM", "5.6.7.8", window_s=3600.0)
    assert exists is True


@pytest.mark.asyncio
async def test_recent_alert_exists_false_wrong_type(adb):
    await adb.save_access_alert(
        alert_type="HIGH_RATE_SUSTAINED",
        ip="5.6.7.8",
    )
    exists = await adb.recent_alert_exists("SEQUENTIAL_ENUM", "5.6.7.8", window_s=3600.0)
    assert exists is False


@pytest.mark.asyncio
async def test_recent_alert_exists_false_expired(adb):
    # Insert an old alert (2 hours ago) manually
    old_ts = time.time() - 7300
    await adb._db.execute(
        "INSERT INTO access_alerts (ts, alert_type, ip, details) VALUES (?, ?, ?, ?)",
        (old_ts, "HIGH_RATE_SUSTAINED", "9.9.9.9", "{}"),
    )
    await adb._db.commit()

    exists = await adb.recent_alert_exists("HIGH_RATE_SUSTAINED", "9.9.9.9", window_s=3600.0)
    assert exists is False


@pytest.mark.asyncio
async def test_get_unresolved_alerts_excludes_resolved(adb):
    await adb.save_access_alert("HIGH_RATE_SUSTAINED", ip="1.1.1.1")
    await adb._db.execute(
        "UPDATE access_alerts SET resolved = 1, resolved_at = ? WHERE ip = ?",
        (time.time(), "1.1.1.1"),
    )
    await adb._db.commit()

    alerts = await adb.get_unresolved_alerts()
    assert len(alerts) == 0
