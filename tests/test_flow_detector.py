"""Tests for the institutional options flow detector.

Covers all 5 detection algorithms (block trade, sweep, dark pool,
accumulation, distribution), batch scanning, composite scoring,
filtering, configuration, helper functions, and edge cases.
"""

import json
import math
import time

import pytest

from rot.flow.detector import (
    FlowDetector,
    FlowDetectorConfig,
    _extract_ticker_data,
    _parse_market_data,
    _safe_float,
    _safe_int,
)
from rot.flow.history import FlowHistory
from rot.flow.types import FlowEvent, FlowScore


# ── Helper: market data builder ────────────────────────


def _md(
    *,
    last_close=150.0,
    atm_iv=0.35,
    call_oi=5000,
    put_oi=3000,
    volume=1000,
    put_call_oi_ratio=0.0,
    change_1d=0.0,
):
    """Build a flat market data dict with sensible defaults."""
    d = {
        "last_close": last_close,
        "atm_iv": atm_iv,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "volume": volume,
    }
    if put_call_oi_ratio:
        d["put_call_oi_ratio"] = put_call_oi_ratio
    if change_1d:
        d["change_1d"] = change_1d
    return d


# ── Timestamp fixture ──────────────────────────────────

NOW = time.time()


# ================================================================
# 1. Helper functions
# ================================================================


class TestSafeFloat:
    def test_normal_float(self):
        assert _safe_float(3.14) == 3.14

    def test_int_input(self):
        assert _safe_float(5) == 5.0

    def test_string_number(self):
        assert _safe_float("2.5") == 2.5

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0
        assert _safe_float(None, 42.0) == 42.0

    def test_nan_returns_default(self):
        assert _safe_float(float("nan")) == 0.0

    def test_inf_returns_default(self):
        assert _safe_float(float("inf")) == 0.0
        assert _safe_float(float("-inf"), -1.0) == -1.0

    def test_bad_string_returns_default(self):
        assert _safe_float("not-a-number", 99.0) == 99.0

    def test_list_returns_default(self):
        assert _safe_float([1, 2]) == 0.0


class TestSafeInt:
    def test_normal_int(self):
        assert _safe_int(10) == 10

    def test_float_truncated(self):
        assert _safe_int(3.9) == 3

    def test_string_number(self):
        assert _safe_int("7") == 7

    def test_none_returns_default(self):
        assert _safe_int(None) == 0
        assert _safe_int(None, -1) == -1

    def test_bad_string_returns_default(self):
        assert _safe_int("abc", 5) == 5


class TestParseMarketData:
    def test_dict_passthrough(self):
        d = {"atm_iv": 0.3}
        assert _parse_market_data(d) is d

    def test_json_string(self):
        j = json.dumps({"call_oi": 1000})
        assert _parse_market_data(j) == {"call_oi": 1000}

    def test_bad_json_returns_empty(self):
        assert _parse_market_data("{broken") == {}

    def test_none_returns_empty(self):
        assert _parse_market_data(None) == {}

    def test_number_returns_empty(self):
        assert _parse_market_data(42) == {}


class TestExtractTickerData:
    def test_nested_by_ticker(self):
        md = {"TSLA": {"atm_iv": 0.4, "call_oi": 500}}
        assert _extract_ticker_data(md, "TSLA") == {"atm_iv": 0.4, "call_oi": 500}

    def test_flat_structure(self):
        md = {"atm_iv": 0.3, "call_oi": 100}
        assert _extract_ticker_data(md, "TSLA") == md

    def test_missing_ticker_no_market_keys(self):
        md = {"AAPL": {"atm_iv": 0.3}}
        assert _extract_ticker_data(md, "TSLA") == {}


# ================================================================
# 2. Block trade detection
# ================================================================


class TestBlockTrade:
    def test_detect_above_threshold(self):
        """Block trade detected when estimated premium exceeds threshold."""
        # Premium approx: volume * 0.4 * price * sigma * sqrt(30/365) * 100
        # With volume=2000, price=150, sigma=0.35:
        # atm_approx ~ 0.4 * 150 * 0.35 * sqrt(0.0822) ~ 0.4*150*0.35*0.2867 ~ 6.02
        # premium ~ 2000 * 6.02 * 100 = 1_204_000 >> 100_000
        detector = FlowDetector()
        md = _md(volume=2000, last_close=150.0, atm_iv=0.35, call_oi=8000, put_oi=2000)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) == 1
        evt = block_events[0]
        assert evt.ticker == "TSLA"
        assert evt.premium > 100_000
        assert evt.volume == 2000

    def test_no_detection_below_threshold(self):
        """No block trade when premium is below threshold."""
        # With volume=1, price=10 => tiny premium
        detector = FlowDetector()
        md = _md(volume=1, last_close=10.0, atm_iv=0.10)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) == 0

    def test_direction_bullish_from_oi(self):
        """Direction inferred as bullish when call_oi >> put_oi."""
        detector = FlowDetector()
        md = _md(volume=2000, last_close=150.0, call_oi=10000, put_oi=1000)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) >= 1
        # put/call ratio = 1000/10000 = 0.1 < 0.6 => bullish
        assert block_events[0].direction == "bullish"

    def test_direction_bearish_from_oi(self):
        """Direction inferred as bearish when put_oi >> call_oi."""
        detector = FlowDetector()
        md = _md(volume=2000, last_close=150.0, call_oi=1000, put_oi=5000)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) >= 1
        # put/call ratio = 5000/1000 = 5.0 > 1.5 => bearish
        assert block_events[0].direction == "bearish"

    def test_direction_neutral_balanced_oi(self):
        """Direction is neutral when put/call ratio between 0.6 and 1.5."""
        detector = FlowDetector()
        md = _md(volume=2000, last_close=150.0, call_oi=5000, put_oi=5000)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) >= 1
        assert block_events[0].direction == "neutral"

    def test_zero_volume_no_detection(self):
        """No block trade with zero volume."""
        detector = FlowDetector()
        md = _md(volume=0)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) == 0

    def test_zero_price_no_detection(self):
        """No block trade with zero price."""
        detector = FlowDetector()
        md = _md(volume=5000, last_close=0.0)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) == 0

    def test_signal_id_propagated(self):
        """signal_id is carried through to the event."""
        detector = FlowDetector()
        md = _md(volume=2000, last_close=150.0)
        events = detector.detect_from_market_data(
            "TSLA", md, signal_id="sig-123", timestamp=NOW
        )
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) >= 1
        assert block_events[0].signal_id == "sig-123"

    def test_default_iv_used_when_missing(self):
        """When atm_iv is 0 or missing, defaults to 0.30 sigma."""
        detector = FlowDetector()
        md = _md(volume=3000, last_close=200.0, atm_iv=0)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        # sigma defaults to 0.30, premium should still exceed threshold
        # 3000 * 0.4 * 200 * 0.30 * sqrt(30/365) * 100 = 3000*6.88*100 ~ 2_065_000
        assert len(block_events) >= 1

    def test_custom_threshold(self):
        """Custom block_premium_threshold works."""
        # Set threshold very high so default volume/price won't trigger
        config = FlowDetectorConfig(block_premium_threshold=10_000_000)
        detector = FlowDetector(config=config)
        md = _md(volume=500, last_close=100.0)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) == 0


# ================================================================
# 3. Sweep detection
# ================================================================


class TestSweep:
    def test_detect_high_volume_and_premium(self):
        """Sweep detected with volume >= threshold and premium >= threshold."""
        detector = FlowDetector()
        md = _md(volume=1000, last_close=200.0, atm_iv=0.40, put_call_oi_ratio=0.4)
        events = detector.detect_from_market_data("NVDA", md, timestamp=NOW)
        sweep_events = [e for e in events if e.flow_type == "sweep"]
        assert len(sweep_events) == 1
        assert sweep_events[0].direction == "bullish"  # ratio 0.4 < 0.6

    def test_no_detection_volume_too_low(self):
        """No sweep when volume < sweep_volume_threshold."""
        detector = FlowDetector()
        md = _md(volume=100, last_close=200.0)  # 100 < 500 default
        events = detector.detect_from_market_data("NVDA", md, timestamp=NOW)
        sweep_events = [e for e in events if e.flow_type == "sweep"]
        assert len(sweep_events) == 0

    def test_no_detection_premium_too_low(self):
        """No sweep when estimated premium < sweep_premium_threshold."""
        # Low price + low IV => low premium even with enough volume
        detector = FlowDetector()
        md = _md(volume=500, last_close=1.0, atm_iv=0.10)
        events = detector.detect_from_market_data("PENNY", md, timestamp=NOW)
        sweep_events = [e for e in events if e.flow_type == "sweep"]
        assert len(sweep_events) == 0

    def test_bearish_direction_from_put_call_ratio(self):
        """Sweep direction bearish when put_call_oi_ratio > 1.5."""
        detector = FlowDetector()
        md = _md(volume=1000, last_close=200.0, atm_iv=0.40, put_call_oi_ratio=2.0)
        events = detector.detect_from_market_data("SPY", md, timestamp=NOW)
        sweep_events = [e for e in events if e.flow_type == "sweep"]
        assert len(sweep_events) == 1
        assert sweep_events[0].direction == "bearish"

    def test_neutral_direction_balanced_ratio(self):
        """Sweep direction neutral when ratio between 0.6 and 1.5."""
        detector = FlowDetector()
        md = _md(volume=1000, last_close=200.0, atm_iv=0.40, put_call_oi_ratio=1.0)
        events = detector.detect_from_market_data("SPY", md, timestamp=NOW)
        sweep_events = [e for e in events if e.flow_type == "sweep"]
        assert len(sweep_events) == 1
        assert sweep_events[0].direction == "neutral"

    def test_zero_price_no_sweep(self):
        """No sweep with zero price."""
        detector = FlowDetector()
        md = _md(volume=1000, last_close=0.0)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        sweep_events = [e for e in events if e.flow_type == "sweep"]
        assert len(sweep_events) == 0


# ================================================================
# 4. Dark pool detection
# ================================================================


class TestDarkPool:
    def test_detect_high_oi_low_volume(self):
        """Dark pool detected with high OI and low visible volume."""
        history = FlowHistory()
        # Prime history so baseline exists with flow_count > 3
        for i in range(5):
            history.update("AAPL", premium=50000.0, volume=200, direction="bullish")
        detector = FlowDetector(history=history)
        # total_oi = 8000+3000=11000 >= 1000; volume=50 low relative to OI
        md = _md(volume=50, last_close=170.0, call_oi=8000, put_oi=3000)
        events = detector.detect_from_market_data("AAPL", md, timestamp=NOW)
        dark_events = [e for e in events if e.flow_type == "dark_pool"]
        assert len(dark_events) == 1
        assert dark_events[0].ticker == "AAPL"

    def test_no_detection_low_oi(self):
        """No dark pool when total_oi < 1000."""
        detector = FlowDetector()
        md = _md(volume=50, call_oi=200, put_oi=100, last_close=170.0)
        events = detector.detect_from_market_data("AAPL", md, timestamp=NOW)
        dark_events = [e for e in events if e.flow_type == "dark_pool"]
        assert len(dark_events) == 0

    def test_normal_ratio_filtered_out(self):
        """Dark pool NOT detected when vol/OI ratio > dark_pool_volume_ratio."""
        history = FlowHistory()
        for i in range(5):
            history.update("AAPL", premium=50000.0, volume=2000, direction="bullish")
        detector = FlowDetector(history=history)
        # volume=5000, total_oi=10000 => ratio=0.5 > 0.30 default threshold
        md = _md(volume=5000, last_close=170.0, call_oi=5000, put_oi=5000)
        events = detector.detect_from_market_data("AAPL", md, timestamp=NOW)
        dark_events = [e for e in events if e.flow_type == "dark_pool"]
        assert len(dark_events) == 0

    def test_no_baseline_still_detects(self):
        """Dark pool can still detect without baseline (no vol/OI filter applied)."""
        detector = FlowDetector()
        # No history => baseline check skipped, falls through to OI >= 1000 check
        md = _md(volume=10, last_close=170.0, call_oi=6000, put_oi=4000)
        events = detector.detect_from_market_data("XYZ", md, timestamp=NOW)
        dark_events = [e for e in events if e.flow_type == "dark_pool"]
        # Whether it's detected depends on score vs composite_min_score
        # oi_score = min(10000/10000*20, 30) = 20; stealth = 15 (10 < 10000*0.1)
        # score = 20 + 20 + 15 = 55 > 25 => detected
        assert len(dark_events) == 1


# ================================================================
# 5. Accumulation detection
# ================================================================


class TestAccumulation:
    def _prime_bullish_history(self, history, ticker="TSLA", count=5):
        """Prime history with enough bullish events for accumulation detection.

        Uses small premium values so that the call_oi passed to
        get_premium_percentile will rank at the 70th+ percentile.
        """
        for i in range(count):
            history.update(
                ticker,
                premium=1000.0 + i * 100,
                volume=500,
                oi_change=1000,
                direction="bullish",
                timestamp=NOW - (count - i) * 3600,
            )

    def test_detect_with_bullish_history(self):
        """Accumulation detected when history has >= min_events and bullish_ratio >= 0.65."""
        history = FlowHistory()
        self._prime_bullish_history(history, "TSLA", count=5)
        detector = FlowDetector(history=history)
        # call_oi=6000 needs to rank >= 70th percentile vs premium_observations
        # primed observations are [1000, 1100, 1200, 1300, 1400] so 6000 is at 100th pct
        md = _md(volume=800, last_close=200.0, call_oi=6000, put_oi=2000, atm_iv=0.40)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        acc_events = [e for e in events if e.flow_type == "accumulation"]
        assert len(acc_events) == 1
        assert acc_events[0].direction == "bullish"

    def test_not_detected_without_history(self):
        """Accumulation NOT detected when no baseline exists."""
        detector = FlowDetector()
        md = _md(volume=800, last_close=200.0, call_oi=6000, put_oi=2000)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        acc_events = [e for e in events if e.flow_type == "accumulation"]
        assert len(acc_events) == 0

    def test_not_detected_insufficient_events(self):
        """Accumulation NOT detected when history has fewer than min_events."""
        history = FlowHistory()
        # Only 2 events, default min is 3
        self._prime_bullish_history(history, "TSLA", count=2)
        detector = FlowDetector(history=history)
        md = _md(volume=800, last_close=200.0, call_oi=6000, put_oi=2000)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        acc_events = [e for e in events if e.flow_type == "accumulation"]
        assert len(acc_events) == 0

    def test_not_detected_mixed_direction(self):
        """Accumulation NOT detected when bullish_ratio < 0.65 (mixed flow)."""
        history = FlowHistory()
        # 3 bullish + 3 bearish => ratio 0.5
        for i in range(3):
            history.update("TSLA", premium=50000.0, direction="bullish")
        for i in range(3):
            history.update("TSLA", premium=50000.0, direction="bearish")
        detector = FlowDetector(history=history)
        md = _md(volume=800, last_close=200.0, call_oi=6000, put_oi=2000)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        acc_events = [e for e in events if e.flow_type == "accumulation"]
        assert len(acc_events) == 0

    def test_zero_call_oi_no_detection(self):
        """Accumulation NOT detected when call_oi is zero."""
        history = FlowHistory()
        self._prime_bullish_history(history, "TSLA", count=5)
        detector = FlowDetector(history=history)
        md = _md(volume=800, last_close=200.0, call_oi=0, put_oi=2000)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        acc_events = [e for e in events if e.flow_type == "accumulation"]
        assert len(acc_events) == 0


# ================================================================
# 6. Distribution detection
# ================================================================


class TestDistribution:
    def _prime_bearish_history(self, history, ticker="TSLA", count=5):
        """Prime history with enough bearish events for distribution detection."""
        for i in range(count):
            history.update(
                ticker,
                premium=100_000.0 + i * 10_000,
                volume=500,
                oi_change=1000,
                direction="bearish",
                timestamp=NOW - (count - i) * 3600,
            )

    def test_detect_with_bearish_history(self):
        """Distribution detected when history is consistently bearish."""
        history = FlowHistory()
        self._prime_bearish_history(history, "TSLA", count=5)
        detector = FlowDetector(history=history)
        md = _md(volume=800, last_close=200.0, call_oi=2000, put_oi=6000, atm_iv=0.40)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        dist_events = [e for e in events if e.flow_type == "distribution"]
        assert len(dist_events) == 1
        assert dist_events[0].direction == "bearish"

    def test_not_detected_without_history(self):
        """Distribution NOT detected when no baseline exists."""
        detector = FlowDetector()
        md = _md(volume=800, last_close=200.0, call_oi=2000, put_oi=6000)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        dist_events = [e for e in events if e.flow_type == "distribution"]
        assert len(dist_events) == 0

    def test_not_detected_bullish_history(self):
        """Distribution NOT detected when history is bullish (bearish_ratio < 0.65)."""
        history = FlowHistory()
        for i in range(5):
            history.update("TSLA", premium=50000.0, direction="bullish")
        detector = FlowDetector(history=history)
        md = _md(volume=800, last_close=200.0, call_oi=2000, put_oi=6000)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        dist_events = [e for e in events if e.flow_type == "distribution"]
        assert len(dist_events) == 0

    def test_zero_put_oi_no_detection(self):
        """Distribution NOT detected when put_oi is zero."""
        history = FlowHistory()
        self._prime_bearish_history(history, "TSLA", count=5)
        detector = FlowDetector(history=history)
        md = _md(volume=800, last_close=200.0, call_oi=5000, put_oi=0)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        dist_events = [e for e in events if e.flow_type == "distribution"]
        assert len(dist_events) == 0


# ================================================================
# 7. scan_batch
# ================================================================


class TestScanBatch:
    def test_multiple_signals(self):
        """Batch scan processes multiple signals and returns combined events."""
        detector = FlowDetector()
        signals = [
            {
                "ticker": "TSLA",
                "market_data": _md(volume=2000, last_close=200.0),
                "id": "sig1",
                "created_at": NOW,
            },
            {
                "ticker": "AAPL",
                "market_data": _md(volume=1500, last_close=170.0),
                "id": "sig2",
                "created_at": NOW,
            },
        ]
        events = detector.scan_batch(signals)
        tickers = {e.ticker for e in events}
        assert "TSLA" in tickers or "AAPL" in tickers
        assert len(events) >= 1

    def test_json_string_market_data(self):
        """scan_batch handles market_data as JSON string."""
        detector = FlowDetector()
        md_json = json.dumps(_md(volume=3000, last_close=300.0))
        signals = [
            {
                "ticker": "NVDA",
                "market_data": md_json,
                "id": "sig3",
                "created_at": NOW,
            },
        ]
        events = detector.scan_batch(signals)
        assert all(e.ticker == "NVDA" for e in events)

    def test_empty_market_data(self):
        """scan_batch skips signals with empty market data."""
        detector = FlowDetector()
        signals = [
            {"ticker": "TSLA", "market_data": {}, "id": "sig4", "created_at": NOW},
        ]
        events = detector.scan_batch(signals)
        assert len(events) == 0

    def test_missing_ticker(self):
        """scan_batch skips signals without a ticker."""
        detector = FlowDetector()
        signals = [
            {"market_data": _md(volume=2000), "id": "sig5", "created_at": NOW},
            {"ticker": "", "market_data": _md(volume=2000), "id": "sig6"},
        ]
        events = detector.scan_batch(signals)
        assert len(events) == 0

    def test_empty_signals_list(self):
        """scan_batch with empty list returns empty."""
        detector = FlowDetector()
        assert detector.scan_batch([]) == []

    def test_nested_market_data_by_ticker(self):
        """scan_batch works when market_data is nested by ticker."""
        detector = FlowDetector()
        md = {"TSLA": _md(volume=3000, last_close=250.0)}
        signals = [
            {"ticker": "TSLA", "market_data": md, "id": "sig7", "created_at": NOW}
        ]
        events = detector.scan_batch(signals)
        assert all(e.ticker == "TSLA" for e in events)

    def test_bad_market_data_json_skipped(self):
        """scan_batch handles invalid JSON market data gracefully."""
        detector = FlowDetector()
        signals = [
            {
                "ticker": "TSLA",
                "market_data": "{not valid json",
                "id": "sig8",
                "created_at": NOW,
            },
        ]
        events = detector.scan_batch(signals)
        assert len(events) == 0


# ================================================================
# 8. compute_score
# ================================================================


class TestComputeScore:
    def test_empty_events_score_zero(self):
        """compute_score with no events returns score=0."""
        detector = FlowDetector()
        score = detector.compute_score([], "TSLA", timestamp=NOW)
        assert isinstance(score, FlowScore)
        assert score.score == 0.0
        assert score.event_count == 0
        assert score.bullish_flow == 0.0
        assert score.bearish_flow == 0.0
        assert score.net_premium == 0.0

    def test_single_event(self):
        """compute_score with one event uses max=avg=that event."""
        event = FlowEvent(
            id="e1",
            ticker="TSLA",
            flow_type="block_trade",
            direction="bullish",
            premium=200_000.0,
            volume=1000,
            oi_change=5000,
            score=50.0,
            timestamp=NOW,
        )
        detector = FlowDetector()
        score = detector.compute_score([event], "TSLA", timestamp=NOW)
        # composite = 0.6*50 + 0.3*50 + min(1*2, 20) = 30 + 15 + 2 = 47
        assert score.score == 47.0
        assert score.event_count == 1
        assert score.bullish_flow == 200_000.0
        assert score.bearish_flow == 0.0
        assert score.net_premium == 200_000.0

    def test_multiple_events(self):
        """compute_score aggregates across multiple events."""
        e1 = FlowEvent(
            id="e1",
            ticker="TSLA",
            flow_type="block_trade",
            direction="bullish",
            premium=300_000.0,
            volume=1500,
            oi_change=5000,
            score=70.0,
            timestamp=NOW,
        )
        e2 = FlowEvent(
            id="e2",
            ticker="TSLA",
            flow_type="sweep",
            direction="bearish",
            premium=100_000.0,
            volume=800,
            oi_change=0,
            score=40.0,
            timestamp=NOW,
        )
        detector = FlowDetector()
        score = detector.compute_score([e1, e2], "TSLA", timestamp=NOW)
        # max=70, avg=55, count_bonus=min(2*2,20)=4
        # composite = 0.6*70 + 0.3*55 + 4 = 42 + 16.5 + 4 = 62.5
        assert score.score == 62.5
        assert score.event_count == 2
        assert score.bullish_flow == 300_000.0
        assert score.bearish_flow == 100_000.0
        assert score.net_premium == 200_000.0

    def test_score_capped_at_100(self):
        """compute_score caps composite at 100."""
        # Create events with very high scores
        events = [
            FlowEvent(
                id=f"e{i}",
                ticker="X",
                flow_type="block_trade",
                direction="bullish",
                premium=1_000_000.0,
                volume=5000,
                oi_change=10000,
                score=100.0,
                timestamp=NOW,
            )
            for i in range(15)
        ]
        detector = FlowDetector()
        score = detector.compute_score(events, "X", timestamp=NOW)
        assert score.score <= 100.0

    def test_count_bonus_capped_at_20(self):
        """Count bonus is capped at 20 (10 events * 2)."""
        events = [
            FlowEvent(
                id=f"e{i}",
                ticker="X",
                flow_type="sweep",
                direction="neutral",
                premium=50_000.0,
                volume=500,
                oi_change=0,
                score=30.0,
                timestamp=NOW,
            )
            for i in range(20)
        ]
        detector = FlowDetector()
        score = detector.compute_score(events, "X", timestamp=NOW)
        # count_bonus = min(20*2, 20) = 20
        # composite = 0.6*30 + 0.3*30 + 20 = 18 + 9 + 20 = 47
        assert score.score == 47.0


# ================================================================
# 9. Filtering and capping
# ================================================================


class TestFiltering:
    def test_below_composite_min_score_filtered(self):
        """Events with score < composite_min_score are filtered out."""
        # Use a high min_score to filter out everything
        config = FlowDetectorConfig(composite_min_score=90)
        detector = FlowDetector(config=config)
        # This will generate events but they should be low-scored
        md = _md(volume=600, last_close=50.0, atm_iv=0.20)
        events = detector.detect_from_market_data("LOW", md, timestamp=NOW)
        # All events below 90 should be filtered out
        for e in events:
            assert e.score >= 90

    def test_max_events_per_ticker_cap(self):
        """No more than max_events_per_ticker returned."""
        config = FlowDetectorConfig(
            max_events_per_ticker=2,
            composite_min_score=0,  # allow all
        )
        history = FlowHistory()
        # Prime lots of bullish history for accumulation
        for i in range(10):
            history.update("BIG", premium=100_000.0, volume=500, direction="bullish")
        detector = FlowDetector(history=history, config=config)
        # This market data should trigger multiple detection types
        md = _md(volume=3000, last_close=300.0, atm_iv=0.5, call_oi=8000, put_oi=2000)
        events = detector.detect_from_market_data("BIG", md, timestamp=NOW)
        assert len(events) <= 2

    def test_empty_ticker_returns_empty(self):
        """Empty ticker string returns no events."""
        detector = FlowDetector()
        events = detector.detect_from_market_data("", _md(), timestamp=NOW)
        assert events == []

    def test_empty_market_data_returns_empty(self):
        """Empty market data dict returns no events."""
        detector = FlowDetector()
        events = detector.detect_from_market_data("TSLA", {}, timestamp=NOW)
        assert events == []


# ================================================================
# 10. Configuration
# ================================================================


class TestConfig:
    def test_default_config(self):
        """Default config has expected values."""
        c = FlowDetectorConfig()
        assert c.block_premium_threshold == 100_000
        assert c.sweep_volume_threshold == 500
        assert c.sweep_premium_threshold == 50_000
        assert c.dark_pool_volume_ratio == 0.30
        assert c.accumulation_min_events == 3
        assert c.accumulation_window_s == 86400 * 3
        assert c.composite_min_score == 25.0
        assert c.max_events_per_ticker == 10
        assert c.volume_surge_multiplier == 3.0
        assert c.oi_surge_pct == 25.0

    def test_custom_config(self):
        """Custom config values override defaults."""
        c = FlowDetectorConfig(
            block_premium_threshold=500_000,
            sweep_volume_threshold=1000,
            composite_min_score=50.0,
        )
        assert c.block_premium_threshold == 500_000
        assert c.sweep_volume_threshold == 1000
        assert c.composite_min_score == 50.0
        # Others remain default
        assert c.dark_pool_volume_ratio == 0.30

    def test_detector_uses_config(self):
        """FlowDetector exposes config property."""
        config = FlowDetectorConfig(block_premium_threshold=999_999)
        detector = FlowDetector(config=config)
        assert detector.config.block_premium_threshold == 999_999

    def test_detector_uses_history(self):
        """FlowDetector exposes history property."""
        history = FlowHistory(max_tickers=100)
        detector = FlowDetector(history=history)
        assert detector.history is history
        assert detector.history.max_tickers == 100


# ================================================================
# 11. Edge cases
# ================================================================


class TestEdgeCases:
    def test_nan_values_in_market_data(self):
        """NaN values in market data are handled gracefully."""
        detector = FlowDetector()
        md = {
            "last_close": float("nan"),
            "atm_iv": float("nan"),
            "call_oi": 5000,
            "put_oi": 3000,
            "volume": 1000,
        }
        # Should not raise; NaN price => zero price => no events
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        # Zero price after NaN conversion means no block/sweep detection
        block_events = [e for e in events if e.flow_type == "block_trade"]
        sweep_events = [e for e in events if e.flow_type == "sweep"]
        assert len(block_events) == 0
        assert len(sweep_events) == 0

    def test_negative_volume_treated_as_zero(self):
        """Negative volume is coerced and blocks detection."""
        detector = FlowDetector()
        md = _md(volume=-100, last_close=150.0)
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) == 0

    def test_very_large_values_dont_crash(self):
        """Extremely large market values do not cause errors."""
        detector = FlowDetector()
        md = _md(volume=10_000_000, last_close=5000.0, atm_iv=2.0, call_oi=100_000_000)
        events = detector.detect_from_market_data("MEGA", md, timestamp=NOW)
        # Should produce events without crashing
        assert isinstance(events, list)
        for e in events:
            assert 0 <= e.score <= 100

    def test_option_volume_key_alternative(self):
        """Detector accepts 'option_volume' as alternative to 'volume'."""
        detector = FlowDetector()
        md = {
            "last_close": 200.0,
            "atm_iv": 0.35,
            "call_oi": 5000,
            "put_oi": 3000,
            "option_volume": 2000,
        }
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) >= 1
        assert block_events[0].volume == 2000

    def test_price_key_alternative(self):
        """Detector accepts 'price' as alternative to 'last_close'."""
        detector = FlowDetector()
        md = {
            "price": 200.0,
            "atm_iv": 0.35,
            "call_oi": 5000,
            "put_oi": 3000,
            "volume": 2000,
        }
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        assert len(block_events) >= 1

    def test_timestamp_defaults_to_now(self):
        """Events get approximately current timestamp when none provided."""
        detector = FlowDetector()
        md = _md(volume=2000, last_close=150.0)
        before = time.time()
        events = detector.detect_from_market_data("TSLA", md)
        after = time.time()
        for e in events:
            assert before <= e.timestamp <= after

    def test_history_updated_after_detection(self):
        """Detected events are recorded in FlowHistory."""
        history = FlowHistory()
        detector = FlowDetector(history=history)
        md = _md(volume=2000, last_close=200.0)
        events = detector.detect_from_market_data("NEW", md, timestamp=NOW)
        if events:
            baseline = history.get_baseline("NEW")
            assert baseline is not None
            assert baseline.flow_count >= 1

    def test_direction_from_change_1d(self):
        """Direction inferred from change_1d when OI ratio is balanced."""
        detector = FlowDetector()
        # Balanced OI but strong positive change_1d => bullish
        md = _md(
            volume=2000,
            last_close=150.0,
            call_oi=5000,
            put_oi=5000,
            change_1d=3.5,
        )
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        if block_events:
            assert block_events[0].direction == "bullish"

    def test_direction_bearish_from_negative_change(self):
        """Direction inferred as bearish from strong negative change_1d."""
        detector = FlowDetector()
        md = _md(
            volume=2000,
            last_close=150.0,
            call_oi=5000,
            put_oi=5000,
            change_1d=-3.5,
        )
        events = detector.detect_from_market_data("TSLA", md, timestamp=NOW)
        block_events = [e for e in events if e.flow_type == "block_trade"]
        if block_events:
            assert block_events[0].direction == "bearish"
