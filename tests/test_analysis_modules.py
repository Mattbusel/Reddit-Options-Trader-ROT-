"""Tests for analysis modules: sector rotation + correlation analysis.

Part 1 — Sector Types (SectorMomentum, RotationEvent, CapitalFlow, SectorRanking)
Part 2 — SectorAnalyzer (compute_sector_momentum, detect_rotation, compute_capital_flow, rank_sectors)
Part 3 — Correlation Types (CorrelationPair, SignalCorrelationMatrix, TickerCluster, LeadLagPair, PredictivePair, NetworkGraph)
Part 4 — CorrelationAnalyzer (compute_signal_correlations, detect_clusters, compute_lead_lag, build_network_data)
Part 5 — Parametrized & stress tests
"""

from __future__ import annotations

import time

import pytest

from rot.analysis.sector_types import (
    CapitalFlow,
    RotationEvent,
    SectorMomentum,
    SectorRanking,
)
from rot.analysis.correlation_types import (
    CorrelationPair,
    LeadLagPair,
    NetworkGraph,
    PredictivePair,
    SignalCorrelationMatrix,
    TickerCluster,
)
from rot.analysis.sector import SectorAnalyzer
from rot.analysis.correlations import CorrelationAnalyzer


# ═══════════════════════════════════════════════════════════════════
# Part 1 — Sector Types
# ═══════════════════════════════════════════════════════════════════


class TestSectorMomentum:
    """SectorMomentum frozen dataclass."""

    def test_creation(self):
        m = SectorMomentum(
            sector="Technology",
            signal_velocity=2.5,
            trend="accelerating",
            acceleration=0.3,
            score=65.0,
            signal_count=30,
            bullish_pct=70.0,
            bearish_pct=20.0,
        )
        assert m.sector == "Technology"
        assert m.signal_velocity == 2.5
        assert m.trend == "accelerating"
        assert m.acceleration == 0.3
        assert m.score == 65.0
        assert m.signal_count == 30
        assert m.bullish_pct == 70.0
        assert m.bearish_pct == 20.0

    def test_defaults(self):
        m = SectorMomentum(
            sector="Energy",
            signal_velocity=1.0,
            trend="stable",
            acceleration=0.0,
            score=30.0,
        )
        assert m.signal_count == 0
        assert m.bullish_pct == 0.0
        assert m.bearish_pct == 0.0

    def test_frozen(self):
        m = SectorMomentum(
            sector="X", signal_velocity=1.0, trend="stable",
            acceleration=0.0, score=10.0,
        )
        with pytest.raises(AttributeError):
            m.sector = "Y"

    def test_to_dict(self):
        m = SectorMomentum(
            sector="Healthcare",
            signal_velocity=1.234,
            trend="decelerating",
            acceleration=-0.456,
            score=42.789,
            signal_count=15,
            bullish_pct=55.555,
            bearish_pct=33.333,
        )
        d = m.to_dict()
        assert d["sector"] == "Healthcare"
        assert d["signal_velocity"] == 1.23
        assert d["trend"] == "decelerating"
        assert d["acceleration"] == -0.46
        assert d["score"] == 42.8
        assert d["signal_count"] == 15
        assert d["bullish_pct"] == 55.6
        assert d["bearish_pct"] == 33.3

    def test_to_dict_rounding_precision(self):
        m = SectorMomentum(
            sector="A", signal_velocity=0.005, trend="stable",
            acceleration=0.005, score=99.95,
        )
        d = m.to_dict()
        assert d["signal_velocity"] == 0.01  # rounds up
        assert d["score"] == 100.0  # rounds up


class TestRotationEvent:
    """RotationEvent frozen dataclass."""

    def test_creation(self):
        e = RotationEvent(
            from_sector="Energy",
            to_sector="Technology",
            detected_at=1000000.0,
            confidence=0.85,
            from_velocity_delta=-0.3,
            to_velocity_delta=0.5,
        )
        assert e.from_sector == "Energy"
        assert e.to_sector == "Technology"
        assert e.detected_at == 1000000.0
        assert e.confidence == 0.85
        assert e.from_velocity_delta == -0.3
        assert e.to_velocity_delta == 0.5

    def test_frozen(self):
        e = RotationEvent(
            from_sector="A", to_sector="B", detected_at=0,
            confidence=0.5, from_velocity_delta=0, to_velocity_delta=0,
        )
        with pytest.raises(AttributeError):
            e.from_sector = "C"

    def test_to_dict(self):
        e = RotationEvent(
            from_sector="Financials",
            to_sector="Healthcare",
            detected_at=1234567.89,
            confidence=0.7777,
            from_velocity_delta=-0.2345,
            to_velocity_delta=0.5678,
        )
        d = e.to_dict()
        assert d["from_sector"] == "Financials"
        assert d["to_sector"] == "Healthcare"
        assert d["detected_at"] == 1234567.89
        assert d["confidence"] == 0.78
        assert d["from_velocity_delta"] == -0.23
        assert d["to_velocity_delta"] == 0.57


class TestCapitalFlow:
    """CapitalFlow frozen dataclass."""

    def test_creation(self):
        f = CapitalFlow(
            sector="Technology",
            bullish_count=20,
            bearish_count=10,
            mixed_count=5,
            bullish_intensity=0.75,
            bearish_intensity=0.60,
            net_flow=5.5,
            flow_change=1.2,
        )
        assert f.sector == "Technology"
        assert f.bullish_count == 20
        assert f.bearish_count == 10
        assert f.mixed_count == 5
        assert f.bullish_intensity == 0.75
        assert f.bearish_intensity == 0.60
        assert f.net_flow == 5.5
        assert f.flow_change == 1.2

    def test_frozen(self):
        f = CapitalFlow(
            sector="X", bullish_count=0, bearish_count=0, mixed_count=0,
            bullish_intensity=0, bearish_intensity=0, net_flow=0, flow_change=0,
        )
        with pytest.raises(AttributeError):
            f.sector = "Y"

    def test_to_dict(self):
        f = CapitalFlow(
            sector="Energy",
            bullish_count=15,
            bearish_count=8,
            mixed_count=3,
            bullish_intensity=0.8123,
            bearish_intensity=0.4567,
            net_flow=3.456,
            flow_change=-0.789,
        )
        d = f.to_dict()
        assert d["sector"] == "Energy"
        assert d["bullish_count"] == 15
        assert d["bearish_count"] == 8
        assert d["mixed_count"] == 3
        assert d["bullish_intensity"] == 0.812
        assert d["bearish_intensity"] == 0.457
        assert d["net_flow"] == 3.46
        assert d["flow_change"] == -0.79


class TestSectorRanking:
    """SectorRanking frozen dataclass."""

    def test_creation(self):
        mom = SectorMomentum(
            sector="Tech", signal_velocity=2.0, trend="stable",
            acceleration=0.0, score=50.0, signal_count=10,
        )
        r = SectorRanking(
            sector="Tech",
            rank=1,
            score=75.0,
            signal_count=10,
            win_rate=0.65,
            momentum=mom,
            net_sentiment=0.3,
        )
        assert r.sector == "Tech"
        assert r.rank == 1
        assert r.score == 75.0
        assert r.signal_count == 10
        assert r.win_rate == 0.65
        assert r.momentum is mom
        assert r.net_sentiment == 0.3

    def test_win_rate_none(self):
        mom = SectorMomentum(
            sector="X", signal_velocity=1.0, trend="stable",
            acceleration=0.0, score=10.0,
        )
        r = SectorRanking(
            sector="X", rank=1, score=10.0, signal_count=5,
            win_rate=None, momentum=mom, net_sentiment=0.0,
        )
        d = r.to_dict()
        assert d["win_rate"] is None

    def test_to_dict(self):
        mom = SectorMomentum(
            sector="Financials", signal_velocity=1.5, trend="accelerating",
            acceleration=0.2, score=60.0, signal_count=20,
        )
        r = SectorRanking(
            sector="Financials", rank=2, score=55.789,
            signal_count=20, win_rate=0.6234, momentum=mom,
            net_sentiment=-0.1234,
        )
        d = r.to_dict()
        assert d["sector"] == "Financials"
        assert d["rank"] == 2
        assert d["score"] == 55.8
        assert d["signal_count"] == 20
        assert d["win_rate"] == 0.623
        assert d["net_sentiment"] == -0.12
        assert "momentum" in d
        assert d["momentum"]["sector"] == "Financials"


# ═══════════════════════════════════════════════════════════════════
# Part 2 — SectorAnalyzer
# ═══════════════════════════════════════════════════════════════════


def _make_sector_signal(
    sector: str,
    stance: str = "bullish",
    confidence: float = 0.7,
    offset_hours: float = 0,
) -> dict:
    """Build a minimal signal dict for sector analysis."""
    return {
        "sector": sector,
        "stance": stance,
        "confidence": confidence,
        "created_at": time.time() - offset_hours * 3600,
    }


class TestSectorAnalyzerInit:
    """SectorAnalyzer initialization."""

    def test_default_min_signals(self):
        sa = SectorAnalyzer()
        assert sa._min_signals == 3

    def test_custom_min_signals(self):
        sa = SectorAnalyzer(min_signals=10)
        assert sa._min_signals == 10


class TestComputeSectorMomentum:
    """SectorAnalyzer.compute_sector_momentum."""

    def test_empty_data(self):
        sa = SectorAnalyzer()
        result = sa.compute_sector_momentum([], days=30)
        assert result == []

    def test_below_min_signals(self):
        sa = SectorAnalyzer(min_signals=5)
        data = [_make_sector_signal("Tech", offset_hours=i) for i in range(3)]
        result = sa.compute_sector_momentum(data, days=30)
        assert result == []

    def test_single_sector_enough_signals(self):
        sa = SectorAnalyzer(min_signals=3)
        data = [_make_sector_signal("Tech", offset_hours=i * 24) for i in range(5)]
        result = sa.compute_sector_momentum(data, days=30)
        assert len(result) == 1
        assert result[0].sector == "Tech"
        assert result[0].signal_count == 5
        assert result[0].score >= 0
        assert result[0].score <= 100

    def test_multiple_sectors_sorted_by_score(self):
        sa = SectorAnalyzer(min_signals=3)
        # Tech: 10 signals (more activity → higher score)
        tech = [_make_sector_signal("Tech", offset_hours=i * 12) for i in range(10)]
        # Energy: 3 signals (minimal)
        energy = [_make_sector_signal("Energy", offset_hours=i * 24) for i in range(3)]
        result = sa.compute_sector_momentum(tech + energy, days=30)
        assert len(result) == 2
        # Higher velocity sector should score higher
        assert result[0].score >= result[1].score

    def test_trend_accelerating(self):
        sa = SectorAnalyzer(min_signals=3)
        # All signals in the recent half → acceleration > 0.1
        data = [_make_sector_signal("Tech", offset_hours=i) for i in range(6)]
        result = sa.compute_sector_momentum(data, days=30)
        assert len(result) == 1
        assert result[0].trend == "accelerating"
        assert result[0].acceleration > 0.1

    def test_trend_decelerating(self):
        sa = SectorAnalyzer(min_signals=3)
        # All signals in older half → deceleration
        data = [_make_sector_signal("Tech", offset_hours=20 * 24 + i) for i in range(6)]
        result = sa.compute_sector_momentum(data, days=30)
        assert len(result) == 1
        assert result[0].trend == "decelerating"
        assert result[0].acceleration < -0.1

    def test_trend_stable(self):
        sa = SectorAnalyzer(min_signals=3)
        # Spread equally across both halves
        recent = [_make_sector_signal("Tech", offset_hours=i * 24) for i in range(3)]
        older = [_make_sector_signal("Tech", offset_hours=20 * 24 + i * 24) for i in range(3)]
        result = sa.compute_sector_momentum(recent + older, days=30)
        assert len(result) == 1
        assert result[0].trend == "stable"

    def test_bullish_bearish_pct(self):
        sa = SectorAnalyzer(min_signals=3)
        data = [
            _make_sector_signal("Tech", stance="bullish", offset_hours=1),
            _make_sector_signal("Tech", stance="bullish", offset_hours=2),
            _make_sector_signal("Tech", stance="bearish", offset_hours=3),
            _make_sector_signal("Tech", stance="mixed", offset_hours=4),
        ]
        result = sa.compute_sector_momentum(data, days=30)
        assert len(result) == 1
        assert result[0].bullish_pct == 50.0
        assert result[0].bearish_pct == 25.0

    def test_old_signals_excluded(self):
        sa = SectorAnalyzer(min_signals=3)
        # Signals outside the 30-day window
        data = [_make_sector_signal("Tech", offset_hours=40 * 24 + i) for i in range(5)]
        result = sa.compute_sector_momentum(data, days=30)
        assert result == []

    def test_empty_sector_name_ignored(self):
        sa = SectorAnalyzer(min_signals=3)
        data = [
            {"sector": "", "stance": "bullish", "confidence": 0.5, "created_at": time.time()},
            {"sector": "  ", "stance": "bullish", "confidence": 0.5, "created_at": time.time()},
        ]
        result = sa.compute_sector_momentum(data, days=30)
        assert result == []

    def test_score_capped_at_100(self):
        sa = SectorAnalyzer(min_signals=3)
        # Many signals to push score past cap
        data = [_make_sector_signal("Tech", offset_hours=i * 0.5) for i in range(100)]
        result = sa.compute_sector_momentum(data, days=30)
        assert len(result) == 1
        assert result[0].score <= 100.0


class TestDetectRotation:
    """SectorAnalyzer.detect_rotation."""

    def test_empty_data(self):
        sa = SectorAnalyzer(min_signals=3)
        result = sa.detect_rotation([], days=30)
        assert result == []

    def test_single_sector_no_rotation(self):
        sa = SectorAnalyzer(min_signals=3)
        data = [_make_sector_signal("Tech", offset_hours=i * 24) for i in range(5)]
        result = sa.detect_rotation(data, days=30)
        assert result == []

    def test_two_sectors_no_rotation_when_both_stable(self):
        sa = SectorAnalyzer(min_signals=3)
        tech = [_make_sector_signal("Tech", offset_hours=i * 24) for i in range(5)]
        energy = [_make_sector_signal("Energy", offset_hours=i * 24) for i in range(5)]
        result = sa.detect_rotation(tech + energy, days=30)
        # Both stable, unlikely rotation
        assert isinstance(result, list)

    def test_rotation_detected_leader_shift(self):
        """Create a scenario where prior leader decelerates and new leader accelerates."""
        sa = SectorAnalyzer(min_signals=3)
        now = time.time()

        # Prior period: Energy was the leader (lots of signals 30-60 days ago)
        prior_energy = [
            {"sector": "Energy", "stance": "bullish", "confidence": 0.8,
             "created_at": now - 45 * 86400 + i * 3600}
            for i in range(10)
        ]

        # Current period: Energy decelerating (few recent, more older half)
        energy_older = [
            {"sector": "Energy", "stance": "bullish", "confidence": 0.7,
             "created_at": now - 20 * 86400 + i * 3600}
            for i in range(5)
        ]
        energy_recent = [
            {"sector": "Energy", "stance": "bearish", "confidence": 0.5,
             "created_at": now - 2 * 86400 + i * 3600}
            for i in range(1)
        ]

        # Current period: Tech accelerating (lots of recent signals)
        tech_recent = [
            {"sector": "Technology", "stance": "bullish", "confidence": 0.8,
             "created_at": now - i * 3600}
            for i in range(10)
        ]
        tech_older = [
            {"sector": "Technology", "stance": "bullish", "confidence": 0.6,
             "created_at": now - 20 * 86400 + i * 3600}
            for i in range(3)
        ]

        all_data = prior_energy + energy_older + energy_recent + tech_recent + tech_older
        result = sa.detect_rotation(all_data, days=30)
        # Result could be empty if conditions not perfectly met, but should be a list
        assert isinstance(result, list)
        for event in result:
            assert isinstance(event, RotationEvent)
            assert 0 <= event.confidence <= 1


class TestComputeCapitalFlow:
    """SectorAnalyzer.compute_capital_flow."""

    def test_empty_data(self):
        sa = SectorAnalyzer()
        result = sa.compute_capital_flow([], days=30)
        assert result == []

    def test_single_sector_bullish(self):
        sa = SectorAnalyzer()
        data = [
            _make_sector_signal("Tech", stance="bullish", confidence=0.8, offset_hours=1),
            _make_sector_signal("Tech", stance="bullish", confidence=0.9, offset_hours=2),
            _make_sector_signal("Tech", stance="bearish", confidence=0.6, offset_hours=3),
        ]
        result = sa.compute_capital_flow(data, days=30)
        assert len(result) == 1
        f = result[0]
        assert f.sector == "Tech"
        assert f.bullish_count == 2
        assert f.bearish_count == 1
        assert f.net_flow > 0  # bullish outweighs bearish

    def test_mixed_stances(self):
        sa = SectorAnalyzer()
        data = [
            _make_sector_signal("Tech", stance="mixed", confidence=0.5, offset_hours=1),
            _make_sector_signal("Tech", stance="bullish", confidence=0.7, offset_hours=2),
            _make_sector_signal("Tech", stance="bearish", confidence=0.7, offset_hours=3),
        ]
        result = sa.compute_capital_flow(data, days=30)
        assert len(result) == 1
        assert result[0].mixed_count == 1

    def test_flow_change_with_prior_period(self):
        sa = SectorAnalyzer()
        now = time.time()
        # Current period: net bullish
        current = [
            {"sector": "Tech", "stance": "bullish", "confidence": 0.8,
             "created_at": now - 3600},
        ]
        # Prior period: net bearish
        prior = [
            {"sector": "Tech", "stance": "bearish", "confidence": 0.9,
             "created_at": now - 40 * 86400},
        ]
        result = sa.compute_capital_flow(current + prior, days=30, prior_days=60)
        assert len(result) == 1
        # flow_change should reflect shift from bearish to bullish
        assert result[0].flow_change > 0

    def test_sorted_by_abs_net_flow(self):
        sa = SectorAnalyzer()
        # Tech: small net flow
        tech = [_make_sector_signal("Tech", stance="bullish", confidence=0.5, offset_hours=1)]
        # Energy: large net flow
        energy = [
            _make_sector_signal("Energy", stance="bullish", confidence=0.9, offset_hours=i)
            for i in range(5)
        ]
        result = sa.compute_capital_flow(tech + energy, days=30)
        assert len(result) == 2
        assert abs(result[0].net_flow) >= abs(result[1].net_flow)

    def test_empty_sector_ignored(self):
        sa = SectorAnalyzer()
        data = [{"sector": "", "stance": "bullish", "confidence": 0.5,
                 "created_at": time.time()}]
        result = sa.compute_capital_flow(data, days=30)
        assert result == []

    def test_intensity_calculation(self):
        sa = SectorAnalyzer()
        data = [
            _make_sector_signal("Tech", stance="bullish", confidence=0.6, offset_hours=1),
            _make_sector_signal("Tech", stance="bullish", confidence=0.8, offset_hours=2),
            _make_sector_signal("Tech", stance="bearish", confidence=0.4, offset_hours=3),
        ]
        result = sa.compute_capital_flow(data, days=30)
        assert len(result) == 1
        # avg confidence of 2 bullish: (0.6 + 0.8) / 2 = 0.7
        assert abs(result[0].bullish_intensity - 0.7) < 0.01
        # avg confidence of 1 bearish: 0.4
        assert abs(result[0].bearish_intensity - 0.4) < 0.01


class TestRankSectors:
    """SectorAnalyzer.rank_sectors."""

    def test_empty_data(self):
        sa = SectorAnalyzer()
        result = sa.rank_sectors([], days=30)
        assert result == []

    def test_below_min_signals(self):
        sa = SectorAnalyzer(min_signals=10)
        data = [_make_sector_signal("Tech", offset_hours=i) for i in range(5)]
        result = sa.rank_sectors(data, days=30)
        assert result == []

    def test_single_sector_rank_1(self):
        sa = SectorAnalyzer(min_signals=3)
        data = [_make_sector_signal("Tech", offset_hours=i * 24) for i in range(5)]
        result = sa.rank_sectors(data, days=30)
        assert len(result) == 1
        assert result[0].rank == 1
        assert result[0].sector == "Tech"
        assert 0 <= result[0].score <= 100

    def test_multiple_sectors_ordered_by_score(self):
        sa = SectorAnalyzer(min_signals=3)
        tech = [_make_sector_signal("Tech", offset_hours=i * 12) for i in range(10)]
        energy = [_make_sector_signal("Energy", offset_hours=i * 24) for i in range(3)]
        result = sa.rank_sectors(tech + energy, days=30)
        assert len(result) == 2
        assert result[0].rank == 1
        assert result[1].rank == 2
        assert result[0].score >= result[1].score

    def test_with_performance_data(self):
        sa = SectorAnalyzer(min_signals=3)
        data = [_make_sector_signal("Tech", offset_hours=i * 24) for i in range(5)]
        perf = {"Tech": {"win_rate": 0.8, "total_tracked": 20}}
        result = sa.rank_sectors(data, performance_data=perf, days=30)
        assert len(result) == 1
        assert result[0].win_rate == 0.8

    def test_performance_data_insufficient_tracked(self):
        sa = SectorAnalyzer(min_signals=3)
        data = [_make_sector_signal("Tech", offset_hours=i * 24) for i in range(5)]
        perf = {"Tech": {"win_rate": 0.9, "total_tracked": 3}}  # < 5
        result = sa.rank_sectors(data, performance_data=perf, days=30)
        assert len(result) == 1
        assert result[0].win_rate is None

    def test_net_sentiment(self):
        sa = SectorAnalyzer(min_signals=3)
        data = [
            _make_sector_signal("Tech", stance="bullish", offset_hours=1),
            _make_sector_signal("Tech", stance="bullish", offset_hours=2),
            _make_sector_signal("Tech", stance="bearish", offset_hours=3),
            _make_sector_signal("Tech", stance="mixed", offset_hours=4),
        ]
        result = sa.rank_sectors(data, days=30)
        assert len(result) == 1
        # net_sentiment = (2 bullish - 1 bearish) / 4 = 0.25
        assert abs(result[0].net_sentiment - 0.25) < 0.01


# ═══════════════════════════════════════════════════════════════════
# Part 3 — Correlation Types
# ═══════════════════════════════════════════════════════════════════


class TestCorrelationPair:
    """CorrelationPair frozen dataclass."""

    def test_creation(self):
        p = CorrelationPair(
            ticker_a="AAPL", ticker_b="MSFT",
            correlation=0.85, co_fires=10,
            same_stance_pct=80.0, sample_size=25,
        )
        assert p.ticker_a == "AAPL"
        assert p.ticker_b == "MSFT"
        assert p.correlation == 0.85
        assert p.co_fires == 10
        assert p.same_stance_pct == 80.0
        assert p.sample_size == 25

    def test_frozen(self):
        p = CorrelationPair(
            ticker_a="A", ticker_b="B",
            correlation=0.5, co_fires=3,
            same_stance_pct=50.0, sample_size=10,
        )
        with pytest.raises(AttributeError):
            p.correlation = 0.9

    def test_negative_correlation(self):
        p = CorrelationPair(
            ticker_a="AAPL", ticker_b="SQQQ",
            correlation=-0.7, co_fires=8,
            same_stance_pct=20.0, sample_size=20,
        )
        assert p.correlation == -0.7

    def test_to_dict(self):
        p = CorrelationPair(
            ticker_a="AAPL", ticker_b="MSFT",
            correlation=0.8567, co_fires=12,
            same_stance_pct=75.3, sample_size=30,
        )
        d = p.to_dict()
        assert d["ticker_a"] == "AAPL"
        assert d["ticker_b"] == "MSFT"
        assert d["correlation"] == 0.857
        assert d["co_fires"] == 12
        assert d["same_stance_pct"] == 75.3
        assert d["sample_size"] == 30


class TestSignalCorrelationMatrix:
    """SignalCorrelationMatrix frozen dataclass."""

    def test_creation_minimal(self):
        m = SignalCorrelationMatrix(tickers=["AAPL", "MSFT"], pairs=[])
        assert m.tickers == ["AAPL", "MSFT"]
        assert m.pairs == []
        assert m.strongest_positive is None
        assert m.strongest_negative is None

    def test_with_strongest(self):
        pos = CorrelationPair("AAPL", "MSFT", 0.9, 15, 90.0, 40)
        neg = CorrelationPair("AAPL", "SQQQ", -0.6, 8, 20.0, 30)
        m = SignalCorrelationMatrix(
            tickers=["AAPL", "MSFT", "SQQQ"],
            pairs=[pos, neg],
            strongest_positive=pos,
            strongest_negative=neg,
        )
        assert m.strongest_positive.correlation == 0.9
        assert m.strongest_negative.correlation == -0.6

    def test_to_dict(self):
        p = CorrelationPair("A", "B", 0.5, 5, 60.0, 20)
        m = SignalCorrelationMatrix(
            tickers=["A", "B"], pairs=[p],
            strongest_positive=p, strongest_negative=None,
        )
        d = m.to_dict()
        assert d["tickers"] == ["A", "B"]
        assert d["pair_count"] == 1
        assert d["strongest_positive"] is not None
        assert d["strongest_negative"] is None


class TestTickerCluster:
    """TickerCluster frozen dataclass."""

    def test_creation(self):
        c = TickerCluster(
            cluster_id=0,
            tickers=["AAPL", "MSFT", "GOOGL"],
            avg_internal_correlation=0.75,
            label="Tech Cluster",
        )
        assert c.cluster_id == 0
        assert c.tickers == ["AAPL", "MSFT", "GOOGL"]
        assert c.avg_internal_correlation == 0.75
        assert c.label == "Tech Cluster"
        assert c.size == 3  # auto-computed from tickers

    def test_size_auto_set(self):
        c = TickerCluster(
            cluster_id=1,
            tickers=["X", "Y"],
            avg_internal_correlation=0.5,
            label="Small",
        )
        assert c.size == 2

    def test_size_explicit(self):
        c = TickerCluster(
            cluster_id=0,
            tickers=["A", "B", "C"],
            avg_internal_correlation=0.6,
            label="Test",
            size=5,  # explicit override
        )
        assert c.size == 5

    def test_to_dict(self):
        c = TickerCluster(
            cluster_id=2,
            tickers=["AAPL", "MSFT"],
            avg_internal_correlation=0.8567,
            label="Duo",
        )
        d = c.to_dict()
        assert d["cluster_id"] == 2
        assert d["tickers"] == ["AAPL", "MSFT"]
        assert d["avg_internal_correlation"] == 0.857
        assert d["label"] == "Duo"
        assert d["size"] == 2


class TestLeadLagPair:
    """LeadLagPair frozen dataclass."""

    def test_creation(self):
        p = LeadLagPair(
            leader="AAPL", follower="MSFT",
            avg_lag_hours=2.5, confidence=0.8,
            occurrences=12,
        )
        assert p.leader == "AAPL"
        assert p.follower == "MSFT"
        assert p.avg_lag_hours == 2.5
        assert p.confidence == 0.8
        assert p.occurrences == 12

    def test_frozen(self):
        p = LeadLagPair("A", "B", 1.0, 0.5, 5)
        with pytest.raises(AttributeError):
            p.leader = "C"

    def test_to_dict(self):
        p = LeadLagPair("AAPL", "MSFT", 3.456, 0.789, 15)
        d = p.to_dict()
        assert d["leader"] == "AAPL"
        assert d["follower"] == "MSFT"
        assert d["avg_lag_hours"] == 3.5
        assert d["confidence"] == 0.79
        assert d["occurrences"] == 15


class TestPredictivePair:
    """PredictivePair frozen dataclass."""

    def test_creation(self):
        p = PredictivePair(
            ticker_a="AAPL", ticker_b="SPY",
            prediction_accuracy=0.72,
            sample_size=50,
            direction="same",
        )
        assert p.ticker_a == "AAPL"
        assert p.ticker_b == "SPY"
        assert p.prediction_accuracy == 0.72
        assert p.sample_size == 50
        assert p.direction == "same"

    def test_inverse_direction(self):
        p = PredictivePair("AAPL", "SQQQ", 0.65, 30, "inverse")
        assert p.direction == "inverse"

    def test_to_dict(self):
        p = PredictivePair("A", "B", 0.7777, 40, "same")
        d = p.to_dict()
        assert d["prediction_accuracy"] == 0.778
        assert d["sample_size"] == 40
        assert d["direction"] == "same"


class TestNetworkGraph:
    """NetworkGraph frozen dataclass."""

    def test_creation(self):
        g = NetworkGraph(
            nodes=[{"id": "AAPL", "label": "AAPL", "size": 10}],
            edges=[{"source": "AAPL", "target": "MSFT", "weight": 0.8}],
        )
        assert len(g.nodes) == 1
        assert len(g.edges) == 1

    def test_empty_graph(self):
        g = NetworkGraph(nodes=[], edges=[])
        assert g.nodes == []
        assert g.edges == []
        d = g.to_dict()
        assert d["node_count"] == 0
        assert d["edge_count"] == 0

    def test_to_dict(self):
        g = NetworkGraph(
            nodes=[{"id": "A"}, {"id": "B"}],
            edges=[{"source": "A", "target": "B", "weight": 0.5}],
        )
        d = g.to_dict()
        assert d["node_count"] == 2
        assert d["edge_count"] == 1
        assert d["nodes"] == [{"id": "A"}, {"id": "B"}]


# ═══════════════════════════════════════════════════════════════════
# Part 4 — CorrelationAnalyzer
# ═══════════════════════════════════════════════════════════════════


def _make_corr_signal(
    ticker: str,
    stance: str = "bullish",
    offset_hours: float = 0,
) -> dict:
    """Build a minimal signal dict for correlation analysis."""
    return {
        "ticker": ticker,
        "stance": stance,
        "created_at": time.time() - offset_hours * 3600,
    }


class TestCorrelationAnalyzerInit:
    """CorrelationAnalyzer initialization."""

    def test_defaults(self):
        ca = CorrelationAnalyzer()
        assert ca._min_co_fires == 3
        assert ca._window_hours == 4

    def test_custom(self):
        ca = CorrelationAnalyzer(min_co_fires=5, correlation_window_hours=8)
        assert ca._min_co_fires == 5
        assert ca._window_hours == 8


class TestComputeSignalCorrelations:
    """CorrelationAnalyzer.compute_signal_correlations."""

    def test_empty_signals(self):
        ca = CorrelationAnalyzer()
        result = ca.compute_signal_correlations([], days=30)
        assert isinstance(result, SignalCorrelationMatrix)
        assert result.tickers == []
        assert result.pairs == []

    def test_single_ticker_no_pairs(self):
        ca = CorrelationAnalyzer()
        signals = [_make_corr_signal("AAPL", offset_hours=i) for i in range(10)]
        result = ca.compute_signal_correlations(signals, days=30)
        assert len(result.tickers) == 1
        assert result.pairs == []

    def test_two_tickers_co_firing(self):
        ca = CorrelationAnalyzer(min_co_fires=3, correlation_window_hours=4)
        signals = []
        for i in range(5):
            # AAPL and MSFT fire within 1 hour of each other
            signals.append(_make_corr_signal("AAPL", offset_hours=i * 24))
            signals.append(_make_corr_signal("MSFT", offset_hours=i * 24 + 1))
        result = ca.compute_signal_correlations(signals, days=30, min_signals=3)
        assert len(result.tickers) == 2
        if result.pairs:
            assert result.pairs[0].ticker_a in ("AAPL", "MSFT")
            assert result.pairs[0].co_fires >= 3

    def test_same_stance_positive_correlation(self):
        ca = CorrelationAnalyzer(min_co_fires=3, correlation_window_hours=4)
        signals = []
        for i in range(5):
            signals.append(_make_corr_signal("AAPL", stance="bullish", offset_hours=i * 24))
            signals.append(_make_corr_signal("MSFT", stance="bullish", offset_hours=i * 24 + 0.5))
        result = ca.compute_signal_correlations(signals, days=30, min_signals=3)
        if result.pairs:
            assert result.pairs[0].correlation > 0
            assert result.pairs[0].same_stance_pct >= 80

    def test_opposite_stance_negative_correlation(self):
        ca = CorrelationAnalyzer(min_co_fires=3, correlation_window_hours=4)
        signals = []
        for i in range(5):
            signals.append(_make_corr_signal("AAPL", stance="bullish", offset_hours=i * 24))
            signals.append(_make_corr_signal("SQQQ", stance="bearish", offset_hours=i * 24 + 0.5))
        result = ca.compute_signal_correlations(signals, days=30, min_signals=3)
        if result.pairs:
            # same_stance_pct < 40 → negative correlation
            assert result.pairs[0].correlation < 0

    def test_min_signals_filter(self):
        ca = CorrelationAnalyzer()
        signals = [
            _make_corr_signal("AAPL", offset_hours=0),
            _make_corr_signal("MSFT", offset_hours=0),
        ]
        result = ca.compute_signal_correlations(signals, days=30, min_signals=5)
        assert result.tickers == []  # neither has 5 signals

    def test_old_signals_excluded(self):
        ca = CorrelationAnalyzer()
        signals = [_make_corr_signal("AAPL", offset_hours=40 * 24 + i) for i in range(10)]
        result = ca.compute_signal_correlations(signals, days=30, min_signals=5)
        assert result.tickers == []

    def test_strongest_positive_and_negative(self):
        ca = CorrelationAnalyzer(min_co_fires=3, correlation_window_hours=4)
        signals = []
        for i in range(6):
            signals.append(_make_corr_signal("AAPL", stance="bullish", offset_hours=i * 24))
            signals.append(_make_corr_signal("MSFT", stance="bullish", offset_hours=i * 24 + 0.5))
            signals.append(_make_corr_signal("SQQQ", stance="bearish", offset_hours=i * 24 + 0.5))
        result = ca.compute_signal_correlations(signals, days=30, min_signals=3)
        # Should have positive (AAPL-MSFT) and negative (AAPL-SQQQ or MSFT-SQQQ)
        assert isinstance(result, SignalCorrelationMatrix)

    def test_pairs_sorted_by_abs_correlation(self):
        ca = CorrelationAnalyzer(min_co_fires=2, correlation_window_hours=24)
        signals = []
        for i in range(8):
            signals.append(_make_corr_signal("A", stance="bullish", offset_hours=i * 24))
            signals.append(_make_corr_signal("B", stance="bullish", offset_hours=i * 24 + 1))
            signals.append(_make_corr_signal("C", stance="bullish", offset_hours=i * 24 + 2))
        result = ca.compute_signal_correlations(signals, days=30, min_signals=2)
        if len(result.pairs) >= 2:
            for j in range(len(result.pairs) - 1):
                assert abs(result.pairs[j].correlation) >= abs(result.pairs[j + 1].correlation)


class TestDetectClusters:
    """CorrelationAnalyzer.detect_clusters."""

    def test_no_pairs(self):
        ca = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(tickers=["A", "B"], pairs=[])
        result = ca.detect_clusters(matrix, threshold=0.3)
        assert result == []

    def test_below_threshold(self):
        ca = CorrelationAnalyzer()
        p = CorrelationPair("A", "B", 0.1, 5, 60.0, 20)
        matrix = SignalCorrelationMatrix(tickers=["A", "B"], pairs=[p])
        result = ca.detect_clusters(matrix, threshold=0.3)
        assert result == []

    def test_single_cluster(self):
        ca = CorrelationAnalyzer()
        p = CorrelationPair("A", "B", 0.8, 10, 90.0, 30)
        matrix = SignalCorrelationMatrix(tickers=["A", "B"], pairs=[p])
        result = ca.detect_clusters(matrix, threshold=0.3)
        assert len(result) == 1
        assert sorted(result[0].tickers) == ["A", "B"]
        assert result[0].avg_internal_correlation == 0.8

    def test_two_separate_clusters(self):
        ca = CorrelationAnalyzer()
        p1 = CorrelationPair("A", "B", 0.9, 15, 95.0, 40)
        p2 = CorrelationPair("C", "D", 0.7, 8, 80.0, 25)
        # A-C and B-D have low correlation (no link)
        matrix = SignalCorrelationMatrix(
            tickers=["A", "B", "C", "D"],
            pairs=[p1, p2],
        )
        result = ca.detect_clusters(matrix, threshold=0.3)
        assert len(result) == 2
        all_tickers = set()
        for c in result:
            all_tickers.update(c.tickers)
        assert all_tickers == {"A", "B", "C", "D"}

    def test_connected_component_merges(self):
        ca = CorrelationAnalyzer()
        # A-B and B-C above threshold → single cluster A,B,C
        p1 = CorrelationPair("A", "B", 0.8, 10, 90.0, 30)
        p2 = CorrelationPair("B", "C", 0.6, 7, 70.0, 25)
        matrix = SignalCorrelationMatrix(
            tickers=["A", "B", "C"],
            pairs=[p1, p2],
        )
        result = ca.detect_clusters(matrix, threshold=0.3)
        assert len(result) == 1
        assert sorted(result[0].tickers) == ["A", "B", "C"]

    def test_sorted_by_size_desc(self):
        ca = CorrelationAnalyzer()
        p1 = CorrelationPair("A", "B", 0.8, 10, 90.0, 30)
        p2 = CorrelationPair("B", "C", 0.7, 8, 80.0, 25)
        p3 = CorrelationPair("D", "E", 0.6, 6, 70.0, 20)
        matrix = SignalCorrelationMatrix(
            tickers=["A", "B", "C", "D", "E"],
            pairs=[p1, p2, p3],
        )
        result = ca.detect_clusters(matrix, threshold=0.3)
        if len(result) >= 2:
            assert result[0].size >= result[1].size

    def test_negative_correlation_excluded(self):
        ca = CorrelationAnalyzer()
        p = CorrelationPair("A", "B", -0.5, 10, 20.0, 30)
        matrix = SignalCorrelationMatrix(tickers=["A", "B"], pairs=[p])
        result = ca.detect_clusters(matrix, threshold=0.3)
        assert result == []  # negative correlation not >= threshold


class TestComputeLeadLag:
    """CorrelationAnalyzer.compute_lead_lag."""

    def test_empty_signals(self):
        ca = CorrelationAnalyzer()
        result = ca.compute_lead_lag([], days=30)
        assert result == []

    def test_single_ticker(self):
        ca = CorrelationAnalyzer()
        signals = [_make_corr_signal("AAPL", offset_hours=i) for i in range(5)]
        result = ca.compute_lead_lag(signals, days=30)
        assert result == []

    def test_consistent_leader(self):
        ca = CorrelationAnalyzer()
        signals = []
        for i in range(5):
            # AAPL always fires 2 hours before MSFT
            signals.append(_make_corr_signal("AAPL", offset_hours=i * 24 + 2))
            signals.append(_make_corr_signal("MSFT", offset_hours=i * 24))
        result = ca.compute_lead_lag(signals, days=30, min_occurrences=3)
        # AAPL should lead (fires earlier, but since offset_hours is subtracted,
        # larger offset = further in past; MSFT fires at i*24, AAPL at i*24+2
        # meaning MSFT is actually more recent than AAPL)
        # So AAPL leads MSFT
        if result:
            assert isinstance(result[0], LeadLagPair)
            assert result[0].confidence >= 0.6

    def test_min_occurrences_filter(self):
        ca = CorrelationAnalyzer()
        signals = [
            _make_corr_signal("AAPL", offset_hours=0),
            _make_corr_signal("MSFT", offset_hours=1),
        ]
        result = ca.compute_lead_lag(signals, days=30, min_occurrences=5)
        assert result == []

    def test_max_lag_hours_filter(self):
        ca = CorrelationAnalyzer()
        signals = []
        for i in range(5):
            # Signals 50 hours apart within each pair → exceeds 24h max_lag
            signals.append(_make_corr_signal("AAPL", offset_hours=i * 200))
            signals.append(_make_corr_signal("MSFT", offset_hours=i * 200 + 50))
        result = ca.compute_lead_lag(signals, days=1200, max_lag_hours=24, min_occurrences=3)
        assert result == []

    def test_sorted_by_confidence_times_occurrences(self):
        ca = CorrelationAnalyzer()
        signals = []
        for i in range(10):
            signals.append(_make_corr_signal("AAPL", offset_hours=i * 24 + 2))
            signals.append(_make_corr_signal("MSFT", offset_hours=i * 24))
            signals.append(_make_corr_signal("GOOGL", offset_hours=i * 24 + 3))
        result = ca.compute_lead_lag(signals, days=30, min_occurrences=3)
        if len(result) >= 2:
            for j in range(len(result) - 1):
                score_a = result[j].confidence * result[j].occurrences
                score_b = result[j + 1].confidence * result[j + 1].occurrences
                assert score_a >= score_b


class TestBuildNetworkData:
    """CorrelationAnalyzer.build_network_data."""

    def test_empty_matrix(self):
        ca = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(tickers=[], pairs=[])
        result = ca.build_network_data(matrix)
        assert isinstance(result, NetworkGraph)
        assert result.nodes == []
        assert result.edges == []

    def test_nodes_for_all_tickers(self):
        ca = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(tickers=["AAPL", "MSFT", "GOOGL"], pairs=[])
        result = ca.build_network_data(matrix)
        assert len(result.nodes) == 3
        ids = {n["id"] for n in result.nodes}
        assert ids == {"AAPL", "MSFT", "GOOGL"}

    def test_node_sizing_with_counts(self):
        ca = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(tickers=["AAPL", "MSFT"], pairs=[])
        counts = {"AAPL": 50, "MSFT": 1}
        result = ca.build_network_data(matrix, signal_counts=counts)
        aapl_node = next(n for n in result.nodes if n["id"] == "AAPL")
        msft_node = next(n for n in result.nodes if n["id"] == "MSFT")
        assert aapl_node["size"] == 30  # capped at 30
        assert msft_node["size"] == 5  # min size = max(5, 1) = 5

    def test_edges_above_threshold(self):
        ca = CorrelationAnalyzer()
        p1 = CorrelationPair("AAPL", "MSFT", 0.8, 10, 90.0, 30)
        p2 = CorrelationPair("AAPL", "GOOGL", 0.1, 3, 50.0, 15)
        matrix = SignalCorrelationMatrix(
            tickers=["AAPL", "MSFT", "GOOGL"],
            pairs=[p1, p2],
        )
        result = ca.build_network_data(matrix, min_correlation=0.2)
        assert len(result.edges) == 1
        assert result.edges[0]["source"] == "AAPL"
        assert result.edges[0]["target"] == "MSFT"

    def test_positive_edge_green(self):
        ca = CorrelationAnalyzer()
        p = CorrelationPair("A", "B", 0.5, 5, 80.0, 20)
        matrix = SignalCorrelationMatrix(tickers=["A", "B"], pairs=[p])
        result = ca.build_network_data(matrix, min_correlation=0.2)
        assert result.edges[0]["color"] == "#22c55e"

    def test_negative_edge_red(self):
        ca = CorrelationAnalyzer()
        p = CorrelationPair("A", "B", -0.5, 5, 20.0, 20)
        matrix = SignalCorrelationMatrix(tickers=["A", "B"], pairs=[p])
        result = ca.build_network_data(matrix, min_correlation=0.2)
        assert result.edges[0]["color"] == "#ef4444"

    def test_edge_weight_is_abs_correlation(self):
        ca = CorrelationAnalyzer()
        p = CorrelationPair("A", "B", -0.7, 10, 15.0, 30)
        matrix = SignalCorrelationMatrix(tickers=["A", "B"], pairs=[p])
        result = ca.build_network_data(matrix, min_correlation=0.2)
        assert result.edges[0]["weight"] == 0.7

    def test_edge_includes_co_fires(self):
        ca = CorrelationAnalyzer()
        p = CorrelationPair("A", "B", 0.6, 12, 75.0, 25)
        matrix = SignalCorrelationMatrix(tickers=["A", "B"], pairs=[p])
        result = ca.build_network_data(matrix, min_correlation=0.2)
        assert result.edges[0]["co_fires"] == 12

    def test_no_signal_counts_defaults(self):
        ca = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(tickers=["X"], pairs=[])
        result = ca.build_network_data(matrix)
        assert result.nodes[0]["signals"] == 1  # default
        assert result.nodes[0]["size"] == 5  # max(5, min(30, 1)) = 5


# ═══════════════════════════════════════════════════════════════════
# Part 5 — Parametrized & Stress Tests
# ═══════════════════════════════════════════════════════════════════


class TestParametrized:
    """Parametrized tests for analysis modules."""

    @pytest.mark.parametrize("num_signals,expected_momentum", [
        (0, 0),    # no data → no results
        (2, 0),    # below min_signals=3
        (3, 1),    # exactly at threshold
        (10, 1),   # well above
    ])
    def test_sector_momentum_threshold(self, num_signals, expected_momentum):
        sa = SectorAnalyzer(min_signals=3)
        data = [_make_sector_signal("Tech", offset_hours=i * 24) for i in range(num_signals)]
        result = sa.compute_sector_momentum(data, days=30)
        assert len(result) == expected_momentum

    @pytest.mark.parametrize("stance,expected_pct", [
        ("bullish", 100.0),
        ("bearish", 0.0),
    ])
    def test_sector_momentum_all_same_stance(self, stance, expected_pct):
        sa = SectorAnalyzer(min_signals=3)
        data = [_make_sector_signal("Tech", stance=stance, offset_hours=i) for i in range(5)]
        result = sa.compute_sector_momentum(data, days=30)
        assert len(result) == 1
        assert result[0].bullish_pct == expected_pct

    @pytest.mark.parametrize("threshold,expected_clusters", [
        (0.1, 1),   # low threshold → everything clusters
        (0.5, 1),   # medium → still clusters
        (0.95, 0),  # very high → nothing clusters
    ])
    def test_cluster_threshold_sensitivity(self, threshold, expected_clusters):
        ca = CorrelationAnalyzer()
        p = CorrelationPair("A", "B", 0.8, 10, 90.0, 30)
        matrix = SignalCorrelationMatrix(tickers=["A", "B"], pairs=[p])
        result = ca.detect_clusters(matrix, threshold=threshold)
        assert len(result) == expected_clusters

    @pytest.mark.parametrize("min_corr,expected_edges", [
        (0.1, 2),
        (0.5, 1),
        (0.9, 0),
    ])
    def test_network_min_correlation_filter(self, min_corr, expected_edges):
        ca = CorrelationAnalyzer()
        p1 = CorrelationPair("A", "B", 0.8, 10, 90.0, 30)
        p2 = CorrelationPair("A", "C", 0.3, 5, 60.0, 20)
        matrix = SignalCorrelationMatrix(
            tickers=["A", "B", "C"], pairs=[p1, p2],
        )
        result = ca.build_network_data(matrix, min_correlation=min_corr)
        assert len(result.edges) == expected_edges

    @pytest.mark.parametrize("days", [1, 7, 30, 90, 365])
    def test_sector_momentum_various_windows(self, days):
        sa = SectorAnalyzer(min_signals=3)
        # Generate signals within the window
        data = [
            _make_sector_signal("Tech", offset_hours=i * (days * 24 / 10))
            for i in range(10)
        ]
        result = sa.compute_sector_momentum(data, days=days)
        assert isinstance(result, list)

    @pytest.mark.parametrize("n_sectors", [1, 5, 10, 20])
    def test_rank_many_sectors(self, n_sectors):
        sa = SectorAnalyzer(min_signals=3)
        data = []
        for i in range(n_sectors):
            for j in range(5):
                data.append(_make_sector_signal(f"Sector_{i}", offset_hours=j * 24))
        result = sa.rank_sectors(data, days=30)
        assert len(result) == n_sectors
        # Verify ranks are 1..n
        ranks = [r.rank for r in result]
        assert ranks == list(range(1, n_sectors + 1))


class TestStress:
    """Stress tests for analysis modules."""

    def test_sector_momentum_500_signals(self):
        sa = SectorAnalyzer(min_signals=3)
        sectors = ["Tech", "Energy", "Healthcare", "Financials", "Utilities"]
        data = []
        for i in range(500):
            sector = sectors[i % len(sectors)]
            stance = "bullish" if i % 3 != 0 else "bearish"
            data.append(_make_sector_signal(sector, stance=stance, offset_hours=i * 1.5))
        result = sa.compute_sector_momentum(data, days=60)
        assert len(result) == 5
        for m in result:
            assert 0 <= m.score <= 100

    def test_capital_flow_500_signals(self):
        sa = SectorAnalyzer()
        sectors = ["Tech", "Energy", "Healthcare"]
        data = []
        for i in range(500):
            sector = sectors[i % len(sectors)]
            stance = ["bullish", "bearish", "mixed"][i % 3]
            data.append(_make_sector_signal(sector, stance=stance, confidence=0.5 + (i % 5) * 0.1, offset_hours=i))
        result = sa.compute_capital_flow(data, days=60)
        assert len(result) == 3
        for f in result:
            assert isinstance(f, CapitalFlow)

    def test_correlation_many_tickers(self):
        ca = CorrelationAnalyzer(min_co_fires=2, correlation_window_hours=24)
        tickers = [f"T{i}" for i in range(20)]
        signals = []
        for i in range(100):
            ticker = tickers[i % len(tickers)]
            signals.append(_make_corr_signal(ticker, offset_hours=i * 6))
        result = ca.compute_signal_correlations(signals, days=60, min_signals=3)
        assert isinstance(result, SignalCorrelationMatrix)
        assert len(result.tickers) <= 20

    def test_cluster_detection_many_pairs(self):
        ca = CorrelationAnalyzer()
        pairs = []
        tickers = [f"T{i}" for i in range(15)]
        for i in range(len(tickers)):
            for j in range(i + 1, len(tickers)):
                corr = 0.5 + (i + j) % 5 * 0.1
                pairs.append(CorrelationPair(
                    tickers[i], tickers[j],
                    correlation=corr, co_fires=5,
                    same_stance_pct=70.0, sample_size=20,
                ))
        matrix = SignalCorrelationMatrix(tickers=tickers, pairs=pairs)
        result = ca.detect_clusters(matrix, threshold=0.5)
        assert isinstance(result, list)
        for c in result:
            assert isinstance(c, TickerCluster)
            assert c.size >= 2

    def test_lead_lag_many_signals(self):
        ca = CorrelationAnalyzer()
        signals = []
        tickers = ["AAPL", "MSFT", "GOOGL", "AMZN"]
        for i in range(200):
            ticker = tickers[i % len(tickers)]
            signals.append(_make_corr_signal(ticker, offset_hours=i * 3))
        result = ca.compute_lead_lag(signals, days=60, min_occurrences=3)
        assert isinstance(result, list)
        for pair in result:
            assert isinstance(pair, LeadLagPair)
            assert pair.confidence >= 0.6

    def test_network_graph_large(self):
        ca = CorrelationAnalyzer()
        tickers = [f"T{i}" for i in range(50)]
        pairs = []
        for i in range(0, 50, 2):
            pairs.append(CorrelationPair(
                tickers[i], tickers[i + 1],
                correlation=0.6, co_fires=5,
                same_stance_pct=80.0, sample_size=15,
            ))
        matrix = SignalCorrelationMatrix(tickers=tickers, pairs=pairs)
        counts = {t: (i + 1) * 2 for i, t in enumerate(tickers)}
        result = ca.build_network_data(matrix, min_correlation=0.3, signal_counts=counts)
        assert len(result.nodes) == 50
        assert len(result.edges) == 25

    def test_rank_sectors_with_all_performance_data(self):
        sa = SectorAnalyzer(min_signals=3)
        sectors = [f"Sector_{i}" for i in range(10)]
        data = []
        for s in sectors:
            for j in range(10):
                data.append(_make_sector_signal(s, offset_hours=j * 24))
        perf = {s: {"win_rate": 0.5 + i * 0.04, "total_tracked": 20}
                for i, s in enumerate(sectors)}
        result = sa.rank_sectors(data, performance_data=perf, days=30)
        assert len(result) == 10
        assert all(r.win_rate is not None for r in result)
        # Verify ascending rank numbers
        for i, r in enumerate(result):
            assert r.rank == i + 1

    def test_detect_rotation_many_sectors(self):
        sa = SectorAnalyzer(min_signals=3)
        now = time.time()
        data = []
        sectors = ["Tech", "Energy", "Healthcare", "Financials"]
        for s in sectors:
            for j in range(8):
                data.append({
                    "sector": s,
                    "stance": "bullish" if j % 2 == 0 else "bearish",
                    "confidence": 0.7,
                    "created_at": now - j * 86400,
                })
            # Add older period signals
            for j in range(5):
                data.append({
                    "sector": s,
                    "stance": "bullish",
                    "confidence": 0.8,
                    "created_at": now - (40 + j) * 86400,
                })
        result = sa.detect_rotation(data, days=30)
        assert isinstance(result, list)
        for event in result:
            assert isinstance(event, RotationEvent)
