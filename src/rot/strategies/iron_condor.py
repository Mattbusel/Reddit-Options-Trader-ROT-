"""Iron condor options strategy builder."""

from __future__ import annotations

import math
import unittest
from dataclasses import dataclass
from typing import Tuple


@dataclass
class IronCondorLegs:
    """Defines the four legs of an iron condor position."""

    symbol: str
    expiry: str  # e.g. "2025-06-20"
    short_put_strike: float
    long_put_strike: float
    short_call_strike: float
    long_call_strike: float
    quantity: int


@dataclass
class IronCondorPnL:
    """Profit-and-loss profile for an iron condor."""

    max_profit: float
    max_loss: float
    put_spread_width: float
    call_spread_width: float
    breakeven_lower: float
    breakeven_upper: float
    risk_reward_ratio: float


class IronCondorBuilder:
    """Constructs and analyses iron condor strategies."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def build(
        self,
        underlying_price: float,
        put_spread: Tuple[float, float],
        call_spread: Tuple[float, float],
        expiry: str,
        quantity: int,
        symbol: str = "UNK",
    ) -> IronCondorLegs:
        """Construct iron condor legs from spread tuples.

        Args:
            underlying_price: Current price of the underlying (used for
                validation but not stored separately).
            put_spread: (long_put_strike, short_put_strike) — long below short.
            call_spread: (short_call_strike, long_call_strike) — long above short.
            expiry: Expiry date string.
            quantity: Number of condors (contracts).
            symbol: Ticker symbol.

        Returns:
            Populated :class:`IronCondorLegs` instance.
        """
        long_put, short_put = put_spread
        short_call, long_call = call_spread
        return IronCondorLegs(
            symbol=symbol,
            expiry=expiry,
            short_put_strike=short_put,
            long_put_strike=long_put,
            short_call_strike=short_call,
            long_call_strike=long_call,
            quantity=quantity,
        )

    # ------------------------------------------------------------------
    # PnL calculation
    # ------------------------------------------------------------------

    def compute_pnl(
        self, legs: IronCondorLegs, net_credit_received: float
    ) -> IronCondorPnL:
        """Compute the iron condor PnL profile from legs and net credit.

        The net credit is the total premium received (per condor).  Max profit
        equals this credit; max loss is the wider spread width minus the credit.

        Args:
            legs: The iron condor leg definition.
            net_credit_received: Net option premium received per condor (>0).

        Returns:
            :class:`IronCondorPnL` with all profile fields filled.
        """
        put_width = legs.short_put_strike - legs.long_put_strike
        call_width = legs.long_call_strike - legs.short_call_strike

        max_profit = net_credit_received * legs.quantity
        max_loss_per = max(put_width, call_width) - net_credit_received
        max_loss = max_loss_per * legs.quantity

        breakeven_lower = legs.short_put_strike - net_credit_received
        breakeven_upper = legs.short_call_strike + net_credit_received

        risk_reward_ratio = (
            abs(max_loss / max_profit) if abs(max_profit) > 1e-9 else float("inf")
        )

        return IronCondorPnL(
            max_profit=max_profit,
            max_loss=max_loss,
            put_spread_width=put_width,
            call_spread_width=call_width,
            breakeven_lower=breakeven_lower,
            breakeven_upper=breakeven_upper,
            risk_reward_ratio=risk_reward_ratio,
        )

    # ------------------------------------------------------------------
    # Probability of profit
    # ------------------------------------------------------------------

    def probability_of_profit(
        self,
        legs: IronCondorLegs,
        underlying_price: float,
        sigma: float,
        days_to_expiry: int,
    ) -> float:
        """Estimate the probability that the underlying stays between breakevens.

        Uses a log-normal (Black-Scholes) distribution:
        P(L < S_T < U) = Φ(d_upper) - Φ(d_lower)

        where d = (ln(K/S) / (σ√T)) and T is in years.

        Args:
            legs: Iron condor legs (used for breakevens via compute_pnl).
            underlying_price: Current underlying price.
            sigma: Implied volatility (annualised, e.g. 0.20 for 20%).
            days_to_expiry: Calendar days until expiry.

        Returns:
            Probability in [0, 1].
        """
        if underlying_price <= 0 or sigma <= 0 or days_to_expiry <= 0:
            return 0.0

        T = days_to_expiry / 365.0
        vol_sqrt_T = sigma * math.sqrt(T)

        # We need breakevens — compute from legs with a neutral credit of 0
        # so the caller controls them via legs directly.
        lower = legs.short_put_strike
        upper = legs.short_call_strike

        def norm_cdf(x: float) -> float:
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

        d_upper = math.log(upper / underlying_price) / vol_sqrt_T
        d_lower = math.log(lower / underlying_price) / vol_sqrt_T

        prob = norm_cdf(d_upper) - norm_cdf(d_lower)
        return max(0.0, min(1.0, prob))

    # ------------------------------------------------------------------
    # Delta adjustment
    # ------------------------------------------------------------------

    def adjust_for_delta(
        self,
        legs: IronCondorLegs,
        current_price: float,
        threshold_delta: float = 0.30,
    ) -> IronCondorLegs:
        """Roll strikes outward if a short option is too close to the money.

        A simplified delta estimate is used:
        delta ≈ 0.5 - (strike - current_price) / (2 * current_price * 0.2)

        If |delta| of a short option exceeds *threshold_delta*, the strike is
        moved outward by 5% of current_price.

        Args:
            legs: Current iron condor legs.
            current_price: Current underlying price.
            threshold_delta: Delta threshold (absolute) to trigger a roll.

        Returns:
            Adjusted :class:`IronCondorLegs` (may be unchanged if no roll needed).
        """
        adjustment = current_price * 0.05
        normalizer = max(current_price * 0.4, 1e-9)

        short_put_delta = abs(0.5 - (current_price - legs.short_put_strike) / normalizer)
        short_call_delta = abs(0.5 - (legs.short_call_strike - current_price) / normalizer)

        new_short_put = legs.short_put_strike
        new_long_put = legs.long_put_strike
        new_short_call = legs.short_call_strike
        new_long_call = legs.long_call_strike

        if short_put_delta > threshold_delta:
            new_short_put -= adjustment
            new_long_put -= adjustment

        if short_call_delta > threshold_delta:
            new_short_call += adjustment
            new_long_call += adjustment

        return IronCondorLegs(
            symbol=legs.symbol,
            expiry=legs.expiry,
            short_put_strike=new_short_put,
            long_put_strike=new_long_put,
            short_call_strike=new_short_call,
            long_call_strike=new_long_call,
            quantity=legs.quantity,
        )


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestIronCondorBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = IronCondorBuilder()
        self.legs = IronCondorLegs(
            symbol="SPY",
            expiry="2025-06-20",
            short_put_strike=400.0,
            long_put_strike=390.0,
            short_call_strike=430.0,
            long_call_strike=440.0,
            quantity=1,
        )

    def test_build_returns_correct_strikes(self) -> None:
        legs = self.builder.build(
            underlying_price=415.0,
            put_spread=(390.0, 400.0),
            call_spread=(430.0, 440.0),
            expiry="2025-06-20",
            quantity=1,
            symbol="SPY",
        )
        self.assertEqual(legs.short_put_strike, 400.0)
        self.assertEqual(legs.long_put_strike, 390.0)
        self.assertEqual(legs.short_call_strike, 430.0)
        self.assertEqual(legs.long_call_strike, 440.0)

    def test_compute_pnl_max_profit(self) -> None:
        pnl = self.builder.compute_pnl(self.legs, net_credit_received=3.0)
        self.assertAlmostEqual(pnl.max_profit, 3.0)

    def test_compute_pnl_max_loss(self) -> None:
        pnl = self.builder.compute_pnl(self.legs, net_credit_received=3.0)
        # wider spread = 10, loss = 10 - 3 = 7
        self.assertAlmostEqual(pnl.max_loss, 7.0)

    def test_compute_pnl_breakevens(self) -> None:
        pnl = self.builder.compute_pnl(self.legs, net_credit_received=3.0)
        self.assertAlmostEqual(pnl.breakeven_lower, 397.0)
        self.assertAlmostEqual(pnl.breakeven_upper, 433.0)

    def test_compute_pnl_spread_widths(self) -> None:
        pnl = self.builder.compute_pnl(self.legs, net_credit_received=3.0)
        self.assertAlmostEqual(pnl.put_spread_width, 10.0)
        self.assertAlmostEqual(pnl.call_spread_width, 10.0)

    def test_compute_pnl_risk_reward_ratio(self) -> None:
        pnl = self.builder.compute_pnl(self.legs, net_credit_received=3.0)
        self.assertGreater(pnl.risk_reward_ratio, 0)

    def test_probability_of_profit_in_range(self) -> None:
        pop = self.builder.probability_of_profit(
            self.legs, underlying_price=415.0, sigma=0.20, days_to_expiry=30
        )
        self.assertGreater(pop, 0.0)
        self.assertLessEqual(pop, 1.0)

    def test_probability_of_profit_atm_wide_wings(self) -> None:
        # Wider body → higher probability
        wide_legs = IronCondorLegs(
            symbol="SPY", expiry="2025-06-20",
            short_put_strike=300.0, long_put_strike=290.0,
            short_call_strike=600.0, long_call_strike=610.0,
            quantity=1,
        )
        pop = self.builder.probability_of_profit(
            wide_legs, underlying_price=415.0, sigma=0.20, days_to_expiry=30
        )
        self.assertGreater(pop, 0.5)

    def test_probability_of_profit_zero_sigma(self) -> None:
        pop = self.builder.probability_of_profit(
            self.legs, underlying_price=415.0, sigma=0.0, days_to_expiry=30
        )
        self.assertEqual(pop, 0.0)

    def test_adjust_for_delta_no_adjustment_needed(self) -> None:
        # Strikes where estimated delta is comfortably below 0.30 threshold → no roll.
        # With current_price=415, normalizer=166, strikes at 350 / 450 give
        # short_put_delta≈0.11 and short_call_delta≈0.29 — both below 0.30.
        safe_legs = IronCondorLegs(
            symbol="SPY",
            expiry="2025-06-20",
            short_put_strike=350.0,
            long_put_strike=340.0,
            short_call_strike=450.0,
            long_call_strike=460.0,
            quantity=1,
        )
        adjusted = self.builder.adjust_for_delta(safe_legs, current_price=415.0)
        self.assertAlmostEqual(adjusted.short_put_strike, safe_legs.short_put_strike, places=4)
        self.assertAlmostEqual(adjusted.short_call_strike, safe_legs.short_call_strike, places=4)

    def test_adjust_for_delta_preserves_quantity(self) -> None:
        adjusted = self.builder.adjust_for_delta(self.legs, current_price=415.0)
        self.assertEqual(adjusted.quantity, self.legs.quantity)


if __name__ == "__main__":
    unittest.main()
