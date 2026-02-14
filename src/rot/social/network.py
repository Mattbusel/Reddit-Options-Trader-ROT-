"""Network analysis for the Social Intelligence Network.

Builds co-mention graphs between authors based on shared ticker mentions,
clusters similar authors using agglomerative Jaccard-similarity merging,
and detects contrarian signals where a minority opposes strong consensus.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from rot.social.types import AuthorCluster, ContrarianSignal, STANCES


# ── Configuration ────────────────────────────────────────────────────────────


@dataclass
class NetworkConfig:
    """Tuning knobs for the co-mention graph and clustering engine."""

    # Co-mention graph
    min_co_mentions: int = 3
    """Minimum shared tickers between two authors to form an edge."""

    # Clustering
    cluster_similarity_threshold: float = 0.5
    """Minimum Jaccard similarity to merge two clusters."""

    min_cluster_size: int = 2
    """Minimum number of authors required to keep a cluster."""

    max_clusters: int = 50
    """Maximum clusters stored after detection."""

    # Contrarian detection
    contrarian_min_consensus: int = 5
    """Minimum authors on the consensus side to qualify a contrarian signal."""

    contrarian_max_against: int = 2
    """Maximum authors on the contrarian side (any more is a real split, not contrarian)."""

    contrarian_min_strength: float = 0.3
    """Minimum strength (consensus - contrarian) / (consensus + contrarian) to emit."""

    # Graph size management
    max_graph_nodes: int = 500
    """LRU cap on the author node count."""


# ── Internal mutable node ────────────────────────────────────────────────────


@dataclass
class _AuthorNode:
    """Mutable in-memory representation of an author within the graph.

    Tracks which tickers this author has mentioned and their most recent
    stance per ticker.  Not part of the public API.
    """

    author_id: str
    tickers: Set[str] = field(default_factory=set)
    stances: Dict[str, str] = field(default_factory=dict)
    signal_count: int = 0
    last_seen: float = field(default_factory=time.time)


# ── Core analyzer ────────────────────────────────────────────────────────────


class NetworkAnalyzer:
    """Builds and queries the author co-mention graph.

    Usage::

        analyzer = NetworkAnalyzer()
        analyzer.ingest_signal("user_a", "TSLA", "bullish", time.time())
        analyzer.ingest_signal("user_b", "TSLA", "bearish", time.time())
        clusters = analyzer.detect_clusters()
        contrarians = analyzer.detect_contrarian_signals()
    """

    def __init__(self, config: Optional[NetworkConfig] = None) -> None:
        self._config = config or NetworkConfig()
        self._nodes: OrderedDict[str, _AuthorNode] = OrderedDict()
        self._clusters: List[AuthorCluster] = []
        self._contrarian_signals: List[ContrarianSignal] = []

    # ── Ingestion ────────────────────────────────────────────────────────

    def ingest_signal(
        self,
        author_id: str,
        ticker: str,
        stance: str,
        timestamp: float,
    ) -> None:
        """Record a single author-ticker-stance observation.

        Creates or updates the internal ``_AuthorNode`` for *author_id*,
        adds *ticker* to their mention set, and records their most recent
        stance for that ticker.  The node is moved to the end of the LRU
        ``OrderedDict``; if the graph exceeds ``max_graph_nodes`` the
        oldest (least-recently-seen) author is evicted.

        Args:
            author_id: Unique author identifier (e.g. ``"reddit:u/someone"``).
            ticker: Ticker symbol mentioned (e.g. ``"TSLA"``).
            stance: One of the valid STANCES (``bullish``, ``bearish``,
                ``mixed``, ``unknown``).
            timestamp: Unix epoch timestamp of the observation.
        """
        if not author_id:
            return
        if not ticker:
            return

        node = self._nodes.get(author_id)
        if node is not None:
            # Update existing node
            node.tickers.add(ticker)
            node.stances[ticker] = stance
            node.signal_count += 1
            node.last_seen = max(node.last_seen, timestamp)
            # Move to end for LRU ordering
            self._nodes.move_to_end(author_id)
        else:
            # Create new node
            node = _AuthorNode(
                author_id=author_id,
                tickers={ticker},
                stances={ticker: stance},
                signal_count=1,
                last_seen=timestamp,
            )
            self._nodes[author_id] = node

        # LRU eviction: pop oldest entries until within cap
        while len(self._nodes) > self._config.max_graph_nodes:
            self._nodes.popitem(last=False)

    def ingest_signals_batch(self, signals: List[Dict[str, Any]]) -> None:
        """Ingest a batch of signals at once.

        Each element should be a dict with keys ``author``, ``ticker``,
        ``stance``, and ``created_at``.  Missing or empty author/ticker
        entries are silently skipped.

        Args:
            signals: List of signal dicts to ingest.
        """
        for sig in signals:
            author = sig.get("author", "")
            ticker = sig.get("ticker", "")
            stance = sig.get("stance", "unknown")
            ts = sig.get("created_at", time.time())
            if author and ticker:
                self.ingest_signal(author, ticker, stance, ts)

    # ── Co-mention graph ─────────────────────────────────────────────────

    def build_co_mention_graph(self) -> Dict[Tuple[str, str], float]:
        """Compute pairwise Jaccard similarity over ticker mention sets.

        Only pairs that share at least ``min_co_mentions`` tickers are
        included.  The returned dict maps ``(author_a, author_b)`` (sorted
        lexicographically) to their similarity score.

        Returns:
            Dict keyed by author-pair tuples, values are Jaccard
            similarity scores in ``(0, 1]``, sorted descending by score.
        """
        authors = list(self._nodes.keys())
        edges: Dict[Tuple[str, str], float] = {}
        min_shared = self._config.min_co_mentions

        for i in range(len(authors)):
            node_a = self._nodes[authors[i]]
            for j in range(i + 1, len(authors)):
                node_b = self._nodes[authors[j]]

                shared = node_a.tickers & node_b.tickers
                if len(shared) < min_shared:
                    continue

                sim = self._jaccard(node_a.tickers, node_b.tickers)
                if sim <= 0.0:
                    continue

                # Canonical ordering
                pair = (
                    (authors[i], authors[j])
                    if authors[i] <= authors[j]
                    else (authors[j], authors[i])
                )
                edges[pair] = sim

        # Sort descending by similarity
        sorted_edges: Dict[Tuple[str, str], float] = dict(
            sorted(edges.items(), key=lambda kv: kv[1], reverse=True)
        )
        return sorted_edges

    # ── Clustering ───────────────────────────────────────────────────────

    def detect_clusters(self) -> List[AuthorCluster]:
        """Detect author clusters via greedy agglomerative merging.

        Algorithm:
            1. Build the co-mention graph (pairwise Jaccard similarities).
            2. Initialise each author as a singleton cluster.
            3. Process edges in descending similarity order.  If the two
               authors belong to different clusters and their similarity
               meets ``cluster_similarity_threshold``, merge the smaller
               cluster into the larger one.
            4. Drop clusters smaller than ``min_cluster_size``.
            5. Compute per-cluster average pairwise similarity and common
               tickers (intersection of all members).
            6. Cap at ``max_clusters``, keeping highest similarity first.

        The resulting ``AuthorCluster`` list is stored internally and
        returned.

        Returns:
            List of detected ``AuthorCluster`` objects.
        """
        edges = self.build_co_mention_graph()
        threshold = self._config.cluster_similarity_threshold

        # Union-Find style mapping: author_id -> cluster label
        cluster_of: Dict[str, int] = {}
        clusters: Dict[int, List[str]] = {}
        next_label = 0

        # Initialise each author as its own cluster
        for author_id in self._nodes:
            cluster_of[author_id] = next_label
            clusters[next_label] = [author_id]
            next_label += 1

        # Greedily merge pairs (edges are already sorted DESC by sim)
        for (author_a, author_b), sim in edges.items():
            if sim < threshold:
                break  # All remaining edges are below threshold

            label_a = cluster_of[author_a]
            label_b = cluster_of[author_b]

            if label_a == label_b:
                continue  # Already in the same cluster

            # Merge smaller into larger
            if len(clusters[label_a]) >= len(clusters[label_b]):
                keep, merge = label_a, label_b
            else:
                keep, merge = label_b, label_a

            for member in clusters[merge]:
                cluster_of[member] = keep
            clusters[keep].extend(clusters[merge])
            del clusters[merge]

        # Build AuthorCluster objects for qualifying clusters
        result: List[AuthorCluster] = []
        now = time.time()

        for members in clusters.values():
            if len(members) < self._config.min_cluster_size:
                continue

            # Compute average pairwise similarity within the cluster
            avg_sim = self._cluster_avg_similarity(members)

            # Common tickers = intersection of all member ticker sets
            common = self._cluster_common_tickers(members)

            cluster = AuthorCluster(
                id=uuid.uuid4().hex[:16],
                authors=sorted(members),
                similarity_score=round(avg_sim, 4),
                common_tickers=sorted(common),
                detected_at=now,
            )
            result.append(cluster)

        # Sort by similarity DESC, cap at max_clusters
        result.sort(key=lambda c: c.similarity_score, reverse=True)
        result = result[: self._config.max_clusters]

        self._clusters = result
        return list(result)

    def _cluster_avg_similarity(self, members: List[str]) -> float:
        """Compute the mean pairwise Jaccard similarity for *members*.

        Returns 0.0 if fewer than 2 members or if none share tickers.
        """
        if len(members) < 2:
            return 0.0

        total = 0.0
        count = 0

        for i in range(len(members)):
            node_a = self._nodes.get(members[i])
            if node_a is None:
                continue
            for j in range(i + 1, len(members)):
                node_b = self._nodes.get(members[j])
                if node_b is None:
                    continue
                total += self._jaccard(node_a.tickers, node_b.tickers)
                count += 1

        return total / count if count > 0 else 0.0

    def _cluster_common_tickers(self, members: List[str]) -> Set[str]:
        """Return the intersection of ticker sets for all *members*."""
        sets: List[Set[str]] = []
        for author_id in members:
            node = self._nodes.get(author_id)
            if node is not None:
                sets.append(node.tickers)

        if not sets:
            return set()

        common = sets[0].copy()
        for s in sets[1:]:
            common &= s
        return common

    # ── Contrarian detection ─────────────────────────────────────────────

    def detect_contrarian_signals(
        self, window_hours: float = 24.0
    ) -> List[ContrarianSignal]:
        """Detect tickers where a small minority opposes a strong consensus.

        For each ticker mentioned by multiple authors within the last
        *window_hours*, the method counts bullish vs bearish stances.  A
        contrarian signal is emitted when:

        - The consensus side has >= ``contrarian_min_consensus`` authors.
        - The minority side has >= 1 and <= ``contrarian_max_against``
          authors.
        - The computed strength ``(consensus - minority) / (consensus +
          minority)`` meets ``contrarian_min_strength``.

        ``mixed`` and ``unknown`` stances are ignored (they don't
        contribute to either side).

        The resulting signals are stored internally and returned.

        Args:
            window_hours: Only consider authors seen within this many
                hours.

        Returns:
            List of newly detected ``ContrarianSignal`` objects.
        """
        cutoff = time.time() - window_hours * 3600.0
        cfg = self._config

        # Build per-ticker stance aggregation
        # ticker -> stance -> [author_ids]
        ticker_stances: Dict[str, Dict[str, List[str]]] = {}

        for author_id, node in self._nodes.items():
            if node.last_seen < cutoff:
                continue

            for ticker, stance in node.stances.items():
                if stance not in ("bullish", "bearish"):
                    continue  # Only directional stances matter
                if ticker not in ticker_stances:
                    ticker_stances[ticker] = {}
                bucket = ticker_stances[ticker]
                if stance not in bucket:
                    bucket[stance] = []
                bucket[stance].append(author_id)

        # Find contrarian situations
        result: List[ContrarianSignal] = []
        now = time.time()

        for ticker, stance_map in ticker_stances.items():
            bullish_authors = stance_map.get("bullish", [])
            bearish_authors = stance_map.get("bearish", [])

            bull_count = len(bullish_authors)
            bear_count = len(bearish_authors)

            # Need at least one side to meet consensus threshold
            # and the other to be a small minority
            contrarian_signal = self._check_contrarian_pair(
                ticker=ticker,
                consensus_stance="bullish",
                consensus_authors=bullish_authors,
                consensus_count=bull_count,
                contrarian_stance="bearish",
                contrarian_authors=bearish_authors,
                contrarian_count=bear_count,
                cfg=cfg,
                now=now,
            )
            if contrarian_signal is not None:
                result.append(contrarian_signal)
                continue  # Only one contrarian signal per ticker

            contrarian_signal = self._check_contrarian_pair(
                ticker=ticker,
                consensus_stance="bearish",
                consensus_authors=bearish_authors,
                consensus_count=bear_count,
                contrarian_stance="bullish",
                contrarian_authors=bullish_authors,
                contrarian_count=bull_count,
                cfg=cfg,
                now=now,
            )
            if contrarian_signal is not None:
                result.append(contrarian_signal)

        # Sort by strength DESC
        result.sort(key=lambda s: s.strength, reverse=True)
        self._contrarian_signals = result
        return list(result)

    @staticmethod
    def _check_contrarian_pair(
        *,
        ticker: str,
        consensus_stance: str,
        consensus_authors: List[str],
        consensus_count: int,
        contrarian_stance: str,
        contrarian_authors: List[str],
        contrarian_count: int,
        cfg: NetworkConfig,
        now: float,
    ) -> Optional[ContrarianSignal]:
        """Check if a specific consensus/contrarian pairing qualifies.

        Returns a ``ContrarianSignal`` if all thresholds are met, else
        ``None``.
        """
        if consensus_count < cfg.contrarian_min_consensus:
            return None
        if contrarian_count < 1:
            return None
        if contrarian_count > cfg.contrarian_max_against:
            return None

        total = consensus_count + contrarian_count
        strength = (consensus_count - contrarian_count) / total

        if strength < cfg.contrarian_min_strength:
            return None

        return ContrarianSignal(
            id=uuid.uuid4().hex[:16],
            ticker=ticker,
            contrarian_stance=contrarian_stance,
            consensus_stance=consensus_stance,
            contrarian_authors=sorted(contrarian_authors),
            consensus_author_count=consensus_count,
            strength=round(strength, 4),
            detected_at=now,
        )

    # ── Accessors ────────────────────────────────────────────────────────

    def get_clusters(self) -> List[AuthorCluster]:
        """Return the most recently detected clusters.

        Returns:
            A copy of the internal cluster list.
        """
        return list(self._clusters)

    def get_contrarian_signals(self, limit: int = 50) -> List[ContrarianSignal]:
        """Return stored contrarian signals sorted by strength DESC.

        Args:
            limit: Maximum number of signals to return.

        Returns:
            List of ``ContrarianSignal`` objects, up to *limit* entries.
        """
        signals = sorted(
            self._contrarian_signals,
            key=lambda s: s.strength,
            reverse=True,
        )
        return signals[:limit]

    def get_author_connections(self, author_id: str) -> List[Dict[str, Any]]:
        """Return all authors connected to *author_id* via co-mention.

        Builds the co-mention graph (cached-unfriendly but simple) and
        extracts edges involving *author_id*.

        Args:
            author_id: The author whose connections to look up.

        Returns:
            List of dicts with ``author_id``, ``similarity``, and
            ``common_tickers`` keys, sorted by similarity DESC.
        """
        if author_id not in self._nodes:
            return []

        node = self._nodes[author_id]
        result: List[Dict[str, Any]] = []
        min_shared = self._config.min_co_mentions

        for other_id, other_node in self._nodes.items():
            if other_id == author_id:
                continue

            shared = node.tickers & other_node.tickers
            if len(shared) < min_shared:
                continue

            sim = self._jaccard(node.tickers, other_node.tickers)
            if sim <= 0.0:
                continue

            result.append(
                {
                    "author_id": other_id,
                    "similarity": round(sim, 4),
                    "common_tickers": sorted(shared),
                }
            )

        result.sort(key=lambda x: x["similarity"], reverse=True)
        return result

    def get_ticker_consensus(self, ticker: str) -> Dict[str, Any]:
        """Compute the current stance consensus for a single ticker.

        Counts bullish, bearish, and mixed/unknown stances across all
        authors that mention *ticker*.

        Args:
            ticker: The ticker symbol to query.

        Returns:
            Dict with ``ticker``, ``bullish_count``, ``bearish_count``,
            ``mixed_count``, ``total``, ``dominant_stance``, and
            ``consensus_pct`` keys.
        """
        bullish = 0
        bearish = 0
        mixed = 0

        for node in self._nodes.values():
            stance = node.stances.get(ticker)
            if stance is None:
                continue
            if stance == "bullish":
                bullish += 1
            elif stance == "bearish":
                bearish += 1
            else:
                mixed += 1

        total = bullish + bearish + mixed

        if total == 0:
            return {
                "ticker": ticker,
                "bullish_count": 0,
                "bearish_count": 0,
                "mixed_count": 0,
                "total": 0,
                "dominant_stance": "unknown",
                "consensus_pct": 0.0,
            }

        if bullish >= bearish and bullish >= mixed:
            dominant = "bullish"
            dominant_count = bullish
        elif bearish >= bullish and bearish >= mixed:
            dominant = "bearish"
            dominant_count = bearish
        else:
            dominant = "mixed"
            dominant_count = mixed

        consensus_pct = round(dominant_count / total, 4) if total > 0 else 0.0

        return {
            "ticker": ticker,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "mixed_count": mixed,
            "total": total,
            "dominant_stance": dominant,
            "consensus_pct": consensus_pct,
        }

    def get_network_stats(self) -> Dict[str, Any]:
        """Return high-level statistics about the current graph state.

        Returns:
            Dict with ``total_authors``, ``total_edges``,
            ``avg_connections``, ``total_clusters``,
            ``total_contrarian_signals``, and ``top_mentioned_tickers``
            keys.
        """
        edges = self.build_co_mention_graph()
        total_edges = len(edges)
        total_authors = len(self._nodes)

        # Average connections per author
        if total_authors > 0:
            # Each edge contributes 1 connection to each of 2 authors
            avg_connections = round((2 * total_edges) / total_authors, 2)
        else:
            avg_connections = 0.0

        # Top mentioned tickers by frequency
        ticker_counts: Dict[str, int] = {}
        for node in self._nodes.values():
            for t in node.tickers:
                ticker_counts[t] = ticker_counts.get(t, 0) + 1

        top_tickers = sorted(
            ticker_counts.items(), key=lambda kv: kv[1], reverse=True
        )[:10]

        return {
            "total_authors": total_authors,
            "total_edges": total_edges,
            "avg_connections": avg_connections,
            "total_clusters": len(self._clusters),
            "total_contrarian_signals": len(self._contrarian_signals),
            "top_mentioned_tickers": [
                {"ticker": t, "count": c} for t, c in top_tickers
            ],
        }

    # ── Maintenance ──────────────────────────────────────────────────────

    def clear_old(self, max_age_hours: float = 72.0) -> int:
        """Remove authors not seen within *max_age_hours*.

        Args:
            max_age_hours: Evict authors whose ``last_seen`` timestamp is
                older than ``now - max_age_hours * 3600``.

        Returns:
            Number of authors removed.
        """
        cutoff = time.time() - max_age_hours * 3600.0
        to_remove = [
            aid for aid, node in self._nodes.items() if node.last_seen < cutoff
        ]
        for aid in to_remove:
            del self._nodes[aid]
        return len(to_remove)

    # ── Utilities ────────────────────────────────────────────────────────

    @staticmethod
    def _jaccard(set_a: set, set_b: set) -> float:
        """Compute Jaccard similarity between two sets.

        ``|A intersection B| / |A union B|``.  Returns ``0.0`` if both
        sets are empty.

        Args:
            set_a: First set.
            set_b: Second set.

        Returns:
            Jaccard similarity in ``[0.0, 1.0]``.
        """
        if not set_a and not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        if union == 0:
            return 0.0
        return intersection / union
