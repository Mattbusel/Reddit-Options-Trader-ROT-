"""Sector rotation analysis data types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class SectorMomentum:
    """Momentum metrics for a single sector."""

    sector: str
    signal_velocity: float        # signals per day (recent window)
    trend: str                    # "accelerating" | "decelerating" | "stable"
    acceleration: float           # change in velocity vs prior window
    score: float                  # composite momentum score 0-100
    signal_count: int = 0         # total signals in window
    bullish_pct: float = 0.0      # % bullish signals
    bearish_pct: float = 0.0      # % bearish signals

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sector": self.sector,
            "signal_velocity": round(self.signal_velocity, 2),
            "trend": self.trend,
            "acceleration": round(self.acceleration, 2),
            "score": round(self.score, 1),
            "signal_count": self.signal_count,
            "bullish_pct": round(self.bullish_pct, 1),
            "bearish_pct": round(self.bearish_pct, 1),
        }


@dataclass(frozen=True)
class RotationEvent:
    """Detected leadership change between sectors."""

    from_sector: str
    to_sector: str
    detected_at: float            # unix timestamp
    confidence: float             # 0-1
    from_velocity_delta: float    # how much leader decelerated
    to_velocity_delta: float      # how much new leader accelerated

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_sector": self.from_sector,
            "to_sector": self.to_sector,
            "detected_at": self.detected_at,
            "confidence": round(self.confidence, 2),
            "from_velocity_delta": round(self.from_velocity_delta, 2),
            "to_velocity_delta": round(self.to_velocity_delta, 2),
        }


@dataclass(frozen=True)
class SectorRanking:
    """Ranked sector with composite score."""

    sector: str
    rank: int
    score: float                  # composite 0-100
    signal_count: int
    win_rate: Optional[float]     # None if insufficient data
    momentum: SectorMomentum
    net_sentiment: float          # -1 to +1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sector": self.sector,
            "rank": self.rank,
            "score": round(self.score, 1),
            "signal_count": self.signal_count,
            "win_rate": round(self.win_rate, 3) if self.win_rate is not None else None,
            "momentum": self.momentum.to_dict(),
            "net_sentiment": round(self.net_sentiment, 2),
        }


@dataclass(frozen=True)
class CapitalFlow:
    """Net bullish/bearish flow for a sector."""

    sector: str
    bullish_count: int
    bearish_count: int
    mixed_count: int
    bullish_intensity: float      # avg confidence of bullish signals
    bearish_intensity: float      # avg confidence of bearish signals
    net_flow: float               # bullish - bearish (weighted by confidence)
    flow_change: float            # change in net_flow vs prior period

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sector": self.sector,
            "bullish_count": self.bullish_count,
            "bearish_count": self.bearish_count,
            "mixed_count": self.mixed_count,
            "bullish_intensity": round(self.bullish_intensity, 3),
            "bearish_intensity": round(self.bearish_intensity, 3),
            "net_flow": round(self.net_flow, 2),
            "flow_change": round(self.flow_change, 2),
        }
