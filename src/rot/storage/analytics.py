"""
Chart data, heatmaps, sector, correlations, leaderboards.

Assumes self.db (aiosqlite Connection) exists.
"""
import time
from typing import Any, Dict, List

from .sql_helpers import _row_to_dict


class AnalyticsMixin:
    """Mixin providing analytics and visualization query methods.

    Reads from signals, signal_performance, signal_archive tables.
    Requires self.db to be an open aiosqlite.Connection.
    """

    # ── Trending & Summary ──

    async def get_trending_tickers(self, hours: int = 24, limit: int = 20) -> List[Dict[str, Any]]:
        """Get top tickers by signal count and confidence."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT ticker,
                   COUNT(*) as signal_count,
                   AVG(confidence) as avg_confidence,
                   MAX(trend_score) as max_trend_score,
                   GROUP_CONCAT(DISTINCT stance) as stances,
                   MAX(created_at) as latest_at
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            GROUP BY ticker
            ORDER BY signal_count DESC, avg_confidence DESC
            LIMIT ?
        """
        async with self.db.execute(query, (cutoff, limit)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_performance_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get high-level performance stats (signal counts, stance breakdown, confidence)."""
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

    async def get_strategy_breakdown(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get top strategies by count for the stat card."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT strategy, COUNT(*) as cnt
            FROM signals
            WHERE created_at > ? AND strategy != 'none' AND strategy != ''
            GROUP BY strategy
            ORDER BY cnt DESC
            LIMIT 4
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(r) for r in rows]

    # ── Chart Data ──

    async def get_chart_data(self, hours: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
        """Aggregated ticker data for quadrant bubble chart."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                ticker,
                AVG(confidence) as avg_confidence,
                MAX(trend_score) as max_trend_score,
                COUNT(*) as signal_count,
                SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish_count,
                SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish_count,
                SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed_count,
                GROUP_CONCAT(DISTINCT strategy) as strategies
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            GROUP BY ticker
            HAVING signal_count > 0
            ORDER BY signal_count DESC, avg_confidence DESC
            LIMIT ?
        """
        async with self.db.execute(query, (cutoff, limit)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                # Determine dominant stance
                bc = d.get("bullish_count", 0) or 0
                brc = d.get("bearish_count", 0) or 0
                mc = d.get("mixed_count", 0) or 0
                if bc >= brc and bc >= mc:
                    d["dominant_stance"] = "bullish"
                elif brc > bc and brc >= mc:
                    d["dominant_stance"] = "bearish"
                else:
                    d["dominant_stance"] = "mixed"
                results.append(d)
            return results

    async def get_time_series_data(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Hourly signal counts for timeline chart."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                CAST(created_at / 3600 AS INTEGER) * 3600 as hour_bucket,
                COUNT(*) as total,
                SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed
            FROM signals
            WHERE created_at > ?
            GROUP BY hour_bucket
            ORDER BY hour_bucket ASC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    # ── Sector Analytics ──

    async def get_sector_rotation_data(self, days: int = 30) -> List[Dict[str, Any]]:
        """Sector-level signal aggregation with win rate for rotation insights."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT
                s.sector,
                COUNT(*) as total_signals,
                SUM(CASE WHEN s.stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN s.stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                AVG(s.confidence) as avg_confidence,
                COUNT(DISTINCT s.ticker) as unique_tickers,
                GROUP_CONCAT(DISTINCT s.ticker) as top_tickers
            FROM signals s
            WHERE s.created_at > ? AND s.sector != '' AND s.ticker != 'UNKNOWN'
            GROUP BY s.sector
            HAVING total_signals >= 2
            ORDER BY total_signals DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                bull = d.get("bullish", 0) or 0
                bear = d.get("bearish", 0) or 0
                total = bull + bear
                d["bullish_pct"] = round(bull / total * 100) if total > 0 else 50
                if d.get("top_tickers"):
                    d["top_tickers"] = d["top_tickers"].split(",")[:5]
                else:
                    d["top_tickers"] = []
                results.append(d)
            return results

    async def get_sector_rotation_with_performance(self, days: int = 30) -> List[Dict[str, Any]]:
        """Sector rotation with win rate overlay."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT
                s.sector,
                COUNT(*) as total_signals,
                SUM(CASE WHEN s.stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN s.stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                AVG(s.confidence) as avg_confidence,
                SUM(CASE
                    WHEN sp.price_at_signal > 0 AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                    THEN CASE
                        WHEN s.stance = 'bearish'
                             AND (sp.price_at_signal - COALESCE(sp.price_1d, sp.price_4h, sp.price_1h))
                                 / sp.price_at_signal > 0.005 THEN 1
                        WHEN s.stance = 'bullish'
                             AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) - sp.price_at_signal)
                                 / sp.price_at_signal > 0.005 THEN 1
                        ELSE 0
                    END ELSE NULL END) as winners,
                SUM(CASE
                    WHEN sp.price_at_signal > 0 AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                    THEN 1 ELSE 0 END) as tracked
            FROM signals s
            LEFT JOIN signal_performance sp ON sp.signal_id = s.id
            WHERE s.created_at > ? AND s.sector != '' AND s.ticker != 'UNKNOWN'
            GROUP BY s.sector
            HAVING total_signals >= 2
            ORDER BY total_signals DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                bull = d.get("bullish", 0) or 0
                bear = d.get("bearish", 0) or 0
                total = bull + bear
                d["bullish_pct"] = round(bull / total * 100) if total > 0 else 50
                w = d.get("winners", 0) or 0
                tracked = d.get("tracked", 0) or 0
                d["win_rate"] = round(w / tracked * 100) if tracked > 0 else None
                results.append(d)
            return results

    async def get_sector_heatmap_data(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get sector-level signal aggregation for heatmap."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                sector,
                COUNT(*) as signal_count,
                AVG(confidence) as avg_confidence,
                SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish_count,
                SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish_count,
                SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed_count,
                GROUP_CONCAT(DISTINCT ticker) as tickers
            FROM signals
            WHERE created_at > ? AND sector != '' AND ticker != 'UNKNOWN'
            GROUP BY sector
            ORDER BY signal_count DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_sector_drill_down(
        self, sector: str, hours: int = 24
    ) -> List[Dict[str, Any]]:
        """Get ticker-level data within a sector."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                ticker,
                COUNT(*) as signal_count,
                AVG(confidence) as avg_confidence,
                MAX(trend_score) as max_trend_score,
                GROUP_CONCAT(DISTINCT stance) as stances
            FROM signals
            WHERE created_at > ? AND sector = ? AND ticker != 'UNKNOWN'
            GROUP BY ticker
            ORDER BY signal_count DESC
            LIMIT 20
        """
        async with self.db.execute(query, (cutoff, sector)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_sector_time_series(
        self, days: int = 30, bucket_hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """Time-bucketed sector signal counts for rotation timeline."""
        cutoff = time.time() - (days * 86400)
        bucket_s = bucket_hours * 3600
        query = """
            SELECT
                sector,
                CAST((created_at / ?) AS INTEGER) as bucket,
                COUNT(*) as signal_count,
                SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                AVG(confidence) as avg_confidence
            FROM signals
            WHERE created_at > ? AND sector != '' AND ticker != 'UNKNOWN'
            GROUP BY sector, bucket
            ORDER BY bucket, sector
        """
        async with self.db.execute(query, (bucket_s, cutoff)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                d["timestamp"] = d["bucket"] * bucket_s
                results.append(d)
            return results

    async def get_sector_ticker_breakdown(
        self, sector: str, days: int = 30,
    ) -> List[Dict[str, Any]]:
        """Tickers within a sector with signal count and performance."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT
                s.ticker,
                COUNT(*) as signal_count,
                SUM(CASE WHEN s.stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN s.stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                AVG(s.confidence) as avg_confidence,
                MAX(s.created_at) as latest_at,
                SUM(CASE
                    WHEN sp.price_at_signal > 0 AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                    THEN CASE
                        WHEN s.stance = 'bearish'
                             AND (sp.price_at_signal - COALESCE(sp.price_1d, sp.price_4h, sp.price_1h))
                                 / sp.price_at_signal > 0.005 THEN 1
                        WHEN s.stance = 'bullish'
                             AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) - sp.price_at_signal)
                                 / sp.price_at_signal > 0.005 THEN 1
                        ELSE 0
                    END ELSE NULL END) as winners,
                SUM(CASE WHEN sp.price_at_signal IS NOT NULL
                         AND (sp.price_1h IS NOT NULL OR sp.price_1d IS NOT NULL)
                    THEN 1 ELSE 0 END) as tracked
            FROM signals s
            LEFT JOIN signal_performance sp ON sp.signal_id = s.id
            WHERE s.created_at > ? AND s.sector = ? AND s.ticker != 'UNKNOWN'
            GROUP BY s.ticker
            ORDER BY signal_count DESC
            LIMIT 20
        """
        async with self.db.execute(query, (cutoff, sector)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                w = d.get("winners", 0) or 0
                tracked = d.get("tracked", 0) or 0
                d["win_rate"] = round(w / tracked * 100) if tracked > 0 else None
                results.append(d)
            return results

    async def get_sector_performance_ranked(
        self, days: int = 30,
    ) -> List[Dict[str, Any]]:
        """All sectors ranked by win rate + signal count."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT
                s.sector,
                COUNT(*) as total_signals,
                SUM(CASE WHEN s.stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN s.stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                AVG(s.confidence) as avg_confidence,
                COUNT(DISTINCT s.ticker) as unique_tickers,
                SUM(CASE
                    WHEN sp.price_at_signal > 0 AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                    THEN CASE
                        WHEN s.stance = 'bearish'
                             AND (sp.price_at_signal - COALESCE(sp.price_1d, sp.price_4h, sp.price_1h))
                                 / sp.price_at_signal > 0.005 THEN 1
                        WHEN s.stance = 'bullish'
                             AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) - sp.price_at_signal)
                                 / sp.price_at_signal > 0.005 THEN 1
                        ELSE 0
                    END ELSE NULL END) as winners,
                SUM(CASE WHEN sp.price_at_signal IS NOT NULL
                         AND (sp.price_1h IS NOT NULL OR sp.price_1d IS NOT NULL)
                    THEN 1 ELSE 0 END) as tracked
            FROM signals s
            LEFT JOIN signal_performance sp ON sp.signal_id = s.id
            WHERE s.created_at > ? AND s.sector != '' AND s.ticker != 'UNKNOWN'
            GROUP BY s.sector
            HAVING total_signals >= 2
            ORDER BY tracked DESC, winners DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                bull = d.get("bullish", 0) or 0
                bear = d.get("bearish", 0) or 0
                total = bull + bear
                d["bullish_pct"] = round(bull / total * 100) if total > 0 else 50
                w = d.get("winners", 0) or 0
                tracked = d.get("tracked", 0) or 0
                d["win_rate"] = round(w / tracked * 100) if tracked > 0 else None
                results.append(d)
            return results

    # ── Leaderboard ──

    async def get_leaderboard(
        self, hours: int = 24, limit: int = 20, sort_by: str = "signal_count"
    ) -> List[Dict[str, Any]]:
        """Get ticker leaderboard ranked by various metrics."""
        cutoff = time.time() - (hours * 3600)
        valid_sorts = {"signal_count", "avg_confidence", "max_trend_score"}
        order = sort_by if sort_by in valid_sorts else "signal_count"
        query = f"""
            SELECT
                ticker,
                COUNT(*) as signal_count,
                AVG(confidence) as avg_confidence,
                MAX(trend_score) as max_trend_score,
                GROUP_CONCAT(DISTINCT stance) as stances,
                GROUP_CONCAT(DISTINCT strategy) as strategies,
                MAX(created_at) as latest_at
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            GROUP BY ticker
            ORDER BY {order} DESC
            LIMIT ?
        """
        async with self.db.execute(query, (cutoff, limit)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_leaderboard_with_performance(
        self, hours: int = 24, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get leaderboard with win rate from performance data."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                s.ticker,
                COUNT(DISTINCT s.id) as signal_count,
                AVG(s.confidence) as avg_confidence,
                MAX(s.trend_score) as max_trend_score,
                GROUP_CONCAT(DISTINCT s.stance) as stances,
                COUNT(CASE
                    WHEN sp.price_at_signal IS NOT NULL AND sp.price_1d IS NOT NULL THEN
                        CASE WHEN (s.stance = 'bearish' AND sp.price_1d < sp.price_at_signal)
                                  OR (s.stance != 'bearish' AND sp.price_1d > sp.price_at_signal)
                             THEN 1 END
                    WHEN sp.price_at_signal IS NOT NULL AND sp.price_1h IS NOT NULL THEN
                        CASE WHEN (s.stance = 'bearish' AND sp.price_1h < sp.price_at_signal)
                                  OR (s.stance != 'bearish' AND sp.price_1h > sp.price_at_signal)
                             THEN 1 END
                    END) as perf_winners,
                COUNT(CASE WHEN sp.price_at_signal IS NOT NULL
                           AND (sp.price_1h IS NOT NULL OR sp.price_1d IS NOT NULL)
                      THEN 1 END) as perf_tracked
            FROM signals s
            LEFT JOIN signal_performance sp ON s.id = sp.signal_id
            WHERE s.created_at > ? AND s.ticker != 'UNKNOWN'
            GROUP BY s.ticker
            ORDER BY signal_count DESC
            LIMIT ?
        """
        async with self.db.execute(query, (cutoff, limit)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                tracked = d.get("perf_tracked", 0) or 0
                winners = d.get("perf_winners", 0) or 0
                d["win_rate"] = (winners / tracked * 100) if tracked > 0 else None
                results.append(d)
            return results

    # ── Correlation Analysis ──

    async def get_correlation_matrix(
        self, days: int = 30, min_co: int = 3, limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get top correlated ticker pairs globally.

        Uses a two-step approach to avoid O(n²) self-join:
        1. Bucket signals into 4-hour time windows
        2. Count co-occurrences within the same window
        """
        cutoff = time.time() - (days * 86400)
        window_s = 14400  # 4 hours

        # Step 1: Fetch recent signals (id, ticker, stance, confidence, created_at)
        fetch_q = """
            SELECT id, ticker, stance, confidence, created_at
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            ORDER BY created_at DESC
            LIMIT 2000
        """
        async with self.db.execute(fetch_q, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            signals = [dict(r) for r in rows]

        if not signals:
            return []

        # Step 2: Bucket by time window and count co-fires in Python
        from collections import defaultdict
        pair_stats: Dict[tuple, dict] = defaultdict(
            lambda: {"co_fires": 0, "same_stance": 0, "conf_sum": 0.0}
        )

        # Group signals by time bucket
        buckets: Dict[int, list] = defaultdict(list)
        for s in signals:
            bucket_id = int(s["created_at"] // window_s)
            buckets[bucket_id].append(s)
            # Also add to adjacent bucket to catch cross-boundary pairs
            buckets[bucket_id + 1].append(s)

        seen_pairs: Dict[tuple, set] = defaultdict(set)
        for _bucket_id, bucket_signals in buckets.items():
            for i, a in enumerate(bucket_signals):
                for b in bucket_signals[i + 1:]:
                    if a["ticker"] == b["ticker"] or a["id"] == b["id"]:
                        continue
                    if abs(a["created_at"] - b["created_at"]) >= window_s:
                        continue
                    pair_key = (min(a["ticker"], b["ticker"]), max(a["ticker"], b["ticker"]))
                    signal_pair = (a["id"], b["id"]) if a["id"] < b["id"] else (b["id"], a["id"])
                    if signal_pair in seen_pairs[pair_key]:
                        continue
                    seen_pairs[pair_key].add(signal_pair)
                    ps = pair_stats[pair_key]
                    ps["co_fires"] += 1
                    if a["stance"] == b["stance"]:
                        ps["same_stance"] += 1
                    ps["conf_sum"] += (a["confidence"] + b["confidence"]) / 2

        # Step 3: Filter and sort
        results = []
        for (ta, tb), ps in pair_stats.items():
            if ps["co_fires"] >= min_co:
                results.append({
                    "ticker_a": ta,
                    "ticker_b": tb,
                    "co_fires": ps["co_fires"],
                    "same_stance": ps["same_stance"],
                    "avg_confidence": round(ps["conf_sum"] / ps["co_fires"], 3),
                })

        results.sort(key=lambda x: x["co_fires"], reverse=True)
        return results[:limit]

    async def get_co_occurring_tickers(
        self, hours: int = 24, min_co_occurrence: int = 2
    ) -> List[Dict[str, Any]]:
        """Find tickers that appear in signals within the same run/batch."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                a.ticker as ticker_a,
                b.ticker as ticker_b,
                COUNT(*) as co_occurrences,
                AVG(a.confidence + b.confidence) / 2 as avg_joint_confidence
            FROM signals a
            JOIN signals b ON a.run_id = b.run_id AND a.ticker < b.ticker
            WHERE a.created_at > ?
                  AND a.ticker != 'UNKNOWN' AND b.ticker != 'UNKNOWN'
            GROUP BY a.ticker, b.ticker
            HAVING co_occurrences >= ?
            ORDER BY co_occurrences DESC
            LIMIT 50
        """
        async with self.db.execute(query, (cutoff, min_co_occurrence)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]
