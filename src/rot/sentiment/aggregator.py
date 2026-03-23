"""Sentiment Aggregator — combines multiple sentiment sources into a composite signal.

Combines Reddit sentiment with news, options flow, and technical indicator signals.
Applies confidence weighting and recency decay before producing a composite score
and a human-readable signal strength label.

Typical usage::

    from rot.sentiment.aggregator import (
        SentimentAggregator,
        SentimentScore,
        SentimentSource,
    )
    import datetime

    scores = [
        SentimentScore(
            source=SentimentSource.REDDIT,
            ticker="AAPL",
            score=0.65,
            confidence=0.8,
            timestamp=datetime.datetime.utcnow(),
        ),
        SentimentScore(
            source=SentimentSource.NEWS,
            ticker="AAPL",
            score=0.30,
            confidence=0.6,
            timestamp=datetime.datetime.utcnow(),
        ),
    ]

    agg = SentimentAggregator()
    result = agg.aggregate(scores)
    print(result.composite_score, result.signal_strength)
"""

from __future__ import annotations

import datetime
import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SentimentSource(str, Enum):
    """Supported sentiment data sources."""

    REDDIT = "reddit"
    NEWS = "news"
    OPTIONS_FLOW = "options_flow"
    TECHNICAL_INDICATOR = "technical_indicator"


# Signal strength thresholds
_STRONG_BULL_THRESHOLD = 0.6
_BULL_THRESHOLD = 0.2
_BEAR_THRESHOLD = -0.2
_STRONG_BEAR_THRESHOLD = -0.6

# Default source weights when not overridden
_DEFAULT_SOURCE_WEIGHTS: Dict[SentimentSource, float] = {
    SentimentSource.REDDIT: 1.0,
    SentimentSource.NEWS: 1.2,
    SentimentSource.OPTIONS_FLOW: 1.5,
    SentimentSource.TECHNICAL_INDICATOR: 0.8,
}

# Recency decay half-life in hours (scores older than this are halved)
_DEFAULT_DECAY_HALFLIFE_HOURS = 24.0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SentimentScore:
    """A single sentiment score from one source for one ticker.

    Attributes:
        source:     The data source producing this score.
        ticker:     The underlying equity ticker (e.g. "AAPL").
        score:      Sentiment polarity in [-1, 1].  +1 is maximally bullish.
        confidence: Confidence in [0, 1] — used as a weight multiplier.
        timestamp:  UTC datetime when this score was produced.
    """

    source: SentimentSource
    ticker: str
    score: float
    confidence: float
    timestamp: datetime.datetime

    def __post_init__(self) -> None:
        if not (-1.0 <= self.score <= 1.0):
            raise ValueError(
                f"SentimentScore.score must be in [-1, 1], got {self.score}"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"SentimentScore.confidence must be in [0, 1], got {self.confidence}"
            )

    def age_hours(self, reference: Optional[datetime.datetime] = None) -> float:
        """Return how many hours ago this score was produced."""
        if reference is None:
            reference = datetime.datetime.utcnow()
        delta = reference - self.timestamp
        return max(0.0, delta.total_seconds() / 3600.0)


@dataclass
class AggregatedSentiment:
    """Composite sentiment output for a single ticker.

    Attributes:
        ticker:           The underlying equity ticker.
        composite_score:  Weighted average of all input scores in [-1, 1].
        source_breakdown: Dict mapping source name to its contribution score.
        signal_strength:  Human-readable regime: ``STRONG_BULL``, ``BULL``,
                          ``NEUTRAL``, ``BEAR``, or ``STRONG_BEAR``.
        n_sources:        Number of distinct sources that contributed.
        total_weight:     Sum of all weights used in the aggregation.
    """

    ticker: str
    composite_score: float
    source_breakdown: Dict[str, float]
    signal_strength: str
    n_sources: int
    total_weight: float

    def is_bullish(self) -> bool:
        return self.composite_score > 0.0

    def is_bearish(self) -> bool:
        return self.composite_score < 0.0

    def is_strong(self) -> bool:
        return self.signal_strength in ("STRONG_BULL", "STRONG_BEAR")


def _score_to_signal_strength(score: float) -> str:
    """Map a composite score to a signal strength label."""
    if score > _STRONG_BULL_THRESHOLD:
        return "STRONG_BULL"
    if score > _BULL_THRESHOLD:
        return "BULL"
    if score < _STRONG_BEAR_THRESHOLD:
        return "STRONG_BEAR"
    if score < _BEAR_THRESHOLD:
        return "BEAR"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# SentimentAggregator
# ---------------------------------------------------------------------------


class SentimentAggregator:
    """Combine multiple sentiment scores into a single composite signal.

    Aggregation formula
    -------------------
    For each score ``s_i`` with confidence ``c_i``, source weight ``w_i``, and
    recency decay factor ``d_i``:

        effective_weight_i = c_i * w_i * d_i
        composite_score    = sum(s_i * effective_weight_i) / sum(effective_weight_i)

    Recency decay
    -------------
    ``d_i = 0.5 ^ (age_hours / halflife_hours)``

    Scores contributed more than ``halflife_hours`` ago are down-weighted
    exponentially.

    Args:
        source_weights:     Dict overriding the default per-source weight multipliers.
        decay_halflife_hours: Half-life in hours for the recency decay function.
                              Set to ``float("inf")`` to disable decay.
        reference_time:     Fixed reference time for decay computation.  If None,
                            the current UTC time is used at aggregation time.
    """

    def __init__(
        self,
        source_weights: Optional[Dict[SentimentSource, float]] = None,
        decay_halflife_hours: float = _DEFAULT_DECAY_HALFLIFE_HOURS,
        reference_time: Optional[datetime.datetime] = None,
    ) -> None:
        self._source_weights: Dict[SentimentSource, float] = dict(_DEFAULT_SOURCE_WEIGHTS)
        if source_weights:
            self._source_weights.update(source_weights)
        self._decay_halflife_hours = decay_halflife_hours
        self._reference_time = reference_time

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def aggregate(
        self,
        scores: List[SentimentScore],
        ticker: Optional[str] = None,
    ) -> AggregatedSentiment:
        """Aggregate a list of SentimentScore objects into one composite result.

        Args:
            scores: List of sentiment scores (may span multiple tickers).
            ticker: If provided, filter scores to this ticker only.
                    If None, uses the ticker from the first score.

        Returns:
            AggregatedSentiment with composite score and signal strength.

        Raises:
            ValueError: If scores is empty (or no scores match the ticker filter).
        """
        if not scores:
            raise ValueError("aggregate() requires at least one SentimentScore")

        if ticker is None:
            ticker = scores[0].ticker

        filtered = [s for s in scores if s.ticker == ticker]
        if not filtered:
            raise ValueError(
                f"No SentimentScore objects found for ticker '{ticker}'"
            )

        ref = self._reference_time or datetime.datetime.utcnow()

        weighted_sum = 0.0
        total_weight = 0.0
        source_weighted_scores: Dict[str, float] = {}
        source_total_weights: Dict[str, float] = {}

        for s in filtered:
            source_w = self._source_weights.get(s.source, 1.0)
            decay = self._recency_decay(s.age_hours(ref))
            effective_w = s.confidence * source_w * decay

            weighted_sum += s.score * effective_w
            total_weight += effective_w

            sname = s.source.value
            source_weighted_scores[sname] = (
                source_weighted_scores.get(sname, 0.0) + s.score * effective_w
            )
            source_total_weights[sname] = (
                source_total_weights.get(sname, 0.0) + effective_w
            )

        if total_weight == 0.0:
            composite = 0.0
        else:
            composite = weighted_sum / total_weight

        # Clamp to [-1, 1] for floating-point safety
        composite = max(-1.0, min(1.0, composite))

        # Build per-source breakdown (contribution score per source)
        breakdown: Dict[str, float] = {}
        for sname, sw in source_weighted_scores.items():
            tw = source_total_weights.get(sname, 0.0)
            breakdown[sname] = sw / tw if tw > 0 else 0.0

        distinct_sources = len({s.source for s in filtered})

        return AggregatedSentiment(
            ticker=ticker,
            composite_score=composite,
            source_breakdown=breakdown,
            signal_strength=_score_to_signal_strength(composite),
            n_sources=distinct_sources,
            total_weight=total_weight,
        )

    def aggregate_all_tickers(
        self,
        scores: List[SentimentScore],
    ) -> Dict[str, AggregatedSentiment]:
        """Aggregate scores for every ticker present in the list.

        Returns:
            Dict mapping ticker to its AggregatedSentiment.
        """
        tickers = {s.ticker for s in scores}
        return {t: self.aggregate(scores, ticker=t) for t in sorted(tickers)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _recency_decay(self, age_hours: float) -> float:
        """Compute the recency decay factor for a score of the given age."""
        if self._decay_halflife_hours == float("inf") or self._decay_halflife_hours <= 0:
            return 1.0
        return math.pow(0.5, age_hours / self._decay_halflife_hours)
