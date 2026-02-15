"""Pure stateless metric calculation functions for backtesting.

All functions take simple Python lists and return scalars or dicts.
No side effects, no I/O.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from rot.backtest.result import DrawdownPeriod, EquityPoint, TradeRecord


# ── Helper: daily returns from equity curve ──


def _daily_returns(equity_curve: List[EquityPoint]) -> List[float]:
    """Compute daily percentage returns from an equity curve.

    Groups equity points by calendar day (UTC) and computes
    close-to-close returns.
    """
    if len(equity_curve) < 2:
        return []

    # Group by day (take last equity of each day)
    daily: Dict[str, float] = {}
    for ep in equity_curve:
        day_key = datetime.fromtimestamp(ep.timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
        daily[day_key] = ep.equity

    values = list(daily.values())
    if len(values) < 2:
        return []

    returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            returns.append((values[i] - values[i - 1]) / values[i - 1])
    return returns


# ── Core metric functions ──


def compute_sharpe_ratio(
    equity_curve: List[EquityPoint],
    risk_free_rate: float = 0.02,
) -> Optional[float]:
    """Annualized Sharpe ratio from equity curve daily returns.

    Returns None if insufficient data (< 5 days).
    """
    returns = _daily_returns(equity_curve)
    if len(returns) < 5:
        return None

    daily_rf = risk_free_rate / 252
    excess = [r - daily_rf for r in returns]
    mean_excess = sum(excess) / len(excess)
    variance = sum((r - mean_excess) ** 2 for r in excess) / len(excess)
    std_dev = math.sqrt(variance)

    if std_dev < 1e-10:
        return None
    return (mean_excess / std_dev) * math.sqrt(252)


def compute_sortino_ratio(
    equity_curve: List[EquityPoint],
    risk_free_rate: float = 0.02,
) -> Optional[float]:
    """Annualized Sortino ratio (downside deviation only).

    Returns None if insufficient data or no downside deviation.
    """
    returns = _daily_returns(equity_curve)
    if len(returns) < 5:
        return None

    daily_rf = risk_free_rate / 252
    excess = [r - daily_rf for r in returns]
    mean_excess = sum(excess) / len(excess)

    # Only negative excess returns for downside deviation
    downside = [r ** 2 for r in excess if r < 0]
    if not downside:
        return None

    downside_dev = math.sqrt(sum(downside) / len(excess))
    if downside_dev < 1e-10:
        return None
    return (mean_excess / downside_dev) * math.sqrt(252)


def compute_calmar_ratio(annual_return_pct: float, max_drawdown_pct: float) -> Optional[float]:
    """Calmar ratio = annual return / max drawdown.

    Returns None if max drawdown is zero.
    """
    if max_drawdown_pct < 0.01:
        return None
    return annual_return_pct / max_drawdown_pct


def compute_max_drawdown(equity_curve: List[EquityPoint]) -> Tuple[float, float]:
    """Compute max drawdown percentage and duration in seconds.

    Returns (max_drawdown_pct, max_drawdown_duration_s).
    Drawdown pct is a positive number (e.g. 15.0 means -15%).
    """
    if len(equity_curve) < 2:
        return 0.0, 0.0

    peak = equity_curve[0].equity
    max_dd_pct = 0.0
    max_dd_duration = 0.0
    current_dd_start = equity_curve[0].timestamp

    for ep in equity_curve:
        if ep.equity >= peak:
            peak = ep.equity
            current_dd_start = ep.timestamp
        else:
            dd_pct = (peak - ep.equity) / peak * 100 if peak > 0 else 0.0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_duration = ep.timestamp - current_dd_start

    return max_dd_pct, max_dd_duration


def compute_drawdown_periods(equity_curve: List[EquityPoint]) -> List[DrawdownPeriod]:
    """Identify all drawdown periods from an equity curve."""
    if len(equity_curve) < 2:
        return []

    periods: List[DrawdownPeriod] = []
    peak = equity_curve[0].equity
    peak_ts = equity_curve[0].timestamp
    in_drawdown = False
    dd_start_ts = 0.0
    trough_equity = peak
    trough_ts = peak_ts

    for ep in equity_curve:
        if ep.equity >= peak:
            # New high: close any open drawdown
            if in_drawdown:
                dd_pct = (peak - trough_equity) / peak * 100 if peak > 0 else 0.0
                if dd_pct > 0.1:  # only record meaningful drawdowns
                    periods.append(DrawdownPeriod(
                        start_ts=dd_start_ts,
                        trough_ts=trough_ts,
                        end_ts=ep.timestamp,
                        peak_equity=peak,
                        trough_equity=trough_equity,
                        drawdown_pct=dd_pct,
                        duration_s=ep.timestamp - dd_start_ts,
                    ))
                in_drawdown = False
            peak = ep.equity
            peak_ts = ep.timestamp
            trough_equity = peak
            trough_ts = peak_ts
        else:
            if not in_drawdown:
                in_drawdown = True
                dd_start_ts = peak_ts
            if ep.equity < trough_equity:
                trough_equity = ep.equity
                trough_ts = ep.timestamp

    # Handle open drawdown at end of curve
    if in_drawdown:
        dd_pct = (peak - trough_equity) / peak * 100 if peak > 0 else 0.0
        if dd_pct > 0.1:
            last_ts = equity_curve[-1].timestamp
            periods.append(DrawdownPeriod(
                start_ts=dd_start_ts,
                trough_ts=trough_ts,
                end_ts=0.0,  # 0 = still in drawdown
                peak_equity=peak,
                trough_equity=trough_equity,
                drawdown_pct=dd_pct,
                duration_s=last_ts - dd_start_ts,
            ))

    return periods


def compute_profit_factor(trades: List[TradeRecord]) -> float:
    """Profit factor = total gains / total losses. Returns 0.0 if no losses."""
    gross_gains = sum(t.pnl_dollars for t in trades if t.pnl_dollars > 0)
    gross_losses = abs(sum(t.pnl_dollars for t in trades if t.pnl_dollars < 0))
    if gross_losses < 0.01:
        return float("inf") if gross_gains > 0 else 0.0
    return gross_gains / gross_losses


def compute_expectancy(trades: List[TradeRecord]) -> float:
    """Average dollar P&L per trade."""
    if not trades:
        return 0.0
    return sum(t.pnl_dollars for t in trades) / len(trades)


def compute_win_rate(trades: List[TradeRecord]) -> float:
    """Win rate as fraction 0.0-1.0."""
    if not trades:
        return 0.0
    return sum(1 for t in trades if t.is_win) / len(trades)


def compute_monthly_returns(trades: List[TradeRecord]) -> Dict[str, float]:
    """P&L percentage aggregated by month (YYYY-MM key)."""
    monthly: Dict[str, float] = {}
    for t in trades:
        key = datetime.fromtimestamp(t.entry_time, tz=timezone.utc).strftime("%Y-%m")
        monthly[key] = monthly.get(key, 0.0) + t.pnl_pct
    return dict(sorted(monthly.items()))


def compute_strategy_breakdown(trades: List[TradeRecord]) -> Dict[str, Dict[str, float]]:
    """Per-strategy win rate, avg P&L, and trade count."""
    by_strategy: Dict[str, List[TradeRecord]] = {}
    for t in trades:
        by_strategy.setdefault(t.strategy, []).append(t)

    breakdown = {}
    for strategy, strades in by_strategy.items():
        wins = sum(1 for t in strades if t.is_win)
        total = len(strades)
        avg_pnl = sum(t.pnl_pct for t in strades) / total if total else 0.0
        breakdown[strategy] = {
            "trade_count": float(total),
            "win_rate": wins / total if total else 0.0,
            "avg_pnl_pct": round(avg_pnl, 2),
            "total_pnl_pct": round(sum(t.pnl_pct for t in strades), 2),
        }
    return breakdown


def compute_var(
    equity_curve: List[EquityPoint],
    confidence: float = 0.95,
) -> float:
    """Historical Value at Risk at given confidence level.

    Returns a positive number representing the loss at the given
    percentile (e.g. 2.5 means "you can lose up to 2.5% on 95% of days").
    """
    returns = _daily_returns(equity_curve)
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)
    index = int((1 - confidence) * len(sorted_returns))
    index = max(0, min(index, len(sorted_returns) - 1))
    return -sorted_returns[index] * 100  # convert to positive percentage


def compute_cvar(
    equity_curve: List[EquityPoint],
    confidence: float = 0.95,
) -> float:
    """Conditional VaR (Expected Shortfall) at given confidence level.

    Average of all losses beyond the VaR threshold.
    """
    returns = _daily_returns(equity_curve)
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)
    cutoff = int((1 - confidence) * len(sorted_returns))
    cutoff = max(1, cutoff)
    tail = sorted_returns[:cutoff]
    if not tail:
        return 0.0
    return -sum(tail) / len(tail) * 100


def compute_mae_mfe(trades: List[TradeRecord]) -> Dict[str, float]:
    """Average and max of Maximum Adverse Excursion and Maximum Favorable Excursion.

    Uses pnl_pct as a proxy (actual MAE/MFE requires intra-trade price data
    which we don't have; for losses MAE ≈ |pnl_pct| and for wins MFE ≈ pnl_pct).
    """
    if not trades:
        return {"mae_avg": 0.0, "mae_max": 0.0, "mfe_avg": 0.0, "mfe_max": 0.0}

    losses = [abs(t.pnl_pct) for t in trades if t.pnl_pct < 0]
    gains = [t.pnl_pct for t in trades if t.pnl_pct > 0]

    return {
        "mae_avg": sum(losses) / len(losses) if losses else 0.0,
        "mae_max": max(losses) if losses else 0.0,
        "mfe_avg": sum(gains) / len(gains) if gains else 0.0,
        "mfe_max": max(gains) if gains else 0.0,
    }


def compute_annual_return(total_return_pct: float, days: int) -> float:
    """Annualize a total return over a given number of calendar days."""
    if days <= 0:
        return 0.0
    years = days / 365.25
    if years < 0.01:
        return total_return_pct  # Very short period, don't annualize
    # Compound annual growth rate
    growth = 1 + total_return_pct / 100
    if growth <= 0:
        return -100.0
    annual = (growth ** (1 / years) - 1) * 100
    return annual


def compute_recovery_factor(total_return_pct: float, max_drawdown_pct: float) -> float:
    """Recovery factor = total return / max drawdown."""
    if max_drawdown_pct < 0.01:
        return 0.0
    return total_return_pct / max_drawdown_pct
