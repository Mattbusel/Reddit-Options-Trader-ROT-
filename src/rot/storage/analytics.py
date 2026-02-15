"""
Chart data, heatmaps, sector, correlations, leaderboards.

Assumes self.db (aiosqlite Connection) exists.
"""
import json
import time
from typing import Any, Dict, List, Optional

from .sql_helpers import _row_to_dict


class AnalyticsMixin:
    """Mixin providing analytics and visualization query methods.

    Reads from signals, signal_performance, signal_archive tables.
    Requires self.db to be an open aiosqlite.Connection.
    """

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

    # ── News Feed ──

    async def get_news_feed(
        self, hours: int = 24, limit: int = 50, source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get recent signals from RSS/news sources for the live news feed."""
        cutoff = time.time() - (hours * 3600)
        conditions = ["created_at > ?"]
        params: list = [cutoff]

        _NEWS_SUBS = (
            # MarketWatch feeds
            "marketwatch-top", "marketwatch-realtime",
            # Financial news feeds
            "investing-com-stocks", "yahoo-finance-top", "cnbc-market", "seekingalpha-currents",
            # Government/Regulatory feeds
            "dod-contracts", "dod-releases", "dod-news",
            "fda-press-releases", "fda-drugs", "fda-recalls",
            "fed-press-releases",
            # Social feeds
            "stocktwits", "twitter",
        )
        if source and source in _NEWS_SUBS:
            conditions.append("subreddit = ?")
            params.append(source)
        else:
            placeholders = ",".join("?" for _ in _NEWS_SUBS)
            conditions.append(f"subreddit IN ({placeholders})")
            params.extend(_NEWS_SUBS)

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT id, ticker, event_type, stance, confidence, subreddit,
                   post_title, post_url, created_at, reasoning
            FROM signals
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(limit)

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                # Parse reasoning JSON
                reasoning_str = d.get("reasoning", "{}")
                try:
                    reasoning = json.loads(reasoning_str) if isinstance(reasoning_str, str) else reasoning_str
                    d["reasoning"] = reasoning if isinstance(reasoning, dict) else {}
                except (json.JSONDecodeError, TypeError):
                    d["reasoning"] = {}
                # Extract AI summary if present
                d["ai_summary"] = d["reasoning"].get("ai_summary", "")
                results.append(d)
            return results

    # ── Sentiment Heatmap ──

    async def get_sentiment_heatmap(
        self, hours: int = 24, ticker_limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get sentiment data bucketed by ticker and time period for heatmap."""
        cutoff = time.time() - (hours * 3600)
        # Use 1h buckets for <= 24h, 4h for <= 7d, 1d for longer
        if hours <= 24:
            bucket_s = 3600
        elif hours <= 168:
            bucket_s = 14400
        else:
            bucket_s = 86400

        query = """
            SELECT ticker,
                   CAST(created_at / ? AS INTEGER) * ? as time_bucket,
                   COUNT(*) as signal_count,
                   AVG(confidence) as avg_confidence,
                   SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                   SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                   SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            GROUP BY ticker, time_bucket
            ORDER BY signal_count DESC
        """
        async with self.db.execute(query, (bucket_s, bucket_s, cutoff)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ── Weekly Wrap ──

    async def get_weekly_summary(
        self, start_ts: float, end_ts: float
    ) -> Dict[str, Any]:
        """Get aggregated signal data for a given time window (week)."""
        # Total signals and stance breakdown
        query = """
            SELECT COUNT(*) as total_signals,
                   SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                   SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                   SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed,
                   AVG(confidence) as avg_confidence
            FROM signals
            WHERE created_at >= ? AND created_at < ?
              AND ticker != 'UNKNOWN'
        """
        async with self.db.execute(query, (start_ts, end_ts)) as cursor:
            row = await cursor.fetchone()
            summary = dict(row) if row else {}

        # Top tickers by signal count
        query2 = """
            SELECT ticker, COUNT(*) as count,
                   AVG(confidence) as avg_conf,
                   SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bull,
                   SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bear
            FROM signals
            WHERE created_at >= ? AND created_at < ?
              AND ticker != 'UNKNOWN'
            GROUP BY ticker
            ORDER BY count DESC
            LIMIT 20
        """
        async with self.db.execute(query2, (start_ts, end_ts)) as cursor:
            rows = await cursor.fetchall()
            summary["top_tickers"] = [dict(r) for r in rows]

        # Best and worst performers (from signal_performance)
        try:
            query3 = """
                SELECT sp.ticker, sp.max_gain_pct, sp.max_loss_pct,
                       s.stance, s.confidence, s.event_type
                FROM signal_performance sp
                JOIN signals s ON sp.signal_id = s.id
                WHERE s.created_at >= ? AND s.created_at < ?
                  AND sp.max_gain_pct IS NOT NULL
                ORDER BY sp.max_gain_pct DESC
                LIMIT 10
            """
            async with self.db.execute(query3, (start_ts, end_ts)) as cursor:
                rows = await cursor.fetchall()
                summary["best_calls"] = [dict(r) for r in rows]

            query4 = """
                SELECT sp.ticker, sp.max_gain_pct, sp.max_loss_pct,
                       s.stance, s.confidence, s.event_type
                FROM signal_performance sp
                JOIN signals s ON sp.signal_id = s.id
                WHERE s.created_at >= ? AND s.created_at < ?
                  AND sp.max_loss_pct IS NOT NULL
                ORDER BY sp.max_loss_pct ASC
                LIMIT 10
            """
            async with self.db.execute(query4, (start_ts, end_ts)) as cursor:
                rows = await cursor.fetchall()
                summary["worst_calls"] = [dict(r) for r in rows]
        except Exception:
            summary["best_calls"] = []
            summary["worst_calls"] = []

        return summary

    # ── Signal Replay ──

    async def get_replay_data(
        self, hours: int = 24, include_performance: bool = False
    ) -> List[Dict[str, Any]]:
        """Get signals ordered by creation time for replay animation."""
        cutoff = time.time() - (hours * 3600)

        if include_performance:
            query = """
                SELECT s.id, s.ticker, s.stance, s.confidence, s.event_type,
                       s.created_at, s.strategy, s.trend_score, s.reasoning, s.event_data,
                       sp.price_at_signal, sp.price_1d, sp.max_gain_pct, sp.max_loss_pct
                FROM signals s
                LEFT JOIN signal_performance sp ON s.id = sp.signal_id
                WHERE s.created_at > ? AND s.ticker != 'UNKNOWN'
                ORDER BY s.created_at ASC
            """
        else:
            query = """
                SELECT id, ticker, stance, confidence, event_type,
                       created_at, strategy, trend_score, reasoning, event_data
                FROM signals
                WHERE created_at > ? AND ticker != 'UNKNOWN'
                ORDER BY created_at ASC
            """

        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                # Parse reasoning JSON for thesis field
                reasoning_str = d.get("reasoning", "{}")
                try:
                    reasoning = json.loads(reasoning_str) if isinstance(reasoning_str, str) else reasoning_str
                    d["thesis"] = reasoning.get("thesis", "") if isinstance(reasoning, dict) else ""
                except (json.JSONDecodeError, TypeError):
                    d["thesis"] = ""
                # Parse event_data JSON for entities
                event_data_str = d.get("event_data", "{}")
                try:
                    event_data = json.loads(event_data_str) if isinstance(event_data_str, str) else event_data_str
                    d["entities"] = event_data.get("entities", []) if isinstance(event_data, dict) else []
                except (json.JSONDecodeError, TypeError):
                    d["entities"] = []
                results.append(d)
            return results

    async def get_unusual_events(
        self, hours: int = 24, event_type: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get unusual activity events from the unusual_events table."""
        cutoff = time.time() - (hours * 3600)

        conditions = ["detected_at > ?"]
        params: list = [cutoff]

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        where = " AND ".join(conditions)
        query = f"""
            SELECT * FROM unusual_events
            WHERE {where}
            ORDER BY detected_at DESC, score DESC
            LIMIT ?
        """
        params.append(limit)

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            # Parse details_json
            details_str = d.get("details_json", "{}")
            try:
                d["details"] = json.loads(details_str) if isinstance(details_str, str) else details_str
            except (json.JSONDecodeError, TypeError):
                d["details"] = {}
            results.append(d)

        return results

    async def get_unusual_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get aggregate summary of unusual activity."""
        cutoff = time.time() - (hours * 3600)

        # Event type breakdown
        type_query = """
            SELECT event_type, COUNT(*) as count, AVG(score) as avg_score
            FROM unusual_events
            WHERE detected_at > ?
            GROUP BY event_type
            ORDER BY count DESC
        """
        async with self.db.execute(type_query, (cutoff,)) as cursor:
            type_rows = await cursor.fetchall()

        type_breakdown = {
            row["event_type"]: {"count": row["count"], "avg_score": round(row["avg_score"] or 0, 1)}
            for row in type_rows
        }

        # Top tickers
        ticker_query = """
            SELECT ticker, COUNT(*) as event_count, MAX(score) as max_score
            FROM unusual_events
            WHERE detected_at > ?
            GROUP BY ticker
            ORDER BY event_count DESC, max_score DESC
            LIMIT 10
        """
        async with self.db.execute(ticker_query, (cutoff,)) as cursor:
            ticker_rows = await cursor.fetchall()

        top_tickers = [
            {"ticker": r["ticker"], "event_count": r["event_count"], "max_score": round(r["max_score"] or 0, 1)}
            for r in ticker_rows
        ]

        # Overall stats
        stats_query = """
            SELECT
                COUNT(*) as total_events,
                AVG(score) as avg_score,
                MAX(score) as max_score,
                COUNT(DISTINCT ticker) as unique_tickers
            FROM unusual_events
            WHERE detected_at > ?
        """
        async with self.db.execute(stats_query, (cutoff,)) as cursor:
            row = await cursor.fetchone()

        return {
            "total_events": row["total_events"] or 0,
            "avg_score": round(row["avg_score"] or 0, 1),
            "max_score": round(row["max_score"] or 0, 1),
            "unique_tickers": row["unique_tickers"] or 0,
            "type_breakdown": type_breakdown,
            "top_tickers": top_tickers,
        }

    async def get_unusual_timeline(
        self, ticker: str, days: int = 7
    ) -> List[Dict[str, Any]]:
        """Get unusual activity timeline for a specific ticker."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT * FROM unusual_events
            WHERE ticker = ? AND detected_at > ?
            ORDER BY detected_at ASC
        """
        async with self.db.execute(query, (ticker, cutoff)) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            # Parse details_json
            details_str = d.get("details_json", "{}")
            try:
                d["details"] = json.loads(details_str) if isinstance(details_str, str) else details_str
            except (json.JSONDecodeError, TypeError):
                d["details"] = {}
            results.append(d)

        return results

    async def get_ticker_summary(self, ticker: str) -> Dict[str, Any]:
        """Get aggregate summary for a single ticker.

        Args:
            ticker: Ticker symbol

        Returns:
            Dict with total_signals, avg_confidence, bullish_count, bearish_count, etc.
        """
        query = """
            SELECT ticker,
                   COUNT(*) as total_signals,
                   AVG(confidence) as avg_confidence,
                   SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish_count,
                   SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish_count,
                   SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed_count,
                   MIN(created_at) as first_signal_at,
                   MAX(created_at) as latest_signal_at
            FROM signals
            WHERE ticker = ? AND ticker != 'UNKNOWN'
        """
        async with self.db.execute(query, (ticker.upper(),)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {}

    async def get_ticker_signals(self, ticker: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get signals for a specific ticker, newest first.

        Args:
            ticker: Ticker symbol
            limit: Maximum number of signals to return

        Returns:
            List of signal dicts
        """
        query = """
            SELECT * FROM signals
            WHERE ticker = ? AND ticker != 'UNKNOWN'
            ORDER BY created_at DESC
            LIMIT ?
        """
        async with self.db.execute(query, (ticker.upper(), limit)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(r) for r in rows]
