"""Smart order routing with venue selection and order splitting."""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Venue:
    venue_id: str
    name: str
    fee_bps: float          # transaction fee in basis points
    avg_latency_ms: float   # average latency in milliseconds
    fill_rate: float        # historical fill rate [0, 1]
    min_order_size: float   # minimum order size (shares/contracts)
    max_order_size: float   # maximum order size (shares/contracts)


@dataclass
class OrderRequest:
    order_id: str
    symbol: str
    side: str               # "BUY" or "SELL"
    quantity: float
    limit_price: Optional[float] = None
    urgency: int = 3        # 1 (low) to 5 (high)


@dataclass
class RoutingDecision:
    order_id: str
    primary_venue: str
    split_orders: List[Tuple[str, float]]  # list of (venue_id, quantity)
    estimated_fee_bps: float
    estimated_fill_rate: float


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class SmartOrderRouter:
    """Routes orders to the best venue or splits large orders across venues."""

    _EMA_ALPHA = 0.2  # EMA smoothing factor for performance updates

    def __init__(self) -> None:
        self._venues: Dict[str, Venue] = {}

    def register_venue(self, venue: Venue) -> None:
        """Register a trading venue."""
        self._venues[venue.venue_id] = venue

    def venue_score(self, venue: Venue, order: OrderRequest) -> float:
        """Score a venue for a given order.

        score = fill_rate * 0.5
              + (1 / fee_bps) * 0.3
              + urgency * (1 / latency_ms) * 0.2
        """
        if venue.fee_bps <= 0 or venue.avg_latency_ms <= 0:
            return 0.0
        fee_component = (1.0 / venue.fee_bps) * 0.3
        latency_component = order.urgency * (1.0 / venue.avg_latency_ms) * 0.2
        return venue.fill_rate * 0.5 + fee_component + latency_component

    def should_split(self, order: OrderRequest, venue: Venue) -> bool:
        """Return True if the order is larger than 30% of the venue's max order size."""
        return order.quantity > 0.30 * venue.max_order_size

    def route(self, order: OrderRequest) -> RoutingDecision:
        """Select primary venue and optionally split large orders."""
        if not self._venues:
            return RoutingDecision(
                order_id=order.order_id,
                primary_venue="",
                split_orders=[],
                estimated_fee_bps=0.0,
                estimated_fill_rate=0.0,
            )

        # Filter eligible venues (order fits within size constraints)
        eligible = [
            v for v in self._venues.values()
            if v.min_order_size <= order.quantity <= v.max_order_size
               or order.quantity > v.max_order_size  # can split into multiple
        ]
        if not eligible:
            eligible = list(self._venues.values())

        # Score and sort
        scored = sorted(eligible, key=lambda v: self.venue_score(v, order), reverse=True)
        primary = scored[0]

        # Determine if splitting is needed
        if self.should_split(order, primary) and len(scored) > 1:
            split_orders = self._split_order(order, scored)
        else:
            split_orders = [(primary.venue_id, order.quantity)]

        # Aggregate estimates
        total_qty = sum(q for _, q in split_orders)
        weighted_fee = 0.0
        weighted_fill = 0.0
        for vid, qty in split_orders:
            v = self._venues.get(vid)
            if v and total_qty > 0:
                w = qty / total_qty
                weighted_fee += w * v.fee_bps
                weighted_fill += w * v.fill_rate

        return RoutingDecision(
            order_id=order.order_id,
            primary_venue=primary.venue_id,
            split_orders=split_orders,
            estimated_fee_bps=weighted_fee,
            estimated_fill_rate=weighted_fill,
        )

    def _split_order(
        self, order: OrderRequest, scored_venues: List[Venue]
    ) -> List[Tuple[str, float]]:
        """Split a large order across the top venues by capacity."""
        remaining = order.quantity
        split: List[Tuple[str, float]] = []
        for venue in scored_venues:
            if remaining <= 0:
                break
            chunk = min(remaining, venue.max_order_size)
            if chunk >= venue.min_order_size:
                split.append((venue.venue_id, chunk))
                remaining -= chunk
        # If anything is left (no venue could absorb it), attach to primary
        if remaining > 0 and split:
            vid, qty = split[0]
            split[0] = (vid, qty + remaining)
        return split

    def update_venue_performance(
        self, venue_id: str, fill_rate: float, latency_ms: float
    ) -> None:
        """Update venue performance metrics using an EMA."""
        venue = self._venues.get(venue_id)
        if venue is None:
            return
        alpha = self._EMA_ALPHA
        venue.fill_rate = alpha * fill_rate + (1 - alpha) * venue.fill_rate
        venue.avg_latency_ms = alpha * latency_ms + (1 - alpha) * venue.avg_latency_ms


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSmartOrderRouter(unittest.TestCase):
    def _make_venue(
        self,
        vid: str = "V1",
        fee: float = 10.0,
        latency: float = 5.0,
        fill: float = 0.95,
        min_sz: float = 1.0,
        max_sz: float = 1000.0,
    ) -> Venue:
        return Venue(
            venue_id=vid,
            name=f"Venue {vid}",
            fee_bps=fee,
            avg_latency_ms=latency,
            fill_rate=fill,
            min_order_size=min_sz,
            max_order_size=max_sz,
        )

    def _make_order(
        self,
        qty: float = 100.0,
        urgency: int = 3,
    ) -> OrderRequest:
        return OrderRequest(
            order_id="O1",
            symbol="AAPL",
            side="BUY",
            quantity=qty,
            urgency=urgency,
        )

    def test_register_venue(self):
        router = SmartOrderRouter()
        v = self._make_venue()
        router.register_venue(v)
        self.assertIn("V1", router._venues)

    def test_route_no_venues_returns_empty(self):
        router = SmartOrderRouter()
        decision = router.route(self._make_order())
        self.assertEqual(decision.primary_venue, "")

    def test_route_single_venue(self):
        router = SmartOrderRouter()
        router.register_venue(self._make_venue())
        decision = router.route(self._make_order(qty=100.0))
        self.assertEqual(decision.primary_venue, "V1")
        self.assertEqual(len(decision.split_orders), 1)

    def test_route_selects_best_venue(self):
        router = SmartOrderRouter()
        # V2 has lower fee and lower latency -> should score higher
        router.register_venue(self._make_venue("V1", fee=20.0, latency=10.0, fill=0.80))
        router.register_venue(self._make_venue("V2", fee=5.0, latency=2.0, fill=0.98))
        decision = router.route(self._make_order())
        self.assertEqual(decision.primary_venue, "V2")

    def test_venue_score_higher_fill_rate_wins(self):
        router = SmartOrderRouter()
        v_low = self._make_venue("V1", fill=0.50, fee=10.0, latency=5.0)
        v_high = self._make_venue("V2", fill=0.99, fee=10.0, latency=5.0)
        order = self._make_order()
        self.assertGreater(router.venue_score(v_high, order), router.venue_score(v_low, order))

    def test_should_split_large_order(self):
        router = SmartOrderRouter()
        venue = self._make_venue(max_sz=100.0)
        order = self._make_order(qty=40.0)  # 40 > 30% of 100
        self.assertTrue(router.should_split(order, venue))

    def test_should_not_split_small_order(self):
        router = SmartOrderRouter()
        venue = self._make_venue(max_sz=1000.0)
        order = self._make_order(qty=100.0)  # 100 <= 30% of 1000
        self.assertFalse(router.should_split(order, venue))

    def test_split_order_across_venues(self):
        router = SmartOrderRouter()
        router.register_venue(self._make_venue("V1", max_sz=200.0))
        router.register_venue(self._make_venue("V2", fee=5.0, max_sz=300.0))
        # Order is 400 shares; each venue can only handle 200-300
        order = self._make_order(qty=400.0)
        decision = router.route(order)
        total_split = sum(q for _, q in decision.split_orders)
        self.assertAlmostEqual(total_split, 400.0, places=5)

    def test_update_venue_performance_ema(self):
        router = SmartOrderRouter()
        v = self._make_venue(fill=0.80, latency=10.0)
        router.register_venue(v)
        router.update_venue_performance("V1", fill_rate=1.0, latency_ms=2.0)
        updated = router._venues["V1"]
        # EMA: 0.2 * 1.0 + 0.8 * 0.80 = 0.84
        self.assertAlmostEqual(updated.fill_rate, 0.2 * 1.0 + 0.8 * 0.80, places=5)

    def test_update_nonexistent_venue_no_error(self):
        router = SmartOrderRouter()
        router.update_venue_performance("GHOST", 0.9, 5.0)

    def test_routing_decision_fields(self):
        router = SmartOrderRouter()
        router.register_venue(self._make_venue())
        d = router.route(self._make_order())
        self.assertEqual(d.order_id, "O1")
        self.assertGreater(d.estimated_fee_bps, 0)
        self.assertGreater(d.estimated_fill_rate, 0)

    def test_high_urgency_prefers_low_latency(self):
        router = SmartOrderRouter()
        router.register_venue(self._make_venue("FAST", latency=1.0, fee=20.0, fill=0.85))
        router.register_venue(self._make_venue("SLOW", latency=100.0, fee=5.0, fill=0.99))
        order = self._make_order(urgency=5)
        fast_score = router.venue_score(router._venues["FAST"], order)
        slow_score = router.venue_score(router._venues["SLOW"], order)
        # High urgency should heavily favour the FAST venue's latency component
        self.assertGreater(fast_score, slow_score)


if __name__ == "__main__":
    unittest.main()
