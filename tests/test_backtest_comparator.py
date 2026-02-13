"""Tests for strategy comparator module."""

from __future__ import annotations

import pytest

from rot.backtest.comparator import ComparisonResult, StrategyStats, compare_strategies
from rot.backtest.result import BacktestResult, EquityPoint


# ── Helpers ──


def _ep(ts: float, equity: float, trades: int = 0) -> EquityPoint:
    return EquityPoint(timestamp=ts, equity=equity, trade_count=trades)


def _make_result(
    total_return_pct: float = 10.0,
    sharpe: float | None = 1.5,
    max_dd: float = 5.0,
    win_rate: float = 0.6,
    equity_series: list[float] | None = None,
    **overrides,
) -> BacktestResult:
    if equity_series:
        ec = [_ep(i * 86400, eq) for i, eq in enumerate(equity_series)]
    else:
        ec = [_ep(0, 10000.0), _ep(86400 * 30, 10000.0 * (1 + total_return_pct / 100))]

    defaults = dict(
        total_trades=20,
        winning_trades=int(20 * win_rate),
        losing_trades=20 - int(20 * win_rate),
        win_rate=win_rate,
        total_return_pct=total_return_pct,
        annual_return_pct=total_return_pct * 4,
        final_equity=ec[-1].equity,
        sharpe_ratio=sharpe,
        sortino_ratio=sharpe * 1.2 if sharpe else None,
        max_drawdown_pct=max_dd,
        profit_factor=1.5,
        equity_curve=ec,
    )
    defaults.update(overrides)
    return BacktestResult(**defaults)


# ── Tests ──


class TestCompareEmpty:
    def test_no_results(self):
        result = compare_strategies([], [])
        assert result.n_strategies == 0
        assert result.correlation_matrix == {}
        assert result.rank_by_return == []

    def test_empty_names(self):
        result = compare_strategies([], [])
        assert result.strategies == []


class TestCompareSingle:
    def test_single_strategy(self):
        r = _make_result(total_return_pct=15.0, sharpe=2.0)
        result = compare_strategies([r], ["Alpha"])
        assert result.n_strategies == 1
        assert len(result.strategies) == 1
        assert result.strategies[0].name == "Alpha"
        assert result.strategies[0].total_return_pct == 15.0

    def test_single_rankings(self):
        r = _make_result()
        result = compare_strategies([r], ["Alpha"])
        assert result.rank_by_return == ["Alpha"]
        assert result.rank_by_sharpe == ["Alpha"]


class TestCompareMultiple:
    def test_two_strategies(self):
        r1 = _make_result(total_return_pct=20.0, sharpe=2.0, max_dd=5.0, win_rate=0.7)
        r2 = _make_result(total_return_pct=10.0, sharpe=1.0, max_dd=10.0, win_rate=0.5)
        result = compare_strategies([r1, r2], ["Alpha", "Beta"])

        assert result.n_strategies == 2
        assert result.rank_by_return[0] == "Alpha"
        assert result.rank_by_sharpe[0] == "Alpha"
        assert result.rank_by_drawdown[0] == "Alpha"  # lower drawdown = better
        assert result.rank_by_win_rate[0] == "Alpha"

    def test_three_strategies(self):
        r1 = _make_result(total_return_pct=20.0, sharpe=2.0)
        r2 = _make_result(total_return_pct=30.0, sharpe=1.5)
        r3 = _make_result(total_return_pct=10.0, sharpe=3.0)
        result = compare_strategies([r1, r2, r3], ["A", "B", "C"])

        assert result.n_strategies == 3
        assert result.rank_by_return == ["B", "A", "C"]
        assert result.rank_by_sharpe == ["C", "A", "B"]


class TestCorrelationMatrix:
    def test_self_correlation(self):
        r1 = _make_result()
        result = compare_strategies([r1], ["A"])
        assert result.correlation_matrix[("A", "A")] == 1.0

    def test_symmetric(self):
        r1 = _make_result(equity_series=[10000, 10100, 10050, 10200, 10150])
        r2 = _make_result(equity_series=[10000, 9900, 10000, 9850, 10050])
        result = compare_strategies([r1, r2], ["A", "B"])
        assert result.correlation_matrix[("A", "B")] == result.correlation_matrix[("B", "A")]

    def test_two_strategies_have_correlation(self):
        r1 = _make_result(equity_series=[10000, 10100, 10200, 10300, 10400])
        r2 = _make_result(equity_series=[10000, 10050, 10100, 10150, 10200])
        result = compare_strategies([r1, r2], ["A", "B"])
        corr = result.correlation_matrix[("A", "B")]
        assert -1.0 <= corr <= 1.0


class TestSummaryTable:
    def test_has_all_metrics(self):
        r = _make_result()
        result = compare_strategies([r], ["Alpha"])
        expected_metrics = [
            "total_return_pct", "annual_return_pct", "sharpe_ratio",
            "max_drawdown_pct", "win_rate", "profit_factor", "total_trades",
        ]
        for metric in expected_metrics:
            assert metric in result.summary_table

    def test_summary_values(self):
        r = _make_result(total_return_pct=15.0, win_rate=0.7)
        result = compare_strategies([r], ["Alpha"])
        assert result.summary_table["total_return_pct"]["Alpha"] == 15.0
        assert result.summary_table["win_rate"]["Alpha"] == 0.7

    def test_none_sharpe_becomes_zero(self):
        r = _make_result(sharpe=None)
        result = compare_strategies([r], ["Alpha"])
        assert result.summary_table["sharpe_ratio"]["Alpha"] == 0.0


class TestStrategyStats:
    def test_stats_fields(self):
        r = _make_result(
            total_return_pct=25.0,
            sharpe=2.5,
            max_dd=8.0,
            win_rate=0.65,
        )
        result = compare_strategies([r], ["Alpha"])
        s = result.strategies[0]
        assert s.name == "Alpha"
        assert s.total_return_pct == 25.0
        assert s.sharpe_ratio == 2.5
        assert s.max_drawdown_pct == 8.0
        assert s.win_rate == 0.65
