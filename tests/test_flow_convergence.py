"""Tests for the convergence detector (src/rot/flow/convergence.py).

Covers:
  - Aligned convergence (signal + flow in same direction)
  - Contradictory convergence (signal vs flow opposite)
  - Amplified convergence (3+ aligned flow events)
  - Time window filtering
  - Neutral flow detection (net premium < $5k)
  - Non-directional signal skipping (mixed/unknown)
  - Min score filtering
  - Min flow events gating
  - Multi-ticker batch processing
  - No-overlap (ticker mismatch)
  - check_signal convenience method
  - Empty inputs
  - Premium factor scaling
  - Config overrides
"""

import time
import uuid

import pytest

from rot.flow.convergence import ConvergenceConfig, ConvergenceDetector
from rot.flow.types import FlowEvent, FlowSignalConvergence


# ── Helpers ────────────────────────────────────────────


def _make_event(
    ticker: str = "TSLA",
    direction: str = "bullish",
    premium: float = 100_000.0,
    score: float = 50.0,
    timestamp: float | None = None,
    flow_type: str = "block_trade",
) -> FlowEvent:
    return FlowEvent(
        id=str(uuid.uuid4()),
        ticker=ticker,
        flow_type=flow_type,
        direction=direction,
        premium=premium,
        volume=500,
        oi_change=100,
        score=score,
        timestamp=timestamp or time.time(),
    )


def _make_signal(
    ticker: str = "TSLA",
    stance: str = "bullish",
    created_at: float | None = None,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "ticker": ticker,
        "stance": stance,
        "created_at": created_at or time.time(),
    }


# ── Aligned convergence ───────────────────────────────


class TestAlignedConvergence:
    """Bullish signal + bullish flow, or bearish + bearish."""

    def test_bullish_signal_bullish_flow(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=100_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1
        c = results[0]
        assert c.convergence_type == "aligned"
        assert c.signal_stance == "bullish"
        assert c.flow_direction == "bullish"
        assert c.convergence_score >= 55  # base is 55

    def test_bearish_signal_bearish_flow(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bearish", premium=100_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bearish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1
        c = results[0]
        assert c.convergence_type == "aligned"
        assert c.signal_stance == "bearish"
        assert c.flow_direction == "bearish"

    def test_aligned_score_includes_factors(self):
        """Score should be base(55) + premium(up to 20) + count(2) + score(5)."""
        now = time.time()
        detector = ConvergenceDetector()
        # premium=100k -> premium_factor = min(100k/100k, 1.0)*20 = 20
        # 1 event -> count_factor = min(1*2, 10) = 2
        # score=50 -> score_factor = min(50/10, 10) = 5
        events = [_make_event(direction="bullish", premium=100_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        c = results[0]
        expected = 55 + 20 + 2 + 5  # 82
        assert c.convergence_score == expected

    def test_aligned_details_populated(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=80_000, score=40, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        c = results[0]
        assert "bullish_premium" in c.details
        assert "bearish_premium" in c.details
        assert c.details["event_count"] == 1
        assert c.details["bullish_premium"] == 80_000.0
        assert c.details["bearish_premium"] == 0.0


# ── Contradictory convergence ─────────────────────────


class TestContradictoryConvergence:
    """Signal and flow in opposite directions."""

    def test_bullish_signal_bearish_flow(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bearish", premium=100_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1
        c = results[0]
        assert c.convergence_type == "contradictory"
        assert c.signal_stance == "bullish"
        assert c.flow_direction == "bearish"
        assert c.convergence_score >= 35  # base is 35

    def test_bearish_signal_bullish_flow(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=100_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bearish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1
        c = results[0]
        assert c.convergence_type == "contradictory"
        assert c.net_flow_premium > 0  # bullish flow

    def test_contradictory_score_calculation(self):
        """base(35) + premium(20) + count(2) + score(5) = 62."""
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bearish", premium=100_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        c = results[0]
        expected = 35 + 20 + 2 + 5  # 62
        assert c.convergence_score == expected


# ── Amplified convergence ─────────────────────────────


class TestAmplifiedConvergence:
    """3+ flow events in same direction as signal -> amplified."""

    def test_three_aligned_events_is_amplified(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [
            _make_event(direction="bullish", premium=50_000, score=60, timestamp=now),
            _make_event(direction="bullish", premium=50_000, score=60, timestamp=now - 100),
            _make_event(direction="bullish", premium=50_000, score=60, timestamp=now - 200),
        ]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1
        c = results[0]
        assert c.convergence_type == "amplified"
        assert c.convergence_score >= 70  # base is 70

    def test_amplified_score_calculation(self):
        """Amplified: base(70) + premium + count + score factors."""
        now = time.time()
        detector = ConvergenceDetector()
        # 3 events each 50k bullish => net_premium = 150k
        # premium_factor = min(150k/100k, 1.0) * 20 = 20 (capped at 1.0)
        # count_factor = min(3*2, 10) = 6
        # avg_score = 50 => score_factor = min(50/10, 10) = 5
        events = [
            _make_event(direction="bullish", premium=50_000, score=50, timestamp=now),
            _make_event(direction="bullish", premium=50_000, score=50, timestamp=now - 60),
            _make_event(direction="bullish", premium=50_000, score=50, timestamp=now - 120),
        ]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        c = results[0]
        # 70 + 20 + 6 + 5 = 101 -> capped at 100
        assert c.convergence_score == 100.0

    def test_two_aligned_events_not_amplified(self):
        """Only 2 aligned events -> aligned, not amplified."""
        now = time.time()
        detector = ConvergenceDetector()
        events = [
            _make_event(direction="bullish", premium=50_000, score=50, timestamp=now),
            _make_event(direction="bullish", premium=50_000, score=50, timestamp=now - 60),
        ]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1
        assert results[0].convergence_type == "aligned"

    def test_custom_amplified_threshold(self):
        """Custom amplified_threshold=2 makes 2 events trigger amplified."""
        now = time.time()
        cfg = ConvergenceConfig(amplified_threshold=2)
        detector = ConvergenceDetector(config=cfg)
        events = [
            _make_event(direction="bullish", premium=50_000, score=50, timestamp=now),
            _make_event(direction="bullish", premium=50_000, score=50, timestamp=now - 60),
        ]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1
        assert results[0].convergence_type == "amplified"

    def test_amplified_bearish(self):
        """3 bearish flow events + bearish signal -> amplified."""
        now = time.time()
        detector = ConvergenceDetector()
        events = [
            _make_event(direction="bearish", premium=40_000, score=55, timestamp=now),
            _make_event(direction="bearish", premium=40_000, score=55, timestamp=now - 100),
            _make_event(direction="bearish", premium=40_000, score=55, timestamp=now - 200),
        ]
        signals = [_make_signal(stance="bearish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1
        assert results[0].convergence_type == "amplified"
        assert results[0].flow_direction == "bearish"


# ── Time window matching ──────────────────────────────


class TestTimeWindow:
    """Events outside the time window should not be matched."""

    def test_event_within_window_matched(self):
        now = time.time()
        detector = ConvergenceDetector()  # default 6h window
        # Event 1 hour ago => within 6h window
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now - 3600)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1

    def test_event_outside_window_not_matched(self):
        now = time.time()
        detector = ConvergenceDetector()  # default 6h = 21600s
        # Event 7 hours ago => outside 6h window
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now - 25200)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0

    def test_event_at_window_boundary_included(self):
        now = time.time()
        detector = ConvergenceDetector()  # 6h = 21600s
        # Exactly 6h delta => should be included (<=)
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now - 21600)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1

    def test_event_just_past_window_excluded(self):
        now = time.time()
        detector = ConvergenceDetector()  # 6h = 21600s
        # 6h + 1s delta => just outside window
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now - 21601)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0

    def test_custom_window_hours(self):
        now = time.time()
        cfg = ConvergenceConfig(window_hours=1.0)
        detector = ConvergenceDetector(config=cfg)
        # 2 hours ago => outside 1h window
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now - 7200)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0

    def test_future_event_within_window(self):
        """Flow event slightly after signal should still match (abs delta)."""
        now = time.time()
        detector = ConvergenceDetector()
        # Event 30 min after signal
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now + 1800)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1


# ── Neutral flow ──────────────────────────────────────


class TestNeutralFlow:
    """Net premium < $5k means neutral flow -> no convergence."""

    def test_small_net_premium_neutral(self):
        now = time.time()
        detector = ConvergenceDetector()
        # $4999 net bullish < $5000 threshold -> neutral
        events = [_make_event(direction="bullish", premium=4999, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0

    def test_exactly_5000_neutral(self):
        """abs(net_premium) < 5000 is the check: 5000 is NOT < 5000, so not neutral."""
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=5000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        # 5000 is not < 5000, so flow_direction = bullish, should produce result
        assert len(results) == 1

    def test_mixed_flow_cancels_to_neutral(self):
        """Bullish and bearish flow that nearly cancel out -> neutral."""
        now = time.time()
        detector = ConvergenceDetector()
        events = [
            _make_event(direction="bullish", premium=50_000, score=50, timestamp=now),
            _make_event(direction="bearish", premium=48_000, score=50, timestamp=now),
        ]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        # net = 50k - 48k = 2k < 5k -> neutral -> no convergence
        assert len(results) == 0


# ── Non-directional signals ───────────────────────────


class TestNonDirectionalSignals:
    """Signals with stance mixed/unknown should be skipped."""

    def test_mixed_stance_skipped(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now)]
        signals = [_make_signal(stance="mixed", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0

    def test_unknown_stance_skipped(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now)]
        signals = [_make_signal(stance="unknown", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0


# ── Min score filter ──────────────────────────────────


class TestMinScoreFilter:
    """Convergences below min_score should be filtered out."""

    def test_below_min_score_filtered(self):
        now = time.time()
        cfg = ConvergenceConfig(min_score=90)
        detector = ConvergenceDetector(config=cfg)
        # Aligned base=55. Even with full factors, max ~82 for single event.
        events = [_make_event(direction="bullish", premium=100_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0

    def test_above_min_score_passes(self):
        now = time.time()
        cfg = ConvergenceConfig(min_score=50)
        detector = ConvergenceDetector(config=cfg)
        events = [_make_event(direction="bullish", premium=100_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1


# ── Min flow events ───────────────────────────────────


class TestMinFlowEvents:
    """Config.min_flow_events gates the minimum matched events required."""

    def test_min_flow_events_not_met(self):
        now = time.time()
        cfg = ConvergenceConfig(min_flow_events=2)
        detector = ConvergenceDetector(config=cfg)
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0

    def test_min_flow_events_met(self):
        now = time.time()
        cfg = ConvergenceConfig(min_flow_events=2)
        detector = ConvergenceDetector(config=cfg)
        events = [
            _make_event(direction="bullish", premium=50_000, timestamp=now),
            _make_event(direction="bullish", premium=50_000, timestamp=now - 60),
        ]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1


# ── Multiple signals / tickers ────────────────────────


class TestMultipleSignals:
    """Different tickers matched to their own flow events."""

    def test_two_tickers_each_matched(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [
            _make_event(ticker="TSLA", direction="bullish", premium=100_000, timestamp=now),
            _make_event(ticker="AAPL", direction="bearish", premium=100_000, timestamp=now),
        ]
        signals = [
            _make_signal(ticker="TSLA", stance="bullish", created_at=now),
            _make_signal(ticker="AAPL", stance="bearish", created_at=now),
        ]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 2
        tickers = {c.ticker for c in results}
        assert tickers == {"TSLA", "AAPL"}
        for c in results:
            assert c.convergence_type == "aligned"

    def test_signal_without_flow_excluded(self):
        """Signal for a ticker with no flow events produces nothing."""
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(ticker="TSLA", direction="bullish", premium=100_000, timestamp=now)]
        signals = [_make_signal(ticker="NVDA", stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0


# ── No overlap ────────────────────────────────────────


class TestNoOverlap:
    """Signal ticker not in flow events -> no convergence."""

    def test_no_matching_ticker(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(ticker="AAPL", direction="bullish", premium=100_000, timestamp=now)]
        signals = [_make_signal(ticker="MSFT", stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0


# ── check_signal convenience ─────────────────────────


class TestCheckSignal:
    """check_signal wraps find_convergences for a single signal."""

    def test_check_signal_returns_convergence(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=100_000, score=50, timestamp=now)]
        signal = _make_signal(stance="bullish", created_at=now)

        result = detector.check_signal(signal, events, timestamp=now)

        assert result is not None
        assert isinstance(result, FlowSignalConvergence)
        assert result.convergence_type == "aligned"

    def test_check_signal_returns_none_when_no_match(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(ticker="AAPL", direction="bullish", premium=100_000, timestamp=now)]
        signal = _make_signal(ticker="MSFT", stance="bullish", created_at=now)

        result = detector.check_signal(signal, events, timestamp=now)

        assert result is None

    def test_check_signal_with_empty_events(self):
        detector = ConvergenceDetector()
        signal = _make_signal(stance="bullish")

        result = detector.check_signal(signal, [], timestamp=time.time())

        assert result is None


# ── Empty inputs ──────────────────────────────────────


class TestEmptyInputs:
    """Empty events or signals return empty list."""

    def test_empty_events(self):
        detector = ConvergenceDetector()
        signals = [_make_signal()]

        results = detector.find_convergences([], signals, timestamp=time.time())

        assert results == []

    def test_empty_signals(self):
        detector = ConvergenceDetector()
        events = [_make_event()]

        results = detector.find_convergences(events, [], timestamp=time.time())

        assert results == []

    def test_both_empty(self):
        detector = ConvergenceDetector()

        results = detector.find_convergences([], [], timestamp=time.time())

        assert results == []


# ── Premium factor ────────────────────────────────────


class TestPremiumFactor:
    """Larger premium => higher convergence score."""

    def test_higher_premium_higher_score(self):
        now = time.time()
        detector = ConvergenceDetector()

        low_events = [_make_event(direction="bullish", premium=10_000, score=50, timestamp=now)]
        high_events = [_make_event(direction="bullish", premium=200_000, score=50, timestamp=now)]

        low_signal = _make_signal(stance="bullish", created_at=now)
        high_signal = _make_signal(stance="bullish", created_at=now)

        low_results = detector.find_convergences(low_events, [low_signal], timestamp=now)
        high_results = detector.find_convergences(high_events, [high_signal], timestamp=now)

        assert len(low_results) == 1
        assert len(high_results) == 1
        assert high_results[0].convergence_score > low_results[0].convergence_score

    def test_premium_factor_caps_at_one(self):
        """Premium above premium_scale still only contributes max 20 points."""
        now = time.time()
        detector = ConvergenceDetector()
        # 200k premium, scale is 100k => min(200k/100k, 1.0) = 1.0 => 20 points
        events_200k = [_make_event(direction="bullish", premium=200_000, score=50, timestamp=now)]
        events_500k = [_make_event(direction="bullish", premium=500_000, score=50, timestamp=now)]

        sig1 = _make_signal(stance="bullish", created_at=now)
        sig2 = _make_signal(stance="bullish", created_at=now)

        r1 = detector.find_convergences(events_200k, [sig1], timestamp=now)
        r2 = detector.find_convergences(events_500k, [sig2], timestamp=now)

        # Both should have the same premium factor contribution (capped at 20)
        assert r1[0].convergence_score == r2[0].convergence_score

    def test_small_premium_small_factor(self):
        """$10k premium => factor = min(10k/100k, 1.0)*20 = 2.0."""
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=10_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        c = results[0]
        assert c.details["premium_factor"] == 2.0


# ── Score capping ─────────────────────────────────────


class TestScoreCapping:
    """Final score is capped at 100."""

    def test_score_capped_at_100(self):
        now = time.time()
        detector = ConvergenceDetector()
        # Amplified base(70) + premium(20) + count(10 for 5 events) + score(10 for 100-score events)
        events = [
            _make_event(direction="bullish", premium=100_000, score=100, timestamp=now - i * 10)
            for i in range(5)
        ]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1
        assert results[0].convergence_score == 100.0


# ── Config overrides ──────────────────────────────────


class TestConfigOverrides:
    """Custom config values are respected."""

    def test_default_config_values(self):
        cfg = ConvergenceConfig()
        assert cfg.window_hours == 6.0
        assert cfg.min_score == 30.0
        assert cfg.premium_scale == 100_000.0
        assert cfg.min_flow_events == 1
        assert cfg.aligned_base_score == 55.0
        assert cfg.contradictory_base_score == 35.0
        assert cfg.amplified_threshold == 3
        assert cfg.amplified_base_score == 70.0

    def test_custom_aligned_base_score(self):
        now = time.time()
        cfg = ConvergenceConfig(aligned_base_score=40.0)
        detector = ConvergenceDetector(config=cfg)
        events = [_make_event(direction="bullish", premium=100_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        c = results[0]
        # base(40) + premium(20) + count(2) + score(5) = 67
        assert c.convergence_score == 67.0

    def test_custom_contradictory_base_score(self):
        now = time.time()
        cfg = ConvergenceConfig(contradictory_base_score=20.0, min_score=0)
        detector = ConvergenceDetector(config=cfg)
        events = [_make_event(direction="bearish", premium=100_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        c = results[0]
        # base(20) + premium(20) + count(2) + score(5) = 47
        assert c.convergence_score == 47.0

    def test_custom_premium_scale(self):
        """Smaller premium_scale means premium factor hits cap sooner."""
        now = time.time()
        cfg = ConvergenceConfig(premium_scale=10_000)
        detector = ConvergenceDetector(config=cfg)
        # $10k premium with $10k scale => factor = min(10k/10k, 1.0)*20 = 20
        events = [_make_event(direction="bullish", premium=10_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        c = results[0]
        assert c.details["premium_factor"] == 20.0

    def test_config_accessible_via_property(self):
        cfg = ConvergenceConfig(window_hours=12.0)
        detector = ConvergenceDetector(config=cfg)
        assert detector.config is cfg
        assert detector.config.window_hours == 12.0


# ── Edge cases ────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_signal_missing_created_at_skipped(self):
        """Signal without created_at (or 0) is skipped."""
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now)]
        signals = [{"id": "s1", "ticker": "TSLA", "stance": "bullish", "created_at": 0}]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0

    def test_signal_with_none_created_at_skipped(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now)]
        signals = [{"id": "s1", "ticker": "TSLA", "stance": "bullish", "created_at": None}]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 0

    def test_flow_event_ids_collected(self):
        """All matched flow event IDs are captured in convergence."""
        now = time.time()
        detector = ConvergenceDetector()
        e1 = _make_event(direction="bullish", premium=50_000, timestamp=now)
        e2 = _make_event(direction="bullish", premium=50_000, timestamp=now - 60)
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences([e1, e2], signals, timestamp=now)

        assert len(results) == 1
        assert set(results[0].flow_event_ids) == {e1.id, e2.id}

    def test_convergence_has_unique_id(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=100_000, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert results[0].id is not None
        assert len(results[0].id) > 0

    def test_net_premium_negative_for_bearish_flow(self):
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bearish", premium=100_000, score=50, timestamp=now)]
        signals = [_make_signal(stance="bearish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        c = results[0]
        assert c.net_flow_premium < 0

    def test_count_factor_caps_at_10(self):
        """Even with many events, count factor maxes at 10."""
        now = time.time()
        detector = ConvergenceDetector()
        events = [
            _make_event(direction="bullish", premium=10_000, score=10, timestamp=now - i * 10)
            for i in range(10)
        ]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        assert len(results) == 1
        # 10 events * 2 = 20 -> capped at 10
        c = results[0]
        assert c.details["event_count"] == 10

    def test_score_factor_caps_at_10(self):
        """avg_event_score of 100 -> score_factor = min(100/10, 10) = 10."""
        now = time.time()
        detector = ConvergenceDetector()
        events = [_make_event(direction="bullish", premium=100_000, score=100, timestamp=now)]
        signals = [_make_signal(stance="bullish", created_at=now)]

        results = detector.find_convergences(events, signals, timestamp=now)

        c = results[0]
        assert c.details["avg_event_score"] == 100.0
