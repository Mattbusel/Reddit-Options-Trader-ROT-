"""Correlation analysis data types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class CorrelationPair:
    """A pair of tickers with correlation metrics."""

    ticker_a: str
    ticker_b: str
    correlation: float            # -1 to +1 (Pearson or co-fire)
    co_fires: int                 # number of times both appeared in same window
    same_stance_pct: float        # % of co-fires where stance matched
    sample_size: int              # total observations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker_a": self.ticker_a,
            "ticker_b": self.ticker_b,
            "correlation": round(self.correlation, 3),
            "co_fires": self.co_fires,
            "same_stance_pct": round(self.same_stance_pct, 1),
            "sample_size": self.sample_size,
        }


@dataclass(frozen=True)
class SignalCorrelationMatrix:
    """Full correlation matrix for a set of tickers."""

    tickers: List[str]
    pairs: List[CorrelationPair]
    strongest_positive: Optional[CorrelationPair] = None
    strongest_negative: Optional[CorrelationPair] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tickers": self.tickers,
            "pair_count": len(self.pairs),
            "strongest_positive": (
                self.strongest_positive.to_dict()
                if self.strongest_positive else None
            ),
            "strongest_negative": (
                self.strongest_negative.to_dict()
                if self.strongest_negative else None
            ),
        }


@dataclass(frozen=True)
class TickerCluster:
    """A group of tickers that move together."""

    cluster_id: int
    tickers: List[str]
    avg_internal_correlation: float
    label: str                    # auto-generated label (e.g., "Tech Momentum")
    size: int = 0

    def __post_init__(self) -> None:
        if self.size == 0:
            object.__setattr__(self, "size", len(self.tickers))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "tickers": self.tickers,
            "avg_internal_correlation": round(self.avg_internal_correlation, 3),
            "label": self.label,
            "size": self.size,
        }


@dataclass(frozen=True)
class LeadLagPair:
    """A pair where one ticker's signals tend to precede the other's."""

    leader: str
    follower: str
    avg_lag_hours: float          # average time difference
    confidence: float             # 0-1
    occurrences: int              # how many times this pattern appeared

    def to_dict(self) -> Dict[str, Any]:
        return {
            "leader": self.leader,
            "follower": self.follower,
            "avg_lag_hours": round(self.avg_lag_hours, 1),
            "confidence": round(self.confidence, 2),
            "occurrences": self.occurrences,
        }


@dataclass(frozen=True)
class PredictivePair:
    """A pair where signals on ticker_a predict outcomes on ticker_b."""

    ticker_a: str
    ticker_b: str
    prediction_accuracy: float    # 0-1
    sample_size: int
    direction: str                # "same" or "inverse"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker_a": self.ticker_a,
            "ticker_b": self.ticker_b,
            "prediction_accuracy": round(self.prediction_accuracy, 3),
            "sample_size": self.sample_size,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class NetworkGraph:
    """Network representation for visualization."""

    nodes: List[Dict[str, Any]]   # [{id, label, size, group}]
    edges: List[Dict[str, Any]]   # [{source, target, weight, color}]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }
