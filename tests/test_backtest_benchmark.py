"""Tests for benchmark comparison module."""

from __future__ import annotations

import pytest

from rot.backtest.benchmark import (
    BenchmarkComparison,
    _build_benchmark_curve,
    _compute_beta,
    _compute_correlation,
    compare_to_benchmark,
)
from rot.backtest.result import BacktestResult, EquityPoint


# ── Helpers ──


def _ep(ts: float, equity: float, trades: int = 0) -> EquityPoint:
    return EquityPoint(timestamp=ts, equity=equity, trade_count=trades)


def _make_result(
    equity_curve: list[EquityPoint] | None = None,
    total_return_pct: float = 10.0,
    annual_return_pct: float = 40.0,
    **overrides,
) -> BacktestResult:
    ec = equity_curve or [_ep(0, 10000.0), _ep(86400 * 30, 11000.0)]
    defaults = dict(
        total_trades=10,
        winning_trades=7,
        losing_trades=3,
        win_rate=0.7,
        total_return_pct=total_return_pct,
        annual_return_pct=annual_return_pct,
        final_equity=11000.0,
        equity_curve=ec,
        config_dict={"starting_capital": 10000.0},
    )
    defaults.update(overrides)
    return BacktestResult(**defaults)


def _make_bench_prices(n_days: int, start_price: float = 400.0, daily_return: float = 0.001) -> list[tuple[float, float]]:
    """Generate benchmark prices over n_days."""
    prices = []
    price = start_price
    for i in range(n_days):
        ts = 1700000000.0 + i * 86400
        prices.append((ts, price))
        price *= (1 + daily_return)
    return prices


# ── Build Benchmark Curve ──


class TestBuildBenchmarkCurve:
    def test_empty(self):
        assert _build_benchmark_curve([], 10000.0) == []

    def test_single_price(self):
        curve = _build_benchmark_curve([(100.0, 400.0)], 10000.0)
        assert len(curve) == 1
        assert curve[0].equity == 10000.0

    def test_price_doubles(self):
        prices = [(0, 400.0), (86400, 800.0)]
        curve = _build_benchmark_curve(prices, 10000.0)
        assert len(curve) == 2
        assert curve[0].equity == 10000.0
        assert curve[1].equity == 20000.0

    def test_zero_base_price(self):
        assert _build_benchmark_curve([(0, 0.0)], 10000.0) == []


# ── Correlation ──


class TestCorrelation:
    def test_perfect_positive(self):
        xs = [1.0, 2.0, 3.0, 4.0]
        ys = [2.0, 4.0, 6.0, 8.0]
        assert abs(_compute_correlation(xs, ys) - 1.0) < 0.01

    def test_perfect_negative(self):
        xs = [1.0, 2.0, 3.0, 4.0]
        ys = [8.0, 6.0, 4.0, 2.0]
        assert abs(_compute_correlation(xs, ys) - (-1.0)) < 0.01

    def test_zero_correlation(self):
        xs = [1.0, -1.0, 1.0, -1.0]
        ys = [1.0, 1.0, -1.0, -1.0]
        assert abs(_compute_correlation(xs, ys)) < 0.1

    def test_insufficient_data(self):
        assert _compute_correlation([1.0], [2.0]) == 0.0


# ── Beta ──


class TestBeta:
    def test_identical_returns(self):
        """Same returns → beta ≈ 1."""
        r = [0.01, -0.02, 0.03, -0.01, 0.02]
        beta = _compute_beta(r, r)
        assert abs(beta - 1.0) < 0.01

    def test_double_returns(self):
        """Strategy with 2x benchmark volatility → beta ≈ 2."""
        bench = [0.01, -0.02, 0.03, -0.01, 0.02]
        strat = [0.02, -0.04, 0.06, -0.02, 0.04]
        beta = _compute_beta(strat, bench)
        assert abs(beta - 2.0) < 0.01

    def test_insufficient_data(self):
        assert _compute_beta([0.01], [0.02]) == 1.0


# ── Compare to Benchmark ──


class TestCompareToBenchmark:
    def test_basic_comparison(self):
        # Strategy equity: 10000 → 11000 over 30 days
        ec = [_ep(1700000000.0 + i * 86400, 10000.0 + i * 33.33) for i in range(31)]
        result = _make_result(equity_curve=ec)
        bench_prices = _make_bench_prices(31, daily_return=0.0005)

        comp = compare_to_benchmark(result, bench_prices)
        assert isinstance(comp, BenchmarkComparison)
        assert comp.benchmark_ticker == "SPY"
        assert comp.strategy_return_pct == 10.0
        assert comp.benchmark_return_pct > 0
        assert isinstance(comp.alpha, float)
        assert isinstance(comp.beta, float)
        assert isinstance(comp.correlation, float)

    def test_outperformance(self):
        """Strategy returns more than benchmark → positive outperformance."""
        ec = [_ep(0, 10000.0), _ep(86400 * 30, 12000.0)]
        result = _make_result(equity_curve=ec, total_return_pct=20.0)
        bench_prices = [(0, 400.0), (86400 * 30, 404.0)]  # 1% return

        comp = compare_to_benchmark(result, bench_prices)
        assert comp.outperformance_pct > 0

    def test_underperformance(self):
        """Strategy returns less than benchmark → negative outperformance."""
        ec = [_ep(0, 10000.0), _ep(86400 * 30, 10100.0)]
        result = _make_result(equity_curve=ec, total_return_pct=1.0)
        bench_prices = [(0, 400.0), (86400 * 30, 440.0)]  # 10% return

        comp = compare_to_benchmark(result, bench_prices)
        assert comp.outperformance_pct < 0

    def test_empty_benchmark(self):
        result = _make_result()
        comp = compare_to_benchmark(result, [])
        assert comp.benchmark_return_pct == 0.0
        assert comp.beta == 1.0  # default

    def test_custom_ticker(self):
        result = _make_result()
        comp = compare_to_benchmark(result, [], benchmark_ticker="QQQ")
        assert comp.benchmark_ticker == "QQQ"
