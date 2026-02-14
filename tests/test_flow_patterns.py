"""Tests for FlowPatternRecognizer — institutional flow pattern detection.

Covers all 5 pattern types (repeat_buyer, accumulation_sequence, hedging,
rolling, cross_ticker), confidence filtering, timeframe classification,
edge cases, and custom config.
"""

import time
import uuid

import pytest

from rot.flow.patterns import (
    FlowPatternConfig,
    FlowPatternRecognizer,
    _SECTOR_GROUPS,
    _TICKER_SECTOR,
)
from rot.flow.types import FlowEvent, FlowPattern


# ── Test helper ────────────────────────────────────────────


def _make_event(
    ticker: str = "TSLA",
    flow_type: str = "block_trade",
    direction: str = "bullish",
    premium: float = 150000.0,
    volume: int = 500,
    oi_change: int = 100,
    score: float = 60.0,
    timestamp: float | None = None,
    **kwargs,
) -> FlowEvent:
    import time as _time

    return FlowEvent(
        id=str(uuid.uuid4()),
        ticker=ticker,
        flow_type=flow_type,
        direction=direction,
        premium=premium,
        volume=volume,
        oi_change=oi_change,
        score=score,
        timestamp=timestamp or _time.time(),
        **kwargs,
    )


# ── Repeat Buyer Tests ────────────────────────────────────


class TestRepeatBuyer:
    """Tests for repeat_buyer pattern detection."""

    def test_three_bullish_events_detected(self):
        """3 bullish events for same ticker within window -> detected."""
        now = time.time()
        events = [
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - 3600),
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - 1800),
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - 600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        repeat = [p for p in patterns if p.pattern_type == "repeat_buyer"]
        assert len(repeat) >= 1
        pat = repeat[0]
        assert pat.tickers == ["AAPL"]
        assert pat.details["direction"] == "bullish"
        assert pat.event_count == 3
        assert pat.confidence >= 0.4

    def test_two_events_not_detected(self):
        """Only 2 events (below default min_events=3) -> no repeat_buyer."""
        now = time.time()
        events = [
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - 3600),
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - 1800),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        repeat = [p for p in patterns if p.pattern_type == "repeat_buyer"]
        assert len(repeat) == 0

    def test_mixed_direction_not_enough(self):
        """3 events but mixed direction (2 bullish + 1 bearish) -> not detected."""
        now = time.time()
        events = [
            _make_event(ticker="TSLA", direction="bullish", timestamp=now - 3600),
            _make_event(ticker="TSLA", direction="bullish", timestamp=now - 1800),
            _make_event(ticker="TSLA", direction="bearish", timestamp=now - 600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        repeat = [p for p in patterns if p.pattern_type == "repeat_buyer"]
        assert len(repeat) == 0

    def test_outside_time_window_not_detected(self):
        """3 bullish events but outside 3-day window -> not detected."""
        now = time.time()
        window = 86400 * 3  # default 3 days
        events = [
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - window - 7200),
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - window - 3600),
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - window - 1800),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        repeat = [p for p in patterns if p.pattern_type == "repeat_buyer"]
        assert len(repeat) == 0

    def test_bearish_repeat_buyer(self):
        """3 bearish events -> bearish repeat_buyer detected."""
        now = time.time()
        events = [
            _make_event(ticker="MSFT", direction="bearish", timestamp=now - 7200),
            _make_event(ticker="MSFT", direction="bearish", timestamp=now - 3600),
            _make_event(ticker="MSFT", direction="bearish", timestamp=now - 600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        repeat = [p for p in patterns if p.pattern_type == "repeat_buyer"]
        assert len(repeat) == 1
        assert repeat[0].details["direction"] == "bearish"

    def test_confidence_increases_with_more_events(self):
        """More events should produce higher confidence."""
        now = time.time()
        events_3 = [
            _make_event(ticker="TSLA", direction="bullish", timestamp=now - i * 1000)
            for i in range(3)
        ]
        events_6 = [
            _make_event(ticker="TSLA", direction="bullish", timestamp=now - i * 1000)
            for i in range(6)
        ]
        rec = FlowPatternRecognizer()
        p3 = [p for p in rec.recognize(events_3, timestamp=now) if p.pattern_type == "repeat_buyer"]
        p6 = [p for p in rec.recognize(events_6, timestamp=now) if p.pattern_type == "repeat_buyer"]
        assert len(p3) == 1 and len(p6) == 1
        assert p6[0].confidence > p3[0].confidence

    def test_total_premium_in_details(self):
        """Total premium should be sum of event premiums."""
        now = time.time()
        events = [
            _make_event(ticker="AAPL", direction="bullish", premium=100000.0, timestamp=now - 3600),
            _make_event(ticker="AAPL", direction="bullish", premium=200000.0, timestamp=now - 1800),
            _make_event(ticker="AAPL", direction="bullish", premium=50000.0, timestamp=now - 600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        repeat = [p for p in patterns if p.pattern_type == "repeat_buyer"]
        assert len(repeat) == 1
        assert repeat[0].details["total_premium"] == 350000.0


# ── Accumulation Sequence Tests ───────────────────────────


class TestAccumulationSequence:
    """Tests for accumulation_sequence pattern detection."""

    def test_four_increasing_premiums_over_12h_detected(self):
        """4+ events, same direction, increasing premiums, 12h+ span -> detected."""
        now = time.time()
        events = [
            _make_event(ticker="NVDA", direction="bullish", premium=50000, timestamp=now - 86400 * 2),
            _make_event(ticker="NVDA", direction="bullish", premium=80000, timestamp=now - 86400),
            _make_event(ticker="NVDA", direction="bullish", premium=120000, timestamp=now - 43200),
            _make_event(ticker="NVDA", direction="bullish", premium=200000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        accum = [p for p in patterns if p.pattern_type == "accumulation_sequence"]
        assert len(accum) >= 1
        pat = accum[0]
        assert pat.details["direction"] == "bullish"
        assert pat.details["increase_ratio"] >= 0.5

    def test_not_enough_events(self):
        """3 events (below default min=4) -> no accumulation."""
        now = time.time()
        events = [
            _make_event(ticker="NVDA", direction="bullish", premium=50000, timestamp=now - 86400),
            _make_event(ticker="NVDA", direction="bullish", premium=80000, timestamp=now - 43200),
            _make_event(ticker="NVDA", direction="bullish", premium=120000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        accum = [p for p in patterns if p.pattern_type == "accumulation_sequence"]
        assert len(accum) == 0

    def test_premiums_not_increasing(self):
        """4 events with decreasing premiums -> not detected."""
        now = time.time()
        events = [
            _make_event(ticker="NVDA", direction="bullish", premium=200000, timestamp=now - 86400 * 2),
            _make_event(ticker="NVDA", direction="bullish", premium=100000, timestamp=now - 86400),
            _make_event(ticker="NVDA", direction="bullish", premium=40000, timestamp=now - 43200),
            _make_event(ticker="NVDA", direction="bullish", premium=10000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        accum = [p for p in patterns if p.pattern_type == "accumulation_sequence"]
        assert len(accum) == 0

    def test_too_short_time_span(self):
        """4 events but all within < 12 hours -> not detected (not gradual)."""
        now = time.time()
        events = [
            _make_event(ticker="NVDA", direction="bullish", premium=50000, timestamp=now - 3600 * 4),
            _make_event(ticker="NVDA", direction="bullish", premium=80000, timestamp=now - 3600 * 3),
            _make_event(ticker="NVDA", direction="bullish", premium=120000, timestamp=now - 3600 * 2),
            _make_event(ticker="NVDA", direction="bullish", premium=200000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        accum = [p for p in patterns if p.pattern_type == "accumulation_sequence"]
        assert len(accum) == 0

    def test_bearish_accumulation(self):
        """4 bearish events with increasing premiums -> detected as bearish."""
        now = time.time()
        events = [
            _make_event(ticker="AMD", direction="bearish", premium=30000, timestamp=now - 86400 * 3),
            _make_event(ticker="AMD", direction="bearish", premium=60000, timestamp=now - 86400 * 2),
            _make_event(ticker="AMD", direction="bearish", premium=90000, timestamp=now - 86400),
            _make_event(ticker="AMD", direction="bearish", premium=150000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        accum = [p for p in patterns if p.pattern_type == "accumulation_sequence"]
        assert len(accum) >= 1
        assert accum[0].details["direction"] == "bearish"

    def test_time_span_hours_in_details(self):
        """Time span should appear in details."""
        now = time.time()
        events = [
            _make_event(ticker="NVDA", direction="bullish", premium=50000, timestamp=now - 86400 * 2),
            _make_event(ticker="NVDA", direction="bullish", premium=80000, timestamp=now - 86400),
            _make_event(ticker="NVDA", direction="bullish", premium=120000, timestamp=now - 43200),
            _make_event(ticker="NVDA", direction="bullish", premium=200000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        accum = [p for p in patterns if p.pattern_type == "accumulation_sequence"]
        assert len(accum) >= 1
        assert accum[0].details["time_span_hours"] > 12.0


# ── Hedging Tests ─────────────────────────────────────────


class TestHedging:
    """Tests for hedging pattern detection."""

    def test_bullish_and_bearish_in_window_detected(self):
        """Bullish + bearish events within 8h window, both >= $10k -> detected."""
        now = time.time()
        events = [
            _make_event(ticker="SPY", direction="bullish", premium=50000, timestamp=now - 7200),
            _make_event(ticker="SPY", direction="bearish", premium=40000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        hedge = [p for p in patterns if p.pattern_type == "hedging"]
        assert len(hedge) == 1
        pat = hedge[0]
        assert pat.details["bull_premium"] == 50000.0
        assert pat.details["bear_premium"] == 40000.0
        assert pat.details["balance_ratio"] >= 0.2

    def test_one_sided_not_detected(self):
        """Only bullish events, no bearish -> no hedging."""
        now = time.time()
        events = [
            _make_event(ticker="SPY", direction="bullish", premium=50000, timestamp=now - 7200),
            _make_event(ticker="SPY", direction="bullish", premium=40000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        hedge = [p for p in patterns if p.pattern_type == "hedging"]
        assert len(hedge) == 0

    def test_small_premium_not_detected(self):
        """Both sides present but smaller side < $10k -> not detected."""
        now = time.time()
        events = [
            _make_event(ticker="SPY", direction="bullish", premium=50000, timestamp=now - 7200),
            _make_event(ticker="SPY", direction="bearish", premium=5000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        hedge = [p for p in patterns if p.pattern_type == "hedging"]
        assert len(hedge) == 0

    def test_imbalanced_ratio_not_detected(self):
        """Both sides >= $10k but ratio < 0.2 -> not detected."""
        now = time.time()
        events = [
            _make_event(ticker="SPY", direction="bullish", premium=500000, timestamp=now - 7200),
            _make_event(ticker="SPY", direction="bearish", premium=10001, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        hedge = [p for p in patterns if p.pattern_type == "hedging"]
        # ratio = 10001 / 500000 ~ 0.02 < 0.2
        assert len(hedge) == 0

    def test_hedging_outside_window_not_detected(self):
        """Events outside 8h hedging window -> not detected."""
        now = time.time()
        window = 3600 * 8
        events = [
            _make_event(ticker="SPY", direction="bullish", premium=50000, timestamp=now - window - 3600),
            _make_event(ticker="SPY", direction="bearish", premium=40000, timestamp=now - window - 1800),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        hedge = [p for p in patterns if p.pattern_type == "hedging"]
        assert len(hedge) == 0

    def test_hedging_balance_ratio_in_details(self):
        """Balance ratio details should be calculated correctly."""
        now = time.time()
        events = [
            _make_event(ticker="QQQ", direction="bullish", premium=100000, timestamp=now - 3600),
            _make_event(ticker="QQQ", direction="bearish", premium=100000, timestamp=now - 1800),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        hedge = [p for p in patterns if p.pattern_type == "hedging"]
        assert len(hedge) == 1
        # Perfectly balanced -> ratio = 1.0
        assert hedge[0].details["balance_ratio"] == 1.0


# ── Rolling Tests ─────────────────────────────────────────


class TestRolling:
    """Tests for rolling pattern detection."""

    def test_distribution_then_accumulation_detected(self):
        """Distribution events followed by accumulation events -> detected."""
        now = time.time()
        events = [
            _make_event(ticker="TSLA", flow_type="distribution", direction="bullish", premium=100000, timestamp=now - 86400 * 2),
            _make_event(ticker="TSLA", flow_type="distribution", direction="bullish", premium=80000, timestamp=now - 86400),
            _make_event(ticker="TSLA", flow_type="accumulation", direction="bullish", premium=90000, timestamp=now - 3600),
            _make_event(ticker="TSLA", flow_type="accumulation", direction="bullish", premium=110000, timestamp=now - 1800),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        roll = [p for p in patterns if p.pattern_type == "rolling"]
        assert len(roll) == 1
        assert roll[0].details["size_ratio"] >= 0.3

    def test_wrong_order_not_detected(self):
        """Accumulation before distribution -> not detected (wrong order)."""
        now = time.time()
        events = [
            _make_event(ticker="TSLA", flow_type="accumulation", direction="bullish", premium=100000, timestamp=now - 86400 * 3),
            _make_event(ticker="TSLA", flow_type="accumulation", direction="bullish", premium=80000, timestamp=now - 86400 * 2),
            _make_event(ticker="TSLA", flow_type="distribution", direction="bullish", premium=90000, timestamp=now - 3600),
            _make_event(ticker="TSLA", flow_type="distribution", direction="bullish", premium=110000, timestamp=now - 1800),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        roll = [p for p in patterns if p.pattern_type == "rolling"]
        assert len(roll) == 0

    def test_mismatched_magnitude_not_detected(self):
        """Distribution and accumulation with very different magnitudes (ratio < 0.3) -> not detected."""
        now = time.time()
        events = [
            _make_event(ticker="TSLA", flow_type="distribution", direction="bullish", premium=10000, timestamp=now - 86400 * 2),
            _make_event(ticker="TSLA", flow_type="accumulation", direction="bullish", premium=500000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        roll = [p for p in patterns if p.pattern_type == "rolling"]
        assert len(roll) == 0

    def test_no_distribution_events(self):
        """Only accumulation events, no distribution -> not detected."""
        now = time.time()
        events = [
            _make_event(ticker="TSLA", flow_type="accumulation", direction="bullish", premium=100000, timestamp=now - 86400),
            _make_event(ticker="TSLA", flow_type="accumulation", direction="bullish", premium=120000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        roll = [p for p in patterns if p.pattern_type == "rolling"]
        assert len(roll) == 0

    def test_time_gap_hours_in_details(self):
        """Time gap between distribution and accumulation phases in details."""
        now = time.time()
        events = [
            _make_event(ticker="TSLA", flow_type="distribution", direction="bullish", premium=100000, timestamp=now - 86400 * 3),
            _make_event(ticker="TSLA", flow_type="accumulation", direction="bullish", premium=100000, timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        roll = [p for p in patterns if p.pattern_type == "rolling"]
        assert len(roll) == 1
        assert roll[0].details["time_gap_hours"] > 0


# ── Cross-Ticker Tests ────────────────────────────────────


class TestCrossTicker:
    """Tests for cross_ticker pattern detection."""

    def test_three_sector_tickers_aligned_detected(self):
        """3+ tickers in same sector, aligned direction -> detected."""
        now = time.time()
        # Use mega_tech tickers
        events = [
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - 3600),
            _make_event(ticker="MSFT", direction="bullish", timestamp=now - 1800),
            _make_event(ticker="GOOGL", direction="bullish", timestamp=now - 600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        cross = [p for p in patterns if p.pattern_type == "cross_ticker"]
        assert len(cross) >= 1
        pat = cross[0]
        assert pat.details["sector"] == "mega_tech"
        assert pat.details["direction"] == "bullish"
        assert pat.details["unique_tickers"] >= 3

    def test_fewer_than_three_tickers_not_detected(self):
        """Only 2 sector tickers -> not detected."""
        now = time.time()
        events = [
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - 3600),
            _make_event(ticker="MSFT", direction="bullish", timestamp=now - 1800),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        cross = [p for p in patterns if p.pattern_type == "cross_ticker"]
        assert len(cross) == 0

    def test_not_aligned_direction_not_detected(self):
        """3 sector tickers but mixed directions (dominant_ratio < 0.65) -> not detected."""
        now = time.time()
        events = [
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - 3600),
            _make_event(ticker="MSFT", direction="bearish", timestamp=now - 1800),
            _make_event(ticker="GOOGL", direction="bearish", timestamp=now - 600),
            _make_event(ticker="AMZN", direction="bullish", timestamp=now - 300),
            _make_event(ticker="META", direction="bearish", timestamp=now - 100),
            # 2 bullish, 3 bearish in mega_tech -> ratio = 3/5 = 0.6 < 0.65
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        cross = [p for p in patterns if p.pattern_type == "cross_ticker"]
        assert len(cross) == 0

    def test_non_sector_tickers_not_detected(self):
        """Tickers not in any sector group -> not detected."""
        now = time.time()
        events = [
            _make_event(ticker="ZZXY", direction="bullish", timestamp=now - 3600),
            _make_event(ticker="ABCD", direction="bullish", timestamp=now - 1800),
            _make_event(ticker="WXYZ", direction="bullish", timestamp=now - 600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        cross = [p for p in patterns if p.pattern_type == "cross_ticker"]
        assert len(cross) == 0

    def test_outside_cross_ticker_window_not_detected(self):
        """Events outside 12h window -> not detected."""
        now = time.time()
        window = 3600 * 12
        events = [
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - window - 7200),
            _make_event(ticker="MSFT", direction="bullish", timestamp=now - window - 3600),
            _make_event(ticker="GOOGL", direction="bullish", timestamp=now - window - 1800),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        cross = [p for p in patterns if p.pattern_type == "cross_ticker"]
        assert len(cross) == 0

    def test_bearish_cross_ticker(self):
        """3 sector tickers bearish aligned -> detected as bearish."""
        now = time.time()
        events = [
            _make_event(ticker="JPM", direction="bearish", timestamp=now - 3600),
            _make_event(ticker="BAC", direction="bearish", timestamp=now - 1800),
            _make_event(ticker="GS", direction="bearish", timestamp=now - 600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        cross = [p for p in patterns if p.pattern_type == "cross_ticker"]
        assert len(cross) >= 1
        assert cross[0].details["direction"] == "bearish"
        assert cross[0].details["sector"] == "financials"


# ── Edge Cases & General Tests ────────────────────────────


class TestEdgeCases:
    """Edge cases, empty input, config, and general behavior."""

    def test_empty_events_returns_empty(self):
        """Empty event list -> empty result."""
        rec = FlowPatternRecognizer()
        assert rec.recognize([]) == []

    def test_single_event_no_patterns(self):
        """A single event for a ticker cannot form any pattern (need >= 2)."""
        now = time.time()
        events = [_make_event(ticker="AAPL", timestamp=now - 600)]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        # Cross-ticker also needs 3+ tickers, so nothing detected
        assert len(patterns) == 0

    def test_min_confidence_filter(self):
        """Patterns below min_confidence are filtered out."""
        now = time.time()
        # Build a repeat_buyer that would just barely pass default confidence
        events = [
            _make_event(ticker="TSLA", direction="bullish", timestamp=now - 3600),
            _make_event(ticker="TSLA", direction="bullish", timestamp=now - 1800),
            _make_event(ticker="TSLA", direction="bullish", timestamp=now - 600),
        ]
        # With high min_confidence, pattern should be filtered
        config = FlowPatternConfig(min_confidence=0.95)
        rec = FlowPatternRecognizer(config=config)
        patterns = rec.recognize(events, timestamp=now)
        repeat = [p for p in patterns if p.pattern_type == "repeat_buyer"]
        assert len(repeat) == 0

    def test_custom_config_lower_thresholds(self):
        """Lower thresholds via custom config -> detect patterns earlier."""
        now = time.time()
        # Only 2 bullish events -- normally below min_events=3
        events = [
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - 3600),
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - 1800),
        ]
        config = FlowPatternConfig(repeat_buyer_min_events=2, min_confidence=0.1)
        rec = FlowPatternRecognizer(config=config)
        patterns = rec.recognize(events, timestamp=now)
        repeat = [p for p in patterns if p.pattern_type == "repeat_buyer"]
        assert len(repeat) >= 1

    def test_default_config_used_when_none(self):
        """FlowPatternRecognizer() uses FlowPatternConfig defaults."""
        rec = FlowPatternRecognizer()
        assert rec.config.min_confidence == 0.4
        assert rec.config.repeat_buyer_min_events == 3
        assert rec.config.accumulation_min_events == 4

    def test_timestamp_defaults_to_now(self):
        """If no timestamp provided, uses current time."""
        events = [
            _make_event(ticker="AAPL", direction="bullish", timestamp=time.time() - 100),
            _make_event(ticker="AAPL", direction="bullish", timestamp=time.time() - 50),
            _make_event(ticker="AAPL", direction="bullish", timestamp=time.time() - 10),
        ]
        rec = FlowPatternRecognizer()
        # Should work without explicit timestamp
        patterns = rec.recognize(events)
        repeat = [p for p in patterns if p.pattern_type == "repeat_buyer"]
        assert len(repeat) >= 1

    def test_multiple_pattern_types_from_same_events(self):
        """Events can trigger multiple pattern types simultaneously."""
        now = time.time()
        events = [
            # Repeat buyer: 4 bullish TSLA events
            _make_event(ticker="TSLA", direction="bullish", premium=50000, flow_type="distribution", timestamp=now - 86400 * 3),
            _make_event(ticker="TSLA", direction="bullish", premium=80000, flow_type="distribution", timestamp=now - 86400 * 2),
            _make_event(ticker="TSLA", direction="bullish", premium=120000, flow_type="accumulation", timestamp=now - 86400),
            _make_event(ticker="TSLA", direction="bullish", premium=200000, flow_type="accumulation", timestamp=now - 3600),
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        types = {p.pattern_type for p in patterns}
        # Should detect at least repeat_buyer; may also detect accumulation_sequence and rolling
        assert "repeat_buyer" in types

    def test_confidence_capped_at_095(self):
        """Confidence should never exceed 0.95."""
        now = time.time()
        events = [
            _make_event(ticker="AAPL", direction="bullish", timestamp=now - i * 100)
            for i in range(20)
        ]
        rec = FlowPatternRecognizer()
        patterns = rec.recognize(events, timestamp=now)
        for pat in patterns:
            assert pat.confidence <= 0.95


# ── Timeframe Classification Tests ────────────────────────


class TestTimeframeClassification:
    """Tests for _classify_timeframe helper."""

    def test_under_4h_returns_4h(self):
        """Span < 4 hours -> '4h'."""
        now = time.time()
        events = [
            _make_event(timestamp=now - 3600),
            _make_event(timestamp=now - 1800),
            _make_event(timestamp=now - 600),
        ]
        rec = FlowPatternRecognizer()
        assert rec._classify_timeframe(events) == "4h"

    def test_under_1d_returns_1d(self):
        """Span >= 4h but < 1 day -> '1d'."""
        now = time.time()
        events = [
            _make_event(timestamp=now - 3600 * 10),
            _make_event(timestamp=now - 3600 * 2),
        ]
        rec = FlowPatternRecognizer()
        assert rec._classify_timeframe(events) == "1d"

    def test_under_1w_returns_1w(self):
        """Span >= 1 day but < 7 days -> '1w'."""
        now = time.time()
        events = [
            _make_event(timestamp=now - 86400 * 3),
            _make_event(timestamp=now - 86400),
        ]
        rec = FlowPatternRecognizer()
        assert rec._classify_timeframe(events) == "1w"

    def test_over_1w_returns_1m(self):
        """Span >= 7 days -> '1m'."""
        now = time.time()
        events = [
            _make_event(timestamp=now - 86400 * 10),
            _make_event(timestamp=now - 86400),
        ]
        rec = FlowPatternRecognizer()
        assert rec._classify_timeframe(events) == "1m"

    def test_empty_events_returns_1h(self):
        """Empty event list -> '1h' (fallback)."""
        rec = FlowPatternRecognizer()
        assert rec._classify_timeframe([]) == "1h"


# ── Sector Groups / Ticker Sector Tests ────────────────────


class TestSectorGroups:
    """Tests that the sector group mappings are correct."""

    def test_sector_groups_exist(self):
        """Sector groups dict should contain expected sectors."""
        assert "mega_tech" in _SECTOR_GROUPS
        assert "semis" in _SECTOR_GROUPS
        assert "financials" in _SECTOR_GROUPS
        assert "energy" in _SECTOR_GROUPS
        assert "healthcare" in _SECTOR_GROUPS
        assert "consumer" in _SECTOR_GROUPS
        assert "indices" in _SECTOR_GROUPS

    def test_ticker_sector_reverse_lookup(self):
        """_TICKER_SECTOR reverse mapping should work."""
        assert _TICKER_SECTOR.get("AAPL") == "mega_tech"
        assert _TICKER_SECTOR.get("JPM") == "financials"
        assert _TICKER_SECTOR.get("XOM") == "energy"
        assert _TICKER_SECTOR.get("SPY") == "indices"
        assert _TICKER_SECTOR.get("ZZFAKE") is None

    def test_nvda_in_multiple_sectors(self):
        """NVDA appears in both mega_tech and semis; reverse lookup picks last assignment."""
        assert "NVDA" in _SECTOR_GROUPS["mega_tech"]
        assert "NVDA" in _SECTOR_GROUPS["semis"]
        # Reverse lookup should give one of them (last wins due to dict iteration)
        assert _TICKER_SECTOR["NVDA"] in ("mega_tech", "semis")
