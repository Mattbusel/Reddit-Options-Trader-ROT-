"""Tests for unusual activity detector engine."""

from __future__ import annotations

import time

import pytest

from rot.unusual.config import UnusualDetectorConfig
from rot.unusual.detector import UnusualDetector, _get_float
from rot.unusual.history import UnusualHistory
from rot.unusual.types import UnusualEvent, UnusualScore, UnusualSummary


# ── Helpers ──


def _make_signal(ticker: str = "SPY", **market_overrides) -> dict:
    """Build a minimal signal dict for testing."""
    md = {
        "atm_iv": 0.35,
        "volume": 1000,
        "avg_volume": 500,
        "call_oi": 5000,
        "put_oi": 5000,
        "pc_ratio": 0.85,
    }
    md.update(market_overrides)
    return {
        "id": f"sig-{ticker}-001",
        "ticker": ticker,
        "created_at": time.time(),
        "market_data": {ticker: md},
    }


def _primed_detector(ticker: str = "SPY", n: int = 20) -> UnusualDetector:
    """Create a detector pre-loaded with N baseline observations."""
    history = UnusualHistory()
    for i in range(n):
        history.update(
            ticker,
            iv=0.25 + (i % 5) * 0.02,      # 0.25-0.33
            volume=500.0 + (i % 3) * 50.0,  # 500-600
            oi=10000.0 + i * 10.0,           # 10000-10190
            pc_ratio=0.7 + (i % 4) * 0.1,   # 0.7-1.0
        )
    return UnusualDetector(history=history)


# ── _get_float helper ──


class TestGetFloat:
    """Tests for multi-key float extraction."""

    def test_first_key(self):
        assert _get_float({"a": 1.5}, "a") == 1.5

    def test_fallback_key(self):
        assert _get_float({"b": 2.0}, "a", "b") == 2.0

    def test_missing_returns_none(self):
        assert _get_float({}, "a", "b") is None

    def test_none_value_returns_none(self):
        assert _get_float({"a": None}, "a") is None

    def test_string_number(self):
        assert _get_float({"a": "3.14"}, "a") == pytest.approx(3.14)

    def test_invalid_string(self):
        assert _get_float({"a": "not_a_number"}, "a") is None

    def test_nan_returns_none(self):
        assert _get_float({"a": float("nan")}, "a") is None

    def test_integer(self):
        assert _get_float({"a": 42}, "a") == 42.0


# ── Detector Basics ──


class TestDetectorBasics:
    """Basic detector lifecycle tests."""

    def test_create_default(self):
        d = UnusualDetector()
        assert d.history is not None
        assert d.config is not None

    def test_create_custom(self):
        cfg = UnusualDetectorConfig(iv_rank_threshold=90.0)
        h = UnusualHistory(max_window=50)
        d = UnusualDetector(history=h, config=cfg)
        assert d.config.iv_rank_threshold == 90.0

    def test_scan_empty_signal(self):
        d = UnusualDetector()
        assert d.scan_signal({}) == []

    def test_scan_no_ticker(self):
        d = UnusualDetector()
        assert d.scan_signal({"market_data": {}}) == []

    def test_scan_no_market_data(self):
        d = UnusualDetector()
        assert d.scan_signal({"ticker": "SPY"}) == []

    def test_scan_market_data_json_string(self):
        d = UnusualDetector()
        import json
        sig = {
            "ticker": "SPY",
            "market_data": json.dumps({"SPY": {"atm_iv": 0.5}}),
        }
        # No history primed, so no events expected, but shouldn't crash
        events = d.scan_signal(sig)
        assert isinstance(events, list)

    def test_scan_malformed_json_string(self):
        d = UnusualDetector()
        sig = {"ticker": "SPY", "market_data": "not-json"}
        assert d.scan_signal(sig) == []

    def test_scan_market_data_not_dict(self):
        d = UnusualDetector()
        sig = {"ticker": "SPY", "market_data": [1, 2, 3]}
        assert d.scan_signal(sig) == []


# ── IV Spike Detection ──


class TestIVSpikeDetection:
    """IV spike detection algorithm tests."""

    def test_iv_spike_detected(self):
        det = _primed_detector()
        sig = _make_signal(atm_iv=0.80)  # way above baseline 0.25-0.33
        events = det.scan_signal(sig)
        iv_events = [e for e in events if e.event_type == "iv_spike"]
        assert len(iv_events) >= 1
        assert iv_events[0].score > 0

    def test_iv_spike_not_detected_low(self):
        det = _primed_detector()
        sig = _make_signal(atm_iv=0.26)  # within normal range
        events = det.scan_signal(sig)
        iv_events = [e for e in events if e.event_type == "iv_spike"]
        assert len(iv_events) == 0

    def test_iv_spike_details(self):
        det = _primed_detector()
        sig = _make_signal(atm_iv=0.90)
        events = det.scan_signal(sig)
        iv_events = [e for e in events if e.event_type == "iv_spike"]
        assert len(iv_events) >= 1
        d = iv_events[0].details
        assert "atm_iv" in d
        assert "iv_rank" in d
        assert "threshold" in d

    def test_iv_spike_camelcase_key(self):
        """Detector handles camelCase naming convention."""
        det = _primed_detector()
        sig = _make_signal()
        # Override market_data using camelCase
        sig["market_data"]["SPY"] = {"impliedVolatility": 0.90}
        events = det.scan_signal(sig)
        iv_events = [e for e in events if e.event_type == "iv_spike"]
        assert len(iv_events) >= 1


# ── Volume Surge Detection ──


class TestVolumeSurgeDetection:
    """Volume surge detection tests."""

    def test_volume_surge_detected_by_history(self):
        det = _primed_detector()
        sig = _make_signal(volume=5000)  # ~10x baseline ~500
        events = det.scan_signal(sig)
        vol_events = [e for e in events if e.event_type == "volume_surge"]
        assert len(vol_events) >= 1

    def test_volume_surge_fallback_avg_volume(self):
        """When no history, uses avg_volume from market data."""
        det = UnusualDetector()  # no history primed
        sig = _make_signal(volume=5000, avg_volume=1000)
        events = det.scan_signal(sig)
        vol_events = [e for e in events if e.event_type == "volume_surge"]
        assert len(vol_events) >= 1

    def test_volume_surge_normal(self):
        det = _primed_detector()
        sig = _make_signal(volume=550)  # near baseline
        events = det.scan_signal(sig)
        vol_events = [e for e in events if e.event_type == "volume_surge"]
        assert len(vol_events) == 0

    def test_volume_surge_details(self):
        det = _primed_detector()
        sig = _make_signal(volume=5000)
        events = det.scan_signal(sig)
        vol_events = [e for e in events if e.event_type == "volume_surge"]
        if vol_events:
            d = vol_events[0].details
            assert "volume" in d
            assert "volume_ratio" in d


# ── OI Surge Detection ──


class TestOISurgeDetection:
    """OI surge detection tests."""

    def test_oi_surge_detected(self):
        det = _primed_detector()
        # Baseline OI around 10190 (last value).
        # OI surge needs >20% change from last_oi
        sig = _make_signal(call_oi=8000, put_oi=8000)  # total 16000 vs last ~10190
        events = det.scan_signal(sig)
        oi_events = [e for e in events if e.event_type == "oi_surge"]
        assert len(oi_events) >= 1

    def test_oi_surge_normal(self):
        det = _primed_detector()
        sig = _make_signal(call_oi=5100, put_oi=5100)  # total 10200, ~0.1% change
        events = det.scan_signal(sig)
        oi_events = [e for e in events if e.event_type == "oi_surge"]
        assert len(oi_events) == 0

    def test_oi_surge_first_signal_no_event(self):
        """First OI observation can't trigger surge (no prior)."""
        det = UnusualDetector()
        sig = _make_signal(call_oi=50000, put_oi=50000)
        events = det.scan_signal(sig)
        oi_events = [e for e in events if e.event_type == "oi_surge"]
        assert len(oi_events) == 0


# ── Skew Shift Detection ──


class TestSkewShiftDetection:
    """Put/call skew shift detection tests."""

    def test_skew_shift_detected_bearish(self):
        det = _primed_detector()
        sig = _make_signal(pc_ratio=3.5)  # way above baseline 0.7-1.0
        events = det.scan_signal(sig)
        skew_events = [e for e in events if e.event_type == "skew_shift"]
        assert len(skew_events) >= 1
        assert skew_events[0].details["direction"] == "bearish_skew"

    def test_skew_shift_detected_bullish(self):
        det = _primed_detector()
        sig = _make_signal(pc_ratio=0.1)  # way below baseline
        events = det.scan_signal(sig)
        skew_events = [e for e in events if e.event_type == "skew_shift"]
        assert len(skew_events) >= 1
        assert skew_events[0].details["direction"] == "bullish_skew"

    def test_skew_shift_normal(self):
        det = _primed_detector()
        sig = _make_signal(pc_ratio=0.85)  # within baseline
        events = det.scan_signal(sig)
        skew_events = [e for e in events if e.event_type == "skew_shift"]
        assert len(skew_events) == 0


# ── Sweep Detection ──


class TestSweepDetection:
    """Sweep (vol/OI ratio) detection tests."""

    def test_sweep_detected(self):
        det = _primed_detector()
        # vol/oi > 3.0 threshold
        sig = _make_signal(volume=40000, call_oi=5000, put_oi=5000)  # 40000/10000 = 4.0
        events = det.scan_signal(sig)
        sweep_events = [e for e in events if e.event_type == "sweep"]
        assert len(sweep_events) >= 1

    def test_sweep_not_detected_low_ratio(self):
        det = _primed_detector()
        sig = _make_signal(volume=1000, call_oi=5000, put_oi=5000)  # 1000/10000 = 0.1
        events = det.scan_signal(sig)
        sweep_events = [e for e in events if e.event_type == "sweep"]
        assert len(sweep_events) == 0


# ── Composite Scoring ──


class TestCompositeScoring:
    """Composite score computation tests."""

    def test_empty_events(self):
        det = UnusualDetector()
        score = det.compute_score([])
        assert score.composite_score == 0.0
        assert score.flags == []
        assert score.is_unusual is False

    def test_single_event(self):
        det = UnusualDetector()
        event = UnusualEvent(
            ticker="SPY", event_type="iv_spike", score=80.0,
            details={}, detected_at=time.time(),
        )
        score = det.compute_score([event])
        assert score.composite_score > 0
        assert "High IV" in score.flags
        assert "iv_spike" in score.component_scores

    def test_multiple_events_same_type(self):
        det = UnusualDetector()
        events = [
            UnusualEvent(
                ticker="SPY", event_type="iv_spike", score=80.0,
                details={}, detected_at=time.time(),
            ),
            UnusualEvent(
                ticker="SPY", event_type="iv_spike", score=60.0,
                details={}, detected_at=time.time(),
            ),
        ]
        score = det.compute_score(events)
        # Should use max score per type (80, not 60)
        assert score.component_scores["iv_spike"] == 80.0

    def test_multiple_event_types(self):
        det = UnusualDetector()
        events = [
            UnusualEvent(
                ticker="SPY", event_type="iv_spike", score=80.0,
                details={}, detected_at=time.time(),
            ),
            UnusualEvent(
                ticker="SPY", event_type="volume_surge", score=70.0,
                details={}, detected_at=time.time(),
            ),
        ]
        score = det.compute_score(events)
        assert score.composite_score > 0
        assert len(score.flags) == 2
        assert "iv_spike" in score.component_scores
        assert "volume_surge" in score.component_scores

    def test_score_capped_at_100(self):
        det = UnusualDetector()
        events = [
            UnusualEvent(
                ticker="SPY", event_type=etype, score=100.0,
                details={}, detected_at=time.time(),
            )
            for etype in ["iv_spike", "volume_surge", "oi_surge", "skew_shift", "sweep"]
        ]
        score = det.compute_score(events)
        assert score.composite_score <= 100.0


# ── Summary ──


class TestComputeSummary:
    """Summary computation tests."""

    def test_empty_summary(self):
        det = UnusualDetector()
        summary = det.compute_summary([])
        assert summary.total_events == 0
        assert summary.unique_tickers == 0
        assert summary.highest_score_event is None

    def test_summary_basic(self):
        det = UnusualDetector()
        events = [
            UnusualEvent(
                ticker="SPY", event_type="iv_spike", score=80.0,
                details={}, detected_at=time.time(),
            ),
            UnusualEvent(
                ticker="AAPL", event_type="volume_surge", score=60.0,
                details={}, detected_at=time.time(),
            ),
            UnusualEvent(
                ticker="SPY", event_type="sweep", score=50.0,
                details={}, detected_at=time.time(),
            ),
        ]
        summary = det.compute_summary(events)
        assert summary.total_events == 3
        assert summary.unique_tickers == 2
        assert summary.avg_score == pytest.approx(63.3, rel=0.01)
        assert summary.highest_score_event.ticker == "SPY"
        assert summary.highest_score_event.score == 80.0

    def test_summary_type_breakdown(self):
        det = UnusualDetector()
        events = [
            UnusualEvent(
                ticker="SPY", event_type="iv_spike", score=80.0,
                details={}, detected_at=time.time(),
            ),
            UnusualEvent(
                ticker="AAPL", event_type="iv_spike", score=70.0,
                details={}, detected_at=time.time(),
            ),
            UnusualEvent(
                ticker="SPY", event_type="sweep", score=50.0,
                details={}, detected_at=time.time(),
            ),
        ]
        summary = det.compute_summary(events)
        assert summary.type_breakdown["iv_spike"] == 2
        assert summary.type_breakdown["sweep"] == 1

    def test_summary_top_tickers(self):
        det = UnusualDetector()
        events = [
            UnusualEvent(
                ticker="SPY", event_type="iv_spike", score=80.0,
                details={}, detected_at=time.time(),
            ),
            UnusualEvent(
                ticker="SPY", event_type="volume_surge", score=60.0,
                details={}, detected_at=time.time(),
            ),
            UnusualEvent(
                ticker="AAPL", event_type="sweep", score=50.0,
                details={}, detected_at=time.time(),
            ),
        ]
        summary = det.compute_summary(events)
        assert summary.top_tickers[0]["ticker"] == "SPY"
        assert summary.top_tickers[0]["count"] == 2


# ── Batch Scan ──


class TestBatchScan:
    """Batch scanning tests."""

    def test_batch_empty(self):
        det = UnusualDetector()
        assert det.scan_batch([]) == []

    def test_batch_multiple(self):
        det = _primed_detector()
        signals = [
            _make_signal("SPY", atm_iv=0.90),
            _make_signal("SPY", volume=5000),
        ]
        events = det.scan_batch(signals)
        assert len(events) > 0


# ── Event Cap ──


class TestEventCap:
    """Max events per signal cap tests."""

    def test_events_capped(self):
        cfg = UnusualDetectorConfig(max_events_per_signal=2)
        det = _primed_detector()
        det._config = cfg  # swap config
        # Create signal that triggers many events
        sig = _make_signal(
            atm_iv=0.90, volume=50000, call_oi=20000, put_oi=20000,
            pc_ratio=5.0,
        )
        events = det.scan_signal(sig)
        assert len(events) <= 2

    def test_capped_events_are_highest_score(self):
        cfg = UnusualDetectorConfig(max_events_per_signal=1)
        det = _primed_detector()
        det._config = cfg
        sig = _make_signal(
            atm_iv=0.90, volume=50000, call_oi=20000, put_oi=20000,
            pc_ratio=5.0,
        )
        events = det.scan_signal(sig)
        if events:
            # Should be the highest scoring event
            all_events_uncapped = UnusualDetector(
                history=det.history,
                config=UnusualDetectorConfig(max_events_per_signal=10),
            ).scan_signal(sig)
            max_score = max(e.score for e in all_events_uncapped)
            assert events[0].score == max_score
