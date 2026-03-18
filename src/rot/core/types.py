from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass(frozen=True)
class Post:
    """An immutable snapshot of a Reddit submission.

    Consumed by: TrendEngine, EventBuilder, NLP pipeline.
    Produced by: RedditIngestor, RSSIngestor.

    Attributes:
        id: Reddit fullname ID (e.g. ``"t3_abc123"``).
        created_utc: Unix timestamp of submission creation.
        subreddit: Subreddit name without the ``r/`` prefix.
        title: Submission title text.
        selftext: Body text of self-posts; empty string for link posts.
        url: Canonical URL of the submission.
        score: Net upvotes at time of ingestion.
        num_comments: Comment count at time of ingestion.
        upvote_ratio: Fraction of upvotes (0.0-1.0), or None if unavailable.
        author: Redditor username; may be ``"[deleted]"`` for removed posts.
        permalink: Relative Reddit URL, e.g. ``"/r/wallstreetbets/comments/..."``.
        flair: Post flair text if set, otherwise None.
        is_crosspost: True when this post is a cross-post from another subreddit.
    """

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
    """An immutable snapshot of a single Reddit comment.

    Consumed by: NLP engine (thread analysis module), EventBuilder.
    Produced by: RedditIngestor (when ``include_comments`` is enabled).

    Attributes:
        id: Reddit comment fullname ID (e.g. ``"t1_xyz789"``).
        created_utc: Unix timestamp of comment creation.
        author: Redditor username.
        body: Raw comment body text.
        score: Net upvotes at time of ingestion.
    """

    id: str
    created_utc: int
    author: str
    body: str
    score: int


@dataclass(frozen=True)
class ThreadSnapshot:
    """A point-in-time capture of a Reddit post and its top comments.

    Consumed by: TrendEngine.detect(), EventBuilder.from_candidate().
    Produced by: RedditIngestor.poll().

    Attributes:
        snapshot_ts: Unix timestamp when this snapshot was taken.
        post: The Reddit submission data at snapshot time.
        top_comments: Top-N comments sorted by score at snapshot time.
            May be empty if ``include_comments`` is disabled in config.
    """

    snapshot_ts: int
    post: Post
    top_comments: List[Comment] = field(default_factory=list)


@dataclass(frozen=True)
class TrendCandidate:
    """A post that has exceeded the trend detection threshold.

    Consumed by: PipelineRunner (stages 3-9), AttentionRadar.
    Produced by: TrendEngine.detect().

    Attributes:
        key: Stable deduplication key, typically the post permalink.
        window_s: Duration of the trend window used to compute this score.
        features: Named feature values used to compute trend_score, e.g.
            ``{"score_velocity": 2.3, "comment_velocity": 1.1}``.
        trend_score: Composite momentum score (higher is more trending).
        reason: Human-readable string explaining why this candidate was emitted.
        snapshot: The underlying thread snapshot at time of detection.
    """

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
"""Enumeration of event classification types.

- ``earnings_rumor``: Unconfirmed earnings expectation or whisper.
- ``product_news``: Product launch, update, or recall.
- ``regulatory``: FDA approval/rejection, SEC action, or legislative change.
- ``squeeze_chatter``: Short-squeeze setup or gamma-squeeze discussion.
- ``macro``: Macroeconomic catalyst (Fed, CPI, jobs report, etc.).
- ``other``: Catch-all for events not matching other types.
"""

Stance = Literal["bullish", "bearish", "mixed", "unknown"]
"""Directional sentiment of an event."""

Horizon = Literal["intraday", "1w", "earnings", "longer", "unknown"]
"""Inferred time horizon for the trade thesis."""


@dataclass(frozen=True)
class Evidence:
    """A single piece of source evidence for an Event.

    Attributes:
        post_id: Reddit post ID of the source submission.
        permalink: Relative Reddit URL to the source post.
        subreddit: Subreddit the post appeared in.
        excerpt: Short text excerpt (<=150 chars) that drove the classification.
    """

    post_id: str
    permalink: str
    subreddit: str
    excerpt: str


@dataclass(frozen=True)
class Event:
    """A classified market event extracted from one or more posts.

    Consumed by: CredibilityScorer, Reasoner, TradeBuilder, storage layer.
    Produced by: EventBuilder.from_candidate().

    Attributes:
        event_type: Classification of the market event.
        entities: Validated ticker symbols mentioned in this event (e.g.
            ``["NVDA", "AMD"]``). Always non-empty after SymbolValidator gating.
        stance: Directional sentiment (bullish, bearish, mixed, unknown).
        time_horizon: Inferred trade time horizon.
        evidence: Source posts and excerpts supporting this event.
        confidence: Credibility score in range 0.0-1.0. Set by
            CredibilityScorer; may be updated by LLM reasoning.
        meta: Extensible metadata bag. Known keys include ``"flair"`` (RSS
            feed label), ``"source"`` (ingestor name), ``"suppression_reason"``.
    """

    event_type: EventType
    entities: List[str]
    stance: Stance
    time_horizon: Horizon
    evidence: List[Evidence]
    confidence: float  # 0..1
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReasoningPacket:
    """Structured LLM reasoning output for an Event.

    Consumed by: TradeBuilder, storage layer, alert dispatcher.
    Produced by: Reasoner.reason() (real LLM call or stub fallback).

    When the circuit breaker is open or the LLM call fails, a stub packet is
    returned with ``raw["stub"] = True``.

    Attributes:
        thesis: One-sentence summary of the trade thesis.
        catalyst_window: Human-readable time frame for the catalyst (e.g.
            ``"next 2 weeks"``, ``"before earnings on March 19"``).
        market_expectation: What the market currently prices in.
        invalidations: Conditions that would invalidate the thesis.
        recommended_structures: Options strategy suggestions from the LLM.
        risk_notes: Key risks and caveats.
        raw: Raw LLM response dict. Contains ``"stub": True`` for fallback
            packets, ``"error": "<msg>"`` for failed calls.
    """

    thesis: str
    catalyst_window: str
    market_expectation: str
    invalidations: List[str]
    recommended_structures: List[str]
    risk_notes: List[str]
    raw: Dict[str, Any] = field(default_factory=dict)


Strategy = Literal["debit_spread", "credit_spread", "iron_condor", "calendar", "straddle", "strangle", "none"]
"""Options strategy type. ``none`` indicates no tradeable structure was found."""


@dataclass(frozen=True)
class OptionLeg:
    """One leg of a multi-leg options position.

    Attributes:
        side: ``"buy"`` (long) or ``"sell"`` (short).
        kind: ``"call"`` or ``"put"``.
        strike: Strike price in USD.
        expiry: Expiry date string in ``YYYY-MM-DD`` format.
        qty: Number of contracts.
    """

    side: Literal["buy", "sell"]
    kind: Literal["call", "put"]
    strike: float
    expiry: str
    qty: int


@dataclass(frozen=True)
class TradeIdea:
    """A fully constructed options trade recommendation.

    Consumed by: storage layer, alert dispatcher, web dashboard.
    Produced by: TradeBuilder.build().

    When the TradeBuilder cannot construct a valid trade (e.g. market cap too
    low, no options chain data, informational-only source), ``strategy`` is
    ``"none"``, ``legs`` is empty, and ``do_not_trade_reasons`` lists the
    blocking conditions.

    Attributes:
        underlying: Ticker symbol for the underlying equity.
        strategy: The options structure type.
        legs: Ordered list of option legs comprising the position.
        max_loss: Maximum dollar loss if the position expires worthless.
        thesis: One-sentence rationale for the trade.
        time_stop: Date or event by which the thesis should resolve.
        quality_score: Composite quality score 0.0-1.0 combining confidence,
            market data quality, and structural soundness.
        do_not_trade_reasons: Non-empty list of blocking reasons when
            ``strategy == "none"``.
        meta: Extensible metadata bag.
    """

    underlying: str
    strategy: Strategy
    legs: List[OptionLeg]
    max_loss: float
    thesis: str
    time_stop: str
    quality_score: float
    do_not_trade_reasons: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
