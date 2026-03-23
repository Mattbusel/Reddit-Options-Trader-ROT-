"""
Portfolio Risk Monitor - tracks aggregate exposure across all open signal-derived positions.
Enforces position sizing, sector concentration limits, and Greeks exposure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple


@dataclass
class _PositionRecord:
    """Internal record for a single tracked position."""

    trade_id: str
    symbol: str
    delta: float
    cost: float
    sector: str
    opened_at: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )


class PortfolioRiskMonitor:
    """Tracks aggregate Greeks and sector concentration across open positions.

    The monitor enforces two primary limits:

    1. **Total delta**: The absolute sum of deltas across all open positions
       must not exceed ``max_total_delta``.  Delta measures directional
       exposure -- a value of 100 means the portfolio moves roughly $100 for
       every $1 move in the underlying.

    2. **Sector concentration**: No single sector may represent more than
       ``max_sector_pct`` of total deployed capital.  This prevents over-
       concentration in a single industry (e.g., 30% cap means no sector can
       account for more than 30% of total position cost).

    Args:
        max_total_delta:  Maximum allowable absolute portfolio delta (default: 100).
        max_sector_pct:   Maximum fraction of total cost any one sector may
                          represent (default: 0.30 = 30%).

    Example::

        monitor = PortfolioRiskMonitor(max_total_delta=50.0, max_sector_pct=0.25)

        approved, reason = monitor.can_add_position("AAPL", delta=10.0, cost=500.0)
        if approved:
            monitor.add_position("trade-001", "AAPL", 10.0, 500.0, "Technology")

        print(monitor.generate_report())
    """

    def __init__(
        self,
        max_total_delta: float = 100.0,
        max_sector_pct: float = 0.30,
    ) -> None:
        if max_total_delta <= 0:
            raise ValueError("max_total_delta must be positive")
        if not 0.0 < max_sector_pct <= 1.0:
            raise ValueError("max_sector_pct must be in (0, 1]")

        self.max_total_delta = max_total_delta
        self.max_sector_pct = max_sector_pct
        self._positions: Dict[str, _PositionRecord] = {}  # trade_id -> record

    # ------------------------------------------------------------------
    # Pre-trade checks
    # ------------------------------------------------------------------

    def can_add_position(
        self,
        symbol: str,
        delta: float,
        cost: float,
        sector: str = "Unknown",
    ) -> Tuple[bool, str]:
        """Check whether a proposed position can be added without breaching limits.

        Args:
            symbol: Ticker symbol of the underlying.
            delta:  Delta of the new position (positive = long/bullish,
                    negative = short/bearish).
            cost:   Total cost/premium of the position in USD.
            sector: GICS-style sector name (e.g. "Technology", "Health Care").

        Returns:
            ``(True, "approved")`` if the position passes all risk checks.
            ``(False, <reason string>)`` if any limit would be breached.
        """
        # --- Delta check ---
        new_total_delta = abs(self.total_delta() + delta)
        if new_total_delta > self.max_total_delta:
            return (
                False,
                (
                    f"Delta limit breach: adding delta={delta:.2f} to current "
                    f"total={self.total_delta():.2f} would reach "
                    f"{new_total_delta:.2f}, exceeding max_total_delta="
                    f"{self.max_total_delta:.2f}"
                ),
            )

        # --- Sector concentration check ---
        current_total_cost = self._total_cost()
        new_total_cost = current_total_cost + cost

        if new_total_cost > 0:
            sector_cost = self._sector_cost(sector) + cost
            new_pct = sector_cost / new_total_cost
            if new_pct > self.max_sector_pct:
                return (
                    False,
                    (
                        f"Sector concentration breach: adding ${cost:.2f} to "
                        f"sector '{sector}' would represent "
                        f"{new_pct * 100:.1f}% of portfolio cost, exceeding "
                        f"max_sector_pct={self.max_sector_pct * 100:.1f}%"
                    ),
                )

        # --- Cost sanity ---
        if cost < 0:
            return False, f"Invalid cost: {cost}. Cost must be non-negative."

        return True, "approved"

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------

    def add_position(
        self,
        trade_id: str,
        symbol: str,
        delta: float,
        cost: float,
        sector: str = "Unknown",
    ) -> None:
        """Register an open position.

        This method does NOT re-run risk checks.  Callers should call
        :meth:`can_add_position` first and only proceed if it returns
        ``(True, "approved")``.

        Args:
            trade_id: Unique identifier for this trade (used for removal).
            symbol:   Ticker symbol.
            delta:    Position delta.
            cost:     Total cost / premium paid in USD.
            sector:   GICS sector name.

        Raises:
            ValueError: If *trade_id* is already registered.
        """
        if trade_id in self._positions:
            raise ValueError(
                f"trade_id '{trade_id}' already exists. "
                "Use remove_position() before re-adding."
            )
        self._positions[trade_id] = _PositionRecord(
            trade_id=trade_id,
            symbol=symbol,
            delta=delta,
            cost=cost,
            sector=sector,
        )

    def remove_position(self, trade_id: str) -> bool:
        """De-register a closed position.

        Args:
            trade_id: Trade identifier previously passed to :meth:`add_position`.

        Returns:
            True if the position was found and removed; False if not found.
        """
        if trade_id not in self._positions:
            return False
        del self._positions[trade_id]
        return True

    # ------------------------------------------------------------------
    # Aggregate metrics
    # ------------------------------------------------------------------

    def total_delta(self) -> float:
        """Return the signed sum of deltas across all open positions."""
        return sum(p.delta for p in self._positions.values())

    def sector_concentration(self) -> Dict[str, float]:
        """Return a dict of sector -> fraction of total portfolio cost.

        Returns an empty dict when no positions are open.
        """
        total = self._total_cost()
        if total == 0:
            return {}
        buckets: Dict[str, float] = {}
        for pos in self._positions.values():
            buckets[pos.sector] = buckets.get(pos.sector, 0.0) + pos.cost
        return {sector: cost / total for sector, cost in sorted(buckets.items())}

    def generate_report(self) -> dict:
        """Generate a summary risk report for the current portfolio.

        Returns a dict with:
        - ``timestamp``:           ISO8601 generation time.
        - ``position_count``:      Number of open positions.
        - ``total_delta``:         Signed portfolio delta.
        - ``abs_delta``:           Absolute portfolio delta.
        - ``delta_utilisation``:   Fraction of ``max_total_delta`` consumed.
        - ``total_cost``:          Sum of all position costs.
        - ``sector_concentration``:  Per-sector cost fractions.
        - ``sector_breach``:       True if any sector exceeds ``max_sector_pct``.
        - ``delta_breach``:        True if abs_delta exceeds ``max_total_delta``.
        - ``positions``:           List of per-position detail dicts.
        """
        abs_delta = abs(self.total_delta())
        sector_conc = self.sector_concentration()
        sector_breach = any(v > self.max_sector_pct for v in sector_conc.values())
        return {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "position_count": len(self._positions),
            "total_delta": round(self.total_delta(), 4),
            "abs_delta": round(abs_delta, 4),
            "delta_utilisation": round(abs_delta / self.max_total_delta, 4),
            "total_cost": round(self._total_cost(), 2),
            "sector_concentration": {
                k: round(v, 4) for k, v in sector_conc.items()
            },
            "sector_breach": sector_breach,
            "delta_breach": abs_delta > self.max_total_delta,
            "limits": {
                "max_total_delta": self.max_total_delta,
                "max_sector_pct": self.max_sector_pct,
            },
            "positions": [
                {
                    "trade_id": p.trade_id,
                    "symbol": p.symbol,
                    "delta": p.delta,
                    "cost": p.cost,
                    "sector": p.sector,
                    "opened_at": p.opened_at,
                }
                for p in self._positions.values()
            ],
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _total_cost(self) -> float:
        return sum(p.cost for p in self._positions.values())

    def _sector_cost(self, sector: str) -> float:
        return sum(p.cost for p in self._positions.values() if p.sector == sector)

    def __len__(self) -> int:
        return len(self._positions)

    def __repr__(self) -> str:
        return (
            f"PortfolioRiskMonitor("
            f"positions={len(self._positions)}, "
            f"total_delta={self.total_delta():.2f}, "
            f"max_total_delta={self.max_total_delta})"
        )
