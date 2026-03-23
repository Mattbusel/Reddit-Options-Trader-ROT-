"""Tests for rot.market.vol_surface."""

from __future__ import annotations

import pytest

from rot.market.vol_surface import (
    IVPercentile,
    IVRank,
    ImpliedVolatilitySurface,
    TermStructure,
    VolatilityRegime,
    VolatilitySmile,
)


# ---------------------------------------------------------------------------
# VolatilitySmile
# ---------------------------------------------------------------------------


class TestVolatilitySmile:
    def setup_method(self):
        self.fitter = VolatilitySmile(wing_moneyness=0.05)

    def test_wing_moneyness_validation(self):
        with pytest.raises(ValueError):
            VolatilitySmile(wing_moneyness=0.0)
        with pytest.raises(ValueError):
            VolatilitySmile(wing_moneyness=0.6)

    def test_basic_fit(self):
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        ivs = [0.30, 0.28, 0.25, 0.27, 0.29]
        result = self.fitter.fit("TSLA", "2026-04-17", 100.0, strikes, ivs)
        assert result.symbol == "TSLA"
        assert result.expiry == "2026-04-17"
        assert result.spot_price == 100.0
        assert result.n_strikes == 5
        assert result.atm_iv == pytest.approx(0.25, abs=0.001)

    def test_unequal_lengths_raises(self):
        with pytest.raises(ValueError):
            self.fitter.fit("X", "2026-01-01", 100.0, [100.0, 105.0], [0.25])

    def test_zero_spot_raises(self):
        with pytest.raises(ValueError):
            self.fitter.fit("X", "2026-01-01", 0.0, [100.0], [0.25])

    def test_skew_put_dominated(self):
        # Put wing higher IV than call wing
        strikes = [85.0, 90.0, 100.0, 110.0, 115.0]
        ivs = [0.40, 0.35, 0.25, 0.22, 0.20]
        result = self.fitter.fit("SPY", "2026-04-17", 100.0, strikes, ivs)
        assert result.skew is not None
        assert result.skew > 0  # put skew

    def test_skew_call_dominated(self):
        strikes = [85.0, 90.0, 100.0, 110.0, 115.0]
        ivs = [0.20, 0.22, 0.25, 0.35, 0.40]
        result = self.fitter.fit("MEME", "2026-04-17", 100.0, strikes, ivs)
        assert result.skew is not None
        assert result.skew < 0  # call wing higher

    def test_no_wings(self):
        # Only ATM strike, no wings
        result = self.fitter.fit("X", "2026-04-17", 100.0, [100.0], [0.25])
        assert result.n_strikes == 1
        assert result.skew is None  # can't compute skew with no wings

    def test_invalid_ivs_filtered(self):
        strikes = [100.0, 105.0, 110.0]
        ivs = [0.25, 0.0, -0.10]  # 0 and negative are invalid
        result = self.fitter.fit("X", "2026-04-17", 100.0, strikes, ivs)
        assert result.n_strikes == 1  # only the 0.25 one survives

    def test_atm_closest_to_spot(self):
        strikes = [90.0, 102.0, 115.0]
        ivs = [0.30, 0.22, 0.28]
        result = self.fitter.fit("X", "2026-04-17", 100.0, strikes, ivs)
        assert result.atm_iv == pytest.approx(0.22, abs=0.001)


# ---------------------------------------------------------------------------
# ImpliedVolatilitySurface
# ---------------------------------------------------------------------------


class TestImpliedVolatilitySurface:
    def setup_method(self):
        self.builder = ImpliedVolatilitySurface()

    def _make_chain(self, ivs: dict[float, float]) -> dict:
        return {
            "strikes": list(ivs.keys()),
            "ivs": list(ivs.values()),
        }

    def test_build_surface(self):
        chains = {
            "2026-04-17": self._make_chain({90: 0.30, 100: 0.25, 110: 0.27}),
            "2026-05-15": self._make_chain({90: 0.32, 100: 0.27, 110: 0.29}),
        }
        surface = self.builder.build("SPY", 100.0, chains)
        assert surface.symbol == "SPY"
        assert len(surface.smiles) == 2
        assert "2026-04-17" in surface.smiles
        assert surface.atm_iv_nearest is not None
        assert len(surface.term_structure) == 2

    def test_empty_chains(self):
        surface = self.builder.build("X", 100.0, {})
        assert len(surface.smiles) == 0
        assert surface.atm_iv_nearest is None

    def test_term_structure_sorted(self):
        chains = {
            "2026-06-20": self._make_chain({100: 0.28}),
            "2026-04-17": self._make_chain({100: 0.25}),
        }
        surface = self.builder.build("AAPL", 100.0, chains)
        exps = [t[0] for t in surface.term_structure]
        assert exps == sorted(exps)

    def test_yfinance_style_chain(self):
        chains = {
            "2026-04-17": {
                "calls": [
                    {"strike": 95.0, "impliedVolatility": 0.28},
                    {"strike": 100.0, "impliedVolatility": 0.25},
                ],
                "puts": [
                    {"strike": 95.0, "impliedVolatility": 0.30},
                    {"strike": 100.0, "impliedVolatility": 0.25},
                ],
            }
        }
        surface = self.builder.build("MSFT", 100.0, chains)
        assert len(surface.smiles) == 1
        assert surface.atm_iv_nearest is not None


# ---------------------------------------------------------------------------
# IVRank
# ---------------------------------------------------------------------------


class TestIVRank:
    def setup_method(self):
        self.calc = IVRank()

    def test_at_high(self):
        result = self.calc.compute("SPY", current_iv=0.40, iv_history=[0.20, 0.25, 0.30, 0.35, 0.40])
        assert abs(result.iv_rank - 1.0) < 0.01
        assert result.iv_rank_pct == pytest.approx(100.0, abs=1.0)

    def test_at_low(self):
        result = self.calc.compute("SPY", current_iv=0.20, iv_history=[0.20, 0.25, 0.30, 0.35, 0.40])
        assert abs(result.iv_rank - 0.0) < 0.01

    def test_midpoint(self):
        result = self.calc.compute("SPY", current_iv=0.30, iv_history=[0.20, 0.25, 0.30, 0.35, 0.40])
        assert abs(result.iv_rank - 0.5) < 0.01

    def test_rank_clamped(self):
        # Current IV above history range
        result = self.calc.compute("X", current_iv=0.50, iv_history=[0.20, 0.30])
        assert result.iv_rank <= 1.0 and result.iv_rank >= 0.0

    def test_empty_history_raises(self):
        with pytest.raises(ValueError):
            self.calc.compute("X", 0.30, [])

    def test_invalid_current_iv_raises(self):
        with pytest.raises(ValueError):
            self.calc.compute("X", 0.0, [0.20, 0.30])

    def test_degenerate_all_same(self):
        result = self.calc.compute("X", 0.25, [0.25] * 10)
        assert result.iv_rank == pytest.approx(0.5, abs=0.01)

    def test_52w_high_low(self):
        history = [0.15 + i * 0.01 for i in range(20)]
        result = self.calc.compute("SPY", 0.25, history)
        assert result.iv_52w_low == pytest.approx(0.15, abs=0.001)
        assert result.iv_52w_high == pytest.approx(0.34, abs=0.001)


# ---------------------------------------------------------------------------
# IVPercentile
# ---------------------------------------------------------------------------


class TestIVPercentile:
    def setup_method(self):
        self.calc = IVPercentile()

    def test_high_percentile(self):
        history = [0.10 + i * 0.01 for i in range(30)]  # 0.10 to 0.39
        result = self.calc.compute("SPY", current_iv=0.38, iv_history=history)
        assert result.iv_percentile > 0.9
        assert result.n_observations == 30

    def test_low_percentile(self):
        history = [0.20 + i * 0.01 for i in range(30)]
        result = self.calc.compute("SPY", current_iv=0.21, iv_history=history)
        assert result.iv_percentile < 0.15

    def test_empty_history_raises(self):
        with pytest.raises(ValueError):
            self.calc.compute("X", 0.25, [])

    def test_invalid_current_iv_raises(self):
        with pytest.raises(ValueError):
            self.calc.compute("X", 0.0, [0.25])

    def test_percentile_in_range(self):
        history = [0.10, 0.15, 0.20, 0.25, 0.30]
        result = self.calc.compute("X", 0.20, history)
        assert 0.0 <= result.iv_percentile <= 1.0
        assert 0.0 <= result.iv_percentile_pct <= 100.0


# ---------------------------------------------------------------------------
# TermStructure
# ---------------------------------------------------------------------------


class TestTermStructure:
    def setup_method(self):
        self.ts = TermStructure()

    def test_contango(self):
        pts = [("2026-04-17", 0.20), ("2026-05-15", 0.24), ("2026-06-20", 0.28)]
        result = self.ts.build("SPY", 100.0, pts)
        assert result.contango is True
        assert result.backwardation is False
        assert result.slope is not None
        assert result.slope > 0

    def test_backwardation(self):
        pts = [("2026-04-17", 0.40), ("2026-05-15", 0.30), ("2026-06-20", 0.20)]
        result = self.ts.build("SPY", 100.0, pts)
        assert result.backwardation is True
        assert result.contango is False
        assert result.slope is not None
        assert result.slope < 0

    def test_flat_term_structure(self):
        pts = [("2026-04-17", 0.25), ("2026-05-15", 0.25), ("2026-06-20", 0.25)]
        result = self.ts.build("SPY", 100.0, pts)
        assert result.contango is False
        assert result.backwardation is False

    def test_empty_input(self):
        result = self.ts.build("X", 100.0, [])
        assert len(result.term_points) == 0
        assert result.slope is None

    def test_single_point(self):
        result = self.ts.build("X", 100.0, [("2026-04-17", 0.25)])
        assert len(result.term_points) == 1
        assert result.slope is None  # need >= 2 points for slope

    def test_sorted_output(self):
        pts = [("2026-06-20", 0.28), ("2026-04-17", 0.20), ("2026-05-15", 0.24)]
        result = self.ts.build("SPY", 100.0, pts)
        exps = [p[0] for p in result.term_points]
        assert exps == sorted(exps)


# ---------------------------------------------------------------------------
# VolatilityRegime
# ---------------------------------------------------------------------------


class TestVolatilityRegime:
    def setup_method(self):
        self.regime = VolatilityRegime(high_threshold=0.60, low_threshold=0.30)

    def test_threshold_validation(self):
        with pytest.raises(ValueError):
            VolatilityRegime(high_threshold=0.30, low_threshold=0.60)

    def test_high_regime(self):
        history = [0.10 + i * 0.01 for i in range(30)]
        result = self.regime.classify("SPY", current_iv=0.38, iv_history=history)
        # IVR = (0.38 - 0.10) / (0.39 - 0.10) ≈ 0.97 → high
        assert result.regime == "high"
        assert result.strategy_bias == "sell_premium"
        assert 0.0 < result.confidence <= 1.0

    def test_low_regime(self):
        history = [0.20 + i * 0.01 for i in range(30)]  # 0.20..0.49
        # current_iv near the low end → IVR ~ 0 (low regime)
        result = self.regime.classify("SPY", current_iv=0.21, iv_history=history)
        assert result.regime in ("low", "normal")  # near boundary

    def test_normal_regime(self):
        history = [0.15 + i * 0.005 for i in range(40)]  # 0.15..0.345
        # mid IV → IVR ≈ 0.5 → normal
        mid_iv = (min(history) + max(history)) / 2
        result = self.regime.classify("SPY", current_iv=mid_iv, iv_history=history)
        assert result.regime == "normal"
        assert result.strategy_bias == "neutral"

    def test_confidence_range(self):
        history = [0.15 + i * 0.01 for i in range(20)]
        result = self.regime.classify("X", 0.25, history)
        assert 0.0 <= result.confidence <= 1.0

    def test_fields_populated(self):
        history = [0.20, 0.25, 0.30, 0.35, 0.40] * 10
        result = self.regime.classify("AAPL", 0.35, history)
        assert result.symbol == "AAPL"
        assert result.current_iv == 0.35
        assert 0.0 <= result.iv_rank <= 1.0
        assert result.regime in ("high", "normal", "low")
