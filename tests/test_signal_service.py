"""Unit tests for SignalService.

Tests cache-or-fetch logic and DB delegation with mock dependencies.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from rot.services.signal_service import SignalService


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get_signals = AsyncMock(return_value=[])
    db.get_signal = AsyncMock(return_value=None)
    db.get_trending_tickers = AsyncMock(return_value=[])
    db.get_performance_summary = AsyncMock(return_value={})
    db.get_aggregate_accuracy = AsyncMock(return_value={})
    db.get_accuracy_by_confidence = AsyncMock(return_value=[])
    db.get_strategy_breakdown = AsyncMock(return_value=[])
    db.get_chart_data = AsyncMock(return_value=[])
    db.get_time_series_data = AsyncMock(return_value=[])
    db.get_leaderboard = AsyncMock(return_value=[])
    db.get_leaderboard_with_performance = AsyncMock(return_value=[])
    db.get_performance_history = AsyncMock(return_value=[])
    return db


@pytest.fixture
def mock_cache():
    """A cache that simply calls the fetcher on every get_or_fetch."""
    cache = AsyncMock()

    async def _pass_through(key, fetcher, ttl=None):
        return await fetcher()

    cache.get_or_fetch = AsyncMock(side_effect=_pass_through)
    return cache


@pytest.fixture
def svc_no_cache(mock_db):
    return SignalService(db=mock_db, cache=None)


@pytest.fixture
def svc_cached(mock_db, mock_cache):
    return SignalService(db=mock_db, cache=mock_cache)


# ---------------------------------------------------------------------------
# get_signals
# ---------------------------------------------------------------------------

class TestGetSignals:
    @pytest.mark.asyncio
    async def test_delegates_kwargs(self, svc_no_cache, mock_db):
        """Passes all kwargs to db.get_signals."""
        mock_db.get_signals = AsyncMock(return_value=[{"id": "s1"}])
        result = await svc_no_cache.get_signals(limit=5, ticker="AAPL")
        assert len(result) == 1
        mock_db.get_signals.assert_called_once_with(limit=5, ticker="AAPL")


# ---------------------------------------------------------------------------
# get_signal
# ---------------------------------------------------------------------------

class TestGetSignal:
    @pytest.mark.asyncio
    async def test_returns_signal(self, svc_no_cache, mock_db):
        """Returns a signal dict by ID."""
        mock_db.get_signal = AsyncMock(return_value={"id": "s1", "ticker": "TSLA"})
        result = await svc_no_cache.get_signal("s1")
        assert result["ticker"] == "TSLA"

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, svc_no_cache, mock_db):
        """Returns None when signal not found."""
        mock_db.get_signal = AsyncMock(return_value=None)
        result = await svc_no_cache.get_signal("missing")
        assert result is None


# ---------------------------------------------------------------------------
# Cached methods — without cache
# ---------------------------------------------------------------------------

class TestWithoutCache:
    @pytest.mark.asyncio
    async def test_trending_tickers_no_cache(self, svc_no_cache, mock_db):
        """Calls DB directly when no cache configured."""
        mock_db.get_trending_tickers = AsyncMock(return_value=[{"ticker": "AAPL"}])
        result = await svc_no_cache.get_trending_tickers(hours=24, limit=10)
        assert result == [{"ticker": "AAPL"}]
        mock_db.get_trending_tickers.assert_called_once_with(hours=24, limit=10)

    @pytest.mark.asyncio
    async def test_performance_summary_no_cache(self, svc_no_cache, mock_db):
        """Calls DB directly for performance summary."""
        mock_db.get_performance_summary = AsyncMock(return_value={"win_rate": 0.65})
        result = await svc_no_cache.get_performance_summary(days=30)
        assert result["win_rate"] == 0.65

    @pytest.mark.asyncio
    async def test_aggregate_accuracy_no_cache(self, svc_no_cache, mock_db):
        """Calls DB directly for accuracy."""
        mock_db.get_aggregate_accuracy = AsyncMock(return_value={"accuracy": 0.7})
        result = await svc_no_cache.get_aggregate_accuracy(days=7)
        assert result["accuracy"] == 0.7

    @pytest.mark.asyncio
    async def test_accuracy_by_confidence_no_cache(self, svc_no_cache, mock_db):
        """Calls DB directly for accuracy buckets."""
        mock_db.get_accuracy_by_confidence = AsyncMock(return_value=[{"bucket": "high"}])
        result = await svc_no_cache.get_accuracy_by_confidence(days=7)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_strategy_breakdown_no_cache(self, svc_no_cache, mock_db):
        """Calls DB directly for strategy breakdown."""
        mock_db.get_strategy_breakdown = AsyncMock(return_value=[{"strategy": "calls"}])
        result = await svc_no_cache.get_strategy_breakdown(days=30)
        assert result == [{"strategy": "calls"}]

    @pytest.mark.asyncio
    async def test_chart_data_no_cache(self, svc_no_cache, mock_db):
        """Calls DB directly for chart data."""
        mock_db.get_chart_data = AsyncMock(return_value=[{"x": 1}])
        result = await svc_no_cache.get_chart_data(hours=24, limit=50)
        assert result == [{"x": 1}]

    @pytest.mark.asyncio
    async def test_time_series_no_cache(self, svc_no_cache, mock_db):
        """Calls DB directly for time series."""
        mock_db.get_time_series_data = AsyncMock(return_value=[{"ts": 1}])
        result = await svc_no_cache.get_time_series_data(hours=24)
        assert result == [{"ts": 1}]

    @pytest.mark.asyncio
    async def test_leaderboard_no_cache(self, svc_no_cache, mock_db):
        """Calls DB directly for leaderboard."""
        mock_db.get_leaderboard = AsyncMock(return_value=[{"user": "u1"}])
        result = await svc_no_cache.get_leaderboard(hours=24, limit=10)
        assert result == [{"user": "u1"}]

    @pytest.mark.asyncio
    async def test_performance_history_no_cache(self, svc_no_cache, mock_db):
        """Calls DB directly for performance history."""
        mock_db.get_performance_history = AsyncMock(return_value=[{"signal": "s1"}])
        result = await svc_no_cache.get_performance_history(days=30)
        assert result == [{"signal": "s1"}]


# ---------------------------------------------------------------------------
# Cached methods — with cache
# ---------------------------------------------------------------------------

class TestWithCache:
    @pytest.mark.asyncio
    async def test_trending_tickers_uses_cache(self, svc_cached, mock_cache, mock_db):
        """Routes through cache.get_or_fetch."""
        mock_db.get_trending_tickers = AsyncMock(return_value=[{"ticker": "SPY"}])
        result = await svc_cached.get_trending_tickers(hours=12, limit=5)
        assert result == [{"ticker": "SPY"}]
        mock_cache.get_or_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_performance_summary_uses_cache(self, svc_cached, mock_cache, mock_db):
        """Routes through cache for performance summary."""
        mock_db.get_performance_summary = AsyncMock(return_value={"win_rate": 0.8})
        result = await svc_cached.get_performance_summary(days=7)
        assert result["win_rate"] == 0.8
        mock_cache.get_or_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_aggregate_accuracy_uses_cache(self, svc_cached, mock_cache, mock_db):
        """Routes through cache for accuracy."""
        mock_db.get_aggregate_accuracy = AsyncMock(return_value={"accuracy": 0.75})
        result = await svc_cached.get_aggregate_accuracy(days=7)
        assert result["accuracy"] == 0.75
        mock_cache.get_or_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_chart_data_uses_cache(self, svc_cached, mock_cache, mock_db):
        """Routes through cache for chart data."""
        mock_db.get_chart_data = AsyncMock(return_value=[{"x": 2}])
        result = await svc_cached.get_chart_data(hours=48, limit=100)
        assert result == [{"x": 2}]
        mock_cache.get_or_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_leaderboard_with_performance_uses_cache(self, svc_cached, mock_cache, mock_db):
        """Routes through cache for leaderboard with performance flag."""
        mock_db.get_leaderboard_with_performance = AsyncMock(
            return_value=[{"user": "u1", "pnl": 500}]
        )
        result = await svc_cached.get_leaderboard(
            hours=24, limit=10, with_performance=True
        )
        assert result == [{"user": "u1", "pnl": 500}]
        mock_cache.get_or_fetch.assert_called_once()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_strategy_breakdown_returns_empty_on_error(self, svc_no_cache, mock_db):
        """Returns empty list when strategy breakdown fails."""
        mock_db.get_strategy_breakdown = AsyncMock(side_effect=Exception("table missing"))
        result = await svc_no_cache.get_strategy_breakdown(days=30)
        assert result == []

    @pytest.mark.asyncio
    async def test_leaderboard_returns_empty_on_error(self, svc_no_cache, mock_db):
        """Returns empty list when leaderboard query fails."""
        mock_db.get_leaderboard = AsyncMock(side_effect=Exception("query error"))
        result = await svc_no_cache.get_leaderboard(hours=24, limit=10)
        assert result == []
