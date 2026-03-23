"""Tests for rot.strategy.position_sizing."""

from __future__ import annotations

import pytest

from rot.strategy.position_sizing import (
    FractionalKelly,
    KellyCriterion,
    MaxLossSizing,
    PositionSizingEngine,
    VolatilityScaledSizing,
)


# ---------------------------------------------------------------------------
# KellyCriterion
# ---------------------------------------------------------------------------


class TestKellyCriterion:
    def setup_method(self):
        self.kelly = KellyCriterion(max_fraction=0.50, min_trades=10, floor_fraction=0.02)

    def test_invalid_max_fraction(self):
        with pytest.raises(ValueError):
            KellyCriterion(max_fraction=0.0)
        with pytest.raises(ValueError):
            KellyCriterion(max_fraction=1.5)

    def test_invalid_portfolio_value(self):
        with pytest.raises(ValueError):
            self.kelly.compute(0.60, 5.0, 2.0, portfolio_value=0.0)

    def test_floor_when_insufficient_history(self):
        result = self.kelly.compute(0.60, 5.0, 2.0, portfolio_value=10000.0, n_trades=5)
        assert result.position_fraction == pytest.approx(0.02, abs=1e-6)
        assert result.position_dollars == pytest.approx(200.0, abs=0.01)
        assert "floor" in result.rationale.lower()

    def test_positive_edge(self):
        # win_rate=0.6, avg_win=4%, avg_loss=2%, b=2
        # f* = (0.6*2 - 0.4)/2 = 0.4
        result = self.kelly.compute(
            win_rate=0.60, avg_win=4.0, avg_loss=2.0,
            portfolio_value=10000.0, n_trades=50
        )
        assert result.position_fraction > 0.0
        assert result.position_fraction <= 0.50
        assert result.position_dollars == pytest.approx(result.position_fraction * 10000.0, abs=0.01)

    def test_negative_edge_clamped_to_zero(self):
        # win_rate=0.3, avg_win=1%, avg_loss=2% → negative Kelly → clamped to 0
        result = self.kelly.compute(
            win_rate=0.30, avg_win=1.0, avg_loss=2.0,
            portfolio_value=10000.0, n_trades=50
        )
        assert result.position_fraction >= 0.0

    def test_max_fraction_cap(self):
        # Very high edge → should cap at max_fraction
        result = self.kelly.compute(
            win_rate=0.99, avg_win=100.0, avg_loss=1.0,
            portfolio_value=10000.0, n_trades=100
        )
        assert result.position_fraction <= 0.50

    def test_method_label(self):
        result = self.kelly.compute(0.6, 4.0, 2.0, 10000.0, n_trades=50)
        assert result.method == "kelly_full"


# ---------------------------------------------------------------------------
# FractionalKelly
# ---------------------------------------------------------------------------


class TestFractionalKelly:
    def test_invalid_kelly_fraction(self):
        with pytest.raises(ValueError):
            FractionalKelly(kelly_fraction=0.0)
        with pytest.raises(ValueError):
            FractionalKelly(kelly_fraction=1.5)

    def test_half_kelly_is_half_of_full(self):
        full = KellyCriterion(max_fraction=1.0)
        half_k = FractionalKelly(kelly_fraction=0.5)
        full_result = full.compute(0.6, 4.0, 2.0, 10000.0, n_trades=50)
        half_result = half_k.compute(0.6, 4.0, 2.0, 10000.0, n_trades=50)
        assert abs(half_result.position_fraction - full_result.position_fraction * 0.5) < 1e-5

    def test_quarter_kelly(self):
        qk = FractionalKelly(kelly_fraction=0.25)
        result = qk.compute(0.6, 4.0, 2.0, 10000.0, n_trades=50)
        assert result.position_fraction > 0.0
        assert f"0.25" in result.method or "0.25" in result.rationale

    def test_fraction_in_range(self):
        fk = FractionalKelly(kelly_fraction=0.5)
        result = fk.compute(0.7, 6.0, 2.0, 50000.0, n_trades=100)
        assert 0.0 <= result.position_fraction <= 1.0
        assert result.position_dollars <= 50000.0


# ---------------------------------------------------------------------------
# VolatilityScaledSizing
# ---------------------------------------------------------------------------


class TestVolatilityScaledSizing:
    def setup_method(self):
        self.sizer = VolatilityScaledSizing(
            target_volatility=0.15,
            base_fraction=0.10,
            max_fraction=0.30,
        )

    def test_invalid_target_vol(self):
        with pytest.raises(ValueError):
            VolatilityScaledSizing(target_volatility=0.0)

    def test_invalid_portfolio_value(self):
        with pytest.raises(ValueError):
            self.sizer.compute(0.0, [0.01, 0.02])

    def test_insufficient_history_uses_base(self):
        result = self.sizer.compute(10000.0, [0.01, 0.02])  # only 2 obs
        assert result.position_fraction == pytest.approx(0.10, abs=1e-6)
        assert "insufficient" in result.rationale.lower()

    def test_high_vol_reduces_size(self):
        # Daily vol of 3% → annual ~47% → well above 15% target → smaller position
        daily_vol = [0.03, -0.03, 0.03, -0.03, 0.03, -0.03, 0.03, -0.03, 0.03, -0.03]
        result = self.sizer.compute(10000.0, daily_vol)
        assert result.position_fraction < 0.10  # below base_fraction

    def test_low_vol_increases_size(self):
        # Daily vol of 0.1% → annual ~1.6% → well below 15% target → larger position
        daily_returns = [0.001, -0.001, 0.001, -0.001, 0.001, -0.001, 0.001, -0.001]
        result = self.sizer.compute(10000.0, daily_returns)
        assert result.position_fraction > 0.10  # above base_fraction
        assert result.position_fraction <= 0.30  # capped at max

    def test_max_fraction_cap(self):
        zero_vol = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        result = self.sizer.compute(10000.0, zero_vol)
        assert result.position_fraction <= self.sizer.max_fraction

    def test_method_label(self):
        result = self.sizer.compute(10000.0, [0.01] * 10)
        assert result.method == "vol_scaled"

    def test_position_dollars_consistent(self):
        returns = [0.01, -0.01, 0.02, -0.01, 0.01, -0.02, 0.01, 0.0, -0.01, 0.01]
        result = self.sizer.compute(10000.0, returns)
        assert abs(result.position_dollars - result.position_fraction * 10000.0) < 0.01


# ---------------------------------------------------------------------------
# MaxLossSizing
# ---------------------------------------------------------------------------


class TestMaxLossSizing:
    def setup_method(self):
        self.sizer = MaxLossSizing(
            portfolio_risk_pct=0.02,
            fallback_max_loss_pct=0.50,
            max_fraction=0.20,
        )

    def test_invalid_portfolio_risk(self):
        with pytest.raises(ValueError):
            MaxLossSizing(portfolio_risk_pct=0.0)
        with pytest.raises(ValueError):
            MaxLossSizing(portfolio_risk_pct=1.5)

    def test_invalid_fallback_max_loss(self):
        with pytest.raises(ValueError):
            MaxLossSizing(fallback_max_loss_pct=0.0)

    def test_invalid_portfolio_value(self):
        with pytest.raises(ValueError):
            self.sizer.compute(portfolio_value=-100.0)

    def test_basic_sizing(self):
        # 2% risk / 50% max_loss = 4% fraction
        result = self.sizer.compute(10000.0)
        assert result.position_fraction == pytest.approx(0.04, abs=0.001)
        assert result.position_dollars == pytest.approx(400.0, abs=0.01)

    def test_provided_max_loss(self):
        # 2% risk / 100% max_loss (debit option) = 2% fraction
        result = self.sizer.compute(10000.0, max_loss_pct=1.0)
        assert result.position_fraction == pytest.approx(0.02, abs=0.001)

    def test_max_fraction_cap(self):
        # Very small max_loss_pct → huge raw fraction → capped
        result = self.sizer.compute(10000.0, max_loss_pct=0.001)
        assert result.position_fraction <= 0.20

    def test_method_label(self):
        result = self.sizer.compute(10000.0)
        assert result.method == "max_loss"

    def test_dollars_consistent(self):
        result = self.sizer.compute(25000.0, max_loss_pct=0.50)
        assert abs(result.position_dollars - result.position_fraction * 25000.0) < 0.01


# ---------------------------------------------------------------------------
# PositionSizingEngine
# ---------------------------------------------------------------------------


class TestPositionSizingEngine:
    def _make_engine(self, blend: str = "min") -> PositionSizingEngine:
        return PositionSizingEngine(
            use_kelly=True,
            use_fractional_kelly=True,
            use_vol_scaled=True,
            use_max_loss=True,
            blend_method=blend,
            max_position_fraction=0.25,
        )

    def test_min_blend(self):
        engine = self._make_engine("min")
        result = engine.recommend(
            symbol="TSLA",
            portfolio_value=10000.0,
            signal_confidence=0.7,
            win_rate=0.60,
            avg_win=5.0,
            avg_loss=3.0,
            n_trades=50,
            return_series=[0.01, -0.01, 0.02, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01],
        )
        assert result.symbol == "TSLA"
        assert result.portfolio_value == 10000.0
        assert 0.0 < result.final_fraction <= 0.25
        assert len(result.individual_results) == 4
        assert result.blend_method == "min"

    def test_mean_blend(self):
        engine = self._make_engine("mean")
        result = engine.recommend(
            "AAPL", 20000.0, signal_confidence=0.8,
            win_rate=0.55, avg_win=4.0, avg_loss=3.0, n_trades=30,
        )
        assert 0.0 < result.final_fraction <= 0.25
        assert result.blend_method == "mean"

    def test_weighted_blend(self):
        engine = PositionSizingEngine(
            blend_method="weighted",
            method_weights={"kelly_full": 2.0, "max_loss": 1.0},
        )
        result = engine.recommend(
            "SPY", 50000.0, signal_confidence=0.6,
            win_rate=0.50, avg_win=3.0, avg_loss=3.0, n_trades=20,
        )
        assert result.blend_method == "weighted"
        assert 0.0 < result.final_fraction <= 0.25

    def test_low_confidence_reduces_size(self):
        engine = self._make_engine("mean")
        high_conf = engine.recommend(
            "X", 10000.0, signal_confidence=1.0,
            win_rate=0.6, avg_win=5.0, avg_loss=2.0, n_trades=50,
        )
        low_conf = engine.recommend(
            "X", 10000.0, signal_confidence=0.1,
            win_rate=0.6, avg_win=5.0, avg_loss=2.0, n_trades=50,
        )
        assert low_conf.final_fraction < high_conf.final_fraction

    def test_risk_flags_emitted(self):
        engine = self._make_engine()
        result = engine.recommend(
            "X", 10000.0, signal_confidence=0.10,  # very low
            win_rate=0.30, avg_win=2.0, avg_loss=3.0, n_trades=5,
        )
        assert len(result.risk_flags) > 0
        assert any("confidence" in f for f in result.risk_flags)
        assert any("history" in f for f in result.risk_flags)
        assert any("win_rate" in f for f in result.risk_flags)

    def test_no_risk_flags_good_inputs(self):
        engine = self._make_engine()
        result = engine.recommend(
            "SPY", 100000.0, signal_confidence=0.80,
            win_rate=0.60, avg_win=5.0, avg_loss=2.0, n_trades=100,
        )
        assert result.risk_flags == []

    def test_max_fraction_cap(self):
        engine = PositionSizingEngine(max_position_fraction=0.10)
        result = engine.recommend(
            "X", 10000.0, signal_confidence=1.0,
            win_rate=0.99, avg_win=100.0, avg_loss=0.1, n_trades=200,
        )
        assert result.final_fraction <= 0.10

    def test_no_methods_enabled(self):
        engine = PositionSizingEngine(
            use_kelly=False,
            use_fractional_kelly=False,
            use_vol_scaled=False,
            use_max_loss=False,
        )
        result = engine.recommend("X", 10000.0)
        assert result.final_fraction > 0.0  # minimum default applied
        assert len(result.individual_results) == 0

    def test_invalid_portfolio_value(self):
        engine = self._make_engine()
        with pytest.raises(ValueError):
            engine.recommend("X", portfolio_value=0.0)

    def test_dollars_consistent(self):
        engine = self._make_engine()
        result = engine.recommend(
            "NVDA", 50000.0, signal_confidence=0.7,
            win_rate=0.55, avg_win=4.0, avg_loss=3.0, n_trades=40,
        )
        assert abs(result.final_dollars - result.final_fraction * 50000.0) < 0.01

    def test_confidence_field_stored(self):
        engine = self._make_engine()
        result = engine.recommend("X", 10000.0, signal_confidence=0.75)
        assert result.signal_confidence == 0.75
