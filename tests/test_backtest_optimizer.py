"""Tests for parameter grid search optimizer."""

from __future__ import annotations

import pytest

from rot.backtest.config import BacktestConfig
from rot.backtest.optimizer import (
    OptimizationPoint,
    OptimizationResult,
    _apply_params_to_config,
    _generate_combos,
    optimize,
)


# ── Helpers ──


def _make_signal(idx: int, is_win: bool = True) -> dict:
    entry = 100.0
    exit_1d = 105.0 if is_win else 95.0
    return dict(
        signal_id=f"sig-{idx:03d}",
        ticker="TSLA",
        stance="bullish",
        strategy="debit_spread",
        event_type="product_news",
        confidence=0.65,
        created_at=1700000000.0 + idx * 86400,
        price_at_signal=entry,
        price_1d=exit_1d,
        price_4h=exit_1d - 0.5,
        price_1h=entry + 0.3,
        max_gain_pct=None,
        max_loss_pct=None,
    )


def _make_signals(n: int) -> list[dict]:
    signals = []
    for i in range(n):
        is_win = (i % 3) != 0
        signals.append(_make_signal(i, is_win))
    return signals


# ── Combo Generation ──


class TestGenerateCombos:
    def test_simple_grid(self):
        grid = {"a": [1.0, 2.0], "b": [3.0, 4.0]}
        combos = _generate_combos(grid, max_combos=100)
        assert len(combos) == 4
        assert {"a": 1.0, "b": 3.0} in combos
        assert {"a": 2.0, "b": 4.0} in combos

    def test_cap_enforced(self):
        grid = {"a": list(range(10)), "b": list(range(10)), "c": list(range(10))}
        combos = _generate_combos(grid, max_combos=50)
        assert len(combos) == 50

    def test_single_param(self):
        grid = {"a": [1.0, 2.0, 3.0]}
        combos = _generate_combos(grid, max_combos=100)
        assert len(combos) == 3

    def test_empty_grid(self):
        combos = _generate_combos({}, max_combos=100)
        assert len(combos) == 1  # single empty combo


# ── Config Application ──


class TestApplyParams:
    def test_applies_float_param(self):
        base = BacktestConfig()
        config = _apply_params_to_config(base, {"position_size_pct": 10.0})
        assert config.position_size_pct == 10.0

    def test_applies_int_param(self):
        base = BacktestConfig()
        config = _apply_params_to_config(base, {"max_concurrent_positions": 3.0})
        assert config.max_concurrent_positions == 3

    def test_ignores_unknown_param(self):
        base = BacktestConfig()
        config = _apply_params_to_config(base, {"nonexistent": 42.0})
        assert config == base

    def test_multiple_params(self):
        base = BacktestConfig()
        config = _apply_params_to_config(base, {
            "position_size_pct": 15.0,
            "stop_loss_pct": 8.0,
            "min_confidence": 0.5,
        })
        assert config.position_size_pct == 15.0
        assert config.stop_loss_pct == 8.0
        assert config.min_confidence == 0.5


# ── Optimizer Integration ──


class TestOptimize:
    def test_empty_signals(self):
        result = optimize([], BacktestConfig())
        assert result.total_combos_tested > 0
        # All combos will produce 0 trades

    def test_with_signals(self):
        signals = _make_signals(30)
        result = optimize(
            signals,
            BacktestConfig(),
            param_grid={"position_size_pct": [5.0, 10.0]},
            max_combos=10,
        )
        assert result.total_combos_tested == 2
        assert len(result.points) == 2
        assert result.best_params is not None

    def test_default_grid(self):
        signals = _make_signals(30)
        result = optimize(signals, BacktestConfig(), max_combos=20)
        assert result.total_combos_tested > 0
        assert result.max_combos_cap == 20

    def test_rankings_sorted_by_sharpe(self):
        signals = _make_signals(30)
        result = optimize(
            signals,
            BacktestConfig(),
            param_grid={"position_size_pct": [2.0, 5.0, 10.0, 15.0]},
            max_combos=10,
        )
        if len(result.rankings) >= 2:
            for i in range(len(result.rankings) - 1):
                s1 = result.rankings[i].sharpe_ratio or -999
                s2 = result.rankings[i + 1].sharpe_ratio or -999
                assert s1 >= s2

    def test_rankings_capped_at_20(self):
        signals = _make_signals(30)
        result = optimize(
            signals,
            BacktestConfig(),
            param_grid={
                "position_size_pct": [2.0, 5.0, 10.0, 15.0, 20.0, 25.0],
                "stop_loss_pct": [0.0, 5.0, 10.0, 15.0, 20.0],
            },
            max_combos=100,
        )
        assert len(result.rankings) <= 20


class TestOptimizerHeatmap:
    def test_heatmap_generated(self):
        signals = _make_signals(30)
        result = optimize(
            signals,
            BacktestConfig(),
            param_grid={
                "position_size_pct": [5.0, 10.0],
                "stop_loss_pct": [0.0, 10.0],
            },
            max_combos=100,
        )
        assert result.heatmap_x_param == "position_size_pct"
        assert result.heatmap_y_param == "stop_loss_pct"
        assert len(result.heatmap_x_values) == 2
        assert len(result.heatmap_y_values) == 2
        assert len(result.heatmap_data) == 2  # 2 y values
        assert len(result.heatmap_data[0]) == 2  # 2 x values

    def test_single_param_heatmap(self):
        signals = _make_signals(30)
        result = optimize(
            signals,
            BacktestConfig(),
            param_grid={"position_size_pct": [5.0, 10.0, 15.0]},
            max_combos=10,
        )
        # With single param, x and y are both the same param
        assert result.heatmap_x_param == "position_size_pct"


class TestOptimizerOptimizationPoint:
    def test_point_has_all_fields(self):
        signals = _make_signals(30)
        result = optimize(
            signals,
            BacktestConfig(),
            param_grid={"position_size_pct": [5.0]},
            max_combos=10,
        )
        assert len(result.points) == 1
        point = result.points[0]
        assert "position_size_pct" in point.params
        assert isinstance(point.total_return_pct, float)
        assert isinstance(point.max_drawdown_pct, float)
        assert isinstance(point.win_rate, float)
        assert isinstance(point.total_trades, int)
        assert isinstance(point.profit_factor, float)
