"""Manipulation detection engine for the Social Intelligence Network.

Detects coordinated posting campaigns, bot networks, and pump-and-dump
patterns by analyzing signal metadata (author, timing, stance, price).
Produces scored ManipulationAlert instances for downstream consumption.
"""

from __future__ import annotations

import math
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

from rot.social.types import ManipulationAlert


# ── Configuration ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ManipulationConfig:
    """Tuning knobs for manipulation detection algorithms.

    All thresholds have conservative defaults that minimise false positives
    while still catching obvious coordinated activity.
    """

    # -- Coordinated posting --------------------------------------------------
    coordination_window_s: int = 1800
    """Sliding window (seconds) for clustering co-timed posts. Default 30 min."""

    min_authors_for_coordination: int = 3
    """Minimum distinct authors required to flag a coordination cluster."""

    # -- Bot network ----------------------------------------------------------
    bot_time_tolerance_s: int = 300
    """Two authors whose median inter-post delta is below this are suspicious."""

    bot_min_group_size: int = 3
    """Minimum number of authors in a suspected bot ring."""

    # -- Pump-and-dump --------------------------------------------------------
    pump_volume_multiplier: float = 3.0
    """Flag if recent signal count exceeds baseline by this factor."""

    pump_price_threshold_pct: float = 5.0
    """Price movement threshold (%) used in severity scoring."""

    # -- General --------------------------------------------------------------
    min_severity_to_report: float = 30.0
    """Alerts below this severity are silently dropped."""

    def __post_init__(self) -> None:
        if self.coordination_window_s <= 0:
            raise ValueError("coordination_window_s must be > 0")
        if self.bot_time_tolerance_s <= 0:
            raise ValueError("bot_time_tolerance_s must be > 0")
        if self.bot_min_group_size < 2:
            raise ValueError("bot_min_group_size must be >= 2")
        if self.pump_volume_multiplier <= 1.0:
            raise ValueError("pump_volume_multiplier must be > 1.0")
        if self.pump_price_threshold_pct <= 0.0:
            raise ValueError("pump_price_threshold_pct must be > 0")
        if self.min_authors_for_coordination < 2:
            raise ValueError("min_authors_for_coordination must be >= 2")
        if not (0.0 <= self.min_severity_to_report <= 100.0):
            raise ValueError("min_severity_to_report must be in [0, 100]")


# ── Per-ticker rolling baseline ──────────────────────────────────────────────


@dataclass
class _TickerBaseline:
    """Mutable rolling signal-count baseline for a single ticker.

    Maintains a fixed-length sliding window of daily signal counts used
    to compute the "normal" volume for pump-and-dump detection.
    """

    signal_counts: List[int] = field(default_factory=list)
    """Rolling daily signal counts (most recent last). Max length = 20."""

    last_updated: float = field(default_factory=time.time)
    """Timestamp of the last update."""

    _MAX_WINDOW: int = 20

    def update(self, count: int) -> None:
        """Append a daily signal count and trim to window size."""
        self.signal_counts.append(max(0, count))
        if len(self.signal_counts) > self._MAX_WINDOW:
            self.signal_counts = self.signal_counts[-self._MAX_WINDOW:]
        self.last_updated = time.time()

    def mean(self) -> float:
        """Average daily signal count over the window."""
        if not self.signal_counts:
            return 0.0
        return sum(self.signal_counts) / len(self.signal_counts)

    def std(self) -> float:
        """Standard deviation of daily signal counts."""
        if len(self.signal_counts) < 2:
            return 0.0
        m = self.mean()
        variance = sum((x - m) ** 2 for x in self.signal_counts) / len(self.signal_counts)
        return math.sqrt(variance)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _generate_id() -> str:
    """Generate a short unique identifier."""
    return uuid.uuid4().hex[:16]


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Word-level Jaccard similarity between two strings.

    Returns |intersection(words_a, words_b)| / |union(words_a, words_b)|,
    or 0.0 when both inputs are empty.
    """
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a and not words_b:
        return 0.0
    union = words_a | words_b
    if not union:
        return 0.0
    return len(words_a & words_b) / len(union)


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce *val* to float, returning *default* on failure."""
    if val is None:
        return default
    try:
        f = float(val)
        # NaN guard - use math.isnan for clarity instead of f == f
        import math
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _safe_str(val: Any, default: str = "") -> str:
    """Coerce *val* to str, returning *default* for None."""
    if val is None:
        return default
    return str(val)


def _median(values: List[float]) -> float:
    """Compute the median of a non-empty list of floats."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return s[mid]


# ── Main Detector ────────────────────────────────────────────────────────────


class ManipulationDetector:
    """Detects coordinated posting, bot networks, and pump-and-dump patterns.

    The detector is stateful only with respect to per-ticker baselines
    (used for pump-and-dump detection).  All other analysis is stateless
    and operates purely on the input signal list.

    Each signal dict is expected to have at least::

        {
            "ticker": str,
            "stance": str,          # bullish / bearish / mixed / unknown
            "author": str,
            "subreddit": str,
            "created_at": float,    # unix timestamp
            "confidence": float,
            "price_at_signal": float | None,
            "price_current": float | None,  # optional
            "post_title": str | None,       # optional, used by bot detection
        }
    """

    def __init__(self, config: ManipulationConfig | None = None) -> None:
        self._config = config or ManipulationConfig()
        self._ticker_baselines: Dict[str, _TickerBaseline] = {}

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> ManipulationConfig:
        """Active configuration."""
        return self._config

    @property
    def ticker_baselines(self) -> Dict[str, _TickerBaseline]:
        """Current per-ticker baselines (read-only view)."""
        return dict(self._ticker_baselines)

    # ------------------------------------------------------------------
    # Top-level entry point
    # ------------------------------------------------------------------

    def detect_all(self, signals: List[Dict[str, Any]]) -> List[ManipulationAlert]:
        """Run all detection algorithms and return combined alerts.

        Parameters
        ----------
        signals:
            List of signal dicts (see class docstring for schema).

        Returns
        -------
        Alerts sorted by severity descending, filtered by
        ``min_severity_to_report``.
        """
        if not signals:
            return []

        alerts: List[ManipulationAlert] = []
        alerts.extend(self.detect_coordinated_posting(signals))
        alerts.extend(self.detect_bot_network(signals))
        alerts.extend(self.detect_pump_and_dump(signals))

        # Filter below threshold
        threshold = self._config.min_severity_to_report
        alerts = [a for a in alerts if a.severity >= threshold]

        # Sort by severity descending (stable, deterministic)
        alerts.sort(key=lambda a: (-a.severity, a.detected_at))
        return alerts

    # ------------------------------------------------------------------
    # 1. Coordinated Posting Detection
    # ------------------------------------------------------------------

    def detect_coordinated_posting(
        self, signals: List[Dict[str, Any]]
    ) -> List[ManipulationAlert]:
        """Detect clusters of same-stance posts from distinct authors within
        a tight time window for the same ticker.

        The algorithm:
        1. Group signals by ticker.
        2. Within each group, sort by ``created_at`` and slide a window of
           ``coordination_window_s`` seconds.
        3. For each window, collect unique authors and check if all signals
           share the same directional stance (bullish or bearish).
        4. If the cluster meets the author threshold, emit an alert.

        Returns
        -------
        List of ManipulationAlert with ``alert_type="coordinated_posting"``.
        """
        cfg = self._config
        alerts: List[ManipulationAlert] = []

        # Group by ticker
        by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for sig in signals:
            ticker = _safe_str(sig.get("ticker"))
            if ticker:
                by_ticker[ticker].append(sig)

        for ticker, group in by_ticker.items():
            # Sort by time
            group.sort(key=lambda s: _safe_float(s.get("created_at")))

            # Sliding window to find clusters
            clusters = self._find_time_clusters(group, cfg.coordination_window_s)

            for cluster in clusters:
                authors = list({_safe_str(s.get("author")) for s in cluster if s.get("author")})
                if len(authors) < cfg.min_authors_for_coordination:
                    continue

                # Check stance uniformity — only flag directional consensus
                stances = [_safe_str(s.get("stance")) for s in cluster]
                directional = [st for st in stances if st in ("bullish", "bearish")]
                if not directional:
                    continue

                # Dominant stance must be unanimous among directional signals
                dominant = max(set(directional), key=directional.count)
                dominant_pct = directional.count(dominant) / len(directional)
                if dominant_pct < 0.80:
                    # Require 80% agreement to call it coordination
                    continue

                # Compute timing tightness
                timestamps = sorted(
                    _safe_float(s.get("created_at")) for s in cluster
                )
                time_span = timestamps[-1] - timestamps[0] if len(timestamps) >= 2 else 0.0
                time_tightness = max(0.0, 1.0 - time_span / cfg.coordination_window_s)

                # Severity: more authors + tighter timing = higher severity
                severity = min(
                    100.0,
                    len(authors) * 15.0 + time_tightness * 30.0,
                )
                severity = round(severity, 1)

                evidence: Dict[str, Any] = {
                    "pattern": "coordinated_posting",
                    "authors": sorted(authors),
                    "ticker": ticker,
                    "stance": dominant,
                    "dominant_pct": round(dominant_pct, 2),
                    "time_span_s": round(time_span, 1),
                    "signal_count": len(cluster),
                }

                now = time.time()
                alerts.append(ManipulationAlert(
                    id=_generate_id(),
                    alert_type="coordinated_posting",
                    tickers=[ticker],
                    authors=sorted(authors),
                    evidence=evidence,
                    severity=severity,
                    detected_at=now,
                ))

        return alerts

    # ------------------------------------------------------------------
    # 2. Bot Network Detection
    # ------------------------------------------------------------------

    def detect_bot_network(
        self, signals: List[Dict[str, Any]]
    ) -> List[ManipulationAlert]:
        """Detect author groups that exhibit bot-like posting behaviour.

        Two complementary heuristics:

        **Timing-based:**  For every author pair, compute the absolute time
        deltas between their posts and take the median.  If the median is
        below ``bot_time_tolerance_s`` across 3+ co-occurring posts, the
        pair is flagged.  Connected pairs are merged into groups.

        **Content-based:**  Authors posting near-identical titles (Jaccard
        similarity > 0.8) are also flagged.

        Returns
        -------
        List of ManipulationAlert with ``alert_type="bot_network"``.
        """
        cfg = self._config
        alerts: List[ManipulationAlert] = []

        # ── Timing-based detection ──────────────────────────────────────

        # Collect per-author posting timestamps
        author_times: Dict[str, List[float]] = defaultdict(list)
        for sig in signals:
            author = _safe_str(sig.get("author"))
            ts = _safe_float(sig.get("created_at"))
            if author and ts > 0:
                author_times[author].append(ts)

        # Sort each author's timestamps
        for ts_list in author_times.values():
            ts_list.sort()

        # Check every pair for suspiciously low median time delta
        authors_list = list(author_times.keys())
        suspicious_pairs: List[Tuple[str, str, int, float]] = []

        for a1, a2 in combinations(authors_list, 2):
            ts1 = author_times[a1]
            ts2 = author_times[a2]
            deltas = self._compute_pairwise_deltas(ts1, ts2)
            if len(deltas) < 3:
                continue
            med = _median(deltas)
            if med <= cfg.bot_time_tolerance_s:
                suspicious_pairs.append((a1, a2, len(deltas), med))

        # Merge connected pairs into groups (union-find style)
        timing_groups = self._merge_pairs_into_groups(
            [(p[0], p[1]) for p in suspicious_pairs]
        )

        # Build alerts for timing-based groups
        pair_meta: Dict[Tuple[str, str], Tuple[int, float]] = {
            (p[0], p[1]): (p[2], p[3]) for p in suspicious_pairs
        }

        for group_authors in timing_groups:
            if len(group_authors) < cfg.bot_min_group_size:
                continue

            # Aggregate co-occurrence stats
            total_co = 0
            all_deltas: List[float] = []
            for a1, a2 in combinations(sorted(group_authors), 2):
                key = (a1, a2) if (a1, a2) in pair_meta else (a2, a1)
                if key in pair_meta:
                    co, med = pair_meta[key]
                    total_co += co
                    all_deltas.append(med)

            avg_delta = sum(all_deltas) / len(all_deltas) if all_deltas else 0.0

            severity = min(100.0, len(group_authors) * 20.0 + total_co * 10.0)
            severity = round(severity, 1)

            # Collect tickers touched by this group
            group_tickers = set()
            for sig in signals:
                if _safe_str(sig.get("author")) in group_authors:
                    t = _safe_str(sig.get("ticker"))
                    if t:
                        group_tickers.add(t)

            evidence: Dict[str, Any] = {
                "pattern": "bot_network",
                "sub_pattern": "timing",
                "authors": sorted(group_authors),
                "co_occurrences": total_co,
                "avg_time_delta_s": round(avg_delta, 1),
            }

            now = time.time()
            alerts.append(ManipulationAlert(
                id=_generate_id(),
                alert_type="bot_network",
                tickers=sorted(group_tickers) if group_tickers else ["UNKNOWN"],
                authors=sorted(group_authors),
                evidence=evidence,
                severity=severity,
                detected_at=now,
            ))

        # ── Content-based detection (duplicate titles) ──────────────────

        content_alerts = self._detect_similar_titles(signals)
        alerts.extend(content_alerts)

        return alerts

    # ------------------------------------------------------------------
    # 3. Pump-and-Dump Detection
    # ------------------------------------------------------------------

    def detect_pump_and_dump(
        self, signals: List[Dict[str, Any]]
    ) -> List[ManipulationAlert]:
        """Detect pump-and-dump patterns by comparing recent signal volume
        against rolling baselines, checking for bullish concentration, and
        incorporating price movement data when available.

        For each ticker the algorithm:
        1. Counts signals within the coordination window.
        2. Compares to the rolling baseline (mean daily count).
        3. Checks whether the majority of signals are bullish.
        4. Optionally incorporates price movement if ``price_current`` and
           ``price_at_signal`` are present.
        5. Scores severity from volume ratio, bullish concentration, and
           price movement.

        Returns
        -------
        List of ManipulationAlert with ``alert_type="pump_and_dump"``.
        """
        cfg = self._config
        alerts: List[ManipulationAlert] = []

        if not signals:
            return alerts

        # Group by ticker
        by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for sig in signals:
            ticker = _safe_str(sig.get("ticker"))
            if ticker:
                by_ticker[ticker].append(sig)

        now = time.time()
        window_start = now - cfg.coordination_window_s

        for ticker, group in by_ticker.items():
            # Count signals within the recent window
            recent = [
                s for s in group
                if _safe_float(s.get("created_at")) >= window_start
            ]
            recent_count = len(recent)
            if recent_count < 2:
                continue

            # Compare to baseline
            baseline = self._ticker_baselines.get(ticker)
            baseline_avg = baseline.mean() if baseline else 0.0

            # Avoid division by zero — use 1.0 as minimum baseline
            effective_baseline = max(baseline_avg, 1.0)
            volume_ratio = recent_count / effective_baseline

            if volume_ratio < cfg.pump_volume_multiplier:
                continue

            # Check bullish concentration
            stances = [_safe_str(s.get("stance")) for s in recent]
            bullish_count = stances.count("bullish")
            bearish_count = stances.count("bearish")
            total_directional = bullish_count + bearish_count
            if total_directional == 0:
                continue

            bullish_pct = bullish_count / total_directional
            # Pump patterns are overwhelmingly bullish; skip if not
            if bullish_pct < 0.60:
                continue

            # Price movement scoring (optional)
            price_changes: List[float] = []
            for s in recent:
                p_at = _safe_float(s.get("price_at_signal"))
                p_cur = _safe_float(s.get("price_current"))
                if p_at > 0 and p_cur > 0:
                    pct = ((p_cur - p_at) / p_at) * 100.0
                    price_changes.append(pct)

            avg_price_change = (
                sum(price_changes) / len(price_changes) if price_changes else 0.0
            )

            # Price move score: 0-1 based on how much price moved relative
            # to the pump threshold
            price_move_score = 0.0
            if price_changes:
                price_move_score = min(
                    1.0, abs(avg_price_change) / cfg.pump_price_threshold_pct
                )

            # Severity composition
            # volume_ratio contribution: capped at ~45 points
            vol_score = min(1.0, (volume_ratio - 1.0) / (cfg.pump_volume_multiplier * 2.0))
            severity = min(
                100.0,
                vol_score * 15.0 * cfg.pump_volume_multiplier
                + bullish_pct * 30.0
                + price_move_score * 30.0,
            )
            severity = round(severity, 1)

            # Collect authors involved
            authors = sorted({
                _safe_str(s.get("author"))
                for s in recent if s.get("author")
            })

            evidence: Dict[str, Any] = {
                "pattern": "pump_and_dump",
                "ticker": ticker,
                "signal_count": recent_count,
                "baseline_avg": round(baseline_avg, 2),
                "volume_ratio": round(volume_ratio, 2),
                "bullish_pct": round(bullish_pct, 2),
                "price_change_pct": round(avg_price_change, 2) if price_changes else None,
                "authors_involved": len(authors),
            }

            alerts.append(ManipulationAlert(
                id=_generate_id(),
                alert_type="pump_and_dump",
                tickers=[ticker],
                authors=authors,
                evidence=evidence,
                severity=severity,
                detected_at=now,
            ))

        return alerts

    # ------------------------------------------------------------------
    # Baseline management
    # ------------------------------------------------------------------

    def update_baselines(self, signals: List[Dict[str, Any]]) -> None:
        """Update per-ticker daily signal count baselines.

        Groups the provided signals by ticker, counts per calendar day,
        and appends the daily counts to each ticker's rolling window.
        This should be called periodically (e.g. once per day) with the
        day's signals.

        Parameters
        ----------
        signals:
            List of signal dicts with at least ``ticker`` and ``created_at``.
        """
        if not signals:
            return

        # Group by ticker
        by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for sig in signals:
            ticker = _safe_str(sig.get("ticker"))
            if ticker:
                by_ticker[ticker].append(sig)

        # Group each ticker's signals by calendar day and update baseline
        for ticker, group in by_ticker.items():
            # Bin by day (integer day index from epoch)
            day_counts: Dict[int, int] = defaultdict(int)
            for s in group:
                ts = _safe_float(s.get("created_at"))
                if ts > 0:
                    day_index = int(ts // 86400)
                    day_counts[day_index] += 1

            if not day_counts:
                continue

            baseline = self._ticker_baselines.get(ticker)
            if baseline is None:
                baseline = _TickerBaseline()
                self._ticker_baselines[ticker] = baseline

            # Append each day's count in chronological order
            for day_index in sorted(day_counts.keys()):
                baseline.update(day_counts[day_index])

        # Evict stale baselines (not updated in 30 days) to bound memory
        cutoff = time.time() - 30 * 86400
        stale_tickers = [
            t for t, b in self._ticker_baselines.items()
            if b.last_updated < cutoff
        ]
        for t in stale_tickers:
            del self._ticker_baselines[t]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_time_clusters(
        self,
        sorted_signals: List[Dict[str, Any]],
        window_s: float,
    ) -> List[List[Dict[str, Any]]]:
        """Find clusters of signals where all entries fall within *window_s*.

        Uses a sliding-window approach on the time-sorted signal list.
        Signals are added to the current cluster while the gap from the
        first signal in the cluster to the new signal is within the window.
        When a signal falls outside, the current cluster is emitted (if
        it has 2+ members) and a new cluster starts.

        Returns
        -------
        List of clusters, each cluster being a list of signal dicts.
        """
        if len(sorted_signals) < 2:
            return []

        clusters: List[List[Dict[str, Any]]] = []
        current_cluster: List[Dict[str, Any]] = [sorted_signals[0]]
        cluster_start_ts = _safe_float(sorted_signals[0].get("created_at"))

        for sig in sorted_signals[1:]:
            ts = _safe_float(sig.get("created_at"))
            if ts - cluster_start_ts <= window_s:
                current_cluster.append(sig)
            else:
                # Emit current cluster if non-trivial
                if len(current_cluster) >= 2:
                    clusters.append(current_cluster)
                # Start new cluster from this signal
                current_cluster = [sig]
                cluster_start_ts = ts

        # Don't forget the last cluster
        if len(current_cluster) >= 2:
            clusters.append(current_cluster)

        return clusters

    def _compute_pairwise_deltas(
        self,
        ts1: List[float],
        ts2: List[float],
    ) -> List[float]:
        """Compute the minimum absolute time deltas between two sorted
        timestamp lists.

        For each timestamp in *ts1*, find the closest timestamp in *ts2*
        and record the absolute delta.  This is O(n*m) but both lists are
        expected to be short (per-author post counts).

        Returns
        -------
        List of absolute time deltas (seconds).
        """
        if not ts1 or not ts2:
            return []

        deltas: List[float] = []
        for t1 in ts1:
            # Find closest t2
            best = float("inf")
            for t2 in ts2:
                d = abs(t1 - t2)
                if d < best:
                    best = d
            if best < float("inf"):
                deltas.append(best)

        return deltas

    @staticmethod
    def _merge_pairs_into_groups(
        pairs: List[Tuple[str, str]],
    ) -> List[set]:
        """Merge (author, author) pairs into connected components.

        Simple union-find via iterative merging.  Returns a list of sets,
        each set being a connected group of authors.
        """
        if not pairs:
            return []

        # Build adjacency via dict-based union-find
        parent: Dict[str, str] = {}

        def find(x: str) -> str:
            root = x
            while parent.get(root, root) != root:
                root = parent[root]
            # Path compression
            while parent.get(x, x) != root:
                nxt = parent.get(x, x)
                parent[x] = root
                x = nxt
            return root

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for a, b in pairs:
            # Ensure both exist in parent map
            parent.setdefault(a, a)
            parent.setdefault(b, b)
            union(a, b)

        # Collect groups by root
        groups: Dict[str, set] = defaultdict(set)
        for node in parent:
            root = find(node)
            groups[root].add(node)

        return list(groups.values())

    def _detect_similar_titles(
        self, signals: List[Dict[str, Any]]
    ) -> List[ManipulationAlert]:
        """Detect groups of authors posting near-identical titles.

        Compares all pairs of signals that have a ``post_title`` field.
        Pairs with Jaccard similarity > 0.8 are flagged, and connected
        authors are merged into groups.

        Returns
        -------
        List of ManipulationAlert with ``alert_type="bot_network"`` and
        ``sub_pattern="similar_titles"`` in evidence.
        """
        cfg = self._config
        alerts: List[ManipulationAlert] = []

        SIMILARITY_THRESHOLD = 0.8

        # Collect signals that have titles and distinct authors
        titled_signals: List[Dict[str, Any]] = []
        for sig in signals:
            title = _safe_str(sig.get("post_title"))
            author = _safe_str(sig.get("author"))
            if title and author:
                titled_signals.append(sig)

        if len(titled_signals) < 2:
            return alerts

        # Find pairs of different authors with similar titles
        similar_pairs: List[Tuple[str, str]] = []
        similar_titles_map: Dict[Tuple[str, str], List[str]] = {}

        for i, sig_a in enumerate(titled_signals):
            author_a = _safe_str(sig_a.get("author"))
            title_a = _safe_str(sig_a.get("post_title"))
            for j in range(i + 1, len(titled_signals)):
                sig_b = titled_signals[j]
                author_b = _safe_str(sig_b.get("author"))
                title_b = _safe_str(sig_b.get("post_title"))

                # Skip same-author pairs
                if author_a == author_b:
                    continue

                sim = _jaccard_similarity(title_a, title_b)
                if sim >= SIMILARITY_THRESHOLD:
                    pair_key = tuple(sorted([author_a, author_b]))
                    similar_pairs.append(pair_key)  # type: ignore[arg-type]
                    if pair_key not in similar_titles_map:
                        similar_titles_map[pair_key] = []
                    # Store unique titles
                    for t in (title_a, title_b):
                        if t not in similar_titles_map[pair_key]:
                            similar_titles_map[pair_key].append(t)

        if not similar_pairs:
            return alerts

        # Deduplicate pairs
        unique_pairs = list(set(similar_pairs))

        # Merge into groups
        groups = self._merge_pairs_into_groups(unique_pairs)

        for group_authors in groups:
            if len(group_authors) < cfg.bot_min_group_size:
                continue

            # Collect similar titles for this group
            all_titles: List[str] = []
            for pair_key, titles in similar_titles_map.items():
                if pair_key[0] in group_authors or pair_key[1] in group_authors:
                    for t in titles:
                        if t not in all_titles:
                            all_titles.append(t)

            # Collect tickers
            group_tickers = set()
            for sig in signals:
                if _safe_str(sig.get("author")) in group_authors:
                    t = _safe_str(sig.get("ticker"))
                    if t:
                        group_tickers.add(t)

            # Count co-occurrences for this group
            co_count = sum(
                1 for p in unique_pairs
                if p[0] in group_authors and p[1] in group_authors
            )

            severity = min(100.0, len(group_authors) * 20.0 + co_count * 10.0)
            severity = round(severity, 1)

            evidence: Dict[str, Any] = {
                "pattern": "bot_network",
                "sub_pattern": "similar_titles",
                "authors": sorted(group_authors),
                "co_occurrences": co_count,
                "similar_titles": all_titles[:10],  # Cap for payload size
            }

            now = time.time()
            alerts.append(ManipulationAlert(
                id=_generate_id(),
                alert_type="bot_network",
                tickers=sorted(group_tickers) if group_tickers else ["UNKNOWN"],
                authors=sorted(group_authors),
                evidence=evidence,
                severity=severity,
                detected_at=now,
            ))

        return alerts
