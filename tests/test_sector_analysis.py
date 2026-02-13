"""Tests for sector rotation analysis engine."""

from __future__ import annotations

import time

import pytest

from rot.analysis.sector import SectorAnalyzer
from rot.analysis.sector_types import (
    CapitalFlow,
    RotationEvent,
    SectorMomentum,
    SectorRanking,
)


# ── Helpers ──


def _make_signal(
    sector: str = "Technology",
    stance: str = "bullish",
    confidence: float = 0.6,
    created_at: float | None = None,
    ticker: str = "AAPL",
) -> dict:
    return {
        "sector": sector,
        "stance": stance,
        "confidence": confidence,
        "created_at": created_at or time.time(),
        "ticker": ticker,
    }


def _make_sector_signals(
    sector: str,
    count: int,
    stance: str = "bullish",
    days_ago_start: float = 0,
    days_ago_end: float = 20,
) -> list:
    """Create evenly-spaced signals across a time range."""
    now = time.time()
    start = now - (days_ago_end * 86400)
    step = (days_ago_end - days_ago_start) * 86400 / max(count, 1)
    return [
        _make_signal(
            sector=sector,
            stance=stance,
            created_at=start + i * step,
        )
        for i in range(count)
    ]


# ── SectorMomentum ──


class TestSectorMomentum:
    """Sector momentum computation tests."""

    def test_empty_data(self):
        analyzer = SectorAnalyzer()
        result = analyzer.compute_sector_momentum([], days=30)
        assert result == []

    def test_insufficient_signals(self):
        analyzer = SectorAnalyzer(min_signals=5)
        signals = [_make_signal("Tech")] * 3
        result = analyzer.compute_sector_momentum(signals, days=30)
        assert result == []

    def test_single_sector(self):
        analyzer = SectorAnalyzer(min_signals=3)
        signals = _make_sector_signals("Technology", 10)
        result = analyzer.compute_sector_momentum(signals, days=30)
        assert len(result) == 1
        assert result[0].sector == "Technology"
        assert result[0].signal_count == 10
        assert result[0].score > 0

    def test_multiple_sectors_ranked(self):
        analyzer = SectorAnalyzer(min_signals=3)
        signals = (
            _make_sector_signals("Technology", 20) +
            _make_sector_signals("Healthcare", 5) +
            _make_sector_signals("Energy", 10)
        )
        result = analyzer.compute_sector_momentum(signals, days=30)
        assert len(result) == 3
        # Highest velocity sector should rank first
        assert result[0].signal_count >= result[-1].signal_count

    def test_acceleration_detected(self):
        analyzer = SectorAnalyzer(min_signals=3)
        now = time.time()
        # More signals in recent half
        signals = (
            _make_sector_signals("Tech", 3, days_ago_start=15, days_ago_end=30) +
            _make_sector_signals("Tech", 12, days_ago_start=0, days_ago_end=15)
        )
        result = analyzer.compute_sector_momentum(signals, days=30)
        assert len(result) == 1
        assert result[0].trend == "accelerating"
        assert result[0].acceleration > 0

    def test_deceleration_detected(self):
        analyzer = SectorAnalyzer(min_signals=3)
        # More signals in older half
        signals = (
            _make_sector_signals("Tech", 12, days_ago_start=15, days_ago_end=30) +
            _make_sector_signals("Tech", 3, days_ago_start=0, days_ago_end=15)
        )
        result = analyzer.compute_sector_momentum(signals, days=30)
        assert len(result) == 1
        assert result[0].trend == "decelerating"

    def test_bullish_bearish_pct(self):
        analyzer = SectorAnalyzer(min_signals=3)
        signals = (
            _make_sector_signals("Tech", 7, stance="bullish") +
            _make_sector_signals("Tech", 3, stance="bearish")
        )
        result = analyzer.compute_sector_momentum(signals, days=30)
        assert len(result) == 1
        assert result[0].bullish_pct == pytest.approx(70.0)
        assert result[0].bearish_pct == pytest.approx(30.0)

    def test_to_dict(self):
        m = SectorMomentum(
            sector="Tech", signal_velocity=2.5, trend="accelerating",
            acceleration=0.5, score=75.0, signal_count=20,
            bullish_pct=60.0, bearish_pct=30.0,
        )
        d = m.to_dict()
        assert d["sector"] == "Tech"
        assert d["score"] == 75.0

    def test_stale_signals_excluded(self):
        analyzer = SectorAnalyzer(min_signals=3)
        old = _make_sector_signals("Tech", 10, days_ago_start=40, days_ago_end=50)
        result = analyzer.compute_sector_momentum(old, days=30)
        assert result == []


# ── Capital Flow ──


class TestCapitalFlow:
    """Capital flow computation tests."""

    def test_empty(self):
        analyzer = SectorAnalyzer()
        result = analyzer.compute_capital_flow([], days=30)
        assert result == []

    def test_bullish_dominant(self):
        analyzer = SectorAnalyzer()
        signals = (
            _make_sector_signals("Tech", 8, stance="bullish") +
            _make_sector_signals("Tech", 2, stance="bearish")
        )
        result = analyzer.compute_capital_flow(signals, days=30)
        assert len(result) == 1
        assert result[0].sector == "Tech"
        assert result[0].bullish_count == 8
        assert result[0].bearish_count == 2
        assert result[0].net_flow > 0

    def test_bearish_dominant(self):
        analyzer = SectorAnalyzer()
        signals = (
            _make_sector_signals("Energy", 2, stance="bullish") +
            _make_sector_signals("Energy", 8, stance="bearish")
        )
        result = analyzer.compute_capital_flow(signals, days=30)
        assert len(result) == 1
        assert result[0].net_flow < 0

    def test_to_dict(self):
        flow = CapitalFlow(
            sector="Tech", bullish_count=5, bearish_count=3, mixed_count=1,
            bullish_intensity=0.7, bearish_intensity=0.5,
            net_flow=1.5, flow_change=0.3,
        )
        d = flow.to_dict()
        assert d["sector"] == "Tech"
        assert d["net_flow"] == 1.5


# ── Ranking ──


class TestSectorRanking:
    """Sector ranking tests."""

    def test_empty(self):
        analyzer = SectorAnalyzer()
        result = analyzer.rank_sectors([], days=30)
        assert result == []

    def test_ranked_by_score(self):
        analyzer = SectorAnalyzer(min_signals=3)
        signals = (
            _make_sector_signals("Technology", 20) +
            _make_sector_signals("Healthcare", 5) +
            _make_sector_signals("Energy", 10)
        )
        result = analyzer.rank_sectors(signals, days=30)
        assert len(result) == 3
        assert result[0].rank == 1
        assert result[1].rank == 2
        assert result[2].rank == 3
        assert result[0].score >= result[1].score

    def test_with_performance_data(self):
        analyzer = SectorAnalyzer(min_signals=3)
        signals = (
            _make_sector_signals("Technology", 10) +
            _make_sector_signals("Healthcare", 10)
        )
        perf = {
            "Technology": {"win_rate": 0.65, "total_tracked": 20},
            "Healthcare": {"win_rate": 0.45, "total_tracked": 20},
        }
        result = analyzer.rank_sectors(signals, performance_data=perf, days=30)
        assert len(result) == 2
        # Tech should rank higher due to win rate
        assert result[0].sector == "Technology"
        assert result[0].win_rate == 0.65

    def test_to_dict(self):
        m = SectorMomentum(
            sector="Tech", signal_velocity=1.0, trend="stable",
            acceleration=0.0, score=50.0, signal_count=10,
        )
        r = SectorRanking(
            sector="Tech", rank=1, score=75.0, signal_count=10,
            win_rate=0.6, momentum=m, net_sentiment=0.3,
        )
        d = r.to_dict()
        assert d["rank"] == 1
        assert d["win_rate"] == 0.6
        assert d["momentum"]["score"] == 50.0


# ── Rotation Detection ──


class TestRotationDetection:
    """Rotation event detection tests."""

    def test_no_data(self):
        analyzer = SectorAnalyzer()
        result = analyzer.detect_rotation([], days=30)
        assert result == []

    def test_single_sector_no_rotation(self):
        analyzer = SectorAnalyzer(min_signals=3)
        signals = _make_sector_signals("Tech", 10)
        result = analyzer.detect_rotation(signals, days=30)
        assert result == []  # need 2+ sectors and momentum delta

    def test_to_dict(self):
        r = RotationEvent(
            from_sector="Energy", to_sector="Tech",
            detected_at=time.time(), confidence=0.75,
            from_velocity_delta=-0.5, to_velocity_delta=0.8,
        )
        d = r.to_dict()
        assert d["from_sector"] == "Energy"
        assert d["to_sector"] == "Tech"
        assert d["confidence"] == 0.75
