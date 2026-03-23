"""Correlation trading analytics: Pearson, EWMA, pairs trades, and dispersion."""

import math
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Correlation functions
# ---------------------------------------------------------------------------


def pearson_corr(x: List[float], y: List[float]) -> float:
    """Standard Pearson correlation coefficient between two series."""
    n = min(len(x), len(y))
    if n < 2:
        return float("nan")
    x = x[:n]
    y = y[:n]
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)
    denom = math.sqrt(var_x * var_y)
    if denom == 0.0:
        return float("nan")
    return cov / denom


def rolling_corr(x: List[float], y: List[float], window: int) -> List[float]:
    """Rolling Pearson correlation with a fixed window size."""
    n = min(len(x), len(y))
    if n < window or window < 2:
        return []
    result = []
    for i in range(window, n + 1):
        xi = x[i - window:i]
        yi = y[i - window:i]
        result.append(pearson_corr(xi, yi))
    return result


def ewma_corr(x: List[float], y: List[float], lambda_: float = 0.94) -> float:
    """
    Exponentially weighted moving average (EWMA) correlation.

    Uses the RiskMetrics EWMA methodology with decay factor lambda_.
    """
    n = min(len(x), len(y))
    if n < 2:
        return float("nan")
    x = x[:n]
    y = y[:n]

    # EWMA means
    ex = x[0]
    ey = y[0]
    for i in range(1, n):
        ex = lambda_ * ex + (1 - lambda_) * x[i]
        ey = lambda_ * ey + (1 - lambda_) * y[i]

    # EWMA variances and covariance
    var_x = 0.0
    var_y = 0.0
    cov_xy = 0.0
    for i in range(n):
        dx = x[i] - ex
        dy = y[i] - ey
        w = (1 - lambda_) * lambda_ ** (n - 1 - i)
        var_x += w * dx * dx
        var_y += w * dy * dy
        cov_xy += w * dx * dy

    denom = math.sqrt(var_x * var_y)
    if denom == 0.0:
        return float("nan")
    return cov_xy / denom


# ---------------------------------------------------------------------------
# Correlation Matrix
# ---------------------------------------------------------------------------


class CorrelationMatrix:
    """NxN correlation matrix built from a list of return series."""

    def __init__(self, series: List[List[float]]) -> None:
        self._n = len(series)
        self._matrix: List[List[float]] = [
            [0.0] * self._n for _ in range(self._n)
        ]
        for i in range(self._n):
            for j in range(self._n):
                if i == j:
                    self._matrix[i][j] = 1.0
                elif j > i:
                    c = pearson_corr(series[i], series[j])
                    self._matrix[i][j] = c
                    self._matrix[j][i] = c

    def get(self, i: int, j: int) -> float:
        """Return correlation between series i and j."""
        return self._matrix[i][j]

    def eigenvalues(self, max_iter: int = 200, tol: float = 1e-8) -> List[float]:
        """
        Approximate dominant eigenvalues using the power iteration method
        (deflation after each eigenvalue).
        """
        n = self._n
        eigenvalues_list = []
        A = [row[:] for row in self._matrix]  # copy

        def mat_vec(M: List[List[float]], v: List[float]) -> List[float]:
            res = [0.0] * n
            for r in range(n):
                for c in range(n):
                    res[r] += M[r][c] * v[c]
            return res

        def norm(v: List[float]) -> float:
            return math.sqrt(sum(vi ** 2 for vi in v))

        def dot(a: List[float], b: List[float]) -> float:
            return sum(ai * bi for ai, bi in zip(a, b))

        for _ in range(n):
            # Random starting vector
            v = [1.0 if i == _ % n else 0.0 for i in range(n)]
            vn = norm(v)
            if vn == 0:
                continue
            v = [vi / vn for vi in v]

            eigenval = 0.0
            for _ in range(max_iter):
                w = mat_vec(A, v)
                new_eigenval = dot(v, w)
                wn = norm(w)
                if wn < tol:
                    break
                v_new = [wi / wn for wi in w]
                if abs(new_eigenval - eigenval) < tol:
                    eigenval = new_eigenval
                    v = v_new
                    break
                eigenval = new_eigenval
                v = v_new

            eigenvalues_list.append(eigenval)

            # Deflate: A = A - eigenval * v * v^T
            for r in range(n):
                for c in range(n):
                    A[r][c] -= eigenval * v[r] * v[c]

        return sorted(eigenvalues_list, reverse=True)

    def is_positive_definite(self) -> bool:
        """Check positive definiteness via eigenvalue sign."""
        evs = self.eigenvalues()
        return all(ev > -1e-8 for ev in evs)


# ---------------------------------------------------------------------------
# Pairs Trade
# ---------------------------------------------------------------------------


class PairsTrade:
    """Statistical pairs trading: spread, z-score, signals, and backtest."""

    def __init__(
        self,
        series_a: List[float],
        series_b: List[float],
        lookback: int = 60,
    ) -> None:
        self.series_a = series_a
        self.series_b = series_b
        self.lookback = lookback

    def hedge_ratio(self) -> float:
        """OLS beta of series_a on series_b over the lookback window."""
        n = min(len(self.series_a), len(self.series_b), self.lookback)
        if n < 2:
            return 1.0
        a = self.series_a[-n:]
        b = self.series_b[-n:]
        mean_b = sum(b) / n
        mean_a = sum(a) / n
        cov = sum((b[i] - mean_b) * (a[i] - mean_a) for i in range(n))
        var_b = sum((bi - mean_b) ** 2 for bi in b)
        if var_b == 0.0:
            return 1.0
        return cov / var_b

    def spread(self) -> List[float]:
        """Spread = a - beta * b."""
        beta = self.hedge_ratio()
        n = min(len(self.series_a), len(self.series_b))
        return [
            self.series_a[i] - beta * self.series_b[i]
            for i in range(n)
        ]

    def zscore(self) -> List[float]:
        """Z-score of the spread using rolling mean and std (lookback window)."""
        sprd = self.spread()
        n = len(sprd)
        result = []
        lb = self.lookback
        for i in range(n):
            window = sprd[max(0, i - lb + 1): i + 1]
            if len(window) < 2:
                result.append(0.0)
                continue
            mean_w = sum(window) / len(window)
            std_w = math.sqrt(sum((v - mean_w) ** 2 for v in window) / len(window))
            if std_w < 1e-12:
                result.append(0.0)
            else:
                result.append((sprd[i] - mean_w) / std_w)
        return result

    def signals(
        self,
        entry_threshold: float = 2.0,
        exit_threshold: float = 0.5,
    ) -> List[int]:
        """
        Trading signals based on z-score thresholds.

        +1 = long spread (long A, short B)
        -1 = short spread (short A, long B)
         0 = flat
        """
        zscores = self.zscore()
        signals = []
        position = 0
        for z in zscores:
            if position == 0:
                if z < -entry_threshold:
                    position = 1
                elif z > entry_threshold:
                    position = -1
            elif position == 1:
                if z > -exit_threshold:
                    position = 0
            elif position == -1:
                if z < exit_threshold:
                    position = 0
            signals.append(position)
        return signals

    def backtest(self, initial_capital: float = 100_000.0) -> dict:
        """
        Simple backtest of the pairs strategy.

        Returns a dict with:
          - 'final_capital': final portfolio value
          - 'total_return': total return as a fraction
          - 'num_trades': number of position changes
          - 'sharpe': annualized Sharpe ratio (252 days assumed)
        """
        sigs = self.signals()
        sprd = self.spread()
        n = len(sigs)
        capital = initial_capital
        daily_pnls = []
        prev_sig = 0
        num_trades = 0

        for i in range(1, n):
            if i >= len(sprd):
                break
            sig = sigs[i - 1]
            spread_change = sprd[i] - sprd[i - 1]
            pnl = sig * spread_change
            capital += pnl
            daily_pnls.append(pnl)
            if sig != prev_sig:
                num_trades += 1
            prev_sig = sig

        total_return = (capital - initial_capital) / initial_capital if initial_capital > 0 else 0.0

        # Annualized Sharpe
        if len(daily_pnls) > 1:
            mean_pnl = sum(daily_pnls) / len(daily_pnls)
            std_pnl = math.sqrt(
                sum((p - mean_pnl) ** 2 for p in daily_pnls) / len(daily_pnls)
            )
            sharpe = (mean_pnl / std_pnl * math.sqrt(252)) if std_pnl > 0 else 0.0
        else:
            sharpe = 0.0

        return {
            "final_capital": capital,
            "total_return": total_return,
            "num_trades": num_trades,
            "sharpe": sharpe,
        }


# ---------------------------------------------------------------------------
# Dispersion Trade
# ---------------------------------------------------------------------------


class DispersionTrade:
    """
    Dispersion trading: exploit the relationship between index and component vols.

    Profit when implied correlation is too high (sell index vol, buy component vols)
    or too low (buy index vol, sell component vols).
    """

    def __init__(
        self,
        index_returns: List[float],
        component_returns: List[List[float]],
        weights: List[float],
    ) -> None:
        self.index_returns = index_returns
        self.component_returns = component_returns
        self.weights = weights

    def _realized_vol(self, returns: List[float]) -> float:
        if len(returns) < 2:
            return 0.0
        n = len(returns)
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        return math.sqrt(variance * 252)  # annualized

    def realized_index_vol(self) -> float:
        """Annualized realized volatility of the index."""
        return self._realized_vol(self.index_returns)

    def realized_component_vol(self) -> float:
        """Weighted average of realized component volatilities."""
        if len(self.component_returns) != len(self.weights):
            return 0.0
        total_weight = sum(self.weights)
        if total_weight == 0.0:
            return 0.0
        weighted_vol = sum(
            self.weights[i] * self._realized_vol(self.component_returns[i])
            for i in range(len(self.weights))
        )
        return weighted_vol / total_weight

    def correlation_implied(self) -> float:
        """
        Implied correlation from index and component volatilities.

        rho_implied ≈ (sigma_index / sigma_components)^2
        """
        sigma_idx = self.realized_index_vol()
        sigma_comp = self.realized_component_vol()
        if sigma_comp == 0.0:
            return float("nan")
        return (sigma_idx / sigma_comp) ** 2

    def dispersion_pnl(self, long_components: bool = True) -> float:
        """
        Approximate dispersion P&L.

        If long_components=True: long component vols, short index vol.
        P&L is proportional to the difference between weighted component vol
        and index vol.
        """
        sigma_idx = self.realized_index_vol()
        sigma_comp = self.realized_component_vol()
        spread = sigma_comp - sigma_idx
        if long_components:
            return spread   # profit when components outperform
        else:
            return -spread  # profit when index outperforms
