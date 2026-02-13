"""Tests for the backtesting engine."""

from __future__ import annotations

import pytest

from rot.backtest.config import BacktestConfig
from rot.backtest.engine import (
    BacktestEngine,
    _compute_pnl_pct,
    _position_size_confidence,
    _position_size_fixed,
    _position_size_kelly,
    _resolve_exit_price,
)


# ── Helpers ──


def _make_signal(**overrides) -> dict:
    """Create a signal dict matching get_backtest_signals() output."""
    defaults = dict(
        signal_id="sig-001",
        ticker="TSLA",
        stance="bullish",
        strategy="debit_spread",
        event_type="product_news",
        confidence=0.65,
        created_at=1700000000.0,
        price_at_signal=250.0,
        price_1h=252.0,
        price_4h=255.0,
        price_1d=260.0,
        max_gain_pct=None,
        max_loss_pct=None,
    )
    defaults.update(overrides)
    return defaults


def _signals_sequence(n: int, base_ts: float = 1700000000.0) -> list[dict]:
    """Create N signals spread 86400s apart with varied outcomes."""
    signals = []
    for i in range(n):
        is_win = i % 3 != 0  # 2/3 win rate
        entry = 100.0
        exit_1d = 105.0 if is_win else 95.0
        signals.append(
            _make_signal(
                signal_id=f"sig-{i:03d}",
                created_at=base_ts + i * 86400,
                price_at_signal=entry,
                price_1d=exit_1d,
                price_4h=exit_1d - 1.0 if is_win else exit_1d + 1.0,
                price_1h=entry + 0.5,
                confidence=0.5 + (i % 5) * 0.1,
            )
        )
    return signals


# ── P&L Calculation Tests ──


class TestComputePnlPct:
    def test_bullish_price_up(self):
        """Bullish + price up → positive P&L."""
        pnl = _compute_pnl_pct("bullish", "debit_spread", 100.0, 105.0)
        assert abs(pnl - 5.0) < 0.01

    def test_bullish_price_down(self):
        """Bullish + price down → negative P&L."""
        pnl = _compute_pnl_pct("bullish", "debit_spread", 100.0, 95.0)
        assert abs(pnl - (-5.0)) < 0.01

    def test_bearish_price_down(self):
        """Bearish + price down → positive P&L (profit from drop)."""
        pnl = _compute_pnl_pct("bearish", "credit_spread", 100.0, 95.0)
        assert abs(pnl - 5.0) < 0.01

    def test_bearish_price_up(self):
        """Bearish + price up → negative P&L."""
        pnl = _compute_pnl_pct("bearish", "credit_spread", 100.0, 105.0)
        assert abs(pnl - (-5.0)) < 0.01

    def test_mixed_straddle_big_move(self):
        """Mixed stance → 0 P&L (neutral, regardless of strategy)."""
        pnl = _compute_pnl_pct("mixed", "straddle", 100.0, 103.0)
        assert pnl == 0.0

    def test_mixed_straddle_small_move(self):
        """Mixed stance → 0 P&L (neutral, regardless of strategy)."""
        pnl = _compute_pnl_pct("mixed", "straddle", 100.0, 100.5)
        assert pnl == 0.0

    def test_mixed_iron_condor_small_move(self):
        """Mixed stance → 0 P&L (neutral, regardless of strategy)."""
        pnl = _compute_pnl_pct("mixed", "iron_condor", 100.0, 100.5)
        assert pnl == 0.0

    def test_mixed_iron_condor_big_move(self):
        """Mixed stance → 0 P&L (neutral, regardless of strategy)."""
        pnl = _compute_pnl_pct("mixed", "iron_condor", 100.0, 103.0)
        assert pnl == 0.0

    def test_unknown_stance(self):
        """Unknown stance → 0 P&L (neutral)."""
        pnl = _compute_pnl_pct("unknown", "debit_spread", 100.0, 110.0)
        assert pnl == 0.0

    def test_zero_entry_price(self):
        pnl = _compute_pnl_pct("bullish", "debit_spread", 0.0, 100.0)
        assert pnl == 0.0

    def test_stop_loss_cap(self):
        """Stop loss caps negative P&L."""
        pnl = _compute_pnl_pct(
            "bullish", "debit_spread", 100.0, 80.0,
            max_loss_pct=10.0,
        )
        assert abs(pnl - (-10.0)) < 0.01

    def test_take_profit_cap(self):
        """Take profit caps positive P&L."""
        pnl = _compute_pnl_pct(
            "bullish", "debit_spread", 100.0, 130.0,
            max_gain_pct=15.0,
        )
        assert abs(pnl - 15.0) < 0.01


# ── Exit Price Resolution ──


class TestResolveExitPrice:
    def test_prefer_1d(self):
        sig = _make_signal(price_1d=260.0, price_4h=255.0, price_1h=252.0)
        assert _resolve_exit_price(sig, use_1d=True) == 260.0

    def test_fallback_4h_when_1d_missing(self):
        sig = _make_signal(price_1d=None, price_4h=255.0, price_1h=252.0)
        assert _resolve_exit_price(sig, use_1d=True) == 255.0

    def test_fallback_1h(self):
        sig = _make_signal(price_1d=None, price_4h=None, price_1h=252.0)
        assert _resolve_exit_price(sig, use_1d=True) == 252.0

    def test_none_when_all_missing(self):
        sig = _make_signal(price_1d=None, price_4h=None, price_1h=None)
        assert _resolve_exit_price(sig, use_1d=True) is None

    def test_prefer_4h_when_not_1d(self):
        sig = _make_signal(price_1d=260.0, price_4h=255.0, price_1h=252.0)
        assert _resolve_exit_price(sig, use_1d=False) == 255.0

    def test_zero_price_skipped(self):
        sig = _make_signal(price_1d=0.0, price_4h=255.0, price_1h=252.0)
        assert _resolve_exit_price(sig, use_1d=True) == 255.0


# ── Position Sizing ──


class TestPositionSizing:
    def test_fixed_pct(self):
        assert _position_size_fixed(10000.0, 5.0) == 500.0

    def test_fixed_pct_10(self):
        assert _position_size_fixed(10000.0, 10.0) == 1000.0

    def test_kelly_no_history(self):
        """Kelly with no history → minimum 2% position."""
        result = _position_size_kelly(10000.0, 0.0, 0.0, 0.0)
        assert result == 200.0

    def test_kelly_good_edge(self):
        """Kelly with 60% win rate, 2:1 ratio → meaningful position."""
        result = _position_size_kelly(10000.0, 0.6, 4.0, 2.0)
        # f* = (0.6*2 - 0.4)/2 = 0.4, half-Kelly = 0.2 → $2000
        assert result > 500  # should be a reasonable position
        assert result <= 2500  # but not extreme

    def test_kelly_capped(self):
        """Kelly can't exceed max_pct."""
        result = _position_size_kelly(10000.0, 0.9, 10.0, 1.0, max_pct=10.0)
        assert result <= 500.0  # 10% / 2 (half-Kelly) = 5%

    def test_confidence_weighted_low(self):
        """Low confidence → small position."""
        result = _position_size_confidence(10000.0, 0.0, 5.0)
        # scale = 0.5, → 10000 * 0.05 * 0.5 = 250
        assert abs(result - 250.0) < 0.01

    def test_confidence_weighted_high(self):
        """High confidence → large position."""
        result = _position_size_confidence(10000.0, 1.0, 5.0)
        # scale = 2.0, → 10000 * 0.05 * 2.0 = 1000
        assert abs(result - 1000.0) < 0.01

    def test_confidence_weighted_mid(self):
        """Mid confidence → base position."""
        result = _position_size_confidence(10000.0, 0.5, 5.0)
        # scale = 0.5 + 0.5*1.5 = 1.25, → 10000 * 0.05 * 1.25 = 625
        assert abs(result - 625.0) < 0.01


# ── Engine Integration Tests ──


class TestBacktestEngine:
    def setup_method(self):
        self.engine = BacktestEngine()

    def test_empty_signals(self):
        result = self.engine.run([], BacktestConfig())
        assert result.total_trades == 0
        assert result.final_equity == 10000.0
        assert result.total_return_pct == 0.0

    def test_single_winning_trade(self):
        signals = [_make_signal(
            stance="bullish",
            price_at_signal=100.0,
            price_1d=105.0,
        )]
        result = self.engine.run(signals, BacktestConfig())
        assert result.total_trades == 1
        assert result.winning_trades == 1
        assert result.losing_trades == 0
        assert result.win_rate == 1.0
        assert result.final_equity > 10000.0

    def test_single_losing_trade(self):
        signals = [_make_signal(
            stance="bullish",
            price_at_signal=100.0,
            price_1d=95.0,
        )]
        result = self.engine.run(signals, BacktestConfig())
        assert result.total_trades == 1
        assert result.winning_trades == 0
        assert result.losing_trades == 1
        assert result.final_equity < 10000.0

    def test_multiple_trades(self):
        signals = _signals_sequence(10)
        result = self.engine.run(signals, BacktestConfig())
        assert result.total_trades == 10
        assert result.winning_trades + result.losing_trades == 10
        assert len(result.trades) == 10
        assert len(result.equity_curve) == 11  # initial + 10 trades

    def test_chronological_order(self):
        """Signals are processed in chronological order regardless of input order."""
        # Create signals in reverse order
        signals = [
            _make_signal(signal_id="late", created_at=1700100000.0, price_at_signal=100.0, price_1d=110.0),
            _make_signal(signal_id="early", created_at=1700000000.0, price_at_signal=100.0, price_1d=105.0),
        ]
        result = self.engine.run(signals, BacktestConfig())
        assert result.trades[0].signal_id == "early"
        assert result.trades[1].signal_id == "late"

    def test_confidence_filter(self):
        signals = [
            _make_signal(confidence=0.3),
            _make_signal(confidence=0.7, signal_id="high"),
        ]
        config = BacktestConfig(min_confidence=0.5)
        result = self.engine.run(signals, config)
        assert result.total_trades == 1
        assert result.trades[0].signal_id == "high"

    def test_strategy_filter(self):
        signals = [
            _make_signal(strategy="debit_spread"),
            _make_signal(strategy="credit_spread", signal_id="credit"),
        ]
        config = BacktestConfig(strategy_filter="credit_spread")
        result = self.engine.run(signals, config)
        assert result.total_trades == 1
        assert result.trades[0].strategy == "credit_spread"

    def test_event_type_filter(self):
        signals = [
            _make_signal(event_type="earnings_rumor", signal_id="er"),
            _make_signal(event_type="product_news"),
        ]
        config = BacktestConfig(event_type_filter="earnings_rumor")
        result = self.engine.run(signals, config)
        assert result.total_trades == 1
        assert result.trades[0].signal_id == "er"

    def test_stance_filter(self):
        signals = [
            _make_signal(stance="bullish"),
            _make_signal(stance="bearish", signal_id="bear"),
        ]
        config = BacktestConfig(stance_filter="bearish")
        result = self.engine.run(signals, config)
        assert result.total_trades == 1
        assert result.trades[0].stance == "bearish"

    def test_ticker_filter(self):
        signals = [
            _make_signal(ticker="TSLA"),
            _make_signal(ticker="AAPL", signal_id="aapl"),
        ]
        config = BacktestConfig(ticker_filter="AAPL")
        result = self.engine.run(signals, config)
        assert result.total_trades == 1
        assert result.trades[0].ticker == "AAPL"

    def test_skip_missing_prices(self):
        signals = [
            _make_signal(price_at_signal=None),
            _make_signal(price_1d=None, price_4h=None, price_1h=None, signal_id="noexit"),
            _make_signal(signal_id="valid"),
        ]
        result = self.engine.run(signals, BacktestConfig())
        assert result.total_trades == 1
        assert result.trades[0].signal_id == "valid"

    def test_position_size_fixed_mode(self):
        """Default fixed_pct mode → position = 5% of equity."""
        signals = [_make_signal(price_at_signal=100.0, price_1d=110.0)]
        config = BacktestConfig(position_size_pct=10.0)
        result = self.engine.run(signals, config)
        # 10% of 10000 = $1000 position, 10% gain → $100 pnl
        expected_pnl = 1000.0 * 0.10
        assert abs(result.trades[0].pnl_dollars - expected_pnl) < 1.0

    def test_position_size_confidence_mode(self):
        """Confidence-weighted mode scales with signal confidence."""
        signals = [_make_signal(price_at_signal=100.0, price_1d=110.0, confidence=1.0)]
        config = BacktestConfig(position_size_mode="confidence_weighted", position_size_pct=5.0)
        result = self.engine.run(signals, config)
        # confidence=1.0 → scale=2.0 → position=10000*0.05*2.0=1000
        # 10% gain → $100 pnl
        assert abs(result.trades[0].pnl_dollars - 100.0) < 1.0

    def test_kelly_mode(self):
        """Kelly mode uses running stats."""
        signals = _signals_sequence(5)
        config = BacktestConfig(position_size_mode="kelly")
        result = self.engine.run(signals, config)
        assert result.total_trades == 5

    def test_stop_loss(self):
        """Stop loss caps losses."""
        signals = [_make_signal(
            stance="bullish",
            price_at_signal=100.0,
            price_1d=80.0,  # -20% move
        )]
        config = BacktestConfig(stop_loss_pct=5.0)
        result = self.engine.run(signals, config)
        assert result.trades[0].pnl_pct >= -5.0

    def test_take_profit(self):
        """Take profit caps gains."""
        signals = [_make_signal(
            stance="bullish",
            price_at_signal=100.0,
            price_1d=130.0,  # +30% move
        )]
        config = BacktestConfig(take_profit_pct=10.0)
        result = self.engine.run(signals, config)
        assert result.trades[0].pnl_pct <= 10.0

    def test_bearish_stance(self):
        """Bearish stance profits when price drops."""
        signals = [_make_signal(
            stance="bearish",
            strategy="credit_spread",
            price_at_signal=100.0,
            price_1d=90.0,
        )]
        result = self.engine.run(signals, BacktestConfig())
        assert result.trades[0].is_win is True
        assert result.trades[0].pnl_pct > 0

    def test_equity_curve_starts_at_capital(self):
        signals = _signals_sequence(3)
        config = BacktestConfig(starting_capital=5000.0)
        result = self.engine.run(signals, config)
        assert result.equity_curve[0].equity == 5000.0

    def test_use_1d_price_false(self):
        """When use_1d_price=False, prefers 4h exit."""
        signals = [_make_signal(
            stance="bullish",
            price_at_signal=100.0,
            price_1d=110.0,
            price_4h=105.0,
        )]
        config = BacktestConfig(use_1d_price=False)
        result = self.engine.run(signals, config)
        assert result.trades[0].exit_price == 105.0

    def test_result_has_metrics(self):
        """Result includes computed metrics."""
        signals = _signals_sequence(20)
        result = self.engine.run(signals, BacktestConfig())
        assert result.total_return_pct != 0.0
        assert result.profit_factor > 0
        assert result.max_drawdown_pct >= 0
        assert result.monthly_returns  # non-empty
        assert result.strategy_breakdown  # non-empty
        assert result.config_dict  # includes config

    def test_result_config_dict(self):
        config = BacktestConfig(starting_capital=5000.0, stop_loss_pct=10.0)
        result = self.engine.run([], config)
        assert result.config_dict["starting_capital"] == 5000.0
        assert result.config_dict["stop_loss_pct"] == 10.0

    def test_equity_never_negative(self):
        """Equity should never go below 0."""
        # Create signals that all lose heavily
        signals = [
            _make_signal(
                signal_id=f"sig-{i}",
                created_at=1700000000.0 + i * 86400,
                stance="bullish",
                price_at_signal=100.0,
                price_1d=50.0,  # -50% move
            )
            for i in range(5)
        ]
        config = BacktestConfig(position_size_pct=50.0)  # large positions
        result = self.engine.run(signals, config)
        for ep in result.equity_curve:
            assert ep.equity >= 0.0

    def test_mixed_strategies_in_result(self):
        signals = [
            _make_signal(strategy="debit_spread", signal_id="s1"),
            _make_signal(strategy="credit_spread", signal_id="s2", created_at=1700086400.0),
        ]
        result = self.engine.run(signals, BacktestConfig())
        assert "debit_spread" in result.strategy_breakdown
        assert "credit_spread" in result.strategy_breakdown

    def test_multiple_filters_combined(self):
        """Multiple filters work together."""
        signals = [
            _make_signal(confidence=0.8, stance="bullish", strategy="debit_spread", signal_id="match"),
            _make_signal(confidence=0.3, stance="bullish", strategy="debit_spread"),
            _make_signal(confidence=0.8, stance="bearish", strategy="debit_spread"),
            _make_signal(confidence=0.8, stance="bullish", strategy="credit_spread"),
        ]
        config = BacktestConfig(
            min_confidence=0.5,
            stance_filter="bullish",
            strategy_filter="debit_spread",
        )
        result = self.engine.run(signals, config)
        assert result.total_trades == 1
        assert result.trades[0].signal_id == "match"

    def test_large_backtest(self):
        """Performance test with 100 signals."""
        signals = _signals_sequence(100)
        result = self.engine.run(signals, BacktestConfig())
        assert result.total_trades == 100
        assert len(result.equity_curve) == 101
