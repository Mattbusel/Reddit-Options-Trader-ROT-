"""Options trade tax optimization utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List


@dataclass
class TradeRecord:
    symbol: str
    open_date: str
    close_date: str
    proceeds: float
    cost_basis: float
    quantity: int
    option_type: str


@dataclass
class TaxLot:
    symbol: str
    quantity: int
    cost_basis: float
    open_date: str
    is_short_term: bool


class TaxOptimizer:
    """Optimize tax treatment of options trades."""

    def __init__(
        self,
        tax_rate_short: float = 0.35,
        tax_rate_long: float = 0.15,
    ) -> None:
        self.tax_rate_short = tax_rate_short
        self.tax_rate_long = tax_rate_long

    # ------------------------------------------------------------------
    # Holding period classification
    # ------------------------------------------------------------------

    @staticmethod
    def classify_holding(open_date: str, close_date: str) -> bool:
        """Return True when the holding period is short-term (< 366 days)."""
        fmt = "%Y-%m-%d"
        try:
            d_open = datetime.strptime(open_date, fmt).date()
            d_close = datetime.strptime(close_date, fmt).date()
        except ValueError:
            return True  # Treat as short-term when dates are invalid
        return (d_close - d_open).days < 366

    # ------------------------------------------------------------------
    # Gain/loss computation
    # ------------------------------------------------------------------

    def compute_gain_loss(self, record: TradeRecord) -> dict:
        """Compute gain/loss, tax owed, and holding period for a trade record."""
        gain_loss = (record.proceeds - record.cost_basis) * record.quantity
        is_short = self.classify_holding(record.open_date, record.close_date)
        rate = self.tax_rate_short if is_short else self.tax_rate_long
        tax_owed = max(0.0, gain_loss * rate)

        fmt = "%Y-%m-%d"
        try:
            d_open = datetime.strptime(record.open_date, fmt).date()
            d_close = datetime.strptime(record.close_date, fmt).date()
            days = (d_close - d_open).days
        except ValueError:
            days = 0

        return {
            "gain_loss": gain_loss,
            "tax_owed": tax_owed,
            "is_short_term": is_short,
            "holding_days": days,
        }

    # ------------------------------------------------------------------
    # Tax-loss harvesting
    # ------------------------------------------------------------------

    def tax_loss_harvest(
        self, positions: List[TaxLot], target_loss: float
    ) -> List[TaxLot]:
        """
        Select lots with unrealised losses (negative cost_basis proxy) that together
        total at least target_loss. Here cost_basis > 0 implies a loss position.
        Lots are sorted by cost_basis descending (largest loss first).
        """
        loss_lots = [lot for lot in positions if lot.cost_basis < 0]
        loss_lots.sort(key=lambda l: l.cost_basis)  # most negative first

        selected: List[TaxLot] = []
        accumulated = 0.0
        for lot in loss_lots:
            selected.append(lot)
            accumulated += abs(lot.cost_basis) * lot.quantity
            if accumulated >= target_loss:
                break
        return selected

    # ------------------------------------------------------------------
    # Optimal lot selection
    # ------------------------------------------------------------------

    def optimal_lot_selection(
        self, lots: List[TaxLot], quantity: int
    ) -> List[TaxLot]:
        """
        Choose lots that minimise tax on a sale of *quantity* units.
        Strategy: prefer long-term lots, then highest cost basis (smallest gain).
        """
        # Sort: long-term before short-term, then by highest cost_basis descending
        sorted_lots = sorted(
            lots,
            key=lambda l: (l.is_short_term, -l.cost_basis),
        )
        selected: List[TaxLot] = []
        remaining = quantity
        for lot in sorted_lots:
            if remaining <= 0:
                break
            take = min(lot.quantity, remaining)
            if take == lot.quantity:
                selected.append(lot)
            else:
                selected.append(
                    TaxLot(
                        symbol=lot.symbol,
                        quantity=take,
                        cost_basis=lot.cost_basis,
                        open_date=lot.open_date,
                        is_short_term=lot.is_short_term,
                    )
                )
            remaining -= take
        return selected

    # ------------------------------------------------------------------
    # Wash-sale check
    # ------------------------------------------------------------------

    def wash_sale_check(
        self, closed_trade: TradeRecord, open_trades: List[TradeRecord]
    ) -> bool:
        """
        Return True if the same symbol was traded within 30 days before or after
        the close date of closed_trade (wash-sale rule).
        """
        fmt = "%Y-%m-%d"
        try:
            close_dt = datetime.strptime(closed_trade.close_date, fmt).date()
        except ValueError:
            return False

        for trade in open_trades:
            if trade.symbol != closed_trade.symbol:
                continue
            for ds in (trade.open_date, trade.close_date):
                try:
                    dt = datetime.strptime(ds, fmt).date()
                    if abs((dt - close_dt).days) <= 30:
                        return True
                except ValueError:
                    continue
        return False

    # ------------------------------------------------------------------
    # Annual summary
    # ------------------------------------------------------------------

    def annual_summary(self, records: List[TradeRecord]) -> dict:
        """Compute annual tax summary across all trade records."""
        total_gains = 0.0
        total_losses = 0.0
        short_term_gains = 0.0
        long_term_gains = 0.0
        estimated_tax = 0.0

        for record in records:
            result = self.compute_gain_loss(record)
            gl = result["gain_loss"]
            if gl >= 0:
                total_gains += gl
                if result["is_short_term"]:
                    short_term_gains += gl
                else:
                    long_term_gains += gl
            else:
                total_losses += abs(gl)
            estimated_tax += result["tax_owed"]

        return {
            "total_gains": total_gains,
            "total_losses": total_losses,
            "net_pnl": total_gains - total_losses,
            "estimated_tax": estimated_tax,
            "short_term_gains": short_term_gains,
            "long_term_gains": long_term_gains,
        }
