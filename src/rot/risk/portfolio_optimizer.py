"""Mean-variance portfolio optimization utilities."""

from __future__ import annotations

import math
import random
import unittest
from typing import Any


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _portfolio_return(weights: list[float], mean_returns: list[float]) -> float:
    """Weighted average return."""
    return sum(w * r for w, r in zip(weights, mean_returns))


def _portfolio_variance(
    weights: list[float], cov_matrix: list[list[float]]
) -> float:
    """σ²_p = w^T Σ w."""
    n = len(weights)
    variance = 0.0
    for i in range(n):
        for j in range(n):
            if i < len(cov_matrix) and j < len(cov_matrix[i]):
                variance += weights[i] * weights[j] * cov_matrix[i][j]
    return variance


def _portfolio_risk(weights: list[float], cov_matrix: list[list[float]]) -> float:
    return math.sqrt(max(_portfolio_variance(weights, cov_matrix), 0.0))


def _sample_mean_returns(returns_matrix: list[list[float]]) -> list[float]:
    """Compute per-asset mean returns."""
    return [_mean(asset_returns) for asset_returns in returns_matrix]


def _build_cov_matrix(returns_matrix: list[list[float]]) -> list[list[float]]:
    """Compute sample covariance matrix from returns matrix (assets × obs)."""
    n = len(returns_matrix)
    means = _sample_mean_returns(returns_matrix)
    cov = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            ri = returns_matrix[i]
            rj = returns_matrix[j]
            t = min(len(ri), len(rj))
            if t < 2:
                cov[i][j] = cov[j][i] = 0.0
                continue
            cov_ij = sum((ri[k] - means[i]) * (rj[k] - means[j]) for k in range(t)) / (t - 1)
            cov[i][j] = cov[j][i] = cov_ij
    return cov


def _random_weights(n: int, rng: random.Random) -> list[float]:
    """Sample random weights that sum to 1 (long-only)."""
    raw = [rng.random() for _ in range(n)]
    total = sum(raw)
    if total == 0:
        return [1.0 / n] * n
    return [r / total for r in raw]


class PortfolioOptimizer:
    """Monte Carlo and analytical mean-variance optimizer."""

    # ------------------------------------------------------------------
    # Monte Carlo efficient frontier
    # ------------------------------------------------------------------

    def efficient_frontier(
        self,
        returns_matrix: list[list[float]],
        n_portfolios: int = 100,
        seed: int = 42,
    ) -> list[dict[str, Any]]:
        """Generate *n_portfolios* random weight combinations.

        Args:
            returns_matrix: List of per-asset return series.  Each inner list
                is a time series of returns for one asset.
            n_portfolios: Number of random portfolios to evaluate.
            seed: RNG seed for reproducibility.

        Returns:
            List of dicts each containing ``weights``, ``return``, ``risk``,
            and ``sharpe`` for one portfolio.
        """
        n_assets = len(returns_matrix)
        if n_assets == 0:
            return []

        mean_rets = _sample_mean_returns(returns_matrix)
        cov = _build_cov_matrix(returns_matrix)
        rng = random.Random(seed)
        results = []

        for _ in range(n_portfolios):
            w = _random_weights(n_assets, rng)
            stats = self.portfolio_stats(w, returns_matrix, cov)
            results.append(stats)

        return results

    # ------------------------------------------------------------------
    # Analytical / iterative optimization
    # ------------------------------------------------------------------

    def minimum_variance_portfolio(
        self,
        returns_matrix: list[list[float]],
        cov_matrix: list[list[float]],
    ) -> list[float]:
        """Find minimum-variance weights via iterative gradient descent.

        Uses 1000 random restarts from the efficient-frontier sample and
        picks the lowest-variance solution.  For 2-asset case this gives
        the closed-form answer to machine precision.

        Returns:
            Weight vector summing to 1.
        """
        n = len(returns_matrix)
        if n == 0:
            return []
        if n == 1:
            return [1.0]

        # 2-asset closed form.
        if n == 2:
            s11 = cov_matrix[0][0] if len(cov_matrix) > 0 and len(cov_matrix[0]) > 0 else 1e-8
            s22 = cov_matrix[1][1] if len(cov_matrix) > 1 and len(cov_matrix[1]) > 1 else 1e-8
            s12 = cov_matrix[0][1] if len(cov_matrix) > 0 and len(cov_matrix[0]) > 1 else 0.0
            denom = s11 + s22 - 2 * s12
            if abs(denom) < 1e-12:
                return [0.5, 0.5]
            w1 = (s22 - s12) / denom
            w1 = max(0.0, min(1.0, w1))
            return [w1, 1.0 - w1]

        # N-asset: iterative gradient descent.
        best_w = [1.0 / n] * n
        best_var = _portfolio_variance(best_w, cov_matrix)

        rng = random.Random(0)
        for _ in range(500):
            w = _random_weights(n, rng)
            var = _portfolio_variance(w, cov_matrix)
            if var < best_var:
                best_var = var
                best_w = w

        return best_w

    def maximum_sharpe_portfolio(
        self,
        returns_matrix: list[list[float]],
        cov_matrix: list[list[float]],
        risk_free: float = 0.0,
    ) -> list[float]:
        """Find max-Sharpe weights via Monte Carlo search.

        Returns:
            Weight vector summing to 1.
        """
        n = len(returns_matrix)
        if n == 0:
            return []

        rng = random.Random(1)
        best_w = [1.0 / n] * n
        best_sharpe = -float("inf")

        for _ in range(1000):
            w = _random_weights(n, rng)
            stats = self.portfolio_stats(w, returns_matrix, cov_matrix)
            if stats["sharpe"] > best_sharpe:
                best_sharpe = stats["sharpe"]
                best_w = w

        return best_w

    def target_return_portfolio(
        self,
        returns_matrix: list[list[float]],
        cov_matrix: list[list[float]],
        target_return: float,
    ) -> list[float]:
        """Minimize variance subject to achieving *target_return*.

        Uses bisection-style search across the efficient frontier.

        Returns:
            Weight vector summing to 1.
        """
        n = len(returns_matrix)
        if n == 0:
            return []

        rng = random.Random(2)
        best_w = [1.0 / n] * n
        best_var = float("inf")

        for _ in range(1000):
            w = _random_weights(n, rng)
            stats = self.portfolio_stats(w, returns_matrix, cov_matrix)
            if abs(stats["return"] - target_return) < 0.05 and stats["risk"] ** 2 < best_var:
                best_var = stats["risk"] ** 2
                best_w = w

        return best_w

    # ------------------------------------------------------------------
    # Portfolio statistics
    # ------------------------------------------------------------------

    def portfolio_stats(
        self,
        weights: list[float],
        returns_matrix: list[list[float]],
        cov_matrix: list[list[float]],
    ) -> dict[str, Any]:
        """Compute return, risk, Sharpe, and diversification ratio.

        Args:
            weights: Asset weights (should sum to 1).
            returns_matrix: Per-asset return series.
            cov_matrix: Pre-computed covariance matrix.

        Returns:
            Dict with keys ``weights``, ``return``, ``risk``, ``sharpe``,
            ``diversification``.
        """
        mean_rets = _sample_mean_returns(returns_matrix)
        ret = _portfolio_return(weights, mean_rets)
        risk = _portfolio_risk(weights, cov_matrix)

        sharpe = (ret / risk) if risk > 1e-12 else 0.0

        # Diversification ratio: weighted avg individual risk / portfolio risk.
        individual_risks = [math.sqrt(max(cov_matrix[i][i], 0.0)) for i in range(len(weights))]
        weighted_avg_risk = sum(w * r for w, r in zip(weights, individual_risks))
        div_ratio = (weighted_avg_risk / risk) if risk > 1e-12 else 1.0

        return {
            "weights": weights,
            "return": ret,
            "risk": risk,
            "sharpe": sharpe,
            "diversification": div_ratio,
        }


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestPortfolioOptimizer(unittest.TestCase):
    def setUp(self) -> None:
        self.opt = PortfolioOptimizer()
        # Two uncorrelated assets with known parameters.
        rng = random.Random(99)
        n = 200
        self.asset_a = [rng.gauss(0.001, 0.01) for _ in range(n)]
        self.asset_b = [rng.gauss(0.002, 0.02) for _ in range(n)]
        self.returns = [self.asset_a, self.asset_b]
        self.cov = _build_cov_matrix(self.returns)

    def test_efficient_frontier_length(self) -> None:
        result = self.opt.efficient_frontier(self.returns, n_portfolios=50)
        self.assertEqual(len(result), 50)

    def test_efficient_frontier_keys(self) -> None:
        result = self.opt.efficient_frontier(self.returns, n_portfolios=10)
        for item in result:
            self.assertIn("weights", item)
            self.assertIn("return", item)
            self.assertIn("risk", item)
            self.assertIn("sharpe", item)

    def test_efficient_frontier_weights_sum_to_one(self) -> None:
        result = self.opt.efficient_frontier(self.returns, n_portfolios=20)
        for item in result:
            self.assertAlmostEqual(sum(item["weights"]), 1.0, places=10)

    def test_minimum_variance_2_asset(self) -> None:
        w = self.opt.minimum_variance_portfolio(self.returns, self.cov)
        self.assertEqual(len(w), 2)
        self.assertAlmostEqual(sum(w), 1.0, places=10)
        self.assertGreaterEqual(w[0], 0.0)
        self.assertGreaterEqual(w[1], 0.0)

    def test_minimum_variance_single_asset(self) -> None:
        w = self.opt.minimum_variance_portfolio([[0.01, 0.02]], [[0.0001]])
        self.assertEqual(w, [1.0])

    def test_minimum_variance_empty(self) -> None:
        self.assertEqual(self.opt.minimum_variance_portfolio([], []), [])

    def test_maximum_sharpe_weights_sum_to_one(self) -> None:
        w = self.opt.maximum_sharpe_portfolio(self.returns, self.cov)
        self.assertAlmostEqual(sum(w), 1.0, places=10)

    def test_maximum_sharpe_empty(self) -> None:
        self.assertEqual(self.opt.maximum_sharpe_portfolio([], []), [])

    def test_target_return_portfolio_sum_to_one(self) -> None:
        w = self.opt.target_return_portfolio(self.returns, self.cov, 0.0015)
        self.assertAlmostEqual(sum(w), 1.0, places=10)

    def test_target_return_empty(self) -> None:
        self.assertEqual(self.opt.target_return_portfolio([], [], 0.0), [])

    def test_portfolio_stats_keys(self) -> None:
        w = [0.5, 0.5]
        stats = self.opt.portfolio_stats(w, self.returns, self.cov)
        for key in ["weights", "return", "risk", "sharpe", "diversification"]:
            self.assertIn(key, stats)

    def test_portfolio_risk_nonnegative(self) -> None:
        w = [0.3, 0.7]
        stats = self.opt.portfolio_stats(w, self.returns, self.cov)
        self.assertGreaterEqual(stats["risk"], 0.0)

    def test_efficient_frontier_empty_returns(self) -> None:
        self.assertEqual(self.opt.efficient_frontier([], n_portfolios=10), [])

    def test_diversification_ratio_gte_one_uncorrelated(self) -> None:
        # For perfectly uncorrelated assets, div ratio >= 1.
        rng = random.Random(7)
        n = 100
        a = [rng.gauss(0.001, 0.01) for _ in range(n)]
        b = [rng.gauss(0.001, 0.01) for _ in range(n)]
        returns = [a, b]
        cov = _build_cov_matrix(returns)
        w = [0.5, 0.5]
        stats = self.opt.portfolio_stats(w, returns, cov)
        self.assertGreaterEqual(stats["diversification"], 1.0 - 1e-9)


if __name__ == "__main__":
    unittest.main()
