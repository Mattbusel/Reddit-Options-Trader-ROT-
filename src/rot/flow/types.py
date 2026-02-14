"""Options flow intelligence data types.

Frozen dataclasses for institutional flow detection, pattern recognition,
signal-flow convergence scoring, and Greeks computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── Constants ───────────────────────────────────────────

FLOW_TYPES = frozenset({
    "block_trade",
    "sweep",
    "dark_pool",
    "accumulation",
    "distribution",
})

FLOW_DIRECTIONS = frozenset({"bullish", "bearish", "neutral"})

PATTERN_TYPES = frozenset({
    "repeat_buyer",
    "accumulation_sequence",
    "hedging",
    "rolling",
    "cross_ticker",
})

CONVERGENCE_TYPES = frozenset({
    "aligned",
    "contradictory",
    "amplified",
})

# ── Flow Event ──────────────────────────────────────────


@dataclass(frozen=True)
class FlowEvent:
    """Single institutional flow event detection.

    Represents a detected unusual flow activity: block trade, sweep,
    dark pool print, accumulation, or distribution pattern.
    """

    ticker: str
    flow_type: str  # one of FLOW_TYPES
    direction: str  # one of FLOW_DIRECTIONS
    premium: float  # total premium in dollars
    volume: int  # contracts traded
    oi_change: int  # change in open interest
    score: float  # 0-100 event significance score
    timestamp: float  # unix timestamp
    details: Dict[str, Any] = field(default_factory=dict)
    signal_id: Optional[str] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.flow_type not in FLOW_TYPES:
            raise ValueError(
                f"Invalid flow_type '{self.flow_type}', "
                f"must be one of {sorted(FLOW_TYPES)}"
            )
        if self.direction not in FLOW_DIRECTIONS:
            raise ValueError(
                f"Invalid direction '{self.direction}', "
                f"must be one of {sorted(FLOW_DIRECTIONS)}"
            )
        if self.premium < 0:
            raise ValueError(f"Premium must be >= 0, got {self.premium}")
        if not (0 <= self.score <= 100):
            raise ValueError(f"Score must be 0-100, got {self.score}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "flow_type": self.flow_type,
            "direction": self.direction,
            "premium": round(self.premium, 2),
            "volume": self.volume,
            "oi_change": self.oi_change,
            "score": round(self.score, 1),
            "timestamp": self.timestamp,
            "details": self.details,
            "signal_id": self.signal_id,
        }

    @property
    def premium_k(self) -> float:
        """Premium in thousands."""
        return round(self.premium / 1000.0, 1)


# ── Flow Score ──────────────────────────────────────────


@dataclass(frozen=True)
class FlowScore:
    """Aggregate flow score for a single ticker.

    Computed from multiple FlowEvents — net premium, direction,
    composite significance score 0-100.
    """

    ticker: str
    score: float  # 0-100 composite flow score
    bullish_flow: float  # total bullish premium
    bearish_flow: float  # total bearish premium
    net_premium: float  # bullish - bearish
    event_count: int  # number of flow events
    detected_at: float

    def __post_init__(self) -> None:
        if not (0 <= self.score <= 100):
            raise ValueError(f"Score must be 0-100, got {self.score}")

    @property
    def flow_direction(self) -> str:
        """Net flow direction based on premium."""
        if abs(self.net_premium) < 10000:  # $10k neutral threshold
            return "neutral"
        return "bullish" if self.net_premium > 0 else "bearish"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "score": round(self.score, 1),
            "bullish_flow": round(self.bullish_flow, 2),
            "bearish_flow": round(self.bearish_flow, 2),
            "net_premium": round(self.net_premium, 2),
            "event_count": self.event_count,
            "flow_direction": self.flow_direction,
            "detected_at": self.detected_at,
        }


# ── Flow Pattern ────────────────────────────────────────


@dataclass(frozen=True)
class FlowPattern:
    """Detected institutional flow pattern.

    Recognized patterns include repeat buyer, accumulation sequence,
    hedging, rolling, and cross-ticker sector flow.
    """

    pattern_type: str  # one of PATTERN_TYPES
    tickers: List[str]
    confidence: float  # 0-1
    timeframe: str  # "1h", "4h", "1d", "1w"
    event_count: int
    details: Dict[str, Any] = field(default_factory=dict)
    detected_at: float = 0.0
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.pattern_type not in PATTERN_TYPES:
            raise ValueError(
                f"Invalid pattern_type '{self.pattern_type}', "
                f"must be one of {sorted(PATTERN_TYPES)}"
            )
        if not (0 <= self.confidence <= 1):
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "pattern_type": self.pattern_type,
            "tickers": self.tickers,
            "confidence": round(self.confidence, 3),
            "timeframe": self.timeframe,
            "event_count": self.event_count,
            "details": self.details,
            "detected_at": self.detected_at,
        }


# ── Signal-Flow Convergence ─────────────────────────────


@dataclass(frozen=True)
class FlowSignalConvergence:
    """When a social signal and institutional flow event align.

    Convergence types:
      - aligned: social signal + flow in same direction → high confidence
      - contradictory: social vs flow opposite → warning flag
      - amplified: multiple flow events reinforce social signal
    """

    signal_id: str
    ticker: str
    flow_event_ids: List[str]
    convergence_score: float  # 0-100
    convergence_type: str  # one of CONVERGENCE_TYPES
    signal_stance: str  # bullish/bearish
    flow_direction: str  # bullish/bearish/neutral
    net_flow_premium: float
    details: Dict[str, Any] = field(default_factory=dict)
    detected_at: float = 0.0
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if not (0 <= self.convergence_score <= 100):
            raise ValueError(
                f"Convergence score must be 0-100, got {self.convergence_score}"
            )
        if self.convergence_type not in CONVERGENCE_TYPES:
            raise ValueError(
                f"Invalid convergence_type '{self.convergence_type}', "
                f"must be one of {sorted(CONVERGENCE_TYPES)}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "signal_id": self.signal_id,
            "ticker": self.ticker,
            "flow_event_ids": self.flow_event_ids,
            "convergence_score": round(self.convergence_score, 1),
            "convergence_type": self.convergence_type,
            "signal_stance": self.signal_stance,
            "flow_direction": self.flow_direction,
            "net_flow_premium": round(self.net_flow_premium, 2),
            "details": self.details,
            "detected_at": self.detected_at,
        }


# ── Greeks Snapshot ─────────────────────────────────────


@dataclass(frozen=True)
class GreeksSnapshot:
    """Greeks data point for a single option or portfolio position.

    Contains all standard Black-Scholes Greeks plus implied volatility.
    """

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    iv: float  # implied volatility (annualized)
    underlying_price: float = 0.0
    strike: float = 0.0
    dte: float = 0.0  # days to expiry
    option_type: str = "call"
    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delta": round(self.delta, 4),
            "gamma": round(self.gamma, 6),
            "theta": round(self.theta, 4),
            "vega": round(self.vega, 4),
            "rho": round(self.rho, 4),
            "iv": round(self.iv, 4),
            "underlying_price": round(self.underlying_price, 2),
            "strike": round(self.strike, 2),
            "dte": round(self.dte, 1),
            "option_type": self.option_type,
            "timestamp": self.timestamp,
        }


# ── Flow Summary ────────────────────────────────────────


@dataclass(frozen=True)
class FlowSummary:
    """Aggregate flow statistics for dashboard display."""

    total_events: int
    unique_tickers: int
    total_premium: float
    net_premium: float
    avg_score: float
    bullish_count: int
    bearish_count: int
    neutral_count: int
    top_tickers: List[Dict[str, Any]] = field(default_factory=list)
    type_breakdown: Dict[str, int] = field(default_factory=dict)
    convergence_count: int = 0
    pattern_count: int = 0

    @property
    def dominant_direction(self) -> str:
        """Overall flow direction."""
        if abs(self.net_premium) < 50000:
            return "neutral"
        return "bullish" if self.net_premium > 0 else "bearish"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_events": self.total_events,
            "unique_tickers": self.unique_tickers,
            "total_premium": round(self.total_premium, 2),
            "net_premium": round(self.net_premium, 2),
            "avg_score": round(self.avg_score, 1),
            "bullish_count": self.bullish_count,
            "bearish_count": self.bearish_count,
            "neutral_count": self.neutral_count,
            "dominant_direction": self.dominant_direction,
            "top_tickers": self.top_tickers,
            "type_breakdown": self.type_breakdown,
            "convergence_count": self.convergence_count,
            "pattern_count": self.pattern_count,
        }
