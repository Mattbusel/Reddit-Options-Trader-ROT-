"""Unusual activity detection data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Valid unusual event types
EVENT_TYPES = frozenset({
    "iv_spike",
    "volume_surge",
    "oi_surge",
    "skew_shift",
    "sweep",
})


@dataclass(frozen=True)
class UnusualEvent:
    """A single unusual activity detection."""

    ticker: str
    event_type: str          # one of EVENT_TYPES
    score: float             # 0-100 unusual-ness score
    details: Dict[str, Any]  # type-specific detail dict
    detected_at: float       # unix timestamp
    signal_id: Optional[str] = None  # linked ROT signal if applicable

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type '{self.event_type}'. "
                f"Must be one of {sorted(EVENT_TYPES)}"
            )
        if not (0 <= self.score <= 100):
            raise ValueError(f"Score must be 0-100, got {self.score}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "event_type": self.event_type,
            "score": round(self.score, 1),
            "details": self.details,
            "detected_at": self.detected_at,
            "signal_id": self.signal_id,
        }


@dataclass(frozen=True)
class UnusualScore:
    """Composite unusual activity score for a signal/ticker."""

    composite_score: float       # 0-100 weighted composite
    flags: List[str]             # human-readable flag names
    component_scores: Dict[str, float]  # event_type → score
    events: List[UnusualEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not (0 <= self.composite_score <= 100):
            raise ValueError(f"Composite score must be 0-100, got {self.composite_score}")

    @property
    def flag_count(self) -> int:
        return len(self.flags)

    @property
    def is_unusual(self) -> bool:
        return self.composite_score > 0 and len(self.flags) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "composite_score": round(self.composite_score, 1),
            "flags": self.flags,
            "component_scores": {k: round(v, 1) for k, v in self.component_scores.items()},
            "event_count": len(self.events),
        }


@dataclass(frozen=True)
class UnusualSummary:
    """Aggregate unusual activity summary over a time period."""

    total_events: int
    unique_tickers: int
    avg_score: float
    top_tickers: List[Dict[str, Any]]    # [{ticker, count, avg_score}]
    type_breakdown: Dict[str, int]       # event_type → count
    highest_score_event: Optional[UnusualEvent] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_events": self.total_events,
            "unique_tickers": self.unique_tickers,
            "avg_score": round(self.avg_score, 1),
            "top_tickers": self.top_tickers,
            "type_breakdown": self.type_breakdown,
            "highest_score": (
                self.highest_score_event.to_dict()
                if self.highest_score_event else None
            ),
        }
