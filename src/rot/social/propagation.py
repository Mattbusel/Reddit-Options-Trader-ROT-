"""Sentiment propagation tracker for the Social Intelligence Network.

Tracks how sentiment for a ticker spreads across subreddits and platforms.
When a signal for a ticker appears on one source and later appears on another,
a SentimentPropagation event is recorded capturing the origin, destination,
timestamps, and computed lag.

This enables identification of leading vs lagging sources, virality scoring,
and early detection of cross-platform sentiment waves.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from rot.social.types import SentimentPropagation


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PropagationConfig:
    """Configuration for the propagation tracker.

    Attributes:
        window_hours: Time window in hours for propagation tracking.
        min_lag_seconds: Minimum lag in seconds to count as propagation
            rather than simultaneous posting.
        max_lag_seconds: Maximum lag in seconds (24h default) to consider
            two signals as related propagation rather than independent events.
        min_signals_per_source: Minimum signals from a source to count as
            an established presence for that ticker.
        max_tracked_tickers: LRU cap on the number of tickers tracked
            concurrently. When exceeded, the least recently used ticker
            is evicted.
    """

    window_hours: int = 24
    min_lag_seconds: float = 60.0
    max_lag_seconds: float = 86400.0
    min_signals_per_source: int = 2
    max_tracked_tickers: int = 200


# ---------------------------------------------------------------------------
# Internal per-ticker, per-source presence record
# ---------------------------------------------------------------------------

@dataclass
class _TickerPresence:
    """Mutable record tracking a ticker's presence on a single source.

    Attributes:
        source: Subreddit or platform name (e.g. "wallstreetbets", "stocktwits").
        first_seen: Unix timestamp of the earliest signal for this ticker
            from this source.
        signal_count: Running count of signals received.
        stance: Dominant stance observed from this source for this ticker.
        last_updated: Unix timestamp of the most recent signal.
    """

    source: str
    first_seen: float
    signal_count: int = 1
    stance: str = "unknown"
    last_updated: float = 0.0

    def __post_init__(self) -> None:
        if self.last_updated == 0.0:
            self.last_updated = self.first_seen


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gen_id() -> str:
    """Generate a short random hex identifier."""
    return uuid.uuid4().hex[:16]


def _cutoff_ts(window_hours: int) -> float:
    """Return the unix timestamp for *window_hours* ago."""
    return time.time() - window_hours * 3600.0


# ---------------------------------------------------------------------------
# PropagationTracker
# ---------------------------------------------------------------------------

class PropagationTracker:
    """Tracks cross-source sentiment propagation for tickers.

    As signals arrive, the tracker records which source first mentioned a
    ticker and detects when that sentiment subsequently appears on other
    sources within the configured time window.  Each such cross-source
    appearance generates a ``SentimentPropagation`` event.

    The tracker maintains an LRU-bounded ``OrderedDict`` of tickers so
    memory usage stays predictable even with high signal throughput.

    Example::

        tracker = PropagationTracker()
        events = tracker.ingest_signal("TSLA", "wallstreetbets", "bullish", time.time())
        # later...
        events = tracker.ingest_signal("TSLA", "stocks", "bullish", time.time() + 300)
        # events will contain a SentimentPropagation from wsb -> stocks
    """

    def __init__(self, config: Optional[PropagationConfig] = None) -> None:
        self._config = config or PropagationConfig()
        # ticker -> {source_name -> _TickerPresence}
        self._ticker_sources: OrderedDict[str, Dict[str, _TickerPresence]] = OrderedDict()
        # All detected propagation events (newest appended at end)
        self._propagations: List[SentimentPropagation] = []

    # ------------------------------------------------------------------
    # Core ingestion
    # ------------------------------------------------------------------

    def ingest_signal(
        self,
        ticker: str,
        source: str,
        stance: str,
        timestamp: float,
    ) -> List[SentimentPropagation]:
        """Record a signal arrival and detect any propagation events.

        When a signal for *ticker* arrives from *source* at *timestamp*,
        the tracker checks whether the same ticker has been seen from
        other sources.  For each earlier source whose ``first_seen`` plus
        ``min_lag_seconds`` is before this timestamp (and within
        ``max_lag_seconds``), a ``SentimentPropagation`` event is created
        recording the spread from that origin to *source*.

        Similarly, if *source* was the earliest and other sources appeared
        later but before now, propagation events from *source* to those
        later sources are created (if they haven't been recorded yet).

        Args:
            ticker: Ticker symbol (e.g. ``"TSLA"``).
            source: Subreddit or platform name.
            stance: Dominant stance (``"bullish"``, ``"bearish"``, etc.).
            timestamp: Unix timestamp of the signal.

        Returns:
            List of newly created ``SentimentPropagation`` events, which
            may be empty if no cross-source propagation was detected.
        """
        ticker = ticker.upper()
        new_propagations: List[SentimentPropagation] = []

        # Ensure ticker entry exists; move to end for LRU tracking
        if ticker in self._ticker_sources:
            self._ticker_sources.move_to_end(ticker)
        else:
            self._ticker_sources[ticker] = {}
            self._enforce_lru()

        sources = self._ticker_sources[ticker]

        # Update or create the presence record for this source
        if source in sources:
            presence = sources[source]
            presence.signal_count += 1
            presence.stance = stance
            presence.last_updated = timestamp
            if timestamp < presence.first_seen:
                presence.first_seen = timestamp
        else:
            sources[source] = _TickerPresence(
                source=source,
                first_seen=timestamp,
                signal_count=1,
                stance=stance,
                last_updated=timestamp,
            )

        # Build a set of already-known (origin, dest) pairs for this ticker
        # to avoid creating duplicate propagation events.
        existing_pairs = self._existing_pairs_for_ticker(ticker)

        # Check all other sources for propagation relationships
        for other_source, other_presence in sources.items():
            if other_source == source:
                continue

            # Case 1: other_source appeared first, this signal is the spread
            lag = timestamp - other_presence.first_seen
            if (
                self._config.min_lag_seconds <= lag <= self._config.max_lag_seconds
                and (other_source, source) not in existing_pairs
            ):
                prop = SentimentPropagation(
                    id=_gen_id(),
                    ticker=ticker,
                    origin_sub=other_source,
                    spread_to=source,
                    origin_ts=other_presence.first_seen,
                    spread_ts=timestamp,
                )
                self._propagations.append(prop)
                new_propagations.append(prop)
                existing_pairs.add((other_source, source))

            # Case 2: this source appeared first, other_source is the spread
            reverse_lag = other_presence.first_seen - timestamp
            if (
                self._config.min_lag_seconds <= reverse_lag <= self._config.max_lag_seconds
                and (source, other_source) not in existing_pairs
            ):
                prop = SentimentPropagation(
                    id=_gen_id(),
                    ticker=ticker,
                    origin_sub=source,
                    spread_to=other_source,
                    origin_ts=timestamp,
                    spread_ts=other_presence.first_seen,
                )
                self._propagations.append(prop)
                new_propagations.append(prop)
                existing_pairs.add((source, other_source))

        return new_propagations

    def ingest_signals_batch(
        self,
        signals: List[Dict[str, Any]],
    ) -> List[SentimentPropagation]:
        """Ingest a batch of signals and return all detected propagation events.

        Each dict in *signals* must contain:
          - ``ticker`` (str): ticker symbol
          - ``subreddit`` (str): source name (subreddit or platform)
          - ``stance`` (str): sentiment stance
          - ``created_at`` (float): unix timestamp

        Signals are processed in chronological order (earliest first) so
        that propagation relationships are detected correctly.

        Args:
            signals: List of signal dicts.

        Returns:
            All newly created ``SentimentPropagation`` events from the batch.
        """
        # Sort by created_at ascending to ensure chronological processing
        sorted_signals = sorted(signals, key=lambda s: s.get("created_at", 0.0))

        all_propagations: List[SentimentPropagation] = []
        for sig in sorted_signals:
            ticker = sig.get("ticker", "")
            source = sig.get("subreddit", "")
            stance = sig.get("stance", "unknown")
            ts = sig.get("created_at", 0.0)

            if not ticker or not source:
                continue

            new_props = self.ingest_signal(ticker, source, stance, ts)
            all_propagations.extend(new_props)

        return all_propagations

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_propagation_timeline(self, ticker: str) -> List[SentimentPropagation]:
        """Return all propagation events for a ticker, sorted by origin_ts ASC.

        Args:
            ticker: Ticker symbol to query.

        Returns:
            Chronologically ordered list of ``SentimentPropagation`` events
            for the given ticker.
        """
        ticker = ticker.upper()
        events = [p for p in self._propagations if p.ticker == ticker]
        events.sort(key=lambda p: p.origin_ts)
        return events

    def get_leading_sources(self, window_hours: int = 24) -> Dict[str, int]:
        """Count how many times each source originated sentiment that spread.

        A "leading" source is one whose signal appeared first and was later
        detected on other sources.  This method counts origin appearances
        within the given time window.

        Args:
            window_hours: Only consider propagation events detected within
                this many hours of the current time.

        Returns:
            Dict mapping source name to count, sorted by count descending.
        """
        cutoff = _cutoff_ts(window_hours)
        counts: Dict[str, int] = {}
        for p in self._propagations:
            if p.detected_at >= cutoff:
                counts[p.origin_sub] = counts.get(p.origin_sub, 0) + 1
        # Sort by count descending
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    def get_lagging_sources(self, window_hours: int = 24) -> Dict[str, int]:
        """Count how many times each source appeared as a propagation destination.

        A "lagging" source is one that picks up sentiment after it has already
        appeared elsewhere.

        Args:
            window_hours: Only consider propagation events detected within
                this many hours of the current time.

        Returns:
            Dict mapping source name to count, sorted by count descending.
        """
        cutoff = _cutoff_ts(window_hours)
        counts: Dict[str, int] = {}
        for p in self._propagations:
            if p.detected_at >= cutoff:
                counts[p.spread_to] = counts.get(p.spread_to, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    def get_avg_lag_by_pair(
        self,
        window_hours: int = 24,
    ) -> Dict[Tuple[str, str], float]:
        """Compute average propagation lag for each (origin, destination) pair.

        Args:
            window_hours: Only consider propagation events detected within
                this many hours of the current time.

        Returns:
            Dict mapping ``(origin_sub, spread_to)`` tuples to the average
            lag in seconds, sorted by average lag ascending (fastest pairs
            first).
        """
        cutoff = _cutoff_ts(window_hours)
        pair_lags: Dict[Tuple[str, str], List[float]] = {}
        for p in self._propagations:
            if p.detected_at >= cutoff:
                key = (p.origin_sub, p.spread_to)
                pair_lags.setdefault(key, []).append(p.lag_seconds)

        result: Dict[Tuple[str, str], float] = {}
        for pair, lags in pair_lags.items():
            result[pair] = sum(lags) / len(lags)

        return dict(sorted(result.items(), key=lambda kv: kv[1]))

    def get_virality_score(self, ticker: str) -> float:
        """Compute a virality score (0-100) for a ticker.

        The score reflects how quickly and broadly sentiment for this
        ticker is spreading across sources.  It is composed of three
        factors:

        - **Source breadth** (0-40): ``source_count * 20``, capped at 40.
          More sources reached means higher virality.
        - **Speed** (0-30): Faster average propagation relative to
          ``max_lag_seconds`` yields a higher factor.
        - **Volume** (0-30): More total signals across all sources
          increases the score.

        Args:
            ticker: Ticker symbol.

        Returns:
            Float score in ``[0, 100]``.
        """
        ticker = ticker.upper()
        sources = self._ticker_sources.get(ticker)
        if not sources:
            return 0.0

        source_count = len(sources)

        # Total signal count across all sources for this ticker
        total_signals = sum(p.signal_count for p in sources.values())

        # Compute average lag from propagation events for this ticker
        ticker_props = [p for p in self._propagations if p.ticker == ticker]
        if ticker_props:
            avg_lag = sum(p.lag_seconds for p in ticker_props) / len(ticker_props)
        else:
            avg_lag = self._config.max_lag_seconds

        # Speed factor: inversely proportional to average lag
        # If avg_lag is 0 or negative, treat as maximum speed
        max_lag = self._config.max_lag_seconds
        if max_lag > 0:
            speed_factor = max(0.0, 1.0 - avg_lag / max_lag) * 100.0
        else:
            speed_factor = 100.0

        # Volume factor
        volume_factor = min(100.0, total_signals * 5.0)

        score = (
            min(40.0, source_count * 20.0)
            + speed_factor * 0.30
            + volume_factor * 0.30
        )

        return min(100.0, max(0.0, score))

    def get_active_tickers(self, window_hours: int = 6) -> List[Dict[str, Any]]:
        """Return tickers with active propagation, sorted by virality.

        A ticker is "active" if it has at least one propagation event
        detected within the given time window.

        Args:
            window_hours: Only include tickers with propagation detected
                within this many hours.

        Returns:
            List of dicts, each containing:
              - ``ticker``: ticker symbol
              - ``source_count``: number of distinct sources
              - ``earliest_ts``: earliest signal timestamp
              - ``propagation_count``: number of propagation events
              - ``virality_score``: computed virality (0-100)

            Sorted by ``virality_score`` descending.
        """
        cutoff = _cutoff_ts(window_hours)

        # Find tickers with recent propagation events
        active_tickers: Dict[str, List[SentimentPropagation]] = {}
        for p in self._propagations:
            if p.detected_at >= cutoff:
                active_tickers.setdefault(p.ticker, []).append(p)

        result: List[Dict[str, Any]] = []
        for ticker, props in active_tickers.items():
            sources = self._ticker_sources.get(ticker, {})
            source_count = len(sources)

            # Earliest timestamp across all sources
            earliest_ts = min(
                (pr.first_seen for pr in sources.values()),
                default=0.0,
            )

            virality = self.get_virality_score(ticker)

            result.append({
                "ticker": ticker,
                "source_count": source_count,
                "earliest_ts": earliest_ts,
                "propagation_count": len(props),
                "virality_score": round(virality, 2),
            })

        # Sort by virality descending
        result.sort(key=lambda d: d["virality_score"], reverse=True)
        return result

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear_old(self, max_age_hours: int = 48) -> int:
        """Remove propagation events older than *max_age_hours*.

        This prevents unbounded memory growth over long-running sessions.

        Args:
            max_age_hours: Maximum age in hours; events older than this
                are discarded.

        Returns:
            Number of propagation events removed.
        """
        cutoff = _cutoff_ts(max_age_hours)
        original_count = len(self._propagations)
        self._propagations = [
            p for p in self._propagations if p.detected_at >= cutoff
        ]
        removed = original_count - len(self._propagations)

        # Also clean up stale ticker presence entries.
        # A ticker whose last_updated across all sources is older than the
        # cutoff is no longer relevant.
        stale_tickers: List[str] = []
        for ticker, sources in self._ticker_sources.items():
            if not sources:
                stale_tickers.append(ticker)
                continue
            latest = max(pr.last_updated for pr in sources.values())
            if latest < cutoff:
                stale_tickers.append(ticker)

        for ticker in stale_tickers:
            del self._ticker_sources[ticker]

        return removed

    def export_propagations(self) -> List[SentimentPropagation]:
        """Return all stored propagation events.

        Returns:
            Shallow copy of the internal propagation list so callers can
            iterate without affecting the tracker state.
        """
        return list(self._propagations)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enforce_lru(self) -> None:
        """Evict the least recently used ticker if over the cap."""
        while len(self._ticker_sources) > self._config.max_tracked_tickers:
            # popitem(last=False) removes the oldest (least recently used) entry
            self._ticker_sources.popitem(last=False)

    def _existing_pairs_for_ticker(
        self,
        ticker: str,
    ) -> set:
        """Return a set of ``(origin_sub, spread_to)`` pairs already recorded
        for the given ticker, used to avoid duplicate propagation events.

        Args:
            ticker: Uppercase ticker symbol.

        Returns:
            Set of 2-tuples ``(origin_sub, spread_to)``.
        """
        pairs: set = set()
        for p in self._propagations:
            if p.ticker == ticker:
                pairs.add((p.origin_sub, p.spread_to))
        return pairs

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def tracked_ticker_count(self) -> int:
        """Number of tickers currently being tracked."""
        return len(self._ticker_sources)

    @property
    def total_propagation_count(self) -> int:
        """Total number of propagation events stored."""
        return len(self._propagations)

    def get_ticker_sources(self, ticker: str) -> Dict[str, Dict[str, Any]]:
        """Return source presence info for a ticker (for debugging).

        Args:
            ticker: Ticker symbol.

        Returns:
            Dict mapping source name to a dict with ``first_seen``,
            ``signal_count``, ``stance``, and ``last_updated``.
        """
        ticker = ticker.upper()
        sources = self._ticker_sources.get(ticker, {})
        return {
            src: {
                "first_seen": pr.first_seen,
                "signal_count": pr.signal_count,
                "stance": pr.stance,
                "last_updated": pr.last_updated,
            }
            for src, pr in sources.items()
        }

    def __repr__(self) -> str:
        return (
            f"PropagationTracker("
            f"tickers={self.tracked_ticker_count}, "
            f"propagations={self.total_propagation_count})"
        )
