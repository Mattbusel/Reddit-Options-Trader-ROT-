"""Granger causality analysis for Reddit signal → price move relationships.

Tests whether a Reddit-derived signal time series (e.g. mention count, sentiment
score, credibility-weighted upvotes) has statistically significant predictive
power over future price returns — i.e. whether the signal "Granger-causes" the
price series.

Algorithm
---------
A bivariate VAR(p) model is fit for each candidate lag ``p`` in ``max_lags``:

    price_t = α + Σ β_i * price_{t-i} + Σ γ_i * signal_{t-i} + ε_t

The restricted model omits the signal lags.  An F-test compares the residual
sum-of-squares of the two models.  A low p-value (< ``alpha``) means the signal
coefficients are jointly significant — the signal Granger-causes the price.

No external statistics library is required; the F-statistic is computed from
first principles using only ``numpy``.

Example
-------
>>> import numpy as np
>>> from rot.analysis.granger import GrangerTest, GrangerResult
>>>
>>> # 120 daily observations of Reddit mention counts and SPY returns.
>>> signal = np.random.randn(120).cumsum()   # simulated mention series
>>> price  = np.random.randn(120) * 0.01     # simulated daily returns
>>>
>>> test = GrangerTest(max_lags=5, alpha=0.05)
>>> results = test.run(signal, price)
>>> best = test.best_lag(results)
>>> print(f"Best lag: {best.lag}  p={best.p_value:.4f}  causes={best.granger_causes}")
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class GrangerResult:
    """Result for a single tested lag order."""

    lag: int
    """Lag order p tested."""

    f_statistic: float
    """F-statistic for the joint significance of signal lags."""

    p_value: float
    """Two-tailed p-value from the F-distribution."""

    df_num: int
    """Numerator degrees of freedom (= lag)."""

    df_den: int
    """Denominator degrees of freedom (= n - 2*lag - 1)."""

    rss_restricted: float
    """Residual sum-of-squares of the price-only model."""

    rss_unrestricted: float
    """Residual sum-of-squares of the full model."""

    granger_causes: bool
    """True when p_value < alpha — signal has predictive power over price."""

    alpha: float
    """Significance threshold used for the ``granger_causes`` decision."""


def _ols(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    """Ordinary least squares: returns coefficients and RSS."""
    coef, residuals, _, _ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ coef
    rss = float(np.sum((y - y_hat) ** 2))
    return coef, rss


def _f_pvalue(f: float, df1: int, df2: int) -> float:
    """P-value of an F(df1, df2) test statistic using regularised incomplete beta."""
    if df1 <= 0 or df2 <= 0 or not math.isfinite(f) or f < 0:
        return 1.0
    # Use the relationship between F CDF and incomplete beta function.
    x = df2 / (df2 + df1 * f)
    # scipy is not required; implement log-beta regularisation manually.
    try:
        # Prefer scipy if available for accuracy.
        from scipy.stats import f as f_dist  # type: ignore[import]
        return float(f_dist.sf(f, df1, df2))
    except ImportError:
        pass
    # Fallback: Abramowitz & Stegun incomplete beta approximation.
    return _ibeta_sf(x, df2 / 2.0, df1 / 2.0)


def _log_beta(a: float, b: float) -> float:
    """Log of the complete beta function B(a, b)."""
    import math
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _ibeta_sf(x: float, a: float, b: float) -> float:
    """Survival function of Beta(a,b) at x via continued fraction (Lentz)."""
    if x <= 0.0:
        return 1.0
    if x >= 1.0:
        return 0.0
    # Use symmetry relation for stability.
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _ibeta_sf(1 - x, b, a)
    log_coef = a * math.log(x) + b * math.log(1 - x) - _log_beta(a, b)
    coef = math.exp(log_coef)
    # Continued fraction via Lentz's algorithm.
    TINY = 1e-30
    MAX_ITER = 200
    TOL = 3e-7
    f = TINY
    C = f
    D = 1.0 - (a + b) * x / (a + 1)
    if abs(D) < TINY:
        D = TINY
    D = 1.0 / D
    C = TINY
    f = D * TINY
    for m in range(1, MAX_ITER + 1):
        for sign in (1, -1):
            if sign == 1:
                mn = m
                num = mn * (b - mn) * x / ((a + 2 * mn - 1) * (a + 2 * mn))
            else:
                mn = m
                num = -(a + mn) * (a + b + mn) * x / ((a + 2 * mn) * (a + 2 * mn + 1))
            D = 1.0 + num * D
            if abs(D) < TINY:
                D = TINY
            C = 1.0 + num / C
            if abs(C) < TINY:
                C = TINY
            D = 1.0 / D
            delta = C * D
            f *= delta
            if abs(delta - 1.0) < TOL:
                return 1.0 - coef * f / a
    return 1.0 - coef * f / a


class GrangerTest:
    """Granger-causality test: does ``signal`` Granger-cause ``price``?

    Parameters
    ----------
    max_lags:
        Maximum lag order to test. Each lag from 1 to ``max_lags`` is tested
        independently.
    alpha:
        Significance level for the ``granger_causes`` flag (default 0.05).
    min_obs:
        Minimum number of observations required (after lag differencing) before
        the test is run. Fewer observations return ``p_value=1.0``.
    """

    def __init__(
        self,
        max_lags: int = 5,
        alpha: float = 0.05,
        min_obs: int = 20,
    ) -> None:
        if max_lags < 1:
            raise ValueError("max_lags must be >= 1")
        self.max_lags = max_lags
        self.alpha = alpha
        self.min_obs = min_obs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        signal: Sequence[float],
        price: Sequence[float],
    ) -> List[GrangerResult]:
        """Run the Granger causality test for each lag from 1 to ``max_lags``.

        Parameters
        ----------
        signal:
            1-D time series of the Reddit-derived signal (mention count,
            sentiment score, etc.).  Must be the same length as ``price``.
        price:
            1-D time series of price returns (or levels).

        Returns
        -------
        List of :class:`GrangerResult`, one per tested lag order.
        """
        sig = np.asarray(signal, dtype=float)
        prc = np.asarray(price, dtype=float)
        if sig.shape != prc.shape or sig.ndim != 1:
            raise ValueError("signal and price must be 1-D arrays of equal length")

        results: List[GrangerResult] = []
        for lag in range(1, self.max_lags + 1):
            results.append(self._test_lag(sig, prc, lag))
        return results

    def best_lag(self, results: List[GrangerResult]) -> Optional[GrangerResult]:
        """Return the result with the smallest p-value (strongest causality)."""
        if not results:
            return None
        return min(results, key=lambda r: r.p_value)

    def significant_lags(self, results: List[GrangerResult]) -> List[GrangerResult]:
        """Return only results where ``granger_causes`` is True."""
        return [r for r in results if r.granger_causes]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _test_lag(self, signal: np.ndarray, price: np.ndarray, lag: int) -> GrangerResult:
        n = len(price)
        n_eff = n - lag  # effective sample after removing lagged rows

        null_result = GrangerResult(
            lag=lag,
            f_statistic=0.0,
            p_value=1.0,
            df_num=lag,
            df_den=max(n_eff - 2 * lag - 1, 1),
            rss_restricted=0.0,
            rss_unrestricted=0.0,
            granger_causes=False,
            alpha=self.alpha,
        )

        if n_eff < self.min_obs:
            return null_result

        # Build design matrices.
        # Rows: t = lag, lag+1, ..., n-1
        # Restricted (price lags only + intercept).
        X_r = np.ones((n_eff, lag + 1))
        for j in range(1, lag + 1):
            X_r[:, j] = price[lag - j : n - j]

        # Unrestricted adds signal lags.
        X_u = np.ones((n_eff, 2 * lag + 1))
        X_u[:, : lag + 1] = X_r
        for j in range(1, lag + 1):
            X_u[:, lag + j] = signal[lag - j : n - j]

        y = price[lag:]

        _, rss_r = _ols(X_r, y)
        _, rss_u = _ols(X_u, y)

        df_num = lag
        df_den = n_eff - 2 * lag - 1

        if df_den <= 0 or rss_u <= 0:
            return null_result

        f_stat = ((rss_r - rss_u) / df_num) / (rss_u / df_den)
        p_val = _f_pvalue(f_stat, df_num, df_den)

        return GrangerResult(
            lag=lag,
            f_statistic=float(f_stat),
            p_value=float(p_val),
            df_num=df_num,
            df_den=df_den,
            rss_restricted=float(rss_r),
            rss_unrestricted=float(rss_u),
            granger_causes=p_val < self.alpha,
            alpha=self.alpha,
        )


@dataclass
class GrangerSummary:
    """Aggregated Granger-causality results across a set of tickers or signals."""

    ticker: str
    signal_name: str
    results: List[GrangerResult]
    n_observations: int

    @property
    def any_significant(self) -> bool:
        """True if any lag is statistically significant."""
        return any(r.granger_causes for r in self.results)

    @property
    def min_p_value(self) -> float:
        """Smallest p-value across all tested lags."""
        if not self.results:
            return 1.0
        return min(r.p_value for r in self.results)

    @property
    def best_lag(self) -> Optional[GrangerResult]:
        """Result at the most significant lag."""
        if not self.results:
            return None
        return min(self.results, key=lambda r: r.p_value)

    def summary_line(self) -> str:
        best = self.best_lag
        if best is None:
            return f"{self.ticker} | {self.signal_name} | no data"
        arrow = "→" if best.granger_causes else "✗"
        return (
            f"{self.ticker} | {self.signal_name} {arrow} price "
            f"(lag={best.lag}, F={best.f_statistic:.2f}, p={best.p_value:.4f}, "
            f"n={self.n_observations})"
        )
