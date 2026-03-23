"""Risk parity portfolio construction.

Implements the equal-risk-contribution (ERC) framework where each asset
contributes equally to the total portfolio volatility.
"""

from __future__ import annotations

import math
import unittest


class RiskParityOptimizer:
    """Build risk-parity portfolios using iterative re-weighting."""

    # ------------------------------------------------------------------
    # Core math helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mat_vec(matrix: list[list[float]], vec: list[float]) -> list[float]:
        """Matrix-vector product Σ·w."""
        n = len(vec)
        result = [0.0] * n
        for i in range(n):
            for j in range(n):
                result[i] += matrix[i][j] * vec[j]
        return result

    @staticmethod
    def _dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def portfolio_volatility(
        self,
        weights: list[float],
        cov_matrix: list[list[float]],
    ) -> float:
        """σ_p = sqrt(w' Σ w)."""
        sigma_w = self._mat_vec(cov_matrix, weights)
        variance = self._dot(weights, sigma_w)
        return math.sqrt(max(variance, 0.0))

    def risk_contribution(
        self,
        weights: list[float],
        cov_matrix: list[list[float]],
    ) -> list[float]:
        """Marginal risk contribution times weight for each asset.

        RC_i = w_i · (Σw)_i / σ_p
        """
        sigma_w = self._mat_vec(cov_matrix, weights)
        vol = self.portfolio_volatility(weights, cov_matrix)
        if vol < 1e-12:
            n = len(weights)
            return [1.0 / n] * n
        return [weights[i] * sigma_w[i] / vol for i in range(len(weights))]

    def equal_risk_contribution(
        self,
        cov_matrix: list[list[float]],
        tol: float = 1e-8,
        max_iter: int = 1000,
    ) -> list[float]:
        """Compute ERC weights via iterative proportional algorithm.

        Each iteration: w_i ← w_i / sqrt((Σw)_i) and then normalise to sum 1.
        Converges to the portfolio where each asset contributes equally.
        """
        n = len(cov_matrix)
        weights = [1.0 / n] * n  # start with 1/N

        for _ in range(max_iter):
            sigma_w = self._mat_vec(cov_matrix, weights)
            new_weights: list[float] = []
            for i in range(n):
                denom = math.sqrt(max(sigma_w[i], 1e-12))
                new_weights.append(weights[i] / denom)

            # Normalise.
            total = sum(new_weights)
            new_weights = [w / total for w in new_weights]

            # Check convergence.
            diff = math.sqrt(sum((new_weights[i] - weights[i]) ** 2 for i in range(n)))
            weights = new_weights
            if diff < tol:
                break

        return weights

    def target_risk_contribution(
        self,
        weights: list[float],
        cov_matrix: list[list[float]],
        target_contributions: list[float],
    ) -> list[float]:
        """Iteratively adjust weights so that RC_i matches target_contributions.

        target_contributions should sum to 1 (they are treated as fractions of
        total portfolio volatility).

        Algorithm: w_i ← w_i * target_i / RC_i  (multiplicative update),
        repeat until convergence.
        """
        n = len(weights)
        total_target = sum(target_contributions)
        if total_target <= 0.0:
            return weights[:]

        # Normalise targets.
        targets = [t / total_target for t in target_contributions]

        for _ in range(500):
            rc = self.risk_contribution(weights, cov_matrix)
            total_rc = sum(rc)
            if total_rc < 1e-12:
                break

            new_weights = []
            for i in range(n):
                rc_frac = rc[i] / total_rc
                if rc_frac < 1e-12:
                    new_weights.append(weights[i])
                else:
                    new_weights.append(weights[i] * (targets[i] / rc_frac))

            total_w = sum(new_weights)
            if total_w < 1e-12:
                break
            new_weights = [w / total_w for w in new_weights]

            diff = math.sqrt(sum((new_weights[i] - weights[i]) ** 2 for i in range(n)))
            weights = new_weights
            if diff < 1e-8:
                break

        return weights

    def diversification_ratio(
        self,
        weights: list[float],
        cov_matrix: list[list[float]],
    ) -> float:
        """DR = (Σ w_i σ_i) / σ_p.

        A higher diversification ratio means the portfolio is more effectively
        diversified (individual vols sum to more than portfolio vol).
        """
        n = len(weights)
        individual_vols = [math.sqrt(max(cov_matrix[i][i], 0.0)) for i in range(n)]
        weighted_avg_vol = sum(weights[i] * individual_vols[i] for i in range(n))
        portfolio_vol = self.portfolio_volatility(weights, cov_matrix)
        if portfolio_vol < 1e-12:
            return 1.0
        return weighted_avg_vol / portfolio_vol


# ─── TESTS ────────────────────────────────────────────────────────────────────

class TestRiskParityOptimizer(unittest.TestCase):

    def _diagonal_cov(self, variances: list[float]) -> list[list[float]]:
        n = len(variances)
        mat = [[0.0] * n for _ in range(n)]
        for i in range(n):
            mat[i][i] = variances[i]
        return mat

    def setUp(self) -> None:
        self.opt = RiskParityOptimizer()

    def test_portfolio_volatility_diagonal(self) -> None:
        # Equal weights, diagonal cov with variance 1 → vol = sqrt(N * (1/N)^2) = 1/sqrt(N)
        n = 4
        weights = [1.0 / n] * n
        cov = self._diagonal_cov([1.0] * n)
        vol = self.opt.portfolio_volatility(weights, cov)
        self.assertAlmostEqual(vol, 1.0 / math.sqrt(n), places=9)

    def test_portfolio_volatility_two_asset(self) -> None:
        weights = [0.6, 0.4]
        cov = [[0.04, 0.0], [0.0, 0.09]]
        # σ² = 0.36*0.04 + 0.16*0.09 = 0.0144 + 0.0144 = 0.0288
        vol = self.opt.portfolio_volatility(weights, cov)
        self.assertAlmostEqual(vol, math.sqrt(0.0288), places=9)

    def test_risk_contribution_sums_to_vol(self) -> None:
        weights = [0.5, 0.5]
        cov = [[0.04, 0.01], [0.01, 0.09]]
        rc = self.opt.risk_contribution(weights, cov)
        vol = self.opt.portfolio_volatility(weights, cov)
        self.assertAlmostEqual(sum(rc), vol, places=9)

    def test_equal_risk_contribution_diagonal_gives_inv_vol_weights(self) -> None:
        # For diagonal covariance, ERC weights = 1/σ_i normalised.
        variances = [0.04, 0.09, 0.01]  # σ = [0.2, 0.3, 0.1]
        cov = self._diagonal_cov(variances)
        weights = self.opt.equal_risk_contribution(cov)
        self.assertAlmostEqual(sum(weights), 1.0, places=6)
        # Expected: 1/0.2=5, 1/0.3≈3.33, 1/0.1=10 → normalised ≈ [0.272, 0.181, 0.545]
        inv_vols = [1.0 / math.sqrt(v) for v in variances]
        total = sum(inv_vols)
        expected = [v / total for v in inv_vols]
        for w, e in zip(weights, expected):
            self.assertAlmostEqual(w, e, places=4)

    def test_equal_risk_contribution_equal_risk_check(self) -> None:
        cov = [[0.04, 0.01], [0.01, 0.09]]
        weights = self.opt.equal_risk_contribution(cov)
        rc = self.opt.risk_contribution(weights, cov)
        self.assertAlmostEqual(rc[0], rc[1], places=5)

    def test_target_risk_contribution_equal_targets(self) -> None:
        cov = [[0.04, 0.01], [0.01, 0.09]]
        weights = [0.5, 0.5]
        targets = [0.5, 0.5]
        result = self.opt.target_risk_contribution(weights, cov, targets)
        rc = self.opt.risk_contribution(result, cov)
        self.assertAlmostEqual(rc[0] / sum(rc), 0.5, places=4)
        self.assertAlmostEqual(rc[1] / sum(rc), 0.5, places=4)

    def test_target_risk_contribution_sums_to_one(self) -> None:
        cov = [[0.04, 0.01], [0.01, 0.09]]
        weights = [0.5, 0.5]
        result = self.opt.target_risk_contribution(weights, cov, [0.6, 0.4])
        self.assertAlmostEqual(sum(result), 1.0, places=9)

    def test_diversification_ratio_uncorrelated(self) -> None:
        # Uncorrelated assets: DR ≥ 1.
        cov = self._diagonal_cov([0.04, 0.09])
        weights = [0.5, 0.5]
        dr = self.opt.diversification_ratio(weights, cov)
        self.assertGreaterEqual(dr, 1.0)

    def test_diversification_ratio_correlated_assets_lower(self) -> None:
        # Perfectly correlated assets have DR = 1.
        # σ₁=σ₂=0.2, corr=1 → Σ = [[0.04, 0.04], [0.04, 0.04]]
        cov = [[0.04, 0.04], [0.04, 0.04]]
        weights = [0.5, 0.5]
        dr = self.opt.diversification_ratio(weights, cov)
        self.assertAlmostEqual(dr, 1.0, places=9)

    def test_equal_risk_contribution_three_assets(self) -> None:
        cov = [
            [0.04, 0.01, 0.005],
            [0.01, 0.09, 0.02],
            [0.005, 0.02, 0.01],
        ]
        weights = self.opt.equal_risk_contribution(cov)
        self.assertAlmostEqual(sum(weights), 1.0, places=6)
        rc = self.opt.risk_contribution(weights, cov)
        self.assertAlmostEqual(rc[0], rc[1], places=4)
        self.assertAlmostEqual(rc[1], rc[2], places=4)


if __name__ == "__main__":
    unittest.main()
