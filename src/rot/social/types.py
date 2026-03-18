"""Frozen dataclasses for the Social Intelligence Network."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── Constants ────────────────────────────────────────────────────────────────

PLATFORMS = frozenset({"reddit", "stocktwits", "twitter"})
STANCES = frozenset({"bullish", "bearish", "mixed", "unknown"})
OUTCOMES = frozenset({"win", "loss", "neutral"})
ALERT_TYPES = frozenset({"coordinated_posting", "bot_network", "pump_and_dump"})


def _gen_id() -> str:
    return uuid.uuid4().hex[:16]


# ── AuthorProfile ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AuthorProfile:
    """Aggregate profile for a signal author across a platform."""

    id: str
    platform: str
    username: str
    total_signals: int = 0
    win_count: int = 0
    loss_count: int = 0
    accuracy: Optional[float] = None
    roi_if_followed: Optional[float] = None
    sharpe: Optional[float] = None
    reputation_score: Optional[float] = None
    stats: Dict[str, Any] = field(default_factory=dict)
    first_seen: float = field(default_factory=time.time)
    last_seen: Optional[float] = None
    updated_at: Optional[float] = None

    def __post_init__(self) -> None:
        if self.platform not in PLATFORMS:
            raise ValueError(f"Invalid platform: {self.platform!r}. Must be one of {sorted(PLATFORMS)}")
        if not self.username:
            raise ValueError("username must be non-empty")
        if self.total_signals < 0:
            raise ValueError("total_signals must be >= 0")
        if self.win_count < 0:
            raise ValueError("win_count must be >= 0")
        if self.loss_count < 0:
            raise ValueError("loss_count must be >= 0")
        if self.accuracy is not None and not (0.0 <= self.accuracy <= 1.0):
            raise ValueError("accuracy must be in [0, 1]")
        if self.reputation_score is not None and not (0.0 <= self.reputation_score <= 100.0):
            raise ValueError("reputation_score must be in [0, 100]")

    @property
    def decided_count(self) -> int:
        """Total number of resolved (win + loss) predictions for this author."""
        return self.win_count + self.loss_count

    @property
    def computed_accuracy(self) -> Optional[float]:
        """Win rate as a fraction, or ``None`` if no resolved predictions exist."""
        d = self.decided_count
        return self.win_count / d if d > 0 else None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the author record to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "platform": self.platform,
            "username": self.username,
            "total_signals": self.total_signals,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "accuracy": self.accuracy,
            "roi_if_followed": self.roi_if_followed,
            "sharpe": self.sharpe,
            "reputation_score": self.reputation_score,
            "stats": dict(self.stats),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "updated_at": self.updated_at,
        }


# ── AuthorPrediction ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AuthorPrediction:
    """A single prediction by an author, linked to a signal."""

    id: str
    author_id: str
    ticker: str
    stance: str
    confidence: float
    signal_id: Optional[str] = None
    outcome: Optional[str] = None
    pnl_pct: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.author_id:
            raise ValueError("author_id must be non-empty")
        if not self.ticker:
            raise ValueError("ticker must be non-empty")
        if self.stance not in STANCES:
            raise ValueError(f"Invalid stance: {self.stance!r}. Must be one of {sorted(STANCES)}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1]")
        if self.outcome is not None and self.outcome not in OUTCOMES:
            raise ValueError(f"Invalid outcome: {self.outcome!r}. Must be one of {sorted(OUTCOMES)}")

    @property
    def is_resolved(self) -> bool:
        """``True`` if the prediction has an outcome recorded."""
        return self.outcome is not None

    @property
    def is_win(self) -> bool:
        """``True`` if the prediction outcome is ``"win"``."""
        return self.outcome == "win"

    @property
    def is_loss(self) -> bool:
        """``True`` if the prediction outcome is ``"loss"``."""
        return self.outcome == "loss"

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the prediction to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "author_id": self.author_id,
            "signal_id": self.signal_id,
            "ticker": self.ticker,
            "stance": self.stance,
            "confidence": self.confidence,
            "outcome": self.outcome,
            "pnl_pct": self.pnl_pct,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


# ── ManipulationAlert ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ManipulationAlert:
    """An alert for suspected market manipulation."""

    id: str
    alert_type: str
    tickers: List[str]
    authors: List[str]
    evidence: Dict[str, Any]
    severity: float
    detected_at: float = field(default_factory=time.time)
    resolved: bool = False

    def __post_init__(self) -> None:
        if self.alert_type not in ALERT_TYPES:
            raise ValueError(f"Invalid alert_type: {self.alert_type!r}. Must be one of {sorted(ALERT_TYPES)}")
        if not (0.0 <= self.severity <= 100.0):
            raise ValueError("severity must be in [0, 100]")
        if not self.tickers:
            raise ValueError("tickers must be non-empty")

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the manipulation alert to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "alert_type": self.alert_type,
            "tickers": list(self.tickers),
            "authors": list(self.authors),
            "evidence": dict(self.evidence),
            "severity": self.severity,
            "detected_at": self.detected_at,
            "resolved": self.resolved,
        }


# ── SentimentPropagation ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class SentimentPropagation:
    """Tracks how sentiment for a ticker spreads from one source to another."""

    id: str
    ticker: str
    origin_sub: str
    spread_to: str
    origin_ts: float
    spread_ts: float
    detected_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ValueError("ticker must be non-empty")
        if not self.origin_sub:
            raise ValueError("origin_sub must be non-empty")
        if not self.spread_to:
            raise ValueError("spread_to must be non-empty")
        if self.origin_sub == self.spread_to:
            raise ValueError("origin_sub and spread_to must differ")

    @property
    def lag_seconds(self) -> float:
        """Seconds elapsed between the original mention and cross-community spread."""
        return self.spread_ts - self.origin_ts

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the propagation record to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "ticker": self.ticker,
            "origin_sub": self.origin_sub,
            "spread_to": self.spread_to,
            "origin_ts": self.origin_ts,
            "spread_ts": self.spread_ts,
            "lag_seconds": self.lag_seconds,
            "detected_at": self.detected_at,
        }


# ── AuthorCluster ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AuthorCluster:
    """A cluster of authors with similar trading patterns."""

    id: str
    authors: List[str]
    similarity_score: float
    common_tickers: List[str]
    detected_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not (0.0 <= self.similarity_score <= 1.0):
            raise ValueError("similarity_score must be in [0, 1]")
        if len(self.authors) < 2:
            raise ValueError("cluster must have at least 2 authors")

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the author cluster to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "authors": list(self.authors),
            "similarity_score": self.similarity_score,
            "common_tickers": list(self.common_tickers),
            "detected_at": self.detected_at,
        }


# ── ContrarianSignal ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContrarianSignal:
    """A signal where one or few authors go against consensus."""

    id: str
    ticker: str
    contrarian_stance: str
    consensus_stance: str
    contrarian_authors: List[str]
    consensus_author_count: int
    strength: float
    detected_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.contrarian_stance not in STANCES:
            raise ValueError(f"Invalid contrarian_stance: {self.contrarian_stance!r}")
        if self.consensus_stance not in STANCES:
            raise ValueError(f"Invalid consensus_stance: {self.consensus_stance!r}")
        if not (0.0 <= self.strength <= 1.0):
            raise ValueError("strength must be in [0, 1]")
        if self.contrarian_stance == self.consensus_stance:
            raise ValueError("contrarian_stance and consensus_stance must differ")
        if not self.contrarian_authors:
            raise ValueError("contrarian_authors must be non-empty")

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the contrarian signal to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "ticker": self.ticker,
            "contrarian_stance": self.contrarian_stance,
            "consensus_stance": self.consensus_stance,
            "contrarian_authors": list(self.contrarian_authors),
            "consensus_author_count": self.consensus_author_count,
            "strength": self.strength,
            "detected_at": self.detected_at,
        }
