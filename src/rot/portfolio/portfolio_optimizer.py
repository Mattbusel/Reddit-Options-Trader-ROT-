"""
Constrained portfolio optimization using pure Python (no numpy/scipy dependency).
Implements gradient-based methods, risk parity, Black-Litterman, and efficient frontier.
"""
import math


def ols(y, X):
    """Gaussian elimination least squares: solve X^T X beta = X^T y."""
    n = len(X)
    k = len(X[0])
    # Build XtX and Xty
    XtX = [[0.0] * k for _ in range(k)]
    Xty = [0.0] * k
    for i in range(n):
        for j in range(k):
            Xty[j] += X[i][j] * y[i]
            for l in range(k):
                XtX[j][l] += X[i][j] * X[i][l]
    # Gaussian elimination with partial pivoting
    aug = [row[:] + [Xty[r]] for r, row in enumerate(XtX)]
    for col in range(k):
        # Find pivot
        max_row = col
        for row in range(col + 1, k):
            if abs(aug[row][col]) > abs(aug[max_row][col]):
                max_row = row
        aug[col], aug[max_row] = aug[max_row], aug[col]
        if abs(aug[col][col]) < 1e-14:
            continue
        pivot = aug[col][col]
        for row in range(k):
            if row == col:
                continue
            factor = aug[row][col] / pivot
            for c in range(k + 1):
                aug[row][c] -= factor * aug[col][c]
    beta = [aug[r][k] / aug[r][r] if abs(aug[r][r]) > 1e-14 else 0.0 for r in range(k)]
    return beta


def portfolio_variance(weights, cov):
    """Compute w^T Sigma w."""
    n = len(weights)
    var = 0.0
    for i in range(n):
        for j in range(n):
            var += weights[i] * cov[i][j] * weights[j]
    return var


def portfolio_return(weights, returns):
    """Compute w^T mu."""
    return sum(w * r for w, r in zip(weights, returns))


def portfolio_sharpe(weights, returns, cov, rf=0.04):
    """Compute (w^T mu - rf) / sqrt(w^T Sigma w)."""
    pr = portfolio_return(weights, returns)
    pv = portfolio_variance(weights, cov)
    vol = math.sqrt(max(pv, 1e-12))
    return (pr - rf) / vol


class PortfolioOptimizer:
    """
    Constrained portfolio optimizer implementing:
    - Sharpe maximization (gradient ascent)
    - Variance minimization (gradient descent)
    - Risk parity (equal risk contribution)
    - Efficient frontier
    - Black-Litterman posterior weights
    """

    def __init__(self, returns: list, cov: list, risk_free: float = 0.04):
        self.returns = returns
        self.cov = cov
        self.rf = risk_free
        self.n = len(returns)

    def maximize_sharpe(self, max_iter: int = 1000, lr: float = 0.01) -> list:
        """Gradient ascent on Sharpe ratio with long-only projection."""
        w = [1.0 / self.n] * self.n
        best_sharpe = -1e18
        best_w = w[:]

        for _ in range(max_iter):
            pr = portfolio_return(w, self.returns)
            pv = portfolio_variance(w, self.cov)
            vol = math.sqrt(max(pv, 1e-12))
            excess = pr - self.rf

            # Gradient of Sharpe w.r.t. weights
            # d/dw [excess/vol] = (dExcess/dw * vol - excess * dVol/dw) / vol^2
            grad = []
            for i in range(self.n):
                d_excess = self.returns[i]
                cov_w_i = sum(self.cov[i][j] * w[j] for j in range(self.n))
                d_vol = cov_w_i / vol
                g = (d_excess * vol - excess * d_vol) / (vol * vol)
                grad.append(g)

            # Ascent step
            w = [w[i] + lr * grad[i] for i in range(self.n)]
            w = self.project_long_only(w)
            w = self.project_sum_to_one(w)

            sr = portfolio_sharpe(w, self.returns, self.cov, self.rf)
            if sr > best_sharpe:
                best_sharpe = sr
                best_w = w[:]

        return best_w

    def minimize_variance(self, target_return: float = None, max_iter: int = 1000) -> list:
        """Gradient descent on portfolio variance with optional return constraint."""
        w = [1.0 / self.n] * self.n
        lr = 0.01

        for it in range(max_iter):
            pv = portfolio_variance(w, self.cov)
            # Gradient of variance: 2 * Sigma * w
            grad = []
            for i in range(self.n):
                g = 2.0 * sum(self.cov[i][j] * w[j] for j in range(self.n))
                grad.append(g)

            # If target return constraint, add Lagrange penalty
            if target_return is not None:
                pr = portfolio_return(w, self.returns)
                penalty = 10.0 * (pr - target_return)
                for i in range(self.n):
                    grad[i] -= penalty * self.returns[i]

            step = lr / (1 + it * 0.001)
            w = [w[i] - step * grad[i] for i in range(self.n)]
            w = self.project_long_only(w)
            w = self.project_sum_to_one(w)

        return w

    def risk_parity(self, max_iter: int = 500) -> list:
        """Equal risk contribution: each asset contributes equally to total variance."""
        w = [1.0 / self.n] * self.n
        lr = 0.001

        for _ in range(max_iter):
            pv = portfolio_variance(w, self.cov)
            if pv < 1e-12:
                break

            # Marginal risk contribution: (Sigma w)_i
            mrc = [sum(self.cov[i][j] * w[j] for j in range(self.n)) for i in range(self.n)]
            # Risk contribution: w_i * MRC_i
            rc = [w[i] * mrc[i] for i in range(self.n)]
            target_rc = pv / self.n  # Equal contribution target

            # Gradient to equalize risk contributions
            grad = [rc[i] - target_rc for i in range(self.n)]

            w = [max(1e-8, w[i] - lr * grad[i]) for i in range(self.n)]
            w = self.project_sum_to_one(w)

        return w

    @staticmethod
    def project_long_only(weights: list) -> list:
        """Clip negative weights to zero and renormalize."""
        w = [max(0.0, x) for x in weights]
        s = sum(w)
        if s < 1e-12:
            n = len(w)
            return [1.0 / n] * n
        return [x / s for x in w]

    @staticmethod
    def project_sum_to_one(weights: list) -> list:
        """Renormalize weights to sum to one."""
        s = sum(weights)
        if abs(s) < 1e-12:
            n = len(weights)
            return [1.0 / n] * n
        return [x / s for x in weights]

    @staticmethod
    def project_max_weight(weights: list, max_w: float) -> list:
        """Iterative projection: clip to max_w and renormalize until feasible."""
        w = weights[:]
        for _ in range(100):
            w = [min(x, max_w) for x in w]
            s = sum(w)
            if s < 1e-12:
                n = len(w)
                return [1.0 / n] * n
            w = [x / s for x in w]
            if all(x <= max_w + 1e-9 for x in w):
                break
        return w

    def efficient_frontier(self, n_points: int = 20) -> list:
        """
        Compute efficient frontier as list of (return, vol, weights) tuples.
        Sweeps target returns from min-var to max-return portfolio.
        """
        # Bounds for target return
        min_ret = min(self.returns)
        max_ret = max(self.returns)

        frontier = []
        for i in range(n_points):
            t = i / max(n_points - 1, 1)
            target = min_ret + t * (max_ret - min_ret)
            w = self.minimize_variance(target_return=target)
            pr = portfolio_return(w, self.returns)
            pv = portfolio_variance(w, self.cov)
            vol = math.sqrt(max(pv, 0.0))
            frontier.append((pr, vol, w))

        return frontier

    def black_litterman(self, views: list, view_confidences: list, tau: float = 0.05) -> list:
        """
        Black-Litterman posterior weights.
        views: list of (asset_index, expected_return) pairs
        view_confidences: list of confidence scalars (0..1) per view
        Returns posterior expected returns used to compute max-Sharpe weights.
        """
        n = self.n

        # Market-cap equilibrium returns approximation (use equal weight)
        w_eq = [1.0 / n] * n
        # Pi = delta * Sigma * w_eq (risk aversion delta ~ 2.5)
        delta = 2.5
        pi = [delta * sum(self.cov[i][j] * w_eq[j] for j in range(n)) for i in range(n)]

        if not views:
            return self.maximize_sharpe()

        k = len(views)
        # Pick matrix P: k x n
        P = [[0.0] * n for _ in range(k)]
        Q = [0.0] * k
        omega_diag = []

        for idx, (asset_idx, view_ret) in enumerate(views):
            P[idx][asset_idx] = 1.0
            Q[idx] = view_ret
            conf = max(1e-6, min(1.0, view_confidences[idx]))
            omega_diag.append((1.0 - conf) / conf * tau)

        # Posterior mean: mu* = [(tau * Sigma)^-1 + P^T Omega^-1 P]^-1 * [(tau * Sigma)^-1 pi + P^T Omega^-1 Q]
        # Simplified approximation using view blending
        mu_post = pi[:]
        for idx, (asset_idx, view_ret) in enumerate(views):
            conf = max(1e-6, min(1.0, view_confidences[idx]))
            mu_post[asset_idx] = (1 - conf) * mu_post[asset_idx] + conf * view_ret

        # Optimize with posterior returns
        opt = PortfolioOptimizer(mu_post, self.cov, self.rf)
        return opt.maximize_sharpe()
