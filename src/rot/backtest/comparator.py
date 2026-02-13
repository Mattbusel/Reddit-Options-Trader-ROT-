"""Strategy comparison — side-by-side backtest analysis.

Compares multiple backtest results to determine relative performance,
correlation, and rankings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from rot.backtest.metrics import _daily_returns
from rot.backtest.benchmark import _compute_correlation
from rot.backtest.result import BacktestResult


@dataclass(frozen=True)
class StrategyStats:
    """Summary stats for one strategy in a comparison."""

    name: str
    total_return_pct: float
    annual_return_pct: float
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    total_trades: int


@dataclass(frozen=True)
class ComparisonResult:
    """Result of comparing multiple backtest strategies."""

    strategies: List[StrategyStats]
    n_strategies: int

    # Correlation matrix (strategy_i vs strategy_j daily returns)
    # Key: (name_i, name_j) → correlation
    correlation_matrix: Dict[Tuple[str, str], float]

    # Rankings by different metrics
    rank_by_return: List[str]       # strategy names sorted by total return desc
    rank_by_sharpe: List[str]       # sorted by Sharpe desc
    rank_by_drawdown: List[str]     # sorted by max drawdown asc (least = best)
    rank_by_win_rate: List[str]     # sorted by win rate desc

    # Summary table: metric_name → {strategy_name → value}
    summary_table: Dict[str, Dict[str, float]]


def compare_strategies(
    results: List[BacktestResult],
    names: List[str],
) -> ComparisonResult:
    """Compare multiple backtest results side-by-side.

    Parameters
    ----------
    results:
        List of BacktestResult from different strategies/configs.
    names:
        Names for each strategy (same order as results).

    Returns
    -------
    ComparisonResult with correlation matrix, rankings, summary table.
    """
    if not results or not names:
        return ComparisonResult(
            strategies=[],
            n_strategies=0,
            correlation_matrix={},
            rank_by_return=[],
            rank_by_sharpe=[],
            rank_by_drawdown=[],
            rank_by_win_rate=[],
            summary_table={},
        )

    # Build per-strategy stats
    strategies: List[StrategyStats] = []
    daily_returns_map: Dict[str, List[float]] = {}

    for result, name in zip(results, names):
        stats = StrategyStats(
            name=name,
            total_return_pct=result.total_return_pct,
            annual_return_pct=result.annual_return_pct,
            sharpe_ratio=result.sharpe_ratio,
            sortino_ratio=result.sortino_ratio,
            max_drawdown_pct=result.max_drawdown_pct,
            win_rate=result.win_rate,
            profit_factor=result.profit_factor,
            total_trades=result.total_trades,
        )
        strategies.append(stats)
        daily_returns_map[name] = _daily_returns(result.equity_curve)

    # Correlation matrix
    corr_matrix: Dict[Tuple[str, str], float] = {}
    for i, name_i in enumerate(names):
        for j, name_j in enumerate(names):
            if i == j:
                corr_matrix[(name_i, name_j)] = 1.0
            elif i < j:
                corr = _compute_correlation(
                    daily_returns_map[name_i],
                    daily_returns_map[name_j],
                )
                corr_matrix[(name_i, name_j)] = round(corr, 4)
                corr_matrix[(name_j, name_i)] = round(corr, 4)

    # Rankings
    rank_return = sorted(names, key=lambda n: _get_stat(strategies, n, "total_return_pct"), reverse=True)
    rank_sharpe = sorted(
        names,
        key=lambda n: _get_stat(strategies, n, "sharpe_ratio") or -999,
        reverse=True,
    )
    rank_drawdown = sorted(names, key=lambda n: _get_stat(strategies, n, "max_drawdown_pct"))
    rank_win_rate = sorted(names, key=lambda n: _get_stat(strategies, n, "win_rate"), reverse=True)

    # Summary table
    summary: Dict[str, Dict[str, float]] = {
        "total_return_pct": {},
        "annual_return_pct": {},
        "sharpe_ratio": {},
        "max_drawdown_pct": {},
        "win_rate": {},
        "profit_factor": {},
        "total_trades": {},
    }
    for s in strategies:
        summary["total_return_pct"][s.name] = s.total_return_pct
        summary["annual_return_pct"][s.name] = s.annual_return_pct
        summary["sharpe_ratio"][s.name] = s.sharpe_ratio if s.sharpe_ratio is not None else 0.0
        summary["max_drawdown_pct"][s.name] = s.max_drawdown_pct
        summary["win_rate"][s.name] = s.win_rate
        summary["profit_factor"][s.name] = s.profit_factor
        summary["total_trades"][s.name] = float(s.total_trades)

    return ComparisonResult(
        strategies=strategies,
        n_strategies=len(strategies),
        correlation_matrix=corr_matrix,
        rank_by_return=rank_return,
        rank_by_sharpe=rank_sharpe,
        rank_by_drawdown=rank_drawdown,
        rank_by_win_rate=rank_win_rate,
        summary_table=summary,
    )


def _get_stat(strategies: List[StrategyStats], name: str, attr: str) -> float:
    """Get a stat value by strategy name."""
    for s in strategies:
        if s.name == name:
            val = getattr(s, attr, 0.0)
            return val if val is not None else 0.0
    return 0.0
