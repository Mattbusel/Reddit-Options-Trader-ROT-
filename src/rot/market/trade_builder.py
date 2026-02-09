from __future__ import annotations

import datetime
from typing import Any, Dict, List

from rot.core.types import Event, OptionLeg, ReasoningPacket, Strategy, TradeIdea
from rot.market.gates import check_trade_gates


def _next_friday() -> str:
    today = datetime.date.today()
    days_ahead = 4 - today.weekday()  # Friday = 4
    if days_ahead <= 0:
        days_ahead += 7
    return (today + datetime.timedelta(days=days_ahead)).isoformat()


def _next_monthly() -> str:
    today = datetime.date.today()
    # Third Friday of next month
    if today.day > 15:
        month = today.month + 1
        year = today.year + (1 if month > 12 else 0)
        month = month if month <= 12 else month - 12
    else:
        month = today.month
        year = today.year

    # Find third Friday
    first_day = datetime.date(year, month, 1)
    first_friday = first_day + datetime.timedelta(days=(4 - first_day.weekday()) % 7)
    third_friday = first_friday + datetime.timedelta(weeks=2)
    return third_friday.isoformat()


class TradeBuilder:
    def __init__(self, min_market_cap: float = 1e8) -> None:
        self.min_market_cap = min_market_cap

    def build(self, packet: ReasoningPacket, event: Event) -> List[TradeIdea]:
        if not event.entities:
            return [self._no_trade("UNKNOWN", packet.thesis, ["no_tickers_extracted"])]

        underlying = event.entities[0]
        meta = event.meta or {}

        # Check trade gates
        gate_failures = check_trade_gates(meta, min_market_cap=self.min_market_cap)
        if gate_failures:
            return [self._no_trade(underlying, packet.thesis, gate_failures)]

        # Get LLM-enriched fields from reasoning packet raw
        raw = packet.raw or {}
        confidence = raw.get("confidence", event.confidence)
        stance = raw.get("stance", event.stance)
        horizon = raw.get("time_horizon", event.time_horizon)

        # Low confidence = no trade
        if confidence < 0.4:
            return [self._no_trade(underlying, packet.thesis, ["confidence_too_low"])]

        # Get price for strike calculation
        market = meta.get("market", {})
        sym_data = market.get(underlying, {})
        price = sym_data.get("last_close")
        if not price or price <= 0:
            return [self._no_trade(underlying, packet.thesis, ["no_price_data"])]

        # Strategy selection
        strategy, legs, expiry = self._select_strategy(
            stance=stance,
            horizon=horizon,
            price=price,
            underlying=underlying,
        )

        if strategy == "none":
            return [self._no_trade(underlying, packet.thesis, ["no_matching_strategy"])]

        # Calculate max loss
        max_loss = self._estimate_max_loss(strategy, legs, price)

        # Quality score based on confidence and evidence
        quality = self._quality_score(confidence, event, packet)

        return [
            TradeIdea(
                underlying=underlying,
                strategy=strategy,
                legs=legs,
                max_loss=max_loss,
                thesis=packet.thesis,
                time_stop=expiry,
                quality_score=quality,
                meta={
                    "stance": stance,
                    "horizon": horizon,
                    "llm_confidence": confidence,
                    "event_type": raw.get("event_type", event.event_type),
                },
            )
        ]

    def _select_strategy(
        self,
        stance: str,
        horizon: str,
        price: float,
        underlying: str,
    ) -> tuple[Strategy, List[OptionLeg], str]:
        """Select options strategy based on stance and horizon."""

        if horizon == "intraday":
            expiry = _next_friday()
        elif horizon in ("1w", "earnings"):
            expiry = _next_friday()
        else:
            expiry = _next_monthly()

        if stance == "bullish":
            # Bull call spread: buy ATM call, sell OTM call
            atm = round(price, 0)
            otm = round(price * 1.05, 0)
            legs = [
                OptionLeg(side="buy", kind="call", strike=atm, expiry=expiry, qty=1),
                OptionLeg(side="sell", kind="call", strike=otm, expiry=expiry, qty=1),
            ]
            return "debit_spread", legs, expiry

        elif stance == "bearish":
            # Bear put spread: buy ATM put, sell OTM put
            atm = round(price, 0)
            otm = round(price * 0.95, 0)
            legs = [
                OptionLeg(side="buy", kind="put", strike=atm, expiry=expiry, qty=1),
                OptionLeg(side="sell", kind="put", strike=otm, expiry=expiry, qty=1),
            ]
            return "debit_spread", legs, expiry

        elif stance == "mixed":
            # Straddle for uncertain direction
            atm = round(price, 0)
            legs = [
                OptionLeg(side="buy", kind="call", strike=atm, expiry=expiry, qty=1),
                OptionLeg(side="buy", kind="put", strike=atm, expiry=expiry, qty=1),
            ]
            return "straddle", legs, expiry

        return "none", [], expiry

    def _estimate_max_loss(self, strategy: Strategy, legs: List[OptionLeg], price: float) -> float:
        if strategy == "debit_spread":
            # Max loss is width of spread (approximate)
            strikes = [leg.strike for leg in legs]
            if len(strikes) >= 2:
                return abs(strikes[0] - strikes[1]) * 100  # per contract
        elif strategy == "straddle":
            # Max loss is total premium paid (approximate as 3% of underlying)
            return price * 0.03 * 100 * 2
        elif strategy == "strangle":
            return price * 0.02 * 100 * 2
        return 0.0

    def _quality_score(self, confidence: float, event: Event, packet: ReasoningPacket) -> float:
        score = confidence * 0.5

        # Boost for classified event type
        if event.event_type != "other":
            score += 0.1

        # Boost for specific thesis
        if packet.thesis and len(packet.thesis) > 50:
            score += 0.1

        # Boost for having recommended structures
        if packet.recommended_structures:
            score += 0.1

        # Penalty for many risk notes
        if len(packet.risk_notes) > 3:
            score -= 0.1

        return max(0.0, min(1.0, score))

    def _no_trade(self, underlying: str, thesis: str, reasons: List[str]) -> TradeIdea:
        return TradeIdea(
            underlying=underlying,
            strategy="none",
            legs=[],
            max_loss=0.0,
            thesis=thesis,
            time_stop="N/A",
            quality_score=0.0,
            do_not_trade_reasons=reasons,
        )
