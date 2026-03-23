"""Position sizing and portfolio management for ROT.

Provides ``Position``, ``PortfolioManager``, and related utilities for
tracking open positions, computing P&L, assessing risk concentration,
and sizing new positions via Kelly criterion and volatility-adjusted logic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Position:
    """A single open position in the portfolio."""

    symbol: str
    entry_price: float
    current_price: float
    quantity: float
    position_type: str  # "long" or "short"
    entry_time: datetime
    option_type: str = "stock"  # "call", "put", or "stock"

    @property
    def market_value(self) -> float:
        """Signed market value of the position."""
        if self.position_type == "long":
            return self.current_price * self.quantity
        else:
            return -self.current_price * self.quantity

    @property
    def unrealized_pnl(self) -> float:
        """Unrealized P&L for this position."""
        if self.position_type == "long":
            return (self.current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.current_price) * self.quantity

    @property
    def delta(self) -> float:
        """Approximate delta for this position.

        Uses 1.0 for stocks (and long calls / short puts) and 0.5 for ATM
        options as a first-order approximation.
        """
        if self.option_type == "stock":
            base = 1.0
        else:
            base = 0.5  # ATM option approximation

        if self.position_type == "long":
            return base * self.quantity
        else:
            return -base * self.quantity


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class PortfolioManager:
    """Manages a collection of open and closed positions with P&L tracking."""

    def __init__(self) -> None:
        self._open_positions: dict[str, Position] = {}
        self._realized_pnl: float = 0.0
        self._closed_history: list[dict] = []

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------

    def add_position(self, position: Position) -> None:
        """Add or replace a position for the given symbol."""
        self._open_positions[position.symbol] = position

    def close_position(self, symbol: str, exit_price: float) -> float:
        """Close an open position and return the realized P&L.

        Args:
            symbol: The ticker symbol to close.
            exit_price: The price at which the position is closed.

        Returns:
            Realized P&L for the closed position.

        Raises:
            KeyError: If no open position exists for ``symbol``.
        """
        pos = self._open_positions.pop(symbol)
        if pos.position_type == "long":
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        self._realized_pnl += pnl
        self._closed_history.append(
            {
                "symbol": symbol,
                "pnl": pnl,
                "entry": pos.entry_price,
                "exit": exit_price,
            }
        )
        return pnl

    # ------------------------------------------------------------------
    # Portfolio-level metrics
    # ------------------------------------------------------------------

    def portfolio_delta(self) -> float:
        """Sum of all position deltas (portfolio-level directional exposure)."""
        return sum(pos.delta for pos in self._open_positions.values())

    def total_market_value(self) -> float:
        """Gross absolute market value of all open positions."""
        return sum(abs(pos.market_value) for pos in self._open_positions.values())

    def unrealized_pnl(self) -> float:
        """Total unrealized P&L across all open positions."""
        return sum(pos.unrealized_pnl for pos in self._open_positions.values())

    def realized_pnl(self) -> float:
        """Total realized P&L from all closed positions."""
        return self._realized_pnl

    def total_pnl(self) -> float:
        """Combined realized + unrealized P&L."""
        return self.realized_pnl() + self.unrealized_pnl()

    def position_concentration(self) -> dict[str, float]:
        """Return each symbol's share of total gross market value.

        Returns:
            Dict mapping symbol → fraction of total market value [0, 1].
        """
        total = self.total_market_value()
        if total == 0.0:
            return {sym: 0.0 for sym in self._open_positions}
        return {
            sym: abs(pos.market_value) / total
            for sym, pos in self._open_positions.items()
        }

    def open_positions(self) -> dict[str, Position]:
        """Return a view of open positions."""
        return dict(self._open_positions)

    # ------------------------------------------------------------------
    # Risk metrics
    # ------------------------------------------------------------------

    @staticmethod
    def max_drawdown(price_history: list[float]) -> float:
        """Compute the maximum drawdown from a sequence of portfolio values.

        Args:
            price_history: Ordered list of portfolio equity values.

        Returns:
            Maximum drawdown as a non-negative fraction (e.g. 0.25 = 25% DD).
            Returns 0.0 if the series has fewer than 2 points.
        """
        if len(price_history) < 2:
            return 0.0

        peak = price_history[0]
        max_dd = 0.0
        for value in price_history:
            if value > peak:
                peak = value
            if peak > 0.0:
                dd = (peak - value) / peak
                if dd > max_dd:
                    max_dd = dd
        return max_dd

    @staticmethod
    def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Kelly Criterion position fraction, clamped to [0, 0.25].

        Formula:
            f = win_rate / avg_loss - (1 - win_rate) / avg_win

        Args:
            win_rate: Historical win rate in [0, 1].
            avg_win: Average winning trade size (absolute, > 0).
            avg_loss: Average losing trade size (absolute, > 0).

        Returns:
            Recommended fraction of capital to risk, clamped to [0, 0.25].
        """
        if avg_win <= 0.0 or avg_loss <= 0.0:
            return 0.0
        raw = win_rate / avg_loss - (1.0 - win_rate) / avg_win
        return max(0.0, min(0.25, raw))

    @staticmethod
    def size_position(
        signal_strength: float,
        volatility: float,
        portfolio_value: float,
        max_risk_pct: float = 0.02,
    ) -> float:
        """Compute a volatility-adjusted position size in dollar terms.

        The baseline risk budget is ``portfolio_value * max_risk_pct``.  This
        is scaled by ``signal_strength`` (0–1) and divided by ``volatility``
        to reduce size in turbulent conditions.

        Args:
            signal_strength: Conviction of the trade signal in [0, 1].
            volatility: Annualised (or normalised) volatility of the asset.
            portfolio_value: Total portfolio equity in dollars.
            max_risk_pct: Maximum fraction of portfolio to risk per trade.

        Returns:
            Position size in dollars.  Returns 0.0 when inputs are degenerate.
        """
        if volatility <= 0.0 or portfolio_value <= 0.0:
            return 0.0
        risk_budget = portfolio_value * max_risk_pct
        return risk_budget * signal_strength / volatility
