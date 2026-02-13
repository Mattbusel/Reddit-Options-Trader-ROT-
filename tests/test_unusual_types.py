"""Tests for unusual activity data types."""

from __future__ import annotations

import pytest

from rot.unusual.types import EVENT_TYPES, UnusualEvent, UnusualScore, UnusualSummary


# ── UnusualEvent ──


class TestUnusualEvent:
    """UnusualEvent frozen dataclass tests."""

    def test_create_valid_event(self):
        e = UnusualEvent(
            ticker="TSLA",
            event_type="iv_spike",
            score=85.0,
            details={"atm_iv": 0.72, "iv_rank": 92.0},
            detected_at=1700000000.0,
            signal_id="sig-001",
        )
        assert e.ticker == "TSLA"
        assert e.event_type == "iv_spike"
        assert e.score == 85.0
        assert e.signal_id == "sig-001"

    def test_create_all_event_types(self):
        for etype in EVENT_TYPES:
            e = UnusualEvent(
                ticker="SPY", event_type=etype, score=50.0,
                details={}, detected_at=1.0,
            )
            assert e.event_type == etype

    def test_invalid_event_type_raises(self):
        with pytest.raises(ValueError, match="Invalid event_type"):
            UnusualEvent(
                ticker="SPY", event_type="bad_type", score=50.0,
                details={}, detected_at=1.0,
            )

    def test_score_below_zero_raises(self):
        with pytest.raises(ValueError, match="Score must be 0-100"):
            UnusualEvent(
                ticker="SPY", event_type="iv_spike", score=-1.0,
                details={}, detected_at=1.0,
            )

    def test_score_above_100_raises(self):
        with pytest.raises(ValueError, match="Score must be 0-100"):
            UnusualEvent(
                ticker="SPY", event_type="iv_spike", score=101.0,
                details={}, detected_at=1.0,
            )

    def test_score_edge_zero(self):
        e = UnusualEvent(
            ticker="SPY", event_type="iv_spike", score=0.0,
            details={}, detected_at=1.0,
        )
        assert e.score == 0.0

    def test_score_edge_100(self):
        e = UnusualEvent(
            ticker="SPY", event_type="iv_spike", score=100.0,
            details={}, detected_at=1.0,
        )
        assert e.score == 100.0

    def test_signal_id_optional(self):
        e = UnusualEvent(
            ticker="SPY", event_type="iv_spike", score=50.0,
            details={}, detected_at=1.0,
        )
        assert e.signal_id is None

    def test_frozen(self):
        e = UnusualEvent(
            ticker="SPY", event_type="iv_spike", score=50.0,
            details={}, detected_at=1.0,
        )
        with pytest.raises(AttributeError):
            e.score = 60.0  # type: ignore[misc]

    def test_to_dict(self):
        e = UnusualEvent(
            ticker="AAPL", event_type="volume_surge", score=72.3,
            details={"volume": 1000}, detected_at=1700000000.0, signal_id="s1",
        )
        d = e.to_dict()
        assert d["ticker"] == "AAPL"
        assert d["event_type"] == "volume_surge"
        assert d["score"] == 72.3
        assert d["details"]["volume"] == 1000
        assert d["signal_id"] == "s1"

    def test_to_dict_rounds_score(self):
        e = UnusualEvent(
            ticker="SPY", event_type="sweep", score=55.555,
            details={}, detected_at=1.0,
        )
        d = e.to_dict()
        assert d["score"] == 55.6


# ── UnusualScore ──


class TestUnusualScore:
    """UnusualScore composite score tests."""

    def test_create_valid_score(self):
        s = UnusualScore(
            composite_score=75.0,
            flags=["High IV", "Volume Spike"],
            component_scores={"iv_spike": 85.0, "volume_surge": 65.0},
        )
        assert s.composite_score == 75.0
        assert s.flag_count == 2
        assert s.is_unusual is True

    def test_zero_score_empty_flags(self):
        s = UnusualScore(
            composite_score=0.0, flags=[], component_scores={},
        )
        assert s.flag_count == 0
        assert s.is_unusual is False

    def test_score_above_100_raises(self):
        with pytest.raises(ValueError, match="Composite score must be 0-100"):
            UnusualScore(composite_score=101.0, flags=[], component_scores={})

    def test_score_below_zero_raises(self):
        with pytest.raises(ValueError, match="Composite score must be 0-100"):
            UnusualScore(composite_score=-5.0, flags=[], component_scores={})

    def test_is_unusual_requires_both(self):
        # Score>0 but no flags → not unusual
        s = UnusualScore(
            composite_score=50.0, flags=[], component_scores={},
        )
        assert s.is_unusual is False

    def test_to_dict(self):
        s = UnusualScore(
            composite_score=80.5,
            flags=["High IV"],
            component_scores={"iv_spike": 80.5},
            events=[
                UnusualEvent(
                    ticker="SPY", event_type="iv_spike", score=80.5,
                    details={}, detected_at=1.0,
                )
            ],
        )
        d = s.to_dict()
        assert d["composite_score"] == 80.5
        assert d["event_count"] == 1
        assert "High IV" in d["flags"]

    def test_frozen(self):
        s = UnusualScore(composite_score=50.0, flags=[], component_scores={})
        with pytest.raises(AttributeError):
            s.composite_score = 60.0  # type: ignore[misc]


# ── UnusualSummary ──


class TestUnusualSummary:
    """UnusualSummary aggregate tests."""

    def test_create_empty(self):
        s = UnusualSummary(
            total_events=0, unique_tickers=0, avg_score=0.0,
            top_tickers=[], type_breakdown={},
        )
        assert s.total_events == 0

    def test_create_populated(self):
        highest = UnusualEvent(
            ticker="NVDA", event_type="iv_spike", score=95.0,
            details={}, detected_at=1.0,
        )
        s = UnusualSummary(
            total_events=10,
            unique_tickers=5,
            avg_score=65.0,
            top_tickers=[{"ticker": "NVDA", "count": 3, "avg_score": 80.0}],
            type_breakdown={"iv_spike": 5, "volume_surge": 3, "sweep": 2},
            highest_score_event=highest,
        )
        assert s.total_events == 10
        assert s.unique_tickers == 5
        assert s.highest_score_event is not None

    def test_to_dict(self):
        s = UnusualSummary(
            total_events=5, unique_tickers=3, avg_score=55.123,
            top_tickers=[{"ticker": "AAPL", "count": 2, "avg_score": 60.0}],
            type_breakdown={"iv_spike": 3, "sweep": 2},
        )
        d = s.to_dict()
        assert d["total_events"] == 5
        assert d["avg_score"] == 55.1
        assert d["highest_score"] is None

    def test_to_dict_with_highest(self):
        highest = UnusualEvent(
            ticker="AAPL", event_type="volume_surge", score=90.0,
            details={"volume": 5000}, detected_at=1.0,
        )
        s = UnusualSummary(
            total_events=1, unique_tickers=1, avg_score=90.0,
            top_tickers=[], type_breakdown={"volume_surge": 1},
            highest_score_event=highest,
        )
        d = s.to_dict()
        assert d["highest_score"]["ticker"] == "AAPL"
        assert d["highest_score"]["score"] == 90.0

    def test_frozen(self):
        s = UnusualSummary(
            total_events=0, unique_tickers=0, avg_score=0.0,
            top_tickers=[], type_breakdown={},
        )
        with pytest.raises(AttributeError):
            s.total_events = 5  # type: ignore[misc]
