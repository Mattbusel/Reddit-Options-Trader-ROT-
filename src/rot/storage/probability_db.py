"""ProbabilityMixin — SQLite persistence for probability pipeline pre-signals.

Table: pre_signal_events
  ticker, timestamp, pre_signal_confidence, final_signal_confidence,
  pre_signal_direction, final_signal_direction, agreement (boolean),
  lead_time_ms

The delta between pre_signal_confidence and final_signal_confidence on the
same documents is the empirical proof of how much alpha exists in processing
information before it completes.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

PROBABILITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS pre_signal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    timestamp REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'reddit',
    doc_id TEXT NOT NULL DEFAULT '',
    pre_signal_confidence REAL NOT NULL,
    final_signal_confidence REAL,
    pre_signal_direction TEXT NOT NULL DEFAULT 'neutral',
    final_signal_direction TEXT,
    agreement INTEGER,
    lead_time_ms REAL,
    iir_value REAL,
    variance REAL,
    chunks_at_fire INTEGER,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_presig_ticker ON pre_signal_events(ticker);
CREATE INDEX IF NOT EXISTS idx_presig_ts ON pre_signal_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_presig_source ON pre_signal_events(source, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_presig_agreement ON pre_signal_events(agreement);
"""


class ProbabilityMixin:
    """SQLite persistence for probability pipeline pre-signal tracking."""

    async def ensure_probability_schema(self) -> None:
        """Create probability tables if they don't exist."""
        try:
            for stmt in PROBABILITY_SCHEMA.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await self.db.execute(stmt)
            await self.db.commit()
        except Exception as exc:
            log.error("ProbabilityMixin.ensure_probability_schema failed: %s", exc)

    async def save_pre_signal(
        self,
        ticker: str,
        timestamp: float,
        source: str,
        doc_id: str,
        pre_signal_confidence: float,
        pre_signal_direction: str,
        iir_value: float = 0.0,
        variance: float = 0.0,
        chunks_at_fire: int = 0,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Insert a new pre-signal event.  Returns the row ID."""
        try:
            cursor = await self.db.execute(
                """
                INSERT INTO pre_signal_events
                    (ticker, timestamp, source, doc_id,
                     pre_signal_confidence, pre_signal_direction,
                     iir_value, variance, chunks_at_fire, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker, timestamp, source, doc_id,
                    pre_signal_confidence, pre_signal_direction,
                    iir_value, variance, chunks_at_fire,
                    json.dumps(meta or {}),
                ),
            )
            await self.db.commit()
            return cursor.lastrowid or 0
        except Exception as exc:
            log.error("save_pre_signal failed: %s", exc)
            return 0

    async def resolve_pre_signal(
        self,
        event_id: int,
        final_confidence: float,
        final_direction: str,
        agreement: bool,
        lead_time_ms: Optional[float],
    ) -> None:
        """Update a pre-signal event with final document outcome."""
        try:
            await self.db.execute(
                """
                UPDATE pre_signal_events
                SET final_signal_confidence = ?,
                    final_signal_direction = ?,
                    agreement = ?,
                    lead_time_ms = ?
                WHERE id = ?
                """,
                (
                    final_confidence,
                    final_direction,
                    1 if agreement else 0,
                    lead_time_ms,
                    event_id,
                ),
            )
            await self.db.commit()
        except Exception as exc:
            log.error("resolve_pre_signal failed for id=%s: %s", event_id, exc)

    async def get_presignal_accuracy_stats(
        self, source: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return accuracy statistics for pre-signals.

        The key metric: agreement_rate measures how often the pre-signal
        direction matched the final signal direction.
        """
        try:
            where = "WHERE agreement IS NOT NULL"
            params: tuple = ()
            if source:
                where += " AND source = ?"
                params = (source,)
            query = f"""
                SELECT
                    COUNT(*) as total,
                    SUM(agreement) as agreements,
                    AVG(pre_signal_confidence) as avg_pre_conf,
                    AVG(final_signal_confidence) as avg_final_conf,
                    AVG(lead_time_ms) as avg_lead_ms,
                    MIN(lead_time_ms) as min_lead_ms,
                    MAX(lead_time_ms) as max_lead_ms
                FROM pre_signal_events
                {where}
            """
            cursor = await self.db.execute(query, params)
            row = await cursor.fetchone()
            if row is None or row[0] == 0:
                return {"total": 0}
            total = row[0]
            agreements = row[1] or 0
            return {
                "total": total,
                "agreements": agreements,
                "agreement_rate": round(agreements / total, 4) if total > 0 else None,
                "avg_pre_confidence": round(row[2], 3) if row[2] else None,
                "avg_final_confidence": round(row[3], 3) if row[3] else None,
                "confidence_delta": round((row[3] or 0) - (row[2] or 0), 3),
                "avg_lead_ms": round(row[4], 1) if row[4] else None,
                "min_lead_ms": round(row[5], 1) if row[5] else None,
                "max_lead_ms": round(row[6], 1) if row[6] else None,
            }
        except Exception as exc:
            log.error("get_presignal_accuracy_stats failed: %s", exc)
            return {}

    async def get_presignals_by_source(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent pre-signal events grouped summary by source."""
        try:
            rows = []
            cursor = await self.db.execute(
                """
                SELECT source,
                       COUNT(*) as total,
                       SUM(agreement) as agreements,
                       AVG(pre_signal_confidence) as avg_pre_conf,
                       AVG(lead_time_ms) as avg_lead_ms
                FROM pre_signal_events
                WHERE agreement IS NOT NULL
                GROUP BY source
                ORDER BY total DESC
                LIMIT ?
                """,
                (limit,),
            )
            async for row in cursor:
                total = row[1]
                agreements = row[2] or 0
                rows.append({
                    "source": row[0],
                    "total": total,
                    "agreements": agreements,
                    "agreement_rate": round(agreements / total, 4) if total > 0 else None,
                    "avg_pre_confidence": round(row[3], 3) if row[3] else None,
                    "avg_lead_ms": round(row[4], 1) if row[4] else None,
                })
            return rows
        except Exception as exc:
            log.error("get_presignals_by_source failed: %s", exc)
            return []
