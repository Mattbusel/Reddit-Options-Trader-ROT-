"""Parameter grid search optimizer for backtesting.

Evaluates combinations of position size, stop loss, take profit,
and min confidence to find optimal parameters by Sharpe ratio.
"""

from __future__ import annotations

import dataclasses
import itertools
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from rot.backtest.config import BacktestConfig
from rot.backtest.engine import BacktestEngine
from rot.backtest.result import BacktestResult


@dataclass(frozen=True)
class OptimizationPoint:
    """Result of one parameter combination."""

    params: Dict[str, float]   # param_name → value
    total_return_pct: float
    sharpe_ratio: Optional[float]
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    profit_factor: float


@dataclass(frozen=True)
class OptimizationResult:
    """Complete optimization results."""

    points: List[OptimizationPoint]
    best_params: Dict[str, float]
    best_sharpe: Optional[float]
    best_return_pct: float

    # Param grid info
    param_grid: Dict[str, List[float]]
    total_combos_tested: int
    max_combos_cap: int

    # Heatmap data for 2D visualization (param1 x param2 → Sharpe)
    heatmap_x_param: str
    heatmap_y_param: str
    heatmap_x_values: List[float]
    heatmap_y_values: List[float]
    heatmap_data: List[List[Optional[float]]]  # [y_idx][x_idx] = Sharpe

    # Rankings (top N by Sharpe)
    rankings: List[OptimizationPoint]


def _generate_combos(
    param_grid: Dict[str, List[float]],
    max_combos: int,
) -> List[Dict[str, float]]:
    """Generate parameter combinations, capping at max_combos."""
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]

    all_combos = list(itertools.product(*values))
    if len(all_combos) > max_combos:
        # Evenly sample to stay under cap
        step = len(all_combos) / max_combos
        indices = [int(i * step) for i in range(max_combos)]
        all_combos = [all_combos[i] for i in indices]

    return [dict(zip(keys, combo)) for combo in all_combos]


def _apply_params_to_config(
    base_config: BacktestConfig,
    params: Dict[str, float],
) -> BacktestConfig:
    """Create a new config with overridden params."""
    overrides = {}
    for key, value in params.items():
        if hasattr(base_config, key):
            # Cast to appropriate type
            field_val = getattr(base_config, key)
            if isinstance(field_val, int):
                overrides[key] = int(value)
            else:
                overrides[key] = float(value)

    return dataclasses.replace(base_config, **overrides)


def optimize(
    signals: List[Dict[str, Any]],
    base_config: BacktestConfig,
    param_grid: Optional[Dict[str, List[float]]] = None,
    max_combos: int = 500,
) -> OptimizationResult:
    """Run grid search optimization.

    Parameters
    ----------
    signals:
        Signal dicts from database.
    base_config:
        Base configuration (non-optimized params stay fixed).
    param_grid:
        Dict of param_name → list of values to try.
        Defaults to standard grid (position_size_pct, stop_loss_pct, min_confidence).
    max_combos:
        Maximum number of parameter combinations to test.

    Returns
    -------
    OptimizationResult with rankings and heatmap data.
    """
    if param_grid is None:
        param_grid = {
            "position_size_pct": [2.0, 5.0, 10.0, 15.0, 20.0],
            "stop_loss_pct": [0.0, 5.0, 10.0, 15.0, 20.0],
            "min_confidence": [0.0, 0.3, 0.5, 0.7],
        }

    combos = _generate_combos(param_grid, max_combos)
    engine = BacktestEngine()
    points: List[OptimizationPoint] = []

    for params in combos:
        try:
            config = _apply_params_to_config(base_config, params)
            result = engine.run(signals, config)
            points.append(OptimizationPoint(
                params=params,
                total_return_pct=result.total_return_pct,
                sharpe_ratio=result.sharpe_ratio,
                max_drawdown_pct=result.max_drawdown_pct,
                win_rate=result.win_rate,
                total_trades=result.total_trades,
                profit_factor=result.profit_factor,
            ))
        except Exception:
            continue

    if not points:
        return OptimizationResult(
            points=[],
            best_params={},
            best_sharpe=None,
            best_return_pct=0.0,
            param_grid=param_grid,
            total_combos_tested=0,
            max_combos_cap=max_combos,
            heatmap_x_param="",
            heatmap_y_param="",
            heatmap_x_values=[],
            heatmap_y_values=[],
            heatmap_data=[],
            rankings=[],
        )

    # Sort by Sharpe (None = -inf for sorting)
    def _sharpe_key(p: OptimizationPoint) -> float:
        return p.sharpe_ratio if p.sharpe_ratio is not None else -999.0

    sorted_points = sorted(points, key=_sharpe_key, reverse=True)
    best = sorted_points[0]
    rankings = sorted_points[:20]  # top 20

    # Build heatmap from first two params
    grid_keys = list(param_grid.keys())
    if len(grid_keys) >= 2:
        hx = grid_keys[0]
        hy = grid_keys[1]
    elif len(grid_keys) == 1:
        hx = grid_keys[0]
        hy = grid_keys[0]
    else:
        hx, hy = "", ""

    hx_vals = sorted(set(param_grid.get(hx, [])))
    hy_vals = sorted(set(param_grid.get(hy, [])))

    # Build Sharpe heatmap matrix
    heatmap: List[List[Optional[float]]] = []
    for y_val in hy_vals:
        row: List[Optional[float]] = []
        for x_val in hx_vals:
            # Find the point matching these coords (average if multiple)
            matching = [
                p.sharpe_ratio
                for p in points
                if abs(p.params.get(hx, -999) - x_val) < 0.001
                and abs(p.params.get(hy, -999) - y_val) < 0.001
                and p.sharpe_ratio is not None
            ]
            if matching:
                row.append(round(sum(matching) / len(matching), 4))
            else:
                row.append(None)
        heatmap.append(row)

    return OptimizationResult(
        points=points,
        best_params=best.params,
        best_sharpe=best.sharpe_ratio,
        best_return_pct=best.total_return_pct,
        param_grid=param_grid,
        total_combos_tested=len(points),
        max_combos_cap=max_combos,
        heatmap_x_param=hx,
        heatmap_y_param=hy,
        heatmap_x_values=hx_vals,
        heatmap_y_values=hy_vals,
        heatmap_data=heatmap,
        rankings=rankings,
    )
