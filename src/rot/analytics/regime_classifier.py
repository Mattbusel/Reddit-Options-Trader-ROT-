"""Market regime classification from price series."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class MarketRegime:
    name: str
    trend: float
    volatility: float
    mean_reversion: float
    confidence: float


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class RegimeClassifier:
    """Classify market regime from a price series."""

    def __init__(self, lookback: int = 20) -> None:
        self.lookback = lookback

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, prices: List[float]) -> MarketRegime:
        """Classify the regime for the given price series."""
        if len(prices) < 4:
            return MarketRegime(
                name="unknown",
                trend=0.0,
                volatility=0.0,
                mean_reversion=0.0,
                confidence=0.0,
            )

        trend = self._compute_trend(prices)
        vol = self._compute_realized_vol(prices)
        hurst = self._compute_hurst(prices)
        mr_speed = self._mean_reversion_speed(prices)

        # Threshold-based regime labelling
        if vol > 0.4:
            name = "high_vol"
        elif vol < 0.1:
            name = "low_vol"
        elif hurst > 0.6 and trend > 0:
            name = "trending_bull"
        elif hurst > 0.6 and trend < 0:
            name = "trending_bear"
        else:
            name = "mean_reverting"

        # Confidence: how strongly the leading indicator diverges from 0.5
        if name in ("trending_bull", "trending_bear"):
            confidence = min(1.0, abs(hurst - 0.5) * 4)
        elif name == "mean_reverting":
            confidence = min(1.0, (0.5 - hurst) * 4) if hurst < 0.5 else 0.5
        elif name == "high_vol":
            confidence = min(1.0, (vol - 0.4) * 5)
        else:
            confidence = min(1.0, (0.1 - vol) * 20) if vol < 0.1 else 0.5

        return MarketRegime(
            name=name,
            trend=trend,
            volatility=vol,
            mean_reversion=mr_speed,
            confidence=float(max(0.0, min(1.0, confidence))),
        )

    def regime_history(self, prices: List[float], window: int) -> List[MarketRegime]:
        """Rolling classification using a sliding window."""
        results: List[MarketRegime] = []
        for end in range(window, len(prices) + 1):
            chunk = prices[end - window : end]
            results.append(self.classify(chunk))
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_trend(self, prices: List[float]) -> float:
        """OLS slope of prices, normalised by average price level."""
        n = len(prices)
        if n < 2:
            return 0.0
        xs = list(range(n))
        mean_x = (n - 1) / 2.0
        mean_y = sum(prices) / n
        num = sum((xs[i] - mean_x) * (prices[i] - mean_y) for i in range(n))
        den = sum((xs[i] - mean_x) ** 2 for i in range(n))
        if den == 0 or mean_y == 0:
            return 0.0
        slope = num / den
        return slope / mean_y  # normalise by price level

    def _compute_hurst(self, prices: List[float]) -> float:
        """
        Rescaled range (R/S) Hurst exponent.

        Uses at least 3 lag scales: lags = [n//4, n//3, n//2] and fits
        log(R/S) ~ H * log(lag).
        """
        n = len(prices)
        if n < 8:
            return 0.5

        lags = [max(4, n // 4), max(4, n // 3), max(4, n // 2)]
        lags = list(dict.fromkeys(lags))  # deduplicate while preserving order

        rs_values = []
        for lag in lags:
            rs = self._rs_for_lag(prices, lag)
            if rs > 0:
                rs_values.append((math.log(lag), math.log(rs)))

        if len(rs_values) < 2:
            return 0.5

        # OLS slope of log(R/S) ~ H * log(lag)
        log_lags = [v[0] for v in rs_values]
        log_rs = [v[1] for v in rs_values]
        mean_x = sum(log_lags) / len(log_lags)
        mean_y = sum(log_rs) / len(log_rs)
        num = sum((log_lags[i] - mean_x) * (log_rs[i] - mean_y) for i in range(len(log_lags)))
        den = sum((log_lags[i] - mean_x) ** 2 for i in range(len(log_lags)))
        if den == 0:
            return 0.5
        return num / den

    def _rs_for_lag(self, prices: List[float], lag: int) -> float:
        """Compute mean R/S statistic for a given lag using non-overlapping blocks."""
        n = len(prices)
        num_blocks = n // lag
        if num_blocks == 0:
            return 0.0

        rs_list = []
        for b in range(num_blocks):
            block = prices[b * lag : (b + 1) * lag]
            mean_b = sum(block) / lag
            # Mean-adjusted series
            deviations = [block[i] - mean_b for i in range(lag)]
            cumulative = []
            s = 0.0
            for d in deviations:
                s += d
                cumulative.append(s)
            r = max(cumulative) - min(cumulative)
            # Standard deviation of block returns
            returns = [block[i + 1] - block[i] for i in range(lag - 1)]
            if len(returns) == 0:
                continue
            mean_ret = sum(returns) / len(returns)
            variance = sum((x - mean_ret) ** 2 for x in returns) / len(returns)
            std = math.sqrt(variance) if variance > 0 else 1e-8
            rs_list.append(r / std)

        if not rs_list:
            return 0.0
        return sum(rs_list) / len(rs_list)

    def _compute_realized_vol(self, prices: List[float]) -> float:
        """Annualized realized volatility from log returns."""
        if len(prices) < 2:
            return 0.0
        log_returns = [
            math.log(prices[i] / prices[i - 1])
            for i in range(1, len(prices))
            if prices[i - 1] > 0 and prices[i] > 0
        ]
        if not log_returns:
            return 0.0
        n = len(log_returns)
        mean = sum(log_returns) / n
        variance = sum((r - mean) ** 2 for r in log_returns) / n
        daily_vol = math.sqrt(variance)
        return daily_vol * math.sqrt(252)

    def _mean_reversion_speed(self, prices: List[float]) -> float:
        """
        AR(1) coefficient phi for the log-return series.
        Mean reversion speed ≈ (1 - phi).
        Returns (1 - phi) so that high values indicate fast mean reversion.
        """
        if len(prices) < 3:
            return 0.0
        log_returns = [
            math.log(prices[i] / prices[i - 1])
            for i in range(1, len(prices))
            if prices[i - 1] > 0 and prices[i] > 0
        ]
        if len(log_returns) < 3:
            return 0.0
        y = log_returns[1:]
        x = log_returns[:-1]
        n = len(y)
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        num = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        den = sum((x[i] - mean_x) ** 2 for i in range(n))
        if den == 0:
            return 0.0
        phi = num / den
        return 1.0 - phi
