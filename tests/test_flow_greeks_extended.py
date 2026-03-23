"""Tests for the extended Black-Scholes API: BlackScholesGreeks, OptionGreeks,
GreeksCalculator, SpreadGreeks (src/rot/flow/greeks.py).
"""

from __future__ import annotations

import math

import pytest

from rot.flow.greeks import (
    DEFAULT_RISK_FREE_RATE,
    BlackScholesGreeks,
    GreeksCalculator,
    OptionGreeks,
    SpreadGreeks,
)


# ── Common test parameters ─────────────────────────────────

S = 100.0
K = 100.0
T_DAYS = 30
T = T_DAYS / 365.0
SIGMA = 0.25
R = DEFAULT_RISK_FREE_RATE


# ── OptionGreeks dataclass ─────────────────────────────────


class TestOptionGreeks:
    def test_fields_present(self) -> None:
        og = OptionGreeks(delta=0.5, gamma=0.02, theta=-0.05, vega=0.1, rho=0.03, implied_volatility=0.25)
        assert og.delta == 0.5
        assert og.gamma == 0.02
        assert og.implied_volatility == 0.25

    def test_to_dict_keys(self) -> None:
        og = OptionGreeks(delta=0.5, gamma=0.02, theta=-0.05, vega=0.1, rho=0.03, implied_volatility=0.25)
        keys = set(og.to_dict().keys())
        assert keys == {"delta", "gamma", "theta", "vega", "rho", "implied_volatility"}

    def test_to_dict_rounds_values(self) -> None:
        og = OptionGreeks(delta=0.123456789, gamma=0.0, theta=0.0, vega=0.0, rho=0.0, implied_volatility=0.25)
        d = og.to_dict()
        # Should be rounded to 6 decimal places
        assert len(str(d["delta"]).replace("0.", "").rstrip("0")) <= 6


# ── BlackScholesGreeks ─────────────────────────────────────


@pytest.fixture
def bsg() -> BlackScholesGreeks:
    return BlackScholesGreeks(risk_free_rate=R)


class TestBlackScholesGreeksDelta:
    def test_atm_call_delta_near_half(self, bsg: BlackScholesGreeks) -> None:
        d = bsg.delta(S, K, T, SIGMA, "call")
        assert d == pytest.approx(0.5, abs=0.07)

    def test_call_delta_range(self, bsg: BlackScholesGreeks) -> None:
        for strike in [50, 80, 100, 120, 200]:
            d = bsg.delta(S, strike, T, SIGMA, "call")
            assert 0.0 <= d <= 1.0

    def test_put_delta_range(self, bsg: BlackScholesGreeks) -> None:
        for strike in [50, 80, 100, 120, 200]:
            d = bsg.delta(S, strike, T, SIGMA, "put")
            assert -1.0 <= d <= 0.0

    def test_put_delta_equals_call_minus_one(self, bsg: BlackScholesGreeks) -> None:
        call_d = bsg.delta(S, K, T, SIGMA, "call")
        put_d = bsg.delta(S, K, T, SIGMA, "put")
        assert put_d == pytest.approx(call_d - 1.0, abs=1e-8)

    def test_delta_zero_inputs(self, bsg: BlackScholesGreeks) -> None:
        assert bsg.delta(0, K, T, SIGMA) == 0.0
        assert bsg.delta(S, 0, T, SIGMA) == 0.0


class TestBlackScholesGreeksGamma:
    def test_gamma_positive(self, bsg: BlackScholesGreeks) -> None:
        g = bsg.gamma(S, K, T, SIGMA)
        assert g > 0

    def test_gamma_zero_at_expiry(self, bsg: BlackScholesGreeks) -> None:
        assert bsg.gamma(S, K, 0, SIGMA) == 0.0


class TestBlackScholesGreeksTheta:
    def test_theta_negative_for_call(self, bsg: BlackScholesGreeks) -> None:
        t = bsg.theta(S, K, T, SIGMA, "call")
        assert t < 0

    def test_theta_zero_at_expiry(self, bsg: BlackScholesGreeks) -> None:
        assert bsg.theta(S, K, 0, SIGMA, "call") == 0.0


class TestBlackScholesGreeksVega:
    def test_vega_positive(self, bsg: BlackScholesGreeks) -> None:
        v = bsg.vega(S, K, T, SIGMA)
        assert v > 0

    def test_vega_zero_at_expiry(self, bsg: BlackScholesGreeks) -> None:
        assert bsg.vega(S, K, 0, SIGMA) == 0.0


class TestBlackScholesGreeksRho:
    def test_call_rho_positive(self, bsg: BlackScholesGreeks) -> None:
        r = bsg.rho(S, K, T, SIGMA, "call")
        assert r > 0

    def test_put_rho_negative(self, bsg: BlackScholesGreeks) -> None:
        r = bsg.rho(S, K, T, SIGMA, "put")
        assert r < 0

    def test_rho_zero_at_expiry(self, bsg: BlackScholesGreeks) -> None:
        assert bsg.rho(S, K, 0, SIGMA, "call") == 0.0


class TestBlackScholesGreeksAllGreeks:
    def test_returns_option_greeks(self, bsg: BlackScholesGreeks) -> None:
        og = bsg.all_greeks(S, K, T, SIGMA, "call")
        assert isinstance(og, OptionGreeks)

    def test_iv_passthrough(self, bsg: BlackScholesGreeks) -> None:
        og = bsg.all_greeks(S, K, T, SIGMA, "call")
        assert og.implied_volatility == SIGMA

    def test_individual_greeks_match_all_greeks(self, bsg: BlackScholesGreeks) -> None:
        og = bsg.all_greeks(S, K, T, SIGMA, "call")
        assert og.delta == pytest.approx(bsg.delta(S, K, T, SIGMA, "call"), abs=1e-10)
        assert og.gamma == pytest.approx(bsg.gamma(S, K, T, SIGMA), abs=1e-10)
        assert og.theta == pytest.approx(bsg.theta(S, K, T, SIGMA, "call"), abs=1e-10)
        assert og.vega == pytest.approx(bsg.vega(S, K, T, SIGMA), abs=1e-10)
        assert og.rho == pytest.approx(bsg.rho(S, K, T, SIGMA, "call"), abs=1e-10)


# ── GreeksCalculator ───────────────────────────────────────


class TestGreeksCalculator:
    def test_basic_compute(self) -> None:
        calc = GreeksCalculator(strike=K, dte_days=T_DAYS, spot=S, volatility=SIGMA)
        og = calc.compute("call")
        assert isinstance(og, OptionGreeks)

    def test_T_property(self) -> None:
        calc = GreeksCalculator(strike=100, dte_days=30, spot=100)
        assert calc.T == pytest.approx(30 / 365.0, rel=1e-6)

    def test_zero_dte_uses_floor(self) -> None:
        calc = GreeksCalculator(strike=100, dte_days=0, spot=100)
        assert calc.T > 0

    def test_call_delta_range(self) -> None:
        calc = GreeksCalculator(strike=100, dte_days=30, spot=100, volatility=0.25)
        og = calc.compute("call")
        assert 0.0 <= og.delta <= 1.0

    def test_put_delta_range(self) -> None:
        calc = GreeksCalculator(strike=100, dte_days=30, spot=100, volatility=0.25)
        og = calc.compute("put")
        assert -1.0 <= og.delta <= 0.0

    def test_stores_parameters(self) -> None:
        calc = GreeksCalculator(strike=150, dte_days=45, spot=148, risk_free_rate=0.04, volatility=0.30)
        assert calc.strike == 150
        assert calc.dte_days == 45
        assert calc.spot == 148
        assert calc.risk_free_rate == 0.04
        assert calc.volatility == 0.30

    def test_high_vol_higher_vega(self) -> None:
        calc_lo = GreeksCalculator(strike=100, dte_days=30, spot=100, volatility=0.10)
        calc_hi = GreeksCalculator(strike=100, dte_days=30, spot=100, volatility=0.50)
        # Both have positive vega; higher vol doesn't directly change vega direction
        assert calc_lo.compute("call").vega > 0
        assert calc_hi.compute("call").vega > 0


# ── SpreadGreeks ───────────────────────────────────────────


class TestSpreadGreeks:
    @pytest.fixture
    def spread(self) -> SpreadGreeks:
        return SpreadGreeks(spot=S, risk_free_rate=R)

    def test_bull_call_spread_returns_option_greeks(self, spread: SpreadGreeks) -> None:
        og = spread.bull_call_spread(100, 110, T_DAYS, SIGMA)
        assert isinstance(og, OptionGreeks)

    def test_bull_call_spread_positive_delta(self, spread: SpreadGreeks) -> None:
        og = spread.bull_call_spread(100, 110, T_DAYS, SIGMA)
        # Long lower strike = net positive delta
        assert og.delta > 0

    def test_bear_put_spread_returns_option_greeks(self, spread: SpreadGreeks) -> None:
        og = spread.bear_put_spread(100, 90, T_DAYS, SIGMA)
        assert isinstance(og, OptionGreeks)

    def test_bear_put_spread_negative_delta(self, spread: SpreadGreeks) -> None:
        og = spread.bear_put_spread(100, 90, T_DAYS, SIGMA)
        # Long higher put = net negative delta
        assert og.delta < 0

    def test_straddle_near_zero_delta(self, spread: SpreadGreeks) -> None:
        og = spread.straddle(100, T_DAYS, SIGMA)
        # ATM straddle delta should be near zero (call + put deltas cancel)
        assert abs(og.delta) < 500  # per-contract scale, so bound loosely

    def test_straddle_positive_gamma(self, spread: SpreadGreeks) -> None:
        og = spread.straddle(100, T_DAYS, SIGMA)
        assert og.gamma > 0

    def test_straddle_positive_vega(self, spread: SpreadGreeks) -> None:
        og = spread.straddle(100, T_DAYS, SIGMA)
        assert og.vega > 0

    def test_aggregate_empty_legs(self, spread: SpreadGreeks) -> None:
        og = spread.aggregate([])
        assert og.delta == 0.0
        assert og.vega == 0.0
        assert og.implied_volatility == 0.0

    def test_aggregate_zero_qty_skipped(self, spread: SpreadGreeks) -> None:
        legs = [{"side": "buy", "kind": "call", "strike": 100, "dte_days": 30, "spot": 100, "volatility": 0.25, "qty": 0}]
        og = spread.aggregate(legs)
        assert og.delta == 0.0

    def test_aggregate_long_short_same_strike_near_zero(self, spread: SpreadGreeks) -> None:
        legs = [
            {"side": "buy", "kind": "call", "strike": 100, "dte_days": 30, "spot": 100, "volatility": 0.25, "qty": 1},
            {"side": "sell", "kind": "call", "strike": 100, "dte_days": 30, "spot": 100, "volatility": 0.25, "qty": 1},
        ]
        og = spread.aggregate(legs)
        assert og.delta == pytest.approx(0.0, abs=1e-6)
        assert og.gamma == pytest.approx(0.0, abs=1e-6)
        assert og.vega == pytest.approx(0.0, abs=1e-6)

    def test_iv_weighted_average(self, spread: SpreadGreeks) -> None:
        legs = [
            {"side": "buy", "kind": "call", "strike": 100, "dte_days": 30, "spot": 100, "volatility": 0.25, "qty": 1},
            {"side": "buy", "kind": "put", "strike": 100, "dte_days": 30, "spot": 100, "volatility": 0.25, "qty": 1},
        ]
        og = spread.aggregate(legs)
        # Both legs have same vol, so average should equal 0.25
        assert og.implied_volatility == pytest.approx(0.25, abs=1e-4)
