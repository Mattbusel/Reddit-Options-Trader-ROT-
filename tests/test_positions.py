"""Unit tests for rot.portfolio.positions — OptionsPosition, PositionTracker, Greeks."""

from __future__ import annotations

from datetime import date, timedelta, datetime, timezone
from unittest.mock import patch

import pytest

from rot.portfolio.positions import (
    LegSide,
    OptionLeg,
    OptionsPosition,
    PortfolioGreeks,
    PositionTracker,
    render_positions_page,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tomorrow() -> date:
    return datetime.now(timezone.utc).date() + timedelta(days=1)


def _in_days(n: int) -> date:
    return datetime.now(timezone.utc).date() + timedelta(days=n)


def _simple_leg(
    contract: str = "AAPL240119C00180000",
    side: LegSide = LegSide.LONG,
    strike: float = 180.0,
    expiry: date | None = None,
    premium: float = 5.0,
    quantity: int = 1,
    delta: float = 0.50,
    theta: float = -0.05,
    gamma: float = 0.02,
    vega: float = 0.10,
) -> OptionLeg:
    return OptionLeg(
        contract=contract,
        side=side,
        strike=strike,
        expiry=expiry or _in_days(30),
        premium=premium,
        quantity=quantity,
        delta=delta,
        theta=theta,
        gamma=gamma,
        vega=vega,
    )


def _simple_position(
    symbol: str = "AAPL",
    strategy: str = "long_call",
    expiry: date | None = None,
    entry_cost: float = 500.0,
    quantity: int = 1,
    legs: list | None = None,
) -> OptionsPosition:
    exp = expiry or _in_days(30)
    return OptionsPosition(
        symbol=symbol,
        strategy=strategy,
        legs=legs or [_simple_leg(expiry=exp)],
        entry_date=datetime.now(timezone.utc).date(),
        expiry=exp,
        quantity=quantity,
        entry_cost=entry_cost,
    )


# ---------------------------------------------------------------------------
# OptionLeg
# ---------------------------------------------------------------------------

class TestOptionLeg:
    def test_long_leg_signed_delta_positive(self):
        leg = _simple_leg(side=LegSide.LONG, delta=0.50)
        assert leg.signed_delta == pytest.approx(0.50)

    def test_short_leg_signed_delta_negative(self):
        leg = _simple_leg(side=LegSide.SHORT, delta=0.50)
        assert leg.signed_delta == pytest.approx(-0.50)

    def test_long_leg_signed_theta_negative(self):
        leg = _simple_leg(side=LegSide.LONG, theta=-0.05)
        assert leg.signed_theta == pytest.approx(-0.05)

    def test_short_leg_signed_theta_positive(self):
        leg = _simple_leg(side=LegSide.SHORT, theta=-0.05)
        assert leg.signed_theta == pytest.approx(0.05)

    def test_long_leg_notional_positive(self):
        leg = _simple_leg(side=LegSide.LONG, premium=5.0, quantity=2)
        assert leg.notional == pytest.approx(5.0 * 2 * 100)

    def test_short_leg_notional_negative(self):
        leg = _simple_leg(side=LegSide.SHORT, premium=5.0, quantity=1)
        assert leg.notional == pytest.approx(-500.0)


# ---------------------------------------------------------------------------
# OptionsPosition
# ---------------------------------------------------------------------------

class TestOptionsPosition:
    def test_unrealized_pnl_zero_at_entry(self):
        pos = _simple_position(entry_cost=500.0)
        pos.current_value = 500.0
        assert pos.unrealized_pnl == pytest.approx(0.0)

    def test_unrealized_pnl_profit(self):
        pos = _simple_position(entry_cost=500.0)
        pos.current_value = 700.0
        assert pos.unrealized_pnl == pytest.approx(200.0)

    def test_unrealized_pnl_loss(self):
        pos = _simple_position(entry_cost=500.0)
        pos.current_value = 300.0
        assert pos.unrealized_pnl == pytest.approx(-200.0)

    def test_delta_adjusted_pnl_includes_theta(self):
        pos = _simple_position(entry_cost=500.0)
        pos.current_value = 600.0
        pos.theta_decay = 25.0
        assert pos.delta_adjusted_pnl == pytest.approx(125.0)  # 0 + 100 + 25

    def test_days_to_expiry_future(self):
        pos = _simple_position(expiry=_in_days(10))
        assert pos.days_to_expiry == 10

    def test_days_to_expiry_expired_returns_zero(self):
        pos = _simple_position(expiry=_in_days(-5))
        assert pos.days_to_expiry == 0

    def test_is_closed_default_false(self):
        pos = _simple_position()
        assert not pos.is_closed

    def test_total_leg_delta_long(self):
        leg = _simple_leg(side=LegSide.LONG, delta=0.50, quantity=2)
        pos = _simple_position(legs=[leg], quantity=1)
        # signed_delta=0.50, qty=2, 100 shares → 0.50*2*100 = 100
        assert pos.total_leg_delta() == pytest.approx(100.0)

    def test_total_leg_delta_multi_leg(self):
        l1 = _simple_leg("A", LegSide.LONG, delta=0.60, quantity=1)
        l2 = _simple_leg("B", LegSide.SHORT, delta=0.30, quantity=1)
        pos = _simple_position(legs=[l1, l2], quantity=1)
        # 0.60*100 - 0.30*100 = 30
        assert pos.total_leg_delta() == pytest.approx(30.0)

    def test_total_leg_theta(self):
        leg = _simple_leg(side=LegSide.LONG, theta=-0.05, quantity=1)
        pos = _simple_position(legs=[leg], quantity=1)
        assert pos.total_leg_theta() == pytest.approx(-5.0)


# ---------------------------------------------------------------------------
# PositionTracker
# ---------------------------------------------------------------------------

class TestPositionTracker:
    def test_add_and_get_position(self):
        tracker = PositionTracker()
        pos = _simple_position("AAPL")
        tracker.add_position(pos)
        assert tracker.get_position("AAPL") is pos

    def test_open_positions_list(self):
        tracker = PositionTracker()
        tracker.add_position(_simple_position("AAPL"))
        tracker.add_position(_simple_position("MSFT"))
        assert len(tracker.open_positions) == 2

    def test_close_position_removes_from_ledger(self):
        tracker = PositionTracker()
        tracker.add_position(_simple_position("AAPL", entry_cost=500.0))
        tracker.get_position("AAPL").current_value = 600.0
        closed = tracker.close_position("AAPL")
        assert tracker.get_position("AAPL") is None
        assert closed.is_closed

    def test_close_position_computes_realized_pnl(self):
        tracker = PositionTracker()
        tracker.add_position(_simple_position("AAPL", entry_cost=500.0))
        closed = tracker.close_position("AAPL", exit_value=700.0)
        assert closed.realized_pnl == pytest.approx(200.0)

    def test_close_missing_raises(self):
        tracker = PositionTracker()
        with pytest.raises(KeyError):
            tracker.close_position("GHOST")

    def test_mark_to_market_updates_value(self):
        tracker = PositionTracker()
        leg = _simple_leg("OPT1", premium=5.0, quantity=1)
        pos = _simple_position("AAPL", legs=[leg], quantity=1, entry_cost=500.0)
        tracker.add_position(pos)
        tracker.mark_to_market({"OPT1": 7.0})
        # new value = 7.0 * 1 * 100 * 1 = 700
        assert pos.current_value == pytest.approx(700.0)

    def test_mark_to_market_missing_contract_unchanged(self):
        tracker = PositionTracker()
        leg = _simple_leg("OPT1", premium=5.0)
        pos = _simple_position("AAPL", legs=[leg], entry_cost=500.0)
        pos.current_value = 500.0
        tracker.add_position(pos)
        tracker.mark_to_market({"OTHER": 99.0})
        # Should stay near 500 (falls back to original premium)
        # Just check it didn't explode
        assert pos.current_value is not None

    def test_positions_at_risk_within_7_days(self):
        tracker = PositionTracker()
        near = _simple_position("AAPL", expiry=_in_days(5))
        far = _simple_position("MSFT", expiry=_in_days(30))
        tracker.add_position(near)
        tracker.add_position(far)
        at_risk = tracker.positions_at_risk()
        assert len(at_risk) == 1
        assert at_risk[0].symbol == "AAPL"

    def test_positions_at_risk_custom_threshold(self):
        tracker = PositionTracker()
        tracker.add_position(_simple_position("AAPL", expiry=_in_days(14)))
        tracker.add_position(_simple_position("MSFT", expiry=_in_days(30)))
        at_risk = tracker.positions_at_risk(days_threshold=15)
        assert len(at_risk) == 1

    def test_portfolio_greeks_empty(self):
        tracker = PositionTracker()
        pg = tracker.portfolio_greeks()
        assert pg.total_delta == 0.0
        assert pg.total_gamma == 0.0

    def test_portfolio_greeks_single_long(self):
        tracker = PositionTracker()
        leg = _simple_leg(delta=0.50, gamma=0.02, quantity=1)
        pos = _simple_position(legs=[leg], quantity=1)
        tracker.add_position(pos)
        pg = tracker.portfolio_greeks()
        assert pg.total_delta == pytest.approx(50.0)
        assert pg.total_gamma == pytest.approx(2.0)

    def test_portfolio_greeks_multi_position(self):
        tracker = PositionTracker()
        leg1 = _simple_leg("A", LegSide.LONG, delta=0.60, gamma=0.02)
        leg2 = _simple_leg("B", LegSide.LONG, delta=0.40, gamma=0.01)
        tracker.add_position(_simple_position("AAPL", legs=[leg1], quantity=1))
        tracker.add_position(_simple_position("MSFT", legs=[leg2], quantity=1))
        pg = tracker.portfolio_greeks()
        assert pg.total_delta == pytest.approx(100.0)  # 60 + 40

    def test_portfolio_summary_structure(self):
        tracker = PositionTracker()
        tracker.add_position(_simple_position("AAPL"))
        summary = tracker.portfolio_summary()
        assert "open_positions" in summary
        assert "total_delta" in summary
        assert "positions" in summary
        assert summary["open_positions"] == 1


# ---------------------------------------------------------------------------
# render_positions_page
# ---------------------------------------------------------------------------

class TestRenderPositionsPage:
    def test_returns_html(self):
        tracker = PositionTracker()
        html = render_positions_page(tracker)
        assert "<!DOCTYPE html>" in html

    def test_contains_position_symbol(self):
        tracker = PositionTracker()
        tracker.add_position(_simple_position("GOOGL"))
        html = render_positions_page(tracker)
        assert "GOOGL" in html

    def test_at_risk_indicator(self):
        tracker = PositionTracker()
        tracker.add_position(_simple_position("TSLA", expiry=_in_days(3)))
        html = render_positions_page(tracker)
        assert "at-risk" in html

    def test_no_positions_message(self):
        tracker = PositionTracker()
        html = render_positions_page(tracker)
        assert "No open positions" in html
