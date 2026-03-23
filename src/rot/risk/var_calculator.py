"""Value-at-Risk (VaR) and related risk metrics for the ROT platform.

All calculations are self-contained and require only the Python standard
library (math, statistics, random).
"""

from __future__ import annotations

import math
import random
import statistics
import unittest
from typing import List, Optional


# ---------------------------------------------------------------------------
# Standalone VaR functions
# ---------------------------------------------------------------------------


def HistoricalVaR(returns: List[float], confidence: float = 0.95) -> float:
    """Historical simulation VaR.

    Sorts ``returns`` and finds the loss at the given percentile.

    Parameters
    ----------
    returns:
        Sequence of period returns (negative values = losses).
    confidence:
        Confidence level, e.g. 0.95 for 95 % VaR.

    Returns
    -------
    float
        VaR expressed as a *positive* loss magnitude.  Zero if ``returns``
        is empty.
    """
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)
    # percentile index for the left tail
    index = int((1.0 - confidence) * len(sorted_returns))
    index = max(0, min(index, len(sorted_returns) - 1))
    return -sorted_returns[index]


def ParametricVaR(
    position_value: float,
    sigma: float,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> float:
    """Parametric (delta-normal) VaR assuming normally distributed returns.

    Parameters
    ----------
    position_value:
        Absolute notional value of the position (USD).
    sigma:
        Daily volatility as a decimal (e.g. 0.02 for 2 %).
    confidence:
        Confidence level.
    horizon_days:
        Holding period in days.

    Returns
    -------
    float
        VaR in the same currency as ``position_value``.
    """
    z = _normal_quantile(confidence)
    return position_value * sigma * z * math.sqrt(horizon_days)


def MonteCarloVaR(
    returns: List[float],
    n_simulations: int = 10_000,
    confidence: float = 0.95,
    seed: int = 42,
) -> float:
    """Monte Carlo VaR via bootstrap resampling of historical returns.

    Parameters
    ----------
    returns:
        Historical returns used as the sampling pool.
    n_simulations:
        Number of bootstrap samples to draw.
    confidence:
        Confidence level.
    seed:
        Random seed for reproducibility.

    Returns
    -------
    float
        VaR expressed as a positive loss magnitude.
    """
    if not returns:
        return 0.0
    rng = random.Random(seed)
    simulated = [rng.choice(returns) for _ in range(n_simulations)]
    return HistoricalVaR(simulated, confidence)


def CVaR(returns: List[float], confidence: float = 0.95) -> float:
    """Conditional VaR (Expected Shortfall).

    Average of returns *beyond* the VaR threshold (i.e. in the tail).

    Parameters
    ----------
    returns:
        Sequence of period returns.
    confidence:
        Confidence level.

    Returns
    -------
    float
        CVaR expressed as a positive loss magnitude.  Zero if the tail is
        empty or ``returns`` is empty.
    """
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)
    cutoff_index = int((1.0 - confidence) * len(sorted_returns))
    cutoff_index = max(1, cutoff_index)  # need at least 1 element in tail
    tail = sorted_returns[:cutoff_index]
    if not tail:
        return 0.0
    return -statistics.mean(tail)


# ---------------------------------------------------------------------------
# Portfolio VaR
# ---------------------------------------------------------------------------


class PortfolioVaR:
    """Aggregate VaR across multiple positions using a correlation matrix.

    Attributes
    ----------
    positions:
        List of ``(position_value, sigma)`` tuples.
    correlation_matrix:
        Square matrix ``C`` where ``C[i][j]`` is the Pearson correlation
        between position *i* and position *j*.  Defaults to the identity
        matrix (independent positions).
    confidence:
        Confidence level for VaR calculations.
    """

    def __init__(
        self,
        positions: Optional[List[tuple]] = None,
        correlation_matrix: Optional[List[List[float]]] = None,
        confidence: float = 0.95,
    ) -> None:
        self.positions: List[tuple] = positions or []
        self.confidence = confidence
        n = len(self.positions)
        if correlation_matrix is not None:
            self.correlation_matrix = correlation_matrix
        else:
            # Default: identity (zero correlation)
            self.correlation_matrix = [
                [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)
            ]

    def add_position(self, position_value: float, sigma: float) -> None:
        """Add a new position to the portfolio."""
        n = len(self.positions)
        self.positions.append((position_value, sigma))
        # Expand correlation matrix: new row/column with 1 on diagonal.
        for row in self.correlation_matrix:
            row.append(0.0)
        new_row = [0.0] * (n + 1)
        new_row[n] = 1.0
        self.correlation_matrix.append(new_row)

    def individual_vars(self, horizon_days: int = 1) -> List[float]:
        """Return the VaR for each individual position."""
        return [
            ParametricVaR(pv, sigma, self.confidence, horizon_days)
            for pv, sigma in self.positions
        ]

    def portfolio_var(self, horizon_days: int = 1) -> float:
        """Compute the portfolio-level VaR via the variance-covariance method.

        ``VaR_portfolio = sqrt( w^T · C_cov · w )``

        where ``C_cov[i][j] = VaR_i × VaR_j × corr[i][j]``.
        """
        vars_ = self.individual_vars(horizon_days)
        n = len(vars_)
        if n == 0:
            return 0.0
        # Portfolio variance = sum_i sum_j VaR_i * VaR_j * corr[i][j]
        portfolio_variance = 0.0
        for i in range(n):
            for j in range(n):
                portfolio_variance += (
                    vars_[i]
                    * vars_[j]
                    * self.correlation_matrix[i][j]
                )
        return math.sqrt(max(portfolio_variance, 0.0))

    def diversification_benefit(self, horizon_days: int = 1) -> float:
        """Return the VaR reduction from diversification.

        ``benefit = sum(individual VaRs) - portfolio VaR``
        """
        return sum(self.individual_vars(horizon_days)) - self.portfolio_var(horizon_days)


# ---------------------------------------------------------------------------
# Normal quantile approximation (rational approximation, Abramowitz & Stegun)
# ---------------------------------------------------------------------------

def _normal_quantile(p: float) -> float:
    """Approximate the inverse normal CDF using the rational approximation
    from Abramowitz & Stegun (formula 26.2.17), accurate to ~±4.5e-4.

    Returns the *z*-score such that Φ(z) = p.
    """
    p = float(p)
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    if p < 0.5:
        return -_normal_quantile(1.0 - p)

    # For p >= 0.5, work with the upper tail.
    q = 1.0 - p
    t = math.sqrt(-2.0 * math.log(q))

    # Rational approximation coefficients (A&S 26.2.17).
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308

    num = c0 + c1 * t + c2 * t * t
    den = 1.0 + d1 * t + d2 * t * t + d3 * t * t * t

    z = t - num / den
    return z


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestHistoricalVaR(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertAlmostEqual(HistoricalVaR([]), 0.0)

    def test_all_positive_returns_var_is_zero_or_small(self):
        returns = [0.01, 0.02, 0.03, 0.04, 0.05]
        var = HistoricalVaR(returns, 0.95)
        # All returns positive → VaR should be ≤ 0 (no loss)
        self.assertLessEqual(var, 0.01)

    def test_known_var(self):
        # 10 returns; 95% VaR → bottom 5% → index 0 of sorted list
        returns = [-0.05, -0.04, -0.03, -0.02, -0.01, 0.01, 0.02, 0.03, 0.04, 0.05]
        var = HistoricalVaR(returns, 0.95)
        self.assertGreater(var, 0.0)

    def test_higher_confidence_higher_var(self):
        returns = list(range(-50, 50))
        var_90 = HistoricalVaR(returns, 0.90)
        var_99 = HistoricalVaR(returns, 0.99)
        self.assertGreaterEqual(var_99, var_90)

    def test_single_return(self):
        self.assertAlmostEqual(HistoricalVaR([-0.1], 0.95), 0.1)


class TestParametricVaR(unittest.TestCase):
    def test_zero_position_is_zero(self):
        self.assertAlmostEqual(ParametricVaR(0.0, 0.02), 0.0)

    def test_zero_sigma_is_zero(self):
        self.assertAlmostEqual(ParametricVaR(100_000.0, 0.0), 0.0)

    def test_var_scales_with_position(self):
        v1 = ParametricVaR(100_000.0, 0.02)
        v2 = ParametricVaR(200_000.0, 0.02)
        self.assertAlmostEqual(v2 / v1, 2.0, places=6)

    def test_var_scales_with_sqrt_horizon(self):
        v1 = ParametricVaR(100_000.0, 0.02, horizon_days=1)
        v10 = ParametricVaR(100_000.0, 0.02, horizon_days=10)
        self.assertAlmostEqual(v10 / v1, math.sqrt(10), places=4)

    def test_higher_confidence_higher_var(self):
        v95 = ParametricVaR(100_000.0, 0.02, confidence=0.95)
        v99 = ParametricVaR(100_000.0, 0.02, confidence=0.99)
        self.assertGreater(v99, v95)


class TestMonteCarloVaR(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertAlmostEqual(MonteCarloVaR([]), 0.0)

    def test_reproducible_with_same_seed(self):
        returns = [0.01 * i - 0.05 for i in range(20)]
        v1 = MonteCarloVaR(returns, seed=42)
        v2 = MonteCarloVaR(returns, seed=42)
        self.assertAlmostEqual(v1, v2)

    def test_different_seeds_may_differ(self):
        returns = [0.01 * i - 0.1 for i in range(50)]
        v1 = MonteCarloVaR(returns, n_simulations=1000, seed=1)
        v2 = MonteCarloVaR(returns, n_simulations=1000, seed=999)
        # Not guaranteed to differ but test runs without error.
        self.assertIsInstance(v1, float)
        self.assertIsInstance(v2, float)


class TestCVaR(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertAlmostEqual(CVaR([]), 0.0)

    def test_cvar_greater_than_or_equal_to_var(self):
        returns = [0.01 * i - 0.5 for i in range(100)]
        var = HistoricalVaR(returns, 0.95)
        cvar = CVaR(returns, 0.95)
        self.assertGreaterEqual(cvar, var - 1e-9)

    def test_all_positive_cvar_small(self):
        returns = [0.01, 0.02, 0.03]
        cvar = CVaR(returns, 0.95)
        self.assertLessEqual(cvar, 0.01)


class TestPortfolioVaR(unittest.TestCase):
    def test_single_position(self):
        pf = PortfolioVaR(positions=[(100_000.0, 0.02)])
        expected = ParametricVaR(100_000.0, 0.02)
        self.assertAlmostEqual(pf.portfolio_var(), expected, places=4)

    def test_independent_positions_pythagoras(self):
        v1 = ParametricVaR(100_000.0, 0.02)
        v2 = ParametricVaR(100_000.0, 0.03)
        expected = math.sqrt(v1 ** 2 + v2 ** 2)
        pf = PortfolioVaR(
            positions=[(100_000.0, 0.02), (100_000.0, 0.03)],
            correlation_matrix=[[1.0, 0.0], [0.0, 1.0]],
        )
        self.assertAlmostEqual(pf.portfolio_var(), expected, places=4)

    def test_perfect_correlation_is_sum(self):
        pf = PortfolioVaR(
            positions=[(100_000.0, 0.02), (100_000.0, 0.02)],
            correlation_matrix=[[1.0, 1.0], [1.0, 1.0]],
        )
        expected = sum(pf.individual_vars())
        self.assertAlmostEqual(pf.portfolio_var(), expected, places=4)

    def test_diversification_benefit_non_negative(self):
        pf = PortfolioVaR(
            positions=[(100_000.0, 0.02), (100_000.0, 0.03)],
            correlation_matrix=[[1.0, 0.3], [0.3, 1.0]],
        )
        self.assertGreaterEqual(pf.diversification_benefit(), -1e-9)

    def test_add_position_expands_matrix(self):
        pf = PortfolioVaR()
        pf.add_position(100_000.0, 0.02)
        pf.add_position(50_000.0, 0.01)
        self.assertEqual(len(pf.positions), 2)
        self.assertEqual(len(pf.correlation_matrix), 2)
        self.assertGreater(pf.portfolio_var(), 0.0)

    def test_empty_portfolio_is_zero(self):
        pf = PortfolioVaR()
        self.assertAlmostEqual(pf.portfolio_var(), 0.0)


class TestNormalQuantile(unittest.TestCase):
    def test_median(self):
        # A&S approximation at p=0.5 is very close to 0 (within ±0.001).
        self.assertAlmostEqual(_normal_quantile(0.5), 0.0, delta=0.001)

    def test_95_percentile(self):
        # z ≈ 1.645 for 95%  (A&S approximation accurate to ±0.005)
        self.assertAlmostEqual(_normal_quantile(0.95), 1.645, delta=0.005)

    def test_99_percentile(self):
        # z ≈ 2.326 for 99%  (A&S approximation accurate to ±0.005)
        self.assertAlmostEqual(_normal_quantile(0.99), 2.326, delta=0.005)

    def test_symmetry(self):
        self.assertAlmostEqual(_normal_quantile(0.05), -_normal_quantile(0.95), places=4)


if __name__ == "__main__":
    unittest.main()
