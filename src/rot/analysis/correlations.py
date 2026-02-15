"""Correlation analysis engine.

Computes signal correlations, detects clusters, identifies lead-lag
relationships, and builds network data for visualization.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from rot.analysis.correlation_types import (
    CorrelationPair,
    LeadLagPair,
    NetworkGraph,
    PredictivePair,
    SignalCorrelationMatrix,
    TickerCluster,
)


class CorrelationAnalyzer:
    """Analyzes ticker correlations from signal data."""

    def __init__(
        self,
        min_co_fires: int = 3,
        correlation_window_hours: int = 4,
    ) -> None:
        self._min_co_fires = min_co_fires
        self._window_hours = correlation_window_hours

    # ── Signal Correlation Matrix ──

    def compute_signal_correlations(
        self,
        signals: List[Dict[str, Any]],
        days: int = 30,
        min_signals: int = 5,
    ) -> SignalCorrelationMatrix:
        """Compute signal-based correlation matrix.

        Two tickers 'co-fire' when they both appear in signals within
        the correlation window (default 4 hours). Correlation strength
        is based on co-fire frequency and stance agreement.
        """
        now = time.time()
        cutoff = now - (days * 86400)
        window_s = self._window_hours * 3600

        # Filter and group by ticker
        by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for s in signals:
            ts = s.get("created_at", 0)
            ticker = s.get("ticker", "")
            if ticker and ts >= cutoff:
                by_ticker[ticker].append(s)

        # Only tickers with enough signals
        tickers = sorted(
            t for t, sigs in by_ticker.items() if len(sigs) >= min_signals
        )

        pairs = []
        for i, t_a in enumerate(tickers):
            for t_b in tickers[i + 1:]:
                co_fires = 0
                same_stance = 0
                sigs_a = by_ticker[t_a]
                sigs_b = by_ticker[t_b]

                for sa in sigs_a:
                    ts_a = sa.get("created_at", 0)
                    stance_a = sa.get("stance", "unknown")
                    for sb in sigs_b:
                        ts_b = sb.get("created_at", 0)
                        if abs(ts_a - ts_b) <= window_s:
                            co_fires += 1
                            if stance_a == sb.get("stance", "unknown"):
                                same_stance += 1

                if co_fires >= self._min_co_fires:
                    # Correlation: normalized co-fire frequency
                    max_possible = min(len(sigs_a), len(sigs_b))
                    corr = co_fires / max_possible if max_possible > 0 else 0
                    same_pct = (same_stance / co_fires * 100) if co_fires else 0

                    # If mostly opposite stances, make correlation negative
                    if same_pct < 40:
                        corr = -corr

                    pairs.append(CorrelationPair(
                        ticker_a=t_a,
                        ticker_b=t_b,
                        correlation=round(corr, 3),
                        co_fires=co_fires,
                        same_stance_pct=round(same_pct, 1),
                        sample_size=len(sigs_a) + len(sigs_b),
                    ))

        pairs.sort(key=lambda p: abs(p.correlation), reverse=True)

        strongest_pos = next(
            (p for p in pairs if p.correlation > 0), None
        )
        strongest_neg = next(
            (p for p in sorted(pairs, key=lambda p: p.correlation) if p.correlation < 0),
            None,
        )

        return SignalCorrelationMatrix(
            tickers=tickers,
            pairs=pairs,
            strongest_positive=strongest_pos,
            strongest_negative=strongest_neg,
        )

    # ── Cluster Detection ──

    def detect_clusters(
        self,
        matrix: SignalCorrelationMatrix,
        threshold: float = 0.3,
    ) -> List[TickerCluster]:
        """Detect ticker clusters via greedy connected-component grouping.

        Tickers are placed in the same cluster if their correlation
        exceeds the threshold.
        """
        # Build adjacency from pairs above threshold
        adj: Dict[str, set] = defaultdict(set)
        pair_corr: Dict[Tuple[str, str], float] = {}
        for p in matrix.pairs:
            if p.correlation >= threshold:
                adj[p.ticker_a].add(p.ticker_b)
                adj[p.ticker_b].add(p.ticker_a)
                key = tuple(sorted([p.ticker_a, p.ticker_b]))
                pair_corr[key] = p.correlation

        # Connected components via BFS
        visited: set = set()
        clusters = []
        cluster_id = 0

        for ticker in matrix.tickers:
            if ticker in visited:
                continue
            if ticker not in adj:
                continue

            # BFS
            component = []
            queue = [ticker]
            while queue:
                t = queue.pop(0)
                if t in visited:
                    continue
                visited.add(t)
                component.append(t)
                for neighbor in adj.get(t, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)

            if len(component) >= 2:
                # Average internal correlation
                internal_corrs = []
                for i, a in enumerate(component):
                    for b in component[i + 1:]:
                        key = tuple(sorted([a, b]))
                        if key in pair_corr:
                            internal_corrs.append(pair_corr[key])

                avg_corr = (
                    sum(internal_corrs) / len(internal_corrs)
                    if internal_corrs else 0.0
                )

                clusters.append(TickerCluster(
                    cluster_id=cluster_id,
                    tickers=sorted(component),
                    avg_internal_correlation=round(avg_corr, 3),
                    label=f"Cluster {cluster_id + 1}",
                ))
                cluster_id += 1

        clusters.sort(key=lambda c: c.size, reverse=True)
        return clusters

    # ── Lead-Lag Detection ──

    def compute_lead_lag(
        self,
        signals: List[Dict[str, Any]],
        days: int = 30,
        max_lag_hours: int = 24,
        min_occurrences: int = 3,
    ) -> List[LeadLagPair]:
        """Identify ticker pairs where one consistently leads the other.

        For each co-occurring pair within max_lag_hours, track which
        ticker's signal came first and by how much.
        """
        now = time.time()
        cutoff = now - (days * 86400)
        max_lag_s = max_lag_hours * 3600

        by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for s in signals:
            ts = s.get("created_at", 0)
            ticker = s.get("ticker", "")
            if ticker and ts >= cutoff:
                by_ticker[ticker].append(s)

        # For each pair, track lead/follow patterns
        pair_lags: Dict[Tuple[str, str], List[float]] = defaultdict(list)

        tickers = sorted(by_ticker.keys())
        for i, t_a in enumerate(tickers):
            for t_b in tickers[i + 1:]:
                for sa in by_ticker[t_a]:
                    ts_a = sa.get("created_at", 0)
                    for sb in by_ticker[t_b]:
                        ts_b = sb.get("created_at", 0)
                        diff = ts_b - ts_a
                        if 0 < abs(diff) <= max_lag_s:
                            if diff > 0:
                                # A leads B
                                pair_lags[(t_a, t_b)].append(diff / 3600)
                            else:
                                # B leads A
                                pair_lags[(t_b, t_a)].append(abs(diff) / 3600)

        results = []
        for (leader, follower), lags in pair_lags.items():
            if len(lags) < min_occurrences:
                continue

            avg_lag = sum(lags) / len(lags)
            # Check consistency: how often does leader actually lead?
            reverse_key = (follower, leader)
            reverse_count = len(pair_lags.get(reverse_key, []))
            total = len(lags) + reverse_count
            consistency = len(lags) / total if total > 0 else 0

            if consistency >= 0.6:  # leader leads at least 60% of the time
                results.append(LeadLagPair(
                    leader=leader,
                    follower=follower,
                    avg_lag_hours=round(avg_lag, 1),
                    confidence=round(consistency, 2),
                    occurrences=len(lags),
                ))

        results.sort(key=lambda p: p.confidence * p.occurrences, reverse=True)
        return results

    # ── Network Graph ──

    def build_network_data(
        self,
        matrix: SignalCorrelationMatrix,
        min_correlation: float = 0.2,
        signal_counts: Optional[Dict[str, int]] = None,
    ) -> NetworkGraph:
        """Build network graph data for visualization.

        Parameters
        ----------
        signal_counts:
            Optional {ticker: count} for node sizing.
        """
        counts = signal_counts or {}

        # Nodes
        nodes = []
        for ticker in matrix.tickers:
            count = counts.get(ticker, 1)
            nodes.append({
                "id": ticker,
                "label": ticker,
                "size": min(30, max(5, count)),
                "signals": count,
            })

        # Edges (only pairs above threshold)
        edges = []
        for pair in matrix.pairs:
            if abs(pair.correlation) >= min_correlation:
                color = (
                    "#22c55e" if pair.correlation > 0 else "#ef4444"
                )
                edges.append({
                    "source": pair.ticker_a,
                    "target": pair.ticker_b,
                    "weight": abs(pair.correlation),
                    "correlation": pair.correlation,
                    "color": color,
                    "co_fires": pair.co_fires,
                })

        return NetworkGraph(nodes=nodes, edges=edges)
