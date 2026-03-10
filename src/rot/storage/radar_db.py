"""RadarMixin — SQLite persistence for AttentionRadar events.

Table: attention_radar_events
  ticker, timestamp, confidence, signal_volume_zscore,
  eventual_catalyst (null until resolved), lead_time_days (null until resolved)

The lead time distribution across all resolved events is the system's most
important performance metric: it measures how far ahead of market-nameable
events the system is operating.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

RADAR_SCHEMA = """
CREATE TABLE IF NOT EXISTS attention_radar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    timestamp REAL NOT NULL,
    confidence REAL NOT NULL,
    signal_volume_zscore REAL NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'other',
    stance TEXT NOT NULL DEFAULT 'unknown',
    source_signal_id TEXT NOT NULL DEFAULT '',
    eventual_catalyst TEXT,
    lead_time_days REAL,
    resolved INTEGER NOT NULL DEFAULT 0,
    resolved_at REAL,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_radar_ticker ON attention_radar_events(ticker);
CREATE INDEX IF NOT EXISTS idx_radar_ts ON attention_radar_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_radar_resolved ON attention_radar_events(resolved, timestamp DESC);
"""


class RadarMixin:
    """SQLite persistence for AttentionRadar events."""

    async def ensure_radar_schema(self) -> None:
        """Create radar tables if they don't exist."""
        try:
            for stmt in RADAR_SCHEMA.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await self.db.execute(stmt)
            await self.db.commit()
        except Exception as exc:
            log.error("RadarMixin.ensure_radar_schema failed: %s", exc)

    async def save_radar_event(
        self,
        ticker: str,
        timestamp: float,
        confidence: float,
        signal_volume_zscore: float,
        event_type: str = "other",
        stance: str = "unknown",
        source_signal_id: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Insert a new AttentionRadar event.  Returns the row ID."""
        try:
            cursor = await self.db.execute(
                """
                INSERT INTO attention_radar_events
                    (ticker, timestamp, confidence, signal_volume_zscore,
                     event_type, stance, source_signal_id, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker, timestamp, confidence, signal_volume_zscore,
                    event_type, stance, source_signal_id,
                    json.dumps(meta or {}),
                ),
            )
            await self.db.commit()
            return cursor.lastrowid or 0
        except Exception as exc:
            log.error("save_radar_event failed: %s", exc)
            return 0

    async def get_unresolved_radar_events(
        self, older_than_ts: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Return unresolved AttentionRadar events, optionally filtered by age."""
        try:
            if older_than_ts is not None:
                query = (
                    "SELECT id, ticker, timestamp, confidence, signal_volume_zscore, "
                    "event_type, stance, source_signal_id, meta "
                    "FROM attention_radar_events "
                    "WHERE resolved = 0 AND timestamp <= ? "
                    "ORDER BY timestamp ASC"
                )
                params = (older_than_ts,)
            else:
                query = (
                    "SELECT id, ticker, timestamp, confidence, signal_volume_zscore, "
                    "event_type, stance, source_signal_id, meta "
                    "FROM attention_radar_events "
                    "WHERE resolved = 0 ORDER BY timestamp ASC"
                )
                params = ()
            rows = []
            async with self.db.execute(query, params) as cursor:
                async for row in cursor:
                    rows.append({
                        "id": row[0],
                        "ticker": row[1],
                        "timestamp": row[2],
                        "confidence": row[3],
                        "signal_volume_zscore": row[4],
                        "event_type": row[5],
                        "stance": row[6],
                        "source_signal_id": row[7],
                        "meta": json.loads(row[8] or "{}"),
                    })
            return rows
        except Exception as exc:
            log.error("get_unresolved_radar_events failed: %s", exc)
            return []

    async def resolve_radar_event(
        self,
        event_id: int,
        eventual_catalyst: str,
        lead_time_days: float,
        resolved_at: Optional[float] = None,
    ) -> None:
        """Mark a radar event as resolved with catalyst and lead time."""
        try:
            await self.db.execute(
                """
                UPDATE attention_radar_events
                SET resolved = 1, eventual_catalyst = ?, lead_time_days = ?, resolved_at = ?
                WHERE id = ?
                """,
                (eventual_catalyst, lead_time_days, resolved_at or time.time(), event_id),
            )
            await self.db.commit()
        except Exception as exc:
            log.error("resolve_radar_event failed for id=%s: %s", event_id, exc)

    async def get_radar_lead_time_distribution(self) -> Dict[str, Any]:
        """Return summary statistics of the lead time distribution for resolved events."""
        try:
            async with self.db.execute(
                """
                SELECT
                    COUNT(*) as total_resolved,
                    AVG(lead_time_days) as avg_lead_days,
                    MIN(lead_time_days) as min_lead_days,
                    MAX(lead_time_days) as max_lead_days,
                    AVG(confidence) as avg_confidence
                FROM attention_radar_events
                WHERE resolved = 1
                """
            ) as cursor:
                row = await cursor.fetchone()
                if row is None or row[0] == 0:
                    return {"total_resolved": 0}
                return {
                    "total_resolved": row[0],
                    "avg_lead_days": round(row[1], 2) if row[1] else None,
                    "min_lead_days": round(row[2], 2) if row[2] else None,
                    "max_lead_days": round(row[3], 2) if row[3] else None,
                    "avg_confidence": round(row[4], 3) if row[4] else None,
                }
        except Exception as exc:
            log.error("get_radar_lead_time_distribution failed: %s", exc)
            return {}

    async def get_directional_signals_after(
        self,
        ticker: str,
        after_ts: float,
        min_confidence: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Find directional signals for a ticker after a given timestamp.

        Used by RadarResolver to match catalysts to radar events.
        Returns signals where stance is bullish or bearish (not unknown/mixed).
        """
        try:
            rows = []
            async with self.db.execute(
                """
                SELECT id, created_at, ticker, event_type, stance, confidence
                FROM signals
                WHERE ticker = ?
                  AND created_at > ?
                  AND confidence >= ?
                  AND stance IN ('bullish', 'bearish')
                ORDER BY created_at ASC
                LIMIT 10
                """,
                (ticker, after_ts, min_confidence),
            ) as cursor:
                async for row in cursor:
                    rows.append({
                        "id": row[0],
                        "created_at": row[1],
                        "ticker": row[2],
                        "event_type": row[3],
                        "stance": row[4],
                        "confidence": row[5],
                    })
            return rows
        except Exception as exc:
            log.error("get_directional_signals_after failed: %s", exc)
            return []
