"""Tests for enterprise analytics API."""

from __future__ import annotations

import time

import pytest

from rot.export.analytics import AnalyticsAPI


# ── Helpers ──


def _make_signal(
    ticker: str = "AAPL",
    stance: str = "bullish",
    event_type: str = "earnings_rumor",
    confidence: float = 0.6,
    quality_score: float = 0.5,
    sector: str = "Technology",
    subreddit: str = "wallstreetbets",
    created_at: float | None = None,
    **extra,
) -> dict:
    d = {
        "ticker": ticker,
        "stance": stance,
        "event_type": event_type,
        "confidence": confidence,
        "quality_score": quality_score,
        "sector": sector,
        "subreddit": subreddit,
        "created_at": created_at or time.time(),
    }
    d.update(extra)
    return d


def _make_perf_signal(
    max_gain_pct: float = 0.0,
    max_loss_pct: float = 0.0,
    **kwargs,
) -> dict:
    s = _make_signal(**kwargs)
    s["max_gain_pct"] = max_gain_pct
    s["max_loss_pct"] = max_loss_pct
    return s


# ── Signal Stats ──


class TestSignalStats:
    """compute_signal_stats tests."""

    def test_empty(self):
        api = AnalyticsAPI()
        result = api.compute_signal_stats([])
        assert result["total_signals"] == 0
        assert result["by_stance"] == {}
        assert result["avg_confidence"] == 0.0

    def test_basic_stats(self):
        api = AnalyticsAPI()
        signals = [
            _make_signal(stance="bullish", confidence=0.7, quality_score=0.8),
            _make_signal(stance="bearish", confidence=0.5, quality_score=0.6),
            _make_signal(stance="bullish", confidence=0.6, quality_score=0.7),
        ]
        result = api.compute_signal_stats(signals)
        assert result["total_signals"] == 3
        assert result["by_stance"]["bullish"] == 2
        assert result["by_stance"]["bearish"] == 1
        assert result["avg_confidence"] == pytest.approx(0.6, abs=0.01)

    def test_by_event_type(self):
        api = AnalyticsAPI()
        signals = [
            _make_signal(event_type="earnings_rumor"),
            _make_signal(event_type="earnings_rumor"),
            _make_signal(event_type="squeeze_chatter"),
        ]
        result = api.compute_signal_stats(signals)
        assert result["by_event_type"]["earnings_rumor"] == 2
        assert result["by_event_type"]["squeeze_chatter"] == 1

    def test_by_sector(self):
        api = AnalyticsAPI()
        signals = [
            _make_signal(sector="Technology"),
            _make_signal(sector="Healthcare"),
            _make_signal(sector="Technology"),
            _make_signal(sector=""),  # empty sector should be excluded
        ]
        result = api.compute_signal_stats(signals)
        assert result["by_sector"]["Technology"] == 2
        assert result["by_sector"]["Healthcare"] == 1
        assert "" not in result["by_sector"]

    def test_date_filter(self):
        api = AnalyticsAPI()
        now = time.time()
        signals = [
            _make_signal(created_at=now - 100),
            _make_signal(created_at=now - 200),
            _make_signal(created_at=now - 1000),  # old
        ]
        result = api.compute_signal_stats(
            signals, date_from=now - 500, date_to=now,
        )
        assert result["total_signals"] == 2

    def test_avg_quality_score(self):
        api = AnalyticsAPI()
        signals = [
            _make_signal(quality_score=0.8),
            _make_signal(quality_score=0.6),
        ]
        result = api.compute_signal_stats(signals)
        assert result["avg_quality_score"] == 0.7


# ── Performance Stats ──


class TestPerformanceStats:
    """compute_performance_stats tests."""

    def test_empty(self):
        api = AnalyticsAPI()
        result = api.compute_performance_stats([])
        assert result["total_tracked"] == 0
        assert result["win_rate"] is None

    def test_all_winners(self):
        api = AnalyticsAPI()
        signals = [
            _make_perf_signal(max_gain_pct=5.0),
            _make_perf_signal(max_gain_pct=3.0),
        ]
        result = api.compute_performance_stats(signals)
        assert result["total_tracked"] == 2
        assert result["winners"] == 2
        assert result["losers"] == 0
        assert result["win_rate"] == 1.0
        assert result["avg_gain_pct"] == 4.0

    def test_mixed_results(self):
        api = AnalyticsAPI()
        signals = [
            _make_perf_signal(max_gain_pct=5.0, max_loss_pct=0),
            _make_perf_signal(max_gain_pct=3.0, max_loss_pct=0),
            _make_perf_signal(max_gain_pct=0, max_loss_pct=4.0),
        ]
        result = api.compute_performance_stats(signals)
        assert result["winners"] == 2
        assert result["losers"] == 1
        assert result["win_rate"] == pytest.approx(0.667, abs=0.01)
        assert result["avg_loss_pct"] == 4.0

    def test_no_decisive_moves(self):
        api = AnalyticsAPI()
        signals = [
            _make_perf_signal(max_gain_pct=0.2, max_loss_pct=0.1),  # below 0.5 threshold
            _make_perf_signal(max_gain_pct=0.3, max_loss_pct=0.4),
        ]
        result = api.compute_performance_stats(signals)
        assert result["winners"] == 0
        assert result["losers"] == 0
        assert result["win_rate"] is None

    def test_date_filter(self):
        api = AnalyticsAPI()
        now = time.time()
        signals = [
            _make_perf_signal(max_gain_pct=5.0, created_at=now - 100),
            _make_perf_signal(max_gain_pct=5.0, created_at=now - 10000),  # old
        ]
        result = api.compute_performance_stats(
            signals, date_from=now - 500,
        )
        assert result["total_tracked"] == 1


# ── Trend Analysis ──


class TestTrendAnalysis:
    """compute_trend_analysis tests."""

    def test_empty(self):
        api = AnalyticsAPI()
        result = api.compute_trend_analysis([])
        assert result["total_signals"] == 0
        assert result["buckets"] == []

    def test_single_bucket(self):
        api = AnalyticsAPI()
        now = time.time()
        signals = [
            _make_signal(stance="bullish", confidence=0.7, created_at=now - 100),
            _make_signal(stance="bearish", confidence=0.5, created_at=now - 50),
        ]
        result = api.compute_trend_analysis(signals, bucket_hours=24)
        assert result["total_signals"] == 2
        assert len(result["buckets"]) >= 1
        bucket = result["buckets"][0]
        assert bucket["count"] == 2
        assert bucket["bullish"] == 1
        assert bucket["bearish"] == 1

    def test_multiple_buckets(self):
        api = AnalyticsAPI()
        now = time.time()
        signals = [
            _make_signal(created_at=now),
            _make_signal(created_at=now - 86400 * 2),  # 2 days ago
        ]
        result = api.compute_trend_analysis(signals, bucket_hours=24)
        assert result["total_signals"] == 2
        assert len(result["buckets"]) >= 2

    def test_bucket_hours_param(self):
        api = AnalyticsAPI()
        result = api.compute_trend_analysis([], bucket_hours=12)
        # Empty case just returns bucket_hours in response
        assert result.get("buckets") == []


# ── Source Analysis ──


class TestSourceAnalysis:
    """compute_source_analysis tests."""

    def test_empty(self):
        api = AnalyticsAPI()
        result = api.compute_source_analysis([])
        assert result["total_signals"] == 0
        assert result["sources"] == []

    def test_single_source(self):
        api = AnalyticsAPI()
        signals = [
            _make_signal(subreddit="wallstreetbets", stance="bullish", confidence=0.7),
            _make_signal(subreddit="wallstreetbets", stance="bearish", confidence=0.5),
        ]
        result = api.compute_source_analysis(signals)
        assert result["total_signals"] == 2
        assert len(result["sources"]) == 1
        source = result["sources"][0]
        assert source["source"] == "wallstreetbets"
        assert source["signal_count"] == 2
        assert source["bullish_pct"] == 50.0
        assert source["bearish_pct"] == 50.0

    def test_multiple_sources(self):
        api = AnalyticsAPI()
        signals = [
            _make_signal(subreddit="wallstreetbets"),
            _make_signal(subreddit="wallstreetbets"),
            _make_signal(subreddit="options"),
        ]
        result = api.compute_source_analysis(signals)
        assert len(result["sources"]) == 2
        # Sorted by count descending
        assert result["sources"][0]["source"] == "wallstreetbets"
        assert result["sources"][0]["signal_count"] == 2
        assert result["sources"][1]["source"] == "options"

    def test_source_avg_metrics(self):
        api = AnalyticsAPI()
        signals = [
            _make_signal(subreddit="wsb", confidence=0.8, quality_score=0.9),
            _make_signal(subreddit="wsb", confidence=0.6, quality_score=0.7),
        ]
        result = api.compute_source_analysis(signals)
        source = result["sources"][0]
        assert source["avg_confidence"] == 0.7
        assert source["avg_quality_score"] == 0.8

    def test_date_filter(self):
        api = AnalyticsAPI()
        now = time.time()
        signals = [
            _make_signal(created_at=now - 100),
            _make_signal(created_at=now - 10000),  # old
        ]
        result = api.compute_source_analysis(signals, date_from=now - 500)
        assert result["total_signals"] == 1

    def test_unknown_source(self):
        api = AnalyticsAPI()
        signals = [_make_signal(subreddit=None)]
        result = api.compute_source_analysis(signals)
        assert result["sources"][0]["source"] == "unknown"


# ── Date Filter ──


class TestDateFilter:
    """_filter_by_date tests."""

    def test_no_filter(self):
        api = AnalyticsAPI()
        signals = [_make_signal(), _make_signal()]
        result = api._filter_by_date(signals)
        assert len(result) == 2

    def test_from_filter(self):
        api = AnalyticsAPI()
        now = time.time()
        signals = [
            _make_signal(created_at=now - 10),
            _make_signal(created_at=now - 1000),
        ]
        result = api._filter_by_date(signals, date_from=now - 100)
        assert len(result) == 1

    def test_to_filter(self):
        api = AnalyticsAPI()
        now = time.time()
        signals = [
            _make_signal(created_at=now - 10),
            _make_signal(created_at=now + 1000),
        ]
        result = api._filter_by_date(signals, date_to=now)
        assert len(result) == 1

    def test_both_filters(self):
        api = AnalyticsAPI()
        now = time.time()
        signals = [
            _make_signal(created_at=now - 500),  # too old
            _make_signal(created_at=now - 50),   # in range
            _make_signal(created_at=now + 500),   # too new
        ]
        result = api._filter_by_date(
            signals, date_from=now - 100, date_to=now,
        )
        assert len(result) == 1
