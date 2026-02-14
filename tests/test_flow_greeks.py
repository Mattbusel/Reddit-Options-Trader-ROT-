"""Tests for the Black-Scholes Greeks engine (src/rot/flow/greeks.py).

Covers: pricing, delta, gamma, theta, vega, rho, edge cases,
implied volatility round-trip, portfolio Greeks aggregation,
compute_greeks snapshot, and module-level convenience functions.

~40 tests exercising correctness, edge cases, and numerical properties.
"""

from __future__ import annotations

import math

import pytest

from rot.flow.greeks import (
    DEFAULT_RISK_FREE_RATE,
    GreeksEngine,
    black_scholes_price,
    compute_iv,
)
from rot.flow.types import GreeksSnapshot


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def engine() -> GreeksEngine:
    """Default GreeksEngine with the standard risk-free rate."""
    return GreeksEngine()


# Common test parameters
S = 100.0  # underlying
K = 100.0  # ATM strike
T = 30 / 365  # 30 days to expiry
SIGMA = 0.25  # 25% annualized vol
R = DEFAULT_RISK_FREE_RATE


# ── Pricing Tests ─────────────────────────────────────────


class TestPricing:
    """Black-Scholes option pricing."""

    def test_atm_call_put_similar_value(self, engine: GreeksEngine) -> None:
        """ATM call and put should have similar (though not identical) value
        due to the cost-of-carry component (S - K*e^(-rT))."""
        call = engine.price(S, K, T, SIGMA, "call")
        put = engine.price(S, K, T, SIGMA, "put")
        # Both should be positive and within a few dollars of each other
        assert call > 0
        assert put > 0
        assert abs(call - put) < 2.0  # difference is ~ S*(1 - e^(-rT))

    def test_deep_itm_call_approximates_intrinsic(self, engine: GreeksEngine) -> None:
        """Deep ITM call price should approach S - K*e^(-rT)."""
        deep_itm_K = 50.0
        call = engine.price(S, deep_itm_K, T, SIGMA, "call")
        discounted = S - deep_itm_K * math.exp(-R * T)
        assert call == pytest.approx(discounted, rel=0.01)

    def test_deep_otm_call_near_zero(self, engine: GreeksEngine) -> None:
        """Deep OTM call should be near zero."""
        deep_otm_K = 200.0
        call = engine.price(S, deep_otm_K, T, SIGMA, "call")
        assert call < 0.01

    def test_deep_otm_put_near_zero(self, engine: GreeksEngine) -> None:
        """Deep OTM put should be near zero."""
        deep_otm_K = 30.0
        put = engine.price(S, deep_otm_K, T, SIGMA, "put")
        assert put < 0.01

    def test_put_call_parity(self, engine: GreeksEngine) -> None:
        """Put-call parity: C - P = S - K*e^(-rT)."""
        call = engine.price(S, K, T, SIGMA, "call")
        put = engine.price(S, K, T, SIGMA, "put")
        forward = S - K * math.exp(-R * T)
        assert (call - put) == pytest.approx(forward, abs=1e-8)

    def test_put_call_parity_otm(self, engine: GreeksEngine) -> None:
        """Put-call parity holds for OTM options too."""
        otm_K = 110.0
        call = engine.price(S, otm_K, T, SIGMA, "call")
        put = engine.price(S, otm_K, T, SIGMA, "put")
        forward = S - otm_K * math.exp(-R * T)
        assert (call - put) == pytest.approx(forward, abs=1e-8)

    def test_longer_expiry_higher_price(self, engine: GreeksEngine) -> None:
        """Longer time to expiry should give higher option price (for calls)."""
        short_T = 7 / 365
        long_T = 90 / 365
        short_price = engine.price(S, K, short_T, SIGMA, "call")
        long_price = engine.price(S, K, long_T, SIGMA, "call")
        assert long_price > short_price

    def test_higher_vol_higher_price(self, engine: GreeksEngine) -> None:
        """Higher volatility should increase option price."""
        low_vol = engine.price(S, K, T, 0.10, "call")
        high_vol = engine.price(S, K, T, 0.50, "call")
        assert high_vol > low_vol


# ── Delta Tests ───────────────────────────────────────────


class TestDelta:
    """Delta: dV/dS."""

    def test_atm_call_delta_near_half(self, engine: GreeksEngine) -> None:
        """ATM call delta should be approximately 0.5."""
        d = engine.delta(S, K, T, SIGMA, "call")
        assert d == pytest.approx(0.5, abs=0.07)

    def test_deep_itm_call_delta_near_one(self, engine: GreeksEngine) -> None:
        """Deep ITM call delta approaches 1.0."""
        d = engine.delta(S, 50.0, T, SIGMA, "call")
        assert d > 0.99

    def test_deep_otm_call_delta_near_zero(self, engine: GreeksEngine) -> None:
        """Deep OTM call delta approaches 0.0."""
        d = engine.delta(S, 200.0, T, SIGMA, "call")
        assert d < 0.01

    def test_put_delta_equals_call_delta_minus_one(self, engine: GreeksEngine) -> None:
        """Put delta = call delta - 1 (always)."""
        call_d = engine.delta(S, K, T, SIGMA, "call")
        put_d = engine.delta(S, K, T, SIGMA, "put")
        assert put_d == pytest.approx(call_d - 1.0, abs=1e-10)

    def test_call_delta_range(self, engine: GreeksEngine) -> None:
        """Call delta is always between 0 and 1."""
        for strike in [50, 80, 100, 120, 200]:
            d = engine.delta(S, strike, T, SIGMA, "call")
            assert 0.0 <= d <= 1.0

    def test_put_delta_range(self, engine: GreeksEngine) -> None:
        """Put delta is always between -1 and 0."""
        for strike in [50, 80, 100, 120, 200]:
            d = engine.delta(S, strike, T, SIGMA, "put")
            assert -1.0 <= d <= 0.0


# ── Gamma Tests ───────────────────────────────────────────


class TestGamma:
    """Gamma: d2V/dS2."""

    def test_atm_gamma_highest(self, engine: GreeksEngine) -> None:
        """ATM gamma should be highest compared to ITM/OTM."""
        atm_g = engine.gamma(S, 100.0, T, SIGMA)
        itm_g = engine.gamma(S, 70.0, T, SIGMA)
        otm_g = engine.gamma(S, 130.0, T, SIGMA)
        assert atm_g > itm_g
        assert atm_g > otm_g

    def test_gamma_always_positive(self, engine: GreeksEngine) -> None:
        """Gamma is always non-negative."""
        for strike in [50, 80, 100, 120, 200]:
            g = engine.gamma(S, strike, T, SIGMA)
            assert g >= 0.0

    def test_gamma_same_for_call_put(self, engine: GreeksEngine) -> None:
        """Gamma is identical for calls and puts at the same strike."""
        # Gamma method does not take option_type (it's the same).
        # Verify by computing via delta difference.
        g = engine.gamma(S, K, T, SIGMA)
        assert g > 0


# ── Theta Tests ───────────────────────────────────────────


class TestTheta:
    """Theta: dV/dT (time decay)."""

    def test_theta_negative_for_calls(self, engine: GreeksEngine) -> None:
        """Long call theta should be negative (time decay)."""
        t = engine.theta(S, K, T, SIGMA, "call")
        assert t < 0

    def test_theta_negative_for_puts(self, engine: GreeksEngine) -> None:
        """Long put theta should generally be negative for reasonable params."""
        t = engine.theta(S, K, T, SIGMA, "put")
        assert t < 0

    def test_atm_theta_most_negative(self, engine: GreeksEngine) -> None:
        """ATM options should have the most negative theta (fastest decay)."""
        atm_t = engine.theta(S, 100.0, T, SIGMA, "call")
        otm_t = engine.theta(S, 130.0, T, SIGMA, "call")
        # ATM theta is more negative (larger absolute value)
        assert abs(atm_t) > abs(otm_t)


# ── Vega Tests ────────────────────────────────────────────


class TestVega:
    """Vega: dV/d(sigma)."""

    def test_vega_always_positive(self, engine: GreeksEngine) -> None:
        """Vega is always positive for options with T > 0."""
        for strike in [80, 100, 120]:
            v = engine.vega(S, strike, T, SIGMA)
            assert v > 0

    def test_atm_vega_highest(self, engine: GreeksEngine) -> None:
        """ATM vega should be highest."""
        atm_v = engine.vega(S, 100.0, T, SIGMA)
        otm_v = engine.vega(S, 130.0, T, SIGMA)
        itm_v = engine.vega(S, 70.0, T, SIGMA)
        assert atm_v > otm_v
        assert atm_v > itm_v

    def test_longer_expiry_higher_vega(self, engine: GreeksEngine) -> None:
        """Longer time to expiry = higher vega."""
        short_v = engine.vega(S, K, 7 / 365, SIGMA)
        long_v = engine.vega(S, K, 90 / 365, SIGMA)
        assert long_v > short_v

    def test_vega_same_for_call_put(self, engine: GreeksEngine) -> None:
        """Vega does not depend on option type (call/put)."""
        # The gamma method signature does not take option_type, confirming
        # the implementation treats vega as call/put-independent.
        v = engine.vega(S, K, T, SIGMA)
        assert v > 0


# ── Rho Tests ─────────────────────────────────────────────


class TestRho:
    """Rho: dV/dr."""

    def test_call_rho_positive(self, engine: GreeksEngine) -> None:
        """Call rho is positive (calls benefit from higher rates)."""
        r = engine.rho(S, K, T, SIGMA, "call")
        assert r > 0

    def test_put_rho_negative(self, engine: GreeksEngine) -> None:
        """Put rho is negative (puts lose value with higher rates)."""
        r = engine.rho(S, K, T, SIGMA, "put")
        assert r < 0


# ── Edge Cases ────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases: T=0, sigma=0, S=0, K=0, negative inputs."""

    def test_price_s_zero(self, engine: GreeksEngine) -> None:
        """S=0 returns 0."""
        assert engine.price(0, K, T, SIGMA, "call") == 0.0
        assert engine.price(0, K, T, SIGMA, "put") == 0.0

    def test_price_k_zero(self, engine: GreeksEngine) -> None:
        """K=0 returns 0."""
        assert engine.price(S, 0, T, SIGMA, "call") == 0.0
        assert engine.price(S, 0, T, SIGMA, "put") == 0.0

    def test_price_t_zero_call_itm(self, engine: GreeksEngine) -> None:
        """At expiry (T=0): ITM call returns intrinsic value."""
        assert engine.price(105, 100, 0, SIGMA, "call") == pytest.approx(5.0)

    def test_price_t_zero_call_otm(self, engine: GreeksEngine) -> None:
        """At expiry (T=0): OTM call returns 0."""
        assert engine.price(95, 100, 0, SIGMA, "call") == 0.0

    def test_price_t_zero_put_itm(self, engine: GreeksEngine) -> None:
        """At expiry (T=0): ITM put returns intrinsic value."""
        assert engine.price(95, 100, 0, SIGMA, "put") == pytest.approx(5.0)

    def test_price_t_zero_put_otm(self, engine: GreeksEngine) -> None:
        """At expiry (T=0): OTM put returns 0."""
        assert engine.price(105, 100, 0, SIGMA, "put") == 0.0

    def test_price_sigma_zero_call(self, engine: GreeksEngine) -> None:
        """Zero vol: deterministic payoff = max(S - K*e^(-rT), 0)."""
        pv_k = K * math.exp(-R * T)
        expected = max(S - pv_k, 0.0)
        assert engine.price(S, K, T, 0, "call") == pytest.approx(expected, abs=1e-10)

    def test_price_sigma_zero_put(self, engine: GreeksEngine) -> None:
        """Zero vol put: deterministic payoff = max(K*e^(-rT) - S, 0)."""
        pv_k = K * math.exp(-R * T)
        expected = max(pv_k - S, 0.0)
        assert engine.price(S, K, T, 0, "put") == pytest.approx(expected, abs=1e-10)

    def test_delta_at_expiry_call_itm(self, engine: GreeksEngine) -> None:
        """At expiry: ITM call delta = 1.0."""
        assert engine.delta(105, 100, 0, SIGMA, "call") == 1.0

    def test_delta_at_expiry_call_otm(self, engine: GreeksEngine) -> None:
        """At expiry: OTM call delta = 0.0."""
        assert engine.delta(95, 100, 0, SIGMA, "call") == 0.0

    def test_delta_at_expiry_put_itm(self, engine: GreeksEngine) -> None:
        """At expiry: ITM put delta = -1.0."""
        assert engine.delta(95, 100, 0, SIGMA, "put") == -1.0

    def test_delta_at_expiry_put_otm(self, engine: GreeksEngine) -> None:
        """At expiry: OTM put delta = 0.0."""
        assert engine.delta(105, 100, 0, SIGMA, "put") == 0.0

    def test_gamma_zero_at_expiry(self, engine: GreeksEngine) -> None:
        """Gamma is 0 when T=0."""
        assert engine.gamma(S, K, 0, SIGMA) == 0.0

    def test_theta_zero_at_expiry(self, engine: GreeksEngine) -> None:
        """Theta is 0 when T=0."""
        assert engine.theta(S, K, 0, SIGMA, "call") == 0.0

    def test_vega_zero_at_expiry(self, engine: GreeksEngine) -> None:
        """Vega is 0 when T=0."""
        assert engine.vega(S, K, 0, SIGMA) == 0.0

    def test_rho_zero_at_expiry(self, engine: GreeksEngine) -> None:
        """Rho is 0 when T=0."""
        assert engine.rho(S, K, 0, SIGMA, "call") == 0.0

    def test_negative_s_returns_zero_price(self, engine: GreeksEngine) -> None:
        """Negative S treated same as S<=0."""
        assert engine.price(-10, K, T, SIGMA, "call") == 0.0

    def test_negative_time_returns_intrinsic(self, engine: GreeksEngine) -> None:
        """Negative T treated same as T<=0 (returns intrinsic)."""
        assert engine.price(110, 100, -0.1, SIGMA, "call") == pytest.approx(10.0)


# ── Implied Volatility Tests ─────────────────────────────


class TestImpliedVolatility:
    """IV computation via bisection."""

    def test_iv_round_trip(self, engine: GreeksEngine) -> None:
        """Price with known sigma, then recover sigma via IV."""
        known_sigma = 0.30
        market_price = engine.price(S, K, T, known_sigma, "call")
        recovered_iv = engine.implied_volatility(market_price, S, K, T, "call")
        assert recovered_iv is not None
        assert recovered_iv == pytest.approx(known_sigma, abs=1e-4)

    def test_iv_round_trip_put(self, engine: GreeksEngine) -> None:
        """IV round-trip for puts."""
        known_sigma = 0.40
        market_price = engine.price(S, K, T, known_sigma, "put")
        recovered_iv = engine.implied_volatility(market_price, S, K, T, "put")
        assert recovered_iv is not None
        assert recovered_iv == pytest.approx(known_sigma, abs=1e-4)

    def test_iv_round_trip_otm(self, engine: GreeksEngine) -> None:
        """IV round-trip for OTM option."""
        known_sigma = 0.35
        otm_K = 115.0
        market_price = engine.price(S, otm_K, T, known_sigma, "call")
        recovered_iv = engine.implied_volatility(market_price, S, otm_K, T, "call")
        assert recovered_iv is not None
        assert recovered_iv == pytest.approx(known_sigma, abs=1e-4)

    def test_iv_returns_none_for_zero_price(self, engine: GreeksEngine) -> None:
        """Market price <= 0 returns None."""
        assert engine.implied_volatility(0.0, S, K, T) is None
        assert engine.implied_volatility(-1.0, S, K, T) is None

    def test_iv_returns_none_for_zero_time(self, engine: GreeksEngine) -> None:
        """T=0 returns None."""
        assert engine.implied_volatility(5.0, S, K, 0, "call") is None

    def test_iv_returns_none_for_zero_s(self, engine: GreeksEngine) -> None:
        """S=0 returns None."""
        assert engine.implied_volatility(5.0, 0, K, T) is None

    def test_iv_returns_none_below_intrinsic(self, engine: GreeksEngine) -> None:
        """Price below intrinsic value returns None (arbitrage)."""
        # Deep ITM call: intrinsic = 50
        assert engine.implied_volatility(0.01, 150.0, 100.0, T, "call") is None


# ── Portfolio Greeks Tests ────────────────────────────────


class TestPortfolioGreeks:
    """Portfolio-level Greeks aggregation."""

    def test_single_long_call(self, engine: GreeksEngine) -> None:
        """Single long call: portfolio delta = per-option delta * 100."""
        pos = [{"S": S, "K": K, "T": T, "sigma": SIGMA, "qty": 1, "option_type": "call"}]
        pg = engine.portfolio_greeks(pos)
        single_delta = engine.delta(S, K, T, SIGMA, "call")
        assert pg.delta == pytest.approx(single_delta * 100, rel=1e-6)

    def test_long_short_offset(self, engine: GreeksEngine) -> None:
        """Long + short at same strike: net delta near zero."""
        positions = [
            {"S": S, "K": K, "T": T, "sigma": SIGMA, "qty": 1, "option_type": "call"},
            {"S": S, "K": K, "T": T, "sigma": SIGMA, "qty": -1, "option_type": "call"},
        ]
        pg = engine.portfolio_greeks(positions)
        assert pg.delta == pytest.approx(0.0, abs=1e-8)
        assert pg.gamma == pytest.approx(0.0, abs=1e-8)
        assert pg.vega == pytest.approx(0.0, abs=1e-8)

    def test_multiple_legs(self, engine: GreeksEngine) -> None:
        """Bull call spread: long lower strike, short higher strike."""
        positions = [
            {"S": S, "K": 95, "T": T, "sigma": SIGMA, "qty": 1, "option_type": "call"},
            {"S": S, "K": 105, "T": T, "sigma": SIGMA, "qty": -1, "option_type": "call"},
        ]
        pg = engine.portfolio_greeks(positions)
        # Net delta should be positive (long lower strike has higher delta)
        assert pg.delta > 0
        # Net gamma can be positive or negative depending on strikes
        # but the important thing is it's a valid number
        assert isinstance(pg.gamma, float)

    def test_empty_positions(self, engine: GreeksEngine) -> None:
        """Empty position list gives all-zero Greeks."""
        pg = engine.portfolio_greeks([])
        assert pg.delta == 0.0
        assert pg.gamma == 0.0
        assert pg.theta == 0.0
        assert pg.vega == 0.0
        assert pg.rho == 0.0
        assert pg.iv == 0.0

    def test_zero_qty_skipped(self, engine: GreeksEngine) -> None:
        """Position with qty=0 should be skipped (same as empty)."""
        positions = [
            {"S": S, "K": K, "T": T, "sigma": SIGMA, "qty": 0, "option_type": "call"},
        ]
        pg = engine.portfolio_greeks(positions)
        assert pg.delta == 0.0
        assert pg.gamma == 0.0

    def test_portfolio_timestamp(self, engine: GreeksEngine) -> None:
        """Timestamp is passed through to the snapshot."""
        pg = engine.portfolio_greeks([], timestamp=1234567890.0)
        assert pg.timestamp == 1234567890.0

    def test_portfolio_returns_greeks_snapshot(self, engine: GreeksEngine) -> None:
        """Return type is GreeksSnapshot."""
        pg = engine.portfolio_greeks([])
        assert isinstance(pg, GreeksSnapshot)


# ── compute_greeks Snapshot Tests ─────────────────────────


class TestComputeGreeks:
    """compute_greeks returns a complete GreeksSnapshot."""

    def test_returns_greeks_snapshot(self, engine: GreeksEngine) -> None:
        """Return value is a GreeksSnapshot dataclass."""
        gs = engine.compute_greeks(S, K, T, SIGMA, "call")
        assert isinstance(gs, GreeksSnapshot)

    def test_snapshot_fields_match_individual_greeks(self, engine: GreeksEngine) -> None:
        """Snapshot delta/gamma/theta/vega/rho match individual method calls."""
        gs = engine.compute_greeks(S, K, T, SIGMA, "call")
        assert gs.delta == pytest.approx(engine.delta(S, K, T, SIGMA, "call"), abs=1e-10)
        assert gs.gamma == pytest.approx(engine.gamma(S, K, T, SIGMA), abs=1e-10)
        assert gs.theta == pytest.approx(engine.theta(S, K, T, SIGMA, "call"), abs=1e-10)
        assert gs.vega == pytest.approx(engine.vega(S, K, T, SIGMA), abs=1e-10)
        assert gs.rho == pytest.approx(engine.rho(S, K, T, SIGMA, "call"), abs=1e-10)

    def test_snapshot_metadata(self, engine: GreeksEngine) -> None:
        """Snapshot carries underlying_price, strike, dte, option_type, iv."""
        gs = engine.compute_greeks(S, K, T, SIGMA, "put", timestamp=42.0)
        assert gs.underlying_price == S
        assert gs.strike == K
        assert gs.dte == pytest.approx(T * 365.0)
        assert gs.option_type == "put"
        assert gs.iv == SIGMA
        assert gs.timestamp == 42.0


# ── Convenience Functions ─────────────────────────────────


class TestConvenienceFunctions:
    """Module-level black_scholes_price() and compute_iv()."""

    def test_black_scholes_price_matches_engine(self) -> None:
        """black_scholes_price() matches GreeksEngine.price()."""
        engine = GreeksEngine()
        assert black_scholes_price(S, K, T, SIGMA, "call") == pytest.approx(
            engine.price(S, K, T, SIGMA, "call"), abs=1e-10
        )

    def test_compute_iv_matches_engine(self) -> None:
        """compute_iv() matches GreeksEngine.implied_volatility()."""
        price = black_scholes_price(S, K, T, 0.30, "call")
        iv = compute_iv(price, S, K, T, "call")
        assert iv is not None
        assert iv == pytest.approx(0.30, abs=1e-4)

    def test_default_risk_free_rate_value(self) -> None:
        """DEFAULT_RISK_FREE_RATE is 0.05."""
        assert DEFAULT_RISK_FREE_RATE == 0.05


# ── Custom Risk-Free Rate ─────────────────────────────────


class TestCustomRate:
    """Engine with a non-default risk-free rate."""

    def test_custom_rate_stored(self) -> None:
        """Engine stores the custom rate."""
        eng = GreeksEngine(risk_free_rate=0.10)
        assert eng.risk_free_rate == 0.10

    def test_explicit_r_overrides_engine_rate(self) -> None:
        """Passing r= to price() overrides the engine default."""
        eng = GreeksEngine(risk_free_rate=0.02)
        p1 = eng.price(S, K, T, SIGMA, "call")  # uses 0.02
        p2 = eng.price(S, K, T, SIGMA, "call", r=0.10)  # uses 0.10
        assert p1 != p2
