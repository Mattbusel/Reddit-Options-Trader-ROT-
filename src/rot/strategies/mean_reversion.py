"""Mean reversion trading strategy implementation.

Provides tools for half-life estimation, z-score signals, pairs trading,
cointegration testing, backtesting, and lookback optimisation.
"""

from __future__ import annotations

import math
from typing import List, Optional


# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------


def estimate_half_life(prices: List[float]) -> float:
    """Estimate the mean-reversion half-life via AR(1) OLS regression.

    Regresses Δp_t on p_{t-1} to obtain the AR(1) coefficient β.
    Half-life = -ln(2) / ln(β).

    Returns a positive float (or inf if the series is non-mean-reverting).
    """
    if len(prices) < 3:
        return float("inf")

    n = len(prices) - 1
    y = [prices[i + 1] - prices[i] for i in range(n)]
    x = prices[:n]

    # OLS: β = (Σ x*y - n*x̄*ȳ) / (Σ x² - n*x̄²)
    x_mean = sum(x) / n
    y_mean = sum(y) / n
    num = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    den = sum((x[i] - x_mean) ** 2 for i in range(n))

    if abs(den) < 1e-12:
        return float("inf")

    beta = num / den

    if beta >= 0 or abs(beta) < 1e-12:
        return float("inf")

    return -math.log(2) / math.log(1 + beta)


def zscore(series: List[float], window: int) -> List[float]:
    """Compute a rolling z-score over *window* observations.

    Returns a list of the same length as *series*.
    Values before a full window of data are set to 0.0.
    """
    result = [0.0] * len(series)
    for i in range(window - 1, len(series)):
        window_data = series[i - window + 1 : i + 1]
        mean = sum(window_data) / window
        variance = sum((x - mean) ** 2 for x in window_data) / max(window - 1, 1)
        std = math.sqrt(max(variance, 1e-12))
        result[i] = (series[i] - mean) / std
    return result


# ---------------------------------------------------------------------------
# MeanReversionStrategy
# ---------------------------------------------------------------------------


class MeanReversionStrategy:
    """Single-instrument mean-reversion strategy based on z-score signals."""

    def __init__(
        self,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        stop_z: float = 3.5,
        lookback: int = 60,
    ) -> None:
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.stop_z = stop_z
        self.lookback = lookback

    def generate_signals(self, prices: List[float]) -> List[int]:
        """Generate +1 (long), -1 (short), 0 (flat) signals.

        Entry when |z| > entry_z, exit when |z| < exit_z,
        stop-loss when |z| > stop_z.
        """
        zscores = zscore(prices, self.lookback)
        signals = [0] * len(prices)
        position = 0  # current held position

        for i in range(self.lookback, len(prices)):
            z = zscores[i]

            # Stop-loss
            if position != 0 and abs(z) > self.stop_z:
                position = 0

            # Exit condition
            if position != 0 and abs(z) < self.exit_z:
                position = 0

            # Entry condition (only when flat)
            if position == 0:
                if z < -self.entry_z:
                    position = 1   # price is low relative to mean → buy
                elif z > self.entry_z:
                    position = -1  # price is high relative to mean → sell

            signals[i] = position

        return signals

    def pairs_zscore(
        self,
        series_a: List[float],
        series_b: List[float],
        window: int,
    ) -> List[float]:
        """Compute the rolling z-score of the OLS spread between series A and B.

        Spread = A - hedge_ratio * B, where hedge_ratio is estimated by OLS
        over the full window preceding each point.
        """
        n = min(len(series_a), len(series_b))
        spread = []

        for i in range(n):
            start = max(0, i - window + 1)
            xa = series_a[start : i + 1]
            xb = series_b[start : i + 1]
            if len(xa) < 2:
                spread.append(0.0)
                continue

            # OLS hedge ratio: β = Cov(A,B) / Var(B)
            mean_a = sum(xa) / len(xa)
            mean_b = sum(xb) / len(xb)
            cov = sum((xa[j] - mean_a) * (xb[j] - mean_b) for j in range(len(xa)))
            var_b = sum((xb[j] - mean_b) ** 2 for j in range(len(xb)))
            hedge = cov / var_b if abs(var_b) > 1e-12 else 1.0
            spread.append(series_a[i] - hedge * series_b[i])

        return zscore(spread, window)

    def cointegration_test(
        self,
        series_a: List[float],
        series_b: List[float],
    ) -> dict:
        """Lightweight cointegration test (ADF-lite).

        1. Regress A on B to get residuals.
        2. Fit AR(1) on residuals.
        3. Return t-statistic for the AR coefficient being < 1 (stationarity).
        """
        n = min(len(series_a), len(series_b))
        if n < 10:
            return {"t_stat": float("nan"), "cointegrated": False, "half_life": float("inf")}

        xa = series_a[:n]
        xb = series_b[:n]

        # Step 1: OLS regression A = alpha + beta * B + residuals
        mean_a = sum(xa) / n
        mean_b = sum(xb) / n
        cov = sum((xa[i] - mean_a) * (xb[i] - mean_b) for i in range(n))
        var_b = sum((xb[i] - mean_b) ** 2 for i in range(n))
        beta = cov / var_b if abs(var_b) > 1e-12 else 1.0
        alpha = mean_a - beta * mean_b
        residuals = [xa[i] - alpha - beta * xb[i] for i in range(n)]

        # Step 2: AR(1) on residuals: Δr_t = rho * r_{t-1} + noise
        half_life = estimate_half_life(residuals)

        # Step 3: t-stat for rho
        m = n - 1
        y = [residuals[i + 1] - residuals[i] for i in range(m)]
        x = residuals[:m]
        x_mean = sum(x) / m
        y_mean = sum(y) / m
        num = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(m))
        den = sum((x[i] - x_mean) ** 2 for i in range(m))
        if abs(den) < 1e-12:
            return {"t_stat": float("nan"), "cointegrated": False, "half_life": half_life}

        rho = num / den
        resid_ar = [y[i] - rho * x[i] for i in range(m)]
        sse = sum(r ** 2 for r in resid_ar)
        se = math.sqrt(sse / max(m - 2, 1) / max(den, 1e-12))
        t_stat = rho / se if se > 1e-12 else float("nan")

        # Rough 5% critical value for ADF ~ -2.86
        cointegrated = t_stat < -2.86

        return {
            "t_stat": t_stat,
            "cointegrated": cointegrated,
            "half_life": half_life,
            "hedge_ratio": beta,
        }

    def backtest(
        self,
        prices: List[float],
        signals: List[int],
        initial_capital: float = 100_000.0,
    ) -> dict:
        """Run a simple single-asset backtest.

        Returns pnl, sharpe, max_drawdown, and win_rate.
        """
        n = min(len(prices), len(signals))
        if n < 2:
            return {
                "pnl": 0.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "final_capital": initial_capital,
            }

        capital = initial_capital
        peak = capital
        max_dd = 0.0
        daily_returns = []
        wins = 0
        trades = 0

        for i in range(1, n):
            ret = (prices[i] - prices[i - 1]) / max(abs(prices[i - 1]), 1e-12)
            trade_ret = signals[i - 1] * ret
            capital *= 1.0 + trade_ret
            daily_returns.append(trade_ret)

            if capital > peak:
                peak = capital
            dd = (peak - capital) / max(peak, 1e-12)
            if dd > max_dd:
                max_dd = dd

            if signals[i - 1] != 0:
                trades += 1
                if trade_ret > 0:
                    wins += 1

        pnl = capital - initial_capital
        mean_ret = sum(daily_returns) / max(len(daily_returns), 1)
        std_ret = math.sqrt(
            sum((r - mean_ret) ** 2 for r in daily_returns) / max(len(daily_returns) - 1, 1)
        )
        sharpe = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 1e-12 else 0.0
        win_rate = wins / max(trades, 1)

        return {
            "pnl": pnl,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "final_capital": capital,
        }

    def optimal_lookback(
        self,
        prices: List[float],
        lookbacks: Optional[List[int]] = None,
    ) -> int:
        """Find the lookback that minimises half-life estimation error.

        For each candidate lookback window, estimate half-life on each
        sub-window and minimise variance of the estimates.
        """
        if lookbacks is None:
            lookbacks = [20, 30, 40, 60, 90, 120]

        best_lookback = lookbacks[0]
        best_score = float("inf")

        for lb in lookbacks:
            if lb >= len(prices):
                continue
            estimates = []
            for start in range(0, len(prices) - lb, lb // 2):
                window_prices = prices[start : start + lb]
                hl = estimate_half_life(window_prices)
                if math.isfinite(hl):
                    estimates.append(hl)
            if len(estimates) < 2:
                continue
            mean_hl = sum(estimates) / len(estimates)
            variance = sum((e - mean_hl) ** 2 for e in estimates) / len(estimates)
            if variance < best_score:
                best_score = variance
                best_lookback = lb

        return best_lookback
