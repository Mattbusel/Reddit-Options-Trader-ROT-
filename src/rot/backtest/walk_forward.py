"""Walk-forward analysis for backtest validation.

Splits signal history into chronological in-sample / out-of-sample
folds to detect overfitting and measure strategy stability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from rot.backtest.config import BacktestConfig
from rot.backtest.engine import BacktestEngine
from rot.backtest.result import BacktestResult


@dataclass(frozen=True)
class WalkForwardFold:
    """A single in-sample / out-of-sample fold."""

    fold_index: int
    is_signals: int        # number of in-sample signals
    oos_signals: int       # number of out-of-sample signals
    is_return_pct: float   # in-sample total return
    oos_return_pct: float  # out-of-sample total return
    is_sharpe: Optional[float]
    oos_sharpe: Optional[float]
    is_win_rate: float
    oos_win_rate: float
    degradation_pct: float  # (IS_return - OOS_return) / |IS_return| * 100


@dataclass(frozen=True)
class WalkForwardResult:
    """Results from walk-forward analysis across all folds."""

    n_folds: int
    in_sample_pct: float
    folds: List[WalkForwardFold]

    # Aggregated metrics
    avg_oos_return_pct: float
    avg_oos_win_rate: float
    avg_degradation_pct: float

    # Stability score: 0-1 (high = stable, consistent across folds)
    stability_score: float

    # Summary
    total_is_signals: int
    total_oos_signals: int


def run_walk_forward(
    signals: List[Dict[str, Any]],
    config: BacktestConfig,
    n_folds: int = 5,
    in_sample_pct: float = 0.7,
) -> WalkForwardResult:
    """Run walk-forward analysis.

    Parameters
    ----------
    signals:
        List of signal dicts (same format as engine.run()).
    config:
        Backtest configuration.
    n_folds:
        Number of chronological folds.
    in_sample_pct:
        Fraction of each fold used for in-sample (0.5-0.9).

    Returns
    -------
    WalkForwardResult with per-fold and aggregate metrics.
    """
    # Sort chronologically
    sorted_signals = sorted(signals, key=lambda s: s.get("created_at", 0))
    n = len(sorted_signals)

    if n < n_folds * 4:
        # Not enough signals for meaningful walk-forward
        return WalkForwardResult(
            n_folds=0,
            in_sample_pct=in_sample_pct,
            folds=[],
            avg_oos_return_pct=0.0,
            avg_oos_win_rate=0.0,
            avg_degradation_pct=0.0,
            stability_score=0.0,
            total_is_signals=0,
            total_oos_signals=0,
        )

    engine = BacktestEngine()
    fold_size = n // n_folds
    folds: List[WalkForwardFold] = []

    for i in range(n_folds):
        start = i * fold_size
        end = start + fold_size if i < n_folds - 1 else n
        fold_signals = sorted_signals[start:end]

        if len(fold_signals) < 4:
            continue

        # Split into IS / OOS
        split_idx = int(len(fold_signals) * in_sample_pct)
        split_idx = max(2, min(split_idx, len(fold_signals) - 2))

        is_signals = fold_signals[:split_idx]
        oos_signals = fold_signals[split_idx:]

        if not is_signals or not oos_signals:
            continue

        # Run backtest on each portion
        is_result = engine.run(is_signals, config)
        oos_result = engine.run(oos_signals, config)

        # Degradation: how much worse is OOS vs IS
        if abs(is_result.total_return_pct) > 0.01:
            degradation = (
                (is_result.total_return_pct - oos_result.total_return_pct)
                / abs(is_result.total_return_pct) * 100
            )
        else:
            degradation = 0.0

        folds.append(WalkForwardFold(
            fold_index=i,
            is_signals=is_result.total_trades,
            oos_signals=oos_result.total_trades,
            is_return_pct=round(is_result.total_return_pct, 2),
            oos_return_pct=round(oos_result.total_return_pct, 2),
            is_sharpe=is_result.sharpe_ratio,
            oos_sharpe=oos_result.sharpe_ratio,
            is_win_rate=round(is_result.win_rate, 4),
            oos_win_rate=round(oos_result.win_rate, 4),
            degradation_pct=round(degradation, 2),
        ))

    if not folds:
        return WalkForwardResult(
            n_folds=0,
            in_sample_pct=in_sample_pct,
            folds=[],
            avg_oos_return_pct=0.0,
            avg_oos_win_rate=0.0,
            avg_degradation_pct=0.0,
            stability_score=0.0,
            total_is_signals=0,
            total_oos_signals=0,
        )

    # Aggregates
    avg_oos_ret = sum(f.oos_return_pct for f in folds) / len(folds)
    avg_oos_wr = sum(f.oos_win_rate for f in folds) / len(folds)
    avg_deg = sum(f.degradation_pct for f in folds) / len(folds)

    total_is = sum(f.is_signals for f in folds)
    total_oos = sum(f.oos_signals for f in folds)

    # Stability score: based on consistency of OOS returns
    # Lower variance in OOS returns → higher stability
    oos_returns = [f.oos_return_pct for f in folds]
    mean_oos = sum(oos_returns) / len(oos_returns)
    variance_oos = sum((r - mean_oos) ** 2 for r in oos_returns) / len(oos_returns)
    std_oos = variance_oos ** 0.5

    # Also factor in degradation (low degradation = more stable)
    # Stability = 1.0 - normalized_std - normalized_degradation
    # Normalize std by mean (coefficient of variation)
    cv = std_oos / abs(mean_oos) if abs(mean_oos) > 0.01 else 1.0
    cv_penalty = min(cv, 2.0) / 2.0  # cap at 2.0, normalize to [0, 1]
    deg_penalty = min(abs(avg_deg), 200.0) / 200.0  # normalize degradation

    # How many folds were profitable OOS
    profitable_folds = sum(1 for f in folds if f.oos_return_pct > 0)
    profitability_bonus = profitable_folds / len(folds)

    stability = max(0.0, min(1.0,
        0.4 * profitability_bonus + 0.3 * (1.0 - cv_penalty) + 0.3 * (1.0 - deg_penalty)
    ))

    return WalkForwardResult(
        n_folds=len(folds),
        in_sample_pct=in_sample_pct,
        folds=folds,
        avg_oos_return_pct=round(avg_oos_ret, 2),
        avg_oos_win_rate=round(avg_oos_wr, 4),
        avg_degradation_pct=round(avg_deg, 2),
        stability_score=round(stability, 4),
        total_is_signals=total_is,
        total_oos_signals=total_oos,
    )
