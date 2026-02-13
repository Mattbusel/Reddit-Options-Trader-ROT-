"""NLP type definitions for the ROT custom NLP engine.

All dataclasses are frozen (immutable) following the pattern in rot.core.types.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple


# ── Tokenizer Types ──

TokenType = Literal[
    "word", "cashtag", "emoji", "url", "number", "dollar_amount",
    "punctuation", "hashtag", "mention", "options_contract", "unknown",
]


@dataclass(frozen=True)
class Token:
    """A single token produced by the financial tokenizer."""
    text: str               # normalized text (e.g., "TSLA", "ROCKET_EMOJI")
    raw: str                # original text before normalization
    token_type: TokenType
    start: int              # character offset in source
    end: int                # character offset end
    meta: Dict[str, Any] = field(default_factory=dict)
    # meta keys: is_caps (bool), repeat_count (int), is_negation (bool),
    #            is_intensifier (bool), is_diminisher (bool), strike (float),
    #            option_kind (str), expiry_text (str)


# ── Sentiment Types ──

@dataclass(frozen=True)
class SentimentSignal:
    """A single sentiment indicator found in text."""
    token_text: str
    raw_text: str
    polarity: float         # -1.0 to +1.0
    intensity: float        # 0.0 to 1.0
    category: str           # "lexicon", "emoji", "negation", "intensifier", "sarcasm"
    span: Tuple[int, int]   # (start, end) character offsets
    context: str            # surrounding text snippet


@dataclass(frozen=True)
class SentimentResult:
    """Complete sentiment analysis for a piece of text."""
    polarity: float              # -1.0 (max bearish) to +1.0 (max bullish)
    intensity: float             # 0.0 (no signal) to 1.0 (max strength)
    conviction: float            # 0.0 (hedging) to 1.0 (absolute conviction)
    sarcasm_probability: float   # 0.0 to 1.0
    raw_signals: List[SentimentSignal] = field(default_factory=list)
    bullish_count: int = 0
    bearish_count: int = 0
    negated_count: int = 0


# ── Entity Types ──

@dataclass(frozen=True)
class ResolvedEntity:
    """A ticker or financial entity extracted from text."""
    symbol: str                 # canonical ticker, e.g., "TSLA"
    raw_text: str               # original mention
    resolution_method: str      # "cashtag", "bare_ticker", "implicit", "sector", "alias"
    confidence: float           # 0.0 to 1.0
    span: Tuple[int, int]       # character offsets
    sentiment_toward: Optional[str] = None  # "bullish", "bearish", or None


@dataclass(frozen=True)
class OptionsEntity:
    """An options contract reference extracted from text."""
    ticker_context: Optional[str]
    strike: Optional[float]
    kind: Optional[Literal["call", "put"]]
    expiry_text: Optional[str]
    raw_text: str
    span: Tuple[int, int]


@dataclass(frozen=True)
class PositionEntity:
    """A position description extracted from text."""
    position_type: Literal["long", "short", "neutral", "unknown"]
    quantity: Optional[int]
    instrument: Optional[str]  # "shares", "contracts", "calls", "puts"
    raw_text: str
    span: Tuple[int, int]


# ── Event Classification Types ──

@dataclass(frozen=True)
class ClassifiedEvent:
    """A single event category with confidence score."""
    category: str              # e.g., "earnings_rumor", "squeeze_chatter"
    confidence: float          # 0.0 to 1.0
    evidence_spans: List[Tuple[int, int]] = field(default_factory=list)
    matched_terms: List[str] = field(default_factory=list)


# ── Temporal Types ──

Tense = Literal["past", "present", "future", "unknown"]


@dataclass(frozen=True)
class TemporalResult:
    """Temporal analysis of text: tense, actionability, urgency."""
    dominant_tense: Tense
    actionability: float       # 0.0 (not actionable) to 1.0 (urgent/current)
    urgency: float             # 0.0 to 1.0
    time_expressions: List[str] = field(default_factory=list)
    tense_signals: Dict[str, int] = field(default_factory=dict)


# ── Thread Analysis Types ──

@dataclass(frozen=True)
class CommentAnalysis:
    """Sentiment analysis of a single comment."""
    comment_id: str
    author: str
    score: int
    polarity: float
    conviction: float
    sarcasm_probability: float
    length: int


@dataclass(frozen=True)
class ThreadResult:
    """Aggregate analysis of a post's comment thread."""
    consensus_polarity: float     # -1.0 to +1.0
    consensus_score: float        # 0.0 to 1.0 (how much commenters agree)
    agreement_with_op: float      # 0.0 to 1.0 (how much comments agree with OP)
    contrarian_detected: bool
    top_comment_aligns: Optional[bool]  # None if no comments
    comment_count_analyzed: int
    comment_analyses: List[CommentAnalysis] = field(default_factory=list)


# ── Master NLP Result ──

@dataclass(frozen=True)
class NLPResult:
    """Complete NLP analysis output for one post."""
    # Sentiment
    sentiment: SentimentResult
    # Entities
    entities: List[ResolvedEntity] = field(default_factory=list)
    options_entities: List[OptionsEntity] = field(default_factory=list)
    positions: List[PositionEntity] = field(default_factory=list)
    # Classification
    classifications: List[ClassifiedEvent] = field(default_factory=list)
    # Temporal
    temporal: Optional[TemporalResult] = None
    # Thread
    thread: Optional[ThreadResult] = None
    # Derived convenience fields
    ticker_symbols: List[str] = field(default_factory=list)
    primary_stance: str = "unknown"
    primary_event_type: str = "other"
    # Debug
    token_count: int = 0
    processing_time_ms: float = 0.0
