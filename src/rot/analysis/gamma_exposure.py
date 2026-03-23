"""Gamma Exposure (GEX) analysis for options markets."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class GexData:
    """Raw data for a single option contract used in GEX calculations."""

    symbol: str
    strike: float
    expiry: str
    option_type: str  # "call" or "put"
    open_interest: float
    gamma: float
    underlying_price: float


class GexAnalyzer:
    """Computes Gamma Exposure (GEX) metrics for a list of option contracts."""

    # ------------------------------------------------------------------
    # Core GEX computation
    # ------------------------------------------------------------------

    def compute_gex(self, data: List[GexData]) -> Dict[float, float]:
        """Compute net GEX per strike.

        Dealer convention:
        - Calls: dealers are short → positive GEX (they buy as price rises).
        - Puts:  dealers are long  → negative GEX (they sell as price falls).

        GEX_contract = gamma * open_interest * underlying_price^2 * 0.01

        Args:
            data: List of option contract data.

        Returns:
            Dictionary mapping strike → net GEX value.
        """
        result: Dict[float, float] = {}
        for d in data:
            gex = d.gamma * d.open_interest * (d.underlying_price ** 2) * 0.01
            if d.option_type.lower() == "put":
                gex = -gex
            result[d.strike] = result.get(d.strike, 0.0) + gex
        return result

    def net_gex(self, data: List[GexData]) -> float:
        """Compute the aggregate net GEX across all contracts.

        Args:
            data: List of option contract data.

        Returns:
            Sum of all GEX values.
        """
        return sum(self.compute_gex(data).values())

    # ------------------------------------------------------------------
    # GEX flip point
    # ------------------------------------------------------------------

    def gex_flip_point(self, data: List[GexData]) -> Optional[float]:
        """Find the strike where net GEX crosses zero (interpolated).

        Scans strikes in ascending order and linearly interpolates between
        consecutive strikes where the GEX changes sign.

        Args:
            data: List of option contract data.

        Returns:
            Interpolated strike of zero GEX crossing, or None if not found.
        """
        gex_map = self.compute_gex(data)
        if not gex_map:
            return None

        sorted_strikes = sorted(gex_map.keys())

        for i in range(len(sorted_strikes) - 1):
            k0 = sorted_strikes[i]
            k1 = sorted_strikes[i + 1]
            g0 = gex_map[k0]
            g1 = gex_map[k1]

            if g0 == 0.0:
                return k0
            if g1 == 0.0:
                return k1

            # Sign change detected
            if g0 * g1 < 0:
                # Linear interpolation: k_flip = k0 + (k1-k0)*(-g0)/(g1-g0)
                return k0 + (k1 - k0) * (-g0) / (g1 - g0)

        return None

    # ------------------------------------------------------------------
    # Largest gamma strikes
    # ------------------------------------------------------------------

    def largest_gamma_strikes(
        self, data: List[GexData], n: int = 5
    ) -> List[Tuple[float, float]]:
        """Return the top *n* strikes by absolute GEX value.

        Args:
            data: List of option contract data.
            n: Number of strikes to return.

        Returns:
            List of (strike, gex) tuples, sorted by |gex| descending.
        """
        gex_map = self.compute_gex(data)
        sorted_items = sorted(gex_map.items(), key=lambda x: abs(x[1]), reverse=True)
        return sorted_items[:n]

    # ------------------------------------------------------------------
    # GEX profile
    # ------------------------------------------------------------------

    def gex_profile(
        self,
        data: List[GexData],
        price_range: Tuple[float, float],
        steps: int = 50,
    ) -> List[Tuple[float, float]]:
        """Compute a GEX profile across a price range.

        For each price point in the range, computes cumulative GEX from all
        strikes up to and including that price.

        Args:
            data: List of option contract data.
            price_range: (low, high) price bounds.
            steps: Number of evenly-spaced price points.

        Returns:
            List of (price, cumulative_gex) tuples.
        """
        low, high = price_range
        if steps <= 0 or low >= high:
            return []

        step_size = (high - low) / max(steps - 1, 1)
        prices = [low + i * step_size for i in range(steps)]

        gex_map = self.compute_gex(data)

        result: List[Tuple[float, float]] = []
        for price in prices:
            cumulative = sum(gex for strike, gex in gex_map.items() if strike <= price)
            result.append((price, cumulative))

        return result


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestGexAnalyzer(unittest.TestCase):
    def _make_call(self, strike: float, oi: float, gamma: float, underlying: float = 100.0) -> GexData:
        return GexData(
            symbol="SPY",
            strike=strike,
            expiry="2025-06-20",
            option_type="call",
            open_interest=oi,
            gamma=gamma,
            underlying_price=underlying,
        )

    def _make_put(self, strike: float, oi: float, gamma: float, underlying: float = 100.0) -> GexData:
        return GexData(
            symbol="SPY",
            strike=strike,
            expiry="2025-06-20",
            option_type="put",
            open_interest=oi,
            gamma=gamma,
            underlying_price=underlying,
        )

    def test_compute_gex_call_is_positive(self) -> None:
        analyzer = GexAnalyzer()
        data = [self._make_call(100.0, 1000.0, 0.05)]
        gex_map = analyzer.compute_gex(data)
        self.assertGreater(gex_map[100.0], 0)

    def test_compute_gex_put_is_negative(self) -> None:
        analyzer = GexAnalyzer()
        data = [self._make_put(100.0, 1000.0, 0.05)]
        gex_map = analyzer.compute_gex(data)
        self.assertLess(gex_map[100.0], 0)

    def test_net_gex_sums_all(self) -> None:
        analyzer = GexAnalyzer()
        data = [
            self._make_call(100.0, 1000.0, 0.05),
            self._make_put(100.0, 1000.0, 0.05),
        ]
        net = analyzer.net_gex(data)
        self.assertAlmostEqual(net, 0.0)

    def test_net_gex_positive_when_calls_dominate(self) -> None:
        analyzer = GexAnalyzer()
        data = [
            self._make_call(100.0, 2000.0, 0.05),
            self._make_put(100.0, 500.0, 0.05),
        ]
        net = analyzer.net_gex(data)
        self.assertGreater(net, 0)

    def test_gex_flip_point_found(self) -> None:
        analyzer = GexAnalyzer()
        data = [
            self._make_call(90.0, 2000.0, 0.10),  # big positive
            self._make_put(110.0, 2000.0, 0.10),  # big negative
        ]
        flip = analyzer.gex_flip_point(data)
        self.assertIsNotNone(flip)
        assert flip is not None
        self.assertGreater(flip, 90.0)
        self.assertLess(flip, 110.0)

    def test_gex_flip_point_none_when_no_crossing(self) -> None:
        analyzer = GexAnalyzer()
        data = [
            self._make_call(90.0, 1000.0, 0.05),
            self._make_call(100.0, 1000.0, 0.05),
        ]
        flip = analyzer.gex_flip_point(data)
        # All positive — no flip
        self.assertIsNone(flip)

    def test_largest_gamma_strikes_count(self) -> None:
        analyzer = GexAnalyzer()
        data = [self._make_call(float(s), 1000.0, 0.01 * (s % 5 + 1)) for s in range(90, 115, 5)]
        top = analyzer.largest_gamma_strikes(data, n=3)
        self.assertEqual(len(top), 3)

    def test_largest_gamma_strikes_sorted_by_abs(self) -> None:
        analyzer = GexAnalyzer()
        data = [
            self._make_call(100.0, 5000.0, 0.10),  # largest
            self._make_call(105.0, 100.0, 0.01),   # smallest
        ]
        top = analyzer.largest_gamma_strikes(data, n=2)
        self.assertEqual(top[0][0], 100.0)

    def test_gex_profile_correct_length(self) -> None:
        analyzer = GexAnalyzer()
        data = [self._make_call(100.0, 1000.0, 0.05)]
        profile = analyzer.gex_profile(data, (90.0, 110.0), steps=20)
        self.assertEqual(len(profile), 20)

    def test_gex_profile_cumulative_increases_past_strike(self) -> None:
        analyzer = GexAnalyzer()
        data = [self._make_call(100.0, 1000.0, 0.05)]
        profile = analyzer.gex_profile(data, (95.0, 110.0), steps=10)
        # Before strike 100 cumulative should be 0, after should be positive
        prices_below = [p for p, g in profile if p < 100.0]
        prices_above = [g for p, g in profile if p >= 100.0]
        if prices_above:
            self.assertGreater(prices_above[0], 0)

    def test_gex_profile_empty_on_invalid_range(self) -> None:
        analyzer = GexAnalyzer()
        data = [self._make_call(100.0, 1000.0, 0.05)]
        profile = analyzer.gex_profile(data, (110.0, 90.0), steps=10)
        self.assertEqual(profile, [])


if __name__ == "__main__":
    unittest.main()
