"""Paper trading service — encapsulates portfolio and trade business logic.

Extracts business logic from paper_trading.py route handlers into a
testable service class with custom exception types.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class InsufficientBalanceError(Exception):
    """Raised when paper portfolio balance is too low to execute a trade."""


class NoPriceDataError(Exception):
    """Raised when no entry/exit price is available for a signal."""


class TradeNotFoundError(Exception):
    """Raised when a paper trade does not exist."""


class NotOwnerError(Exception):
    """Raised when a user tries to act on a trade they don't own."""


class TradeAlreadyClosedError(Exception):
    """Raised when attempting to close an already-closed trade."""


class SignalNotFoundError(Exception):
    """Raised when a referenced signal does not exist."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PaperTradingService:
    """Business logic for paper trading operations."""

    def __init__(self, db) -> None:
        self._db = db

    async def get_or_create_portfolio(self, user_id: str) -> dict:
        """Get existing portfolio or initialize a new one."""
        portfolio = await self._db.get_paper_portfolio(user_id)
        if not portfolio:
            await self._db.init_paper_portfolio(user_id)
            portfolio = await self._db.get_paper_portfolio(user_id)
        return portfolio

    async def execute_trade(
        self, user_id: str, signal_id: str, dollars: float
    ) -> dict:
        """Execute a paper trade on a signal.

        Returns:
            The created trade dict.

        Raises:
            InsufficientBalanceError: Portfolio balance < $10.
            SignalNotFoundError: Signal does not exist.
            NoPriceDataError: No price available for the signal.
        """
        portfolio = await self.get_or_create_portfolio(user_id)

        # Validate allocation
        dollars = min(max(dollars, 10.0), portfolio["balance"])
        if portfolio["balance"] < 10.0:
            raise InsufficientBalanceError("Insufficient paper balance")

        # Get signal
        signal = await self._db.get_signal(signal_id)
        if not signal:
            raise SignalNotFoundError(f"Signal {signal_id} not found")

        # Resolve entry price
        entry_price = await self._resolve_entry_price(signal_id, signal)
        if not entry_price or entry_price <= 0:
            raise NoPriceDataError("No price data for this signal")

        # Calculate quantity (fractional shares ok)
        quantity = round(dollars / entry_price, 4)

        trade = await self._db.create_paper_trade(
            user_id=user_id,
            signal_id=signal_id,
            ticker=signal["ticker"],
            stance=signal.get("stance", "unknown"),
            entry_price=entry_price,
            quantity=quantity,
            dollars=dollars,
        )
        return trade

    async def close_trade(self, user_id: str, trade_id: str) -> dict:
        """Close an open paper trade at the current price.

        Returns:
            The updated trade dict.

        Raises:
            TradeNotFoundError: Trade does not exist.
            NotOwnerError: Trade belongs to a different user.
            TradeAlreadyClosedError: Trade is already closed.
            NoPriceDataError: No current price available.
        """
        trade = await self._db.get_paper_trade(trade_id)
        if not trade:
            raise TradeNotFoundError(f"Trade {trade_id} not found")
        if trade["user_id"] != user_id:
            raise NotOwnerError("Not your trade")
        if trade["status"] != "open":
            raise TradeAlreadyClosedError("Trade already closed")

        # Resolve exit price
        exit_price = await self._resolve_exit_price(trade["signal_id"])
        if not exit_price:
            raise NoPriceDataError(
                "No current price available yet — try again later"
            )

        result = await self._db.close_paper_trade(trade_id, exit_price)
        return result

    async def get_portfolio_summary(self, user_id: str) -> dict:
        """Return portfolio and open position count.

        Returns:
            Dict with 'portfolio' and 'open_positions' keys.
        """
        portfolio = await self.get_or_create_portfolio(user_id)
        open_trades = await self._db.get_paper_trades(
            user_id, status="open", limit=50
        )
        return {
            "portfolio": portfolio,
            "open_positions": len(open_trades),
        }

    async def get_trades(
        self, user_id: str, status: str = "open", limit: int = 50
    ) -> list:
        """Return paper trades for a user filtered by status."""
        return await self._db.get_paper_trades(
            user_id, status=status, limit=limit
        )

    # ── Private helpers ──

    async def _resolve_entry_price(self, signal_id: str, signal: dict) -> float | None:
        """Try to find an entry price from performance data or market_data."""
        perf = await self._db.get_performance_for_signal(signal_id)
        entry_price = None
        if perf:
            entry_price = perf.get("price_at_signal")
        if not entry_price:
            md = signal.get("market_data", {})
            ticker = signal.get("ticker", "")
            if isinstance(md, dict) and ticker in md:
                entry_price = md[ticker].get("price") or md[ticker].get(
                    "currentPrice"
                )
        return entry_price

    async def _resolve_exit_price(self, signal_id: str) -> float | None:
        """Try to find a current exit price from performance data."""
        perf = await self._db.get_performance_for_signal(signal_id)
        if not perf:
            return None
        for field in (
            "price_1w",
            "price_1d",
            "price_4h",
            "price_1h",
            "price_at_signal",
        ):
            p = perf.get(field)
            if p and p > 0:
                return p
        return None
