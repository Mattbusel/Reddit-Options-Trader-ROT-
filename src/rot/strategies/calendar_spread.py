"""Calendar spread options strategy builder and analyser."""

from __future__ import annotations

import math
import unittest
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CalendarSpreadLegs:
    """Defines a calendar spread position (same strike, two expiries)."""

    symbol: str
    strike: float
    near_expiry: str   # ISO date string, e.g. "2025-06-20"
    far_expiry: str    # ISO date string, e.g. "2025-09-19"
    option_type: str   # "call" or "put"
    quantity: int      # number of spreads (positive = long far / short near)


@dataclass
class CalendarSpreadAnalysis:
    """Profit-and-loss analytics for a calendar spread."""

    max_profit_estimate: float  # approx peak P&L at near expiry with stock at strike
    max_loss: float             # net debit paid (worst case)
    breakeven_price: float      # approximate underlying price at breakeven
    theta_advantage: float      # daily theta edge (long far - short near)
    vega_exposure: float        # net vega (positive = long vega)
    net_debit: float            # premium paid to enter the spread


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class CalendarSpreadBuilder:
    """Build, analyse, and manage calendar spread positions."""

    # -----------------------------------------------------------------------
    # Construction helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def build(
        symbol: str,
        strike: float,
        near_expiry: str,
        far_expiry: str,
        option_type: str = "call",
        quantity: int = 1,
    ) -> CalendarSpreadLegs:
        """Create a CalendarSpreadLegs object.

        Args:
            symbol: Underlying ticker symbol.
            strike: Strike price for both legs.
            near_expiry: Expiry date of the short (near-term) leg.
            far_expiry: Expiry date of the long (far-term) leg.
            option_type: "call" or "put".
            quantity: Number of spreads.

        Returns:
            CalendarSpreadLegs representing the position.

        Raises:
            ValueError: If option_type is not "call" or "put".
        """
        if option_type not in ("call", "put"):
            raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        return CalendarSpreadLegs(
            symbol=symbol,
            strike=strike,
            near_expiry=near_expiry,
            far_expiry=far_expiry,
            option_type=option_type,
            quantity=quantity,
        )

    # -----------------------------------------------------------------------
    # Analysis
    # -----------------------------------------------------------------------

    @staticmethod
    def analyze(
        legs: CalendarSpreadLegs,
        near_iv: float,
        far_iv: float,
        underlying_price: float,
        days_to_near: int,
    ) -> CalendarSpreadAnalysis:
        """Estimate the P&L profile of a calendar spread.

        Uses a simplified Black-Scholes-inspired framework to estimate key
        metrics without requiring a full options pricing library.

        Args:
            legs: The calendar spread structure.
            near_iv: Implied volatility of the near-term leg (annualised, e.g. 0.25).
            far_iv: Implied volatility of the far-term leg.
            underlying_price: Current price of the underlying.
            days_to_near: Calendar days until near-leg expiry.

        Returns:
            CalendarSpreadAnalysis with estimated metrics.
        """
        t_near = max(days_to_near, 1) / 365.0
        t_far = t_near + 30.0 / 365.0  # assume far is ~30 days beyond near

        # Approximate option price via simplified BSM intrinsic+time value
        near_price = _approx_option_price(
            underlying_price, legs.strike, t_near, near_iv, legs.option_type
        )
        far_price = _approx_option_price(
            underlying_price, legs.strike, t_far, far_iv, legs.option_type
        )

        net_debit = (far_price - near_price) * legs.quantity * 100  # per contract

        # Max profit: near leg expires worthless at strike, far retains value
        max_profit_estimate = far_price * legs.quantity * 100 - net_debit

        # Max loss is capped at the net debit paid
        max_loss = net_debit

        # Theta: near-term theta is higher (time decay faster)
        near_theta = _approx_theta(underlying_price, legs.strike, t_near, near_iv)
        far_theta = _approx_theta(underlying_price, legs.strike, t_far, far_iv)
        theta_advantage = CalendarSpreadBuilder.theta_decay_advantage(near_theta, far_theta)

        # Vega: long far, short near — net long vega (far vega > near vega)
        near_vega = _approx_vega(underlying_price, legs.strike, t_near, near_iv)
        far_vega = _approx_vega(underlying_price, legs.strike, t_far, far_iv)
        vega_exposure = (far_vega - near_vega) * legs.quantity

        # Breakeven: approx as strike +/- 0.5 * near_iv * S * sqrt(t_near)
        be_offset = 0.5 * near_iv * underlying_price * math.sqrt(t_near)
        breakeven_price = underlying_price + be_offset if underlying_price < legs.strike else underlying_price - be_offset

        return CalendarSpreadAnalysis(
            max_profit_estimate=max_profit_estimate,
            max_loss=max_loss,
            breakeven_price=breakeven_price,
            theta_advantage=theta_advantage,
            vega_exposure=vega_exposure,
            net_debit=net_debit,
        )

    # -----------------------------------------------------------------------
    # Rolling
    # -----------------------------------------------------------------------

    @staticmethod
    def roll_forward(
        legs: CalendarSpreadLegs,
        new_near_expiry: str,
        new_far_expiry: str,
    ) -> CalendarSpreadLegs:
        """Roll both legs forward to new expiry dates.

        Preserves strike, symbol, option_type, and quantity.

        Args:
            legs: Existing calendar spread legs.
            new_near_expiry: New near-term expiry date.
            new_far_expiry: New far-term expiry date.

        Returns:
            A new CalendarSpreadLegs with updated expiries.
        """
        return CalendarSpreadLegs(
            symbol=legs.symbol,
            strike=legs.strike,
            near_expiry=new_near_expiry,
            far_expiry=new_far_expiry,
            option_type=legs.option_type,
            quantity=legs.quantity,
        )

    # -----------------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------------

    @staticmethod
    def optimal_strike(underlying_price: float, near_iv: float) -> float:
        """Return the optimal (near-ATM) strike for a calendar spread.

        Rounds to the nearest standard strike increment based on price level.

        Args:
            underlying_price: Current underlying price.
            near_iv: Near-term implied volatility (informational, for future use).

        Returns:
            ATM or near-ATM strike price.
        """
        _ = near_iv  # reserved for IV-skew-adjusted ATM computation
        if underlying_price < 20:
            increment = 0.5
        elif underlying_price < 100:
            increment = 1.0
        elif underlying_price < 500:
            increment = 5.0
        else:
            increment = 10.0
        return round(underlying_price / increment) * increment

    @staticmethod
    def theta_decay_advantage(near_theta: float, far_theta: float) -> float:
        """Compute the daily theta edge of a long calendar spread.

        We are short the near leg (fast decay) and long the far leg (slow decay).
        The advantage is the extra decay collected: near_theta - far_theta.

        Args:
            near_theta: Daily theta of the near-term option (negative for long options).
            far_theta: Daily theta of the far-term option.

        Returns:
            Positive value indicates net theta collection.
        """
        return abs(near_theta) - abs(far_theta)


# ---------------------------------------------------------------------------
# Private pricing helpers (simplified BSM approximations)
# ---------------------------------------------------------------------------


def _approx_option_price(
    s: float, k: float, t: float, iv: float, option_type: str
) -> float:
    """Approximate option price using a simplified ATM formula."""
    intrinsic = max(s - k, 0.0) if option_type == "call" else max(k - s, 0.0)
    time_value = s * iv * math.sqrt(t) * 0.4  # ~N(d1) at ATM ≈ 0.4
    return intrinsic + time_value


def _approx_theta(s: float, k: float, t: float, iv: float) -> float:
    """Approximate daily theta (negative for long option)."""
    if t <= 0:
        return 0.0
    # dV/dt ≈ -S*σ/(2*sqrt(T)) per year, divide by 365 for daily
    return -(s * iv) / (2.0 * math.sqrt(t) * 365.0)


def _approx_vega(s: float, k: float, t: float, iv: float) -> float:
    """Approximate vega (change in price per 1% change in IV)."""
    return s * math.sqrt(t) * 0.4 * 0.01  # N(d1) ≈ 0.4 at ATM


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCalendarSpreadBuilder(unittest.TestCase):
    def setUp(self):
        self.builder = CalendarSpreadBuilder()
        self.legs = CalendarSpreadBuilder.build(
            symbol="AAPL",
            strike=150.0,
            near_expiry="2025-06-20",
            far_expiry="2025-09-19",
            option_type="call",
            quantity=2,
        )

    def test_build_basic(self):
        self.assertEqual(self.legs.symbol, "AAPL")
        self.assertEqual(self.legs.strike, 150.0)
        self.assertEqual(self.legs.quantity, 2)
        self.assertEqual(self.legs.option_type, "call")

    def test_build_put(self):
        legs = CalendarSpreadBuilder.build("SPY", 400.0, "2025-06-20", "2025-09-19", "put", 1)
        self.assertEqual(legs.option_type, "put")

    def test_build_invalid_option_type(self):
        with self.assertRaises(ValueError):
            CalendarSpreadBuilder.build("X", 100.0, "2025-06-20", "2025-09-19", "future", 1)

    def test_build_invalid_quantity(self):
        with self.assertRaises(ValueError):
            CalendarSpreadBuilder.build("X", 100.0, "2025-06-20", "2025-09-19", "call", 0)

    def test_analyze_returns_analysis(self):
        analysis = CalendarSpreadBuilder.analyze(self.legs, 0.25, 0.28, 148.0, 30)
        self.assertIsInstance(analysis, CalendarSpreadAnalysis)

    def test_analyze_max_loss_is_debit(self):
        analysis = CalendarSpreadBuilder.analyze(self.legs, 0.25, 0.28, 150.0, 30)
        self.assertAlmostEqual(analysis.max_loss, analysis.net_debit)

    def test_analyze_theta_advantage_positive(self):
        analysis = CalendarSpreadBuilder.analyze(self.legs, 0.30, 0.28, 150.0, 10)
        # Near-term theta decays faster — advantage should be positive
        self.assertGreater(analysis.theta_advantage, 0)

    def test_analyze_vega_positive(self):
        analysis = CalendarSpreadBuilder.analyze(self.legs, 0.25, 0.28, 150.0, 30)
        # Long calendar is long vega
        self.assertGreater(analysis.vega_exposure, 0)

    def test_roll_forward(self):
        rolled = CalendarSpreadBuilder.roll_forward(self.legs, "2025-09-19", "2025-12-19")
        self.assertEqual(rolled.near_expiry, "2025-09-19")
        self.assertEqual(rolled.far_expiry, "2025-12-19")
        self.assertEqual(rolled.strike, self.legs.strike)
        self.assertEqual(rolled.symbol, self.legs.symbol)

    def test_roll_preserves_quantity(self):
        rolled = CalendarSpreadBuilder.roll_forward(self.legs, "2025-09-19", "2025-12-19")
        self.assertEqual(rolled.quantity, self.legs.quantity)

    def test_optimal_strike_rounds_to_increment(self):
        strike = CalendarSpreadBuilder.optimal_strike(149.7, 0.25)
        self.assertEqual(strike, 150.0)

    def test_optimal_strike_large_price(self):
        strike = CalendarSpreadBuilder.optimal_strike(502.0, 0.2)
        self.assertEqual(strike % 10, 0)

    def test_theta_decay_advantage(self):
        adv = CalendarSpreadBuilder.theta_decay_advantage(-0.05, -0.02)
        self.assertAlmostEqual(adv, 0.03)

    def test_theta_decay_advantage_zero(self):
        adv = CalendarSpreadBuilder.theta_decay_advantage(-0.03, -0.03)
        self.assertAlmostEqual(adv, 0.0)


if __name__ == "__main__":
    unittest.main()
