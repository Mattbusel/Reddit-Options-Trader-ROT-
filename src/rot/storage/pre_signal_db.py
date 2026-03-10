"""PreSignalMixin — SQLite persistence for the Probability Pipeline.

Table: pre_signal_events
  Tracks every pre-signal fired before document completion alongside the
  final signal from the same document, enabling empirical measurement of
  how much alpha exists in processing information before it completes.

The delta between pre-signal accuracy and post-signal accuracy on the same
documents is the primary performance metric for Capability 3.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

PRE_SIGNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS pre_signal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'reddit',
    doc_id TEXT NOT NULL DEFAULT '',
    pre_signal_confidence REAL NOT NULL,
    pre_signal_direction TEXT NOT NULL DEFAULT 'neutral',
    pre_signal_iir_value REAL NOT NULL DEFAULT 0.0,
    pre_signal_variance REAL NOT NULL DEFAULT 0.0,
    chunks_processed_at_fire INTEGER NOT NULL DEFAULT 0,
    fired_at REAL NOT NULL,
    final_confidence REAL,
    final_direction TEXT,
    agreement INTEGER,
    lead_time_ms REAL,
    resolved INTEGER NOT NULL DEFAULT 0,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_pre_signal_ticker ON pre_signal_events(ticker);
CREATE INDEX IF NOT EXISTS idx_pre_signal_fired ON pre_signal_events(fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_pre_signal_resolved ON pre_signal_events(resolved, fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_pre_signal_source ON pre_signal_events(source, fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_pre_signal_agreement ON pre_signal_events(agreement, fired_at DESC);
"""


class PreSignalMixin:
    """SQLite persistence for Probability Pipeline pre-signal events."""

    async def ensure_pre_signal_schema(self) -> None:
        """Create pre_signal tables if they don't exist."""
        try:
            for stmt in PRE_SIGNAL_SCHEMA.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await self.db.execute(stmt)
            await self.db.commit()
        except Exception as exc:
            log.error("PreSignalMixin.ensure_pre_signal_schema failed: %s", exc)

    async def save_pre_signal(
        self,
        ticker: str,
        source: str,
        doc_id: str,
        pre_signal_confidence: float,
        pre_signal_direction: str,
        pre_signal_iir_value: float,
        pre_signal_variance: float,
        chunks_processed_at_fire: int,
        fired_at: Optional[float] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Insert a new pre-signal event.  Returns the row ID."""
        try:
            cursor = await self.db.execute(
                """
                INSERT INTO pre_signal_events
                    (ticker, source, doc_id, pre_signal_confidence, pre_signal_direction,
                     pre_signal_iir_value, pre_signal_variance, chunks_processed_at_fire,
                     fired_at, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker, source, doc_id, pre_signal_confidence, pre_signal_direction,
                    pre_signal_iir_value, pre_signal_variance, chunks_processed_at_fire,
                    fired_at or time.time(), json.dumps(meta or {}),
                ),
            )
            await self.db.commit()
            return cursor.lastrowid or 0
        except Exception as exc:
            log.error("save_pre_signal failed: %s", exc)
            return 0

    async def resolve_pre_signal(
        self,
        pre_signal_id: int,
        final_confidence: float,
        final_direction: str,
        agreement: bool,
        lead_time_ms: Optional[float] = None,
    ) -> None:
        """Update a pre-signal event with final document outcome."""
        try:
            await self.db.execute(
                """
                UPDATE pre_signal_events
                SET final_confidence = ?, final_direction = ?, agreement = ?,
                    lead_time_ms = ?, resolved = 1
                WHERE id = ?
                """,
                (final_confidence, final_direction, int(agreement), lead_time_ms, pre_signal_id),
            )
            await self.db.commit()
        except Exception as exc:
            log.error("resolve_pre_signal failed for id=%s: %s", pre_signal_id, exc)

    async def get_pre_signal_accuracy_stats(
        self, source: Optional[str] = None, days: int = 30
    ) -> Dict[str, Any]:
        """Return pre-signal accuracy statistics vs final signal accuracy.

        The core metric: does firing early (pre-signal) agree with the final
        signal direction?  Agreement rate > 50% means alpha exists in early firing.
        """
        cutoff = time.time() - days * 86400
        try:
            if source:
                query = """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved,
                        SUM(CASE WHEN agreement = 1 THEN 1 ELSE 0 END) as agreements,
                        AVG(pre_signal_confidence) as avg_pre_confidence,
                        AVG(final_confidence) as avg_final_confidence,
                        AVG(lead_time_ms) as avg_lead_ms
                    FROM pre_signal_events
                    WHERE fired_at > ? AND source = ?
                """
                params = (cutoff, source)
            else:
                query = """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved,
                        SUM(CASE WHEN agreement = 1 THEN 1 ELSE 0 END) as agreements,
                        AVG(pre_signal_confidence) as avg_pre_confidence,
                        AVG(final_confidence) as avg_final_confidence,
                        AVG(lead_time_ms) as avg_lead_ms
                    FROM pre_signal_events
                    WHERE fired_at > ?
                """
                params = (cutoff,)

            async with self.db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                if row is None or row[0] == 0:
                    return {"total": 0}
                total = row[0] or 0
                resolved = row[1] or 0
                agreements = row[2] or 0
                agreement_rate = (agreements / resolved * 100) if resolved > 0 else None
                return {
                    "total": total,
                    "resolved": resolved,
                    "agreements": agreements,
                    "agreement_rate_pct": round(agreement_rate, 1) if agreement_rate is not None else None,
                    "avg_pre_confidence": round(row[3], 3) if row[3] else None,
                    "avg_final_confidence": round(row[4], 3) if row[4] else None,
                    "avg_lead_time_ms": round(row[5], 1) if row[5] else None,
                }
        except Exception as exc:
            log.error("get_pre_signal_accuracy_stats failed: %s", exc)
            return {}

    async def get_unresolved_pre_signals(
        self, doc_id: Optional[str] = None, ticker: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return unresolved pre-signals for resolution by stream processor."""
        try:
            conditions = ["resolved = 0"]
            params: list = []
            if doc_id:
                conditions.append("doc_id = ?")
                params.append(doc_id)
            if ticker:
                conditions.append("ticker = ?")
                params.append(ticker)
            where = " AND ".join(conditions)
            rows = []
            async with self.db.execute(
                f"SELECT id, ticker, source, doc_id, pre_signal_confidence, "
                f"pre_signal_direction, fired_at FROM pre_signal_events "
                f"WHERE {where} ORDER BY fired_at ASC LIMIT 1000",
                params,
            ) as cursor:
                async for row in cursor:
                    rows.append({
                        "id": row[0],
                        "ticker": row[1],
                        "source": row[2],
                        "doc_id": row[3],
                        "pre_signal_confidence": row[4],
                        "pre_signal_direction": row[5],
                        "fired_at": row[6],
                    })
            return rows
        except Exception as exc:
            log.error("get_unresolved_pre_signals failed: %s", exc)
            return []
