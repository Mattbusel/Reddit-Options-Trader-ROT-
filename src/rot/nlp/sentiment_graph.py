"""Sentiment graph network for Reddit post entity relationships.

Models relationships between entities (tickers, people, events) mentioned in
Reddit posts as a directed attributed graph.  Graph attention is used to
propagate sentiment along edges and identify the most influential nodes.
Tickers with high betweenness centrality are flagged as potential market movers.

Architecture overview
---------------------
* **Nodes**: tickers (``$AAPL``), persons (``Elon Musk``), events
  (``FDA approval``), subreddits.
* **Edges**: sentiment relationships derived from co-mention context.
  Edge weight encodes polarity and confidence.
* **Graph attention**: a lightweight single-layer graph attention network
  (GAT) propagates neighbour sentiment to update node embeddings.
* **Centrality analysis**: betweenness centrality identifies influential
  tickers likely to drive correlated moves.

Dependencies (optional, degrades gracefully)::

    pip install networkx

Example::

    from rot.nlp.sentiment_graph import SentimentGraph

    graph = SentimentGraph()
    graph.add_post(
        post_id="t3_abc",
        entities=["AAPL", "Tim Cook"],
        sentiment=0.8,
        subreddit="wallstreetbets",
    )
    movers = graph.top_movers(n=5)
    print(movers)   # [("AAPL", 0.94), ...]
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional networkx import
# ---------------------------------------------------------------------------

_NX_AVAILABLE = False
try:
    import networkx as nx
    _NX_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    """A node in the sentiment graph.

    Attributes:
        node_id: Unique string identifier (ticker symbol, person name, etc.).
        node_type: One of ``"ticker"``, ``"person"``, ``"event"``,
            ``"subreddit"``.
        sentiment_score: Aggregated sentiment in [-1, 1].
        mention_count: Total times this entity has been mentioned.
        attention_weight: GAT-computed attention (updated each propagation).
    """

    node_id: str
    node_type: str = "ticker"
    sentiment_score: float = 0.0
    mention_count: int = 0
    attention_weight: float = 0.0


@dataclass
class GraphEdge:
    """A directed edge representing a sentiment relationship.

    Attributes:
        source: Source node id.
        target: Target node id.
        weight: Edge polarity weight in [-1, 1].
        post_ids: Set of Reddit post IDs that contributed to this edge.
    """

    source: str
    target: str
    weight: float = 0.0
    post_ids: Set[str] = field(default_factory=set)


@dataclass
class MarketMover:
    """A ticker identified as a potential market mover.

    Attributes:
        ticker: Ticker symbol.
        centrality: Betweenness centrality score.
        sentiment: Aggregated sentiment on the node.
        influence_score: Combined centrality * |sentiment| score.
    """

    ticker: str
    centrality: float
    sentiment: float
    influence_score: float


# ---------------------------------------------------------------------------
# Sentiment graph
# ---------------------------------------------------------------------------


class SentimentGraph:
    """Attributed sentiment graph over Reddit post entities.

    Args:
        decay_factor: Multiplicative decay applied to old edge weights on each
            new post addition (simulates recency bias).
        max_nodes: Maximum number of nodes to track before pruning the least
            mentioned (default 5000).
    """

    def __init__(
        self,
        decay_factor: float = 0.99,
        max_nodes: int = 5_000,
    ) -> None:
        self.decay_factor = decay_factor
        self.max_nodes = max_nodes
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: Dict[Tuple[str, str], GraphEdge] = {}

        if _NX_AVAILABLE:
            self._graph: Optional["nx.DiGraph"] = nx.DiGraph()
        else:
            self._graph = None

        log.debug("sentiment_graph.init", decay=decay_factor)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def add_post(
        self,
        post_id: str,
        entities: List[str],
        sentiment: float,
        subreddit: str = "unknown",
        entity_types: Optional[Dict[str, str]] = None,
    ) -> None:
        """Ingest a Reddit post and update the graph.

        Adds/updates nodes for each entity and creates directed edges between
        all co-mentioned entity pairs with the post's sentiment as weight.

        Args:
            post_id: Reddit post ID (e.g. ``"t3_abc123"``).
            entities: List of entity strings recognised in the post.
            sentiment: Post-level sentiment in [-1, 1].
            subreddit: Source subreddit name.
            entity_types: Optional dict mapping entity string → type.  Unknown
                entities default to ``"ticker"`` if they look like a cashtag,
                else ``"person"``.
        """
        if not entities:
            return

        entity_types = entity_types or {}
        # Decay existing edge weights
        for edge in self._edges.values():
            edge.weight *= self.decay_factor

        # Ensure subreddit node exists
        self._upsert_node(subreddit, "subreddit", sentiment)

        # Upsert entity nodes
        for ent in entities:
            etype = entity_types.get(ent, self._infer_type(ent))
            self._upsert_node(ent, etype, sentiment)

        # Create / update edges between all co-mentioned entities
        all_nodes = [subreddit] + entities
        for i, src in enumerate(all_nodes):
            for tgt in all_nodes[i + 1 :]:
                self._upsert_edge(src, tgt, sentiment, post_id)
                self._upsert_edge(tgt, src, sentiment * 0.5, post_id)  # weaker reverse

        # Sync to networkx
        if self._graph is not None:
            self._sync_nx()

        # Prune if oversized
        if len(self._nodes) > self.max_nodes:
            self._prune()

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def propagate_attention(self, iterations: int = 3) -> None:
        """Run simplified graph attention propagation.

        Each iteration: each node's attention weight is updated as the
        softmax-normalised weighted sum of its in-neighbours' sentiment.

        Args:
            iterations: Number of propagation rounds.
        """
        for _ in range(iterations):
            new_weights: Dict[str, float] = {}
            for node_id, node in self._nodes.items():
                in_edges = [
                    e for (s, t), e in self._edges.items() if t == node_id
                ]
                if not in_edges:
                    new_weights[node_id] = node.attention_weight
                    continue

                # Attention scores: softmax over edge weights
                raw_scores = [abs(e.weight) + 1e-6 for e in in_edges]
                total = sum(raw_scores)
                normed = [s / total for s in raw_scores]

                neighbour_sentiment = sum(
                    w * self._nodes[e.source].sentiment_score
                    for w, e in zip(normed, in_edges)
                    if e.source in self._nodes
                )
                new_weights[node_id] = (
                    0.5 * node.attention_weight + 0.5 * neighbour_sentiment
                )

            for nid, w in new_weights.items():
                self._nodes[nid].attention_weight = w

    def betweenness_centrality(self) -> Dict[str, float]:
        """Compute betweenness centrality for all nodes.

        Uses networkx when available; falls back to a degree-heuristic.

        Returns:
            Dict mapping node_id → centrality score.
        """
        if _NX_AVAILABLE and self._graph is not None and len(self._graph) > 0:
            try:
                return nx.betweenness_centrality(self._graph, weight="weight", normalized=True)
            except Exception as exc:
                log.warning("sentiment_graph.centrality_error", error=str(exc))

        # Fallback: degree-based proxy
        degree: Dict[str, int] = {nid: 0 for nid in self._nodes}
        for (src, tgt) in self._edges:
            degree[src] = degree.get(src, 0) + 1
            degree[tgt] = degree.get(tgt, 0) + 1
        max_deg = max(degree.values()) if degree else 1
        return {nid: d / max_deg for nid, d in degree.items()}

    def top_movers(self, n: int = 10, ticker_only: bool = True) -> List[MarketMover]:
        """Return top-n entities by influence (centrality * |sentiment|).

        Args:
            n: Number of top entities to return.
            ticker_only: When True, only include nodes of type ``"ticker"``.

        Returns:
            List of :class:`MarketMover` sorted by influence_score descending.
        """
        self.propagate_attention()
        centrality = self.betweenness_centrality()

        movers: List[MarketMover] = []
        for node_id, node in self._nodes.items():
            if ticker_only and node.node_type != "ticker":
                continue
            cent = centrality.get(node_id, 0.0)
            influence = cent * abs(node.sentiment_score + node.attention_weight)
            movers.append(
                MarketMover(
                    ticker=node_id,
                    centrality=cent,
                    sentiment=node.sentiment_score,
                    influence_score=influence,
                )
            )

        movers.sort(key=lambda m: m.influence_score, reverse=True)
        return movers[:n]

    def node_sentiment(self, entity: str) -> Optional[float]:
        """Return the aggregated sentiment score for *entity*, or None."""
        node = self._nodes.get(entity)
        return node.sentiment_score if node else None

    def edge_count(self) -> int:
        """Return total number of edges in the graph."""
        return len(self._edges)

    def node_count(self) -> int:
        """Return total number of nodes in the graph."""
        return len(self._nodes)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _upsert_node(self, node_id: str, node_type: str, sentiment: float) -> None:
        if node_id not in self._nodes:
            self._nodes[node_id] = GraphNode(node_id=node_id, node_type=node_type)
        node = self._nodes[node_id]
        # Running average sentiment
        node.mention_count += 1
        alpha = 1.0 / node.mention_count
        node.sentiment_score = (1 - alpha) * node.sentiment_score + alpha * sentiment

    def _upsert_edge(
        self, src: str, tgt: str, sentiment: float, post_id: str
    ) -> None:
        key = (src, tgt)
        if key not in self._edges:
            self._edges[key] = GraphEdge(source=src, target=tgt)
        edge = self._edges[key]
        # EMA of edge weight
        edge.weight = 0.7 * edge.weight + 0.3 * sentiment
        edge.post_ids.add(post_id)

    def _sync_nx(self) -> None:
        """Synchronise internal structures with the networkx graph."""
        assert self._graph is not None
        for node_id, node in self._nodes.items():
            if not self._graph.has_node(node_id):
                self._graph.add_node(
                    node_id,
                    node_type=node.node_type,
                    sentiment=node.sentiment_score,
                )
        for (src, tgt), edge in self._edges.items():
            self._graph.add_edge(src, tgt, weight=abs(edge.weight))

    def _prune(self) -> None:
        """Remove the least-mentioned nodes to stay under max_nodes."""
        sorted_nodes = sorted(
            self._nodes.values(), key=lambda n: n.mention_count
        )
        to_remove = sorted_nodes[: len(self._nodes) - self.max_nodes]
        for node in to_remove:
            del self._nodes[node.node_id]
            # Remove associated edges
            self._edges = {
                k: v
                for k, v in self._edges.items()
                if k[0] != node.node_id and k[1] != node.node_id
            }

    @staticmethod
    def _infer_type(entity: str) -> str:
        """Infer node type from entity string heuristic."""
        clean = entity.strip("$").upper()
        # Likely a ticker if 1-5 uppercase letters
        if clean.isalpha() and 1 <= len(clean) <= 5:
            return "ticker"
        return "person"
