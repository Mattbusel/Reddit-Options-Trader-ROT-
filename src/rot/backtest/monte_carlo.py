"""Monte Carlo simulation for backtesting confidence intervals.

Bootstrap resampling of historical trade P&L to estimate:
  - Equity curve percentile bands (fan chart)
  - Final equity distribution
  - Max drawdown distribution
  - Probability of profit / probability of ruin
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from rot.backtest.result import TradeRecord


@dataclass(frozen=True)
class MonteCarloResult:
    """Results from a Monte Carlo simulation."""

    n_simulations: int
    n_trades: int

    # Percentile equity curves: key = percentile (5/25/50/75/95)
    # Each value is a list of equity values (one per trade step)
    percentile_curves: Dict[int, List[float]]

    # Final equity distribution percentiles
    final_equity_p5: float
    final_equity_p25: float
    final_equity_p50: float
    final_equity_p75: float
    final_equity_p95: float

    # Max drawdown distribution percentiles
    max_drawdown_p5: float
    max_drawdown_p50: float
    max_drawdown_p95: float

    # Probabilities
    prob_profit: float      # fraction of simulations with positive return
    prob_ruin: float         # fraction where equity dropped below 50%
    prob_double: float       # fraction where equity doubled

    # Summary
    mean_final_equity: float
    std_final_equity: float


def _simulate_one(
    trade_pnl_pcts: List[float],
    starting_capital: float,
    rng: random.Random,
) -> Tuple[List[float], float, float]:
    """Run one bootstrap simulation.

    Returns (equity_at_each_step, final_equity, max_drawdown_pct).
    """
    equity = starting_capital
    peak = equity
    max_dd_pct = 0.0
    equities = [equity]

    n = len(trade_pnl_pcts)
    for _ in range(n):
        # Bootstrap: sample with replacement
        pnl_pct = rng.choice(trade_pnl_pcts)
        # Position size is implicitly same as original (pnl_pct already includes sizing)
        equity *= (1 + pnl_pct / 100.0)
        if equity < 0:
            equity = 0.0
        equities.append(equity)

        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak * 100
            if dd > max_dd_pct:
                max_dd_pct = dd

    return equities, equity, max_dd_pct


def _percentile(sorted_vals: List[float], pct: float) -> float:
    """Compute percentile from pre-sorted list."""
    if not sorted_vals:
        return 0.0
    idx = int(pct / 100.0 * (len(sorted_vals) - 1))
    idx = max(0, min(idx, len(sorted_vals) - 1))
    return sorted_vals[idx]


def run_monte_carlo(
    trades: List[TradeRecord],
    starting_capital: float = 10000.0,
    n_simulations: int = 1000,
    seed: Optional[int] = None,
) -> MonteCarloResult:
    """Run Monte Carlo bootstrap simulation.

    Parameters
    ----------
    trades:
        List of TradeRecord from a backtest run.
    starting_capital:
        Starting portfolio value.
    n_simulations:
        Number of bootstrap simulations.
    seed:
        Random seed for reproducibility (None = random).

    Returns
    -------
    MonteCarloResult with percentile bands and probabilities.
    """
    if not trades:
        return MonteCarloResult(
            n_simulations=n_simulations,
            n_trades=0,
            percentile_curves={5: [], 25: [], 50: [], 75: [], 95: []},
            final_equity_p5=starting_capital,
            final_equity_p25=starting_capital,
            final_equity_p50=starting_capital,
            final_equity_p75=starting_capital,
            final_equity_p95=starting_capital,
            max_drawdown_p5=0.0,
            max_drawdown_p50=0.0,
            max_drawdown_p95=0.0,
            prob_profit=0.0,
            prob_ruin=0.0,
            prob_double=0.0,
            mean_final_equity=starting_capital,
            std_final_equity=0.0,
        )

    rng = random.Random(seed)  # nosec B311 - Monte Carlo simulation, not cryptographic
    trade_pnls = [t.pnl_pct for t in trades]
    n_trades = len(trades)

    # Run simulations
    all_equities: List[List[float]] = []
    final_equities: List[float] = []
    max_drawdowns: List[float] = []

    for _ in range(n_simulations):
        equities, final_eq, max_dd = _simulate_one(
            trade_pnls, starting_capital, rng
        )
        all_equities.append(equities)
        final_equities.append(final_eq)
        max_drawdowns.append(max_dd)

    # Build percentile curves (equity at each trade step)
    percentile_curves: Dict[int, List[float]] = {p: [] for p in [5, 25, 50, 75, 95]}
    for step in range(n_trades + 1):
        step_equities = sorted(sim[step] for sim in all_equities)
        for p in percentile_curves:
            percentile_curves[p].append(round(_percentile(step_equities, p), 2))

    # Final equity stats
    sorted_finals = sorted(final_equities)
    mean_final = sum(final_equities) / len(final_equities)
    variance = sum((x - mean_final) ** 2 for x in final_equities) / len(final_equities)
    std_final = variance ** 0.5

    # Max drawdown stats
    sorted_dd = sorted(max_drawdowns)

    # Probabilities
    prob_profit = sum(1 for f in final_equities if f > starting_capital) / n_simulations
    prob_ruin = sum(1 for f in final_equities if f < starting_capital * 0.5) / n_simulations
    prob_double = sum(1 for f in final_equities if f >= starting_capital * 2.0) / n_simulations

    return MonteCarloResult(
        n_simulations=n_simulations,
        n_trades=n_trades,
        percentile_curves=percentile_curves,
        final_equity_p5=round(_percentile(sorted_finals, 5), 2),
        final_equity_p25=round(_percentile(sorted_finals, 25), 2),
        final_equity_p50=round(_percentile(sorted_finals, 50), 2),
        final_equity_p75=round(_percentile(sorted_finals, 75), 2),
        final_equity_p95=round(_percentile(sorted_finals, 95), 2),
        max_drawdown_p5=round(_percentile(sorted_dd, 5), 2),
        max_drawdown_p50=round(_percentile(sorted_dd, 50), 2),
        max_drawdown_p95=round(_percentile(sorted_dd, 95), 2),
        prob_profit=round(prob_profit, 4),
        prob_ruin=round(prob_ruin, 4),
        prob_double=round(prob_double, 4),
        mean_final_equity=round(mean_final, 2),
        std_final_equity=round(std_final, 2),
    )
