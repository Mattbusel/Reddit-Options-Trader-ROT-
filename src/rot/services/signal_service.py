"""Signal service — encapsulates signal queries and cached aggregates.

Extracts cached dashboard queries from dashboard.py into a service
that manages cache-or-fetch logic centrally.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class SignalService:
    """Business logic for signal retrieval and analytics."""

    def __init__(self, db, cache=None) -> None:
        self._db = db
        self._cache = cache

    async def get_signals(self, **kwargs) -> list:
        """Fetch signals with optional filters.

        Supports: limit, ticker, stance, min_confidence, event_type,
        date_from, date_to, source, offset, sort, order.
        """
        return await self._db.get_signals(**kwargs)

    async def get_signal(self, signal_id: str) -> dict | None:
        """Fetch a single signal by ID."""
        return await self._db.get_signal(signal_id)

    async def get_trending_tickers(
        self, hours: int = 24, limit: int = 10
    ) -> list:
        """Trending tickers, cached when available."""
        key = f"trending_{hours}_{limit}"
        if self._cache:
            return await self._cache.get_or_fetch(
                key,
                lambda: self._db.get_trending_tickers(hours=hours, limit=limit),
                ttl=30,
            )
        return await self._db.get_trending_tickers(hours=hours, limit=limit)

    async def get_performance_summary(self, days: int = 30) -> dict:
        """Performance summary, cached when available."""
        key = f"perf_summary_{days}"
        if self._cache:
            return await self._cache.get_or_fetch(
                key,
                lambda: self._db.get_performance_summary(days=days),
                ttl=120,
            )
        return await self._db.get_performance_summary(days=days)

    async def get_aggregate_accuracy(
        self, days: int = 7, ticker: str | None = None
    ) -> dict:
        """Aggregate accuracy stats, cached when available."""
        key = f"accuracy_{days}"
        if self._cache:
            return await self._cache.get_or_fetch(
                key,
                lambda: self._db.get_aggregate_accuracy(days=days, ticker=ticker),
                ttl=120,
            )
        return await self._db.get_aggregate_accuracy(days=days, ticker=ticker)

    async def get_accuracy_by_confidence(self, days: int = 7) -> list:
        """Accuracy bucketed by confidence level, cached when available."""
        key = f"accuracy_buckets_{days}"
        if self._cache:
            return await self._cache.get_or_fetch(
                key,
                lambda: self._db.get_accuracy_by_confidence(days=days),
                ttl=120,
            )
        return await self._db.get_accuracy_by_confidence(days=days)

    async def get_strategy_breakdown(self, days: int = 30) -> list:
        """Strategy performance breakdown, cached when available."""
        key = f"strategy_breakdown_{days}"
        try:
            if self._cache:
                return await self._cache.get_or_fetch(
                    key,
                    lambda: self._db.get_strategy_breakdown(days=days),
                    ttl=120,
                )
            return await self._db.get_strategy_breakdown(days=days)
        except Exception:
            log.debug("Strategy breakdown unavailable", exc_info=True)
            return []

    async def get_chart_data(self, hours: int, limit: int) -> list | None:
        """Chart quadrant data, cached when available."""
        key = f"chart_data_{hours}_{limit}"
        if self._cache:
            return await self._cache.get_or_fetch(
                key,
                lambda: self._db.get_chart_data(hours=hours, limit=limit),
                ttl=60,
            )
        return await self._db.get_chart_data(hours=hours, limit=limit)

    async def get_time_series_data(self, hours: int) -> list | None:
        """Time series data, cached when available."""
        key = f"time_series_{hours}"
        if self._cache:
            return await self._cache.get_or_fetch(
                key,
                lambda: self._db.get_time_series_data(hours=hours),
                ttl=60,
            )
        return await self._db.get_time_series_data(hours=hours)

    async def get_leaderboard(
        self,
        hours: int = 24,
        limit: int = 10,
        with_performance: bool = False,
    ) -> list:
        """Leaderboard data, cached when available."""
        if with_performance:
            key = f"leaderboard_perf_{hours}_{limit}"
            fetcher = lambda: self._db.get_leaderboard_with_performance(
                hours=hours, limit=limit
            )
        else:
            key = f"leaderboard_{hours}_{limit}"
            fetcher = lambda: self._db.get_leaderboard(
                hours=hours, limit=limit
            )
        try:
            if self._cache:
                return await self._cache.get_or_fetch(key, fetcher, ttl=30)
            return await fetcher()
        except Exception:
            log.debug("Leaderboard unavailable", exc_info=True)
            return []

    async def get_performance_history(
        self, days: int = 30, ticker: str | None = None, limit: int = 50
    ) -> list:
        """Per-signal performance history."""
        return await self._db.get_performance_history(
            days=days, ticker=ticker, limit=limit
        )
