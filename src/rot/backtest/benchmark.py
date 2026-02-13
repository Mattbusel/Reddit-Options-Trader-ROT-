"""Benchmark comparison for backtest results.

Compares strategy performance against a buy-and-hold benchmark
(typically SPY) to compute alpha, beta, and information ratio.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from rot.backtest.metrics import _daily_returns
from rot.backtest.result import BacktestResult, EquityPoint


@dataclass(frozen=True)
class BenchmarkComparison:
    """Result of comparing a strategy to a benchmark."""

    # Benchmark stats
    benchmark_ticker: str
    benchmark_return_pct: float
    benchmark_sharpe: Optional[float]
    benchmark_max_drawdown_pct: float

    # Relative metrics
    alpha: float             # strategy excess return over benchmark (annualized)
    beta: float              # strategy sensitivity to benchmark moves
    information_ratio: float  # risk-adjusted excess return

    # Correlation
    correlation: float       # correlation of daily returns

    # Comparison
    strategy_return_pct: float
    outperformance_pct: float  # strategy return - benchmark return


def _build_benchmark_curve(
    prices: List[Tuple[float, float]],
    starting_capital: float,
) -> List[EquityPoint]:
    """Build equity curve from benchmark prices.

    Parameters
    ----------
    prices:
        List of (timestamp, price) tuples sorted chronologically.
    starting_capital:
        Starting capital to normalize the equity curve.

    Returns
    -------
    List of EquityPoints representing buy-and-hold equity.
    """
    if not prices:
        return []

    base_price = prices[0][1]
    if base_price <= 0:
        return []

    curve = []
    for ts, price in prices:
        equity = starting_capital * (price / base_price)
        curve.append(EquityPoint(timestamp=ts, equity=equity, trade_count=0))
    return curve


def _compute_correlation(xs: List[float], ys: List[float]) -> float:
    """Pearson correlation between two lists."""
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0

    xs, ys = xs[:n], ys[:n]
    mx = sum(xs) / n
    my = sum(ys) / n

    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n)

    if sx < 1e-10 or sy < 1e-10:
        return 0.0
    return cov / (sx * sy)


def _compute_beta(
    strategy_returns: List[float],
    benchmark_returns: List[float],
) -> float:
    """Compute beta = cov(strat, bench) / var(bench)."""
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 3:
        return 1.0

    sr = strategy_returns[:n]
    br = benchmark_returns[:n]
    mb = sum(br) / n
    ms = sum(sr) / n

    cov = sum((s - ms) * (b - mb) for s, b in zip(sr, br)) / n
    var_b = sum((b - mb) ** 2 for b in br) / n

    if var_b < 1e-12:
        return 1.0
    return cov / var_b


def compare_to_benchmark(
    result: BacktestResult,
    benchmark_prices: List[Tuple[float, float]],
    benchmark_ticker: str = "SPY",
    risk_free_rate: float = 0.02,
) -> BenchmarkComparison:
    """Compare a backtest result to a benchmark.

    Parameters
    ----------
    result:
        BacktestResult from engine.run().
    benchmark_prices:
        List of (timestamp, price) tuples for the benchmark.
    benchmark_ticker:
        Name of benchmark (default: SPY).
    risk_free_rate:
        Annual risk-free rate for Sharpe calculation.

    Returns
    -------
    BenchmarkComparison with alpha, beta, info ratio, correlation.
    """
    starting_capital = result.config_dict.get("starting_capital", 10000.0)

    # Build benchmark equity curve
    bench_curve = _build_benchmark_curve(benchmark_prices, starting_capital)

    # Benchmark metrics
    if bench_curve and len(bench_curve) >= 2:
        bench_return = (bench_curve[-1].equity - bench_curve[0].equity) / bench_curve[0].equity * 100
        bench_returns = _daily_returns(bench_curve)

        # Benchmark Sharpe
        if len(bench_returns) >= 5:
            daily_rf = risk_free_rate / 252
            excess = [r - daily_rf for r in bench_returns]
            mean_e = sum(excess) / len(excess)
            var_e = sum((r - mean_e) ** 2 for r in excess) / len(excess)
            std_e = math.sqrt(var_e)
            bench_sharpe = (mean_e / std_e) * math.sqrt(252) if std_e > 1e-10 else None
        else:
            bench_sharpe = None

        # Benchmark max drawdown
        peak = bench_curve[0].equity
        max_dd = 0.0
        for ep in bench_curve:
            if ep.equity > peak:
                peak = ep.equity
            elif peak > 0:
                dd = (peak - ep.equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd
    else:
        bench_return = 0.0
        bench_returns = []
        bench_sharpe = None
        max_dd = 0.0

    # Strategy daily returns
    strat_returns = _daily_returns(result.equity_curve)

    # Correlation, beta, alpha
    corr = _compute_correlation(strat_returns, bench_returns)
    beta = _compute_beta(strat_returns, bench_returns)

    # Alpha: annualized excess return beyond what beta would predict
    # α = R_strategy - (R_f + β * (R_benchmark - R_f))
    strat_annual = result.annual_return_pct
    bench_annual = bench_return  # simplified
    alpha = strat_annual - (risk_free_rate * 100 + beta * (bench_annual - risk_free_rate * 100))

    # Information ratio: excess return / tracking error
    n = min(len(strat_returns), len(bench_returns))
    if n >= 3:
        tracking = [strat_returns[i] - bench_returns[i] for i in range(n)]
        mean_track = sum(tracking) / len(tracking)
        var_track = sum((t - mean_track) ** 2 for t in tracking) / len(tracking)
        te = math.sqrt(var_track)
        info_ratio = (mean_track / te) * math.sqrt(252) if te > 1e-10 else 0.0
    else:
        info_ratio = 0.0

    outperformance = result.total_return_pct - bench_return

    return BenchmarkComparison(
        benchmark_ticker=benchmark_ticker,
        benchmark_return_pct=round(bench_return, 2),
        benchmark_sharpe=round(bench_sharpe, 4) if bench_sharpe is not None else None,
        benchmark_max_drawdown_pct=round(max_dd, 2),
        alpha=round(alpha, 2),
        beta=round(beta, 4),
        information_ratio=round(info_ratio, 4),
        correlation=round(corr, 4),
        strategy_return_pct=round(result.total_return_pct, 2),
        outperformance_pct=round(outperformance, 2),
    )
