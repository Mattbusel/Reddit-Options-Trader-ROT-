"""Tests for backtest data types: BacktestConfig, TradeRecord, BacktestResult."""

from __future__ import annotations

import pytest

from rot.backtest.config import BacktestConfig
from rot.backtest.result import BacktestResult, DrawdownPeriod, EquityPoint, TradeRecord


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


# ── BacktestConfig Tests ──


class TestBacktestConfig:
    def test_default_values(self):
        cfg = BacktestConfig()
        assert cfg.starting_capital == 10_000.0
        assert cfg.position_size_mode == "fixed_pct"
        assert cfg.position_size_pct == 5.0
        assert cfg.max_concurrent_positions == 5
        assert cfg.stop_loss_pct == 0.0
        assert cfg.take_profit_pct == 0.0
        assert cfg.min_confidence == 0.0
        assert cfg.strategy_filter is None
        assert cfg.event_type_filter is None
        assert cfg.stance_filter is None
        assert cfg.ticker_filter is None
        assert cfg.days == 90
        assert cfg.use_1d_price is True

    def test_validation_passes_for_defaults(self):
        cfg = BacktestConfig()
        errors = cfg.validate()
        assert errors == []

    def test_validation_catches_bad_capital(self):
        cfg = BacktestConfig(starting_capital=0)
        errors = cfg.validate()
        assert any("starting_capital" in e for e in errors)

    def test_validation_catches_bad_position_size(self):
        cfg = BacktestConfig(position_size_pct=0.0)
        errors = cfg.validate()
        assert any("position_size_pct" in e for e in errors)

    def test_validation_catches_bad_stop_loss(self):
        cfg = BacktestConfig(stop_loss_pct=60)
        errors = cfg.validate()
        assert any("stop_loss_pct" in e for e in errors)

    def test_validation_catches_bad_confidence(self):
        cfg = BacktestConfig(min_confidence=2.0)
        errors = cfg.validate()
        assert any("min_confidence" in e for e in errors)

    def test_validation_catches_bad_days(self):
        cfg = BacktestConfig(days=0)
        errors = cfg.validate()
        assert any("days" in e for e in errors)

    def test_validation_catches_bad_max_positions(self):
        cfg = BacktestConfig(max_concurrent_positions=0)
        errors = cfg.validate()
        assert any("max_concurrent_positions" in e for e in errors)

    def test_to_dict_roundtrip(self):
        cfg = BacktestConfig(
            starting_capital=5000.0,
            position_size_mode="kelly",
            strategy_filter="debit_spread",
            stop_loss_pct=10.0,
        )
        d = cfg.to_dict()
        cfg2 = BacktestConfig.from_dict(d)
        assert cfg == cfg2

    def test_from_dict_ignores_unknown_keys(self):
        d = {"starting_capital": 5000.0, "unknown_key": "garbage"}
        cfg = BacktestConfig.from_dict(d)
        assert cfg.starting_capital == 5000.0

    def test_frozen(self):
        cfg = BacktestConfig()
        with pytest.raises(AttributeError):
            cfg.starting_capital = 999  # type: ignore[misc]

    def test_custom_filters(self):
        cfg = BacktestConfig(
            strategy_filter="credit_spread",
            event_type_filter="earnings_rumor",
            stance_filter="bearish",
            ticker_filter="AAPL",
        )
        d = cfg.to_dict()
        assert d["strategy_filter"] == "credit_spread"
        assert d["event_type_filter"] == "earnings_rumor"
        assert d["stance_filter"] == "bearish"
        assert d["ticker_filter"] == "AAPL"


# ── TradeRecord Tests ──


class TestTradeRecord:
    def test_creation(self):
        t = _make_trade()
        assert t.ticker == "TSLA"
        assert t.is_win is True
        assert t.pnl_pct == 4.0

    def test_frozen(self):
        t = _make_trade()
        with pytest.raises(AttributeError):
            t.pnl_pct = 999  # type: ignore[misc]


# ── BacktestResult Tests ──


class TestBacktestResult:
    def test_empty_result(self):
        result = BacktestResult(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_return_pct=0.0,
            annual_return_pct=0.0,
            final_equity=10000.0,
        )
        assert result.total_trades == 0
        assert result.trades == []
        assert result.equity_curve == []
        assert result.monthly_returns == {}

    def test_to_dict_has_all_fields(self):
        result = BacktestResult(
            total_trades=5,
            winning_trades=3,
            losing_trades=2,
            win_rate=0.6,
            total_return_pct=12.5,
            annual_return_pct=50.0,
            final_equity=11250.0,
            sharpe_ratio=1.5,
            profit_factor=2.0,
        )
        d = result.to_dict()
        assert d["total_trades"] == 5
        assert d["win_rate"] == 0.6
        assert d["sharpe_ratio"] == 1.5
        assert "equity_curve" in d
        assert "trades" in d
        assert "monthly_returns" in d

    def test_to_dict_with_trades(self):
        t = _make_trade()
        result = BacktestResult(
            total_trades=1,
            winning_trades=1,
            losing_trades=0,
            win_rate=1.0,
            total_return_pct=4.0,
            annual_return_pct=48.0,
            final_equity=10400.0,
            trades=[t],
        )
        d = result.to_dict()
        assert len(d["trades"]) == 1
        assert d["trades"][0]["ticker"] == "TSLA"

    def test_to_dict_none_sharpe(self):
        result = BacktestResult(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_return_pct=0.0,
            annual_return_pct=0.0,
            final_equity=10000.0,
            sharpe_ratio=None,
        )
        d = result.to_dict()
        assert d["sharpe_ratio"] is None


# ── EquityPoint / DrawdownPeriod Tests ──


class TestEquityPoint:
    def test_creation(self):
        ep = EquityPoint(timestamp=1700000000.0, equity=10500.0, trade_count=3)
        assert ep.equity == 10500.0
        assert ep.trade_count == 3


class TestDrawdownPeriod:
    def test_creation(self):
        dd = DrawdownPeriod(
            start_ts=1700000000.0,
            trough_ts=1700003600.0,
            end_ts=1700007200.0,
            peak_equity=10500.0,
            trough_equity=9000.0,
            drawdown_pct=14.29,
            duration_s=7200.0,
        )
        assert dd.drawdown_pct == 14.29
        assert dd.duration_s == 7200.0
