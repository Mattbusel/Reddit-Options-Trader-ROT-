from __future__ import annotations

import datetime
import time
from typing import Any, Dict, List, Optional, Tuple

from rot.core.types import Event, OptionLeg, ReasoningPacket, Strategy, TradeIdea
from rot.market.gates import check_trade_gates

# ── Deduplication ────────────────────────────────────────

# TTL for trade idea deduplication (seconds)
_DEDUP_TTL_S = 15 * 60  # 15 minutes


def _dedup_key(underlying: str, strategy: str, legs: List[OptionLeg]) -> str:
    """Build a stable deduplication key from (ticker, strategy_type, strike).

    Uses the primary leg's strike (first leg in the list) as the strike
    component.  Returns a colon-separated string.
    """
    primary_strike = legs[0].strike if legs else "none"
    return f"{underlying}:{strategy}:{primary_strike}"


def _next_friday() -> str:
    """Return the ISO date string of the next Friday (for weekly options expiry)."""
    today = datetime.date.today()
    days_ahead = 4 - today.weekday()  # Friday = 4
    if days_ahead <= 0:
        days_ahead += 7
    return (today + datetime.timedelta(days=days_ahead)).isoformat()


def _next_monthly() -> str:
    """Return the ISO date string of the third Friday of next month (standard options expiry)."""
    today = datetime.date.today()
    # Third Friday of next month (always advance to next month)
    month = today.month + 1
    year = today.year + (1 if month > 12 else 0)
    month = month if month <= 12 else month - 12

    # Find third Friday
    first_day = datetime.date(year, month, 1)
    first_friday = first_day + datetime.timedelta(days=(4 - first_day.weekday()) % 7)
    third_friday = first_friday + datetime.timedelta(weeks=2)
    return third_friday.isoformat()


class TradeBuilder:
    """Converts a ``ReasoningPacket`` + ``Event`` into structured trade ideas.

    Applies a series of gates (market cap, confidence threshold, unknown stance,
    options liquidity) and then constructs directional options strategies:
    bull call spreads for bullish signals, bear put spreads for bearish signals,
    and straddles for high-uncertainty catalysts.

    Strike prices are selected as ATM ±5% of last close.  Expiry heuristics
    use the next weekly Friday for short-horizon signals and the third Friday
    of the following month for medium/long-horizon signals.
    """

    def __init__(self, min_market_cap: float = 1e8) -> None:
        """Initialize TradeBuilder with a minimum market-cap filter.

        Args:
            min_market_cap: Minimum market capitalisation (USD) required before a
                trade idea is generated.  Defaults to $100 million.
        """
        self.min_market_cap = min_market_cap
        # Deduplication cache: key → expiry timestamp
        self._dedup_cache: Dict[str, float] = {}

    # Minimum liquidity thresholds for options chain filtering
    MIN_OPTION_VOLUME = 10       # minimum daily volume
    MIN_OPEN_INTEREST = 50       # minimum open interest
    MAX_BID_ASK_SPREAD_PCT = 0.15  # maximum bid-ask spread as % of mid price

    def build(self, packet: ReasoningPacket, event: Event) -> List[TradeIdea]:
        """Build trade ideas for the primary ticker in ``event``.

        Args:
            packet: Reasoning output containing thesis, confidence, and stance.
            event: Structured market event with entities, meta, and market data.

        Returns:
            A list of ``TradeIdea`` objects.  Returns a single ``no_trade``
            entry when any gate check fails (no tickers, low confidence,
            unknown stance, missing price data, or illiquid options chain).
        """
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
        event_type = raw.get("event_type", event.event_type)

        # Unknown stance = no directional view = no trade
        if stance == "unknown":
            return [self._no_trade(underlying, packet.thesis, ["unknown_stance"])]

        # Earnings rumor confidence clamp — historically ~11% win rate
        if event_type == "earnings_rumor" and confidence >= 0.35:
            confidence = 0.25

        # Low confidence = no trade
        if confidence < 0.30:
            return [self._no_trade(underlying, packet.thesis, ["confidence_too_low"])]

        # Get price for strike calculation
        market = meta.get("market", {})
        sym_data = market.get(underlying, {})
        price = sym_data.get("last_close")
        if not price or price <= 0:
            return [self._no_trade(underlying, packet.thesis, ["no_price_data"])]

        # Options chain liquidity filter
        liquidity_issues = self._check_options_liquidity(sym_data)
        if liquidity_issues:
            return [self._no_trade(underlying, packet.thesis, liquidity_issues)]

        # Strategy selection (IV-aware)
        strategy, legs, expiry = self._select_strategy(
            stance=stance,
            horizon=horizon,
            price=price,
            underlying=underlying,
            options_data=sym_data,
        )

        if strategy == "none":
            return [self._no_trade(underlying, packet.thesis, ["no_matching_strategy"])]

        # Deduplication: suppress duplicate (ticker, strategy, strike) within TTL
        if self._is_duplicate(underlying, strategy, legs):
            return [self._no_trade(underlying, packet.thesis, ["duplicate_trade_idea"])]

        # Register in dedup cache
        self._register_dedup(underlying, strategy, legs)

        # Calculate max loss
        max_loss = self._estimate_max_loss(strategy, legs, price)

        # Quality score based on confidence and evidence
        quality = self._quality_score(confidence, event, packet)

        # Include IV context in trade meta
        trade_meta: Dict[str, Any] = {
            "stance": stance,
            "horizon": horizon,
            "llm_confidence": confidence,
            "event_type": raw.get("event_type", event.event_type),
        }
        if sym_data.get("atm_iv"):
            trade_meta["atm_iv"] = sym_data["atm_iv"]
        if sym_data.get("pc_ratio"):
            trade_meta["pc_ratio"] = sym_data["pc_ratio"]

        return [
            TradeIdea(
                underlying=underlying,
                strategy=strategy,
                legs=legs,
                max_loss=max_loss,
                thesis=packet.thesis,
                time_stop=expiry,
                quality_score=quality,
                meta=trade_meta,
            )
        ]

    def _select_strategy(
        self,
        stance: str,
        horizon: str,
        price: float,
        underlying: str,
        options_data: Optional[Dict[str, Any]] = None,
    ) -> tuple[Strategy, List[OptionLeg], str]:
        """Select options strategy based on stance, horizon, and IV environment."""

        if horizon == "intraday":
            expiry = _next_friday()
        elif horizon in ("1w", "earnings"):
            expiry = _next_friday()
        else:
            expiry = _next_monthly()

        # Determine IV regime from options data
        high_iv = False
        if options_data:
            atm_iv = options_data.get("atm_iv")
            if atm_iv and atm_iv > 0.5:  # >50% IV = high volatility
                high_iv = True

        if stance == "bullish":
            atm = round(price, 0)
            if high_iv:
                # High IV: bull put credit spread (sell premium)
                otm = round(price * 0.95, 0)
                legs = [
                    OptionLeg(side="sell", kind="put", strike=atm, expiry=expiry, qty=1),
                    OptionLeg(side="buy", kind="put", strike=otm, expiry=expiry, qty=1),
                ]
                return "credit_spread", legs, expiry
            else:
                # Low/normal IV: bull call debit spread (buy premium)
                otm = round(price * 1.05, 0)
                legs = [
                    OptionLeg(side="buy", kind="call", strike=atm, expiry=expiry, qty=1),
                    OptionLeg(side="sell", kind="call", strike=otm, expiry=expiry, qty=1),
                ]
                return "debit_spread", legs, expiry

        elif stance == "bearish":
            atm = round(price, 0)
            if high_iv:
                # High IV: bear call credit spread (sell premium)
                otm = round(price * 1.05, 0)
                legs = [
                    OptionLeg(side="sell", kind="call", strike=atm, expiry=expiry, qty=1),
                    OptionLeg(side="buy", kind="call", strike=otm, expiry=expiry, qty=1),
                ]
                return "credit_spread", legs, expiry
            else:
                # Low/normal IV: bear put debit spread (buy premium)
                otm = round(price * 0.95, 0)
                legs = [
                    OptionLeg(side="buy", kind="put", strike=atm, expiry=expiry, qty=1),
                    OptionLeg(side="sell", kind="put", strike=otm, expiry=expiry, qty=1),
                ]
                return "debit_spread", legs, expiry

        elif stance == "mixed":
            atm = round(price, 0)
            if high_iv:
                # High IV: iron condor (sell premium on both sides)
                call_sell = round(price * 1.05, 0)
                call_buy = round(price * 1.10, 0)
                put_sell = round(price * 0.95, 0)
                put_buy = round(price * 0.90, 0)
                legs = [
                    OptionLeg(side="sell", kind="call", strike=call_sell, expiry=expiry, qty=1),
                    OptionLeg(side="buy", kind="call", strike=call_buy, expiry=expiry, qty=1),
                    OptionLeg(side="sell", kind="put", strike=put_sell, expiry=expiry, qty=1),
                    OptionLeg(side="buy", kind="put", strike=put_buy, expiry=expiry, qty=1),
                ]
                return "iron_condor", legs, expiry
            else:
                # Low IV: straddle (buy premium for breakout)
                legs = [
                    OptionLeg(side="buy", kind="call", strike=atm, expiry=expiry, qty=1),
                    OptionLeg(side="buy", kind="put", strike=atm, expiry=expiry, qty=1),
                ]
                return "straddle", legs, expiry

        return "none", [], expiry

    def _estimate_max_loss(self, strategy: Strategy, legs: List[OptionLeg], price: float) -> float:
        """Estimate the maximum dollar loss for a single options contract.

        Args:
            strategy: Strategy type identifier (e.g. ``"debit_spread"``).
            legs: List of option legs making up the structure.
            price: Current underlying price used for percentage-based estimates.

        Returns:
            Estimated max loss in USD per contract.  Returns 0.0 when the
            strategy is unrecognised or ``"none"``.
        """
        if strategy in ("debit_spread", "credit_spread"):
            # Max loss is width of spread (approximate)
            strikes = [leg.strike for leg in legs]
            if len(strikes) >= 2:
                return abs(strikes[0] - strikes[1]) * 100  # per contract
        elif strategy == "straddle":
            # Max loss is total premium paid (approximate as 3% of underlying)
            return price * 0.03 * 100 * 2
        elif strategy == "strangle":
            return price * 0.02 * 100 * 2
        elif strategy == "iron_condor":
            # Max loss is wider wing width minus net credit
            strikes = sorted([leg.strike for leg in legs])
            if len(strikes) >= 4:
                return abs(strikes[1] - strikes[0]) * 100
        return 0.0

    def _quality_score(self, confidence: float, event: Event, packet: ReasoningPacket) -> float:
        """Compute a composite trade-quality score in the range [0, 1].

        Weights base credibility confidence at 70% and adds bonuses for a
        classified event type, a detailed thesis, and recommended structures,
        with a penalty for excessive risk notes.

        Args:
            confidence: Credibility confidence in [0, 1].
            event: Structured market event (used for event_type).
            packet: LLM reasoning output (used for thesis and structures).

        Returns:
            Float quality score clamped to [0.0, 1.0].
        """
        score = confidence * 0.7

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

    def _check_options_liquidity(self, sym_data: Dict[str, Any]) -> List[str]:
        """Check if the underlying has sufficient options chain liquidity.

        Returns a list of gate failure reasons, or empty list if OK.
        """
        issues: List[str] = []
        options = sym_data.get("options_chain", {})
        if not options or not isinstance(options, dict):
            # No options chain data available — allow trade (data may be missing)
            return []

        avg_volume = options.get("avg_volume", 0)
        avg_oi = options.get("avg_open_interest", 0)
        avg_spread_pct = options.get("avg_bid_ask_spread_pct", 0)

        if isinstance(avg_volume, (int, float)) and avg_volume < self.MIN_OPTION_VOLUME:
            issues.append("low_option_volume")

        if isinstance(avg_oi, (int, float)) and avg_oi < self.MIN_OPEN_INTEREST:
            issues.append("low_open_interest")

        if isinstance(avg_spread_pct, (int, float)) and avg_spread_pct > self.MAX_BID_ASK_SPREAD_PCT:
            issues.append("wide_bid_ask_spread")

        return issues

    # ── Deduplication helpers ────────────────────────────

    def _is_duplicate(self, underlying: str, strategy: str, legs: List[OptionLeg]) -> bool:
        """Return ``True`` if this (ticker, strategy, strike) was emitted within the TTL.

        Stale entries are evicted before the check to bound cache growth.
        """
        now = time.time()
        # Evict expired entries
        expired = [k for k, exp in self._dedup_cache.items() if exp <= now]
        for k in expired:
            del self._dedup_cache[k]

        key = _dedup_key(underlying, strategy, legs)
        return key in self._dedup_cache

    def _register_dedup(self, underlying: str, strategy: str, legs: List[OptionLeg]) -> None:
        """Register a trade idea in the deduplication cache with a 15-minute TTL."""
        key = _dedup_key(underlying, strategy, legs)
        self._dedup_cache[key] = time.time() + _DEDUP_TTL_S

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
