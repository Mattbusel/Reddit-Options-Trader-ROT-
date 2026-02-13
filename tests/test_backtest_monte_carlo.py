"""Tests for Monte Carlo simulation."""

from __future__ import annotations

import pytest

from rot.backtest.monte_carlo import MonteCarloResult, run_monte_carlo
from rot.backtest.result import TradeRecord


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


def _winning_trades(n: int) -> list[TradeRecord]:
    return [_make_trade(pnl_pct=5.0, is_win=True) for _ in range(n)]


def _losing_trades(n: int) -> list[TradeRecord]:
    return [_make_trade(pnl_pct=-5.0, pnl_dollars=-250.0, is_win=False) for _ in range(n)]


def _mixed_trades(n_win: int, n_lose: int) -> list[TradeRecord]:
    return _winning_trades(n_win) + _losing_trades(n_lose)


# ── Tests ──


class TestMonteCarloEmpty:
    def test_no_trades(self):
        result = run_monte_carlo([], starting_capital=10000.0)
        assert result.n_trades == 0
        assert result.prob_profit == 0.0
        assert result.mean_final_equity == 10000.0
        assert result.std_final_equity == 0.0

    def test_empty_percentile_curves(self):
        result = run_monte_carlo([])
        for p in [5, 25, 50, 75, 95]:
            assert result.percentile_curves[p] == []


class TestMonteCarloBasic:
    def test_all_winners(self):
        trades = _winning_trades(20)
        result = run_monte_carlo(trades, seed=42, n_simulations=200)
        assert result.prob_profit == 1.0
        assert result.prob_ruin == 0.0
        assert result.mean_final_equity > 10000.0
        assert result.final_equity_p5 > 10000.0

    def test_all_losers(self):
        trades = _losing_trades(20)
        result = run_monte_carlo(trades, seed=42, n_simulations=200)
        assert result.prob_profit == 0.0
        assert result.mean_final_equity < 10000.0
        assert result.final_equity_p95 < 10000.0

    def test_mixed_trades(self):
        trades = _mixed_trades(15, 5)
        result = run_monte_carlo(trades, seed=42, n_simulations=500)
        assert result.n_trades == 20
        assert result.n_simulations == 500
        assert 0.0 <= result.prob_profit <= 1.0
        assert 0.0 <= result.prob_ruin <= 1.0


class TestMonteCarloReproducibility:
    def test_same_seed_same_result(self):
        trades = _mixed_trades(10, 10)
        r1 = run_monte_carlo(trades, seed=123, n_simulations=100)
        r2 = run_monte_carlo(trades, seed=123, n_simulations=100)
        assert r1.mean_final_equity == r2.mean_final_equity
        assert r1.prob_profit == r2.prob_profit
        assert r1.final_equity_p50 == r2.final_equity_p50

    def test_different_seed_different_result(self):
        trades = _mixed_trades(10, 10)
        r1 = run_monte_carlo(trades, seed=1, n_simulations=100)
        r2 = run_monte_carlo(trades, seed=999, n_simulations=100)
        # Not guaranteed to differ, but overwhelmingly likely
        assert r1.mean_final_equity != r2.mean_final_equity


class TestMonteCarloPercentiles:
    def test_percentile_ordering(self):
        """P5 <= P25 <= P50 <= P75 <= P95."""
        trades = _mixed_trades(15, 5)
        result = run_monte_carlo(trades, seed=42, n_simulations=500)
        assert result.final_equity_p5 <= result.final_equity_p25
        assert result.final_equity_p25 <= result.final_equity_p50
        assert result.final_equity_p50 <= result.final_equity_p75
        assert result.final_equity_p75 <= result.final_equity_p95

    def test_percentile_curves_length(self):
        trades = _mixed_trades(10, 5)
        result = run_monte_carlo(trades, seed=42, n_simulations=100)
        # Curves should have n_trades + 1 points (including starting point)
        for p in [5, 25, 50, 75, 95]:
            assert len(result.percentile_curves[p]) == 16  # 15 trades + 1

    def test_curves_start_at_capital(self):
        trades = _mixed_trades(10, 5)
        result = run_monte_carlo(trades, starting_capital=5000.0, seed=42, n_simulations=100)
        for p in [5, 25, 50, 75, 95]:
            assert result.percentile_curves[p][0] == 5000.0


class TestMonteCarloDrawdown:
    def test_drawdown_percentile_ordering(self):
        """P5 <= P50 <= P95 for drawdowns."""
        trades = _mixed_trades(15, 10)
        result = run_monte_carlo(trades, seed=42, n_simulations=500)
        assert result.max_drawdown_p5 <= result.max_drawdown_p50
        assert result.max_drawdown_p50 <= result.max_drawdown_p95

    def test_all_winners_low_drawdown(self):
        trades = _winning_trades(20)
        result = run_monte_carlo(trades, seed=42, n_simulations=200)
        assert result.max_drawdown_p50 == 0.0  # no drawdowns with all winners


class TestMonteCarloProbabilities:
    def test_prob_ranges(self):
        trades = _mixed_trades(10, 10)
        result = run_monte_carlo(trades, seed=42, n_simulations=500)
        assert 0.0 <= result.prob_profit <= 1.0
        assert 0.0 <= result.prob_ruin <= 1.0
        assert 0.0 <= result.prob_double <= 1.0

    def test_winning_system_high_prob_profit(self):
        trades = _mixed_trades(18, 2)  # 90% win rate
        result = run_monte_carlo(trades, seed=42, n_simulations=500)
        assert result.prob_profit > 0.8

    def test_losing_system_low_prob_profit(self):
        trades = _mixed_trades(2, 18)  # 10% win rate
        result = run_monte_carlo(trades, seed=42, n_simulations=500)
        assert result.prob_profit < 0.2


class TestMonteCarloStartingCapital:
    def test_custom_starting_capital(self):
        trades = _winning_trades(10)
        result = run_monte_carlo(trades, starting_capital=50000.0, seed=42, n_simulations=100)
        assert result.mean_final_equity > 50000.0
        assert result.final_equity_p5 > 50000.0

    def test_small_starting_capital(self):
        trades = _winning_trades(5)
        result = run_monte_carlo(trades, starting_capital=100.0, seed=42, n_simulations=100)
        assert result.mean_final_equity > 100.0
