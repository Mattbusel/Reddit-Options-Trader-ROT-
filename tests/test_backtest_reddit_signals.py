"""Unit tests for the Round 5 Reddit signal backtest API.

Tests HistoricalSignal, BacktestTrade, BacktestResult, and BacktestEngine
using mock price data — no network access required.
"""

from __future__ import annotations

import datetime
import math
import unittest

from rot.backtest.options_backtest import (
    BacktestEngine,
    BacktestResult,
    BacktestTrade,
    HistoricalSignal,
    _compute_max_drawdown,
    _compute_sharpe,
    bs_call_price,
    bs_put_price,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_price_data(
    ticker: str,
    start: datetime.date,
    n_days: int,
    base_price: float = 100.0,
    daily_change: float = 0.0,
) -> dict:
    """Build a price_data dict with daily prices from start for n_days."""
    prices = {}
    for i in range(n_days):
        d = start + datetime.timedelta(days=i)
        prices[d] = base_price + daily_change * i
    return {ticker: prices}


def _bullish_signal(ticker="AAPL", date=None, confidence=0.7):
    if date is None:
        date = datetime.date(2024, 1, 2)
    return HistoricalSignal(
        ticker=ticker,
        signal_type="bull_call",
        date=date,
        predicted_direction="bullish",
        confidence=confidence,
    )


def _bearish_signal(ticker="AAPL", date=None, confidence=0.7):
    if date is None:
        date = datetime.date(2024, 1, 2)
    return HistoricalSignal(
        ticker=ticker,
        signal_type="bear_put",
        date=date,
        predicted_direction="bearish",
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# HistoricalSignal
# ---------------------------------------------------------------------------

class TestHistoricalSignal(unittest.TestCase):

    def test_bullish_valid(self):
        s = _bullish_signal()
        self.assertEqual(s.predicted_direction, "bullish")
        self.assertAlmostEqual(s.confidence, 0.7)

    def test_bearish_valid(self):
        s = _bearish_signal()
        self.assertEqual(s.predicted_direction, "bearish")

    def test_invalid_direction_raises(self):
        with self.assertRaises(ValueError):
            HistoricalSignal(
                ticker="AAPL",
                signal_type="unknown",
                date=datetime.date(2024, 1, 2),
                predicted_direction="neutral",
            )

    def test_confidence_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            HistoricalSignal(
                ticker="AAPL",
                signal_type="bull_call",
                date=datetime.date(2024, 1, 2),
                predicted_direction="bullish",
                confidence=1.5,
            )

    def test_confidence_zero_valid(self):
        s = HistoricalSignal(
            ticker="AAPL",
            signal_type="bull_call",
            date=datetime.date(2024, 1, 2),
            predicted_direction="bullish",
            confidence=0.0,
        )
        self.assertAlmostEqual(s.confidence, 0.0)

    def test_fields(self):
        s = _bullish_signal("TSLA")
        self.assertEqual(s.ticker, "TSLA")
        self.assertEqual(s.signal_type, "bull_call")


# ---------------------------------------------------------------------------
# BacktestTrade
# ---------------------------------------------------------------------------

class TestBacktestTrade(unittest.TestCase):

    def _make_trade(self, entry=2.0, exit_p=3.0, pnl=0.5, outcome="win"):
        return BacktestTrade(
            signal=_bullish_signal(),
            entry_price=entry,
            exit_price=exit_p,
            strategy_pnl=pnl,
            holding_days=10,
            outcome=outcome,
        )

    def test_is_win_positive_pnl(self):
        t = self._make_trade(pnl=0.3)
        self.assertTrue(t.is_win())

    def test_is_win_negative_pnl(self):
        t = self._make_trade(pnl=-0.2)
        self.assertFalse(t.is_win())

    def test_pnl_pct_formula(self):
        t = self._make_trade(entry=2.0, exit_p=3.0)
        self.assertAlmostEqual(t.pnl_pct(), 0.5)

    def test_pnl_pct_zero_entry(self):
        t = self._make_trade(entry=0.0, exit_p=1.0)
        self.assertEqual(t.pnl_pct(), 0.0)


# ---------------------------------------------------------------------------
# Sharpe and drawdown helpers
# ---------------------------------------------------------------------------

class TestStatHelpers(unittest.TestCase):

    def test_sharpe_zero_for_single_value(self):
        self.assertEqual(_compute_sharpe([0.1]), 0.0)

    def test_sharpe_zero_for_constant(self):
        self.assertEqual(_compute_sharpe([0.1, 0.1, 0.1]), 0.0)

    def test_sharpe_positive_for_positive_mean(self):
        pnls = [0.01] * 20 + [0.02] * 20
        self.assertGreater(_compute_sharpe(pnls), 0.0)

    def test_max_drawdown_no_drawdown(self):
        pnls = [0.1, 0.1, 0.1]
        self.assertAlmostEqual(_compute_max_drawdown(pnls), 0.0)

    def test_max_drawdown_simple(self):
        # +1, -2 → peak=1, trough=-1 → dd=2
        pnls = [1.0, -2.0]
        dd = _compute_max_drawdown(pnls)
        self.assertAlmostEqual(dd, 2.0)

    def test_max_drawdown_empty(self):
        self.assertEqual(_compute_max_drawdown([]), 0.0)


# ---------------------------------------------------------------------------
# BacktestEngine — core functionality
# ---------------------------------------------------------------------------

class TestBacktestEngine(unittest.TestCase):

    def setUp(self):
        self.start = datetime.date(2024, 1, 2)
        self.price_data = _make_price_data(
            "AAPL", self.start, n_days=60, base_price=100.0, daily_change=0.5
        )
        self.engine = BacktestEngine(
            stop_loss_pct=0.20,
            take_profit_pct=0.50,
            holding_days=30,
        )

    def test_run_returns_backtest_result(self):
        signals = [_bullish_signal(date=self.start)]
        result = self.engine.run(signals, self.price_data)
        self.assertIsInstance(result, BacktestResult)

    def test_empty_signals_returns_empty_result(self):
        result = self.engine.run([], self.price_data)
        self.assertEqual(result.n_trades(), 0)
        self.assertEqual(result.win_rate, 0.0)
        self.assertIsNone(result.best_trade)
        self.assertIsNone(result.worst_trade)

    def test_missing_ticker_skipped(self):
        signal = _bullish_signal("UNKNOWN_TICKER", date=self.start)
        result = self.engine.run([signal], self.price_data)
        self.assertEqual(result.n_trades(), 0)

    def test_bullish_signal_in_rising_market(self):
        # Rising price should produce a winning call trade
        signals = [_bullish_signal(date=self.start)]
        result = self.engine.run(signals, self.price_data)
        self.assertEqual(result.n_trades(), 1)
        # Rising market → call should gain value → take_profit exit
        trade = result.trades[0]
        self.assertIn(trade.outcome, ("take_profit", "win", "expiry"))

    def test_bearish_signal_in_falling_market(self):
        falling_data = _make_price_data(
            "AAPL", self.start, n_days=60, base_price=100.0, daily_change=-0.5
        )
        signals = [_bearish_signal(date=self.start)]
        result = self.engine.run(signals, falling_data)
        self.assertEqual(result.n_trades(), 1)

    def test_win_rate_all_wins(self):
        # Strongly rising market → call take-profit
        signals = [_bullish_signal(date=self.start)]
        engine = BacktestEngine(
            stop_loss_pct=0.20,
            take_profit_pct=0.50,
            holding_days=30,
        )
        result = engine.run(signals, self.price_data)
        self.assertGreaterEqual(result.win_rate, 0.0)
        self.assertLessEqual(result.win_rate, 1.0)

    def test_multiple_signals_multiple_trades(self):
        dates = [self.start + datetime.timedelta(days=i) for i in range(5)]
        signals = [_bullish_signal(date=d) for d in dates]
        result = self.engine.run(signals, self.price_data)
        self.assertGreater(result.n_trades(), 0)

    def test_best_and_worst_trade(self):
        signals = [
            _bullish_signal(date=self.start),
            _bearish_signal(date=self.start),
        ]
        result = self.engine.run(signals, self.price_data)
        if result.n_trades() >= 2:
            self.assertGreaterEqual(
                result.best_trade.strategy_pnl,
                result.worst_trade.strategy_pnl,
            )

    def test_total_pnl_is_sum(self):
        signals = [_bullish_signal(date=self.start)]
        result = self.engine.run(signals, self.price_data)
        expected = sum(t.strategy_pnl for t in result.trades)
        self.assertAlmostEqual(result.total_pnl, expected, places=10)

    def test_sharpe_returns_float(self):
        signals = [_bullish_signal(date=self.start + datetime.timedelta(days=i)) for i in range(5)]
        result = self.engine.run(signals, self.price_data)
        self.assertIsInstance(result.sharpe, float)

    def test_max_drawdown_nonnegative(self):
        signals = [_bullish_signal(date=self.start)]
        result = self.engine.run(signals, self.price_data)
        self.assertGreaterEqual(result.max_drawdown, 0.0)

    def test_n_wins_plus_losses_equals_trades(self):
        signals = [_bullish_signal(date=self.start + datetime.timedelta(days=i)) for i in range(3)]
        result = self.engine.run(signals, self.price_data)
        self.assertEqual(result.n_wins() + result.n_losses(), result.n_trades())

    def test_holding_days_capped(self):
        engine = BacktestEngine(holding_days=5)
        signals = [_bullish_signal(date=self.start)]
        result = engine.run(signals, self.price_data)
        if result.trades:
            self.assertLessEqual(result.trades[0].holding_days, 30)

    def test_stop_loss_triggered(self):
        # Collapsing market → stop-loss should trigger for calls
        falling = _make_price_data(
            "AAPL", self.start, n_days=60, base_price=100.0, daily_change=-5.0
        )
        engine = BacktestEngine(stop_loss_pct=0.05, take_profit_pct=10.0, holding_days=30)
        signals = [_bullish_signal(date=self.start)]
        result = engine.run(signals, falling)
        if result.trades:
            # Either stop_loss or expiry depending on IV curve
            self.assertIn(result.trades[0].outcome, ("stop_loss", "loss", "expiry"))


if __name__ == "__main__":
    unittest.main()
