"""Correlation-based trading signals.

Detects regime shifts, mean-reversion opportunities, and breakdown events
based on rolling Pearson correlations between price series.
"""

from __future__ import annotations

import math
import unittest


class CorrelationTrader:
    """Generate trading signals from rolling pair correlations."""

    # ------------------------------------------------------------------
    # Core computations
    # ------------------------------------------------------------------

    @staticmethod
    def _pearson(x: list[float], y: list[float]) -> float:
        """Pearson correlation between two equal-length lists."""
        n = len(x)
        if n < 2:
            return 0.0
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        std_x = math.sqrt(sum((v - mean_x) ** 2 for v in x))
        std_y = math.sqrt(sum((v - mean_y) ** 2 for v in y))
        denom = std_x * std_y
        if denom < 1e-12:
            return 0.0
        return cov / denom

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rolling_correlation(
        self,
        series_a: list[float],
        series_b: list[float],
        window: int,
    ) -> list[float]:
        """Rolling Pearson correlation over `window` observations.

        Returns a list of the same length as the inputs; the first
        (window - 1) entries are NaN since we don't have enough data.
        """
        n = len(series_a)
        if len(series_b) != n:
            raise ValueError("series_a and series_b must have the same length")

        result: list[float] = [float("nan")] * n
        for i in range(window - 1, n):
            win_a = series_a[i - window + 1 : i + 1]
            win_b = series_b[i - window + 1 : i + 1]
            result[i] = self._pearson(win_a, win_b)
        return result

    def detect_correlation_regime(
        self,
        correlations: list[float],
        threshold_high: float = 0.7,
        threshold_low: float = 0.3,
    ) -> list[str]:
        """Classify each correlation value as HIGH / LOW / NORMAL.

        NaN values (insufficient window) are labelled NORMAL.
        """
        result: list[str] = []
        for c in correlations:
            if math.isnan(c):
                result.append("NORMAL")
            elif abs(c) >= threshold_high:
                result.append("HIGH")
            elif abs(c) <= threshold_low:
                result.append("LOW")
            else:
                result.append("NORMAL")
        return result

    def mean_reversion_signal(
        self,
        corr: float,
        historical_mean: float,
        historical_std: float,
    ) -> str:
        """Generate a spread mean-reversion signal.

        When correlation is far above historical mean: spread likely to narrow
        → BUY_SPREAD (bet on convergence, i.e. buy laggard/sell leader).
        When correlation is far below historical mean: spread likely to widen
        → SELL_SPREAD (bet on divergence).
        Otherwise → NEUTRAL.
        """
        if historical_std < 1e-12:
            return "NEUTRAL"
        z = (corr - historical_mean) / historical_std
        if z > 1.0:
            return "BUY_SPREAD"
        if z < -1.0:
            return "SELL_SPREAD"
        return "NEUTRAL"

    def correlation_breakdown_signal(
        self,
        correlations: list[float],
        window: int = 20,
    ) -> list[bool]:
        """Return True at each index where correlation breaks down (> 2σ move).

        Uses a rolling mean and std (computed over the last `window` valid
        correlation values) to detect anomalous correlation shifts.
        NaN entries are treated as False.
        """
        n = len(correlations)
        result: list[bool] = [False] * n

        valid: list[float] = []
        for i in range(n):
            c = correlations[i]
            if math.isnan(c):
                continue
            valid.append(c)
            if len(valid) < window + 1:
                continue
            # Compute stats over the previous `window` values (not including current).
            history = valid[-(window + 1) : -1]
            mean_h = sum(history) / len(history)
            std_h = math.sqrt(
                sum((v - mean_h) ** 2 for v in history) / max(len(history) - 1, 1)
            )
            if std_h < 1e-12:
                continue
            z = abs(c - mean_h) / std_h
            if z > 2.0:
                result[i] = True

        return result

    def pairs_spread(
        self,
        prices_a: list[float],
        prices_b: list[float],
        hedge_ratio: float,
    ) -> list[float]:
        """Compute the spread series: spread_t = price_a_t - hedge_ratio * price_b_t."""
        if len(prices_a) != len(prices_b):
            raise ValueError("prices_a and prices_b must have the same length")
        return [prices_a[i] - hedge_ratio * prices_b[i] for i in range(len(prices_a))]


# ─── TESTS ────────────────────────────────────────────────────────────────────

class TestCorrelationTrader(unittest.TestCase):

    def setUp(self) -> None:
        self.trader = CorrelationTrader()

    # rolling_correlation ---------------------------------------------------

    def test_rolling_correlation_perfect_positive(self) -> None:
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [2.0, 4.0, 6.0, 8.0, 10.0]  # b = 2*a
        corr = self.trader.rolling_correlation(a, b, window=3)
        self.assertAlmostEqual(corr[4], 1.0, places=9)

    def test_rolling_correlation_perfect_negative(self) -> None:
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [-1.0, -2.0, -3.0, -4.0, -5.0]
        corr = self.trader.rolling_correlation(a, b, window=3)
        self.assertAlmostEqual(corr[4], -1.0, places=9)

    def test_rolling_correlation_nan_for_early_values(self) -> None:
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [1.0, 2.0, 3.0, 4.0, 5.0]
        corr = self.trader.rolling_correlation(a, b, window=3)
        self.assertTrue(math.isnan(corr[0]))
        self.assertTrue(math.isnan(corr[1]))
        self.assertFalse(math.isnan(corr[2]))

    def test_rolling_correlation_length_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            self.trader.rolling_correlation([1.0, 2.0], [1.0], window=2)

    # detect_correlation_regime ---------------------------------------------

    def test_detect_regime_high(self) -> None:
        regimes = self.trader.detect_correlation_regime([0.85, -0.9])
        self.assertEqual(regimes, ["HIGH", "HIGH"])

    def test_detect_regime_low(self) -> None:
        regimes = self.trader.detect_correlation_regime([0.1, -0.2])
        self.assertEqual(regimes, ["LOW", "LOW"])

    def test_detect_regime_normal(self) -> None:
        regimes = self.trader.detect_correlation_regime([0.5, -0.5])
        self.assertEqual(regimes, ["NORMAL", "NORMAL"])

    def test_detect_regime_nan_is_normal(self) -> None:
        regimes = self.trader.detect_correlation_regime([float("nan")])
        self.assertEqual(regimes, ["NORMAL"])

    # mean_reversion_signal -------------------------------------------------

    def test_mean_reversion_signal_buy_spread(self) -> None:
        # corr = 0.9, mean = 0.5, std = 0.2 → z = (0.9-0.5)/0.2 = 2.0 > 1 → BUY
        signal = self.trader.mean_reversion_signal(0.9, 0.5, 0.2)
        self.assertEqual(signal, "BUY_SPREAD")

    def test_mean_reversion_signal_sell_spread(self) -> None:
        # corr = 0.1, mean = 0.5, std = 0.2 → z = (0.1-0.5)/0.2 = -2.0 < -1 → SELL
        signal = self.trader.mean_reversion_signal(0.1, 0.5, 0.2)
        self.assertEqual(signal, "SELL_SPREAD")

    def test_mean_reversion_signal_neutral(self) -> None:
        signal = self.trader.mean_reversion_signal(0.5, 0.5, 0.2)
        self.assertEqual(signal, "NEUTRAL")

    def test_mean_reversion_signal_zero_std(self) -> None:
        signal = self.trader.mean_reversion_signal(0.9, 0.5, 0.0)
        self.assertEqual(signal, "NEUTRAL")

    # correlation_breakdown_signal ------------------------------------------

    def test_correlation_breakdown_returns_same_length(self) -> None:
        corrs = [0.5] * 30
        result = self.trader.correlation_breakdown_signal(corrs, window=10)
        self.assertEqual(len(result), 30)

    def test_correlation_breakdown_detects_spike(self) -> None:
        # Stable at 0.5 for 25 values, then a sudden spike to -0.8.
        stable = [0.5] * 25
        spike = stable + [-0.8, -0.8]
        result = self.trader.correlation_breakdown_signal(spike, window=20)
        # At least one True in the spiked region.
        self.assertTrue(any(result[25:]))

    def test_correlation_breakdown_no_breakdown(self) -> None:
        # All values the same → no breakdown.
        corrs = [0.6] * 50
        result = self.trader.correlation_breakdown_signal(corrs, window=10)
        self.assertFalse(any(result))

    # pairs_spread ----------------------------------------------------------

    def test_pairs_spread_simple(self) -> None:
        a = [10.0, 11.0, 12.0]
        b = [5.0, 5.5, 6.0]
        spread = self.trader.pairs_spread(a, b, hedge_ratio=2.0)
        expected = [0.0, 0.0, 0.0]
        for s, e in zip(spread, expected):
            self.assertAlmostEqual(s, e, places=9)

    def test_pairs_spread_length_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            self.trader.pairs_spread([1.0, 2.0], [1.0], hedge_ratio=1.0)

    def test_pairs_spread_nonzero(self) -> None:
        spread = self.trader.pairs_spread([100.0, 101.0], [50.0, 50.5], hedge_ratio=1.5)
        self.assertAlmostEqual(spread[0], 100.0 - 1.5 * 50.0, places=9)


if __name__ == "__main__":
    unittest.main()
