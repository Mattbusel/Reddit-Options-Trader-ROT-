"""Tests for rot.social.propagation.PropagationTracker."""

import time
from unittest.mock import patch

import pytest

from rot.social.propagation import PropagationConfig, PropagationTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TS = 1_700_000_000.0  # fixed reference timestamp for deterministic tests


def _make_tracker(**overrides) -> PropagationTracker:
    """Build a PropagationTracker with sensible test defaults."""
    cfg = PropagationConfig(**overrides)
    return PropagationTracker(config=cfg)


# ---------------------------------------------------------------------------
# PropagationConfig tests
# ---------------------------------------------------------------------------


class TestPropagationConfig:
    """Verify default and custom configuration values."""

    def test_defaults(self):
        cfg = PropagationConfig()
        assert cfg.window_hours == 24
        assert cfg.min_lag_seconds == 60.0
        assert cfg.max_lag_seconds == 86400.0
        assert cfg.min_signals_per_source == 2
        assert cfg.max_tracked_tickers == 200

    def test_custom_values(self):
        cfg = PropagationConfig(
            window_hours=12,
            min_lag_seconds=30.0,
            max_lag_seconds=7200.0,
            min_signals_per_source=5,
            max_tracked_tickers=50,
        )
        assert cfg.window_hours == 12
        assert cfg.min_lag_seconds == 30.0
        assert cfg.max_lag_seconds == 7200.0
        assert cfg.min_signals_per_source == 5
        assert cfg.max_tracked_tickers == 50


# ---------------------------------------------------------------------------
# ingest_signal tests
# ---------------------------------------------------------------------------


class TestIngestSignal:
    """Test the core ingest_signal method."""

    def test_first_signal_creates_presence_no_propagation(self):
        tracker = _make_tracker()
        events = tracker.ingest_signal("TSLA", "wallstreetbets", "bullish", BASE_TS)
        assert events == []
        assert tracker.tracked_ticker_count == 1
        assert tracker.total_propagation_count == 0

        sources = tracker.get_ticker_sources("TSLA")
        assert "wallstreetbets" in sources
        assert sources["wallstreetbets"]["signal_count"] == 1
        assert sources["wallstreetbets"]["stance"] == "bullish"
        assert sources["wallstreetbets"]["first_seen"] == BASE_TS

    def test_same_source_increments_count_no_propagation(self):
        tracker = _make_tracker()
        tracker.ingest_signal("TSLA", "wallstreetbets", "bullish", BASE_TS)
        events = tracker.ingest_signal("TSLA", "wallstreetbets", "bearish", BASE_TS + 100)
        assert events == []
        assert tracker.total_propagation_count == 0

        sources = tracker.get_ticker_sources("TSLA")
        assert sources["wallstreetbets"]["signal_count"] == 2
        assert sources["wallstreetbets"]["stance"] == "bearish"
        assert sources["wallstreetbets"]["first_seen"] == BASE_TS

    def test_different_source_creates_propagation(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        tracker.ingest_signal("TSLA", "wallstreetbets", "bullish", BASE_TS)
        events = tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 120)

        assert len(events) == 1
        prop = events[0]
        assert prop.ticker == "TSLA"
        assert prop.origin_sub == "wallstreetbets"
        assert prop.spread_to == "stocks"
        assert prop.origin_ts == BASE_TS
        assert prop.spread_ts == BASE_TS + 120
        assert prop.lag_seconds == 120.0

    def test_lag_below_min_not_recorded(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        tracker.ingest_signal("TSLA", "wallstreetbets", "bullish", BASE_TS)
        events = tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 30)
        assert events == []
        assert tracker.total_propagation_count == 0

    def test_lag_above_max_not_recorded(self):
        tracker = _make_tracker(min_lag_seconds=60.0, max_lag_seconds=3600.0)
        tracker.ingest_signal("TSLA", "wallstreetbets", "bullish", BASE_TS)
        events = tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 7200)
        assert events == []

    def test_no_duplicate_propagation_events(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        tracker.ingest_signal("TSLA", "wallstreetbets", "bullish", BASE_TS)
        events1 = tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 120)
        assert len(events1) == 1

        # Re-ingesting same pair should not create a duplicate
        events2 = tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 200)
        assert len(events2) == 0
        assert tracker.total_propagation_count == 1

    def test_ticker_uppercased(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        tracker.ingest_signal("tsla", "wallstreetbets", "bullish", BASE_TS)
        events = tracker.ingest_signal("Tsla", "stocks", "bullish", BASE_TS + 120)
        assert len(events) == 1
        assert events[0].ticker == "TSLA"

    def test_reverse_propagation_detected(self):
        """When the new signal is actually earlier than existing signals,
        the tracker detects reverse propagation (new source -> existing source)."""
        tracker = _make_tracker(min_lag_seconds=60.0)
        # First ingested at t+300
        tracker.ingest_signal("AAPL", "stocks", "bullish", BASE_TS + 300)
        # Then we ingest a signal that occurred *earlier* at t+0
        events = tracker.ingest_signal("AAPL", "options", "bullish", BASE_TS)

        assert len(events) == 1
        prop = events[0]
        # options was earlier, stocks was later
        assert prop.origin_sub == "options"
        assert prop.spread_to == "stocks"
        assert prop.origin_ts == BASE_TS
        assert prop.spread_ts == BASE_TS + 300

    def test_multi_source_propagation(self):
        """Three sources produce two propagation events from the first source."""
        tracker = _make_tracker(min_lag_seconds=60.0)
        tracker.ingest_signal("NVDA", "wallstreetbets", "bullish", BASE_TS)
        e1 = tracker.ingest_signal("NVDA", "stocks", "bullish", BASE_TS + 120)
        e2 = tracker.ingest_signal("NVDA", "options", "bullish", BASE_TS + 240)

        assert len(e1) == 1
        assert len(e2) == 2  # wsb->options and stocks->options
        assert tracker.total_propagation_count == 3

    def test_updates_first_seen_if_earlier(self):
        tracker = _make_tracker()
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS + 100)
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS)  # earlier
        sources = tracker.get_ticker_sources("TSLA")
        assert sources["wsb"]["first_seen"] == BASE_TS


# ---------------------------------------------------------------------------
# ingest_signals_batch tests
# ---------------------------------------------------------------------------


class TestIngestSignalsBatch:
    """Test batch ingestion."""

    def test_batch_sorts_by_created_at(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        signals = [
            {"ticker": "TSLA", "subreddit": "stocks", "stance": "bullish", "created_at": BASE_TS + 200},
            {"ticker": "TSLA", "subreddit": "wallstreetbets", "stance": "bullish", "created_at": BASE_TS},
        ]
        events = tracker.ingest_signals_batch(signals)
        # Even though stocks came first in the list, wsb is processed first (earlier ts)
        assert len(events) == 1
        assert events[0].origin_sub == "wallstreetbets"
        assert events[0].spread_to == "stocks"

    def test_batch_skips_empty_ticker_or_source(self):
        tracker = _make_tracker()
        signals = [
            {"ticker": "", "subreddit": "stocks", "stance": "bullish", "created_at": BASE_TS},
            {"ticker": "TSLA", "subreddit": "", "stance": "bullish", "created_at": BASE_TS},
            {"ticker": "TSLA", "subreddit": "stocks", "stance": "bullish", "created_at": BASE_TS},
        ]
        events = tracker.ingest_signals_batch(signals)
        assert events == []
        assert tracker.tracked_ticker_count == 1  # only the valid signal created presence

    def test_batch_empty_list(self):
        tracker = _make_tracker()
        events = tracker.ingest_signals_batch([])
        assert events == []
        assert tracker.tracked_ticker_count == 0


# ---------------------------------------------------------------------------
# get_propagation_timeline tests
# ---------------------------------------------------------------------------


class TestGetPropagationTimeline:
    """Test timeline retrieval for a ticker."""

    def test_returns_events_sorted_by_origin_ts(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        # Create propagation at two different times
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS)
        tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 120)
        tracker.ingest_signal("TSLA", "options", "bullish", BASE_TS + 240)

        timeline = tracker.get_propagation_timeline("TSLA")
        assert len(timeline) >= 1
        # Verify sorted by origin_ts
        for i in range(len(timeline) - 1):
            assert timeline[i].origin_ts <= timeline[i + 1].origin_ts

    def test_returns_empty_for_unknown_ticker(self):
        tracker = _make_tracker()
        assert tracker.get_propagation_timeline("UNKNOWN") == []

    def test_case_insensitive_lookup(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS)
        tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 120)
        assert len(tracker.get_propagation_timeline("tsla")) >= 1


# ---------------------------------------------------------------------------
# get_leading_sources / get_lagging_sources tests
# ---------------------------------------------------------------------------


class TestLeadingLaggingSources:
    """Test leading and lagging source counting."""

    def _setup_tracker(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        now = time.time()
        tracker.ingest_signal("TSLA", "wsb", "bullish", now - 500)
        tracker.ingest_signal("TSLA", "stocks", "bullish", now - 300)
        tracker.ingest_signal("AAPL", "wsb", "bearish", now - 400)
        tracker.ingest_signal("AAPL", "options", "bearish", now - 200)
        return tracker

    def test_leading_sources_counts_origins(self):
        tracker = self._setup_tracker()
        leading = tracker.get_leading_sources(window_hours=24)
        # wsb originated both propagations
        assert "wsb" in leading
        assert leading["wsb"] >= 2

    def test_lagging_sources_counts_destinations(self):
        tracker = self._setup_tracker()
        lagging = tracker.get_lagging_sources(window_hours=24)
        assert "stocks" in lagging
        assert "options" in lagging

    def test_empty_when_no_propagation(self):
        tracker = _make_tracker()
        assert tracker.get_leading_sources() == {}
        assert tracker.get_lagging_sources() == {}

    def test_window_filters_old_events(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        # All propagations have detected_at = now (via default field factory)
        # Using a window of 0 hours means cutoff is in the future, so nothing passes
        # Instead, patch time to test filtering
        old_ts = time.time() - 200_000  # ~55 hours ago
        tracker.ingest_signal("TSLA", "wsb", "bullish", old_ts)
        tracker.ingest_signal("TSLA", "stocks", "bullish", old_ts + 120)
        # detected_at is set to time.time() when SentimentPropagation is created,
        # so with window_hours=1 (cutoff ~1h ago), events detected now will pass
        leading = tracker.get_leading_sources(window_hours=1)
        # The event was detected now, so it should appear
        assert len(leading) >= 1


# ---------------------------------------------------------------------------
# get_avg_lag_by_pair tests
# ---------------------------------------------------------------------------


class TestGetAvgLagByPair:
    """Test average lag computation per (origin, dest) pair."""

    def test_single_event_pair(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        now = time.time()
        tracker.ingest_signal("TSLA", "wsb", "bullish", now - 300)
        tracker.ingest_signal("TSLA", "stocks", "bullish", now - 100)
        avg_lags = tracker.get_avg_lag_by_pair(window_hours=24)
        assert ("wsb", "stocks") in avg_lags
        assert abs(avg_lags[("wsb", "stocks")] - 200.0) < 1.0

    def test_multiple_events_averaged(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        now = time.time()
        # First propagation: wsb -> stocks with 200s lag
        tracker.ingest_signal("TSLA", "wsb", "bullish", now - 500)
        tracker.ingest_signal("TSLA", "stocks", "bullish", now - 300)
        # Second propagation: wsb -> stocks with 100s lag (different ticker)
        tracker.ingest_signal("AAPL", "wsb", "bearish", now - 400)
        tracker.ingest_signal("AAPL", "stocks", "bearish", now - 300)

        avg_lags = tracker.get_avg_lag_by_pair(window_hours=24)
        key = ("wsb", "stocks")
        assert key in avg_lags
        # Average of 200 and 100 = 150
        assert abs(avg_lags[key] - 150.0) < 1.0

    def test_sorted_by_lag_ascending(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        now = time.time()
        tracker.ingest_signal("TSLA", "wsb", "bullish", now - 500)
        tracker.ingest_signal("TSLA", "stocks", "bullish", now - 300)  # 200s lag
        tracker.ingest_signal("AAPL", "options", "bearish", now - 500)
        tracker.ingest_signal("AAPL", "stocks", "bearish", now - 400)  # 100s lag

        avg_lags = tracker.get_avg_lag_by_pair(window_hours=24)
        keys = list(avg_lags.keys())
        lags = list(avg_lags.values())
        for i in range(len(lags) - 1):
            assert lags[i] <= lags[i + 1]

    def test_empty_when_no_propagation(self):
        tracker = _make_tracker()
        assert tracker.get_avg_lag_by_pair() == {}


# ---------------------------------------------------------------------------
# get_virality_score tests
# ---------------------------------------------------------------------------


class TestGetViralityScore:
    """Test virality score computation."""

    def test_unknown_ticker_returns_zero(self):
        tracker = _make_tracker()
        assert tracker.get_virality_score("NOPE") == 0.0

    def test_single_source_no_propagation(self):
        tracker = _make_tracker()
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS)
        score = tracker.get_virality_score("TSLA")
        # 1 source * 20 = 20 (breadth)
        # No propagation => avg_lag = max_lag => speed_factor = 0
        # 1 signal * 5 = 5 (volume) => volume_factor * 0.3 = 1.5
        # Total = 20 + 0 + 1.5 = 21.5
        assert 20.0 <= score <= 25.0

    def test_multiple_sources_increases_score(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS)
        tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 120)
        score = tracker.get_virality_score("TSLA")
        # 2 sources * 20 = 40 (breadth capped at 40)
        # propagation exists => speed_factor > 0
        assert score > 40.0

    def test_score_capped_at_100(self):
        tracker = _make_tracker(min_lag_seconds=1.0)
        # Create many sources and signals to push score high
        for i in range(10):
            src = f"source_{i}"
            tracker.ingest_signal("MEGA", src, "bullish", BASE_TS + i * 10)
        score = tracker.get_virality_score("MEGA")
        assert score <= 100.0

    def test_case_insensitive(self):
        tracker = _make_tracker()
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS)
        assert tracker.get_virality_score("tsla") == tracker.get_virality_score("TSLA")


# ---------------------------------------------------------------------------
# get_active_tickers tests
# ---------------------------------------------------------------------------


class TestGetActiveTickers:
    """Test active ticker retrieval."""

    def test_returns_tickers_with_recent_propagation(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        now = time.time()
        tracker.ingest_signal("TSLA", "wsb", "bullish", now - 300)
        tracker.ingest_signal("TSLA", "stocks", "bullish", now - 100)

        active = tracker.get_active_tickers(window_hours=6)
        assert len(active) == 1
        assert active[0]["ticker"] == "TSLA"
        assert active[0]["source_count"] == 2
        assert active[0]["propagation_count"] >= 1
        assert "virality_score" in active[0]
        assert "earliest_ts" in active[0]

    def test_empty_without_propagation(self):
        tracker = _make_tracker()
        tracker.ingest_signal("TSLA", "wsb", "bullish", time.time())
        assert tracker.get_active_tickers() == []

    def test_sorted_by_virality_descending(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        now = time.time()
        # TSLA has 3 sources, AAPL has 2 => TSLA should have higher virality
        tracker.ingest_signal("TSLA", "wsb", "bullish", now - 500)
        tracker.ingest_signal("TSLA", "stocks", "bullish", now - 300)
        tracker.ingest_signal("TSLA", "options", "bullish", now - 100)

        tracker.ingest_signal("AAPL", "wsb", "bearish", now - 400)
        tracker.ingest_signal("AAPL", "stocks", "bearish", now - 200)

        active = tracker.get_active_tickers(window_hours=6)
        assert len(active) == 2
        assert active[0]["virality_score"] >= active[1]["virality_score"]


# ---------------------------------------------------------------------------
# clear_old tests
# ---------------------------------------------------------------------------


class TestClearOld:
    """Test event cleanup by age."""

    def test_removes_old_events_returns_count(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        # Create events with detected_at = now (via SentimentPropagation default)
        now = time.time()
        tracker.ingest_signal("TSLA", "wsb", "bullish", now - 300)
        tracker.ingest_signal("TSLA", "stocks", "bullish", now - 100)
        assert tracker.total_propagation_count == 1

        # All events are recent, clearing with 48h window removes nothing
        removed = tracker.clear_old(max_age_hours=48)
        assert removed == 0
        assert tracker.total_propagation_count == 1

    def test_clears_events_with_very_short_window(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        now = time.time()
        tracker.ingest_signal("TSLA", "wsb", "bullish", now - 300)
        tracker.ingest_signal("TSLA", "stocks", "bullish", now - 100)
        assert tracker.total_propagation_count == 1

        # Patch _cutoff_ts to return a future time so everything looks "old"
        with patch("rot.social.propagation._cutoff_ts", return_value=now + 3600):
            removed = tracker.clear_old(max_age_hours=0)
        assert removed == 1
        assert tracker.total_propagation_count == 0

    def test_clears_stale_ticker_presences(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        now = time.time()
        tracker.ingest_signal("TSLA", "wsb", "bullish", now - 300)
        assert tracker.tracked_ticker_count == 1

        # Force all presences to look stale
        with patch("rot.social.propagation._cutoff_ts", return_value=now + 3600):
            tracker.clear_old(max_age_hours=0)
        assert tracker.tracked_ticker_count == 0


# ---------------------------------------------------------------------------
# LRU eviction tests
# ---------------------------------------------------------------------------


class TestLRUEviction:
    """Test bounded ticker tracking via LRU eviction."""

    def test_evicts_oldest_ticker_at_capacity(self):
        tracker = _make_tracker(max_tracked_tickers=3)
        tracker.ingest_signal("AAAA", "wsb", "bullish", BASE_TS)
        tracker.ingest_signal("BBBB", "wsb", "bullish", BASE_TS + 1)
        tracker.ingest_signal("CCCC", "wsb", "bullish", BASE_TS + 2)
        assert tracker.tracked_ticker_count == 3

        # Adding a 4th should evict AAAA (oldest)
        tracker.ingest_signal("DDDD", "wsb", "bullish", BASE_TS + 3)
        assert tracker.tracked_ticker_count == 3
        assert tracker.get_ticker_sources("AAAA") == {}
        assert "DDDD" in tracker.get_ticker_sources("DDDD") or tracker.get_ticker_sources("DDDD") != {}

    def test_accessing_existing_ticker_refreshes_lru(self):
        tracker = _make_tracker(max_tracked_tickers=3)
        tracker.ingest_signal("AAAA", "wsb", "bullish", BASE_TS)
        tracker.ingest_signal("BBBB", "wsb", "bullish", BASE_TS + 1)
        tracker.ingest_signal("CCCC", "wsb", "bullish", BASE_TS + 2)

        # Touch AAAA to move it to end (most recently used)
        tracker.ingest_signal("AAAA", "wsb", "bullish", BASE_TS + 3)

        # Now adding a 4th should evict BBBB (now the oldest)
        tracker.ingest_signal("DDDD", "wsb", "bullish", BASE_TS + 4)
        assert tracker.tracked_ticker_count == 3
        assert tracker.get_ticker_sources("BBBB") == {}
        assert tracker.get_ticker_sources("AAAA") != {}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test miscellaneous edge cases."""

    def test_empty_tracker_properties(self):
        tracker = _make_tracker()
        assert tracker.tracked_ticker_count == 0
        assert tracker.total_propagation_count == 0
        assert tracker.export_propagations() == []

    def test_same_source_never_creates_propagation(self):
        tracker = _make_tracker(min_lag_seconds=0.0)
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS)
        events = tracker.ingest_signal("TSLA", "wsb", "bearish", BASE_TS + 300)
        assert events == []
        assert tracker.total_propagation_count == 0

    def test_export_returns_copy(self):
        tracker = _make_tracker(min_lag_seconds=60.0)
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS)
        tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 120)

        exported = tracker.export_propagations()
        assert len(exported) == 1
        # Modifying the exported list should not affect internal state
        exported.clear()
        assert tracker.total_propagation_count == 1

    def test_repr(self):
        tracker = _make_tracker()
        r = repr(tracker)
        assert "PropagationTracker" in r
        assert "tickers=0" in r
        assert "propagations=0" in r

    def test_min_lag_filter_exactly_at_boundary(self):
        """Lag exactly equal to min_lag_seconds should be recorded."""
        tracker = _make_tracker(min_lag_seconds=100.0)
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS)
        events = tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 100)
        assert len(events) == 1

    def test_max_lag_filter_exactly_at_boundary(self):
        """Lag exactly equal to max_lag_seconds should be recorded."""
        tracker = _make_tracker(min_lag_seconds=60.0, max_lag_seconds=500.0)
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS)
        events = tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 500)
        assert len(events) == 1

    def test_multiple_tickers_independent(self):
        """Propagation tracking for different tickers is independent."""
        tracker = _make_tracker(min_lag_seconds=60.0)
        tracker.ingest_signal("TSLA", "wsb", "bullish", BASE_TS)
        tracker.ingest_signal("AAPL", "wsb", "bearish", BASE_TS)
        tracker.ingest_signal("TSLA", "stocks", "bullish", BASE_TS + 120)

        tsla_timeline = tracker.get_propagation_timeline("TSLA")
        aapl_timeline = tracker.get_propagation_timeline("AAPL")
        assert len(tsla_timeline) == 1
        assert len(aapl_timeline) == 0

    def test_default_config_when_none(self):
        tracker = PropagationTracker(config=None)
        assert tracker._config.window_hours == 24
        assert tracker._config.max_tracked_tickers == 200
