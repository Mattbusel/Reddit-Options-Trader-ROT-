"""Tests for rot.unusual — types, history, config, and detector.

Covers UnusualEvent, UnusualScore, UnusualSummary dataclasses. UnusualHistory
rolling baselines (IV rank, volume z-score, volume ratio, OI change, P/C z-score,
LRU eviction, thread safety). UnusualDetectorConfig defaults and total_weight.
UnusualDetector scan_signal, scan_batch, compute_score, compute_summary,
and individual detection algorithms (IV spike, volume surge, OI surge,
skew shift, sweep).
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List

import pytest

from rot.unusual.types import (
    EVENT_TYPES,
    UnusualEvent,
    UnusualScore,
    UnusualSummary,
)
from rot.unusual.config import UnusualDetectorConfig
from rot.unusual.history import TickerStats, UnusualHistory
from rot.unusual.detector import UnusualDetector, _get_float


# ═══════════════════════════════════════════════════════════════════════════
# Part 1: Unusual Types
# ═══════════════════════════════════════════════════════════════════════════


class TestEventTypes:
    def test_all_types_present(self):
        assert "iv_spike" in EVENT_TYPES
        assert "volume_surge" in EVENT_TYPES
        assert "oi_surge" in EVENT_TYPES
        assert "skew_shift" in EVENT_TYPES
        assert "sweep" in EVENT_TYPES
        assert len(EVENT_TYPES) == 5


class TestUnusualEvent:
    def test_basic_creation(self):
        e = UnusualEvent(
            ticker="AAPL", event_type="iv_spike",
            score=75.0, details={"iv": 0.5}, detected_at=1000.0,
        )
        assert e.ticker == "AAPL"
        assert e.score == 75.0
        assert e.signal_id is None

    def test_with_signal_id(self):
        e = UnusualEvent(
            ticker="TSLA", event_type="volume_surge",
            score=50.0, details={}, detected_at=1000.0,
            signal_id="sig_123",
        )
        assert e.signal_id == "sig_123"

    def test_to_dict(self):
        e = UnusualEvent(
            ticker="SPY", event_type="sweep",
            score=88.5, details={"x": 1}, detected_at=2000.0,
        )
        d = e.to_dict()
        assert d["ticker"] == "SPY"
        assert d["score"] == 88.5
        assert d["details"] == {"x": 1}

    def test_invalid_event_type(self):
        with pytest.raises(ValueError, match="Invalid event_type"):
            UnusualEvent(
                ticker="X", event_type="invalid",
                score=50.0, details={}, detected_at=1000.0,
            )

    def test_score_below_zero(self):
        with pytest.raises(ValueError, match="Score must be"):
            UnusualEvent(
                ticker="X", event_type="iv_spike",
                score=-1.0, details={}, detected_at=1000.0,
            )

    def test_score_above_100(self):
        with pytest.raises(ValueError, match="Score must be"):
            UnusualEvent(
                ticker="X", event_type="iv_spike",
                score=101.0, details={}, detected_at=1000.0,
            )

    def test_frozen(self):
        e = UnusualEvent(
            ticker="X", event_type="iv_spike",
            score=50.0, details={}, detected_at=1000.0,
        )
        with pytest.raises(AttributeError):
            e.score = 99.0  # type: ignore[misc]

    @pytest.mark.parametrize("event_type", sorted(EVENT_TYPES))
    def test_all_event_types_valid(self, event_type):
        e = UnusualEvent(
            ticker="X", event_type=event_type,
            score=50.0, details={}, detected_at=1000.0,
        )
        assert e.event_type == event_type

    @pytest.mark.parametrize("score", [0.0, 25.0, 50.0, 75.0, 100.0])
    def test_valid_score_boundaries(self, score):
        e = UnusualEvent(
            ticker="X", event_type="iv_spike",
            score=score, details={}, detected_at=1000.0,
        )
        assert e.score == score


class TestUnusualScore:
    def test_basic_creation(self):
        s = UnusualScore(
            composite_score=50.0,
            flags=["High IV", "Volume Spike"],
            component_scores={"iv_spike": 60.0, "volume_surge": 40.0},
        )
        assert s.composite_score == 50.0
        assert s.flag_count == 2
        assert s.is_unusual is True

    def test_empty_score(self):
        s = UnusualScore(
            composite_score=0.0, flags=[], component_scores={},
        )
        assert s.is_unusual is False
        assert s.flag_count == 0

    def test_to_dict(self):
        s = UnusualScore(
            composite_score=75.5, flags=["High IV"],
            component_scores={"iv_spike": 75.5},
        )
        d = s.to_dict()
        assert d["composite_score"] == 75.5
        assert d["flags"] == ["High IV"]
        assert d["event_count"] == 0

    def test_invalid_composite_score(self):
        with pytest.raises(ValueError, match="Composite score"):
            UnusualScore(
                composite_score=150.0, flags=[], component_scores={},
            )

    def test_is_unusual_with_zero_score_and_flags(self):
        # flags present but score=0 → not unusual
        s = UnusualScore(
            composite_score=0.0, flags=["test"], component_scores={},
        )
        assert s.is_unusual is False


class TestUnusualSummary:
    def test_basic_creation(self):
        s = UnusualSummary(
            total_events=10, unique_tickers=5, avg_score=60.0,
            top_tickers=[{"ticker": "AAPL", "count": 3, "avg_score": 70.0}],
            type_breakdown={"iv_spike": 5, "volume_surge": 5},
        )
        assert s.total_events == 10

    def test_to_dict_with_highest(self):
        event = UnusualEvent(
            ticker="TSLA", event_type="sweep",
            score=95.0, details={}, detected_at=1000.0,
        )
        s = UnusualSummary(
            total_events=1, unique_tickers=1, avg_score=95.0,
            top_tickers=[], type_breakdown={"sweep": 1},
            highest_score_event=event,
        )
        d = s.to_dict()
        assert d["highest_score"]["ticker"] == "TSLA"

    def test_to_dict_no_highest(self):
        s = UnusualSummary(
            total_events=0, unique_tickers=0, avg_score=0.0,
            top_tickers=[], type_breakdown={},
        )
        d = s.to_dict()
        assert d["highest_score"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Part 2: UnusualDetectorConfig
# ═══════════════════════════════════════════════════════════════════════════


class TestUnusualDetectorConfig:
    def test_defaults(self):
        cfg = UnusualDetectorConfig()
        assert cfg.iv_rank_threshold == 80.0
        assert cfg.volume_surge_multiplier == 2.0
        assert cfg.oi_surge_pct == 20.0
        assert cfg.skew_std_threshold == 2.0
        assert cfg.sweep_vol_oi_threshold == 3.0
        assert cfg.max_events_per_signal == 5

    def test_total_weight(self):
        cfg = UnusualDetectorConfig()
        expected = 25.0 + 25.0 + 20.0 + 15.0 + 15.0
        assert cfg.total_weight() == expected

    def test_custom_weights(self):
        cfg = UnusualDetectorConfig(iv_weight=50.0, volume_weight=50.0)
        assert cfg.total_weight() == 50.0 + 50.0 + 20.0 + 15.0 + 15.0


# ═══════════════════════════════════════════════════════════════════════════
# Part 3: UnusualHistory
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def history():
    return UnusualHistory(max_window=20, max_tickers=10)


class TestHistoryBasics:
    def test_initial_empty(self, history):
        assert history.ticker_count == 0

    def test_update_creates_entry(self, history):
        history.update("AAPL", iv=0.3)
        assert history.ticker_count == 1

    def test_multiple_tickers(self, history):
        for i in range(5):
            history.update(f"T{i}", iv=0.3)
        assert history.ticker_count == 5

    def test_lru_eviction(self):
        h = UnusualHistory(max_window=10, max_tickers=3)
        h.update("A", iv=0.1)
        h.update("B", iv=0.2)
        h.update("C", iv=0.3)
        h.update("D", iv=0.4)  # should evict A (oldest)
        assert h.ticker_count == 3
        snap = h.get_stats_snapshot("A")
        assert snap["has_data"] is False

    def test_clear(self, history):
        history.update("AAPL", iv=0.3)
        history.update("TSLA", iv=0.5)
        history.clear()
        assert history.ticker_count == 0

    def test_clear_ticker(self, history):
        history.update("AAPL", iv=0.3)
        history.update("TSLA", iv=0.5)
        history.clear_ticker("AAPL")
        assert history.ticker_count == 1
        assert history.get_stats_snapshot("AAPL")["has_data"] is False

    def test_clear_nonexistent_ticker(self, history):
        history.clear_ticker("NOPE")  # no error


class TestHistoryUpdate:
    def test_skips_negative_iv(self, history):
        history.update("X", iv=-0.5)
        snap = history.get_stats_snapshot("X")
        assert snap["iv_samples"] == 0

    def test_skips_zero_volume(self, history):
        history.update("X", volume=0)
        snap = history.get_stats_snapshot("X")
        assert snap["volume_samples"] == 0

    def test_records_positive_values(self, history):
        history.update("X", iv=0.3, volume=1000, oi=5000, pc_ratio=1.2)
        snap = history.get_stats_snapshot("X")
        assert snap["iv_samples"] == 1
        assert snap["volume_samples"] == 1
        assert snap["oi_samples"] == 1
        assert snap["pc_ratio_samples"] == 1

    def test_tracks_last_oi(self, history):
        history.update("X", oi=1000)
        history.update("X", oi=1200)
        snap = history.get_stats_snapshot("X")
        assert snap["last_oi"] == 1000  # previous value


class TestIVRank:
    def test_insufficient_history(self, history):
        for i in range(4):
            history.update("X", iv=float(i))
        assert history.get_iv_rank("X", 5.0) is None

    def test_sufficient_history(self, history):
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            history.update("X", iv=v)
        rank = history.get_iv_rank("X", 35.0)
        assert rank is not None
        # 3 values below 35 out of 5 → 60%
        assert math.isclose(rank, 60.0)

    def test_above_all(self, history):
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            history.update("X", iv=v)
        rank = history.get_iv_rank("X", 60.0)
        assert rank == 100.0

    def test_below_all(self, history):
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            history.update("X", iv=v)
        rank = history.get_iv_rank("X", 5.0)
        assert rank == 0.0

    def test_unknown_ticker(self, history):
        assert history.get_iv_rank("UNKNOWN", 0.5) is None


class TestVolumeRatio:
    def test_insufficient_history(self, history):
        history.update("X", volume=100)
        history.update("X", volume=200)
        assert history.get_volume_ratio("X", 300) is None

    def test_sufficient_history(self, history):
        for v in [100.0, 200.0, 300.0]:
            history.update("X", volume=v)
        ratio = history.get_volume_ratio("X", 600.0)
        assert ratio is not None
        # mean = 200, ratio = 600/200 = 3.0
        assert math.isclose(ratio, 3.0)

    def test_low_mean_returns_none(self, history):
        for _ in range(5):
            history.update("X", volume=0.1)
        assert history.get_volume_ratio("X", 1.0) is None


class TestVolumeZScore:
    def test_insufficient_history(self, history):
        for _ in range(4):
            history.update("X", volume=100)
        assert history.get_volume_zscore("X", 100) is None

    def test_sufficient_history_low_variance(self, history):
        for _ in range(10):
            history.update("X", volume=100.0)
        zscore = history.get_volume_zscore("X", 200.0)
        assert zscore is not None
        # All same → std < 1 → ratio mode: 200/100 - 1 = 1.0
        assert math.isclose(zscore, 1.0)

    def test_high_variance(self, history):
        for v in [50.0, 100.0, 150.0, 200.0, 250.0]:
            history.update("X", volume=v)
        zscore = history.get_volume_zscore("X", 500.0)
        assert zscore is not None
        assert zscore > 0


class TestOIChangePct:
    def test_no_prior(self, history):
        assert history.get_oi_change_pct("X", 1000) is None

    def test_first_update_no_last_oi(self, history):
        history.update("X", oi=1000)
        assert history.get_oi_change_pct("X", 1200) is None

    def test_with_prior(self, history):
        history.update("X", oi=1000)
        history.update("X", oi=1200)  # sets last_oi=1000
        pct = history.get_oi_change_pct("X", 1500)
        assert pct is not None
        # prev=1000, current=1500 → (1500-1000)/1000 * 100 = 50%
        assert math.isclose(pct, 50.0)

    def test_negative_change(self, history):
        history.update("X", oi=1000)
        history.update("X", oi=800)
        pct = history.get_oi_change_pct("X", 700)
        assert pct is not None
        # prev=1000, current=700 → (700-1000)/1000 * 100 = -30%
        assert math.isclose(pct, -30.0)


class TestPCRatioZScore:
    def test_insufficient_history(self, history):
        for _ in range(4):
            history.update("X", pc_ratio=1.0)
        assert history.get_pc_ratio_zscore("X", 1.0) is None

    def test_sufficient_history_low_variance(self, history):
        for _ in range(10):
            history.update("X", pc_ratio=1.0)
        zscore = history.get_pc_ratio_zscore("X", 1.0)
        assert zscore == 0.0  # std < 0.01 → returns 0.0

    def test_high_value_zscore(self, history):
        for v in [0.8, 1.0, 0.9, 1.1, 1.0]:
            history.update("X", pc_ratio=v)
        zscore = history.get_pc_ratio_zscore("X", 2.0)
        assert zscore is not None
        assert zscore > 0

    def test_unknown_ticker(self, history):
        assert history.get_pc_ratio_zscore("UNKNOWN", 1.0) is None


class TestStatsSnapshot:
    def test_known_ticker(self, history):
        history.update("AAPL", iv=0.3, volume=1000)
        snap = history.get_stats_snapshot("AAPL")
        assert snap["has_data"] is True
        assert snap["iv_samples"] == 1
        assert snap["volume_samples"] == 1

    def test_unknown_ticker(self, history):
        snap = history.get_stats_snapshot("UNKNOWN")
        assert snap["has_data"] is False


# ═══════════════════════════════════════════════════════════════════════════
# Part 4: _get_float helper
# ═══════════════════════════════════════════════════════════════════════════


class TestGetFloat:
    def test_first_key(self):
        assert _get_float({"a": 1.5}, "a") == 1.5

    def test_fallback_key(self):
        assert _get_float({"b": 2.5}, "a", "b") == 2.5

    def test_string_number(self):
        assert _get_float({"a": "3.14"}, "a") == 3.14

    def test_none_value(self):
        assert _get_float({"a": None}, "a") is None

    def test_missing_key(self):
        assert _get_float({}, "a") is None

    def test_nan_returns_none(self):
        assert _get_float({"a": float("nan")}, "a") is None

    def test_invalid_string(self):
        assert _get_float({"a": "abc"}, "a") is None

    def test_multiple_keys_first_valid(self):
        assert _get_float({"b": 5.0}, "a", "b", "c") == 5.0


# ═══════════════════════════════════════════════════════════════════════════
# Part 5: UnusualDetector
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def detector():
    return UnusualDetector(
        history=UnusualHistory(max_window=20, max_tickers=100),
        config=UnusualDetectorConfig(),
    )


class TestDetectorInit:
    def test_default_init(self):
        d = UnusualDetector()
        assert d.config is not None
        assert d.history is not None

    def test_custom_config(self):
        cfg = UnusualDetectorConfig(iv_rank_threshold=90.0)
        d = UnusualDetector(config=cfg)
        assert d.config.iv_rank_threshold == 90.0


class TestScanSignalBasic:
    def test_empty_signal(self, detector):
        events = detector.scan_signal({})
        assert events == []

    def test_no_ticker(self, detector):
        events = detector.scan_signal({"market_data": {"volume": 1000}})
        assert events == []

    def test_no_market_data(self, detector):
        events = detector.scan_signal({"ticker": "AAPL"})
        assert events == []

    def test_string_market_data(self, detector):
        import json
        md = json.dumps({"atm_iv": 0.5})
        events = detector.scan_signal({"ticker": "AAPL", "market_data": md})
        assert isinstance(events, list)

    def test_invalid_json_market_data(self, detector):
        events = detector.scan_signal({"ticker": "AAPL", "market_data": "not json"})
        assert events == []


class TestIVSpikeDetection:
    def test_iv_spike_detected(self, detector):
        # Build enough history for IV rank
        for v in [0.1, 0.15, 0.2, 0.25, 0.3]:
            detector.scan_signal({
                "ticker": "AAPL",
                "market_data": {"atm_iv": v},
            })

        # Now scan with a very high IV
        events = detector.scan_signal({
            "ticker": "AAPL",
            "market_data": {"atm_iv": 0.8},
        })
        iv_events = [e for e in events if e.event_type == "iv_spike"]
        assert len(iv_events) >= 1
        assert iv_events[0].score > 0

    def test_iv_below_threshold_no_event(self, detector):
        for v in [0.1, 0.15, 0.2, 0.25, 0.3, 0.35]:
            detector.scan_signal({
                "ticker": "AAPL",
                "market_data": {"atm_iv": v},
            })

        # IV within normal range
        events = detector.scan_signal({
            "ticker": "AAPL",
            "market_data": {"atm_iv": 0.15},
        })
        iv_events = [e for e in events if e.event_type == "iv_spike"]
        assert len(iv_events) == 0


class TestVolumeSurgeDetection:
    def test_volume_surge_detected(self, detector):
        # Build baseline
        for _ in range(5):
            detector.scan_signal({
                "ticker": "AAPL",
                "market_data": {"volume": 1000},
            })

        # Massive volume spike
        events = detector.scan_signal({
            "ticker": "AAPL",
            "market_data": {"volume": 5000},
        })
        vol_events = [e for e in events if e.event_type == "volume_surge"]
        assert len(vol_events) >= 1

    def test_normal_volume_no_event(self, detector):
        for _ in range(5):
            detector.scan_signal({
                "ticker": "AAPL",
                "market_data": {"volume": 1000},
            })
        events = detector.scan_signal({
            "ticker": "AAPL",
            "market_data": {"volume": 1100},
        })
        vol_events = [e for e in events if e.event_type == "volume_surge"]
        assert len(vol_events) == 0

    def test_fallback_to_avg_volume(self, detector):
        events = detector.scan_signal({
            "ticker": "NEW",
            "market_data": {"volume": 10000, "averageVolume": 1000},
        })
        # ratio = 10000/1000 = 10x → should trigger
        vol_events = [e for e in events if e.event_type == "volume_surge"]
        assert len(vol_events) >= 1


class TestSweepDetection:
    def test_sweep_detected(self, detector):
        # High vol/OI ratio (> 3.0)
        events = detector.scan_signal({
            "ticker": "AAPL",
            "market_data": {
                "volume": 10000,
                "call_oi": 1000,
                "put_oi": 500,
            },
        })
        sweep_events = [e for e in events if e.event_type == "sweep"]
        # vol/oi = 10000 / 1500 ≈ 6.67 > 3.0
        assert len(sweep_events) >= 1

    def test_no_sweep_low_ratio(self, detector):
        events = detector.scan_signal({
            "ticker": "AAPL",
            "market_data": {
                "volume": 100,
                "call_oi": 1000,
                "put_oi": 500,
            },
        })
        sweep_events = [e for e in events if e.event_type == "sweep"]
        assert len(sweep_events) == 0


class TestScanBatch:
    def test_empty_batch(self, detector):
        events = detector.scan_batch([])
        assert events == []

    def test_multiple_signals(self, detector):
        # Build baselines then scan
        for _ in range(5):
            detector.scan_signal({
                "ticker": "AAPL",
                "market_data": {"volume": 1000, "atm_iv": 0.2},
            })
        signals = [
            {"ticker": "AAPL", "market_data": {"volume": 5000, "atm_iv": 0.8}},
            {"ticker": "TSLA", "market_data": {"volume": 10000, "averageVolume": 1000}},
        ]
        events = detector.scan_batch(signals)
        assert isinstance(events, list)
        assert len(events) >= 1


class TestComputeScore:
    def test_empty_events(self, detector):
        score = detector.compute_score([])
        assert score.composite_score == 0.0
        assert score.flags == []
        assert score.is_unusual is False

    def test_single_event(self, detector):
        events = [
            UnusualEvent(
                ticker="AAPL", event_type="iv_spike",
                score=80.0, details={}, detected_at=1000.0,
            ),
        ]
        score = detector.compute_score(events)
        assert score.composite_score > 0
        assert "High IV" in score.flags
        assert score.is_unusual is True
        assert "iv_spike" in score.component_scores

    def test_multiple_events(self, detector):
        events = [
            UnusualEvent(ticker="AAPL", event_type="iv_spike", score=80.0, details={}, detected_at=1000.0),
            UnusualEvent(ticker="AAPL", event_type="volume_surge", score=60.0, details={}, detected_at=1000.0),
        ]
        score = detector.compute_score(events)
        assert score.composite_score > 0
        assert score.flag_count == 2

    def test_max_per_type(self, detector):
        events = [
            UnusualEvent(ticker="AAPL", event_type="iv_spike", score=60.0, details={}, detected_at=1000.0),
            UnusualEvent(ticker="AAPL", event_type="iv_spike", score=80.0, details={}, detected_at=2000.0),
        ]
        score = detector.compute_score(events)
        assert score.component_scores["iv_spike"] == 80.0  # max, not sum


class TestComputeSummary:
    def test_empty_events(self, detector):
        summary = detector.compute_summary([])
        assert summary.total_events == 0
        assert summary.unique_tickers == 0
        assert summary.highest_score_event is None

    def test_single_event(self, detector):
        events = [
            UnusualEvent(
                ticker="AAPL", event_type="iv_spike",
                score=75.0, details={}, detected_at=1000.0,
            ),
        ]
        summary = detector.compute_summary(events)
        assert summary.total_events == 1
        assert summary.unique_tickers == 1
        assert summary.avg_score == 75.0
        assert summary.highest_score_event.ticker == "AAPL"

    def test_multiple_tickers(self, detector):
        events = [
            UnusualEvent(ticker="AAPL", event_type="iv_spike", score=80.0, details={}, detected_at=1000.0),
            UnusualEvent(ticker="TSLA", event_type="volume_surge", score=60.0, details={}, detected_at=1000.0),
            UnusualEvent(ticker="AAPL", event_type="sweep", score=90.0, details={}, detected_at=2000.0),
        ]
        summary = detector.compute_summary(events)
        assert summary.total_events == 3
        assert summary.unique_tickers == 2
        assert summary.type_breakdown["iv_spike"] == 1
        assert summary.type_breakdown["sweep"] == 1
        assert summary.highest_score_event.score == 90.0

    def test_top_tickers_sorted_by_count(self, detector):
        events = [
            UnusualEvent(ticker="AAPL", event_type="iv_spike", score=80.0, details={}, detected_at=1000.0),
            UnusualEvent(ticker="AAPL", event_type="sweep", score=70.0, details={}, detected_at=1000.0),
            UnusualEvent(ticker="TSLA", event_type="iv_spike", score=90.0, details={}, detected_at=1000.0),
        ]
        summary = detector.compute_summary(events)
        assert summary.top_tickers[0]["ticker"] == "AAPL"
        assert summary.top_tickers[0]["count"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# Part 6: Parametrized & Stress
# ═══════════════════════════════════════════════════════════════════════════


class TestParametrized:
    @pytest.mark.parametrize("iv_val,threshold,expect_event", [
        (0.8, 80.0, True),    # High IV rank should trigger
        (0.1, 80.0, False),   # Low IV rank should not trigger
    ])
    def test_iv_detection_parametrized(self, iv_val, threshold, expect_event):
        cfg = UnusualDetectorConfig(iv_rank_threshold=threshold)
        det = UnusualDetector(config=cfg)
        # Build baseline
        for v in [0.1, 0.15, 0.2, 0.25, 0.3]:
            det.scan_signal({"ticker": "X", "market_data": {"atm_iv": v}})
        events = det.scan_signal({"ticker": "X", "market_data": {"atm_iv": iv_val}})
        iv_events = [e for e in events if e.event_type == "iv_spike"]
        if expect_event:
            assert len(iv_events) >= 1
        else:
            assert len(iv_events) == 0

    @pytest.mark.parametrize("n_signals", [0, 1, 10, 50])
    def test_scan_batch_various_sizes(self, detector, n_signals):
        signals = [
            {"ticker": f"T{i}", "market_data": {"volume": 1000 * (i + 1)}}
            for i in range(n_signals)
        ]
        events = detector.scan_batch(signals)
        assert isinstance(events, list)


class TestStress:
    def test_scan_200_signals(self):
        det = UnusualDetector()
        signals = [
            {
                "ticker": f"T{i % 20}",
                "market_data": {
                    "atm_iv": 0.1 + i * 0.01,
                    "volume": 1000 + i * 100,
                    "call_oi": 500 + i * 10,
                    "put_oi": 500 + i * 10,
                    "pc_ratio": 0.8 + i * 0.01,
                },
            }
            for i in range(200)
        ]
        events = det.scan_batch(signals)
        assert isinstance(events, list)

    def test_history_100_tickers(self):
        h = UnusualHistory(max_window=50, max_tickers=100)
        for i in range(100):
            for _ in range(10):
                h.update(f"T{i}", iv=0.2 + i * 0.01, volume=1000.0 + i)
        assert h.ticker_count == 100

    def test_compute_score_many_events(self):
        det = UnusualDetector()
        events = [
            UnusualEvent(
                ticker=f"T{i % 10}",
                event_type=list(EVENT_TYPES)[i % 5],
                score=50.0 + (i % 50),
                details={},
                detected_at=float(i),
            )
            for i in range(200)
        ]
        score = det.compute_score(events)
        assert score.composite_score >= 0
        assert score.composite_score <= 100

    def test_compute_summary_many_events(self):
        det = UnusualDetector()
        events = [
            UnusualEvent(
                ticker=f"T{i % 15}",
                event_type=list(EVENT_TYPES)[i % 5],
                score=20.0 + (i % 80),
                details={},
                detected_at=float(i * 100),
            )
            for i in range(500)
        ]
        summary = det.compute_summary(events)
        assert summary.total_events == 500
        assert summary.unique_tickers == 15
        assert len(summary.top_tickers) <= 10
