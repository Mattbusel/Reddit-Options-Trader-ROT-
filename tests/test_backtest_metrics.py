"""Tests for backtest metric calculation functions."""

from __future__ import annotations

import math

import pytest

from rot.backtest.result import DrawdownPeriod, EquityPoint, TradeRecord


# ── Helpers ──


def _ep(ts: float, equity: float, trades: int = 0) -> EquityPoint:
    return EquityPoint(timestamp=ts, equity=equity, trade_count=trades)


def _make_trade(**overrides) -> TradeRecord:
    defaults = dict(
        signal_id="sig1",
        ticker="TSLA",
        stance="bullish",
        strategy="debit_spread",
        event_type="product_news",
        confidence=0.6,
        entry_time=1700000000.0,
        entry_price=250.0,
        exit_price=260.0,
        pnl_pct=4.0,
        pnl_dollars=200.0,
        is_win=True,
    )
    defaults.update(overrides)
    return TradeRecord(**defaults)


def _make_daily_equity(start_equity: float, daily_returns: list[float]) -> list[EquityPoint]:
    """Build an equity curve with one point per day (86400s apart)."""
    curve = [_ep(1700000000.0, start_equity, 0)]
    equity = start_equity
    for i, r in enumerate(daily_returns):
        equity *= 1 + r
        curve.append(_ep(1700000000.0 + (i + 1) * 86400, equity, i + 1))
    return curve


# ── Import metrics module ──

from rot.backtest.metrics import (
    _daily_returns,
    compute_annual_return,
    compute_calmar_ratio,
    compute_cvar,
    compute_drawdown_periods,
    compute_expectancy,
    compute_mae_mfe,
    compute_max_drawdown,
    compute_monthly_returns,
    compute_profit_factor,
    compute_recovery_factor,
    compute_sharpe_ratio,
    compute_sortino_ratio,
    compute_strategy_breakdown,
    compute_var,
    compute_win_rate,
)


# ── Daily Returns Helper ──


class TestDailyReturns:
    def test_empty_curve(self):
        assert _daily_returns([]) == []

    def test_single_point(self):
        assert _daily_returns([_ep(1700000000.0, 10000.0)]) == []

    def test_same_day_points_take_last(self):
        """Multiple points on same day → only last equity used."""
        curve = [
            _ep(1700000000.0, 10000.0),
            _ep(1700000010.0, 10050.0),  # same day
            _ep(1700086400.0, 10100.0),  # next day
        ]
        returns = _daily_returns(curve)
        assert len(returns) == 1
        assert abs(returns[0] - (10100 - 10050) / 10050) < 1e-8

    def test_multi_day(self):
        curve = _make_daily_equity(10000.0, [0.01, -0.02, 0.03])
        returns = _daily_returns(curve)
        assert len(returns) == 3
        assert abs(returns[0] - 0.01) < 1e-8
        assert abs(returns[1] - (-0.02)) < 1e-8
        assert abs(returns[2] - 0.03) < 1e-8


# ── Sharpe Ratio ──


class TestSharpeRatio:
    def test_insufficient_data(self):
        curve = _make_daily_equity(10000.0, [0.01, 0.02])
        assert compute_sharpe_ratio(curve) is None

    def test_zero_std_dev(self):
        """Constant returns → None (can't divide by zero)."""
        curve = _make_daily_equity(10000.0, [0.01] * 10)
        assert compute_sharpe_ratio(curve) is None

    def test_positive_returns(self):
        """All positive returns → positive Sharpe."""
        returns = [0.01, 0.02, 0.015, 0.005, 0.012, 0.018]
        curve = _make_daily_equity(10000.0, returns)
        sharpe = compute_sharpe_ratio(curve)
        assert sharpe is not None
        assert sharpe > 0

    def test_negative_returns(self):
        """All negative returns → negative Sharpe."""
        returns = [-0.01, -0.02, -0.015, -0.005, -0.012, -0.018]
        curve = _make_daily_equity(10000.0, returns)
        sharpe = compute_sharpe_ratio(curve)
        assert sharpe is not None
        assert sharpe < 0

    def test_risk_free_rate_impact(self):
        """Higher risk-free rate → lower Sharpe for same returns."""
        returns = [0.01, 0.02, 0.015, 0.005, 0.012, 0.018]
        curve = _make_daily_equity(10000.0, returns)
        sharpe_low_rf = compute_sharpe_ratio(curve, risk_free_rate=0.0)
        sharpe_high_rf = compute_sharpe_ratio(curve, risk_free_rate=0.10)
        assert sharpe_low_rf is not None
        assert sharpe_high_rf is not None
        assert sharpe_low_rf > sharpe_high_rf


# ── Sortino Ratio ──


class TestSortinoRatio:
    def test_insufficient_data(self):
        curve = _make_daily_equity(10000.0, [0.01, 0.02])
        assert compute_sortino_ratio(curve) is None

    def test_no_downside(self):
        """All positive excess returns → no downside deviation → None."""
        returns = [0.05, 0.04, 0.03, 0.06, 0.02, 0.04]
        curve = _make_daily_equity(10000.0, returns)
        assert compute_sortino_ratio(curve) is None

    def test_mixed_returns(self):
        """Mixed returns → valid Sortino."""
        returns = [0.02, -0.01, 0.03, -0.02, 0.01, -0.005]
        curve = _make_daily_equity(10000.0, returns)
        sortino = compute_sortino_ratio(curve)
        assert sortino is not None

    def test_sortino_higher_than_sharpe_for_asymmetric(self):
        """Sortino should be higher than Sharpe when upside dominates."""
        returns = [0.05, -0.01, 0.04, -0.005, 0.03, -0.01]
        curve = _make_daily_equity(10000.0, returns)
        sharpe = compute_sharpe_ratio(curve, risk_free_rate=0.0)
        sortino = compute_sortino_ratio(curve, risk_free_rate=0.0)
        assert sharpe is not None
        assert sortino is not None
        assert sortino > sharpe


# ── Calmar Ratio ──


class TestCalmarRatio:
    def test_zero_drawdown(self):
        assert compute_calmar_ratio(20.0, 0.0) is None

    def test_normal(self):
        # 20% annual return, 10% max drawdown → Calmar = 2.0
        assert compute_calmar_ratio(20.0, 10.0) == 2.0

    def test_negative_return(self):
        # -5% annual return, 15% drawdown → Calmar = -1/3
        result = compute_calmar_ratio(-5.0, 15.0)
        assert result is not None
        assert abs(result - (-5.0 / 15.0)) < 1e-8


# ── Max Drawdown ──


class TestMaxDrawdown:
    def test_empty_curve(self):
        dd_pct, dd_dur = compute_max_drawdown([])
        assert dd_pct == 0.0
        assert dd_dur == 0.0

    def test_single_point(self):
        dd_pct, dd_dur = compute_max_drawdown([_ep(100.0, 10000.0)])
        assert dd_pct == 0.0

    def test_no_drawdown(self):
        """Monotonically increasing → no drawdown."""
        curve = [_ep(i * 86400.0, 10000.0 + i * 100) for i in range(5)]
        dd_pct, dd_dur = compute_max_drawdown(curve)
        assert dd_pct == 0.0

    def test_simple_drawdown(self):
        curve = [
            _ep(0, 10000.0),
            _ep(86400, 10500.0),    # peak
            _ep(172800, 9450.0),    # trough: (10500-9450)/10500 = 10%
            _ep(259200, 10200.0),   # recovery
        ]
        dd_pct, dd_dur = compute_max_drawdown(curve)
        assert abs(dd_pct - 10.0) < 0.1
        assert dd_dur > 0

    def test_multiple_drawdowns(self):
        """Finds the largest drawdown."""
        curve = [
            _ep(0, 10000.0),
            _ep(86400, 9500.0),     # 5% dd
            _ep(172800, 10200.0),   # recovery + new peak
            _ep(259200, 8160.0),    # 20% dd from 10200
            _ep(345600, 10500.0),   # recovery
        ]
        dd_pct, _ = compute_max_drawdown(curve)
        assert abs(dd_pct - 20.0) < 0.1


# ── Drawdown Periods ──


class TestDrawdownPeriods:
    def test_empty_curve(self):
        assert compute_drawdown_periods([]) == []

    def test_no_drawdown(self):
        curve = [_ep(i * 86400.0, 10000.0 + i * 100) for i in range(5)]
        assert compute_drawdown_periods(curve) == []

    def test_single_drawdown(self):
        curve = [
            _ep(0, 10000.0),
            _ep(86400, 10500.0),    # peak
            _ep(172800, 9450.0),    # trough
            _ep(259200, 10600.0),   # recovery above peak
        ]
        periods = compute_drawdown_periods(curve)
        assert len(periods) == 1
        assert abs(periods[0].drawdown_pct - 10.0) < 0.1
        assert periods[0].peak_equity == 10500.0
        assert periods[0].trough_equity == 9450.0
        assert periods[0].end_ts == 259200.0

    def test_open_drawdown(self):
        """Drawdown not recovered at end of curve → end_ts = 0."""
        curve = [
            _ep(0, 10000.0),
            _ep(86400, 9000.0),     # 10% dd, never recovered
        ]
        periods = compute_drawdown_periods(curve)
        assert len(periods) == 1
        assert periods[0].end_ts == 0.0

    def test_tiny_drawdown_filtered(self):
        """Drawdowns < 0.1% are filtered out."""
        curve = [
            _ep(0, 10000.0),
            _ep(86400, 9999.0),     # 0.01% dd
            _ep(172800, 10001.0),
        ]
        periods = compute_drawdown_periods(curve)
        assert len(periods) == 0


# ── Profit Factor ──


class TestProfitFactor:
    def test_no_trades(self):
        assert compute_profit_factor([]) == 0.0

    def test_all_winners(self):
        trades = [_make_trade(pnl_dollars=100.0), _make_trade(pnl_dollars=200.0)]
        assert compute_profit_factor(trades) == float("inf")

    def test_all_losers(self):
        trades = [_make_trade(pnl_dollars=-100.0), _make_trade(pnl_dollars=-200.0)]
        assert compute_profit_factor(trades) == 0.0

    def test_normal(self):
        trades = [
            _make_trade(pnl_dollars=300.0),
            _make_trade(pnl_dollars=-100.0),
        ]
        assert abs(compute_profit_factor(trades) - 3.0) < 0.01


# ── Expectancy ──


class TestExpectancy:
    def test_no_trades(self):
        assert compute_expectancy([]) == 0.0

    def test_mixed(self):
        trades = [
            _make_trade(pnl_dollars=200.0),
            _make_trade(pnl_dollars=-100.0),
        ]
        assert abs(compute_expectancy(trades) - 50.0) < 0.01


# ── Win Rate ──


class TestWinRate:
    def test_no_trades(self):
        assert compute_win_rate([]) == 0.0

    def test_all_winners(self):
        trades = [_make_trade(is_win=True), _make_trade(is_win=True)]
        assert compute_win_rate(trades) == 1.0

    def test_mixed(self):
        trades = [
            _make_trade(is_win=True),
            _make_trade(is_win=True),
            _make_trade(is_win=False),
        ]
        assert abs(compute_win_rate(trades) - 2.0 / 3.0) < 1e-8


# ── Monthly Returns ──


class TestMonthlyReturns:
    def test_no_trades(self):
        assert compute_monthly_returns([]) == {}

    def test_single_month(self):
        # 1700000000 = 2023-11-14 UTC
        trades = [
            _make_trade(entry_time=1700000000.0, pnl_pct=5.0),
            _make_trade(entry_time=1700100000.0, pnl_pct=-2.0),
        ]
        result = compute_monthly_returns(trades)
        assert "2023-11" in result
        assert abs(result["2023-11"] - 3.0) < 1e-8

    def test_multiple_months(self):
        trades = [
            _make_trade(entry_time=1700000000.0, pnl_pct=5.0),   # Nov 2023
            _make_trade(entry_time=1702600000.0, pnl_pct=-3.0),  # Dec 2023
        ]
        result = compute_monthly_returns(trades)
        assert len(result) == 2
        keys = list(result.keys())
        assert keys == sorted(keys)  # should be sorted


# ── Strategy Breakdown ──


class TestStrategyBreakdown:
    def test_no_trades(self):
        assert compute_strategy_breakdown([]) == {}

    def test_single_strategy(self):
        trades = [
            _make_trade(strategy="debit_spread", is_win=True, pnl_pct=5.0),
            _make_trade(strategy="debit_spread", is_win=False, pnl_pct=-3.0),
        ]
        result = compute_strategy_breakdown(trades)
        assert "debit_spread" in result
        bd = result["debit_spread"]
        assert bd["trade_count"] == 2.0
        assert bd["win_rate"] == 0.5
        assert abs(bd["avg_pnl_pct"] - 1.0) < 0.01
        assert abs(bd["total_pnl_pct"] - 2.0) < 0.01

    def test_multiple_strategies(self):
        trades = [
            _make_trade(strategy="debit_spread"),
            _make_trade(strategy="credit_spread"),
            _make_trade(strategy="iron_condor"),
        ]
        result = compute_strategy_breakdown(trades)
        assert len(result) == 3


# ── VaR ──


class TestVaR:
    def test_empty_curve(self):
        assert compute_var([]) == 0.0

    def test_positive_var(self):
        """VaR should be positive (representing loss magnitude)."""
        returns = [0.02, -0.03, 0.01, -0.04, 0.015, -0.01, 0.005, -0.02]
        curve = _make_daily_equity(10000.0, returns)
        var = compute_var(curve, confidence=0.95)
        assert var > 0

    def test_higher_confidence_higher_var(self):
        """Higher confidence → VaR captures more extreme tail → larger."""
        returns = [0.02, -0.03, 0.01, -0.04, 0.015, -0.01, 0.005, -0.02,
                   0.01, -0.05, 0.02, -0.015]
        curve = _make_daily_equity(10000.0, returns)
        var_90 = compute_var(curve, confidence=0.90)
        var_99 = compute_var(curve, confidence=0.99)
        assert var_99 >= var_90


# ── CVaR ──


class TestCVaR:
    def test_empty_curve(self):
        assert compute_cvar([]) == 0.0

    def test_cvar_ge_var(self):
        """CVaR (expected shortfall) should be >= VaR."""
        returns = [0.02, -0.03, 0.01, -0.04, 0.015, -0.01, 0.005, -0.02,
                   0.01, -0.05, 0.02, -0.015]
        curve = _make_daily_equity(10000.0, returns)
        var = compute_var(curve, confidence=0.95)
        cvar = compute_cvar(curve, confidence=0.95)
        assert cvar >= var


# ── MAE / MFE ──


class TestMAEMFE:
    def test_no_trades(self):
        result = compute_mae_mfe([])
        assert result == {"mae_avg": 0.0, "mae_max": 0.0, "mfe_avg": 0.0, "mfe_max": 0.0}

    def test_all_winners(self):
        trades = [
            _make_trade(pnl_pct=5.0),
            _make_trade(pnl_pct=10.0),
        ]
        result = compute_mae_mfe(trades)
        assert result["mae_avg"] == 0.0
        assert result["mae_max"] == 0.0
        assert result["mfe_avg"] == 7.5
        assert result["mfe_max"] == 10.0

    def test_all_losers(self):
        trades = [
            _make_trade(pnl_pct=-3.0),
            _make_trade(pnl_pct=-7.0),
        ]
        result = compute_mae_mfe(trades)
        assert result["mae_avg"] == 5.0
        assert result["mae_max"] == 7.0
        assert result["mfe_avg"] == 0.0
        assert result["mfe_max"] == 0.0

    def test_mixed(self):
        trades = [
            _make_trade(pnl_pct=10.0),
            _make_trade(pnl_pct=-4.0),
        ]
        result = compute_mae_mfe(trades)
        assert result["mae_avg"] == 4.0
        assert result["mfe_avg"] == 10.0


# ── Annual Return ──


class TestAnnualReturn:
    def test_zero_days(self):
        assert compute_annual_return(10.0, 0) == 0.0

    def test_very_short_period(self):
        """Very short period returns raw total (no annualization)."""
        assert compute_annual_return(5.0, 1) == 5.0

    def test_one_year(self):
        """Full year → annual return ≈ total return."""
        result = compute_annual_return(10.0, 365)
        assert abs(result - 10.0) < 0.1

    def test_half_year(self):
        """Half year of 5% → annualized > 5%."""
        result = compute_annual_return(5.0, 183)
        assert result > 5.0

    def test_negative_total_loss(self):
        """Total loss > 100% → capped at -100."""
        result = compute_annual_return(-110.0, 365)
        assert result == -100.0


# ── Recovery Factor ──


class TestRecoveryFactor:
    def test_zero_drawdown(self):
        assert compute_recovery_factor(20.0, 0.0) == 0.0

    def test_normal(self):
        assert compute_recovery_factor(30.0, 10.0) == 3.0

    def test_negative_return(self):
        result = compute_recovery_factor(-10.0, 20.0)
        assert result == -0.5
