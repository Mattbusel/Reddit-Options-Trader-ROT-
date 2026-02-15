"""
Performance Tracking & Analytics Mixin

This module contains all performance-related database methods for the ROT system.
Handles win/loss tracking, accuracy metrics, confidence calibration, strategy P&L,
and historical performance analysis.

Performance data comes from two sources:
1. Live data: signals + signal_performance tables (recent signals within purge window)
2. Archived data: signal_archive table (older signals preserved for long-term analytics)

The _UNIFIED_CTE from sql_helpers transparently unions both sources for seamless querying.

Performance tracking assumptions:
- Assumes self.db (aiosqlite Connection) exists in the class using this mixin
- Uses stance-aware win/loss logic (bullish wins on upward moves, bearish on downward)
- 0.5% minimum movement threshold to filter out noise within bid-ask spread
- Mixed/unknown stances are always neutral (no directional bet)

18 methods:
- get_performance_summary: aggregate stats (total signals, win rate, confidence)
- get_performance_for_signal: per-signal performance record
- get_performance_history: chronological signal history with outcomes
- get_performance_csv_data: detailed export data
- get_accuracy_over_time: time-bucketed win rate series
- get_aggregate_accuracy: overall win/loss stats with snapshots
- get_accuracy_by_confidence: win rate by confidence bucket
- get_accuracy_by_event_type: win rate by event category
- get_accuracy_by_strategy: win rate by options strategy
- get_confidence_calibration: expected vs actual win rate by decile
- get_strategy_pnl: P&L breakdown by strategy
- get_performance_by_ticker: per-ticker performance breakdown
- snapshot_win_rate_before_purge: preserve win/loss counts before signal deletion
- get_cumulative_win_rate: aggregate win/loss from snapshots
- recalculate_stance_aware_gains: one-time migration to fix old records
- insert_signal_performance: record initial price when signal created
- get_unchecked_performances: find signals needing price updates
- update_performance_prices: update price columns after tracking
"""

import logging
import time
from typing import Any, Dict, List, Optional

from .sql_helpers import (
    _A_LOSS_SQL,
    _A_NEUTRAL_SQL,
    _A_PRICE_COL,
    _A_WIN_SQL,
    _LOSS_CASE_SQL,
    _LOSS_SQL,
    _NEUTRAL_SQL,
    _PRICE_COL,
    _UNIFIED_CTE,
    _WIN_CASE_SQL,
    _WIN_SQL,
)

log = logging.getLogger(__name__)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert sqlite3.Row to dict."""
    if row is None:
        return {}
    return dict(row)


class PerformanceMixin:
    """Performance tracking & analytics (18 methods). Assumes self.db (aiosqlite Connection) exists."""

    # ── Summary & Overview ──

    async def get_performance_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get aggregate performance stats for the dashboard overview card.

        Returns total signals, avg confidence, stance distribution, unique tickers,
        signals today/7d, high-confidence count, tradeable signals (bullish/bearish only).

        Args:
            days: Number of days to look back (default 30)

        Returns:
            Dict with keys: total_signals, avg_confidence, tradeable_signals,
            bullish_count, bearish_count, mixed_count, signals_today, signals_7d,
            high_conf_count, unique_tickers, unique_sources, daily_avg
        """
        cutoff = time.time() - (days * 86400)
        now = time.time()
        cutoff_24h = now - 86400
        cutoff_7d = now - 7 * 86400
        query = """
            SELECT
                COUNT(*) as total_signals,
                AVG(confidence) as avg_confidence,
                SUM(CASE WHEN stance IN ('bullish', 'bearish') THEN 1 ELSE 0 END) as tradeable_signals,
                SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish_count,
                SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish_count,
                SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed_count,
                SUM(CASE WHEN created_at > ? THEN 1 ELSE 0 END) as signals_today,
                SUM(CASE WHEN created_at > ? THEN 1 ELSE 0 END) as signals_7d,
                SUM(CASE WHEN confidence >= 0.5 THEN 1 ELSE 0 END) as high_conf_count,
                SUM(CASE WHEN strategy = 'debit_spread' THEN 1
                         WHEN strategy = 'credit_spread' THEN 1
                         WHEN strategy = 'long_call' OR strategy = 'long_put' THEN 1
                         ELSE 0 END) as _strat_dummy,
                COUNT(DISTINCT ticker) as unique_tickers,
                COUNT(DISTINCT subreddit) as unique_sources
            FROM signals
            WHERE created_at > ?
        """
        async with self.db.execute(query, (cutoff_24h, cutoff_7d, cutoff)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {"total_signals": 0}
            d = _row_to_dict(row)
            total = d.get("total_signals", 0) or 0
            d["daily_avg"] = round(total / max(days, 1), 1)
            return d

    async def get_aggregate_accuracy(
        self, days: int = 7, ticker: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get aggregate win/loss stats for signal performance.

        Uses the best available price snapshot (1d > 4h > 1h) for evaluation.
        Applies a 0.5% minimum movement threshold — price changes below
        this are classified as neutral (noise within bid-ask spread).

        Merges live signal data with historical snapshots (non-ticker queries only).

        Args:
            days: Number of days to look back (default 7)
            ticker: Optional ticker filter (default None = all tickers)

        Returns:
            Dict with keys: total_tracked, winners, losers, neutral, win_rate,
            avg_gain_pct, avg_loss_pct, avg_1d_return_pct
        """
        cutoff = time.time() - (days * 86400)
        conditions = ["s.created_at > ?"]
        params: list = [cutoff]

        if ticker:
            conditions.append("sp.ticker = ?")
            params.append(ticker.upper())

        where = f"WHERE {' AND '.join(conditions)}"
        # Stance-aware win/loss evaluation: bullish/bearish only
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            SELECT
                COUNT(*) as total_tracked,
                SUM({_WIN_SQL}) as winners,
                SUM({_LOSS_SQL}) as losers,
                SUM({_NEUTRAL_SQL}) as neutral,
                AVG(sp.max_gain_pct) as avg_gain_pct,
                AVG(sp.max_loss_pct) as avg_loss_pct,
                AVG(CASE WHEN sp.price_1d IS NOT NULL
                    THEN CASE WHEN s.stance = 'bearish'
                        THEN (1.0 - sp.price_1d / sp.price_at_signal) * 100
                        ELSE (sp.price_1d / sp.price_at_signal - 1.0) * 100
                    END
                    ELSE NULL END) as avg_1d_return_pct
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            {where}
            AND sp.price_at_signal > 0
            AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                 OR sp.max_gain_pct IS NOT NULL)
        """
        async with self.db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if not row:
                d = {"total_tracked": 0, "winners": 0, "losers": 0,
                     "win_rate": 0, "avg_gain_pct": 0, "avg_loss_pct": 0,
                     "neutral": 0}
            else:
                d = _row_to_dict(row)

        # Merge in snapshot data (only for non-ticker-filtered queries)
        if not ticker:
            snap = await self.get_cumulative_win_rate(days=days)
            snap_w = snap.get("winners", 0) or 0
            snap_l = snap.get("losers", 0) or 0
            snap_n = snap.get("neutral", 0) or 0
            snap_total = snap.get("total_tracked", 0) or 0
            if snap_total > 0:
                d["winners"] = (d.get("winners", 0) or 0) + snap_w
                d["losers"] = (d.get("losers", 0) or 0) + snap_l
                d["neutral"] = (d.get("neutral", 0) or 0) + snap_n
                d["total_tracked"] = (d.get("total_tracked", 0) or 0) + snap_total

        winners = d.get("winners", 0) or 0
        losers = d.get("losers", 0) or 0
        decided = winners + losers
        d["win_rate"] = (winners / decided * 100) if decided > 0 else 0
        return d

    # ── Signal-Level Performance Records ──

    async def insert_signal_performance(
        self, signal_id: str, ticker: str, price_at_signal: float
    ) -> None:
        """Record initial price when a signal is first created.

        Args:
            signal_id: UUID of the signal
            ticker: Ticker symbol
            price_at_signal: Initial price when signal was generated
        """
        now = time.time()
        await self.db.execute(
            """INSERT INTO signal_performance
               (signal_id, ticker, price_at_signal, created_at, checked_at)
               VALUES (?, ?, ?, ?, ?)""",
            (signal_id, ticker, price_at_signal, now, now),
        )
        await self.db.commit()

    async def get_performance_for_signal(
        self, signal_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get performance record for a specific signal.

        Args:
            signal_id: UUID of the signal

        Returns:
            Dict with performance data or None if not found
        """
        async with self.db.execute(
            "SELECT * FROM signal_performance WHERE signal_id = ?", (signal_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    async def get_unchecked_performances(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Find performance records that still need price updates.

        Returns signals where at least one of the price checkpoints
        (1h, 4h, 1d, 1w) is still NULL and needs to be updated.

        Args:
            limit: Max number of records to return (default 50)

        Returns:
            List of dicts with performance + signal data
        """
        query = """
            SELECT sp.*, s.created_at as signal_created_at, s.stance as signal_stance
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE sp.price_1h IS NULL OR sp.price_4h IS NULL
                  OR sp.price_1d IS NULL OR sp.price_1w IS NULL
            ORDER BY s.created_at ASC
            LIMIT ?
        """
        async with self.db.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                # Use signal_created_at for age calculation
                if d.get("signal_created_at"):
                    d["created_at"] = d["signal_created_at"]
                results.append(d)
            return results

    async def update_performance_prices(
        self, perf_id: int, updates: Dict[str, Any]
    ) -> None:
        """Update price columns for a performance record.

        Args:
            perf_id: ID of the performance record
            updates: Dict of column_name: value pairs to update
                     (price_1h, price_4h, price_1d, price_1w, max_gain_pct,
                      max_loss_pct, checked_at)
        """
        set_clauses = []
        params = []
        for col in ("price_1h", "price_4h", "price_1d", "price_1w",
                     "max_gain_pct", "max_loss_pct", "checked_at"):
            if col in updates:
                set_clauses.append(f"{col} = ?")
                params.append(updates[col])
        if not set_clauses:
            return
        params.append(perf_id)
        query = f"UPDATE signal_performance SET {', '.join(set_clauses)} WHERE id = ?"  # nosec B608 - SQL uses constants only, values parameterized
        await self.db.execute(query, params)
        await self.db.commit()

    async def recalculate_stance_aware_gains(self) -> int:
        """One-time recalculation of max_gain_pct/max_loss_pct with stance awareness.

        Fixes old records that were calculated without considering signal stance.
        Bearish signals have their price deltas inverted so that downward moves
        count as gains and upward moves as losses.

        Returns:
            Number of records updated
        """
        query = """
            SELECT sp.id, sp.price_at_signal, sp.price_1h, sp.price_4h,
                   sp.price_1d, sp.price_1w, s.stance
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE sp.price_at_signal > 0
              AND (sp.price_1h IS NOT NULL OR sp.price_4h IS NOT NULL
                   OR sp.price_1d IS NOT NULL OR sp.price_1w IS NOT NULL)
        """
        updated = 0
        async with self.db.execute(query) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                d = dict(row)
                price_at = d["price_at_signal"]
                stance = d.get("stance", "bullish")
                tracked = []
                for key in ("price_1h", "price_4h", "price_1d", "price_1w"):
                    if d.get(key) is not None:
                        tracked.append(d[key])
                if not tracked:
                    continue
                raw_pcts = [(p / price_at - 1.0) * 100 for p in tracked]
                if stance == "bearish":
                    pcts = [-pct for pct in raw_pcts]
                else:
                    pcts = raw_pcts
                new_gain = max(pcts)
                new_loss = min(pcts)
                await self.db.execute(
                    "UPDATE signal_performance SET max_gain_pct = ?, max_loss_pct = ? WHERE id = ?",
                    (new_gain, new_loss, d["id"]),
                )
                updated += 1
        if updated > 0:
            await self.db.commit()
            log.info("Recalculated stance-aware gains for %d performance records", updated)
        return updated

    # ── Historical Performance Queries (uses _UNIFIED_CTE for live + archived data) ──

    async def get_performance_history(
        self, days: int = 30, ticker: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get per-signal performance records.

        Uses _UNIFIED_CTE to transparently query both live and archived signals.

        Args:
            days: Number of days to look back (default 30)
            ticker: Optional ticker filter (default None = all tickers)
            limit: Max records to return (default 50)

        Returns:
            List of dicts with signal + performance data
        """
        cutoff = time.time() - (days * 86400)
        conditions = ["created_at > ?"]
        params: list = [cutoff]

        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker.upper())

        where = f"WHERE {' AND '.join(conditions)}"
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT id as signal_id, ticker, created_at,
                   price_at_signal, price_1h, price_4h, price_1d,
                   max_gain_pct, max_loss_pct,
                   stance, confidence, strategy
            FROM _unified
            {where}
            AND price_at_signal > 0
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(limit)
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_performance_csv_data(
        self, days: int = 365, ticker: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get detailed performance data for CSV export.

        Uses _UNIFIED_CTE to include both live and archived signals.

        Args:
            days: Number of days to look back (default 365 for yearly export)
            ticker: Optional ticker filter (default None = all tickers)

        Returns:
            List of dicts with full signal + performance + metadata
        """
        cutoff = time.time() - (days * 86400)
        conditions = ["created_at > ?"]
        params: list = [cutoff]

        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker.upper())

        where = f"WHERE {' AND '.join(conditions)}"
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT id as signal_id, ticker, created_at,
                   price_at_signal, price_1h, price_4h, price_1d,
                   max_gain_pct, max_loss_pct,
                   stance, confidence, strategy,
                   event_type, subreddit, post_title
            FROM _unified
            {where}
            AND price_at_signal > 0
            ORDER BY created_at DESC
        """
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_accuracy_over_time(
        self, days: int = 30, interval: str = "daily"
    ) -> List[Dict[str, Any]]:
        """Get time-bucketed accuracy for performance charts.

        Uses _UNIFIED_CTE to include both live and archived signals.

        Args:
            days: Number of days to look back (default 30)
            interval: Bucket size — "daily" (86400s) or "hourly" (3600s)

        Returns:
            List of dicts with time_bucket, total, winners, avg_gain_pct, avg_loss_pct
        """
        cutoff = time.time() - (days * 86400)
        bucket_s = 86400 if interval == "daily" else 3600
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT
                CAST(created_at / ? AS INTEGER) * ? as time_bucket,
                COUNT(*) as total,
                SUM({_A_WIN_SQL}) as winners,
                AVG(max_gain_pct) as avg_gain_pct,
                AVG(max_loss_pct) as avg_loss_pct
            FROM _unified
            WHERE created_at > ? AND price_at_signal > 0
                  AND (price_1d IS NOT NULL OR price_4h IS NOT NULL)
            GROUP BY time_bucket
            ORDER BY time_bucket ASC
        """
        async with self.db.execute(query, (bucket_s, bucket_s, cutoff)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    # ── Breakdown by Attributes ──

    async def get_accuracy_by_confidence(self, days: int = 30) -> List[Dict[str, Any]]:
        """Win rate broken down by confidence buckets: <30%, 30-50%, 50-70%, 70%+.

        Uses _UNIFIED_CTE to include both live and archived signals.

        Args:
            days: Number of days to look back (default 30)

        Returns:
            List of dicts with bucket, label, total, winners, losers, win_rate
        """
        cutoff = time.time() - (days * 86400)
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT
                CASE
                    WHEN confidence < 0.3 THEN 'low'
                    WHEN confidence < 0.5 THEN 'mid'
                    WHEN confidence < 0.7 THEN 'high'
                    ELSE 'very_high'
                END as bucket,
                COUNT(*) as total,
                SUM({_A_WIN_SQL}) as winners,
                SUM({_A_LOSS_SQL}) as losers
            FROM _unified
            WHERE created_at > ?
            AND price_at_signal > 0
            AND {_A_PRICE_COL} IS NOT NULL
            GROUP BY bucket
            ORDER BY confidence ASC
        """
        labels = {"low": "<30%", "mid": "30-50%", "high": "50-70%", "very_high": "70%+"}
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                w = d.get("winners", 0) or 0
                l = d.get("losers", 0) or 0
                decided = w + l
                d["win_rate"] = round(w / decided * 100) if decided > 0 else 0
                d["label"] = labels.get(d.get("bucket", ""), "?")
                results.append(d)
            return results

    async def get_accuracy_by_event_type(self, days: int = 30) -> List[Dict[str, Any]]:
        """Win rate broken down by event_type (earnings_rumor, squeeze, etc.).

        Uses _UNIFIED_CTE to include both live and archived signals.

        Args:
            days: Number of days to look back (default 30)

        Returns:
            List of dicts with event_type, total, winners, losers, neutral,
            win_rate, avg_return_pct
        """
        cutoff = time.time() - (days * 86400)
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT
                event_type,
                COUNT(*) as total,
                SUM({_A_WIN_SQL}) as winners,
                SUM({_A_LOSS_SQL}) as losers,
                SUM({_A_NEUTRAL_SQL}) as neutral,
                AVG(CASE WHEN price_1d IS NOT NULL
                    THEN CASE WHEN stance = 'bearish'
                        THEN (1.0 - price_1d / price_at_signal) * 100
                        ELSE (price_1d / price_at_signal - 1.0) * 100
                    END ELSE NULL END) as avg_return_pct
            FROM _unified
            WHERE created_at > ? AND price_at_signal > 0
                  AND {_A_PRICE_COL} IS NOT NULL
            GROUP BY event_type
            ORDER BY total DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                w = d.get("winners", 0) or 0
                l = d.get("losers", 0) or 0
                decided = w + l
                d["win_rate"] = round(w / decided * 100) if decided > 0 else 0
                results.append(d)
            return results

    async def get_accuracy_by_strategy(self, days: int = 30) -> List[Dict[str, Any]]:
        """Win rate broken down by strategy (debit_spread, credit_spread, etc.).

        Uses _UNIFIED_CTE to include both live and archived signals.

        Args:
            days: Number of days to look back (default 30)

        Returns:
            List of dicts with strategy, total, winners, losers, win_rate,
            avg_return_pct, avg_gain_pct (winning trades), avg_loss_pct (losing trades)
        """
        cutoff = time.time() - (days * 86400)
        # stance_return: positive = trade direction was right, negative = wrong
        # Use 1d-only price column for avg_gain/avg_loss (more reliable)
        _a_1d_win = _WIN_CASE_SQL.format(price_col="price_1d").replace("s.stance", "stance").replace("sp.price_at_signal", "price_at_signal")
        _a_1d_loss = _LOSS_CASE_SQL.format(price_col="price_1d").replace("s.stance", "stance").replace("sp.price_at_signal", "price_at_signal")
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT
                strategy,
                COUNT(*) as total,
                SUM({_A_WIN_SQL}) as winners,
                SUM({_A_LOSS_SQL}) as losers,
                AVG(CASE WHEN price_1d IS NOT NULL
                    THEN CASE WHEN stance = 'bearish'
                        THEN (1.0 - price_1d / price_at_signal) * 100
                        ELSE (price_1d / price_at_signal - 1.0) * 100
                    END ELSE NULL END) as avg_return_pct,
                AVG(CASE
                    WHEN price_1d IS NOT NULL AND {_a_1d_win} = 1
                    THEN CASE WHEN stance = 'bearish'
                        THEN (1.0 - price_1d / price_at_signal) * 100
                        ELSE (price_1d / price_at_signal - 1.0) * 100
                    END ELSE NULL END) as avg_gain_pct,
                AVG(CASE
                    WHEN price_1d IS NOT NULL AND {_a_1d_loss} = 1
                    THEN CASE WHEN stance = 'bearish'
                        THEN (1.0 - price_1d / price_at_signal) * 100
                        ELSE (price_1d / price_at_signal - 1.0) * 100
                    END ELSE NULL END) as avg_loss_pct
            FROM _unified
            WHERE created_at > ? AND price_at_signal > 0
                  AND strategy != 'none'
                  AND {_A_PRICE_COL} IS NOT NULL
            GROUP BY strategy
            ORDER BY total DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                w = d.get("winners", 0) or 0
                l = d.get("losers", 0) or 0
                decided = w + l
                d["win_rate"] = round(w / decided * 100) if decided > 0 else 0
                results.append(d)
            return results

    async def get_strategy_pnl(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get P&L breakdown by strategy.

        Uses _UNIFIED_CTE to include both live and archived signals.

        Args:
            days: Number of days to look back (default 30)

        Returns:
            List of dicts with strategy, total, winners, avg_gain_pct,
            avg_loss_pct, avg_1d_return_pct
        """
        cutoff = time.time() - (days * 86400)
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT
                strategy,
                COUNT(*) as total,
                SUM({_A_WIN_SQL}) as winners,
                AVG(max_gain_pct) as avg_gain_pct,
                AVG(max_loss_pct) as avg_loss_pct,
                AVG(CASE WHEN price_1d IS NOT NULL
                    THEN CASE WHEN stance = 'bearish'
                        THEN (1.0 - price_1d / price_at_signal) * 100
                        ELSE (price_1d / price_at_signal - 1.0) * 100
                    END
                    ELSE NULL END) as avg_1d_return_pct
            FROM _unified
            WHERE created_at > ? AND price_at_signal > 0
                  AND strategy != 'none'
            GROUP BY strategy
            ORDER BY total DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_performance_by_ticker(
        self, days: int = 30, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get performance breakdown by ticker.

        Uses _UNIFIED_CTE to include both live and archived signals.

        Args:
            days: Number of days to look back (default 30)
            limit: Max tickers to return (default 20)

        Returns:
            List of dicts with ticker, total_signals, winners,
            avg_gain_pct, avg_loss_pct
        """
        cutoff = time.time() - (days * 86400)
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT
                ticker,
                COUNT(*) as total_signals,
                SUM({_A_WIN_SQL}) as winners,
                AVG(max_gain_pct) as avg_gain_pct,
                AVG(max_loss_pct) as avg_loss_pct
            FROM _unified
            WHERE created_at > ? AND price_at_signal > 0
              AND (price_1d IS NOT NULL OR price_4h IS NOT NULL)
            GROUP BY ticker
            ORDER BY total_signals DESC
            LIMIT ?
        """
        async with self.db.execute(query, (cutoff, limit)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    # ── Confidence Calibration ──

    async def get_confidence_calibration(self, days: int = 90) -> List[Dict[str, Any]]:
        """Expected vs actual win rate by confidence decile for calibration chart.

        Uses _UNIFIED_CTE to include both live and archived signals.
        Groups signals into 10 confidence buckets (0-10%, 10-20%, ..., 90-100%)
        and compares expected win rate (avg confidence) vs actual win rate.

        Args:
            days: Number of days to look back (default 90)

        Returns:
            List of dicts with decile, bucket_label, total, winners, losers,
            avg_confidence, expected_win_rate, actual_win_rate
        """
        cutoff = time.time() - (days * 86400)
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT
                CAST(confidence * 10 AS INTEGER) as decile,
                COUNT(*) as total,
                SUM({_A_WIN_SQL}) as winners,
                SUM({_A_LOSS_SQL}) as losers,
                AVG(confidence) as avg_confidence
            FROM _unified
            WHERE created_at > ? AND price_at_signal > 0
                  AND {_A_PRICE_COL} IS NOT NULL
                  AND stance IN ('bullish', 'bearish')
            GROUP BY decile
            ORDER BY decile ASC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                w = d.get("winners", 0) or 0
                l = d.get("losers", 0) or 0
                decided = w + l
                d["actual_win_rate"] = round(w / decided * 100) if decided > 0 else 0
                d["expected_win_rate"] = round((d.get("avg_confidence", 0) or 0) * 100)
                decile = d.get("decile", 0) or 0
                d["bucket_label"] = f"{decile * 10}-{decile * 10 + 10}%"
                d["label"] = d["bucket_label"]  # backward compat
                results.append(d)
            return results

    # ── Snapshot & Archival ──

    async def snapshot_win_rate_before_purge(self, keep_days: int = 14) -> int:
        """Snapshot win/loss counts for signals that are about to be purged.

        Called BEFORE purge_old_signals so the resolved outcomes are preserved
        permanently in the win_rate_snapshots table. This allows long-term
        historical win rate tracking even after old signals are deleted.

        Args:
            keep_days: Signals older than this will be snapshotted (default 14)

        Returns:
            Number of signals included in the snapshot
        """
        cutoff = time.time() - (keep_days * 86400)
        # Only snapshot signals that will be deleted (older than cutoff)
        # AND that have price data to evaluate
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            SELECT
                COUNT(*) as total_tracked,
                MIN(s.created_at) as period_start,
                MAX(s.created_at) as period_end,
                SUM({_WIN_SQL}) as winners,
                SUM({_LOSS_SQL}) as losers,
                SUM({_NEUTRAL_SQL}) as neutral,
                AVG(sp.max_gain_pct) as avg_gain_pct,
                AVG(sp.max_loss_pct) as avg_loss_pct,
                AVG(CASE WHEN sp.price_1d IS NOT NULL
                    THEN CASE WHEN s.stance = 'bearish'
                        THEN (1.0 - sp.price_1d / sp.price_at_signal) * 100
                        ELSE (sp.price_1d / sp.price_at_signal - 1.0) * 100
                    END
                    ELSE NULL END) as avg_1d_return_pct
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE s.created_at < ?
            AND sp.price_at_signal > 0
            AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                 OR sp.max_gain_pct IS NOT NULL)
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return 0
            d = _row_to_dict(row)

        total = d.get("total_tracked", 0) or 0
        if total == 0:
            return 0

        now = time.time()
        await self.db.execute(
            """INSERT INTO win_rate_snapshots
               (snapshot_at, period_start, period_end, winners, losers, neutral,
                total_tracked, avg_gain_pct, avg_loss_pct, avg_1d_return_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                d.get("period_start", 0) or 0,
                d.get("period_end", 0) or 0,
                d.get("winners", 0) or 0,
                d.get("losers", 0) or 0,
                d.get("neutral", 0) or 0,
                total,
                d.get("avg_gain_pct"),
                d.get("avg_loss_pct"),
                d.get("avg_1d_return_pct"),
            ),
        )
        await self.db.commit()
        log.info(
            "Win-rate snapshot: %dW / %dL / %dN (total %d) from signals before %d days",
            d.get("winners", 0) or 0,
            d.get("losers", 0) or 0,
            d.get("neutral", 0) or 0,
            total,
            keep_days,
        )
        return total

    async def get_cumulative_win_rate(self, days: int = 30) -> Dict[str, Any]:
        """Get cumulative win/loss from snapshots, optionally filtered by time range.

        Reads from the win_rate_snapshots table to retrieve historical win/loss
        data for signals that have already been purged.

        Args:
            days: Number of days to look back (default 30). Use 0 for all-time stats.

        Returns:
            Dict with keys: winners, losers, neutral, total_tracked,
            avg_gain_pct, avg_loss_pct, avg_1d_return_pct
        """
        if days > 0:
            cutoff = time.time() - (days * 86400)
            query = """
                SELECT
                    COALESCE(SUM(winners), 0) as winners,
                    COALESCE(SUM(losers), 0) as losers,
                    COALESCE(SUM(neutral), 0) as neutral,
                    COALESCE(SUM(total_tracked), 0) as total_tracked,
                    AVG(avg_gain_pct) as avg_gain_pct,
                    AVG(avg_loss_pct) as avg_loss_pct,
                    AVG(avg_1d_return_pct) as avg_1d_return_pct
                FROM win_rate_snapshots
                WHERE period_end > ?
            """
            params = (cutoff,)
        else:
            query = """
                SELECT
                    COALESCE(SUM(winners), 0) as winners,
                    COALESCE(SUM(losers), 0) as losers,
                    COALESCE(SUM(neutral), 0) as neutral,
                    COALESCE(SUM(total_tracked), 0) as total_tracked,
                    AVG(avg_gain_pct) as avg_gain_pct,
                    AVG(avg_loss_pct) as avg_loss_pct,
                    AVG(avg_1d_return_pct) as avg_1d_return_pct
                FROM win_rate_snapshots
            """
            params = ()
        async with self.db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else {
                "winners": 0, "losers": 0, "neutral": 0, "total_tracked": 0
            }
