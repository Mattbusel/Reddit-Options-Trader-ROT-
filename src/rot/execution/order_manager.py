"""Order lifecycle manager for the ROT platform.

Tracks orders from submission through full or partial fills to completion,
cancellation, or rejection.
"""

from __future__ import annotations

import uuid
import unittest
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OrderStatus(Enum):
    """Lifecycle state of an order."""

    PENDING = auto()
    SUBMITTED = auto()
    PARTIALLY_FILLED = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


# ---------------------------------------------------------------------------
# Order dataclass
# ---------------------------------------------------------------------------


@dataclass
class Order:
    """Represents a single order in the system.

    Attributes
    ----------
    symbol:
        Ticker symbol (e.g. "AAPL", "TSLA 230120C00150000").
    side:
        BUY or SELL.
    order_type:
        MARKET, LIMIT, or STOP.
    quantity:
        Requested number of shares / contracts.
    price:
        Limit price (required for LIMIT and STOP orders; ignored for MARKET).
    order_id:
        Auto-generated UUID string if not provided.
    status:
        Current lifecycle state (starts PENDING).
    filled_qty:
        Total quantity filled so far.
    avg_fill_price:
        Volume-weighted average fill price (0.0 until any fill).
    """

    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float = 0.0
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: OrderStatus = field(default=OrderStatus.PENDING)
    filled_qty: float = field(default=0.0)
    avg_fill_price: float = field(default=0.0)

    # Internal: accumulated cost for avg_fill_price calculation.
    _fill_cost: float = field(default=0.0, repr=False, compare=False)

    @property
    def remaining_qty(self) -> float:
        """Unfilled quantity."""
        return max(self.quantity - self.filled_qty, 0.0)

    @property
    def is_open(self) -> bool:
        """True if the order is still active (not terminal)."""
        return self.status in {
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIALLY_FILLED,
        }

    @property
    def is_terminal(self) -> bool:
        """True if the order is in a terminal state."""
        return self.status in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        }


# ---------------------------------------------------------------------------
# OrderManager
# ---------------------------------------------------------------------------


class OrderManager:
    """Manage the full lifecycle of orders.

    Orders are stored in two collections:
    - *active*: orders that are open (PENDING / SUBMITTED / PARTIALLY_FILLED).
    - *history*: terminal orders (FILLED / CANCELLED / REJECTED).

    All operations are synchronous and in-memory; persistence is the caller's
    responsibility.
    """

    def __init__(self) -> None:
        self._active: Dict[str, Order] = {}
        self._history: Dict[str, Order] = {}

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def submit_order(self, order: Order) -> str:
        """Submit a new order.

        Transitions the order from PENDING → SUBMITTED and stores it in the
        active book.

        Parameters
        ----------
        order:
            The order to submit.  Its ``order_id`` is used as the key; a new
            UUID is generated automatically if the caller didn't provide one.

        Returns
        -------
        str
            The ``order_id`` of the submitted order.

        Raises
        ------
        ValueError
            If an order with the same ``order_id`` already exists.
        """
        if order.order_id in self._active or order.order_id in self._history:
            raise ValueError(f"Order {order.order_id!r} already exists.")
        if order.status != OrderStatus.PENDING:
            raise ValueError(
                f"Only PENDING orders can be submitted; got {order.status.name}."
            )
        order.status = OrderStatus.SUBMITTED
        self._active[order.order_id] = order
        return order.order_id

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.

        Parameters
        ----------
        order_id:
            Identifier of the order to cancel.

        Returns
        -------
        bool
            ``True`` if the order was successfully cancelled, ``False`` if
            the order_id was not found or the order is already terminal.
        """
        order = self._active.get(order_id)
        if order is None:
            return False
        order.status = OrderStatus.CANCELLED
        self._history[order_id] = self._active.pop(order_id)
        return True

    # ------------------------------------------------------------------
    # Rejection
    # ------------------------------------------------------------------

    def reject_order(self, order_id: str, reason: str = "") -> bool:
        """Move an order to REJECTED status.

        Parameters
        ----------
        order_id:
            Identifier of the order to reject.
        reason:
            Optional human-readable rejection reason (logged but not stored).

        Returns
        -------
        bool
            ``True`` if the order was found and rejected.
        """
        order = self._active.get(order_id)
        if order is None:
            return False
        order.status = OrderStatus.REJECTED
        self._history[order_id] = self._active.pop(order_id)
        return True

    # ------------------------------------------------------------------
    # Fill handling
    # ------------------------------------------------------------------

    def update_fill(self, order_id: str, qty: float, price: float) -> None:
        """Record a partial or full fill for an order.

        Updates ``filled_qty`` and ``avg_fill_price`` (VWAP).  Transitions
        the status to PARTIALLY_FILLED or FILLED accordingly.

        Parameters
        ----------
        order_id:
            The order receiving the fill.
        qty:
            Quantity filled in this execution.
        price:
            Execution price for this fill.

        Raises
        ------
        KeyError
            If ``order_id`` is not found in the active book.
        ValueError
            If ``qty`` or ``price`` is non-positive, or if the fill would
            exceed the order's total quantity.
        """
        if qty <= 0:
            raise ValueError(f"Fill quantity must be positive; got {qty}.")
        if price <= 0:
            raise ValueError(f"Fill price must be positive; got {price}.")

        order = self._active.get(order_id)
        if order is None:
            raise KeyError(f"Order {order_id!r} not found in active book.")

        new_total_qty = order.filled_qty + qty
        if new_total_qty > order.quantity + 1e-9:
            raise ValueError(
                f"Fill of {qty} would exceed order quantity "
                f"({new_total_qty:.4f} > {order.quantity:.4f})."
            )

        # Update VWAP.
        order._fill_cost += qty * price
        order.filled_qty = min(new_total_qty, order.quantity)
        order.avg_fill_price = order._fill_cost / order.filled_qty

        # Update status.
        if order.filled_qty >= order.quantity - 1e-9:
            order.status = OrderStatus.FILLED
            self._history[order_id] = self._active.pop(order_id)
        else:
            order.status = OrderStatus.PARTIALLY_FILLED

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_order(self, order_id: str) -> Optional[Order]:
        """Return an order by id, searching both active and history."""
        return self._active.get(order_id) or self._history.get(order_id)

    def get_open_orders(self) -> List[Order]:
        """Return a list of all currently open (active) orders."""
        return list(self._active.values())

    def order_history(self) -> List[Order]:
        """Return a list of all terminal (historical) orders."""
        return list(self._history.values())

    def all_orders(self) -> List[Order]:
        """Return every order (active + historical)."""
        return list(self._active.values()) + list(self._history.values())

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def total_filled_value(self) -> float:
        """Sum of (filled_qty × avg_fill_price) across all FILLED orders."""
        return sum(
            o.filled_qty * o.avg_fill_price
            for o in self._history.values()
            if o.status == OrderStatus.FILLED
        )

    def fill_rate(self) -> float:
        """Fraction of submitted orders that were fully filled."""
        total = len(self._active) + len(self._history)
        if total == 0:
            return 0.0
        filled = sum(
            1 for o in self._history.values() if o.status == OrderStatus.FILLED
        )
        return filled / total


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def _make_order(**kwargs) -> Order:
    defaults = dict(
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10.0,
        price=150.0,
    )
    defaults.update(kwargs)
    return Order(**defaults)


class TestOrderStatus(unittest.TestCase):
    def test_all_statuses_exist(self):
        for name in ("PENDING", "SUBMITTED", "PARTIALLY_FILLED", "FILLED",
                     "CANCELLED", "REJECTED"):
            self.assertIn(name, OrderStatus.__members__)


class TestOrder(unittest.TestCase):
    def test_default_status_pending(self):
        o = _make_order()
        self.assertEqual(o.status, OrderStatus.PENDING)

    def test_order_id_auto_generated(self):
        o1 = _make_order()
        o2 = _make_order()
        self.assertNotEqual(o1.order_id, o2.order_id)

    def test_remaining_qty(self):
        o = _make_order(quantity=10.0)
        o.filled_qty = 3.0
        self.assertAlmostEqual(o.remaining_qty, 7.0)

    def test_is_open(self):
        o = _make_order()
        self.assertTrue(o.is_open)
        o.status = OrderStatus.FILLED
        self.assertFalse(o.is_open)

    def test_is_terminal(self):
        o = _make_order()
        self.assertFalse(o.is_terminal)
        o.status = OrderStatus.CANCELLED
        self.assertTrue(o.is_terminal)


class TestOrderManagerSubmit(unittest.TestCase):
    def setUp(self):
        self.mgr = OrderManager()

    def test_submit_returns_order_id(self):
        o = _make_order()
        oid = self.mgr.submit_order(o)
        self.assertEqual(oid, o.order_id)

    def test_submit_transitions_to_submitted(self):
        o = _make_order()
        self.mgr.submit_order(o)
        self.assertEqual(o.status, OrderStatus.SUBMITTED)

    def test_submit_duplicate_raises(self):
        o = _make_order()
        self.mgr.submit_order(o)
        with self.assertRaises(ValueError):
            self.mgr.submit_order(o)

    def test_submit_non_pending_raises(self):
        o = _make_order()
        o.status = OrderStatus.SUBMITTED
        with self.assertRaises(ValueError):
            self.mgr.submit_order(o)

    def test_open_orders_contains_submitted(self):
        o = _make_order()
        self.mgr.submit_order(o)
        self.assertIn(o, self.mgr.get_open_orders())


class TestOrderManagerCancel(unittest.TestCase):
    def setUp(self):
        self.mgr = OrderManager()

    def test_cancel_open_order(self):
        o = _make_order()
        oid = self.mgr.submit_order(o)
        result = self.mgr.cancel_order(oid)
        self.assertTrue(result)
        self.assertEqual(o.status, OrderStatus.CANCELLED)
        self.assertNotIn(o, self.mgr.get_open_orders())
        self.assertIn(o, self.mgr.order_history())

    def test_cancel_unknown_order_returns_false(self):
        self.assertFalse(self.mgr.cancel_order("nonexistent"))

    def test_cancel_already_filled_returns_false(self):
        o = _make_order()
        oid = self.mgr.submit_order(o)
        self.mgr.update_fill(oid, 10.0, 150.0)
        self.assertFalse(self.mgr.cancel_order(oid))


class TestOrderManagerFills(unittest.TestCase):
    def setUp(self):
        self.mgr = OrderManager()

    def _submit(self, **kwargs) -> tuple:
        o = _make_order(**kwargs)
        oid = self.mgr.submit_order(o)
        return o, oid

    def test_full_fill_moves_to_history(self):
        o, oid = self._submit(quantity=10.0)
        self.mgr.update_fill(oid, 10.0, 150.0)
        self.assertEqual(o.status, OrderStatus.FILLED)
        self.assertIn(o, self.mgr.order_history())
        self.assertNotIn(o, self.mgr.get_open_orders())

    def test_partial_fill_stays_active(self):
        o, oid = self._submit(quantity=10.0)
        self.mgr.update_fill(oid, 3.0, 150.0)
        self.assertEqual(o.status, OrderStatus.PARTIALLY_FILLED)
        self.assertIn(o, self.mgr.get_open_orders())

    def test_avg_fill_price_vwap(self):
        o, oid = self._submit(quantity=10.0)
        self.mgr.update_fill(oid, 5.0, 100.0)
        self.mgr.update_fill(oid, 5.0, 200.0)
        self.assertAlmostEqual(o.avg_fill_price, 150.0, places=6)

    def test_overfill_raises(self):
        o, oid = self._submit(quantity=5.0)
        with self.assertRaises(ValueError):
            self.mgr.update_fill(oid, 10.0, 150.0)

    def test_zero_qty_raises(self):
        o, oid = self._submit()
        with self.assertRaises(ValueError):
            self.mgr.update_fill(oid, 0.0, 150.0)

    def test_negative_price_raises(self):
        o, oid = self._submit()
        with self.assertRaises(ValueError):
            self.mgr.update_fill(oid, 1.0, -1.0)

    def test_unknown_order_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.mgr.update_fill("bad-id", 1.0, 100.0)


class TestOrderManagerStats(unittest.TestCase):
    def setUp(self):
        self.mgr = OrderManager()

    def test_fill_rate_empty(self):
        self.assertAlmostEqual(self.mgr.fill_rate(), 0.0)

    def test_fill_rate_all_filled(self):
        for i in range(3):
            o = _make_order(quantity=1.0)
            oid = self.mgr.submit_order(o)
            self.mgr.update_fill(oid, 1.0, 100.0)
        self.assertAlmostEqual(self.mgr.fill_rate(), 1.0, places=6)

    def test_total_filled_value(self):
        o = _make_order(quantity=10.0)
        oid = self.mgr.submit_order(o)
        self.mgr.update_fill(oid, 10.0, 200.0)
        self.assertAlmostEqual(self.mgr.total_filled_value(), 2000.0, places=4)

    def test_reject_order(self):
        o = _make_order()
        oid = self.mgr.submit_order(o)
        result = self.mgr.reject_order(oid, "insufficient margin")
        self.assertTrue(result)
        self.assertEqual(o.status, OrderStatus.REJECTED)

    def test_get_order_finds_active(self):
        o = _make_order()
        oid = self.mgr.submit_order(o)
        found = self.mgr.get_order(oid)
        self.assertIs(found, o)

    def test_get_order_finds_history(self):
        o = _make_order()
        oid = self.mgr.submit_order(o)
        self.mgr.cancel_order(oid)
        found = self.mgr.get_order(oid)
        self.assertIs(found, o)


if __name__ == "__main__":
    unittest.main()
