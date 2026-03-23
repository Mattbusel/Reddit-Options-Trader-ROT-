"""ML-based volatility prediction for options trading."""

from __future__ import annotations

import math
import statistics
import unittest
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# VolatilityFeatures
# ---------------------------------------------------------------------------


@dataclass
class VolatilityFeatures:
    """Feature vector for volatility prediction models."""

    realized_vol_5d: float    # 5-day realized volatility (annualised)
    realized_vol_21d: float   # 21-day realized volatility (annualised)
    iv_rank: float            # IV rank [0, 100] over past 52 weeks
    iv_percentile: float      # IV percentile [0, 100]
    vol_of_vol: float         # Volatility-of-volatility (std of daily vol changes)
    skew: float               # 25-delta put skew (put IV - call IV)
    term_structure_slope: float  # (long-term IV - short-term IV) / days


# ---------------------------------------------------------------------------
# VolatilityPredictor
# ---------------------------------------------------------------------------


class VolatilityPredictor:
    """Predict implied and realised volatility from market features."""

    # Long-run mean volatility (annualised) used for mean-reversion blending
    LONG_RUN_MEAN_VOL: float = 0.20

    # Weights for the linear model
    LINEAR_WEIGHTS: dict[str, float] = {
        "realized_vol_5d": 0.35,
        "realized_vol_21d": 0.30,
        "iv_rank": 0.001,           # scaled: iv_rank is 0-100
        "iv_percentile": 0.001,
        "vol_of_vol": 0.15,
        "skew": 0.05,
        "term_structure_slope": 100.0,  # slope is tiny per day
    }

    # -----------------------------------------------------------------------
    # Feature extraction
    # -----------------------------------------------------------------------

    @staticmethod
    def extract_features(
        price_history: list[float],
        option_data: dict,
    ) -> VolatilityFeatures:
        """Extract a VolatilityFeatures vector from raw market data.

        Args:
            price_history: List of closing prices (most recent last).
            option_data: Dict with optional keys: iv_rank, iv_percentile,
                         near_iv, far_iv, days_near, days_far, put_iv, call_iv.

        Returns:
            VolatilityFeatures populated from available data.
        """
        if len(price_history) < 2:
            # Not enough data — return zeros
            return VolatilityFeatures(0, 0, 0, 0, 0, 0, 0)

        returns = _log_returns(price_history)

        rv5 = VolatilityPredictor.realized_volatility(returns, window=min(5, len(returns)))
        rv21 = VolatilityPredictor.realized_volatility(returns, window=min(21, len(returns)))

        iv_rank = float(option_data.get("iv_rank", 50.0))
        iv_percentile = float(option_data.get("iv_percentile", 50.0))

        # Vol-of-vol: std of 5-day rolling vol changes
        vov = _vol_of_vol(returns, window=5)

        # Skew: put IV minus call IV
        put_iv = float(option_data.get("put_iv", 0.25))
        call_iv = float(option_data.get("call_iv", 0.22))
        skew = put_iv - call_iv

        # Term structure slope
        near_iv = float(option_data.get("near_iv", 0.25))
        far_iv = float(option_data.get("far_iv", 0.22))
        days_near = int(option_data.get("days_near", 30))
        days_far = int(option_data.get("days_far", 90))
        slope = VolatilityPredictor.vol_surface_slope(near_iv, far_iv, days_near, days_far)

        return VolatilityFeatures(
            realized_vol_5d=rv5,
            realized_vol_21d=rv21,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            vol_of_vol=vov,
            skew=skew,
            term_structure_slope=slope,
        )

    # -----------------------------------------------------------------------
    # Core metrics
    # -----------------------------------------------------------------------

    @staticmethod
    def realized_volatility(returns: list[float], window: int = 21) -> float:
        """Annualised realised volatility over a rolling window.

        Args:
            returns: List of log returns.
            window: Number of observations.

        Returns:
            Annualised standard deviation of returns.
        """
        if len(returns) < 2:
            return 0.0
        subset = returns[-window:] if len(returns) >= window else returns
        if len(subset) < 2:
            return 0.0
        mean = sum(subset) / len(subset)
        variance = sum((r - mean) ** 2 for r in subset) / (len(subset) - 1)
        return math.sqrt(variance * 252)  # annualise

    # -----------------------------------------------------------------------
    # Prediction
    # -----------------------------------------------------------------------

    @staticmethod
    def predict_vol(
        features: VolatilityFeatures,
        model_type: str = "linear",
    ) -> float:
        """Predict forward volatility from the feature vector.

        Args:
            features: VolatilityFeatures instance.
            model_type: "linear" (weighted sum) or "mean_reversion" (blend).

        Returns:
            Predicted annualised volatility.
        """
        if model_type == "linear":
            w = VolatilityPredictor.LINEAR_WEIGHTS
            pred = (
                w["realized_vol_5d"] * features.realized_vol_5d
                + w["realized_vol_21d"] * features.realized_vol_21d
                + w["iv_rank"] * features.iv_rank
                + w["iv_percentile"] * features.iv_percentile
                + w["vol_of_vol"] * features.vol_of_vol
                + w["skew"] * features.skew
                + w["term_structure_slope"] * features.term_structure_slope
            )
            return max(pred, 0.01)

        elif model_type == "mean_reversion":
            # Ornstein-Uhlenbeck-style blend towards long-run mean
            speed = 0.5  # mean-reversion speed
            current_vol = (features.realized_vol_5d + features.realized_vol_21d) / 2.0
            mu = VolatilityPredictor.LONG_RUN_MEAN_VOL
            pred = current_vol + speed * (mu - current_vol)
            return max(pred, 0.01)

        else:
            raise ValueError(f"Unknown model_type: {model_type!r}")

    # -----------------------------------------------------------------------
    # Regime classification
    # -----------------------------------------------------------------------

    @staticmethod
    def vol_regime_classification(
        vol: float,
        percentile_25: float,
        percentile_75: float,
    ) -> str:
        """Classify the current volatility regime.

        Args:
            vol: Current realised or implied volatility.
            percentile_25: 25th percentile of the historical vol distribution.
            percentile_75: 75th percentile of the historical vol distribution.

        Returns:
            "LOW", "NORMAL", or "HIGH".
        """
        if vol < percentile_25:
            return "LOW"
        elif vol > percentile_75:
            return "HIGH"
        else:
            return "NORMAL"

    # -----------------------------------------------------------------------
    # Term structure
    # -----------------------------------------------------------------------

    @staticmethod
    def vol_surface_slope(
        short_term_vol: float,
        long_term_vol: float,
        days_short: int,
        days_long: int,
    ) -> float:
        """Compute the slope of the volatility term structure.

        A positive slope means vol increases with time (contango).
        A negative slope means vol is in backwardation.

        Args:
            short_term_vol: IV for the near-term maturity.
            long_term_vol: IV for the far-term maturity.
            days_short: DTE for near-term maturity.
            days_long: DTE for far-term maturity.

        Returns:
            Slope in vol/day units.
        """
        delta_days = days_long - days_short
        if delta_days == 0:
            return 0.0
        return (long_term_vol - short_term_vol) / delta_days

    # -----------------------------------------------------------------------
    # Backtesting
    # -----------------------------------------------------------------------

    @staticmethod
    def backtest_predictions(
        price_history: list[float],
        window: int = 21,
    ) -> list[dict]:
        """Roll through price history, predict vol at each step, compare to actual.

        Args:
            price_history: List of closing prices.
            window: Look-back window for realised vol calculation.

        Returns:
            List of dicts with keys: index, predicted_vol, actual_vol, error.
        """
        if len(price_history) < window + 2:
            return []

        returns = _log_returns(price_history)
        results = []

        for i in range(window, len(returns) - window):
            features = VolatilityFeatures(
                realized_vol_5d=VolatilityPredictor.realized_volatility(
                    returns[:i], window=min(5, i)
                ),
                realized_vol_21d=VolatilityPredictor.realized_volatility(
                    returns[:i], window=min(21, i)
                ),
                iv_rank=50.0,
                iv_percentile=50.0,
                vol_of_vol=_vol_of_vol(returns[:i], window=5),
                skew=0.03,
                term_structure_slope=0.0001,
            )
            predicted = VolatilityPredictor.predict_vol(features, model_type="linear")
            actual = VolatilityPredictor.realized_volatility(
                returns[i : i + window], window=window
            )
            results.append(
                {
                    "index": i,
                    "predicted_vol": predicted,
                    "actual_vol": actual,
                    "error": predicted - actual,
                }
            )

        return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _log_returns(prices: list[float]) -> list[float]:
    """Compute log returns from a price series."""
    return [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]


def _vol_of_vol(returns: list[float], window: int = 5) -> float:
    """Compute the standard deviation of rolling realised volatility."""
    if len(returns) < window * 2:
        return 0.0
    rolling_vols = []
    for i in range(window, len(returns)):
        subset = returns[i - window : i]
        mean = sum(subset) / len(subset)
        var = sum((r - mean) ** 2 for r in subset) / max(len(subset) - 1, 1)
        rolling_vols.append(math.sqrt(var * 252))
    if len(rolling_vols) < 2:
        return 0.0
    mean_rv = sum(rolling_vols) / len(rolling_vols)
    vov_var = sum((v - mean_rv) ** 2 for v in rolling_vols) / (len(rolling_vols) - 1)
    return math.sqrt(vov_var)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVolatilityPredictor(unittest.TestCase):
    def _sample_prices(self, n: int = 100) -> list[float]:
        """Generate a simple synthetic price series."""
        prices = [100.0]
        for i in range(1, n):
            prices.append(prices[-1] * (1 + 0.01 * math.sin(i * 0.3) + 0.005))
        return prices

    def test_realized_volatility_positive(self):
        prices = self._sample_prices(50)
        returns = _log_returns(prices)
        rv = VolatilityPredictor.realized_volatility(returns, window=21)
        self.assertGreater(rv, 0)

    def test_realized_volatility_insufficient_data(self):
        rv = VolatilityPredictor.realized_volatility([], window=21)
        self.assertEqual(rv, 0.0)

    def test_realized_volatility_single_return(self):
        rv = VolatilityPredictor.realized_volatility([0.01], window=21)
        self.assertEqual(rv, 0.0)

    def test_extract_features_returns_dataclass(self):
        prices = self._sample_prices(60)
        features = VolatilityPredictor.extract_features(prices, {"iv_rank": 40})
        self.assertIsInstance(features, VolatilityFeatures)

    def test_extract_features_short_history(self):
        features = VolatilityPredictor.extract_features([100.0], {})
        self.assertEqual(features.realized_vol_5d, 0)

    def test_predict_vol_linear_positive(self):
        features = VolatilityFeatures(0.20, 0.18, 45, 50, 0.05, 0.03, 0.0001)
        vol = VolatilityPredictor.predict_vol(features, "linear")
        self.assertGreater(vol, 0)

    def test_predict_vol_mean_reversion(self):
        features = VolatilityFeatures(0.40, 0.38, 80, 85, 0.10, 0.05, 0.0002)
        vol = VolatilityPredictor.predict_vol(features, "mean_reversion")
        # Should be between current and long-run mean
        current = (0.40 + 0.38) / 2
        self.assertLess(vol, current)  # vol > LONG_RUN_MEAN, should be pulled down
        self.assertGreater(vol, VolatilityPredictor.LONG_RUN_MEAN_VOL)

    def test_predict_vol_invalid_model(self):
        features = VolatilityFeatures(0.20, 0.18, 45, 50, 0.05, 0.03, 0.0001)
        with self.assertRaises(ValueError):
            VolatilityPredictor.predict_vol(features, "neural_net")

    def test_vol_regime_low(self):
        self.assertEqual(VolatilityPredictor.vol_regime_classification(0.10, 0.15, 0.30), "LOW")

    def test_vol_regime_normal(self):
        self.assertEqual(VolatilityPredictor.vol_regime_classification(0.20, 0.15, 0.30), "NORMAL")

    def test_vol_regime_high(self):
        self.assertEqual(VolatilityPredictor.vol_regime_classification(0.40, 0.15, 0.30), "HIGH")

    def test_vol_surface_slope_contango(self):
        slope = VolatilityPredictor.vol_surface_slope(0.25, 0.28, 30, 90)
        self.assertGreater(slope, 0)

    def test_vol_surface_slope_backwardation(self):
        slope = VolatilityPredictor.vol_surface_slope(0.35, 0.25, 30, 90)
        self.assertLess(slope, 0)

    def test_vol_surface_slope_zero_delta(self):
        slope = VolatilityPredictor.vol_surface_slope(0.25, 0.28, 60, 60)
        self.assertEqual(slope, 0.0)

    def test_backtest_predictions_returns_list(self):
        prices = self._sample_prices(100)
        results = VolatilityPredictor.backtest_predictions(prices, window=10)
        self.assertIsInstance(results, list)
        self.assertTrue(len(results) > 0)

    def test_backtest_predictions_has_required_keys(self):
        prices = self._sample_prices(80)
        results = VolatilityPredictor.backtest_predictions(prices, window=10)
        for r in results:
            self.assertIn("index", r)
            self.assertIn("predicted_vol", r)
            self.assertIn("actual_vol", r)
            self.assertIn("error", r)

    def test_backtest_predictions_short_series(self):
        results = VolatilityPredictor.backtest_predictions([100.0, 101.0, 102.0], window=21)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
