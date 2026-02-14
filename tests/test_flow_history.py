"""Tests for rot.flow.history — FlowBaseline + FlowHistory.

Covers:
  - Basic update and baseline field mutations
  - Direction counting (bullish/bearish net premium)
  - LRU eviction at capacity
  - Max observations bounding
  - Premium/volume percentile computation
  - Z-score computation
  - Baseline properties (avg_premium, avg_volume, premium_std, bullish_ratio)
  - Empty state queries
  - clear(), remove_ticker(), get_all_tickers()
  - get_top_tickers() with multiple sort keys
  - update_batch() from event dicts
  - to_dict() serialization
  - Move-to-end on access (LRU ordering)
"""

import math
import time

from rot.flow.history import FlowBaseline, FlowHistory


# ── FlowBaseline dataclass ─────────────────────────────


class TestFlowBaselineDefaults:
    """Verify default values and properties on a fresh baseline."""

    def test_defaults(self):
        b = FlowBaseline()
        assert b.net_premium == 0.0
        assert b.total_premium == 0.0
        assert b.flow_count == 0
        assert b.bullish_count == 0
        assert b.bearish_count == 0
        assert b.premium_observations == []
        assert b.volume_observations == []
        assert b.oi_observations == []
        assert b.first_seen == 0.0
        assert b.last_seen == 0.0

    def test_avg_premium_empty(self):
        assert FlowBaseline().avg_premium == 0.0

    def test_avg_volume_empty(self):
        assert FlowBaseline().avg_volume == 0.0

    def test_premium_std_empty(self):
        assert FlowBaseline().premium_std == 0.0

    def test_bullish_ratio_no_directional(self):
        """No bullish or bearish events => ratio is 0.5."""
        assert FlowBaseline().bullish_ratio == 0.5


class TestFlowBaselineProperties:
    """Verify computed properties with known data."""

    def test_avg_premium(self):
        b = FlowBaseline(premium_observations=[10.0, 20.0, 30.0])
        assert b.avg_premium == 20.0

    def test_avg_volume(self):
        b = FlowBaseline(volume_observations=[100, 200, 300])
        assert b.avg_volume == 200.0

    def test_premium_std_single_observation(self):
        b = FlowBaseline(premium_observations=[5.0])
        assert b.premium_std == 0.0

    def test_premium_std_known_values(self):
        # population: [2, 4, 4, 4, 5, 5, 7, 9]  (sample std)
        obs = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        b = FlowBaseline(premium_observations=obs)
        mean = sum(obs) / len(obs)
        variance = sum((x - mean) ** 2 for x in obs) / (len(obs) - 1)
        expected_std = math.sqrt(variance)
        assert abs(b.premium_std - expected_std) < 1e-10

    def test_bullish_ratio(self):
        b = FlowBaseline(bullish_count=3, bearish_count=7)
        assert b.bullish_ratio == 0.3

    def test_bullish_ratio_all_bullish(self):
        b = FlowBaseline(bullish_count=5, bearish_count=0)
        assert b.bullish_ratio == 1.0

    def test_to_dict_keys(self):
        b = FlowBaseline(
            net_premium=100.0,
            total_premium=500.0,
            flow_count=3,
            bullish_count=2,
            bearish_count=1,
            premium_observations=[100.0, 200.0, 200.0],
            first_seen=1000.0,
            last_seen=2000.0,
        )
        d = b.to_dict()
        assert d["net_premium"] == 100.0
        assert d["total_premium"] == 500.0
        assert d["flow_count"] == 3
        assert d["bullish_count"] == 2
        assert d["bearish_count"] == 1
        assert d["observation_count"] == 3
        assert d["first_seen"] == 1000.0
        assert d["last_seen"] == 2000.0
        assert "avg_premium" in d
        assert "premium_std" in d
        assert "bullish_ratio" in d
        assert "avg_volume" in d


# ── FlowHistory ────────────────────────────────────────


class TestFlowHistoryBasicUpdate:
    """Verify that update() mutates baseline fields correctly."""

    def test_single_update(self):
        h = FlowHistory()
        h.update("AAPL", premium=50000.0, volume=200, oi_change=500, timestamp=1000.0)
        b = h.get_baseline("AAPL")
        assert b is not None
        assert b.flow_count == 1
        assert b.total_premium == 50000.0
        assert b.premium_observations == [50000.0]
        assert b.volume_observations == [200]
        assert b.oi_observations == [500]
        assert b.first_seen == 1000.0
        assert b.last_seen == 1000.0

    def test_multiple_updates(self):
        h = FlowHistory()
        h.update("AAPL", premium=100.0, timestamp=1.0)
        h.update("AAPL", premium=200.0, timestamp=2.0)
        h.update("AAPL", premium=300.0, timestamp=3.0)
        b = h.get_baseline("AAPL")
        assert b.flow_count == 3
        assert b.total_premium == 600.0
        assert b.premium_observations == [100.0, 200.0, 300.0]
        assert b.first_seen == 1.0
        assert b.last_seen == 3.0

    def test_zero_volume_not_appended(self):
        """volume=0 should not add to volume_observations."""
        h = FlowHistory()
        h.update("TSLA", premium=1000.0, volume=0)
        b = h.get_baseline("TSLA")
        assert b.volume_observations == []

    def test_zero_oi_change_not_appended(self):
        """oi_change=0 should not add to oi_observations."""
        h = FlowHistory()
        h.update("TSLA", premium=1000.0, oi_change=0)
        b = h.get_baseline("TSLA")
        assert b.oi_observations == []

    def test_default_timestamp_uses_now(self):
        h = FlowHistory()
        before = time.time()
        h.update("SPY", premium=100.0)
        after = time.time()
        b = h.get_baseline("SPY")
        assert before <= b.first_seen <= after
        assert before <= b.last_seen <= after


class TestFlowHistoryDirectionCounting:
    """Verify bullish/bearish net premium and count logic."""

    def test_bullish_adds_to_net_premium(self):
        h = FlowHistory()
        h.update("AAPL", premium=100.0, direction="bullish", timestamp=1.0)
        b = h.get_baseline("AAPL")
        assert b.net_premium == 100.0
        assert b.bullish_count == 1
        assert b.bearish_count == 0

    def test_bearish_subtracts_from_net_premium(self):
        h = FlowHistory()
        h.update("AAPL", premium=75.0, direction="bearish", timestamp=1.0)
        b = h.get_baseline("AAPL")
        assert b.net_premium == -75.0
        assert b.bullish_count == 0
        assert b.bearish_count == 1

    def test_neutral_does_not_affect_net_or_counts(self):
        h = FlowHistory()
        h.update("AAPL", premium=200.0, direction="neutral", timestamp=1.0)
        b = h.get_baseline("AAPL")
        assert b.net_premium == 0.0
        assert b.bullish_count == 0
        assert b.bearish_count == 0
        # But total_premium and flow_count are still updated
        assert b.total_premium == 200.0
        assert b.flow_count == 1

    def test_mixed_directions(self):
        h = FlowHistory()
        h.update("AAPL", premium=100.0, direction="bullish", timestamp=1.0)
        h.update("AAPL", premium=40.0, direction="bearish", timestamp=2.0)
        h.update("AAPL", premium=60.0, direction="bullish", timestamp=3.0)
        b = h.get_baseline("AAPL")
        assert b.net_premium == 100.0 - 40.0 + 60.0  # 120.0
        assert b.bullish_count == 2
        assert b.bearish_count == 1
        assert b.total_premium == 200.0


class TestFlowHistoryLRUEviction:
    """Verify LRU eviction when cache exceeds max_tickers."""

    def test_evicts_lru_at_capacity(self):
        h = FlowHistory(max_tickers=3)
        h.update("A", premium=1.0, timestamp=1.0)
        h.update("B", premium=2.0, timestamp=2.0)
        h.update("C", premium=3.0, timestamp=3.0)
        assert h.ticker_count == 3
        # Adding a 4th ticker should evict "A" (LRU)
        h.update("D", premium=4.0, timestamp=4.0)
        assert h.ticker_count == 3
        assert not h.has_ticker("A")
        assert h.has_ticker("B")
        assert h.has_ticker("C")
        assert h.has_ticker("D")

    def test_access_moves_to_end_preventing_eviction(self):
        """Re-updating a ticker moves it to end so it won't be evicted."""
        h = FlowHistory(max_tickers=3)
        h.update("A", premium=1.0, timestamp=1.0)
        h.update("B", premium=2.0, timestamp=2.0)
        h.update("C", premium=3.0, timestamp=3.0)
        # Touch "A" again — it should now be most-recently used
        h.update("A", premium=10.0, timestamp=4.0)
        # Adding "D" should evict "B" (now LRU)
        h.update("D", premium=5.0, timestamp=5.0)
        assert h.has_ticker("A")
        assert not h.has_ticker("B")
        assert h.has_ticker("C")
        assert h.has_ticker("D")


class TestFlowHistoryMaxObservations:
    """Verify observations are bounded by max_observations."""

    def test_premium_observations_bounded(self):
        h = FlowHistory(max_observations=5)
        for i in range(7):
            h.update("AAPL", premium=float(i), timestamp=float(i))
        b = h.get_baseline("AAPL")
        assert len(b.premium_observations) == 5
        # Should keep the last 5: [2.0, 3.0, 4.0, 5.0, 6.0]
        assert b.premium_observations == [2.0, 3.0, 4.0, 5.0, 6.0]

    def test_volume_observations_bounded(self):
        h = FlowHistory(max_observations=3)
        for i in range(5):
            h.update("AAPL", premium=1.0, volume=i + 1, timestamp=float(i))
        b = h.get_baseline("AAPL")
        assert len(b.volume_observations) == 3
        assert b.volume_observations == [3, 4, 5]

    def test_oi_observations_bounded(self):
        h = FlowHistory(max_observations=4)
        for i in range(6):
            h.update("AAPL", premium=1.0, oi_change=i + 1, timestamp=float(i))
        b = h.get_baseline("AAPL")
        assert len(b.oi_observations) == 4
        assert b.oi_observations == [3, 4, 5, 6]


class TestFlowHistoryPercentile:
    """Verify premium and volume percentile calculations."""

    def test_premium_percentile_known_values(self):
        h = FlowHistory()
        # Add 10 premiums: 10, 20, 30, ..., 100
        for i in range(1, 11):
            h.update("AAPL", premium=float(i * 10), timestamp=float(i))
        # 50 is greater than 4 values (10,20,30,40) out of 10
        pct = h.get_premium_percentile("AAPL", 50.0)
        assert pct == 40.0  # 4/10 * 100

    def test_premium_percentile_at_max(self):
        h = FlowHistory()
        for i in range(1, 11):
            h.update("AAPL", premium=float(i * 10), timestamp=float(i))
        # 150 is greater than all 10 values
        pct = h.get_premium_percentile("AAPL", 150.0)
        assert pct == 100.0

    def test_premium_percentile_at_min(self):
        h = FlowHistory()
        for i in range(1, 11):
            h.update("AAPL", premium=float(i * 10), timestamp=float(i))
        # 5 is less than all values
        pct = h.get_premium_percentile("AAPL", 5.0)
        assert pct == 0.0

    def test_premium_percentile_insufficient_data(self):
        h = FlowHistory()
        for i in range(4):  # only 4 observations, need >= 5
            h.update("AAPL", premium=float(i * 10), timestamp=float(i))
        assert h.get_premium_percentile("AAPL", 25.0) is None

    def test_premium_percentile_unknown_ticker(self):
        h = FlowHistory()
        assert h.get_premium_percentile("NOPE", 100.0) is None

    def test_volume_percentile_known_values(self):
        h = FlowHistory()
        for i in range(1, 11):
            h.update("AAPL", premium=1.0, volume=i * 100, timestamp=float(i))
        # volume=500 is greater than 4 values (100,200,300,400)
        pct = h.get_volume_percentile("AAPL", 500)
        assert pct == 40.0

    def test_volume_percentile_insufficient_data(self):
        h = FlowHistory()
        for i in range(4):
            h.update("AAPL", premium=1.0, volume=i + 1, timestamp=float(i))
        assert h.get_volume_percentile("AAPL", 5) is None


class TestFlowHistoryZScore:
    """Verify z-score calculations."""

    def test_zscore_known_values(self):
        h = FlowHistory()
        # Observations with known mean and std
        obs = [10.0, 20.0, 30.0, 40.0, 50.0]
        for i, v in enumerate(obs):
            h.update("AAPL", premium=v, timestamp=float(i))
        b = h.get_baseline("AAPL")
        mean = b.avg_premium  # 30.0
        std = b.premium_std
        expected_z = (60.0 - mean) / std
        z = h.get_premium_zscore("AAPL", 60.0)
        assert z is not None
        assert abs(z - expected_z) < 1e-10

    def test_zscore_returns_none_if_std_zero(self):
        """All identical values => std=0 => None."""
        h = FlowHistory()
        for i in range(5):
            h.update("AAPL", premium=100.0, timestamp=float(i))
        assert h.get_premium_zscore("AAPL", 100.0) is None

    def test_zscore_returns_none_insufficient_data(self):
        h = FlowHistory()
        for i in range(4):
            h.update("AAPL", premium=float(i * 10), timestamp=float(i))
        assert h.get_premium_zscore("AAPL", 50.0) is None

    def test_zscore_unknown_ticker(self):
        h = FlowHistory()
        assert h.get_premium_zscore("NOPE", 100.0) is None


class TestFlowHistoryEmptyState:
    """Verify queries on empty/unknown state."""

    def test_get_baseline_unknown_ticker(self):
        h = FlowHistory()
        assert h.get_baseline("AAPL") is None

    def test_has_ticker_unknown(self):
        h = FlowHistory()
        assert h.has_ticker("AAPL") is False

    def test_ticker_count_empty(self):
        h = FlowHistory()
        assert h.ticker_count == 0

    def test_get_all_tickers_empty(self):
        h = FlowHistory()
        assert h.get_all_tickers() == []


class TestFlowHistoryMaintenance:
    """Verify clear(), remove_ticker(), get_all_tickers()."""

    def test_clear(self):
        h = FlowHistory()
        h.update("AAPL", premium=100.0)
        h.update("TSLA", premium=200.0)
        assert h.ticker_count == 2
        h.clear()
        assert h.ticker_count == 0
        assert h.get_baseline("AAPL") is None
        assert h.get_baseline("TSLA") is None

    def test_remove_ticker_exists(self):
        h = FlowHistory()
        h.update("AAPL", premium=100.0)
        result = h.remove_ticker("AAPL")
        assert result is True
        assert h.has_ticker("AAPL") is False
        assert h.ticker_count == 0

    def test_remove_ticker_not_exists(self):
        h = FlowHistory()
        result = h.remove_ticker("NOPE")
        assert result is False

    def test_get_all_tickers_order(self):
        """Tickers returned in insertion/access order (most recent last)."""
        h = FlowHistory()
        h.update("A", premium=1.0, timestamp=1.0)
        h.update("B", premium=2.0, timestamp=2.0)
        h.update("C", premium=3.0, timestamp=3.0)
        assert h.get_all_tickers() == ["A", "B", "C"]

    def test_get_all_tickers_after_access(self):
        """Updating an existing ticker moves it to end."""
        h = FlowHistory()
        h.update("A", premium=1.0, timestamp=1.0)
        h.update("B", premium=2.0, timestamp=2.0)
        h.update("C", premium=3.0, timestamp=3.0)
        h.update("A", premium=10.0, timestamp=4.0)
        assert h.get_all_tickers() == ["B", "C", "A"]


class TestFlowHistoryTopTickers:
    """Verify get_top_tickers() sorting."""

    def _setup_history(self):
        h = FlowHistory()
        # AAPL: total=300, count=3, net=+200 (2 bull, 1 bear), avg=100
        h.update("AAPL", premium=100.0, direction="bullish", timestamp=1.0)
        h.update("AAPL", premium=100.0, direction="bullish", timestamp=2.0)
        h.update("AAPL", premium=100.0, direction="bearish", timestamp=3.0)
        # TSLA: total=500, count=2, net=+500 (2 bull), avg=250
        h.update("TSLA", premium=250.0, direction="bullish", timestamp=4.0)
        h.update("TSLA", premium=250.0, direction="bullish", timestamp=5.0)
        # MSFT: total=50, count=1, net=-50 (1 bear), avg=50
        h.update("MSFT", premium=50.0, direction="bearish", timestamp=6.0)
        return h

    def test_sort_by_total_premium(self):
        h = self._setup_history()
        top = h.get_top_tickers(n=2, sort_by="total_premium")
        assert len(top) == 2
        assert top[0][0] == "TSLA"  # 500
        assert top[1][0] == "AAPL"  # 300

    def test_sort_by_flow_count(self):
        h = self._setup_history()
        top = h.get_top_tickers(n=2, sort_by="flow_count")
        assert top[0][0] == "AAPL"  # 3
        assert top[1][0] == "TSLA"  # 2

    def test_sort_by_net_premium(self):
        """Sorted by abs(net_premium)."""
        h = self._setup_history()
        top = h.get_top_tickers(n=3, sort_by="net_premium")
        assert top[0][0] == "TSLA"  # abs(500)
        assert top[1][0] == "AAPL"  # abs(200)
        assert top[2][0] == "MSFT"  # abs(-50) = 50

    def test_sort_by_avg_premium(self):
        h = self._setup_history()
        top = h.get_top_tickers(n=3, sort_by="avg_premium")
        assert top[0][0] == "TSLA"  # 250
        assert top[1][0] == "AAPL"  # 100
        assert top[2][0] == "MSFT"  # 50

    def test_top_n_limits_output(self):
        h = self._setup_history()
        top = h.get_top_tickers(n=1, sort_by="total_premium")
        assert len(top) == 1


class TestFlowHistoryUpdateBatch:
    """Verify batch update from event dicts."""

    def test_batch_update(self):
        h = FlowHistory()
        events = [
            {"premium": 100.0, "volume": 50, "direction": "bullish", "timestamp": 1.0},
            {"premium": 200.0, "volume": 100, "direction": "bearish", "timestamp": 2.0},
            {"premium": 150.0, "direction": "neutral", "timestamp": 3.0},
        ]
        h.update_batch("AAPL", events)
        b = h.get_baseline("AAPL")
        assert b.flow_count == 3
        assert b.total_premium == 450.0
        assert b.net_premium == 100.0 - 200.0  # -100
        assert b.bullish_count == 1
        assert b.bearish_count == 1
        assert b.premium_observations == [100.0, 200.0, 150.0]
        assert b.volume_observations == [50, 100]

    def test_batch_update_minimal_events(self):
        """Events with only premium (other fields default)."""
        h = FlowHistory()
        events = [{"premium": 42.0}]
        h.update_batch("SPY", events)
        b = h.get_baseline("SPY")
        assert b.flow_count == 1
        assert b.total_premium == 42.0
        assert b.net_premium == 0.0  # neutral default


class TestFlowHistorySerialization:
    """Verify to_dict() serialization."""

    def test_to_dict_empty(self):
        h = FlowHistory()
        assert h.to_dict() == {}

    def test_to_dict_with_data(self):
        h = FlowHistory()
        h.update("AAPL", premium=100.0, direction="bullish", timestamp=1.0)
        h.update("TSLA", premium=200.0, direction="bearish", timestamp=2.0)
        d = h.to_dict()
        assert "AAPL" in d
        assert "TSLA" in d
        assert d["AAPL"]["flow_count"] == 1
        assert d["AAPL"]["bullish_count"] == 1
        assert d["TSLA"]["flow_count"] == 1
        assert d["TSLA"]["bearish_count"] == 1
        # to_dict rounds values
        assert d["AAPL"]["net_premium"] == 100.0
        assert d["TSLA"]["net_premium"] == -200.0


class TestFlowHistoryProperties:
    """Verify max_tickers and ticker_count properties."""

    def test_max_tickers_property(self):
        h = FlowHistory(max_tickers=42)
        assert h.max_tickers == 42

    def test_ticker_count_tracks_additions(self):
        h = FlowHistory()
        assert h.ticker_count == 0
        h.update("A", premium=1.0)
        assert h.ticker_count == 1
        h.update("B", premium=1.0)
        assert h.ticker_count == 2
        # Same ticker does not increase count
        h.update("A", premium=1.0)
        assert h.ticker_count == 2
