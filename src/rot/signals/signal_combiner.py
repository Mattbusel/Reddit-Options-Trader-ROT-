"""Signal aggregation and consensus module.

Combines signals from multiple sources (sentiment, technical, fundamental, ML)
into a single consensus signal for a given ticker.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class SignalSource:
    """A named signal source with an associated weight."""
    name: str
    weight: float  # 0-1
    signal_type: str  # 'sentiment' | 'technical' | 'fundamental' | 'ml'

    def __post_init__(self) -> None:
        if not (0.0 <= self.weight <= 1.0):
            raise ValueError(f"SignalSource weight must be in [0, 1], got {self.weight}")
        valid_types = {"sentiment", "technical", "fundamental", "ml"}
        if self.signal_type not in valid_types:
            raise ValueError(f"signal_type must be one of {valid_types}, got {self.signal_type!r}")


@dataclass
class RawSignal:
    """A raw directional signal from a single source."""
    source_name: str
    ticker: str
    direction: int       # 1 = bullish, -1 = bearish, 0 = neutral
    strength: float      # 0-1: how strong the signal is
    confidence: float    # 0-1: how confident the source is
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.direction not in (-1, 0, 1):
            raise ValueError(f"direction must be -1, 0, or 1, got {self.direction}")


@dataclass
class CombinedSignal:
    """Aggregated signal across multiple sources for a single ticker."""
    ticker: str
    direction: float          # weighted direction in [-1, 1]
    strength: float           # 0-1
    confidence: float         # weighted average confidence
    contributing_sources: List[str]
    consensus_score: float    # fraction of signals agreeing with majority direction
    timestamp: float = field(default_factory=time.time)


class SignalCombiner:
    """Aggregates raw signals from multiple sources into consensus signals.

    Usage::

        combiner = SignalCombiner()
        combiner.add_source(SignalSource("reddit_sentiment", weight=0.4, signal_type="sentiment"))
        combiner.add_signal(RawSignal("reddit_sentiment", "AAPL", direction=1, strength=0.8, confidence=0.7))
        combined = combiner.combine("AAPL")
    """

    def __init__(self) -> None:
        self._sources: Dict[str, SignalSource] = {}
        self._signals: List[RawSignal] = []

    def add_source(self, source: SignalSource) -> None:
        """Register a signal source."""
        self._sources[source.name] = source

    def add_signal(self, signal: RawSignal) -> None:
        """Add a raw signal to the internal buffer."""
        self._signals.append(signal)

    def combine(self, ticker: str, lookback_seconds: float = 300.0) -> Optional[CombinedSignal]:
        """Combine recent signals for the given ticker into a consensus signal.

        Args:
            ticker: The ticker symbol to aggregate signals for.
            lookback_seconds: Only consider signals emitted within this window.

        Returns:
            A CombinedSignal, or None if no relevant signals exist.
        """
        now = time.time()
        cutoff = now - lookback_seconds

        recent = [
            s for s in self._signals
            if s.ticker == ticker and s.timestamp >= cutoff
        ]

        if not recent:
            return None

        # --- Weighted direction ---
        # direction_val = Σ(direction * strength * weight * confidence) / Σ(strength * weight * confidence)
        numerator = 0.0
        denominator = 0.0
        for sig in recent:
            source = self._sources.get(sig.source_name)
            w = source.weight if source else 1.0
            contribution = sig.strength * w * sig.confidence
            numerator += sig.direction * contribution
            denominator += contribution

        if denominator == 0.0:
            return None

        weighted_direction = numerator / denominator

        # --- Consensus score ---
        # Fraction of signals that agree with the majority direction sign
        majority_dir = 1 if weighted_direction >= 0 else -1
        agreeing = sum(1 for s in recent if (s.direction * majority_dir) > 0)
        # Neutral signals (direction=0) count as partial agreement
        neutrals = sum(1 for s in recent if s.direction == 0)
        consensus_score = (agreeing + 0.5 * neutrals) / len(recent) if recent else 0.0

        # --- Combined confidence ---
        conf_num = 0.0
        conf_den = 0.0
        for sig in recent:
            source = self._sources.get(sig.source_name)
            w = source.weight if source else 1.0
            conf_num += sig.confidence * w
            conf_den += w
        combined_confidence = conf_num / conf_den if conf_den > 0 else 0.0

        # --- Strength ---
        avg_strength = sum(s.strength for s in recent) / len(recent)

        contributing = list({s.source_name for s in recent})

        return CombinedSignal(
            ticker=ticker,
            direction=weighted_direction,
            strength=avg_strength,
            confidence=combined_confidence,
            contributing_sources=contributing,
            consensus_score=consensus_score,
            timestamp=now,
        )

    def top_opportunities(
        self,
        min_strength: float = 0.6,
        min_consensus: float = 0.7,
        lookback_seconds: float = 300.0,
    ) -> List[CombinedSignal]:
        """Return all tickers with strong, consensus-backed signals.

        Args:
            min_strength: Minimum average signal strength (0-1).
            min_consensus: Minimum consensus score (0-1).
            lookback_seconds: Lookback window for signals.

        Returns:
            List of CombinedSignal sorted by |direction| descending.
        """
        tickers = {s.ticker for s in self._signals}
        results = []
        for ticker in tickers:
            combined = self.combine(ticker, lookback_seconds)
            if combined is None:
                continue
            if combined.strength >= min_strength and combined.consensus_score >= min_consensus:
                results.append(combined)

        results.sort(key=lambda s: abs(s.direction), reverse=True)
        return results

    def signal_agreement_matrix(
        self, lookback_seconds: float = 300.0
    ) -> Dict[str, Dict[str, float]]:
        """Compute pairwise agreement between signal sources.

        For each pair of sources (A, B), the agreement score is the fraction of
        tickers for which both sources emit signals with the same direction sign.

        Returns:
            Nested dict: {source_a: {source_b: agreement_fraction}}.
        """
        now = time.time()
        cutoff = now - lookback_seconds
        recent = [s for s in self._signals if s.timestamp >= cutoff]

        # Group by (source_name, ticker) → latest direction
        latest: Dict[tuple, int] = {}
        for sig in recent:
            key = (sig.source_name, sig.ticker)
            latest[key] = sig.direction

        sources = list(self._sources.keys())
        matrix: Dict[str, Dict[str, float]] = {s: {} for s in sources}

        for i, src_a in enumerate(sources):
            for src_b in sources:
                if src_a == src_b:
                    matrix[src_a][src_b] = 1.0
                    continue

                tickers_a = {t for (s, t) in latest if s == src_a}
                tickers_b = {t for (s, t) in latest if s == src_b}
                common = tickers_a & tickers_b

                if not common:
                    matrix[src_a][src_b] = 0.0
                    continue

                agreements = sum(
                    1
                    for t in common
                    if (latest[(src_a, t)] * latest[(src_b, t)]) > 0
                    or (latest[(src_a, t)] == 0 and latest[(src_b, t)] == 0)
                )
                matrix[src_a][src_b] = agreements / len(common)

        return matrix
