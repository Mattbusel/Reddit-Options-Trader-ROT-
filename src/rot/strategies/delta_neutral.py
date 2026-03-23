"""Delta-neutral strategy construction and maintenance."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class DeltaPosition:
    """A single position with Greek values."""
    symbol: str
    delta: float
    gamma: float
    quantity: float
    price: float


class DeltaNeutralStrategy:
    """Constructs and maintains a delta-neutral portfolio."""

    def __init__(
        self,
        target_delta: float = 0.0,
        rebalance_threshold: float = 0.1,
    ) -> None:
        self.target_delta = target_delta
        self.rebalance_threshold = rebalance_threshold
        self._positions: List[DeltaPosition] = []

    def add_position(self, position: DeltaPosition) -> None:
        """Add a position to the portfolio."""
        self._positions.append(position)

    def portfolio_delta(self) -> float:
        """Total portfolio delta = sum of delta * quantity."""
        return sum(p.delta * p.quantity for p in self._positions)

    def portfolio_gamma(self) -> float:
        """Total portfolio gamma = sum of gamma * quantity."""
        return sum(p.gamma * p.quantity for p in self._positions)

    def needs_rebalance(self) -> bool:
        """True when |portfolio_delta − target_delta| exceeds threshold."""
        return abs(self.portfolio_delta() - self.target_delta) > self.rebalance_threshold

    def compute_hedge(self, stock_price: float) -> Dict:
        """
        Compute the stock trade required to neutralise portfolio delta.

        The underlying stock has delta = 1 per share, so we need to buy/sell
        a quantity equal to (target_delta − portfolio_delta).
        """
        excess_delta = self.portfolio_delta() - self.target_delta
        quantity = -excess_delta  # shares to trade (negative = sell)
        cost = quantity * stock_price
        action = "buy" if quantity > 0 else "sell" if quantity < 0 else "none"
        return {
            "action": action,
            "quantity": abs(quantity),
            "cost": abs(cost),
        }

    def apply_hedge(self, stock_price: float) -> None:
        """Add a synthetic stock position to neutralise delta."""
        excess_delta = self.portfolio_delta() - self.target_delta
        hedge_qty = -excess_delta
        if abs(hedge_qty) < 1e-10:
            return
        hedge = DeltaPosition(
            symbol="_HEDGE",
            delta=1.0,
            gamma=0.0,
            quantity=hedge_qty,
            price=stock_price,
        )
        self._positions.append(hedge)

    def delta_decay(self, time_dt: float) -> None:
        """
        Approximate delta change over time dt via gamma.

        Δdelta ≈ gamma * delta_S * sqrt(dt)  where delta_S = 0.01 * price.
        """
        for pos in self._positions:
            delta_s = 0.01 * pos.price
            pos.delta += pos.gamma * delta_s * math.sqrt(time_dt)

    def pnl_attribution(self) -> Dict:
        """Rough P&L attribution breakdown."""
        delta_pnl = self.portfolio_delta() * 0.01  # 1% move assumption
        gamma_pnl = 0.5 * self.portfolio_gamma() * (0.01 ** 2)
        theta_pnl = -0.01 * len(self._positions)  # rough theta proxy
        total = delta_pnl + gamma_pnl + theta_pnl
        return {
            "delta_pnl": delta_pnl,
            "gamma_pnl": gamma_pnl,
            "theta_pnl": theta_pnl,
            "total": total,
        }

    def stress_delta(self, price_change_pct: float) -> float:
        """Estimated portfolio delta after a price move using gamma."""
        current_delta = self.portfolio_delta()
        gamma = self.portfolio_gamma()
        # Approximate: new_delta ≈ current_delta + gamma * price_change
        return current_delta + gamma * price_change_pct
