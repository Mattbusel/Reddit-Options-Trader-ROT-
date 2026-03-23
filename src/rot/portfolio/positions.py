"""Options Position Tracker for the ROT platform.

Maintains an in-memory ledger of multi-leg options positions, supports
mark-to-market updates, computes portfolio Greeks, and identifies positions
approaching expiry.

Typical usage::

    from datetime import date
    from rot.portfolio.positions import (
        OptionLeg, OptionsPosition, PositionTracker, LegSide,
    )

    tracker = PositionTracker()

    leg = OptionLeg(
        contract="AAPL240119C00180000",
        side=LegSide.LONG,
        strike=180.0,
        expiry=date(2024, 1, 19),
        premium=5.50,
        quantity=2,
    )
    pos = OptionsPosition(
        symbol="AAPL",
        strategy="long_call",
        legs=[leg],
        entry_date=date(2024, 1, 2),
        expiry=date(2024, 1, 19),
        quantity=2,
        entry_cost=1100.0,
    )

    tracker.add_position(pos)
    tracker.mark_to_market({"AAPL240119C00180000": 6.50})

    greeks = tracker.portfolio_greeks()
    print(greeks.total_delta)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LegSide(str, Enum):
    """Whether a leg is long (bought) or short (sold)."""
    LONG = "long"
    SHORT = "short"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OptionLeg:
    """One leg of a multi-leg options position.

    Attributes:
        contract:  OCC option symbol (e.g. ``"AAPL240119C00180000"``).
        side:      :attr:`LegSide.LONG` or :attr:`LegSide.SHORT`.
        strike:    Strike price in USD.
        expiry:    Expiry date.
        premium:   Premium paid/received per share (USD).
        quantity:  Number of contracts (1 contract = 100 shares).
        delta:     Leg-level Black-Scholes delta (optional).
        gamma:     Leg-level gamma (optional).
        theta:     Leg-level theta per day (optional).
        vega:      Leg-level vega (optional).
    """
    contract: str
    side: LegSide
    strike: float
    expiry: date
    premium: float
    quantity: int = 1
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    @property
    def signed_delta(self) -> float:
        """Delta sign-adjusted for long/short: short legs negate delta."""
        return self.delta if self.side == LegSide.LONG else -self.delta

    @property
    def signed_theta(self) -> float:
        return self.theta if self.side == LegSide.LONG else -self.theta

    @property
    def notional(self) -> float:
        """Total premium in/out for the leg (positive = debit, negative = credit)."""
        multiplier = 1 if self.side == LegSide.LONG else -1
        return multiplier * self.premium * self.quantity * 100


@dataclass
class OptionsPosition:
    """A complete options position (possibly multi-leg).

    Attributes:
        symbol:         Underlying ticker (e.g. ``"AAPL"``).
        strategy:       Strategy label (e.g. ``"bull_call_spread"``).
        legs:           List of :class:`OptionLeg` objects.
        entry_date:     Date the position was opened.
        expiry:         Expiry date of the position (typically the latest leg).
        quantity:       Number of position units (multiplies each leg's quantity).
        entry_cost:     Total debit paid at entry (USD, positive = debit).
        current_value:  Current mark-to-market value (USD).
        delta:          Position-level delta (sum of signed leg deltas).
        theta_decay:    Cumulative theta decay collected (USD).
    """
    symbol: str
    strategy: str
    legs: List[OptionLeg]
    entry_date: date
    expiry: date
    quantity: int = 1
    entry_cost: float = 0.0
    current_value: float = 0.0
    delta: float = 0.0
    theta_decay: float = 0.0

    # Internal tracking
    _realized_pnl: float = field(default=0.0, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    # ----------------------------------------------------------------
    @property
    def unrealized_pnl(self) -> float:
        """Current value minus entry cost."""
        return self.current_value - self.entry_cost

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def delta_adjusted_pnl(self) -> float:
        """realized_pnl + unrealized_pnl + theta_decay_collected."""
        return self._realized_pnl + self.unrealized_pnl + self.theta_decay

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def days_to_expiry(self) -> int:
        """Calendar days remaining until expiry (from today)."""
        today = datetime.now(timezone.utc).date()
        return max(0, (self.expiry - today).days)

    def mark(self, value: float) -> None:
        """Update current market value and accumulate daily theta decay."""
        old_value = self.current_value
        self.current_value = value
        # Estimate theta decay as reduction in value on short legs
        decay = sum(
            leg.signed_theta * leg.quantity * 100
            for leg in self.legs
        )
        self.theta_decay += decay

    def total_leg_delta(self) -> float:
        """Sum of signed deltas across all legs, scaled by quantity."""
        return sum(leg.signed_delta * leg.quantity * 100 for leg in self.legs) * self.quantity

    def total_leg_gamma(self) -> float:
        multiplier = 1.0
        return sum(leg.gamma * leg.quantity * 100 for leg in self.legs) * multiplier * self.quantity

    def total_leg_theta(self) -> float:
        return sum(leg.signed_theta * leg.quantity * 100 for leg in self.legs) * self.quantity

    def total_leg_vega(self) -> float:
        return sum(
            (leg.vega if leg.side == LegSide.LONG else -leg.vega) * leg.quantity * 100
            for leg in self.legs
        ) * self.quantity


@dataclass
class PortfolioGreeks:
    """Aggregated Greeks across all open positions.

    Attributes:
        total_delta: Net delta of the portfolio.
        total_gamma: Net gamma of the portfolio.
        total_theta: Net theta of the portfolio (daily decay).
        total_vega:  Net vega of the portfolio.
    """
    total_delta: float = 0.0
    total_gamma: float = 0.0
    total_theta: float = 0.0
    total_vega: float = 0.0


# ---------------------------------------------------------------------------
# PositionTracker
# ---------------------------------------------------------------------------

class PositionTracker:
    """In-memory ledger of options positions.

    All operations are synchronous and thread-safe at the Python GIL level.
    Positions are keyed by ``symbol``; if multiple strategies trade the same
    underlying simultaneously use :meth:`add_position` with distinct position
    objects — only the most recently added position is tracked per symbol key.
    For multi-position-per-symbol use cases, subclass and override ``_key``.
    """

    def __init__(self) -> None:
        self._positions: Dict[str, OptionsPosition] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_position(self, position: OptionsPosition) -> None:
        """Add or replace a position in the ledger.

        Args:
            position: The :class:`OptionsPosition` to track.
        """
        key = self._key(position)
        self._positions[key] = position
        log.info("Added position: %s (%s)", position.symbol, position.strategy)

    def close_position(self, symbol: str, exit_value: Optional[float] = None) -> OptionsPosition:
        """Mark a position as closed and remove it from the active ledger.

        Args:
            symbol:     Underlying ticker symbol used as the ledger key.
            exit_value: Final mark-to-market value at close.  If ``None``,
                        uses the position's current ``current_value``.

        Returns:
            The closed :class:`OptionsPosition`.

        Raises:
            KeyError: If *symbol* is not in the active ledger.
        """
        pos = self._positions.pop(symbol)
        if exit_value is not None:
            pos.current_value = exit_value
        pos._realized_pnl = pos.current_value - pos.entry_cost
        pos._closed = True
        log.info("Closed position: %s  realized_pnl=%.2f", symbol, pos._realized_pnl)
        return pos

    def get_position(self, symbol: str) -> Optional[OptionsPosition]:
        """Return the active position for *symbol*, or ``None``."""
        return self._positions.get(symbol)

    @property
    def open_positions(self) -> List[OptionsPosition]:
        """All currently tracked (open) positions."""
        return list(self._positions.values())

    # ------------------------------------------------------------------
    # Mark-to-market
    # ------------------------------------------------------------------

    def mark_to_market(self, prices: Dict[str, float]) -> None:
        """Update current values for all positions.

        Args:
            prices: Mapping of contract symbol → current mid-market price per
                    share (USD).  Only leg contracts present in *prices* are
                    updated; missing contracts keep their previous value.

        The position's ``current_value`` is recomputed as the sum of each
        leg's notional at the new market price.
        """
        for pos in self._positions.values():
            new_value = 0.0
            all_updated = True
            for leg in pos.legs:
                price = prices.get(leg.contract)
                if price is None:
                    all_updated = False
                    # Keep the leg's existing premium contribution
                    side_mult = 1 if leg.side == LegSide.LONG else -1
                    new_value += side_mult * leg.premium * leg.quantity * 100
                else:
                    side_mult = 1 if leg.side == LegSide.LONG else -1
                    new_value += side_mult * price * leg.quantity * 100
            if all_updated or new_value != 0.0:
                pos.mark(new_value * pos.quantity)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def positions_at_risk(self, days_threshold: int = 7) -> List[OptionsPosition]:
        """Return positions with fewer than *days_threshold* days to expiry.

        Args:
            days_threshold: Maximum remaining days to consider "at risk".
                            Default is 7 calendar days.

        Returns:
            List of open positions within *days_threshold* days of expiry.
        """
        return [p for p in self._positions.values() if p.days_to_expiry <= days_threshold]

    def portfolio_greeks(self) -> PortfolioGreeks:
        """Aggregate Greeks across all open positions.

        Returns:
            :class:`PortfolioGreeks` summed over all open positions.
        """
        pg = PortfolioGreeks()
        for pos in self._positions.values():
            pg.total_delta += pos.total_leg_delta()
            pg.total_gamma += pos.total_leg_gamma()
            pg.total_theta += pos.total_leg_theta()
            pg.total_vega += pos.total_leg_vega()
        return pg

    def portfolio_summary(self) -> Dict:
        """Return a dict suitable for JSON serialisation / the REST handler."""
        greeks = self.portfolio_greeks()
        return {
            "open_positions": len(self._positions),
            "total_delta": greeks.total_delta,
            "total_gamma": greeks.total_gamma,
            "total_theta": greeks.total_theta,
            "total_vega": greeks.total_vega,
            "total_unrealized_pnl": sum(p.unrealized_pnl for p in self._positions.values()),
            "total_theta_decay": sum(p.theta_decay for p in self._positions.values()),
            "positions": [
                {
                    "symbol": p.symbol,
                    "strategy": p.strategy,
                    "days_to_expiry": p.days_to_expiry,
                    "entry_cost": p.entry_cost,
                    "current_value": p.current_value,
                    "unrealized_pnl": p.unrealized_pnl,
                    "delta_adjusted_pnl": p.delta_adjusted_pnl,
                    "num_legs": len(p.legs),
                }
                for p in self._positions.values()
            ],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(position: OptionsPosition) -> str:
        return position.symbol


# ---------------------------------------------------------------------------
# HTML page helper (GET /portfolio/positions)
# ---------------------------------------------------------------------------

def render_positions_page(tracker: PositionTracker) -> str:
    """Render an HTML page with position cards and portfolio Greeks.

    Returns:
        A self-contained HTML string suitable for returning from a FastAPI
        or Flask route handler.
    """
    import html as _html

    summary = tracker.portfolio_summary()
    greeks = tracker.portfolio_greeks()

    css = """
body { font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }
h1   { color: #38bdf8; margin-bottom: 4px; }
.subtitle { color: #94a3b8; font-size: 0.9rem; margin-bottom: 24px; }
.greeks { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }
.g-card { background: #1e293b; border-radius: 8px; padding: 16px; text-align: center; }
.g-label { color: #94a3b8; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; }
.g-value { font-size: 1.5rem; font-weight: bold; color: #38bdf8; margin-top: 6px; }
.positions { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
.p-card { background: #1e293b; border-radius: 10px; padding: 20px; }
.p-symbol { font-size: 1.2rem; font-weight: bold; color: #f8fafc; }
.p-strategy { color: #94a3b8; font-size: 0.85rem; margin-bottom: 12px; }
.p-row { display: flex; justify-content: space-between; margin: 4px 0; font-size: 0.88rem; }
.p-key { color: #94a3b8; }
.positive { color: #4ade80; }
.negative { color: #f87171; }
.at-risk { border: 2px solid #ef4444; }
"""

    def g_card(label: str, val: float) -> str:
        return (
            f'<div class="g-card">'
            f'<div class="g-label">{_html.escape(label)}</div>'
            f'<div class="g-value">{val:+.4f}</div>'
            f"</div>"
        )

    greeks_html = (
        g_card("Total Delta", greeks.total_delta)
        + g_card("Total Gamma", greeks.total_gamma)
        + g_card("Total Theta", greeks.total_theta)
        + g_card("Total Vega", greeks.total_vega)
    )

    pos_cards = ""
    for p in summary["positions"]:
        pnl = p["unrealized_pnl"]
        pnl_class = "positive" if pnl >= 0 else "negative"
        at_risk = p["days_to_expiry"] <= 7
        card_class = "p-card at-risk" if at_risk else "p-card"

        pos_cards += f"""
<div class="{card_class}">
  <div class="p-symbol">{_html.escape(p["symbol"])}</div>
  <div class="p-strategy">{_html.escape(p["strategy"])}</div>
  <div class="p-row"><span class="p-key">Days to Expiry</span><span>{"&#x26A0; " if at_risk else ""}{p["days_to_expiry"]}</span></div>
  <div class="p-row"><span class="p-key">Entry Cost</span><span>${p["entry_cost"]:,.2f}</span></div>
  <div class="p-row"><span class="p-key">Current Value</span><span>${p["current_value"]:,.2f}</span></div>
  <div class="p-row"><span class="p-key">Unrealised PnL</span><span class="{pnl_class}">${pnl:+,.2f}</span></div>
  <div class="p-row"><span class="p-key">Delta-Adj PnL</span><span class="{pnl_class}">${p["delta_adjusted_pnl"]:+,.2f}</span></div>
  <div class="p-row"><span class="p-key">Legs</span><span>{p["num_legs"]}</span></div>
</div>"""

    total_upnl = summary["total_unrealized_pnl"]
    upnl_class = "positive" if total_upnl >= 0 else "negative"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ROT — Portfolio Positions</title>
<style>{css}</style>
</head>
<body>
<h1>ROT Portfolio Positions</h1>
<div class="subtitle">
  {summary["open_positions"]} open position(s) &nbsp;|&nbsp;
  Total Unrealised PnL: <span class="{upnl_class}">${total_upnl:+,.2f}</span>
</div>

<h2>Portfolio Greeks</h2>
<div class="greeks">
{greeks_html}
</div>

<h2>Positions</h2>
<div class="positions">
{pos_cards if pos_cards else '<p style="color:#94a3b8">No open positions.</p>'}
</div>
</body>
</html>"""
