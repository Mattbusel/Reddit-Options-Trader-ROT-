"""
Options flow events, patterns, convergences database operations.

This mixin handles all options flow intelligence operations including:
- Flow event CRUD (block trades, sweeps, dark pool, accumulation/distribution)
- Flow pattern detection and storage
- Flow-social signal convergence tracking
- Flow timeline and summary queries
- Data purging

Assumes self.db (aiosqlite Connection) exists.
"""

import json
import time
import uuid
from typing import Any, Dict, List, Optional


class FlowMixin:
    """Options flow events, patterns, convergences. Assumes self.db (aiosqlite Connection) exists."""

    # ── Flow Events ──────────────────────────────────────────────────────

    async def save_flow_event(self, event: Dict[str, Any]) -> str:
        """Save a single flow event. Returns the event ID."""
        event_id = event.get("id") or str(uuid.uuid4())
        await self.db.execute(
            """INSERT OR IGNORE INTO flow_events
               (id, ticker, flow_type, direction, premium, volume,
                oi_change, score, details_json, signal_id, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                event.get("ticker", ""),
                event.get("flow_type", ""),
                event.get("direction", "neutral"),
                event.get("premium", 0.0),
                event.get("volume", 0),
                event.get("oi_change", 0),
                event.get("score", 0.0),
                json.dumps(event.get("details", {})),
                event.get("signal_id"),
                event.get("detected_at", time.time()),
            ),
        )
        await self.db.commit()
        return event_id

    async def save_flow_events_batch(
        self, events: List[Dict[str, Any]],
    ) -> int:
        """Batch insert flow events. Returns count inserted."""
        if not events:
            return 0
        rows = []
        for e in events:
            rows.append((
                e.get("id") or str(uuid.uuid4()),
                e.get("ticker", ""),
                e.get("flow_type", ""),
                e.get("direction", "neutral"),
                e.get("premium", 0.0),
                e.get("volume", 0),
                e.get("oi_change", 0),
                e.get("score", 0.0),
                json.dumps(e.get("details", {})),
                e.get("signal_id"),
                e.get("detected_at", time.time()),
            ))
        await self.db.executemany(
            """INSERT OR IGNORE INTO flow_events
               (id, ticker, flow_type, direction, premium, volume,
                oi_change, score, details_json, signal_id, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await self.db.commit()
        return len(rows)

    async def get_flow_events(
        self,
        hours: int = 24,
        ticker: Optional[str] = None,
        flow_type: Optional[str] = None,
        direction: Optional[str] = None,
        min_score: float = 0.0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query flow events with filters."""
        cutoff = time.time() - (hours * 3600)
        clauses = ["detected_at > ?"]
        params: list = [cutoff]

        if ticker:
            clauses.append("ticker = ?")
            params.append(ticker)
        if flow_type:
            clauses.append("flow_type = ?")
            params.append(flow_type)
        if direction:
            clauses.append("direction = ?")
            params.append(direction)
        if min_score > 0:
            clauses.append("score >= ?")
            params.append(min_score)

        where = " AND ".join(clauses)
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            SELECT * FROM flow_events
            WHERE {where}
            ORDER BY detected_at DESC
            LIMIT ?
        """
        params.append(limit)

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            try:
                d["details"] = json.loads(d.pop("details_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["details"] = {}
            results.append(d)
        return results

    async def get_flow_timeline(
        self, ticker: str, days: int = 7,
    ) -> List[Dict[str, Any]]:
        """Get flow events timeline for a specific ticker."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT * FROM flow_events
            WHERE ticker = ? AND detected_at > ?
            ORDER BY detected_at ASC
        """
        async with self.db.execute(query, (ticker, cutoff)) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            try:
                d["details"] = json.loads(d.pop("details_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["details"] = {}
            results.append(d)
        return results

    async def get_flow_summary(
        self, hours: int = 24,
    ) -> Dict[str, Any]:
        """Get aggregate flow stats for a time period."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                COUNT(*) as total_events,
                COUNT(DISTINCT ticker) as unique_tickers,
                COALESCE(SUM(premium), 0) as total_premium,
                COALESCE(SUM(CASE WHEN direction='bullish' THEN premium ELSE 0 END), 0) as bullish_premium,
                COALESCE(SUM(CASE WHEN direction='bearish' THEN premium ELSE 0 END), 0) as bearish_premium,
                COALESCE(AVG(score), 0) as avg_score,
                SUM(CASE WHEN direction='bullish' THEN 1 ELSE 0 END) as bullish_count,
                SUM(CASE WHEN direction='bearish' THEN 1 ELSE 0 END) as bearish_count,
                SUM(CASE WHEN direction='neutral' THEN 1 ELSE 0 END) as neutral_count
            FROM flow_events
            WHERE detected_at > ?
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            row = await cursor.fetchone()

        if row:
            summary = dict(row)
            for k in summary:
                if summary[k] is None:
                    summary[k] = 0
        else:
            summary = {
                "total_events": 0, "unique_tickers": 0,
                "total_premium": 0, "bullish_premium": 0, "bearish_premium": 0,
                "avg_score": 0, "bullish_count": 0, "bearish_count": 0,
                "neutral_count": 0,
            }

        summary["net_premium"] = summary.get("bullish_premium", 0) - summary.get("bearish_premium", 0)

        # Type breakdown
        type_query = """
            SELECT flow_type, COUNT(*) as cnt, SUM(premium) as total_prem
            FROM flow_events
            WHERE detected_at > ?
            GROUP BY flow_type
            ORDER BY cnt DESC
        """
        async with self.db.execute(type_query, (cutoff,)) as cursor:
            type_rows = await cursor.fetchall()
        summary["type_breakdown"] = {
            r["flow_type"]: {"count": r["cnt"], "premium": round(r["total_prem"] or 0, 2)}
            for r in type_rows
        }

        # Top tickers by premium
        ticker_query = """
            SELECT ticker, COUNT(*) as cnt, SUM(premium) as total_prem,
                   AVG(score) as avg_score
            FROM flow_events
            WHERE detected_at > ?
            GROUP BY ticker
            ORDER BY total_prem DESC
            LIMIT 10
        """
        async with self.db.execute(ticker_query, (cutoff,)) as cursor:
            ticker_rows = await cursor.fetchall()
        summary["top_tickers"] = [
            {"ticker": r["ticker"], "count": r["cnt"],
             "premium": round(r["total_prem"] or 0, 2),
             "avg_score": round(r["avg_score"] or 0, 1)}
            for r in ticker_rows
        ]

        return summary

    # ── Flow Patterns ────────────────────────────────────────────────────

    async def save_flow_pattern(self, pattern: Dict[str, Any]) -> str:
        """Save a detected flow pattern. Returns pattern ID."""
        pattern_id = pattern.get("id") or str(uuid.uuid4())
        await self.db.execute(
            """INSERT OR IGNORE INTO flow_patterns
               (id, pattern_type, tickers_json, confidence, timeframe,
                event_count, details_json, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pattern_id,
                pattern.get("pattern_type", ""),
                json.dumps(pattern.get("tickers", [])),
                pattern.get("confidence", 0.0),
                pattern.get("timeframe", ""),
                pattern.get("event_count", 0),
                json.dumps(pattern.get("details", {})),
                pattern.get("detected_at", time.time()),
            ),
        )
        await self.db.commit()
        return pattern_id

    async def get_flow_patterns(
        self,
        hours: int = 24,
        pattern_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query flow patterns with optional type filter."""
        cutoff = time.time() - (hours * 3600)
        clauses = ["detected_at > ?"]
        params: list = [cutoff]
        if pattern_type:
            clauses.append("pattern_type = ?")
            params.append(pattern_type)

        where = " AND ".join(clauses)
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            SELECT * FROM flow_patterns
            WHERE {where}
            ORDER BY detected_at DESC
            LIMIT ?
        """
        params.append(limit)

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            try:
                d["tickers"] = json.loads(d.pop("tickers_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["tickers"] = []
            try:
                d["details"] = json.loads(d.pop("details_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["details"] = {}
            results.append(d)
        return results

    # ── Flow Convergences ────────────────────────────────────────────────

    async def save_flow_convergence(self, convergence: Dict[str, Any]) -> str:
        """Save a flow-signal convergence. Returns convergence ID."""
        conv_id = convergence.get("id") or str(uuid.uuid4())
        await self.db.execute(
            """INSERT OR IGNORE INTO flow_convergences
               (id, signal_id, ticker, flow_event_ids_json, convergence_score,
                convergence_type, signal_stance, flow_direction,
                net_flow_premium, details_json, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                conv_id,
                convergence.get("signal_id", ""),
                convergence.get("ticker", ""),
                json.dumps(convergence.get("flow_event_ids", [])),
                convergence.get("convergence_score", 0.0),
                convergence.get("convergence_type", ""),
                convergence.get("signal_stance", ""),
                convergence.get("flow_direction", ""),
                convergence.get("net_flow_premium", 0.0),
                json.dumps(convergence.get("details", {})),
                convergence.get("detected_at", time.time()),
            ),
        )
        await self.db.commit()
        return conv_id

    async def get_flow_convergences(
        self,
        hours: int = 24,
        ticker: Optional[str] = None,
        convergence_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query flow convergences with filters."""
        cutoff = time.time() - (hours * 3600)
        clauses = ["detected_at > ?"]
        params: list = [cutoff]
        if ticker:
            clauses.append("ticker = ?")
            params.append(ticker)
        if convergence_type:
            clauses.append("convergence_type = ?")
            params.append(convergence_type)

        where = " AND ".join(clauses)
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            SELECT * FROM flow_convergences
            WHERE {where}
            ORDER BY convergence_score DESC, detected_at DESC
            LIMIT ?
        """
        params.append(limit)

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            try:
                d["flow_event_ids"] = json.loads(d.pop("flow_event_ids_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["flow_event_ids"] = []
            try:
                d["details"] = json.loads(d.pop("details_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["details"] = {}
            results.append(d)
        return results

