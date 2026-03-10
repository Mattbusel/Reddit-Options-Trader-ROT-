"""
ROT Access Monitor — background anomaly detection for API abuse.

Runs as an asyncio background task, scanning `api_request_log` every
`interval_s` seconds for three attack patterns:

    1. HIGH_RATE_SUSTAINED  — ≥ 2 req/s sustained over 10 min
       Matches the original attacker (~1 req/sec, 150K+ requests over 3 days)

    2. SEQUENTIAL_ENUM      — ≥ 30 distinct endpoints probed within 5 min
       Characteristic of automated scraping / route discovery

    3. AUTH_BYPASS_ATTEMPT  — ≥ 20 HTTP 401 responses to a single IP within 5 min
       Credential stuffing or auth bypass probing

Each detection writes to `access_alerts` (via AccessLogMixin.save_access_alert).
Duplicate alerts for the same IP + type are suppressed for 1 hour.

Usage:
    from rot.auth.access_monitor import AccessMonitor

    monitor = AccessMonitor(db, interval_s=300)
    task = asyncio.create_task(monitor.run())
    ...
    await monitor.stop()
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


class AccessMonitor:
    """Background monitor that detects anomalous API access patterns."""

    def __init__(
        self,
        db,
        interval_s: float = 300.0,          # scan every 5 minutes
        sustained_window_s: float = 600.0,   # 10-minute window for rate check
        sustained_min_rps: float = 2.0,      # fire at ≥ 2 req/s sustained
        enum_window_s: float = 300.0,        # 5-minute window for endpoint enumeration
        enum_min_endpoints: int = 30,        # fire at ≥ 30 distinct endpoints
        auth_window_s: float = 300.0,        # 5-minute window for 401 check
        auth_min_401s: int = 20,             # fire at ≥ 20 401s
        dedup_window_s: float = 3600.0,      # suppress repeat alerts for 1 hour
    ) -> None:
        self._db = db
        self._interval_s = interval_s
        self._sustained_window_s = sustained_window_s
        self._sustained_min_rps = sustained_min_rps
        self._enum_window_s = enum_window_s
        self._enum_min_endpoints = enum_min_endpoints
        self._auth_window_s = auth_window_s
        self._auth_min_401s = auth_min_401s
        self._dedup_window_s = dedup_window_s
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def run(self) -> None:
        """Main loop — call via asyncio.create_task(monitor.run())."""
        self._running = True
        log.info(
            "AccessMonitor started (interval=%.0fs, sustained_rps=%.1f)",
            self._interval_s,
            self._sustained_min_rps,
        )
        while self._running:
            try:
                await asyncio.sleep(self._interval_s)
            except asyncio.CancelledError:
                break
            if not self._running:
                break
            try:
                await self._scan()
            except Exception as exc:
                log.warning("AccessMonitor scan error: %s", exc)

        log.info("AccessMonitor stopped")

    async def stop(self) -> None:
        """Signal the loop to exit cleanly."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    # ── Detection passes ─────────────────────────────────────────────────

    async def _scan(self) -> None:
        """Run all detection passes in sequence."""
        t0 = time.time()
        alerts_fired = 0

        alerts_fired += await self._check_sustained_rate()
        alerts_fired += await self._check_sequential_enum()
        alerts_fired += await self._check_auth_bypass()

        elapsed = (time.time() - t0) * 1000
        if alerts_fired:
            log.warning(
                "AccessMonitor scan complete: %d new alert(s) fired (%.1f ms)",
                alerts_fired,
                elapsed,
            )
        else:
            log.debug("AccessMonitor scan: clean (%.1f ms)", elapsed)

    async def _check_sustained_rate(self) -> int:
        """Fire HIGH_RATE_SUSTAINED for IPs exceeding sustained_min_rps."""
        fired = 0
        try:
            offenders = await self._db.get_sustained_high_rate_ips(
                window_s=self._sustained_window_s,
                min_rps=self._sustained_min_rps,
            )
        except Exception as exc:
            log.warning("AccessMonitor._check_sustained_rate DB error: %s", exc)
            return 0

        for row in offenders:
            ip = row.get("ip")
            if await self._already_alerted("HIGH_RATE_SUSTAINED", ip):
                continue
            details = json.dumps({
                "request_count": row.get("cnt"),
                "window_s": self._sustained_window_s,
                "first_seen": row.get("first_seen"),
                "last_seen": row.get("last_seen"),
                "rps": round(
                    (row.get("cnt") or 0) / self._sustained_window_s, 3
                ),
            })
            await self._fire_alert("HIGH_RATE_SUSTAINED", ip=ip, details=details)
            fired += 1

        return fired

    async def _check_sequential_enum(self) -> int:
        """Fire SEQUENTIAL_ENUM for IPs probing many distinct endpoints."""
        fired = 0
        try:
            offenders = await self._db.get_sequential_enumeration_ips(
                window_s=self._enum_window_s,
                min_distinct_endpoints=self._enum_min_endpoints,
            )
        except Exception as exc:
            log.warning("AccessMonitor._check_sequential_enum DB error: %s", exc)
            return 0

        for row in offenders:
            ip = row.get("ip")
            if await self._already_alerted("SEQUENTIAL_ENUM", ip):
                continue
            details = json.dumps({
                "distinct_endpoints": row.get("distinct_eps"),
                "total_requests": row.get("total"),
                "window_s": self._enum_window_s,
            })
            await self._fire_alert("SEQUENTIAL_ENUM", ip=ip, details=details)
            fired += 1

        return fired

    async def _check_auth_bypass(self) -> int:
        """Fire AUTH_BYPASS_ATTEMPT for IPs with high 401 counts."""
        fired = 0
        try:
            offenders = await self._db.get_high_401_rate_ips(
                window_s=self._auth_window_s,
                min_count=self._auth_min_401s,
            )
        except Exception as exc:
            log.warning("AccessMonitor._check_auth_bypass DB error: %s", exc)
            return 0

        for row in offenders:
            ip = row.get("ip")
            if await self._already_alerted("AUTH_BYPASS_ATTEMPT", ip):
                continue
            details = json.dumps({
                "401_count": row.get("cnt"),
                "window_s": self._auth_window_s,
            })
            await self._fire_alert("AUTH_BYPASS_ATTEMPT", ip=ip, details=details)
            fired += 1

        return fired

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _already_alerted(self, alert_type: str, ip: Optional[str]) -> bool:
        try:
            return await self._db.recent_alert_exists(
                alert_type, ip, window_s=self._dedup_window_s
            )
        except Exception:
            return False  # If check fails, err on the side of alerting

    async def _fire_alert(
        self,
        alert_type: str,
        ip: Optional[str] = None,
        api_key_hash: Optional[str] = None,
        user_id: Optional[str] = None,
        details: str = "{}",
    ) -> None:
        log.warning(
            "ACCESS ALERT [%s] ip=%s details=%s",
            alert_type,
            ip,
            details,
        )
        try:
            await self._db.save_access_alert(
                alert_type=alert_type,
                ip=ip,
                api_key_hash=api_key_hash,
                user_id=user_id,
                details=details,
            )
        except Exception as exc:
            log.error("AccessMonitor: failed to save alert: %s", exc)
