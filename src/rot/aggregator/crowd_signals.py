"""Crowdsourced signal aggregator across multiple Reddit communities.

Aggregates sentiment and trade signals from r/wallstreetbets, r/options,
r/stocks, r/investing, and r/SecurityAnalysis simultaneously.  Communities
are weighted by their historical accuracy (updated via outcome feedback).
Inter-community divergence is detected and flagged as contrarian signals.

Key components
--------------
* :class:`CommunityProfile` -- metadata and accuracy history for a subreddit.
* :class:`AggregatedSignal` -- weighted consensus signal for a ticker.
* :class:`DivergenceAlert` -- contrarian signal when communities disagree.
* :class:`CrowdSignalAggregator` -- main aggregation engine.

Example::

    from rot.aggregator.crowd_signals import CrowdSignalAggregator

    agg = CrowdSignalAggregator()
    agg.ingest(
        subreddit="wallstreetbets",
        ticker="NVDA",
        sentiment=0.85,
        confidence=0.7,
        post_id="t3_abc",
    )
    signal = agg.aggregate("NVDA")
    print(signal.consensus_sentiment, signal.divergence_detected)
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Community definitions
# ---------------------------------------------------------------------------

# Default community profiles with prior accuracy weights
_DEFAULT_COMMUNITIES: Dict[str, Dict[str, Any]] = {
    "wallstreetbets": {
        "description": "Retail speculation, meme stocks, high-conviction YOLO trades.",
        "base_weight": 1.0,
        "typical_horizon": "short",   # 1-5 days
        "contrarian_indicator": False,
    },
    "options": {
        "description": "Retail options strategies, IV discussion, spreads.",
        "base_weight": 1.2,
        "typical_horizon": "short",
        "contrarian_indicator": False,
    },
    "stocks": {
        "description": "Mix of retail fundamentals and technical analysis.",
        "base_weight": 0.9,
        "typical_horizon": "medium",  # 1-4 weeks
        "contrarian_indicator": False,
    },
    "investing": {
        "description": "Long-term buy-and-hold, index funds, value investing.",
        "base_weight": 0.7,
        "typical_horizon": "long",    # months
        "contrarian_indicator": False,
    },
    "SecurityAnalysis": {
        "description": "Professional-grade fundamental analysis, DCF, 10-Ks.",
        "base_weight": 1.4,
        "typical_horizon": "long",
        "contrarian_indicator": False,
    },
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CommunityProfile:
    """Metadata and dynamic accuracy weight for a single subreddit.

    Attributes:
        name: Subreddit name (without r/).
        description: Short description.
        base_weight: Initial importance weight.
        accuracy_weight: Dynamically updated weight based on signal accuracy.
        correct_calls: Historical count of directionally correct signals.
        total_calls: Historical count of all signals with known outcomes.
        typical_horizon: Signal time horizon (``"short"``, ``"medium"``,
            ``"long"``).
    """

    name: str
    description: str
    base_weight: float = 1.0
    accuracy_weight: float = 1.0
    correct_calls: int = 0
    total_calls: int = 0
    typical_horizon: str = "short"

    @property
    def historical_accuracy(self) -> float:
        """Historical directional accuracy in [0, 1]."""
        if self.total_calls == 0:
            return 0.5  # Prior: coin flip
        return self.correct_calls / self.total_calls

    @property
    def effective_weight(self) -> float:
        """Combined base × accuracy weight."""
        return self.base_weight * self.accuracy_weight


@dataclass
class CommunitySignal:
    """A single signal data point from one community for one ticker.

    Attributes:
        subreddit: Source subreddit name.
        ticker: Ticker symbol.
        sentiment: Sentiment value in [-1, 1].
        confidence: Model confidence in [0, 1].
        post_id: Reddit post identifier.
        timestamp: Unix timestamp.
    """

    subreddit: str
    ticker: str
    sentiment: float
    confidence: float
    post_id: str
    timestamp: float


@dataclass
class AggregatedSignal:
    """Weighted consensus signal for a ticker across all communities.

    Attributes:
        ticker: Ticker symbol.
        consensus_sentiment: Weighted average sentiment in [-1, 1].
        consensus_confidence: Weighted average confidence.
        community_breakdown: Dict of subreddit → sentiment for this ticker.
        dominant_community: Community with the highest effective weight.
        divergence_detected: True when communities disagree significantly.
        divergence_description: Human-readable divergence explanation.
        bullish_communities: Communities with sentiment > 0.1.
        bearish_communities: Communities with sentiment < -0.1.
        signal_strength: Absolute value of consensus_sentiment * confidence.
        timestamp: Unix timestamp of aggregation.
    """

    ticker: str
    consensus_sentiment: float
    consensus_confidence: float
    community_breakdown: Dict[str, float]
    dominant_community: str
    divergence_detected: bool
    divergence_description: str
    bullish_communities: List[str]
    bearish_communities: List[str]
    signal_strength: float
    timestamp: float


@dataclass
class DivergenceAlert:
    """Contrarian signal when major communities disagree on a ticker.

    Attributes:
        ticker: Ticker symbol.
        bullish_communities: Communities with positive sentiment.
        bearish_communities: Communities with negative sentiment.
        wsb_direction: Direction of r/wallstreetbets (``"bull"`` / ``"bear"``).
        institutional_direction: Direction of r/SecurityAnalysis / r/investing.
        divergence_score: Magnitude of disagreement in [0, 1].
        contrarian_signal: Recommended contrarian position based on divergence.
        timestamp: Unix timestamp.
    """

    ticker: str
    bullish_communities: List[str]
    bearish_communities: List[str]
    wsb_direction: Optional[str]
    institutional_direction: Optional[str]
    divergence_score: float
    contrarian_signal: str
    timestamp: float


# ---------------------------------------------------------------------------
# Main aggregator
# ---------------------------------------------------------------------------


class CrowdSignalAggregator:
    """Aggregates options/sentiment signals from multiple Reddit communities.

    Args:
        communities: Dict of subreddit name → config dict.  Defaults to the
            five standard communities when not supplied.
        divergence_threshold: Minimum absolute spread between community
            sentiment averages to trigger a divergence alert (default 0.4).
        signal_window_sec: Max age of signals included in aggregation (default
            24 hours).
        ema_alpha: EMA decay applied to community accuracy weights on feedback.
    """

    def __init__(
        self,
        communities: Optional[Dict[str, Dict[str, Any]]] = None,
        divergence_threshold: float = 0.4,
        signal_window_sec: float = 86_400.0,
        ema_alpha: float = 0.1,
    ) -> None:
        self.divergence_threshold = divergence_threshold
        self.signal_window_sec = signal_window_sec
        self.ema_alpha = ema_alpha

        raw = communities or _DEFAULT_COMMUNITIES
        self._profiles: Dict[str, CommunityProfile] = {}
        for name, cfg in raw.items():
            self._profiles[name] = CommunityProfile(
                name=name,
                description=cfg.get("description", ""),
                base_weight=cfg.get("base_weight", 1.0),
                typical_horizon=cfg.get("typical_horizon", "short"),
            )

        # ticker -> list of CommunitySignal
        self._signals: Dict[str, List[CommunitySignal]] = {}

        log.info(
            "crowd_signals.init",
            communities=list(self._profiles.keys()),
            divergence_threshold=divergence_threshold,
        )

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest(
        self,
        subreddit: str,
        ticker: str,
        sentiment: float,
        confidence: float = 0.5,
        post_id: str = "",
        timestamp: Optional[float] = None,
    ) -> CommunitySignal:
        """Record a signal from a community for a ticker.

        Args:
            subreddit: Source subreddit name (r/ prefix optional).
            ticker: Ticker symbol.
            sentiment: Post/thread sentiment in [-1, 1].
            confidence: NLP confidence score in [0, 1].
            post_id: Reddit post ID.
            timestamp: Unix timestamp; defaults to now.

        Returns:
            The recorded :class:`CommunitySignal`.
        """
        clean_sub = subreddit.lstrip("r/").lower()
        # Auto-register unknown communities with default weight
        if clean_sub not in self._profiles:
            self._profiles[clean_sub] = CommunityProfile(
                name=clean_sub,
                description="Auto-registered community.",
                base_weight=0.5,
            )

        sig = CommunitySignal(
            subreddit=clean_sub,
            ticker=ticker.upper(),
            sentiment=max(-1.0, min(1.0, sentiment)),
            confidence=max(0.0, min(1.0, confidence)),
            post_id=post_id or f"auto_{int(time.time())}",
            timestamp=timestamp or time.time(),
        )
        bucket = self._signals.setdefault(ticker.upper(), [])
        bucket.append(sig)

        # Prune old signals
        cutoff = time.time() - self.signal_window_sec
        self._signals[ticker.upper()] = [
            s for s in bucket if s.timestamp >= cutoff
        ]

        log.debug(
            "crowd_signals.ingested",
            subreddit=clean_sub,
            ticker=ticker,
            sentiment=round(sentiment, 3),
        )
        return sig

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(self, ticker: str) -> Optional[AggregatedSignal]:
        """Compute the weighted consensus signal for *ticker*.

        Args:
            ticker: Ticker symbol.

        Returns:
            :class:`AggregatedSignal` or ``None`` when no signals exist.
        """
        signals = self._signals.get(ticker.upper(), [])
        if not signals:
            return None

        # Group by community and compute per-community weighted average
        community_avg: Dict[str, Tuple[float, float]] = {}  # sub -> (sentiment, confidence)
        for sub, prof in self._profiles.items():
            sub_sigs = [s for s in signals if s.subreddit == sub]
            if not sub_sigs:
                continue
            w_sent = sum(s.sentiment * s.confidence for s in sub_sigs)
            w_conf = sum(s.confidence for s in sub_sigs)
            if w_conf < 1e-9:
                continue
            community_avg[sub] = (w_sent / w_conf, w_conf / len(sub_sigs))

        if not community_avg:
            return None

        # Weighted consensus across communities
        total_weight = 0.0
        weighted_sentiment = 0.0
        weighted_confidence = 0.0

        community_breakdown: Dict[str, float] = {}
        for sub, (sent, conf) in community_avg.items():
            prof = self._profiles[sub]
            w = prof.effective_weight * conf
            weighted_sentiment += sent * w
            weighted_confidence += conf * w
            total_weight += w
            community_breakdown[sub] = round(sent, 4)

        if total_weight < 1e-9:
            return None

        consensus_sent = weighted_sentiment / total_weight
        consensus_conf = weighted_confidence / total_weight

        # Dominant community by effective weight
        dominant = max(
            community_breakdown.keys(),
            key=lambda s: self._profiles[s].effective_weight,
        )

        # Divergence detection
        div_detected, div_desc = self._detect_divergence(community_breakdown)

        bullish = [s for s, v in community_breakdown.items() if v > 0.1]
        bearish = [s for s, v in community_breakdown.items() if v < -0.1]

        signal = AggregatedSignal(
            ticker=ticker.upper(),
            consensus_sentiment=round(consensus_sent, 4),
            consensus_confidence=round(consensus_conf, 4),
            community_breakdown=community_breakdown,
            dominant_community=dominant,
            divergence_detected=div_detected,
            divergence_description=div_desc,
            bullish_communities=bullish,
            bearish_communities=bearish,
            signal_strength=round(abs(consensus_sent) * consensus_conf, 4),
            timestamp=time.time(),
        )

        log.info(
            "crowd_signals.aggregated",
            ticker=ticker,
            consensus=round(consensus_sent, 3),
            divergence=div_detected,
            communities=len(community_breakdown),
        )
        return signal

    def divergence_alerts(self, min_score: float = 0.3) -> List[DivergenceAlert]:
        """Return divergence alerts for all tracked tickers.

        Args:
            min_score: Minimum divergence score to include.

        Returns:
            List of :class:`DivergenceAlert` sorted by divergence_score desc.
        """
        alerts: List[DivergenceAlert] = []
        for ticker in self._signals:
            signal = self.aggregate(ticker)
            if signal is None or not signal.divergence_detected:
                continue

            wsb_sent = signal.community_breakdown.get("wallstreetbets")
            wsb_dir = None
            if wsb_sent is not None:
                wsb_dir = "bull" if wsb_sent > 0.1 else ("bear" if wsb_sent < -0.1 else None)

            inst_sents = [
                signal.community_breakdown.get(s)
                for s in ("securityanalysis", "investing")
                if s in signal.community_breakdown
            ]
            inst_mean = (
                sum(v for v in inst_sents if v is not None) / len(inst_sents)
                if inst_sents
                else None
            )
            inst_dir = None
            if inst_mean is not None:
                inst_dir = "bull" if inst_mean > 0.1 else ("bear" if inst_mean < -0.1 else None)

            div_score = self._compute_divergence_score(signal.community_breakdown)
            if div_score < min_score:
                continue

            # Contrarian: if WSB is bullish while institutional is bearish, consider puts
            if wsb_dir == "bull" and inst_dir == "bear":
                contrarian = "contrarian_bear: WSB euphoria vs institutional caution"
            elif wsb_dir == "bear" and inst_dir == "bull":
                contrarian = "contrarian_bull: WSB panic vs institutional confidence"
            else:
                contrarian = "monitor: divergence without clear contrarian setup"

            alerts.append(
                DivergenceAlert(
                    ticker=ticker,
                    bullish_communities=signal.bullish_communities,
                    bearish_communities=signal.bearish_communities,
                    wsb_direction=wsb_dir,
                    institutional_direction=inst_dir,
                    divergence_score=round(div_score, 3),
                    contrarian_signal=contrarian,
                    timestamp=time.time(),
                )
            )

        alerts.sort(key=lambda a: a.divergence_score, reverse=True)
        return alerts

    # ------------------------------------------------------------------
    # Accuracy feedback
    # ------------------------------------------------------------------

    def record_outcome(
        self, subreddit: str, correct: bool
    ) -> None:
        """Update a community's accuracy weight based on a signal outcome.

        Args:
            subreddit: The community whose signal is being evaluated.
            correct: True when the community's signal was directionally correct.
        """
        clean = subreddit.lstrip("r/").lower()
        prof = self._profiles.get(clean)
        if prof is None:
            return

        prof.total_calls += 1
        if correct:
            prof.correct_calls += 1

        # Update EMA accuracy weight: Bayesian-like update
        acc = prof.historical_accuracy
        # Scale weight: [0.5 accuracy → 0.5x weight] to [1.0 accuracy → 2x weight]
        new_acc_weight = max(0.1, 2.0 * acc)
        prof.accuracy_weight = (
            (1 - self.ema_alpha) * prof.accuracy_weight
            + self.ema_alpha * new_acc_weight
        )
        log.info(
            "crowd_signals.outcome_recorded",
            subreddit=clean,
            correct=correct,
            accuracy=round(acc, 3),
            new_weight=round(prof.accuracy_weight, 3),
        )

    def community_weights(self) -> Dict[str, float]:
        """Return effective weights for all communities."""
        return {
            name: round(prof.effective_weight, 4)
            for name, prof in self._profiles.items()
        }

    def tracked_tickers(self) -> List[str]:
        """Return all tickers with at least one signal in the window."""
        now = time.time()
        cutoff = now - self.signal_window_sec
        return [
            t for t, sigs in self._signals.items()
            if any(s.timestamp >= cutoff for s in sigs)
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_divergence(
        self, breakdown: Dict[str, float]
    ) -> Tuple[bool, str]:
        """Detect whether communities significantly disagree.

        Args:
            breakdown: Dict of subreddit → sentiment score.

        Returns:
            Tuple (divergence_detected, description).
        """
        if len(breakdown) < 2:
            return False, ""

        values = list(breakdown.values())
        max_v = max(values)
        min_v = min(values)
        spread = max_v - min_v

        if spread < self.divergence_threshold:
            return False, ""

        bull_subs = [s for s, v in breakdown.items() if v > 0.1]
        bear_subs = [s for s, v in breakdown.items() if v < -0.1]

        if not bull_subs or not bear_subs:
            return False, ""

        desc = (
            f"Community divergence (spread={spread:.2f}): "
            f"Bullish: {', '.join(bull_subs)}; "
            f"Bearish: {', '.join(bear_subs)}."
        )
        log.info("crowd_signals.divergence_detected", spread=round(spread, 3))
        return True, desc

    @staticmethod
    def _compute_divergence_score(breakdown: Dict[str, float]) -> float:
        """Compute a divergence score as normalised sentiment std-dev."""
        if len(breakdown) < 2:
            return 0.0
        vals = list(breakdown.values())
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        return min(1.0, math.sqrt(var))
