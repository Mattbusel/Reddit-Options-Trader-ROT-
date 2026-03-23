"""
Rolling correlation matrix with regime detection.

Computes Pearson correlations over a rolling lookback window and classifies
market correlation regimes.
"""

import math
import time
from dataclasses import dataclass, field
from collections import deque
from typing import Dict, List


@dataclass
class CorrelationRegime:
    name: str
    avg_correlation: float
    max_correlation: float
    min_correlation: float
    timestamp: float


class CorrelationAnalyzer:
    """Analyzes rolling correlations between asset return streams."""

    def __init__(self, assets: List[str], lookback: int = 60):
        self.assets = assets
        self.lookback = lookback
        # Rolling window of returns per asset: deque of floats
        self._history: Dict[str, deque] = {a: deque(maxlen=lookback) for a in assets}
        self._prior_avg_corr: float = 0.0
        self._last_avg_corr: float = 0.0

    def update(self, returns: Dict[str, float], timestamp: float):
        """Add a new observation to the rolling window."""
        for asset in self.assets:
            if asset in returns:
                self._history[asset].append(returns[asset])

    def _pearson(self, xs: List[float], ys: List[float]) -> float:
        """Compute Pearson correlation between two series."""
        n = len(xs)
        if n < 2:
            return 0.0
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
        denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
        if denom_x < 1e-12 or denom_y < 1e-12:
            return 0.0
        return num / (denom_x * denom_y)

    def compute_matrix(self) -> List[List[float]]:
        """Compute Pearson correlation matrix over lookback window."""
        n = len(self.assets)
        matrix = [[0.0] * n for _ in range(n)]
        for i, ai in enumerate(self.assets):
            for j, aj in enumerate(self.assets):
                if i == j:
                    matrix[i][j] = 1.0
                elif j > i:
                    xs = list(self._history[ai])
                    ys = list(self._history[aj])
                    min_len = min(len(xs), len(ys))
                    if min_len >= 2:
                        corr = self._pearson(xs[-min_len:], ys[-min_len:])
                    else:
                        corr = 0.0
                    matrix[i][j] = corr
                    matrix[j][i] = corr
        return matrix

    def average_correlation(self) -> float:
        """Mean of off-diagonal correlation elements."""
        matrix = self.compute_matrix()
        n = len(self.assets)
        if n <= 1:
            return 0.0
        total = 0.0
        count = 0
        for i in range(n):
            for j in range(n):
                if i != j:
                    total += matrix[i][j]
                    count += 1
        return total / count if count > 0 else 0.0

    def detect_regime(self) -> CorrelationRegime:
        """Classify current correlation regime."""
        matrix = self.compute_matrix()
        n = len(self.assets)
        off_diag = [
            matrix[i][j]
            for i in range(n)
            for j in range(n)
            if i != j
        ]

        if not off_diag:
            return CorrelationRegime(
                name="low_correlation",
                avg_correlation=0.0,
                max_correlation=0.0,
                min_correlation=0.0,
                timestamp=time.time(),
            )

        avg = sum(off_diag) / len(off_diag)
        max_corr = max(off_diag)
        min_corr = min(off_diag)

        if avg > 0.7:
            name = "high_correlation"
        elif avg < 0.3:
            name = "low_correlation"
        else:
            name = "moderate"

        return CorrelationRegime(
            name=name,
            avg_correlation=avg,
            max_correlation=max_corr,
            min_correlation=min_corr,
            timestamp=time.time(),
        )

    def correlation_shock(self, threshold: float = 0.3) -> bool:
        """True if the avg_correlation changed by >threshold vs prior."""
        current = self.average_correlation()
        shock = abs(current - self._prior_avg_corr) > threshold
        self._prior_avg_corr = self._last_avg_corr
        self._last_avg_corr = current
        return shock

    def diversification_ratio(self, weights: List[float]) -> float:
        """
        Diversification ratio = sum(w*vol) / portfolio_vol.

        Uses correlation matrix and uniform unit volatilities (vol=1 per asset).
        """
        n = len(self.assets)
        if n == 0 or len(weights) != n:
            return 1.0

        matrix = self.compute_matrix()
        vols = [1.0] * n  # unit volatilities

        weighted_vol_sum = sum(weights[i] * vols[i] for i in range(n))

        # Portfolio variance = w^T * Sigma * w where Sigma[i][j] = corr[i][j]*vol[i]*vol[j]
        port_var = 0.0
        for i in range(n):
            for j in range(n):
                port_var += weights[i] * weights[j] * matrix[i][j] * vols[i] * vols[j]

        port_vol = math.sqrt(max(port_var, 0.0))
        if port_vol < 1e-12:
            return 1.0
        return weighted_vol_sum / port_vol

    def eigenvalue_risk(self) -> float:
        """
        Power iteration to estimate largest eigenvalue / trace (concentration).

        Returns a value in [0, 1] where 1 means all variance in one factor.
        """
        matrix = self.compute_matrix()
        n = len(self.assets)
        if n == 0:
            return 0.0

        trace = sum(matrix[i][i] for i in range(n))
        if trace < 1e-12:
            return 0.0

        # Power iteration for dominant eigenvalue
        v = [1.0 / math.sqrt(n)] * n
        for _ in range(50):
            # v_new = matrix * v
            v_new = [0.0] * n
            for i in range(n):
                for j in range(n):
                    v_new[i] += matrix[i][j] * v[j]
            norm = math.sqrt(sum(x * x for x in v_new))
            if norm < 1e-12:
                break
            v = [x / norm for x in v_new]
        # Rayleigh quotient: lambda = v^T * A * v
        Av = [sum(matrix[i][j] * v[j] for j in range(n)) for i in range(n)]
        lambda_max = sum(v[i] * Av[i] for i in range(n))
        return lambda_max / trace
