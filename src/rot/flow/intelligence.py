"""
Options Flow Intelligence Module

Detects unusual options activity that may indicate informed trading:
- Large block trades (> $500K notional)
- Sweeping (aggressive buying across multiple strikes)
- Dark pool prints (off-exchange large blocks)
- Unusual IV spikes
- Put/Call ratio extremes
- Options expiry clustering (many contracts expiring same date)

These signals are integrated with Reddit/RSS signals to amplify conviction
when both social sentiment AND unusual flow align.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ── Enumerations ─────────────────────────────────────────────────────────────


class FlowType(Enum):
    BLOCK = "block"          # single large trade
    SWEEP = "sweep"          # hitting multiple exchanges/strikes
    DARK_POOL = "dark_pool"  # off-exchange print
    IV_SPIKE = "iv_spike"    # implied volatility explosion
    PCRA = "pcra"            # put/call ratio anomaly


class Sentiment(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class OptionsFlowEvent:
    """A single unusual options flow event.

    Fields
    ------
    event_id        Unique identifier (UUID4 string).
    timestamp       UTC datetime of the trade/event.
    symbol          Underlying ticker (e.g. "AAPL").
    flow_type       Categorical type of unusual flow.
    sentiment       Directional bias inferred from the trade.
    notional_usd    Total notional value (premium * quantity * 100).
    strike          Option strike price, if applicable.
    expiry          Expiry date string YYYY-MM-DD, if applicable.
    option_type     "call" or "put", if applicable.
    iv              Implied volatility at time of trade (decimal, e.g. 0.45).
    iv_rank         IV rank 0-100 relative to 52-week range.
    exchange        Exchange/venue name (e.g. "CBOE", "DARK").
    is_unusual      True when the event passes anomaly threshold.
    conviction_score  0.0-1.0 normalised confidence in the signal.
    notes           Human-readable summary of why flagged.
    """

    event_id: str
    timestamp: datetime
    symbol: str
    flow_type: FlowType
    sentiment: Sentiment
    notional_usd: float
    strike: Optional[float]
    expiry: Optional[str]       # YYYY-MM-DD
    option_type: Optional[str]  # "call" | "put"
    iv: Optional[float]
    iv_rank: Optional[float]    # 0-100
    exchange: str
    is_unusual: bool
    conviction_score: float     # 0.0-1.0
    notes: str


@dataclass
class FlowAnalysis:
    """Aggregate flow analysis for one symbol over a lookback window."""

    symbol: str
    analysis_time: datetime
    total_call_flow_usd: float
    total_put_flow_usd: float
    put_call_ratio: float
    unusual_events: List[OptionsFlowEvent]
    aggregate_sentiment: Sentiment
    flow_conviction: float   # 0.0-1.0
    summary: str


# ── PCR history helpers ───────────────────────────────────────────────────────


def _rolling_mean(values: List[float]) -> float:
    """Return mean of a list; 0.0 for empty list."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _rolling_std(values: List[float], mean: float) -> float:
    """Return population standard deviation; 0.0 for <2 elements."""
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance ** 0.5


# ── FlowDetector ─────────────────────────────────────────────────────────────


class FlowDetector:
    """Analyzes raw options data to detect unusual flow patterns.

    Usage
    -----
    detector = FlowDetector()
    event = detector.ingest_trade(
        symbol="AAPL", strike=180.0, expiry="2024-02-16",
        option_type="call", quantity=500, premium=3.50,
        exchange="CBOE", timestamp=datetime.utcnow(),
        iv=0.45, iv_rank=85,
    )
    analysis = detector.analyze_symbol("AAPL")
    """

    BLOCK_THRESHOLD_USD = 500_000
    SWEEP_MIN_EXCHANGES = 3
    UNUSUAL_IV_RANK_THRESHOLD = 80  # IV rank > 80 is unusual

    def __init__(self, pcr_lookback_days: int = 20) -> None:
        self.events: List[OptionsFlowEvent] = []
        # symbol -> list of (timestamp_unix, pcr_value)
        self.pcr_history: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
        self.pcr_lookback_days = pcr_lookback_days
        # Running call/put daily volume accumulators: symbol -> {date_str: [calls, puts]}
        self._daily_volume: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(lambda: [0.0, 0.0])
        )

    # ── Public ingest ────────────────────────────────────────────────────────

    def ingest_trade(
        self,
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str,  # "call" or "put"
        quantity: int,
        premium: float,
        exchange: str,
        timestamp: datetime,
        iv: float,
        iv_rank: float,
    ) -> Optional[OptionsFlowEvent]:
        """Process a single options trade.  Returns an ``OptionsFlowEvent`` if unusual.

        Notional = premium * quantity * 100 (standard US contract multiplier).
        """
        option_type = option_type.lower().strip()
        notional = premium * abs(quantity) * 100

        # Accumulate daily volume for PCR tracking
        date_key = timestamp.strftime("%Y-%m-%d")
        vol_entry = self._daily_volume[symbol][date_key]
        if option_type == "call":
            vol_entry[0] += abs(quantity)
        elif option_type == "put":
            vol_entry[1] += abs(quantity)

        # Determine flow type and whether unusual
        flow_type, is_unusual, notes = self._classify_trade(
            symbol=symbol,
            notional=notional,
            option_type=option_type,
            iv_rank=iv_rank,
            exchange=exchange,
            quantity=quantity,
        )

        if not is_unusual:
            return None

        sentiment = self._infer_sentiment(option_type, flow_type, quantity)
        conviction = self._score_conviction(
            notional=notional,
            iv_rank=iv_rank,
            flow_type=flow_type,
            is_unusual=is_unusual,
        )

        event = OptionsFlowEvent(
            event_id=str(uuid.uuid4()),
            timestamp=timestamp,
            symbol=symbol.upper(),
            flow_type=flow_type,
            sentiment=sentiment,
            notional_usd=notional,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            iv=iv,
            iv_rank=iv_rank,
            exchange=exchange,
            is_unusual=is_unusual,
            conviction_score=conviction,
            notes=notes,
        )
        self.events.append(event)
        return event

    # ── Classification helpers ───────────────────────────────────────────────

    def _classify_trade(
        self,
        symbol: str,
        notional: float,
        option_type: str,
        iv_rank: float,
        exchange: str,
        quantity: int,
    ) -> Tuple[FlowType, bool, str]:
        """Return (flow_type, is_unusual, notes)."""
        exchange_upper = exchange.upper()

        # Dark pool check first (off-exchange venues)
        if exchange_upper in ("DARK", "OTC", "ATS", "DARKPOOL"):
            if notional >= self.BLOCK_THRESHOLD_USD:
                return (
                    FlowType.DARK_POOL,
                    True,
                    f"Dark pool block: ${notional:,.0f} notional off-exchange on {exchange}",
                )

        # Block trade
        if self.is_block_trade(notional):
            notes = (
                f"Block trade: ${notional:,.0f} notional "
                f"({option_type.upper()}, qty={quantity})"
            )
            return FlowType.BLOCK, True, notes

        # IV spike
        if self.is_iv_spike(iv_rank):
            notes = f"IV spike: IV rank {iv_rank:.1f} (threshold {self.UNUSUAL_IV_RANK_THRESHOLD})"
            return FlowType.IV_SPIKE, True, notes

        # PCR anomaly (checks historical baseline)
        pcr_z = self.pcr_anomaly(symbol)
        if pcr_z is not None and abs(pcr_z) >= 2.0:
            direction = "extreme puts" if pcr_z > 0 else "extreme calls"
            notes = f"PCR anomaly: z-score {pcr_z:.2f} ({direction})"
            return FlowType.PCRA, True, notes

        return FlowType.BLOCK, False, ""

    def _infer_sentiment(
        self, option_type: str, flow_type: FlowType, quantity: int
    ) -> Sentiment:
        """Infer directional sentiment from option type and flow type."""
        if flow_type == FlowType.PCRA:
            # For PCR anomaly the caller checks pcr_anomaly sign separately;
            # default to neutral here since it was already handled in notes.
            return Sentiment.NEUTRAL

        if option_type == "call":
            return Sentiment.BULLISH if quantity > 0 else Sentiment.BEARISH
        if option_type == "put":
            return Sentiment.BEARISH if quantity > 0 else Sentiment.BULLISH
        return Sentiment.NEUTRAL

    def _score_conviction(
        self,
        notional: float,
        iv_rank: float,
        flow_type: FlowType,
        is_unusual: bool,
    ) -> float:
        """Return conviction score in [0.0, 1.0]."""
        if not is_unusual:
            return 0.0

        score = 0.0

        # Notional contribution (log-scaled, caps at $10M)
        notional_clamped = max(notional, 1.0)
        notional_score = min(
            (import_log_scaled := __import__("math").log10(notional_clamped / self.BLOCK_THRESHOLD_USD + 1)),
            1.0,
        ) * 0.5
        score += notional_score

        # IV rank contribution
        if iv_rank >= self.UNUSUAL_IV_RANK_THRESHOLD:
            score += min((iv_rank - self.UNUSUAL_IV_RANK_THRESHOLD) / 20.0, 1.0) * 0.3

        # Flow type bonus
        type_bonus = {
            FlowType.DARK_POOL: 0.15,
            FlowType.SWEEP: 0.15,
            FlowType.BLOCK: 0.10,
            FlowType.IV_SPIKE: 0.10,
            FlowType.PCRA: 0.05,
        }.get(flow_type, 0.0)
        score += type_bonus

        return min(score, 1.0)

    # ── Detection predicates ─────────────────────────────────────────────────

    def is_block_trade(self, notional: float) -> bool:
        """Return True when notional exceeds BLOCK_THRESHOLD_USD."""
        return notional >= self.BLOCK_THRESHOLD_USD

    def is_iv_spike(self, iv_rank: float) -> bool:
        """Return True when IV rank exceeds UNUSUAL_IV_RANK_THRESHOLD."""
        return iv_rank >= self.UNUSUAL_IV_RANK_THRESHOLD

    # ── PCR tracking ────────────────────────────────────────────────────────

    def update_pcr(
        self, symbol: str, calls_volume: float, puts_volume: float
    ) -> None:
        """Record a PCR data point.  Call once per day/bar per symbol."""
        if calls_volume <= 0:
            ratio = 999.0  # extreme puts dominance
        else:
            ratio = puts_volume / calls_volume
        ts = datetime.now(tz=timezone.utc).timestamp()
        self.pcr_history[symbol].append((ts, ratio))
        # Trim to lookback window
        cutoff = ts - self.pcr_lookback_days * 86400
        self.pcr_history[symbol] = [
            (t, r) for t, r in self.pcr_history[symbol] if t >= cutoff
        ]

    def pcr_anomaly(self, symbol: str) -> Optional[float]:
        """Return z-score of the most recent PCR vs historical baseline.

        Positive z-score = puts dominating (bearish flow).
        Negative z-score = calls dominating (bullish flow).
        Returns None when fewer than 5 data points exist.
        """
        history = self.pcr_history.get(symbol, [])
        if len(history) < 5:
            return None
        values = [r for _, r in history]
        mean = _rolling_mean(values)
        std = _rolling_std(values, mean)
        if std == 0.0:
            return None
        latest = values[-1]
        return (latest - mean) / std

    # ── Symbol analysis ──────────────────────────────────────────────────────

    def analyze_symbol(self, symbol: str, lookback_hours: int = 24) -> FlowAnalysis:
        """Produce a full ``FlowAnalysis`` for ``symbol`` over ``lookback_hours``."""
        symbol = symbol.upper()
        cutoff_ts = datetime.now(tz=timezone.utc).timestamp() - lookback_hours * 3600

        recent_events = [
            e
            for e in self.events
            if e.symbol == symbol
            and e.is_unusual
            and e.timestamp.replace(tzinfo=timezone.utc).timestamp() >= cutoff_ts
        ]

        total_call_usd = sum(
            e.notional_usd for e in recent_events if e.option_type == "call"
        )
        total_put_usd = sum(
            e.notional_usd for e in recent_events if e.option_type == "put"
        )

        if total_call_usd > 0:
            pcr = total_put_usd / total_call_usd
        elif total_put_usd > 0:
            pcr = 999.0
        else:
            pcr = 1.0

        # Aggregate sentiment: weight by notional * conviction
        bullish_weight = sum(
            e.notional_usd * e.conviction_score
            for e in recent_events
            if e.sentiment == Sentiment.BULLISH
        )
        bearish_weight = sum(
            e.notional_usd * e.conviction_score
            for e in recent_events
            if e.sentiment == Sentiment.BEARISH
        )

        if bullish_weight > bearish_weight * 1.25:
            agg_sentiment = Sentiment.BULLISH
        elif bearish_weight > bullish_weight * 1.25:
            agg_sentiment = Sentiment.BEARISH
        else:
            agg_sentiment = Sentiment.NEUTRAL

        # Overall conviction: mean of individual event convictions (weighted by notional)
        total_notional = sum(e.notional_usd for e in recent_events)
        if total_notional > 0 and recent_events:
            flow_conviction = min(
                sum(e.conviction_score * e.notional_usd for e in recent_events)
                / total_notional,
                1.0,
            )
        elif recent_events:
            flow_conviction = sum(e.conviction_score for e in recent_events) / len(
                recent_events
            )
        else:
            flow_conviction = 0.0

        summary = (
            f"{symbol}: {len(recent_events)} unusual event(s) in last {lookback_hours}h | "
            f"call flow ${total_call_usd:,.0f} | put flow ${total_put_usd:,.0f} | "
            f"P/C ratio {pcr:.2f} | sentiment {agg_sentiment.value} | "
            f"conviction {flow_conviction:.2f}"
        )

        return FlowAnalysis(
            symbol=symbol,
            analysis_time=datetime.now(tz=timezone.utc),
            total_call_flow_usd=total_call_usd,
            total_put_flow_usd=total_put_usd,
            put_call_ratio=pcr,
            unusual_events=recent_events,
            aggregate_sentiment=agg_sentiment,
            flow_conviction=flow_conviction,
            summary=summary,
        )

    def top_unusual_symbols(self, n: int = 10) -> List[Tuple[str, float]]:
        """Return top-n (symbol, conviction_score) pairs with most unusual flow.

        Conviction is the notional-weighted mean of all unusual events per symbol.
        """
        symbol_data: Dict[str, List[float]] = defaultdict(list)
        for e in self.events:
            if e.is_unusual:
                symbol_data[e.symbol].append((e.conviction_score, e.notional_usd))

        scored: List[Tuple[str, float]] = []
        for sym, items in symbol_data.items():
            total_notional = sum(notional for _, notional in items)
            if total_notional > 0:
                wt_conviction = sum(c * n_ for c, n_ in items) / total_notional
            else:
                wt_conviction = sum(c for c, _ in items) / len(items)
            scored.append((sym, wt_conviction))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]


# ── FlowSignalIntegrator ─────────────────────────────────────────────────────


class FlowSignalIntegrator:
    """Combines institutional flow analysis with Reddit/social sentiment scores.

    The integrator takes a ``social_conviction`` (0.0-1.0) produced by ROT's
    NLP pipeline and an optional ``FlowAnalysis`` and returns a combined
    conviction score along with a human-readable explanation.

    Combination rules
    -----------------
    1. Both aligned (same direction): multiply convictions, cap at 0.95.
    2. Flow agrees but is weak (flow_conviction < 0.4): add 0.10 to social.
    3. Flow disagrees with social: subtract 0.20 from social.
    4. No flow data (analysis is None or no unusual events): return social unchanged.
    5. Flow is neutral: return social unchanged.
    """

    BOTH_ALIGNED_CAP = 0.95
    WEAK_FLOW_BOOST = 0.10
    DISAGREE_PENALTY = 0.20
    WEAK_FLOW_THRESHOLD = 0.40

    def combine_signals(
        self,
        social_conviction: float,
        flow_analysis: Optional[FlowAnalysis],
        social_sentiment: Optional[Sentiment] = None,
    ) -> Tuple[float, str]:
        """Return (combined_conviction, explanation).

        Parameters
        ----------
        social_conviction : float
            NLP pipeline conviction in [0.0, 1.0].
        flow_analysis : FlowAnalysis or None
            Result from ``FlowDetector.analyze_symbol()``.  Pass None when no
            flow data is available.
        social_sentiment : Sentiment or None
            Optional directional hint from the NLP pipeline.  When None, the
            integrator infers bullish/bearish from the raw conviction value
            (> 0.5 = bullish, <= 0.5 = bearish).
        """
        social_conviction = max(0.0, min(1.0, social_conviction))

        # No flow data → return unchanged
        if flow_analysis is None or not flow_analysis.unusual_events:
            return (
                social_conviction,
                "No unusual flow data available; using social conviction unchanged.",
            )

        flow_sent = flow_analysis.aggregate_sentiment
        flow_conv = flow_analysis.flow_conviction

        # Neutral flow → no adjustment
        if flow_sent == Sentiment.NEUTRAL:
            return (
                social_conviction,
                f"Flow is neutral ({flow_analysis.symbol}); social conviction unchanged at {social_conviction:.2f}.",
            )

        # Infer social direction if not provided
        if social_sentiment is None:
            social_sentiment = (
                Sentiment.BULLISH if social_conviction >= 0.5 else Sentiment.BEARISH
            )

        aligned = social_sentiment == flow_sent

        if aligned:
            if flow_conv < self.WEAK_FLOW_THRESHOLD:
                # Weak agreement → small boost
                combined = min(social_conviction + self.WEAK_FLOW_BOOST, self.BOTH_ALIGNED_CAP)
                explanation = (
                    f"Flow ({flow_analysis.symbol}) agrees ({flow_sent.value}) but is weak "
                    f"(flow conviction {flow_conv:.2f}). "
                    f"Boosted social conviction {social_conviction:.2f} -> {combined:.2f}."
                )
            else:
                # Strong agreement → multiplicative amplification
                combined = min(
                    social_conviction * flow_conv / max(social_conviction, flow_conv)
                    + (social_conviction + flow_conv) / 2.0 * 0.5,
                    self.BOTH_ALIGNED_CAP,
                )
                # Simpler formula: geometric mean, capped
                combined = min(
                    (social_conviction * flow_conv) ** 0.5
                    + (social_conviction + flow_conv) / 4.0,
                    self.BOTH_ALIGNED_CAP,
                )
                explanation = (
                    f"Flow ({flow_analysis.symbol}) strongly agrees ({flow_sent.value}, "
                    f"flow conviction {flow_conv:.2f}). "
                    f"Amplified social conviction {social_conviction:.2f} -> {combined:.2f}."
                )
        else:
            # Disagreement → penalise
            combined = max(0.0, social_conviction - self.DISAGREE_PENALTY)
            explanation = (
                f"Flow ({flow_analysis.symbol}) DISAGREES — flow is {flow_sent.value}, "
                f"social is {social_sentiment.value}. "
                f"Penalised social conviction {social_conviction:.2f} -> {combined:.2f}."
            )

        return (round(combined, 4), explanation)
