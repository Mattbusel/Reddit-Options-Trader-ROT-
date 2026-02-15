"""Risk analytics for backtest results.

Computes a comprehensive set of risk metrics from a BacktestResult,
wrapping the lower-level functions from ``metrics.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from rot.backtest.metrics import (
    compute_cvar,
    compute_mae_mfe,
    compute_recovery_factor,
    compute_var,
)
from rot.backtest.result import BacktestResult, DrawdownPeriod


@dataclass(frozen=True)
class RiskMetrics:
    """Comprehensive risk metrics for a backtest run."""

    # Value at Risk
    var_95: float          # 95% confidence VaR (positive = loss %)
    var_99: float          # 99% confidence VaR

    # Conditional VaR (Expected Shortfall)
    cvar_95: float
    cvar_99: float

    # Max Adverse / Favorable Excursion
    mae_avg: float         # avg loss on losing trades (%)
    mae_max: float         # worst single loss (%)
    mfe_avg: float         # avg gain on winning trades (%)
    mfe_max: float         # best single gain (%)

    # Recovery
    recovery_factor: float  # total return / max drawdown

    # Drawdown analysis
    max_drawdown_pct: float
    max_drawdown_duration_s: float
    avg_drawdown_pct: float
    num_drawdowns: int

    # Underwater analysis
    longest_underwater_s: float    # longest time below previous peak
    pct_time_underwater: float     # fraction of time in drawdown

    # Risk/reward
    gain_to_pain_ratio: float      # sum(gains) / sum(|losses|) = profit factor
    ulcer_index: float             # RMS of drawdowns (measures pain)

    # Tail risk
    worst_trade_pct: float
    best_trade_pct: float
    skewness: float               # positive = right-skewed (good)
    kurtosis: float               # high = fat tails


def _compute_skewness(values: List[float]) -> float:
    """Compute sample skewness."""
    n = len(values)
    if n < 3:
        return 0.0
    mean = sum(values) / n
    m2 = sum((x - mean) ** 2 for x in values) / n
    m3 = sum((x - mean) ** 3 for x in values) / n
    if m2 < 1e-12:
        return 0.0
    return m3 / (m2 ** 1.5)


def _compute_kurtosis(values: List[float]) -> float:
    """Compute excess kurtosis (normal distribution = 0)."""
    n = len(values)
    if n < 4:
        return 0.0
    mean = sum(values) / n
    m2 = sum((x - mean) ** 2 for x in values) / n
    m4 = sum((x - mean) ** 4 for x in values) / n
    if m2 < 1e-12:
        return 0.0
    return (m4 / (m2 ** 2)) - 3.0


def _compute_ulcer_index(drawdown_periods: List[DrawdownPeriod]) -> float:
    """Ulcer Index = RMS of drawdown percentages."""
    if not drawdown_periods:
        return 0.0
    sum_sq = sum(dd.drawdown_pct ** 2 for dd in drawdown_periods)
    return (sum_sq / len(drawdown_periods)) ** 0.5


def compute_risk_metrics(result: BacktestResult) -> RiskMetrics:
    """Compute comprehensive risk metrics from a BacktestResult.

    Parameters
    ----------
    result:
        A completed BacktestResult with trades, equity_curve, and drawdown_periods.

    Returns
    -------
    RiskMetrics with all risk analytics populated.
    """
    ec = result.equity_curve
    trades = result.trades
    dd_periods = result.drawdown_periods

    # VaR / CVaR
    var_95 = compute_var(ec, confidence=0.95)
    var_99 = compute_var(ec, confidence=0.99)
    cvar_95 = compute_cvar(ec, confidence=0.95)
    cvar_99 = compute_cvar(ec, confidence=0.99)

    # MAE/MFE
    mae_mfe = compute_mae_mfe(trades)

    # Recovery factor
    recovery = compute_recovery_factor(result.total_return_pct, result.max_drawdown_pct)

    # Drawdown analysis
    avg_dd = (
        sum(dd.drawdown_pct for dd in dd_periods) / len(dd_periods)
        if dd_periods
        else 0.0
    )

    # Underwater analysis
    longest_uw = max((dd.duration_s for dd in dd_periods), default=0.0)
    total_time = 0.0
    total_uw_time = 0.0
    if len(ec) >= 2:
        total_time = ec[-1].timestamp - ec[0].timestamp
        total_uw_time = sum(dd.duration_s for dd in dd_periods)
    pct_uw = total_uw_time / total_time if total_time > 0 else 0.0

    # Trade P&L distribution
    pnl_pcts = [t.pnl_pct for t in trades]
    worst = min(pnl_pcts) if pnl_pcts else 0.0
    best = max(pnl_pcts) if pnl_pcts else 0.0

    # Gain/pain
    gains = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
    losses = abs(sum(t.pnl_pct for t in trades if t.pnl_pct < 0))
    gain_to_pain = gains / losses if losses > 0.01 else (float("inf") if gains > 0 else 0.0)

    # Ulcer index
    ulcer = _compute_ulcer_index(dd_periods)

    # Distribution shape
    skew = _compute_skewness(pnl_pcts)
    kurt = _compute_kurtosis(pnl_pcts)

    return RiskMetrics(
        var_95=round(var_95, 4),
        var_99=round(var_99, 4),
        cvar_95=round(cvar_95, 4),
        cvar_99=round(cvar_99, 4),
        mae_avg=round(mae_mfe["mae_avg"], 4),
        mae_max=round(mae_mfe["mae_max"], 4),
        mfe_avg=round(mae_mfe["mfe_avg"], 4),
        mfe_max=round(mae_mfe["mfe_max"], 4),
        recovery_factor=round(recovery, 4),
        max_drawdown_pct=round(result.max_drawdown_pct, 4),
        max_drawdown_duration_s=round(result.max_drawdown_duration_s, 1),
        avg_drawdown_pct=round(avg_dd, 4),
        num_drawdowns=len(dd_periods),
        longest_underwater_s=round(longest_uw, 1),
        pct_time_underwater=round(pct_uw, 4),
        gain_to_pain_ratio=round(gain_to_pain, 4) if gain_to_pain != float("inf") else float("inf"),
        ulcer_index=round(ulcer, 4),
        worst_trade_pct=round(worst, 4),
        best_trade_pct=round(best, 4),
        skewness=round(skew, 4),
        kurtosis=round(kurt, 4),
    )
