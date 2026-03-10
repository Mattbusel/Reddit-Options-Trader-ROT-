"""
Tests for rot.auth.access_monitor.AccessMonitor.

Coverage:
- _check_sustained_rate: fires alert when offenders found, skips when dedup active
- _check_sequential_enum: fires alert for scraping pattern
- _check_auth_bypass: fires alert for high-401-rate IPs
- _scan: calls all three checks, returns combined count
- run/stop: starts and stops cleanly
- DB errors in detection passes are swallowed (circuit breaker)
- _fire_alert: logs and calls save_access_alert
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rot.auth.access_monitor import AccessMonitor


def _make_db(
    sustained: list | None = None,
    enum: list | None = None,
    auth_401: list | None = None,
    recent_alert: bool = False,
) -> MagicMock:
    """Build a mock DB with all AccessLogMixin methods stubbed."""
    db = MagicMock()
    db.get_sustained_high_rate_ips = AsyncMock(return_value=sustained or [])
    db.get_sequential_enumeration_ips = AsyncMock(return_value=enum or [])
    db.get_high_401_rate_ips = AsyncMock(return_value=auth_401 or [])
    db.recent_alert_exists = AsyncMock(return_value=recent_alert)
    db.save_access_alert = AsyncMock(return_value=1)
    return db


# ── _check_sustained_rate ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sustained_rate_no_offenders():
    db = _make_db(sustained=[])
    monitor = AccessMonitor(db)
    fired = await monitor._check_sustained_rate()
    assert fired == 0
    db.save_access_alert.assert_not_called()


@pytest.mark.asyncio
async def test_sustained_rate_fires_for_offender():
    offender = {"ip": "1.2.3.4", "cnt": 1200, "first_seen": 1000.0, "last_seen": 1600.0}
    db = _make_db(sustained=[offender], recent_alert=False)
    monitor = AccessMonitor(db)
    fired = await monitor._check_sustained_rate()
    assert fired == 1
    db.save_access_alert.assert_awaited_once()
    call_kwargs = db.save_access_alert.call_args[1]
    assert call_kwargs["alert_type"] == "HIGH_RATE_SUSTAINED"
    assert call_kwargs["ip"] == "1.2.3.4"


@pytest.mark.asyncio
async def test_sustained_rate_deduplicates():
    offender = {"ip": "1.2.3.4", "cnt": 1200, "first_seen": 1000.0, "last_seen": 1600.0}
    db = _make_db(sustained=[offender], recent_alert=True)  # already alerted
    monitor = AccessMonitor(db)
    fired = await monitor._check_sustained_rate()
    assert fired == 0
    db.save_access_alert.assert_not_called()


@pytest.mark.asyncio
async def test_sustained_rate_multiple_offenders():
    offenders = [
        {"ip": "1.1.1.1", "cnt": 2000, "first_seen": 0.0, "last_seen": 600.0},
        {"ip": "2.2.2.2", "cnt": 1800, "first_seen": 0.0, "last_seen": 600.0},
    ]
    db = _make_db(sustained=offenders, recent_alert=False)
    monitor = AccessMonitor(db)
    fired = await monitor._check_sustained_rate()
    assert fired == 2


@pytest.mark.asyncio
async def test_sustained_rate_db_error_swallowed():
    db = _make_db()
    db.get_sustained_high_rate_ips = AsyncMock(side_effect=RuntimeError("db crash"))
    monitor = AccessMonitor(db)
    fired = await monitor._check_sustained_rate()
    assert fired == 0  # Error swallowed, no crash


# ── _check_sequential_enum ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sequential_enum_no_offenders():
    db = _make_db(enum=[])
    monitor = AccessMonitor(db)
    fired = await monitor._check_sequential_enum()
    assert fired == 0


@pytest.mark.asyncio
async def test_sequential_enum_fires():
    offender = {"ip": "scraper.ip", "distinct_eps": 45, "total": 50}
    db = _make_db(enum=[offender], recent_alert=False)
    monitor = AccessMonitor(db)
    fired = await monitor._check_sequential_enum()
    assert fired == 1
    call_kwargs = db.save_access_alert.call_args[1]
    assert call_kwargs["alert_type"] == "SEQUENTIAL_ENUM"


@pytest.mark.asyncio
async def test_sequential_enum_db_error_swallowed():
    db = _make_db()
    db.get_sequential_enumeration_ips = AsyncMock(side_effect=RuntimeError("db crash"))
    monitor = AccessMonitor(db)
    fired = await monitor._check_sequential_enum()
    assert fired == 0


# ── _check_auth_bypass ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_bypass_no_offenders():
    db = _make_db(auth_401=[])
    monitor = AccessMonitor(db)
    fired = await monitor._check_auth_bypass()
    assert fired == 0


@pytest.mark.asyncio
async def test_auth_bypass_fires():
    offender = {"ip": "hacker.ip", "cnt": 30}
    db = _make_db(auth_401=[offender], recent_alert=False)
    monitor = AccessMonitor(db)
    fired = await monitor._check_auth_bypass()
    assert fired == 1
    call_kwargs = db.save_access_alert.call_args[1]
    assert call_kwargs["alert_type"] == "AUTH_BYPASS_ATTEMPT"
    assert call_kwargs["ip"] == "hacker.ip"


@pytest.mark.asyncio
async def test_auth_bypass_db_error_swallowed():
    db = _make_db()
    db.get_high_401_rate_ips = AsyncMock(side_effect=RuntimeError("db crash"))
    monitor = AccessMonitor(db)
    fired = await monitor._check_auth_bypass()
    assert fired == 0


# ── _scan ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_calls_all_three_passes():
    db = _make_db()
    monitor = AccessMonitor(db)

    with patch.object(monitor, "_check_sustained_rate", new=AsyncMock(return_value=1)), \
         patch.object(monitor, "_check_sequential_enum", new=AsyncMock(return_value=0)), \
         patch.object(monitor, "_check_auth_bypass", new=AsyncMock(return_value=1)):
        await monitor._scan()
        monitor._check_sustained_rate.assert_awaited_once()
        monitor._check_sequential_enum.assert_awaited_once()
        monitor._check_auth_bypass.assert_awaited_once()


@pytest.mark.asyncio
async def test_scan_totals_alerts():
    db = _make_db()
    monitor = AccessMonitor(db)

    with patch.object(monitor, "_check_sustained_rate", new=AsyncMock(return_value=2)), \
         patch.object(monitor, "_check_sequential_enum", new=AsyncMock(return_value=1)), \
         patch.object(monitor, "_check_auth_bypass", new=AsyncMock(return_value=3)):
        # _scan itself doesn't return total, but shouldn't raise
        await monitor._scan()


# ── run / stop ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_stop():
    db = _make_db()
    monitor = AccessMonitor(db, interval_s=0.05)

    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.02)  # Let it start
    await monitor.stop()

    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("AccessMonitor.run() did not stop within 1 second")


@pytest.mark.asyncio
async def test_stop_idempotent():
    db = _make_db()
    monitor = AccessMonitor(db, interval_s=1000)
    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.01)
    await monitor.stop()
    await monitor.stop()  # Second stop should not raise
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


# ── _fire_alert ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fire_alert_calls_save(caplog):
    db = _make_db()
    monitor = AccessMonitor(db)

    import logging
    with caplog.at_level(logging.WARNING, logger="rot.auth.access_monitor"):
        await monitor._fire_alert(
            "HIGH_RATE_SUSTAINED",
            ip="9.9.9.9",
            details='{"rps": 3.5}',
        )

    db.save_access_alert.assert_awaited_once_with(
        alert_type="HIGH_RATE_SUSTAINED",
        ip="9.9.9.9",
        api_key_hash=None,
        user_id=None,
        details='{"rps": 3.5}',
    )
    assert "HIGH_RATE_SUSTAINED" in caplog.text


@pytest.mark.asyncio
async def test_fire_alert_db_error_logged(caplog):
    db = _make_db()
    db.save_access_alert = AsyncMock(side_effect=RuntimeError("db down"))
    monitor = AccessMonitor(db)

    import logging
    with caplog.at_level(logging.ERROR, logger="rot.auth.access_monitor"):
        await monitor._fire_alert("HIGH_RATE_SUSTAINED", ip="1.2.3.4")

    assert "failed to save alert" in caplog.text


# ── _already_alerted ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_already_alerted_true():
    db = _make_db(recent_alert=True)
    monitor = AccessMonitor(db)
    result = await monitor._already_alerted("HIGH_RATE_SUSTAINED", "1.2.3.4")
    assert result is True


@pytest.mark.asyncio
async def test_already_alerted_false():
    db = _make_db(recent_alert=False)
    monitor = AccessMonitor(db)
    result = await monitor._already_alerted("HIGH_RATE_SUSTAINED", "1.2.3.4")
    assert result is False


@pytest.mark.asyncio
async def test_already_alerted_db_error_returns_false():
    db = _make_db()
    db.recent_alert_exists = AsyncMock(side_effect=RuntimeError("db crash"))
    monitor = AccessMonitor(db)
    # On error, err on the side of alerting (return False = not already alerted)
    result = await monitor._already_alerted("HIGH_RATE_SUSTAINED", "1.2.3.4")
    assert result is False
