"""Tests for src/rot/paper/options_paper.py"""
from __future__ import annotations

import math
import pytest

from rot.paper.options_paper import (
    ClosedTrade,
    OptionPosition,
    OptionsPaperTrader,
    PortfolioSummary,
    _bsm_call,
    _bsm_put,
    _bsm_delta_call,
)


# ---------------------------------------------------------------------------
# BSM helpers
# ---------------------------------------------------------------------------


class TestBSMHelpers:
    def test_call_positive_for_itm(self):
        price = _bsm_call(S=110, K=100, T=0.25, r=0.05, sigma=0.20)
        assert price > 10.0  # intrinsic value

    def test_put_positive_for_itm(self):
        price = _bsm_put(S=90, K=100, T=0.25, r=0.05, sigma=0.20)
        assert price > 10.0  # intrinsic value

    def test_call_parity_approx(self):
        """C - P ~ S - K*e^(-rT) (put-call parity)."""
        S, K, T, r, sigma = 100.0, 100.0, 0.5, 0.05, 0.2
        C = _bsm_call(S, K, T, r, sigma)
        P = _bsm_put(S, K, T, r, sigma)
        parity = S - K * math.exp(-r * T)
        assert math.isclose(C - P, parity, rel_tol=1e-6)

    def test_call_zero_time_is_intrinsic(self):
        price = _bsm_call(S=110, K=100, T=0.0, r=0.05, sigma=0.2)
        assert math.isclose(price, 10.0, abs_tol=1e-9)

    def test_delta_call_between_zero_and_one(self):
        d = _bsm_delta_call(S=100, K=100, T=0.5, r=0.05, sigma=0.2)
        assert 0.0 <= d <= 1.0

    def test_deep_itm_call_delta_near_one(self):
        d = _bsm_delta_call(S=200, K=100, T=0.5, r=0.05, sigma=0.2)
        assert d > 0.95


# ---------------------------------------------------------------------------
# OptionsPaperTrader construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_capital(self):
        t = OptionsPaperTrader()
        assert t.initial_capital == 100_000.0
        assert t.cash == 100_000.0

    def test_custom_capital(self):
        t = OptionsPaperTrader(initial_capital=50_000)
        assert t.initial_capital == 50_000.0

    def test_invalid_capital_raises(self):
        with pytest.raises(ValueError):
            OptionsPaperTrader(initial_capital=0)

    def test_initial_no_positions(self):
        t = OptionsPaperTrader()
        assert len(t.positions) == 0

    def test_initial_no_closed_trades(self):
        t = OptionsPaperTrader()
        assert len(t.closed_trades) == 0


# ---------------------------------------------------------------------------
# open_trade
# ---------------------------------------------------------------------------


class TestOpenTrade:
    def test_open_trade_returns_string(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 1)
        assert isinstance(pid, str)

    def test_open_trade_creates_position(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 1)
        assert pid in t.positions

    def test_open_trade_deducts_cash(self):
        t = OptionsPaperTrader(initial_capital=100_000)
        t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 1)
        assert t.cash == 100_000 - 3.5 * 1 * 100

    def test_open_trade_negative_premium_raises(self):
        t = OptionsPaperTrader()
        with pytest.raises(ValueError):
            t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", -1.0, 1)

    def test_open_trade_zero_quantity_raises(self):
        t = OptionsPaperTrader()
        with pytest.raises(ValueError):
            t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 0)

    def test_open_multiple_positions(self):
        t = OptionsPaperTrader()
        p1 = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 1)
        p2 = t.open_trade("TSLA", "long_put", [200.0], "2026-06-20", 5.0, 2)
        assert p1 != p2
        assert len(t.positions) == 2

    def test_position_attributes(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 2)
        pos = t.positions[pid]
        assert isinstance(pos, OptionPosition)
        assert pos.ticker == "AAPL"
        assert pos.strategy == "long_call"
        assert pos.strikes == [150.0]
        assert pos.expiry == "2026-06-20"
        assert pos.quantity == 2
        assert pos.entry_premium == 3.5


# ---------------------------------------------------------------------------
# close_trade
# ---------------------------------------------------------------------------


class TestCloseTrade:
    def test_close_returns_closed_trade(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 1)
        ct = t.close_trade(pid, exit_premium=5.0)
        assert isinstance(ct, ClosedTrade)

    def test_close_removes_from_positions(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 1)
        t.close_trade(pid, exit_premium=5.0)
        assert pid not in t.positions

    def test_close_adds_to_closed_trades(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 1)
        t.close_trade(pid, exit_premium=5.0)
        assert len(t.closed_trades) == 1

    def test_winning_trade_pnl(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 1)
        ct = t.close_trade(pid, exit_premium=5.0)
        assert math.isclose(ct.realised_pnl, (5.0 - 3.5) * 1 * 100)
        assert ct.is_winner

    def test_losing_trade_pnl(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 5.0, 1)
        ct = t.close_trade(pid, exit_premium=2.0)
        assert ct.realised_pnl < 0
        assert not ct.is_winner

    def test_close_unknown_raises(self):
        t = OptionsPaperTrader()
        with pytest.raises(KeyError):
            t.close_trade("nonexistent-id", exit_premium=1.0)

    def test_close_negative_premium_raises(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 1)
        with pytest.raises(ValueError):
            t.close_trade(pid, exit_premium=-1.0)


# ---------------------------------------------------------------------------
# mark_to_market
# ---------------------------------------------------------------------------


class TestMarkToMarket:
    def test_direct_price_update(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 1)
        t.mark_to_market(prices={pid: 5.0}, iv_surface={})
        assert t.positions[pid].current_value == 5.0

    def test_bsm_fallback_call(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [100.0], "2026-06-20", 5.0, 1)
        iv_surface = {"AAPL": {"spot": 110.0, "iv": 0.25, "r": 0.05, "T": 0.5}}
        t.mark_to_market(prices={}, iv_surface=iv_surface)
        pos = t.positions[pid]
        assert pos.current_value > 0.0

    def test_bsm_fallback_put(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_put", [100.0], "2026-06-20", 5.0, 1)
        iv_surface = {"AAPL": {"spot": 90.0, "iv": 0.25, "r": 0.05, "T": 0.5}}
        t.mark_to_market(prices={}, iv_surface=iv_surface)
        pos = t.positions[pid]
        assert pos.current_value > 0.0

    def test_delta_updated_via_bsm(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [100.0], "2026-06-20", 5.0, 1)
        iv_surface = {"AAPL": {"spot": 105.0, "iv": 0.20, "r": 0.05, "T": 0.5}}
        t.mark_to_market(prices={}, iv_surface=iv_surface)
        assert 0.0 <= t.positions[pid].delta <= 1.0

    def test_no_update_when_ticker_missing(self):
        t = OptionsPaperTrader()
        pid = t.open_trade("AAPL", "long_call", [150.0], "2026-06-20", 3.5, 1)
        entry_value = t.positions[pid].current_value
        t.mark_to_market(prices={}, iv_surface={})
        assert t.positions[pid].current_value == entry_value


# ---------------------------------------------------------------------------
# get_summary / PortfolioSummary
# ---------------------------------------------------------------------------


class TestPortfolioSummary:
    def test_summary_type(self):
        t = OptionsPaperTrader()
        assert isinstance(t.get_summary(), PortfolioSummary)

    def test_summary_no_trades(self):
        t = OptionsPaperTrader()
        s = t.get_summary()
        assert s.open_positions == 0
        assert s.closed_trades == 0
        assert s.win_rate == 0.0

    def test_win_rate_all_winners(self):
        t = OptionsPaperTrader()
        p1 = t.open_trade("A", "long_call", [100.0], "2026-06-20", 1.0, 1)
        p2 = t.open_trade("B", "long_call", [200.0], "2026-06-20", 2.0, 1)
        t.close_trade(p1, exit_premium=2.0)
        t.close_trade(p2, exit_premium=3.0)
        s = t.get_summary()
        assert s.win_rate == 1.0

    def test_win_rate_mixed(self):
        t = OptionsPaperTrader()
        p1 = t.open_trade("A", "long_call", [100.0], "2026-06-20", 3.0, 1)
        p2 = t.open_trade("B", "long_call", [200.0], "2026-06-20", 3.0, 1)
        t.close_trade(p1, exit_premium=5.0)  # winner
        t.close_trade(p2, exit_premium=1.0)  # loser
        s = t.get_summary()
        assert math.isclose(s.win_rate, 0.5)

    def test_max_drawdown_non_positive(self):
        t = OptionsPaperTrader()
        t.open_trade("A", "long_call", [100.0], "2026-06-20", 10.0, 10)
        s = t.get_summary()
        assert s.max_drawdown <= 0.0

    def test_open_positions_count(self):
        t = OptionsPaperTrader()
        t.open_trade("A", "long_call", [100.0], "2026-06-20", 2.0, 1)
        t.open_trade("B", "long_put", [200.0], "2026-06-20", 3.0, 1)
        s = t.get_summary()
        assert s.open_positions == 2
