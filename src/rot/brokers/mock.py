"""Mock broker for unit testing and local simulation.

Provides a fully in-memory :class:`MockBroker` that:

* Tracks submitted orders and open positions.
* Simulates order fills with optional configurable slippage.
* Enforces basic buying-power checks.
* Allows injecting fill delays and partial fills for stress-testing.

No network calls are made.
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from rot.brokers.base import AccountInfo, BrokerClient, OptionOrder, OrderResult


@dataclass
class _Position:
    """Internal representation of a mock open position."""

    order_id: str
    symbol: str
    option_type: str
    strike: Decimal
    expiry: str
    action: str
    quantity: int
    avg_price: Decimal


class MockBroker(BrokerClient):
    """In-memory mock broker for testing and paper-simulation.

    Args:
        initial_buying_power: Starting available capital (default: $100,000).
        slippage_pct:         Fraction added to limit price on fills to model
                              adverse execution (default: 0.01 = 1%).
        fill_rate:            Probability that a submitted order is filled
                              immediately (default: 1.0 = always fill).
        random_seed:          Seed for the PRNG used in slippage / partial fills.
                              Set a fixed value for deterministic tests.
    """

    def __init__(
        self,
        initial_buying_power: Decimal = Decimal("100000"),
        slippage_pct: float = 0.01,
        fill_rate: float = 1.0,
        random_seed: Optional[int] = None,
    ) -> None:
        self._buying_power = initial_buying_power
        self._slippage_pct = slippage_pct
        self._fill_rate = fill_rate
        self._rng = random.Random(random_seed)
        self._orders: Dict[str, OrderResult] = {}
        self._positions: Dict[str, _Position] = {}  # order_id -> position
        self._account_id = f"mock-{uuid.uuid4().hex[:8]}"

    # ------------------------------------------------------------------
    # BrokerClient implementation
    # ------------------------------------------------------------------

    async def get_account(self) -> AccountInfo:
        portfolio_value = self._buying_power + self._portfolio_market_value()
        return AccountInfo(
            account_id=self._account_id,
            buying_power=self._buying_power,
            portfolio_value=portfolio_value,
            open_positions=await self.get_positions(),
        )

    async def submit_order(self, order: OptionOrder) -> OrderResult:
        """Simulate order submission with optional slippage and fill rate."""
        order_id = str(uuid.uuid4())
        timestamp = datetime.now(tz=timezone.utc).isoformat()

        # Determine fill
        will_fill = self._rng.random() < self._fill_rate

        if will_fill:
            fill_price = self._compute_fill_price(order)
            cost = fill_price * order.quantity * 100  # 1 contract = 100 shares

            if order.action in ("buy_to_open",) and cost > self._buying_power:
                result = OrderResult(
                    order_id=order_id,
                    status="rejected",
                    filled_qty=0,
                    avg_price=None,
                    timestamp=timestamp,
                )
                self._orders[order_id] = result
                return result

            # Deduct cost for buys, credit for sells
            if order.action in ("buy_to_open", "buy_to_close"):
                self._buying_power -= cost
            else:
                self._buying_power += cost

            self._positions[order_id] = _Position(
                order_id=order_id,
                symbol=order.symbol,
                option_type=order.option_type,
                strike=order.strike,
                expiry=order.expiry,
                action=order.action,
                quantity=order.quantity,
                avg_price=fill_price,
            )
            result = OrderResult(
                order_id=order_id,
                status="filled",
                filled_qty=order.quantity,
                avg_price=fill_price,
                timestamp=timestamp,
            )
        else:
            result = OrderResult(
                order_id=order_id,
                status="accepted",
                filled_qty=0,
                avg_price=None,
                timestamp=timestamp,
            )

        self._orders[order_id] = result
        return result

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending (unfilled) order.

        Returns:
            True if the order existed and was not already filled.
            False if the order does not exist or was already filled.
        """
        result = self._orders.get(order_id)
        if result is None:
            return False
        if result.status == "filled":
            return False
        # Mark as cancelled
        self._orders[order_id] = OrderResult(
            order_id=order_id,
            status="cancelled",
            filled_qty=result.filled_qty,
            avg_price=result.avg_price,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
        )
        return True

    async def get_option_chain(self, symbol: str, expiry: str) -> List[dict]:
        """Return a synthetic options chain centred around a $100 stock price.

        Generates strikes from $80 to $120 in $5 increments for both calls and
        puts.  Prices are derived from a simple intrinsic-value model; there is
        no vol surface.  Suitable for integration testing only.
        """
        chain = []
        spot = Decimal("100")
        strikes = [spot + Decimal(str(d)) for d in range(-20, 25, 5)]
        for strike in strikes:
            for opt_type in ("call", "put"):
                intrinsic = max(Decimal("0"), spot - strike) if opt_type == "put" else max(Decimal("0"), strike - spot)
                mid = max(Decimal("0.50"), intrinsic + Decimal("2.00"))
                spread = mid * Decimal("0.05")
                chain.append(
                    {
                        "symbol": f"{symbol}_{expiry}_{opt_type[0].upper()}_{strike}",
                        "underlying": symbol,
                        "option_type": opt_type,
                        "strike": float(strike),
                        "expiry": expiry,
                        "bid": float(mid - spread),
                        "ask": float(mid + spread),
                        "volume": self._rng.randint(100, 5000),
                        "open_interest": self._rng.randint(500, 20000),
                        "implied_volatility": round(self._rng.uniform(0.20, 0.80), 4),
                        "delta": self._synthetic_delta(opt_type, float(strike), float(spot)),
                        "gamma": round(self._rng.uniform(0.01, 0.05), 4),
                        "theta": round(-self._rng.uniform(0.01, 0.10), 4),
                        "vega": round(self._rng.uniform(0.05, 0.30), 4),
                    }
                )
        return chain

    async def get_positions(self) -> List[dict]:
        """Return all currently filled positions as a list of dicts."""
        return [
            {
                "symbol": p.symbol,
                "option_type": p.option_type,
                "strike": float(p.strike),
                "expiry": p.expiry,
                "qty": p.quantity,
                "avg_entry_price": float(p.avg_price),
                "market_value": float(p.avg_price * p.quantity * 100),
                "unrealized_pl": 0.0,  # Mock has no live pricing
                "side": "long" if p.action in ("buy_to_open",) else "short",
                "asset_class": "us_option",
                "order_id": p.order_id,
            }
            for p in self._positions.values()
            if p.order_id in self._orders
            and self._orders[p.order_id].status == "filled"
        ]

    # ------------------------------------------------------------------
    # Test-helper methods (not part of BrokerClient interface)
    # ------------------------------------------------------------------

    def get_order(self, order_id: str) -> Optional[OrderResult]:
        """Retrieve the current state of an order by ID."""
        return self._orders.get(order_id)

    def all_orders(self) -> List[OrderResult]:
        """Return all orders ever submitted to this mock broker."""
        return list(self._orders.values())

    def reset(self, initial_buying_power: Optional[Decimal] = None) -> None:
        """Reset all state, optionally setting a new buying power balance."""
        if initial_buying_power is not None:
            self._buying_power = initial_buying_power
        self._orders.clear()
        self._positions.clear()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_fill_price(self, order: OptionOrder) -> Decimal:
        """Return a simulated fill price incorporating slippage.

        If a limit price is set, the fill is at limit_price * (1 + slippage_pct)
        for buys and limit_price * (1 - slippage_pct) for sells.
        For market orders, a nominal price of $2.00 per contract is used.
        """
        base = order.limit_price if order.limit_price is not None else Decimal("2.00")
        slip = Decimal(str(self._slippage_pct))
        if order.action in ("buy_to_open", "buy_to_close"):
            return (base * (Decimal("1") + slip)).quantize(Decimal("0.01"))
        return (base * (Decimal("1") - slip)).quantize(Decimal("0.01"))

    def _portfolio_market_value(self) -> Decimal:
        total = Decimal("0")
        for pos in self._positions.values():
            if self._orders.get(pos.order_id, {}) and getattr(
                self._orders[pos.order_id], "status", ""
            ) == "filled":
                total += pos.avg_price * pos.quantity * 100
        return total

    @staticmethod
    def _synthetic_delta(option_type: str, strike: float, spot: float) -> float:
        """Very rough delta approximation for synthetic chain generation."""
        moneyness = (spot - strike) / spot
        if option_type == "call":
            return round(max(0.05, min(0.95, 0.5 + moneyness * 2)), 4)
        return round(max(-0.95, min(-0.05, -0.5 + moneyness * 2)), 4)
