"""Enterprise analytics API.

Provides aggregate statistics for signal quality, performance, trends,
and source analysis. Used by the enterprise dashboard and API endpoints.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Dict, List, Optional


class AnalyticsAPI:
    """Enterprise analytics aggregator."""

    def __init__(self, db: Any = None) -> None:
        self._db = db

    @property
    def db(self) -> Any:
        return self._db

    @db.setter
    def db(self, value: Any) -> None:
        self._db = value

    # ── Signal Stats ──

    def compute_signal_stats(
        self,
        signals: List[Dict[str, Any]],
        date_from: Optional[float] = None,
        date_to: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Compute aggregate signal statistics.

        Parameters
        ----------
        signals:
            List of signal dicts from database.
        """
        filtered = self._filter_by_date(signals, date_from, date_to)

        if not filtered:
            return {
                "total_signals": 0,
                "by_stance": {},
                "by_event_type": {},
                "by_sector": {},
                "avg_confidence": 0.0,
                "avg_quality_score": 0.0,
            }

        total = len(filtered)

        # By stance
        stance_counts: Dict[str, int] = defaultdict(int)
        for s in filtered:
            stance_counts[s.get("stance", "unknown")] += 1

        # By event type
        type_counts: Dict[str, int] = defaultdict(int)
        for s in filtered:
            type_counts[s.get("event_type", "other")] += 1

        # By sector
        sector_counts: Dict[str, int] = defaultdict(int)
        for s in filtered:
            sector = s.get("sector", "").strip()
            if sector:
                sector_counts[sector] += 1

        # Averages
        avg_conf = sum(s.get("confidence", 0) for s in filtered) / total
        avg_quality = sum(s.get("quality_score", 0) for s in filtered) / total

        return {
            "total_signals": total,
            "by_stance": dict(stance_counts),
            "by_event_type": dict(type_counts),
            "by_sector": dict(sector_counts),
            "avg_confidence": round(avg_conf, 3),
            "avg_quality_score": round(avg_quality, 3),
        }

    # ── Performance Stats ──

    def compute_performance_stats(
        self,
        signals_with_perf: List[Dict[str, Any]],
        date_from: Optional[float] = None,
        date_to: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Compute performance statistics from signals with performance data.

        Each signal dict should include price tracking fields
        (price_at_signal, price_1d, max_gain_pct, max_loss_pct).
        """
        filtered = self._filter_by_date(signals_with_perf, date_from, date_to)

        if not filtered:
            return {
                "total_tracked": 0,
                "winners": 0,
                "losers": 0,
                "win_rate": None,
                "avg_gain_pct": None,
                "avg_loss_pct": None,
            }

        winners = 0
        losers = 0
        gains = []
        losses = []

        for s in filtered:
            gain = s.get("max_gain_pct", 0) or 0
            loss = s.get("max_loss_pct", 0) or 0

            if gain > 0.5:
                winners += 1
                gains.append(gain)
            elif loss > 0.5:
                losers += 1
                losses.append(loss)

        total = winners + losers
        return {
            "total_tracked": len(filtered),
            "winners": winners,
            "losers": losers,
            "win_rate": round(winners / total, 3) if total > 0 else None,
            "avg_gain_pct": round(sum(gains) / len(gains), 2) if gains else None,
            "avg_loss_pct": round(sum(losses) / len(losses), 2) if losses else None,
        }

    # ── Trend Analysis ──

    def compute_trend_analysis(
        self,
        signals: List[Dict[str, Any]],
        date_from: Optional[float] = None,
        date_to: Optional[float] = None,
        bucket_hours: int = 24,
    ) -> Dict[str, Any]:
        """Compute signal volume trends over time.

        Groups signals into time buckets and measures volume,
        sentiment, and confidence trends.
        """
        filtered = self._filter_by_date(signals, date_from, date_to)

        if not filtered:
            return {"buckets": [], "total_signals": 0}

        bucket_s = bucket_hours * 3600
        min_ts = min(s.get("created_at", 0) for s in filtered)
        max_ts = max(s.get("created_at", 0) for s in filtered)

        buckets = []
        t = min_ts
        while t <= max_ts + bucket_s:
            bucket_end = t + bucket_s
            in_bucket = [
                s for s in filtered
                if t <= s.get("created_at", 0) < bucket_end
            ]

            if in_bucket:
                bullish = sum(1 for s in in_bucket if s.get("stance") == "bullish")
                bearish = sum(1 for s in in_bucket if s.get("stance") == "bearish")
                avg_conf = sum(s.get("confidence", 0) for s in in_bucket) / len(in_bucket)

                buckets.append({
                    "timestamp": t,
                    "count": len(in_bucket),
                    "bullish": bullish,
                    "bearish": bearish,
                    "avg_confidence": round(avg_conf, 3),
                })

            t += bucket_s

        return {
            "buckets": buckets,
            "total_signals": len(filtered),
            "bucket_hours": bucket_hours,
        }

    # ── Source Analysis ──

    def compute_source_analysis(
        self,
        signals: List[Dict[str, Any]],
        date_from: Optional[float] = None,
        date_to: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Analyze signal quality by source (subreddit, RSS, etc.).

        Returns per-source breakdown of signal count, avg confidence,
        avg quality, and stance distribution.
        """
        filtered = self._filter_by_date(signals, date_from, date_to)

        if not filtered:
            return {"sources": [], "total_signals": 0}

        by_source: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for s in filtered:
            source = s.get("subreddit", "unknown") or "unknown"
            by_source[source].append(s)

        sources = []
        for source, sigs in by_source.items():
            total = len(sigs)
            avg_conf = sum(s.get("confidence", 0) for s in sigs) / total
            avg_quality = sum(s.get("quality_score", 0) for s in sigs) / total
            bullish = sum(1 for s in sigs if s.get("stance") == "bullish")
            bearish = sum(1 for s in sigs if s.get("stance") == "bearish")

            sources.append({
                "source": source,
                "signal_count": total,
                "avg_confidence": round(avg_conf, 3),
                "avg_quality_score": round(avg_quality, 3),
                "bullish_pct": round(bullish / total * 100, 1) if total else 0,
                "bearish_pct": round(bearish / total * 100, 1) if total else 0,
            })

        sources.sort(key=lambda x: x["signal_count"], reverse=True)

        return {
            "sources": sources,
            "total_signals": len(filtered),
        }

    # ── Helper ──

    def _filter_by_date(
        self,
        signals: List[Dict[str, Any]],
        date_from: Optional[float] = None,
        date_to: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Filter signals by date range."""
        result = signals
        if date_from:
            result = [s for s in result if s.get("created_at", 0) >= date_from]
        if date_to:
            result = [s for s in result if s.get("created_at", 0) <= date_to]
        return result
