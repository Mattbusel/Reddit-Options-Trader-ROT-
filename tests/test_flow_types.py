"""Tests for options flow intelligence data types."""

from __future__ import annotations

import pytest

from rot.flow.types import (
    CONVERGENCE_TYPES,
    FLOW_DIRECTIONS,
    FLOW_TYPES,
    PATTERN_TYPES,
    FlowEvent,
    FlowPattern,
    FlowScore,
    FlowSignalConvergence,
    FlowSummary,
    GreeksSnapshot,
)


# ── FlowEvent ──


class TestFlowEvent:
    """FlowEvent frozen dataclass tests."""

    def test_create_valid_event(self):
        e = FlowEvent(
            ticker="TSLA",
            flow_type="sweep",
            direction="bullish",
            premium=250000.0,
            volume=500,
            oi_change=200,
            score=78.5,
            timestamp=1700000000.0,
            details={"exchange": "CBOE"},
            signal_id="sig-001",
            id="flow-001",
        )
        assert e.ticker == "TSLA"
        assert e.flow_type == "sweep"
        assert e.direction == "bullish"
        assert e.premium == 250000.0
        assert e.volume == 500
        assert e.oi_change == 200
        assert e.score == 78.5
        assert e.signal_id == "sig-001"
        assert e.id == "flow-001"

    def test_create_all_flow_types(self):
        for ft in FLOW_TYPES:
            e = FlowEvent(
                ticker="SPY", flow_type=ft, direction="neutral",
                premium=1000.0, volume=10, oi_change=0,
                score=50.0, timestamp=1.0,
            )
            assert e.flow_type == ft

    def test_create_all_directions(self):
        for d in FLOW_DIRECTIONS:
            e = FlowEvent(
                ticker="SPY", flow_type="block_trade", direction=d,
                premium=1000.0, volume=10, oi_change=0,
                score=50.0, timestamp=1.0,
            )
            assert e.direction == d

    def test_invalid_flow_type_raises(self):
        with pytest.raises(ValueError, match="Invalid flow_type"):
            FlowEvent(
                ticker="SPY", flow_type="bad_type", direction="bullish",
                premium=1000.0, volume=10, oi_change=0,
                score=50.0, timestamp=1.0,
            )

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError, match="Invalid direction"):
            FlowEvent(
                ticker="SPY", flow_type="sweep", direction="sideways",
                premium=1000.0, volume=10, oi_change=0,
                score=50.0, timestamp=1.0,
            )

    def test_negative_premium_raises(self):
        with pytest.raises(ValueError, match="Premium must be >= 0"):
            FlowEvent(
                ticker="SPY", flow_type="sweep", direction="bullish",
                premium=-100.0, volume=10, oi_change=0,
                score=50.0, timestamp=1.0,
            )

    def test_score_below_zero_raises(self):
        with pytest.raises(ValueError, match="Score must be 0-100"):
            FlowEvent(
                ticker="SPY", flow_type="sweep", direction="bullish",
                premium=1000.0, volume=10, oi_change=0,
                score=-1.0, timestamp=1.0,
            )

    def test_score_above_100_raises(self):
        with pytest.raises(ValueError, match="Score must be 0-100"):
            FlowEvent(
                ticker="SPY", flow_type="sweep", direction="bullish",
                premium=1000.0, volume=10, oi_change=0,
                score=100.1, timestamp=1.0,
            )

    def test_score_edge_zero(self):
        e = FlowEvent(
            ticker="SPY", flow_type="sweep", direction="neutral",
            premium=0.0, volume=0, oi_change=0,
            score=0.0, timestamp=1.0,
        )
        assert e.score == 0.0

    def test_score_edge_100(self):
        e = FlowEvent(
            ticker="SPY", flow_type="sweep", direction="bullish",
            premium=5000000.0, volume=10000, oi_change=5000,
            score=100.0, timestamp=1.0,
        )
        assert e.score == 100.0

    def test_premium_zero_allowed(self):
        e = FlowEvent(
            ticker="SPY", flow_type="dark_pool", direction="neutral",
            premium=0.0, volume=100, oi_change=0,
            score=30.0, timestamp=1.0,
        )
        assert e.premium == 0.0

    def test_signal_id_optional(self):
        e = FlowEvent(
            ticker="AAPL", flow_type="accumulation", direction="bullish",
            premium=500.0, volume=5, oi_change=5,
            score=40.0, timestamp=1.0,
        )
        assert e.signal_id is None

    def test_id_optional(self):
        e = FlowEvent(
            ticker="AAPL", flow_type="distribution", direction="bearish",
            premium=500.0, volume=5, oi_change=-5,
            score=40.0, timestamp=1.0,
        )
        assert e.id is None

    def test_frozen(self):
        e = FlowEvent(
            ticker="SPY", flow_type="sweep", direction="bullish",
            premium=1000.0, volume=10, oi_change=0,
            score=50.0, timestamp=1.0,
        )
        with pytest.raises(AttributeError):
            e.score = 60.0  # type: ignore[misc]

    def test_to_dict(self):
        e = FlowEvent(
            ticker="NVDA", flow_type="block_trade", direction="bearish",
            premium=1234567.89, volume=2000, oi_change=-500,
            score=92.34, timestamp=1700000000.0,
            details={"legs": 2}, signal_id="s1", id="f1",
        )
        d = e.to_dict()
        assert d["ticker"] == "NVDA"
        assert d["flow_type"] == "block_trade"
        assert d["direction"] == "bearish"
        assert d["premium"] == 1234567.89
        assert d["volume"] == 2000
        assert d["oi_change"] == -500
        assert d["score"] == 92.3
        assert d["signal_id"] == "s1"
        assert d["details"]["legs"] == 2

    def test_to_dict_rounds_premium(self):
        e = FlowEvent(
            ticker="SPY", flow_type="sweep", direction="bullish",
            premium=1234.5678, volume=10, oi_change=0,
            score=50.0, timestamp=1.0,
        )
        d = e.to_dict()
        assert d["premium"] == 1234.57

    def test_to_dict_rounds_score(self):
        e = FlowEvent(
            ticker="SPY", flow_type="sweep", direction="bullish",
            premium=1000.0, volume=10, oi_change=0,
            score=55.555, timestamp=1.0,
        )
        d = e.to_dict()
        assert d["score"] == 55.6

    def test_premium_k_property(self):
        e = FlowEvent(
            ticker="TSLA", flow_type="sweep", direction="bullish",
            premium=250000.0, volume=500, oi_change=200,
            score=80.0, timestamp=1.0,
        )
        assert e.premium_k == 250.0

    def test_premium_k_rounds(self):
        e = FlowEvent(
            ticker="TSLA", flow_type="sweep", direction="bullish",
            premium=1234567.0, volume=100, oi_change=0,
            score=50.0, timestamp=1.0,
        )
        assert e.premium_k == 1234.6

    def test_premium_k_zero(self):
        e = FlowEvent(
            ticker="SPY", flow_type="dark_pool", direction="neutral",
            premium=0.0, volume=1, oi_change=0,
            score=10.0, timestamp=1.0,
        )
        assert e.premium_k == 0.0

    def test_defaults_details_empty_dict(self):
        e = FlowEvent(
            ticker="SPY", flow_type="sweep", direction="bullish",
            premium=1000.0, volume=10, oi_change=0,
            score=50.0, timestamp=1.0,
        )
        assert e.details == {}


# ── FlowScore ──


class TestFlowScore:
    """FlowScore frozen dataclass tests."""

    def test_create_valid_score(self):
        s = FlowScore(
            ticker="AAPL",
            score=72.5,
            bullish_flow=500000.0,
            bearish_flow=200000.0,
            net_premium=300000.0,
            event_count=15,
            detected_at=1700000000.0,
        )
        assert s.ticker == "AAPL"
        assert s.score == 72.5
        assert s.event_count == 15

    def test_score_below_zero_raises(self):
        with pytest.raises(ValueError, match="Score must be 0-100"):
            FlowScore(
                ticker="SPY", score=-0.1, bullish_flow=0, bearish_flow=0,
                net_premium=0, event_count=0, detected_at=1.0,
            )

    def test_score_above_100_raises(self):
        with pytest.raises(ValueError, match="Score must be 0-100"):
            FlowScore(
                ticker="SPY", score=100.1, bullish_flow=0, bearish_flow=0,
                net_premium=0, event_count=0, detected_at=1.0,
            )

    def test_score_edge_zero(self):
        s = FlowScore(
            ticker="SPY", score=0.0, bullish_flow=0, bearish_flow=0,
            net_premium=0, event_count=0, detected_at=1.0,
        )
        assert s.score == 0.0

    def test_score_edge_100(self):
        s = FlowScore(
            ticker="SPY", score=100.0, bullish_flow=1000000, bearish_flow=0,
            net_premium=1000000, event_count=50, detected_at=1.0,
        )
        assert s.score == 100.0

    def test_flow_direction_bullish(self):
        s = FlowScore(
            ticker="TSLA", score=80.0,
            bullish_flow=500000.0, bearish_flow=100000.0,
            net_premium=400000.0,
            event_count=10, detected_at=1.0,
        )
        assert s.flow_direction == "bullish"

    def test_flow_direction_bearish(self):
        s = FlowScore(
            ticker="TSLA", score=65.0,
            bullish_flow=100000.0, bearish_flow=500000.0,
            net_premium=-400000.0,
            event_count=10, detected_at=1.0,
        )
        assert s.flow_direction == "bearish"

    def test_flow_direction_neutral_small_premium(self):
        s = FlowScore(
            ticker="SPY", score=30.0,
            bullish_flow=5000.0, bearish_flow=4000.0,
            net_premium=1000.0,
            event_count=2, detected_at=1.0,
        )
        assert s.flow_direction == "neutral"

    def test_flow_direction_neutral_threshold(self):
        """Net premium exactly at threshold ($9999) is still neutral."""
        s = FlowScore(
            ticker="SPY", score=30.0,
            bullish_flow=15000.0, bearish_flow=5001.0,
            net_premium=9999.0,
            event_count=2, detected_at=1.0,
        )
        assert s.flow_direction == "neutral"

    def test_flow_direction_bullish_at_threshold(self):
        """Net premium exactly $10000 crosses into bullish."""
        s = FlowScore(
            ticker="SPY", score=40.0,
            bullish_flow=20000.0, bearish_flow=10000.0,
            net_premium=10000.0,
            event_count=5, detected_at=1.0,
        )
        assert s.flow_direction == "bullish"

    def test_flow_direction_bearish_at_neg_threshold(self):
        """Net premium exactly -$10000 crosses into bearish."""
        s = FlowScore(
            ticker="SPY", score=40.0,
            bullish_flow=10000.0, bearish_flow=20000.0,
            net_premium=-10000.0,
            event_count=5, detected_at=1.0,
        )
        assert s.flow_direction == "bearish"

    def test_frozen(self):
        s = FlowScore(
            ticker="SPY", score=50.0, bullish_flow=0, bearish_flow=0,
            net_premium=0, event_count=0, detected_at=1.0,
        )
        with pytest.raises(AttributeError):
            s.score = 60.0  # type: ignore[misc]

    def test_to_dict(self):
        s = FlowScore(
            ticker="NVDA", score=85.4321,
            bullish_flow=750123.456, bearish_flow=250789.123,
            net_premium=499334.333,
            event_count=20, detected_at=1700000000.0,
        )
        d = s.to_dict()
        assert d["ticker"] == "NVDA"
        assert d["score"] == 85.4
        assert d["bullish_flow"] == 750123.46
        assert d["bearish_flow"] == 250789.12
        assert d["net_premium"] == 499334.33
        assert d["event_count"] == 20
        assert d["flow_direction"] == "bullish"
        assert d["detected_at"] == 1700000000.0


# ── FlowPattern ──


class TestFlowPattern:
    """FlowPattern frozen dataclass tests."""

    def test_create_valid_pattern(self):
        p = FlowPattern(
            pattern_type="repeat_buyer",
            tickers=["TSLA"],
            confidence=0.85,
            timeframe="4h",
            event_count=5,
            details={"buyer_count": 3},
            detected_at=1700000000.0,
            id="pat-001",
        )
        assert p.pattern_type == "repeat_buyer"
        assert p.tickers == ["TSLA"]
        assert p.confidence == 0.85
        assert p.id == "pat-001"

    def test_create_all_pattern_types(self):
        for pt in PATTERN_TYPES:
            p = FlowPattern(
                pattern_type=pt, tickers=["SPY"],
                confidence=0.5, timeframe="1h", event_count=2,
            )
            assert p.pattern_type == pt

    def test_invalid_pattern_type_raises(self):
        with pytest.raises(ValueError, match="Invalid pattern_type"):
            FlowPattern(
                pattern_type="invalid_pattern", tickers=["SPY"],
                confidence=0.5, timeframe="1h", event_count=1,
            )

    def test_confidence_below_zero_raises(self):
        with pytest.raises(ValueError, match="Confidence must be 0-1"):
            FlowPattern(
                pattern_type="hedging", tickers=["SPY"],
                confidence=-0.01, timeframe="1h", event_count=1,
            )

    def test_confidence_above_one_raises(self):
        with pytest.raises(ValueError, match="Confidence must be 0-1"):
            FlowPattern(
                pattern_type="hedging", tickers=["SPY"],
                confidence=1.01, timeframe="1h", event_count=1,
            )

    def test_confidence_edge_zero(self):
        p = FlowPattern(
            pattern_type="rolling", tickers=["AAPL"],
            confidence=0.0, timeframe="1d", event_count=1,
        )
        assert p.confidence == 0.0

    def test_confidence_edge_one(self):
        p = FlowPattern(
            pattern_type="rolling", tickers=["AAPL"],
            confidence=1.0, timeframe="1d", event_count=3,
        )
        assert p.confidence == 1.0

    def test_cross_ticker_multiple_tickers(self):
        p = FlowPattern(
            pattern_type="cross_ticker",
            tickers=["AAPL", "MSFT", "GOOG"],
            confidence=0.7, timeframe="1w", event_count=8,
        )
        assert len(p.tickers) == 3

    def test_id_optional(self):
        p = FlowPattern(
            pattern_type="accumulation_sequence", tickers=["NVDA"],
            confidence=0.6, timeframe="4h", event_count=4,
        )
        assert p.id is None

    def test_defaults(self):
        p = FlowPattern(
            pattern_type="hedging", tickers=["SPY"],
            confidence=0.5, timeframe="1h", event_count=2,
        )
        assert p.details == {}
        assert p.detected_at == 0.0
        assert p.id is None

    def test_frozen(self):
        p = FlowPattern(
            pattern_type="hedging", tickers=["SPY"],
            confidence=0.5, timeframe="1h", event_count=2,
        )
        with pytest.raises(AttributeError):
            p.confidence = 0.9  # type: ignore[misc]

    def test_to_dict(self):
        p = FlowPattern(
            pattern_type="repeat_buyer",
            tickers=["TSLA", "NVDA"],
            confidence=0.8765,
            timeframe="4h",
            event_count=6,
            details={"avg_premium": 50000},
            detected_at=1700000000.0,
            id="p1",
        )
        d = p.to_dict()
        assert d["pattern_type"] == "repeat_buyer"
        assert d["tickers"] == ["TSLA", "NVDA"]
        assert d["confidence"] == 0.876
        assert d["timeframe"] == "4h"
        assert d["event_count"] == 6
        assert d["id"] == "p1"
        assert d["details"]["avg_premium"] == 50000


# ── FlowSignalConvergence ──


class TestFlowSignalConvergence:
    """FlowSignalConvergence frozen dataclass tests."""

    def test_create_valid_convergence(self):
        c = FlowSignalConvergence(
            signal_id="sig-001",
            ticker="TSLA",
            flow_event_ids=["f1", "f2"],
            convergence_score=82.5,
            convergence_type="aligned",
            signal_stance="bullish",
            flow_direction="bullish",
            net_flow_premium=500000.0,
            details={"match_count": 2},
            detected_at=1700000000.0,
            id="conv-001",
        )
        assert c.signal_id == "sig-001"
        assert c.convergence_score == 82.5
        assert c.convergence_type == "aligned"

    def test_create_all_convergence_types(self):
        for ct in CONVERGENCE_TYPES:
            c = FlowSignalConvergence(
                signal_id="s1", ticker="SPY", flow_event_ids=["f1"],
                convergence_score=50.0, convergence_type=ct,
                signal_stance="bullish", flow_direction="neutral",
                net_flow_premium=0.0,
            )
            assert c.convergence_type == ct

    def test_invalid_convergence_type_raises(self):
        with pytest.raises(ValueError, match="Invalid convergence_type"):
            FlowSignalConvergence(
                signal_id="s1", ticker="SPY", flow_event_ids=["f1"],
                convergence_score=50.0, convergence_type="unknown",
                signal_stance="bullish", flow_direction="neutral",
                net_flow_premium=0.0,
            )

    def test_score_below_zero_raises(self):
        with pytest.raises(ValueError, match="Convergence score must be 0-100"):
            FlowSignalConvergence(
                signal_id="s1", ticker="SPY", flow_event_ids=["f1"],
                convergence_score=-5.0, convergence_type="aligned",
                signal_stance="bullish", flow_direction="bullish",
                net_flow_premium=100000.0,
            )

    def test_score_above_100_raises(self):
        with pytest.raises(ValueError, match="Convergence score must be 0-100"):
            FlowSignalConvergence(
                signal_id="s1", ticker="SPY", flow_event_ids=["f1"],
                convergence_score=100.1, convergence_type="aligned",
                signal_stance="bullish", flow_direction="bullish",
                net_flow_premium=100000.0,
            )

    def test_score_edge_zero(self):
        c = FlowSignalConvergence(
            signal_id="s1", ticker="SPY", flow_event_ids=[],
            convergence_score=0.0, convergence_type="contradictory",
            signal_stance="bearish", flow_direction="bullish",
            net_flow_premium=50000.0,
        )
        assert c.convergence_score == 0.0

    def test_score_edge_100(self):
        c = FlowSignalConvergence(
            signal_id="s1", ticker="TSLA", flow_event_ids=["f1", "f2", "f3"],
            convergence_score=100.0, convergence_type="amplified",
            signal_stance="bullish", flow_direction="bullish",
            net_flow_premium=2000000.0,
        )
        assert c.convergence_score == 100.0

    def test_id_optional(self):
        c = FlowSignalConvergence(
            signal_id="s1", ticker="SPY", flow_event_ids=["f1"],
            convergence_score=50.0, convergence_type="aligned",
            signal_stance="bullish", flow_direction="bullish",
            net_flow_premium=100000.0,
        )
        assert c.id is None

    def test_defaults(self):
        c = FlowSignalConvergence(
            signal_id="s1", ticker="SPY", flow_event_ids=["f1"],
            convergence_score=50.0, convergence_type="aligned",
            signal_stance="bullish", flow_direction="bullish",
            net_flow_premium=100000.0,
        )
        assert c.details == {}
        assert c.detected_at == 0.0
        assert c.id is None

    def test_frozen(self):
        c = FlowSignalConvergence(
            signal_id="s1", ticker="SPY", flow_event_ids=["f1"],
            convergence_score=50.0, convergence_type="aligned",
            signal_stance="bullish", flow_direction="bullish",
            net_flow_premium=100000.0,
        )
        with pytest.raises(AttributeError):
            c.convergence_score = 90.0  # type: ignore[misc]

    def test_to_dict(self):
        c = FlowSignalConvergence(
            signal_id="sig-001", ticker="AAPL",
            flow_event_ids=["f1", "f2"],
            convergence_score=77.777,
            convergence_type="amplified",
            signal_stance="bearish",
            flow_direction="bearish",
            net_flow_premium=-345678.123,
            details={"strength": "high"},
            detected_at=1700000000.0,
            id="c1",
        )
        d = c.to_dict()
        assert d["signal_id"] == "sig-001"
        assert d["ticker"] == "AAPL"
        assert d["flow_event_ids"] == ["f1", "f2"]
        assert d["convergence_score"] == 77.8
        assert d["convergence_type"] == "amplified"
        assert d["signal_stance"] == "bearish"
        assert d["flow_direction"] == "bearish"
        assert d["net_flow_premium"] == -345678.12
        assert d["id"] == "c1"
        assert d["details"]["strength"] == "high"


# ── GreeksSnapshot ──


class TestGreeksSnapshot:
    """GreeksSnapshot frozen dataclass tests."""

    def test_create_valid_snapshot(self):
        g = GreeksSnapshot(
            delta=0.55, gamma=0.03, theta=-0.05,
            vega=0.12, rho=0.01, iv=0.35,
            underlying_price=150.0, strike=155.0,
            dte=30.0, option_type="call", timestamp=1700000000.0,
        )
        assert g.delta == 0.55
        assert g.gamma == 0.03
        assert g.iv == 0.35
        assert g.option_type == "call"

    def test_defaults(self):
        g = GreeksSnapshot(
            delta=0.5, gamma=0.02, theta=-0.03,
            vega=0.10, rho=0.005, iv=0.30,
        )
        assert g.underlying_price == 0.0
        assert g.strike == 0.0
        assert g.dte == 0.0
        assert g.option_type == "call"
        assert g.timestamp == 0.0

    def test_put_option_type(self):
        g = GreeksSnapshot(
            delta=-0.45, gamma=0.03, theta=-0.04,
            vega=0.11, rho=-0.008, iv=0.40,
            option_type="put",
        )
        assert g.option_type == "put"

    def test_frozen(self):
        g = GreeksSnapshot(
            delta=0.5, gamma=0.02, theta=-0.03,
            vega=0.10, rho=0.005, iv=0.30,
        )
        with pytest.raises(AttributeError):
            g.delta = 0.6  # type: ignore[misc]

    def test_to_dict_rounding(self):
        g = GreeksSnapshot(
            delta=0.55123456, gamma=0.03456789, theta=-0.05123456,
            vega=0.12345678, rho=0.01234567, iv=0.35678901,
            underlying_price=150.456, strike=155.789,
            dte=30.45, option_type="call", timestamp=1700000000.0,
        )
        d = g.to_dict()
        assert d["delta"] == 0.5512
        assert d["gamma"] == 0.034568
        assert d["theta"] == -0.0512
        assert d["vega"] == 0.1235
        assert d["rho"] == 0.0123
        assert d["iv"] == 0.3568
        assert d["underlying_price"] == 150.46
        assert d["strike"] == 155.79
        assert d["dte"] == 30.4
        assert d["option_type"] == "call"
        assert d["timestamp"] == 1700000000.0

    def test_negative_greeks(self):
        """Puts and short positions have negative delta/theta/rho."""
        g = GreeksSnapshot(
            delta=-0.45, gamma=0.03, theta=-0.08,
            vega=0.11, rho=-0.01, iv=0.50,
        )
        assert g.delta < 0
        assert g.theta < 0
        assert g.rho < 0


# ── FlowSummary ──


class TestFlowSummary:
    """FlowSummary frozen dataclass tests."""

    def test_create_valid_summary(self):
        s = FlowSummary(
            total_events=100,
            unique_tickers=25,
            total_premium=5000000.0,
            net_premium=1500000.0,
            avg_score=65.0,
            bullish_count=60,
            bearish_count=30,
            neutral_count=10,
        )
        assert s.total_events == 100
        assert s.unique_tickers == 25
        assert s.net_premium == 1500000.0

    def test_defaults(self):
        s = FlowSummary(
            total_events=0, unique_tickers=0, total_premium=0,
            net_premium=0, avg_score=0, bullish_count=0,
            bearish_count=0, neutral_count=0,
        )
        assert s.top_tickers == []
        assert s.type_breakdown == {}
        assert s.convergence_count == 0
        assert s.pattern_count == 0

    def test_dominant_direction_bullish(self):
        s = FlowSummary(
            total_events=50, unique_tickers=10, total_premium=1000000,
            net_premium=500000.0, avg_score=70.0,
            bullish_count=40, bearish_count=10, neutral_count=0,
        )
        assert s.dominant_direction == "bullish"

    def test_dominant_direction_bearish(self):
        s = FlowSummary(
            total_events=50, unique_tickers=10, total_premium=1000000,
            net_premium=-500000.0, avg_score=70.0,
            bullish_count=10, bearish_count=40, neutral_count=0,
        )
        assert s.dominant_direction == "bearish"

    def test_dominant_direction_neutral_small_premium(self):
        s = FlowSummary(
            total_events=20, unique_tickers=5, total_premium=80000,
            net_premium=10000.0, avg_score=40.0,
            bullish_count=12, bearish_count=8, neutral_count=0,
        )
        assert s.dominant_direction == "neutral"

    def test_dominant_direction_neutral_threshold(self):
        """Net premium exactly at $49999 is still neutral."""
        s = FlowSummary(
            total_events=10, unique_tickers=3, total_premium=100000,
            net_premium=49999.0, avg_score=50.0,
            bullish_count=6, bearish_count=4, neutral_count=0,
        )
        assert s.dominant_direction == "neutral"

    def test_dominant_direction_bullish_at_threshold(self):
        """Net premium exactly $50000 crosses into bullish."""
        s = FlowSummary(
            total_events=10, unique_tickers=3, total_premium=100000,
            net_premium=50000.0, avg_score=50.0,
            bullish_count=7, bearish_count=3, neutral_count=0,
        )
        assert s.dominant_direction == "bullish"

    def test_dominant_direction_bearish_at_neg_threshold(self):
        """Net premium exactly -$50000 crosses into bearish."""
        s = FlowSummary(
            total_events=10, unique_tickers=3, total_premium=100000,
            net_premium=-50000.0, avg_score=50.0,
            bullish_count=3, bearish_count=7, neutral_count=0,
        )
        assert s.dominant_direction == "bearish"

    def test_frozen(self):
        s = FlowSummary(
            total_events=0, unique_tickers=0, total_premium=0,
            net_premium=0, avg_score=0, bullish_count=0,
            bearish_count=0, neutral_count=0,
        )
        with pytest.raises(AttributeError):
            s.total_events = 5  # type: ignore[misc]

    def test_to_dict(self):
        s = FlowSummary(
            total_events=50,
            unique_tickers=12,
            total_premium=2345678.123,
            net_premium=987654.567,
            avg_score=68.789,
            bullish_count=30,
            bearish_count=15,
            neutral_count=5,
            top_tickers=[{"ticker": "TSLA", "count": 8, "premium": 500000}],
            type_breakdown={"sweep": 20, "block_trade": 15, "dark_pool": 15},
            convergence_count=7,
            pattern_count=3,
        )
        d = s.to_dict()
        assert d["total_events"] == 50
        assert d["unique_tickers"] == 12
        assert d["total_premium"] == 2345678.12
        assert d["net_premium"] == 987654.57
        assert d["avg_score"] == 68.8
        assert d["bullish_count"] == 30
        assert d["bearish_count"] == 15
        assert d["neutral_count"] == 5
        assert d["dominant_direction"] == "bullish"
        assert d["top_tickers"][0]["ticker"] == "TSLA"
        assert d["type_breakdown"]["sweep"] == 20
        assert d["convergence_count"] == 7
        assert d["pattern_count"] == 3

    def test_create_empty(self):
        s = FlowSummary(
            total_events=0, unique_tickers=0, total_premium=0.0,
            net_premium=0.0, avg_score=0.0,
            bullish_count=0, bearish_count=0, neutral_count=0,
        )
        assert s.total_events == 0
        assert s.dominant_direction == "neutral"


# ── Constants ──


class TestConstants:
    """Constant frozenset validation."""

    def test_flow_types_contents(self):
        expected = {"block_trade", "sweep", "dark_pool", "accumulation", "distribution"}
        assert FLOW_TYPES == expected

    def test_flow_directions_contents(self):
        expected = {"bullish", "bearish", "neutral"}
        assert FLOW_DIRECTIONS == expected

    def test_pattern_types_contents(self):
        expected = {
            "repeat_buyer", "accumulation_sequence",
            "hedging", "rolling", "cross_ticker",
        }
        assert PATTERN_TYPES == expected

    def test_convergence_types_contents(self):
        expected = {"aligned", "contradictory", "amplified"}
        assert CONVERGENCE_TYPES == expected

    def test_constants_are_frozensets(self):
        assert isinstance(FLOW_TYPES, frozenset)
        assert isinstance(FLOW_DIRECTIONS, frozenset)
        assert isinstance(PATTERN_TYPES, frozenset)
        assert isinstance(CONVERGENCE_TYPES, frozenset)
