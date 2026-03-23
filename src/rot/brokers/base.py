"""Abstract broker interface for ROT signal execution."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional


@dataclass
class OptionOrder:
    """A single options order instruction.

    Attributes:
        symbol:      Underlying ticker symbol (e.g. "AAPL").
        option_type: "call" or "put".
        strike:      Strike price as a Decimal.
        expiry:      Expiry date in YYYY-MM-DD format.
        quantity:    Number of contracts (each contract = 100 shares).
        action:      One of "buy_to_open", "buy_to_close",
                     "sell_to_open", "sell_to_close".
        order_type:  "limit" or "market".
        limit_price: Limit price per contract (required when order_type="limit").
    """

    symbol: str
    option_type: str        # "call" | "put"
    strike: Decimal
    expiry: str             # YYYY-MM-DD
    quantity: int
    action: str             # "buy_to_open" | "sell_to_close" | ...
    order_type: str         # "limit" | "market"
    limit_price: Optional[Decimal] = None


@dataclass
class OrderResult:
    """Result returned after submitting or querying an order.

    Attributes:
        order_id:   Broker-assigned order identifier.
        status:     "accepted", "filled", "partially_filled", "cancelled", "rejected".
        filled_qty: Number of contracts filled so far.
        avg_price:  Volume-weighted average fill price, or None if unfilled.
        timestamp:  ISO8601 timestamp when the broker processed the order.
    """

    order_id: str
    status: str
    filled_qty: int
    avg_price: Optional[Decimal]
    timestamp: str


@dataclass
class AccountInfo:
    """A snapshot of broker account state.

    Attributes:
        account_id:      Broker account identifier.
        buying_power:    Available capital for new positions.
        portfolio_value: Total market value of all positions plus cash.
        open_positions:  List of raw position dicts as returned by the broker.
    """

    account_id: str
    buying_power: Decimal
    portfolio_value: Decimal
    open_positions: List[dict] = field(default_factory=list)


class BrokerClient(ABC):
    """Abstract interface that all broker integrations must implement.

    All methods are async so implementations can use non-blocking HTTP clients
    (e.g. httpx.AsyncClient) without blocking the event loop.
    """

    @abstractmethod
    async def get_account(self) -> AccountInfo:
        """Return a current snapshot of the account."""

    @abstractmethod
    async def submit_order(self, order: OptionOrder) -> OrderResult:
        """Submit an options order and return the immediate broker response."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Request cancellation of an open order.

        Returns:
            True if the cancel request was accepted; False otherwise.
        """

    @abstractmethod
    async def get_option_chain(self, symbol: str, expiry: str) -> List[dict]:
        """Fetch the options chain for *symbol* at *expiry* (YYYY-MM-DD).

        Returns:
            A list of contract dicts with at minimum: strike, option_type,
            bid, ask, volume, open_interest, implied_volatility.
        """

    @abstractmethod
    async def get_positions(self) -> List[dict]:
        """Return all currently open positions.

        Returns:
            A list of position dicts with at minimum: symbol, qty, avg_entry_price,
            market_value, unrealized_pl.
        """
