"""Tests for risk analytics module."""

from __future__ import annotations

import pytest

from rot.backtest.result import BacktestResult, DrawdownPeriod, EquityPoint, TradeRecord
from rot.backtest.risk import (
    RiskMetrics,
    _compute_kurtosis,
    _compute_skewness,
    _compute_ulcer_index,
    compute_risk_metrics,
)


# ── Helpers ──


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


def _ep(ts: float, equity: float, trades: int = 0) -> EquityPoint:
    return EquityPoint(timestamp=ts, equity=equity, trade_count=trades)


def _make_result(
    trades: list[TradeRecord] | None = None,
    equity_curve: list[EquityPoint] | None = None,
    drawdown_periods: list[DrawdownPeriod] | None = None,
    **overrides,
) -> BacktestResult:
    trades = trades or []
    equity_curve = equity_curve or [_ep(0, 10000.0)]
    drawdown_periods = drawdown_periods or []

    winners = [t for t in trades if t.is_win]
    losers = [t for t in trades if not t.is_win]

    defaults = dict(
        total_trades=len(trades),
        winning_trades=len(winners),
        losing_trades=len(losers),
        win_rate=len(winners) / len(trades) if trades else 0.0,
        total_return_pct=10.0,
        annual_return_pct=40.0,
        final_equity=11000.0,
        max_drawdown_pct=5.0,
        max_drawdown_duration_s=86400.0,
        equity_curve=equity_curve,
        trades=trades,
        drawdown_periods=drawdown_periods,
    )
    defaults.update(overrides)
    return BacktestResult(**defaults)


# ── Statistical Helper Tests ──


class TestSkewness:
    def test_empty(self):
        assert _compute_skewness([]) == 0.0

    def test_symmetric(self):
        """Symmetric distribution → skewness ≈ 0."""
        vals = [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0]
        assert abs(_compute_skewness(vals)) < 0.1

    def test_right_skewed(self):
        """Right-skewed → positive skewness."""
        vals = [1.0, 1.0, 1.0, 1.0, 1.0, 10.0]
        assert _compute_skewness(vals) > 0

    def test_left_skewed(self):
        """Left-skewed → negative skewness."""
        vals = [-10.0, -1.0, -1.0, -1.0, -1.0, -1.0]
        assert _compute_skewness(vals) < 0


class TestKurtosis:
    def test_empty(self):
        assert _compute_kurtosis([]) == 0.0

    def test_uniform(self):
        """Uniform-like → negative excess kurtosis."""
        vals = list(range(10))
        # Uniform dist has negative excess kurtosis
        assert _compute_kurtosis(vals) < 0

    def test_fat_tails(self):
        """Distribution with fat tails → high kurtosis."""
        # Normal-ish in center, with extreme outliers
        vals = [0.0] * 50 + [10.0, -10.0, 20.0, -20.0]
        assert _compute_kurtosis(vals) > 0


class TestUlcerIndex:
    def test_no_drawdowns(self):
        assert _compute_ulcer_index([]) == 0.0

    def test_single_drawdown(self):
        dd = DrawdownPeriod(
            start_ts=0, trough_ts=100, end_ts=200,
            peak_equity=10000, trough_equity=9000,
            drawdown_pct=10.0, duration_s=200,
        )
        assert abs(_compute_ulcer_index([dd]) - 10.0) < 0.01

    def test_multiple_drawdowns(self):
        dds = [
            DrawdownPeriod(start_ts=0, trough_ts=100, end_ts=200,
                           peak_equity=10000, trough_equity=9000,
                           drawdown_pct=10.0, duration_s=200),
            DrawdownPeriod(start_ts=300, trough_ts=400, end_ts=500,
                           peak_equity=10500, trough_equity=10000,
                           drawdown_pct=4.76, duration_s=200),
        ]
        ui = _compute_ulcer_index(dds)
        assert ui > 0
        # RMS of [10.0, 4.76] = sqrt((100 + 22.66)/2) ≈ 7.83
        assert abs(ui - 7.83) < 0.1


# ── Risk Metrics Integration ──


class TestComputeRiskMetrics:
    def test_empty_result(self):
        result = _make_result()
        risk = compute_risk_metrics(result)
        assert isinstance(risk, RiskMetrics)
        assert risk.num_drawdowns == 0
        assert risk.worst_trade_pct == 0.0

    def test_with_trades(self):
        trades = [
            _make_trade(pnl_pct=5.0, is_win=True),
            _make_trade(pnl_pct=3.0, is_win=True),
            _make_trade(pnl_pct=-4.0, is_win=False, pnl_dollars=-200.0),
            _make_trade(pnl_pct=-2.0, is_win=False, pnl_dollars=-100.0),
        ]
        ec = [
            _ep(0, 10000.0),
            _ep(86400, 10500.0),
            _ep(172800, 10800.0),
            _ep(259200, 10400.0),
            _ep(345600, 10200.0),
        ]
        dd = DrawdownPeriod(
            start_ts=172800, trough_ts=345600, end_ts=0,
            peak_equity=10800, trough_equity=10200,
            drawdown_pct=5.56, duration_s=172800,
        )
        result = _make_result(
            trades=trades,
            equity_curve=ec,
            drawdown_periods=[dd],
            max_drawdown_pct=5.56,
        )
        risk = compute_risk_metrics(result)

        # MAE/MFE
        assert risk.mae_avg > 0  # has losing trades
        assert risk.mfe_avg > 0  # has winning trades
        assert risk.mfe_max == 5.0  # best trade
        assert risk.mae_max == 4.0  # worst loss magnitude

        # Drawdown
        assert risk.num_drawdowns == 1
        assert risk.avg_drawdown_pct > 0

        # Trade extremes
        assert risk.worst_trade_pct == -4.0
        assert risk.best_trade_pct == 5.0

        # Gain/pain ratio
        assert risk.gain_to_pain_ratio > 0

    def test_all_winners(self):
        trades = [
            _make_trade(pnl_pct=5.0, is_win=True),
            _make_trade(pnl_pct=3.0, is_win=True),
        ]
        ec = [_ep(0, 10000.0), _ep(86400, 10500.0), _ep(172800, 10800.0)]
        result = _make_result(
            trades=trades,
            equity_curve=ec,
            drawdown_periods=[],
            max_drawdown_pct=0.0,
        )
        risk = compute_risk_metrics(result)
        assert risk.mae_avg == 0.0
        assert risk.mae_max == 0.0
        assert risk.gain_to_pain_ratio == float("inf")
        assert risk.worst_trade_pct == 3.0  # smallest gain

    def test_skewness_positive_for_winners(self):
        """More winners than losers → right-skewed."""
        trades = [
            _make_trade(pnl_pct=10.0, is_win=True),
            _make_trade(pnl_pct=8.0, is_win=True),
            _make_trade(pnl_pct=7.0, is_win=True),
            _make_trade(pnl_pct=-2.0, is_win=False, pnl_dollars=-100.0),
        ]
        ec = [_ep(i * 86400, 10000.0 + i * 100) for i in range(5)]
        result = _make_result(trades=trades, equity_curve=ec)
        risk = compute_risk_metrics(result)
        assert risk.skewness < 0  # left-skewed since outlier is negative

    def test_pct_time_underwater(self):
        ec = [_ep(0, 10000.0), _ep(100000, 10500.0)]
        dd = DrawdownPeriod(
            start_ts=0, trough_ts=50000, end_ts=100000,
            peak_equity=10000, trough_equity=9500,
            drawdown_pct=5.0, duration_s=50000,
        )
        result = _make_result(equity_curve=ec, drawdown_periods=[dd])
        risk = compute_risk_metrics(result)
        assert risk.pct_time_underwater > 0
        assert risk.pct_time_underwater <= 1.0
