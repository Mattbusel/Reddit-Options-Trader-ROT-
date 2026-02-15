"""
Comprehensive tests for sector analysis types module.

Modules tested:
- rot.analysis.sector_types

Coverage:
- SectorMomentum dataclass (frozen, to_dict)
- RotationEvent dataclass (frozen, to_dict)
- SectorRanking dataclass (frozen, to_dict with nested momentum)
- CapitalFlow dataclass (frozen, to_dict)
- to_dict rounding behavior
- Frozen immutability
- Optional fields (win_rate)
"""
from __future__ import annotations

import pytest

from rot.analysis.sector_types import CapitalFlow, RotationEvent, SectorMomentum, SectorRanking


class TestSectorMomentum:
    def test_sector_momentum_creation(self):
        """SectorMomentum can be created with required fields."""
        momentum = SectorMomentum(
            sector="Technology",
            signal_velocity=12.5,
            trend="accelerating",
            acceleration=2.3,
            score=85.0,
        )

        assert momentum.sector == "Technology"
        assert momentum.signal_velocity == 12.5
        assert momentum.trend == "accelerating"
        assert momentum.score == 85.0

    def test_sector_momentum_defaults(self):
        """SectorMomentum has default values for optional fields."""
        momentum = SectorMomentum(
            sector="Energy",
            signal_velocity=5.0,
            trend="stable",
            acceleration=0.0,
            score=50.0,
        )

        assert momentum.signal_count == 0
        assert momentum.bullish_pct == 0.0
        assert momentum.bearish_pct == 0.0

    def test_sector_momentum_to_dict(self):
        """SectorMomentum.to_dict returns properly formatted dict."""
        momentum = SectorMomentum(
            sector="Technology",
            signal_velocity=12.567,
            trend="accelerating",
            acceleration=2.345,
            score=85.123,
            signal_count=100,
            bullish_pct=65.432,
            bearish_pct=34.567,
        )

        result = momentum.to_dict()

        assert result["sector"] == "Technology"
        assert result["signal_velocity"] == 12.57  # Rounded to 2 decimals
        assert result["trend"] == "accelerating"
        assert result["acceleration"] == 2.35  # Rounded to 2 decimals
        assert result["score"] == 85.1  # Rounded to 1 decimal
        assert result["signal_count"] == 100
        assert result["bullish_pct"] == 65.4  # Rounded to 1 decimal
        assert result["bearish_pct"] == 34.6  # Rounded to 1 decimal

    def test_sector_momentum_frozen(self):
        """SectorMomentum is immutable (frozen)."""
        momentum = SectorMomentum(
            sector="Energy",
            signal_velocity=5.0,
            trend="stable",
            acceleration=0.0,
            score=50.0,
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            momentum.score = 100.0


class TestRotationEvent:
    def test_rotation_event_creation(self):
        """RotationEvent can be created."""
        event = RotationEvent(
            from_sector="Technology",
            to_sector="Healthcare",
            detected_at=1234567890.0,
            confidence=0.85,
            from_velocity_delta=-5.2,
            to_velocity_delta=8.3,
        )

        assert event.from_sector == "Technology"
        assert event.to_sector == "Healthcare"
        assert event.confidence == 0.85

    def test_rotation_event_to_dict(self):
        """RotationEvent.to_dict returns properly formatted dict."""
        event = RotationEvent(
            from_sector="Technology",
            to_sector="Healthcare",
            detected_at=1234567890.123,
            confidence=0.8567,
            from_velocity_delta=-5.234,
            to_velocity_delta=8.345,
        )

        result = event.to_dict()

        assert result["from_sector"] == "Technology"
        assert result["to_sector"] == "Healthcare"
        assert result["detected_at"] == 1234567890.123  # No rounding on timestamp
        assert result["confidence"] == 0.86  # Rounded to 2 decimals
        assert result["from_velocity_delta"] == -5.23  # Rounded to 2 decimals
        assert result["to_velocity_delta"] == 8.35  # Rounded to 2 decimals

    def test_rotation_event_frozen(self):
        """RotationEvent is immutable."""
        event = RotationEvent(
            from_sector="Tech",
            to_sector="Health",
            detected_at=123.0,
            confidence=0.8,
            from_velocity_delta=-5.0,
            to_velocity_delta=8.0,
        )

        with pytest.raises(Exception):
            event.confidence = 0.9


class TestSectorRanking:
    def test_sector_ranking_creation(self):
        """SectorRanking can be created with nested momentum."""
        momentum = SectorMomentum(
            sector="Technology",
            signal_velocity=12.5,
            trend="accelerating",
            acceleration=2.3,
            score=85.0,
        )

        ranking = SectorRanking(
            sector="Technology",
            rank=1,
            score=90.5,
            signal_count=150,
            win_rate=0.678,
            momentum=momentum,
            net_sentiment=0.45,
        )

        assert ranking.sector == "Technology"
        assert ranking.rank == 1
        assert ranking.momentum == momentum

    def test_sector_ranking_optional_win_rate(self):
        """SectorRanking win_rate can be None."""
        momentum = SectorMomentum(
            sector="Energy",
            signal_velocity=5.0,
            trend="stable",
            acceleration=0.0,
            score=50.0,
        )

        ranking = SectorRanking(
            sector="Energy",
            rank=5,
            score=45.0,
            signal_count=10,
            win_rate=None,  # Insufficient data
            momentum=momentum,
            net_sentiment=0.0,
        )

        assert ranking.win_rate is None

    def test_sector_ranking_to_dict(self):
        """SectorRanking.to_dict includes nested momentum.to_dict."""
        momentum = SectorMomentum(
            sector="Technology",
            signal_velocity=12.567,
            trend="accelerating",
            acceleration=2.345,
            score=85.123,
        )

        ranking = SectorRanking(
            sector="Technology",
            rank=1,
            score=90.567,
            signal_count=150,
            win_rate=0.67890,
            momentum=momentum,
            net_sentiment=0.4567,
        )

        result = ranking.to_dict()

        assert result["sector"] == "Technology"
        assert result["rank"] == 1
        assert result["score"] == 90.6  # Rounded to 1 decimal
        assert result["signal_count"] == 150
        assert result["win_rate"] == 0.679  # Rounded to 3 decimals
        assert result["net_sentiment"] == 0.46  # Rounded to 2 decimals
        assert "momentum" in result
        assert isinstance(result["momentum"], dict)
        assert result["momentum"]["sector"] == "Technology"

    def test_sector_ranking_to_dict_none_win_rate(self):
        """SectorRanking.to_dict handles None win_rate."""
        momentum = SectorMomentum(
            sector="Energy",
            signal_velocity=5.0,
            trend="stable",
            acceleration=0.0,
            score=50.0,
        )

        ranking = SectorRanking(
            sector="Energy",
            rank=5,
            score=45.0,
            signal_count=10,
            win_rate=None,
            momentum=momentum,
            net_sentiment=0.0,
        )

        result = ranking.to_dict()
        assert result["win_rate"] is None

    def test_sector_ranking_frozen(self):
        """SectorRanking is immutable."""
        momentum = SectorMomentum(
            sector="Tech",
            signal_velocity=12.5,
            trend="accelerating",
            acceleration=2.3,
            score=85.0,
        )

        ranking = SectorRanking(
            sector="Tech",
            rank=1,
            score=90.0,
            signal_count=100,
            win_rate=0.7,
            momentum=momentum,
            net_sentiment=0.5,
        )

        with pytest.raises(Exception):
            ranking.rank = 2


class TestCapitalFlow:
    def test_capital_flow_creation(self):
        """CapitalFlow can be created."""
        flow = CapitalFlow(
            sector="Technology",
            bullish_count=120,
            bearish_count=80,
            mixed_count=20,
            bullish_intensity=0.75,
            bearish_intensity=0.65,
            net_flow=15.5,
            flow_change=3.2,
        )

        assert flow.sector == "Technology"
        assert flow.bullish_count == 120
        assert flow.bearish_count == 80
        assert flow.net_flow == 15.5

    def test_capital_flow_to_dict(self):
        """CapitalFlow.to_dict returns properly formatted dict."""
        flow = CapitalFlow(
            sector="Technology",
            bullish_count=120,
            bearish_count=80,
            mixed_count=20,
            bullish_intensity=0.7567,
            bearish_intensity=0.6543,
            net_flow=15.567,
            flow_change=3.234,
        )

        result = flow.to_dict()

        assert result["sector"] == "Technology"
        assert result["bullish_count"] == 120
        assert result["bearish_count"] == 80
        assert result["mixed_count"] == 20
        assert result["bullish_intensity"] == 0.757  # Rounded to 3 decimals
        assert result["bearish_intensity"] == 0.654  # Rounded to 3 decimals
        assert result["net_flow"] == 15.57  # Rounded to 2 decimals
        assert result["flow_change"] == 3.23  # Rounded to 2 decimals

    def test_capital_flow_frozen(self):
        """CapitalFlow is immutable."""
        flow = CapitalFlow(
            sector="Tech",
            bullish_count=120,
            bearish_count=80,
            mixed_count=20,
            bullish_intensity=0.75,
            bearish_intensity=0.65,
            net_flow=15.5,
            flow_change=3.2,
        )

        with pytest.raises(Exception):
            flow.net_flow = 20.0


class TestEdgeCases:
    def test_negative_values(self):
        """Types handle negative values correctly."""
        momentum = SectorMomentum(
            sector="Energy",
            signal_velocity=5.0,
            trend="decelerating",
            acceleration=-3.5,  # Negative acceleration
            score=30.0,
        )

        assert momentum.acceleration == -3.5

        result = momentum.to_dict()
        assert result["acceleration"] == -3.5

    def test_zero_values(self):
        """Types handle zero values correctly."""
        flow = CapitalFlow(
            sector="Utilities",
            bullish_count=0,
            bearish_count=0,
            mixed_count=0,
            bullish_intensity=0.0,
            bearish_intensity=0.0,
            net_flow=0.0,
            flow_change=0.0,
        )

        result = flow.to_dict()
        assert result["net_flow"] == 0.0
        assert result["flow_change"] == 0.0

    def test_extreme_rounding(self):
        """to_dict rounding works with extreme values."""
        momentum = SectorMomentum(
            sector="Test",
            signal_velocity=0.0001,
            trend="stable",
            acceleration=0.0001,
            score=0.0001,
        )

        result = momentum.to_dict()
        # All round to 0.0 or 0.00 due to rounding
        assert result["signal_velocity"] == 0.0
        assert result["acceleration"] == 0.0
        assert result["score"] == 0.0
