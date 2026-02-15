"""
Macro events, earnings, insider, FOMC, impact cache mixin.

Assumes self.db (aiosqlite Connection) exists.
"""
import json
import time
from typing import Any, Dict, List, Optional


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert dataclass to dict if needed."""
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(obj)
    return obj


class MacroMixin:
    """Macro events, earnings, insider, FOMC, impact cache. Assumes self.db (aiosqlite Connection) exists."""

    # ── Macro Events ──

    async def upsert_macro_event(self, event) -> bool:
        """Insert or update a macro event. Accepts MacroEvent dataclass or dict.

        Returns True if inserted/updated.
        """
        d = _to_dict(event) if not isinstance(event, dict) else event
        now = time.time()
        has_actual = 1 if d.get("actual_value") is not None else 0
        await self.db.execute(
            """INSERT INTO macro_events
               (id, event_type, name, scheduled_at, actual_at, country, importance,
                category, consensus_value, actual_value, previous_value, surprise_pct,
                affected_sectors, affected_tickers, source, meta, created_at, has_actual)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   actual_at = excluded.actual_at,
                   actual_value = excluded.actual_value,
                   surprise_pct = excluded.surprise_pct,
                   has_actual = excluded.has_actual,
                   meta = excluded.meta""",
            (
                d.get("id", ""),
                d.get("event_type", ""),
                d.get("name", ""),
                d.get("scheduled_at", 0),
                d.get("actual_at"),
                d.get("country", "US"),
                d.get("importance", "medium"),
                d.get("category", "other"),
                d.get("consensus_value"),
                d.get("actual_value"),
                d.get("previous_value"),
                d.get("surprise_pct"),
                json.dumps(d.get("affected_sectors", [])),
                json.dumps(d.get("affected_tickers", [])),
                d.get("source", ""),
                json.dumps(d.get("meta", {})),
                now,
                has_actual,
            ),
        )
        await self.db.commit()
        return True

    async def query_macro_events(
        self,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        event_type: Optional[str] = None,
        category: Optional[str] = None,
        importance_in: Optional[List[str]] = None,
        has_actual: Optional[bool] = None,
        order: str = "asc",
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Query macro events with flexible filters."""
        clauses: List[str] = []
        params: list = []

        if start_ts is not None:
            clauses.append("scheduled_at >= ?")
            params.append(start_ts)
        if end_ts is not None:
            clauses.append("scheduled_at <= ?")
            params.append(end_ts)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if importance_in:
            placeholders = ",".join("?" * len(importance_in))
            clauses.append(f"importance IN ({placeholders})")
            params.extend(importance_in)
        if has_actual is not None:
            clauses.append("has_actual = ?")
            params.append(1 if has_actual else 0)

        where = " AND ".join(clauses) if clauses else "1=1"
        direction = "ASC" if order == "asc" else "DESC"
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            SELECT * FROM macro_events
            WHERE {where}
            ORDER BY scheduled_at {direction}
            LIMIT ?
        """
        params.append(limit)

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_macro_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Get a single macro event by ID."""
        async with self.db.execute(
            "SELECT * FROM macro_events WHERE id = ?", (event_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    # ── Earnings Events ──

    async def upsert_earnings_event(self, event) -> bool:
        """Insert or update an earnings event. Accepts EarningsEvent dataclass or dict."""
        d = _to_dict(event) if not isinstance(event, dict) else event
        now = time.time()
        await self.db.execute(
            """INSERT INTO earnings_events
               (id, ticker, report_date, fiscal_quarter, eps_estimate, eps_actual,
                revenue_estimate, revenue_actual, surprise_pct,
                expected_move_pct, actual_move_pct,
                iv_before, iv_after, iv_crush_pct, meta, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   eps_actual = excluded.eps_actual,
                   revenue_actual = excluded.revenue_actual,
                   surprise_pct = excluded.surprise_pct,
                   actual_move_pct = excluded.actual_move_pct,
                   iv_after = excluded.iv_after,
                   iv_crush_pct = excluded.iv_crush_pct,
                   meta = excluded.meta""",
            (
                d.get("id", ""),
                d.get("ticker", ""),
                d.get("report_date", 0),
                d.get("fiscal_quarter", ""),
                d.get("eps_estimate"),
                d.get("eps_actual"),
                d.get("revenue_estimate"),
                d.get("revenue_actual"),
                d.get("surprise_pct"),
                d.get("expected_move_pct"),
                d.get("actual_move_pct"),
                d.get("iv_before"),
                d.get("iv_after"),
                d.get("iv_crush_pct"),
                json.dumps(d.get("meta", {})),
                now,
            ),
        )
        await self.db.commit()
        return True

    async def query_earnings_events(
        self,
        ticker: Optional[str] = None,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        order: str = "asc",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query earnings events with filters."""
        clauses: List[str] = []
        params: list = []

        if ticker:
            clauses.append("ticker = ?")
            params.append(ticker)
        if start_ts is not None:
            clauses.append("report_date >= ?")
            params.append(start_ts)
        if end_ts is not None:
            clauses.append("report_date <= ?")
            params.append(end_ts)

        where = " AND ".join(clauses) if clauses else "1=1"
        direction = "ASC" if order == "asc" else "DESC"
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            SELECT * FROM earnings_events
            WHERE {where}
            ORDER BY report_date {direction}
            LIMIT ?
        """
        params.append(limit)

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_earnings_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Get a single earnings event by ID."""
        async with self.db.execute(
            "SELECT * FROM earnings_events WHERE id = ?", (event_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_earnings_by_ticker(
        self, ticker: str, limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get earnings history for a specific ticker."""
        async with self.db.execute(
            """SELECT * FROM earnings_events
               WHERE ticker = ?
               ORDER BY report_date DESC
               LIMIT ?""",
            (ticker, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── Insider Trades ──

    async def upsert_insider_trade(self, trade) -> bool:
        """Insert or update an insider trade. Accepts InsiderTrade dataclass or dict."""
        d = _to_dict(trade) if not isinstance(trade, dict) else trade
        now = time.time()
        await self.db.execute(
            """INSERT INTO insider_trades
               (id, ticker, insider_name, title, trade_type, shares, price,
                value, filing_date, transaction_date, source, meta, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   shares = excluded.shares,
                   price = excluded.price,
                   value = excluded.value,
                   meta = excluded.meta""",
            (
                d.get("id", ""),
                d.get("ticker", ""),
                d.get("insider_name", ""),
                d.get("title", ""),
                d.get("trade_type", "buy"),
                d.get("shares", 0),
                d.get("price", 0.0),
                d.get("value", 0.0),
                d.get("filing_date", 0),
                d.get("transaction_date"),
                d.get("source", "form4"),
                json.dumps(d.get("meta", {})),
                now,
            ),
        )
        await self.db.commit()
        return True

    async def query_insider_trades(
        self,
        ticker: Optional[str] = None,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        trade_type: Optional[str] = None,
        source: Optional[str] = None,
        min_value: Optional[int] = None,
        order: str = "desc",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query insider trades with filters."""
        clauses: List[str] = []
        params: list = []

        if ticker:
            clauses.append("ticker = ?")
            params.append(ticker)
        if start_ts is not None:
            clauses.append("filing_date >= ?")
            params.append(start_ts)
        if end_ts is not None:
            clauses.append("filing_date <= ?")
            params.append(end_ts)
        if trade_type:
            clauses.append("trade_type = ?")
            params.append(trade_type)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if min_value is not None:
            clauses.append("value >= ?")
            params.append(min_value)

        where = " AND ".join(clauses) if clauses else "1=1"
        direction = "DESC" if order == "desc" else "ASC"
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            SELECT * FROM insider_trades
            WHERE {where}
            ORDER BY filing_date {direction}
            LIMIT ?
        """
        params.append(limit)

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_signals_for_ticker(
        self, ticker: str, limit: int = 10, days: int = 7,
    ) -> List[Dict[str, Any]]:
        """Get recent signals for a ticker (used by insider cross-reference)."""
        cutoff = time.time() - days * 86400
        async with self.db.execute(
            """SELECT id, stance, confidence, created_at
               FROM signals
               WHERE ticker = ? AND created_at >= ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (ticker, cutoff, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── FOMC Meetings ──

    async def upsert_fomc_meeting(self, meeting) -> bool:
        """Insert or update a FOMC meeting. Accepts FOMCMeeting dataclass or dict."""
        d = _to_dict(meeting) if not isinstance(meeting, dict) else meeting
        now = time.time()
        await self.db.execute(
            """INSERT INTO fomc_meetings
               (id, meeting_date, rate_decision, rate_before, rate_after,
                statement_text, statement_diff, hawkish_score, dovish_score,
                dot_plot_median, meta, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   rate_decision = excluded.rate_decision,
                   rate_after = excluded.rate_after,
                   statement_text = excluded.statement_text,
                   statement_diff = excluded.statement_diff,
                   hawkish_score = excluded.hawkish_score,
                   dovish_score = excluded.dovish_score,
                   dot_plot_median = excluded.dot_plot_median,
                   meta = excluded.meta""",
            (
                d.get("id", ""),
                d.get("meeting_date", 0),
                d.get("rate_decision", ""),
                d.get("rate_before", 0.0),
                d.get("rate_after", 0.0),
                d.get("statement_text", ""),
                d.get("statement_diff", ""),
                d.get("hawkish_score", 0.0),
                d.get("dovish_score", 0.0),
                d.get("dot_plot_median"),
                json.dumps(d.get("meta", {})),
                now,
            ),
        )
        await self.db.commit()
        return True

    async def get_next_fomc_meeting(self, after_ts: float) -> Optional[Dict[str, Any]]:
        """Get the next FOMC meeting after a given timestamp."""
        async with self.db.execute(
            """SELECT * FROM fomc_meetings
               WHERE meeting_date >= ?
               ORDER BY meeting_date ASC
               LIMIT 1""",
            (after_ts,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def query_fomc_meetings(
        self, limit: int = 20, order: str = "desc",
    ) -> List[Dict[str, Any]]:
        """Query FOMC meetings."""
        # Validate order parameter to prevent SQL injection
        if order not in ("desc", "asc"):
            raise ValueError(f"Invalid order parameter: {order}")
        direction = "DESC" if order == "desc" else "ASC"
        async with self.db.execute(
            f"""SELECT * FROM fomc_meetings
                ORDER BY meeting_date {direction}
                LIMIT ?""",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_fomc_meeting(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        """Get a single FOMC meeting by ID."""
        async with self.db.execute(
            "SELECT * FROM fomc_meetings WHERE id = ?", (meeting_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    # ── Event Impact Cache ──

    async def get_event_impact_cache(self, event_type: str) -> Optional[Dict[str, Any]]:
        """Get cached event impact analysis."""
        async with self.db.execute(
            "SELECT * FROM event_impact_cache WHERE event_type = ?", (event_type,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def save_event_impact_cache(
        self,
        event_type: str,
        avg_spy_move: float,
        avg_vix_change: float,
        sample_size: int,
        reactions_json: Any,
        sector_sensitivity: Any,
    ) -> None:
        """Save or update event impact cache."""
        now = time.time()
        reactions_str = json.dumps(
            [_to_dict(r) if not isinstance(r, dict) else r for r in reactions_json]
        ) if isinstance(reactions_json, list) else json.dumps(reactions_json)
        sectors_str = json.dumps(sector_sensitivity) if isinstance(
            sector_sensitivity, (list, dict)
        ) else str(sector_sensitivity)
        await self.db.execute(
            """INSERT INTO event_impact_cache
               (event_type, avg_spy_move, avg_vix_change, sample_size,
                reactions_json, sector_sensitivity_json, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(event_type) DO UPDATE SET
                   avg_spy_move = excluded.avg_spy_move,
                   avg_vix_change = excluded.avg_vix_change,
                   sample_size = excluded.sample_size,
                   reactions_json = excluded.reactions_json,
                   sector_sensitivity_json = excluded.sector_sensitivity_json,
                   computed_at = excluded.computed_at""",
            (event_type, avg_spy_move, avg_vix_change, sample_size,
             reactions_str, sectors_str, now),
        )
        await self.db.commit()

    # ── Congress Trades ──

    async def get_congress_trades(
        self, days: int = 30, limit: int = 100, ticker: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get congressional trades from the congress_trades table."""
        cutoff = time.time() - (days * 86400)
        conditions = ["filed_at > ?"]
        params: list = [cutoff]
        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker.upper())
        where = " AND ".join(conditions)
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            SELECT * FROM congress_trades
            WHERE {where}
            ORDER BY filed_at DESC LIMIT ?
        """
        params.append(limit)
        try:
            async with self.db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception:
            return []

    async def insert_congress_trade(self, trade: Dict[str, Any]) -> Optional[str]:
        """Insert a congressional trade record."""
        import uuid
        trade_id = str(uuid.uuid4())[:12]
        now = time.time()
        await self.db.execute(
            """INSERT OR IGNORE INTO congress_trades
               (id, politician, party, chamber, ticker, trade_type, amount_range,
                filed_at, disclosure_date, source_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade_id,
                trade.get("politician", ""),
                trade.get("party", ""),
                trade.get("chamber", ""),
                trade.get("ticker", "").upper(),
                trade.get("trade_type", ""),
                trade.get("amount_range", ""),
                trade.get("filed_at", now),
                trade.get("disclosure_date", ""),
                trade.get("source_url", ""),
                now,
            ),
        )
        await self.db.commit()
        return trade_id

    async def get_congress_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get summary stats for congressional trading."""
        cutoff = time.time() - (days * 86400)
        try:
            async with self.db.execute(
                """SELECT COUNT(*) as total_trades,
                          COUNT(DISTINCT politician) as politicians,
                          COUNT(DISTINCT ticker) as tickers,
                          SUM(CASE WHEN trade_type = 'purchase' THEN 1 ELSE 0 END) as buys,
                          SUM(CASE WHEN trade_type = 'sale' THEN 1 ELSE 0 END) as sells
                   FROM congress_trades WHERE filed_at > ?""",
                (cutoff,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else {}
        except Exception:
            return {}

    async def purge_old_congress_trades(self, keep_days: int = 90) -> int:
        """Delete congressional trades older than keep_days."""
        cutoff = time.time() - (keep_days * 86400)
        try:
            async with self.db.execute(
                "DELETE FROM congress_trades WHERE filed_at < ?", (cutoff,)
            ) as cursor:
                count = cursor.rowcount
            await self.db.commit()
            return count
        except Exception:
            return 0

    # ── Macro Purge ──

    async def purge_old_macro_events(self, keep_days: int = 365) -> int:
        """Purge old macro events older than keep_days. Returns count deleted."""
        cutoff = time.time() - keep_days * 86400
        cursor = await self.db.execute(
            "DELETE FROM macro_events WHERE scheduled_at < ?", (cutoff,)
        )
        deleted = cursor.rowcount
        await self.db.commit()
        return deleted

    async def purge_old_insider_trades(self, keep_days: int = 365) -> int:
        """Purge old insider trades older than keep_days. Returns count deleted."""
        cutoff = time.time() - keep_days * 86400
        cursor = await self.db.execute(
            "DELETE FROM insider_trades WHERE filing_date < ?", (cutoff,)
        )
        deleted = cursor.rowcount
        await self.db.commit()
        return deleted

    async def purge_old_earnings_events(self, keep_days: int = 365) -> int:
        """Purge old earnings events older than keep_days. Returns count deleted."""
        cutoff = time.time() - keep_days * 86400
        cursor = await self.db.execute(
            "DELETE FROM earnings_events WHERE report_date < ?", (cutoff,)
        )
        deleted = cursor.rowcount
        await self.db.commit()
        return deleted
