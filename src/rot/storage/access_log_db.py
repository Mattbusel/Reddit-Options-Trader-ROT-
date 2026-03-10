"""
Database mixin for api_request_log and access_alerts tables.

Schema:

    api_request_log  — written by RequestLogMiddleware on every request
    access_alerts    — written by AccessMonitor when anomalous patterns fire

Both tables are created idempotently via ensure_access_log_schema().
"""
from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

ACCESS_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_request_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL    NOT NULL,
    api_key_hash TEXT,
    user_id      TEXT,
    tier         TEXT,
    method       TEXT    NOT NULL,
    endpoint     TEXT    NOT NULL,
    status_code  INTEGER,
    response_ms  REAL,
    ip           TEXT,
    user_agent   TEXT
);

CREATE INDEX IF NOT EXISTS idx_arl_ts   ON api_request_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_arl_ip   ON api_request_log(ip, ts DESC);
CREATE INDEX IF NOT EXISTS idx_arl_key  ON api_request_log(api_key_hash, ts DESC);

CREATE TABLE IF NOT EXISTS access_alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL    NOT NULL,
    alert_type   TEXT    NOT NULL,
    ip           TEXT,
    api_key_hash TEXT,
    user_id      TEXT,
    details      TEXT    NOT NULL DEFAULT '{}',
    resolved     INTEGER NOT NULL DEFAULT 0,
    resolved_at  REAL
);

CREATE INDEX IF NOT EXISTS idx_alerts_ts       ON access_alerts(ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_ip       ON access_alerts(ip, ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_type     ON access_alerts(alert_type, ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON access_alerts(resolved, ts DESC);
"""


class AccessLogMixin:
    """Mixin providing api_request_log and access_alerts DB operations."""

    async def ensure_access_log_schema(self) -> None:
        """Create tables if they don't exist (called at startup)."""
        if not self._db:
            raise RuntimeError("Database not connected")
        for stmt in ACCESS_LOG_SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await self._db.execute(stmt)
        await self._db.commit()

    # ── api_request_log queries ──────────────────────────────────────────

    async def get_request_rate_for_ip(
        self,
        ip: str,
        window_s: float = 60.0,
    ) -> float:
        """Return requests-per-second from `ip` in the last `window_s` seconds."""
        if not self._db:
            return 0.0
        since = time.time() - window_s
        async with self._db.execute(
            "SELECT COUNT(*) FROM api_request_log WHERE ip = ? AND ts >= ?",
            (ip, since),
        ) as cursor:
            row = await cursor.fetchone()
            count = row[0] if row else 0
        return count / window_s if window_s > 0 else 0.0

    async def get_sustained_high_rate_ips(
        self,
        window_s: float = 600.0,
        min_rps: float = 2.0,
    ) -> list[dict]:
        """
        Return IPs with sustained request rate above `min_rps` over `window_s`.

        An entity making ~1 req/sec for hours will appear here.
        """
        if not self._db:
            return []
        since = time.time() - window_s
        threshold_count = int(min_rps * window_s)
        async with self._db.execute(
            """
            SELECT ip, COUNT(*) AS cnt,
                   MIN(ts) AS first_seen, MAX(ts) AS last_seen
            FROM api_request_log
            WHERE ts >= ?
            GROUP BY ip
            HAVING cnt >= ?
            ORDER BY cnt DESC
            """,
            (since, threshold_count),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_sequential_enumeration_ips(
        self,
        window_s: float = 300.0,
        min_distinct_endpoints: int = 30,
    ) -> list[dict]:
        """
        Return IPs probing many distinct endpoints — characteristic of scraping.
        """
        if not self._db:
            return []
        since = time.time() - window_s
        async with self._db.execute(
            """
            SELECT ip, COUNT(DISTINCT endpoint) AS distinct_eps, COUNT(*) AS total
            FROM api_request_log
            WHERE ts >= ?
            GROUP BY ip
            HAVING distinct_eps >= ?
            ORDER BY distinct_eps DESC
            """,
            (since, min_distinct_endpoints),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_high_401_rate_ips(
        self,
        window_s: float = 300.0,
        min_count: int = 20,
    ) -> list[dict]:
        """Return IPs generating many 401 responses (auth bypass attempts)."""
        if not self._db:
            return []
        since = time.time() - window_s
        async with self._db.execute(
            """
            SELECT ip, COUNT(*) AS cnt
            FROM api_request_log
            WHERE ts >= ? AND status_code = 401
            GROUP BY ip
            HAVING cnt >= ?
            ORDER BY cnt DESC
            """,
            (since, min_count),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── access_alerts ────────────────────────────────────────────────────

    async def save_access_alert(
        self,
        alert_type: str,
        ip: Optional[str] = None,
        api_key_hash: Optional[str] = None,
        user_id: Optional[str] = None,
        details: str = "{}",
    ) -> int:
        """Insert an access alert row. Returns the new row id."""
        if not self._db:
            raise RuntimeError("Database not connected")
        cursor = await self._db.execute(
            """
            INSERT INTO access_alerts
                (ts, alert_type, ip, api_key_hash, user_id, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (time.time(), alert_type, ip, api_key_hash, user_id, details),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_unresolved_alerts(self, limit: int = 100) -> list[dict]:
        """Fetch unresolved access alerts, newest first."""
        if not self._db:
            return []
        async with self._db.execute(
            """
            SELECT * FROM access_alerts
            WHERE resolved = 0
            ORDER BY ts DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def recent_alert_exists(
        self,
        alert_type: str,
        ip: Optional[str],
        window_s: float = 3600.0,
    ) -> bool:
        """True if a same-type alert for this IP was already fired recently."""
        if not self._db:
            return False
        since = time.time() - window_s
        async with self._db.execute(
            """
            SELECT 1 FROM access_alerts
            WHERE alert_type = ? AND ip = ? AND ts >= ?
            LIMIT 1
            """,
            (alert_type, ip, since),
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None
