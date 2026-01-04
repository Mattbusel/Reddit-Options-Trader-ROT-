from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass(frozen=True)
class Post:
    id: str
    created_utc: int
    subreddit: str
    title: str
    selftext: str
    url: str
    score: int
    num_comments: int
    upvote_ratio: Optional[float]
    author: str
    permalink: str
    flair: Optional[str] = None
    is_crosspost: bool = False


@dataclass(frozen=True)
class Comment:
    id: str
    created_utc: int
    author: str
    body: str
    score: int


@dataclass(frozen=True)
class ThreadSnapshot:
    snapshot_ts: int
    post: Post
    top_comments: List[Comment] = field(default_factory=list)


@dataclass(frozen=True)
class TrendCandidate:
    key: str
    window_s: int
    features: Dict[str, float]
    trend_score: float
    reason: str
    snapshot: ThreadSnapshot


EventType = Literal[
    "earnings_rumor",
    "product_news",
    "regulatory",
    "squeeze_chatter",
    "macro",
    "other",
]
Stance = Literal["bullish", "bearish", "mixed", "unknown"]
Horizon = Literal["intraday", "1w", "earnings", "longer", "unknown"]


@dataclass(frozen=True)
class Evidence:
    post_id: str
    permalink: str
    subreddit: str
    excerpt: str


@dataclass(frozen=True)
class Event:
    event_type: EventType
    entities: List[str]
    stance: Stance
    time_horizon: Horizon
    evidence: List[Evidence]
    confidence: float  # 0..1
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReasoningPacket:
    thesis: str
    catalyst_window: str
    market_expectation: str
    invalidations: List[str]
    recommended_structures: List[str]
    risk_notes: List[str]
    raw: Dict[str, Any] = field(default_factory=dict)


Strategy = Literal["debit_spread", "calendar", "straddle", "strangle", "none"]


@dataclass(frozen=True)
class OptionLeg:
    side: Literal["buy", "sell"]
    kind: Literal["call", "put"]
    strike: float
    expiry: str
    qty: int


@dataclass(frozen=True)
class TradeIdea:
    underlying: str
    strategy: Strategy
    legs: List[OptionLeg]
    max_loss: float
    thesis: str
    time_stop: str
    quality_score: float
    do_not_trade_reasons: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
