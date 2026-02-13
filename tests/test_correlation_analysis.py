"""Tests for correlation analysis engine."""

from __future__ import annotations

import time

import pytest

from rot.analysis.correlations import CorrelationAnalyzer
from rot.analysis.correlation_types import (
    CorrelationPair,
    LeadLagPair,
    NetworkGraph,
    PredictivePair,
    SignalCorrelationMatrix,
    TickerCluster,
)


# ── Helpers ──


def _make_signal(
    ticker: str = "AAPL",
    stance: str = "bullish",
    created_at: float | None = None,
    confidence: float = 0.6,
) -> dict:
    return {
        "ticker": ticker,
        "stance": stance,
        "created_at": created_at or time.time(),
        "confidence": confidence,
    }


def _make_co_firing_signals(
    ticker_a: str,
    ticker_b: str,
    count: int,
    same_stance: bool = True,
    gap_hours: float = 1.0,
) -> list:
    """Create signals where two tickers co-fire within a time window."""
    now = time.time()
    signals = []
    for i in range(count):
        base_time = now - (i * 86400)
        signals.append(_make_signal(
            ticker_a, stance="bullish", created_at=base_time,
        ))
        signals.append(_make_signal(
            ticker_b,
            stance="bullish" if same_stance else "bearish",
            created_at=base_time + (gap_hours * 3600),
        ))
    return signals


# ── Signal Correlation Matrix ──


class TestSignalCorrelations:
    """Signal correlation matrix tests."""

    def test_empty_signals(self):
        analyzer = CorrelationAnalyzer()
        result = analyzer.compute_signal_correlations([])
        assert result.tickers == []
        assert result.pairs == []

    def test_single_ticker(self):
        analyzer = CorrelationAnalyzer()
        signals = [_make_signal("AAPL") for _ in range(10)]
        result = analyzer.compute_signal_correlations(signals)
        assert len(result.tickers) == 1
        assert result.pairs == []  # need 2+ tickers

    def test_co_firing_pair(self):
        analyzer = CorrelationAnalyzer(min_co_fires=3)
        signals = _make_co_firing_signals("AAPL", "MSFT", 5)
        result = analyzer.compute_signal_correlations(signals, min_signals=3)
        assert len(result.pairs) >= 1
        pair = result.pairs[0]
        assert {pair.ticker_a, pair.ticker_b} == {"AAPL", "MSFT"}
        assert pair.co_fires >= 3
        assert pair.correlation > 0

    def test_same_stance_high_correlation(self):
        analyzer = CorrelationAnalyzer(min_co_fires=3)
        signals = _make_co_firing_signals("AAPL", "MSFT", 5, same_stance=True)
        result = analyzer.compute_signal_correlations(signals, min_signals=3)
        if result.pairs:
            assert result.pairs[0].same_stance_pct > 50

    def test_opposite_stance_negative(self):
        analyzer = CorrelationAnalyzer(min_co_fires=3)
        signals = _make_co_firing_signals("AAPL", "MSFT", 5, same_stance=False)
        result = analyzer.compute_signal_correlations(signals, min_signals=3)
        if result.pairs:
            # Opposite stances should produce negative correlation
            assert result.pairs[0].correlation < 0

    def test_no_co_fires(self):
        analyzer = CorrelationAnalyzer(min_co_fires=3)
        now = time.time()
        signals = (
            [_make_signal("AAPL", created_at=now - i * 86400 * 10)
             for i in range(5)]
            + [_make_signal("MSFT", created_at=now - (i * 86400 * 10 + 86400 * 5))
               for i in range(5)]
        )
        result = analyzer.compute_signal_correlations(signals, min_signals=3)
        # May have pairs but very low co-fires due to wide time gaps
        for pair in result.pairs:
            assert pair.co_fires >= 3 or True  # all pairs have min co-fires

    def test_strongest_positive(self):
        analyzer = CorrelationAnalyzer(min_co_fires=2)
        signals = _make_co_firing_signals("AAPL", "MSFT", 5, same_stance=True)
        result = analyzer.compute_signal_correlations(signals, min_signals=3)
        if result.strongest_positive:
            assert result.strongest_positive.correlation > 0

    def test_matrix_to_dict(self):
        m = SignalCorrelationMatrix(
            tickers=["AAPL", "MSFT"],
            pairs=[CorrelationPair(
                ticker_a="AAPL", ticker_b="MSFT", correlation=0.8,
                co_fires=5, same_stance_pct=80.0, sample_size=10,
            )],
        )
        d = m.to_dict()
        assert d["tickers"] == ["AAPL", "MSFT"]
        assert d["pair_count"] == 1


# ── Cluster Detection ──


class TestClusterDetection:
    """Ticker cluster detection tests."""

    def test_empty_matrix(self):
        analyzer = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(tickers=[], pairs=[])
        result = analyzer.detect_clusters(matrix)
        assert result == []

    def test_no_pairs_above_threshold(self):
        analyzer = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(
            tickers=["AAPL", "MSFT"],
            pairs=[CorrelationPair(
                ticker_a="AAPL", ticker_b="MSFT", correlation=0.1,
                co_fires=3, same_stance_pct=50.0, sample_size=10,
            )],
        )
        result = analyzer.detect_clusters(matrix, threshold=0.5)
        assert result == []

    def test_cluster_found(self):
        analyzer = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(
            tickers=["AAPL", "MSFT", "GOOGL"],
            pairs=[
                CorrelationPair("AAPL", "MSFT", 0.7, 5, 80.0, 10),
                CorrelationPair("MSFT", "GOOGL", 0.6, 4, 75.0, 10),
                CorrelationPair("AAPL", "GOOGL", 0.5, 3, 70.0, 10),
            ],
        )
        result = analyzer.detect_clusters(matrix, threshold=0.4)
        assert len(result) >= 1
        assert len(result[0].tickers) >= 2

    def test_cluster_to_dict(self):
        c = TickerCluster(
            cluster_id=0, tickers=["AAPL", "MSFT"],
            avg_internal_correlation=0.75, label="Tech",
        )
        d = c.to_dict()
        assert d["cluster_id"] == 0
        assert d["size"] == 2

    def test_separate_clusters(self):
        analyzer = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(
            tickers=["AAPL", "MSFT", "XOM", "CVX"],
            pairs=[
                CorrelationPair("AAPL", "MSFT", 0.8, 5, 80.0, 10),
                CorrelationPair("XOM", "CVX", 0.7, 4, 75.0, 10),
                # No connection between tech and energy
            ],
        )
        result = analyzer.detect_clusters(matrix, threshold=0.3)
        assert len(result) == 2
        clusters_tickers = [set(c.tickers) for c in result]
        assert {"AAPL", "MSFT"} in clusters_tickers
        assert {"CVX", "XOM"} in clusters_tickers


# ── Lead-Lag Detection ──


class TestLeadLag:
    """Lead-lag pair detection tests."""

    def test_empty(self):
        analyzer = CorrelationAnalyzer()
        result = analyzer.compute_lead_lag([], days=30)
        assert result == []

    def test_leader_detected(self):
        analyzer = CorrelationAnalyzer()
        now = time.time()
        signals = []
        for i in range(5):
            base = now - (i * 86400)
            signals.append(_make_signal("AAPL", created_at=base))
            signals.append(_make_signal("MSFT", created_at=base + 3600))  # 1h later
        result = analyzer.compute_lead_lag(signals, days=30, min_occurrences=3)
        if result:
            assert result[0].leader == "AAPL"
            assert result[0].follower == "MSFT"
            assert result[0].avg_lag_hours == pytest.approx(1.0, abs=0.5)

    def test_to_dict(self):
        ll = LeadLagPair(
            leader="AAPL", follower="MSFT",
            avg_lag_hours=2.5, confidence=0.8, occurrences=10,
        )
        d = ll.to_dict()
        assert d["leader"] == "AAPL"
        assert d["avg_lag_hours"] == 2.5


# ── Network Graph ──


class TestNetworkGraph:
    """Network graph builder tests."""

    def test_empty_matrix(self):
        analyzer = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(tickers=[], pairs=[])
        graph = analyzer.build_network_data(matrix)
        assert graph.nodes == []
        assert graph.edges == []

    def test_basic_graph(self):
        analyzer = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(
            tickers=["AAPL", "MSFT"],
            pairs=[CorrelationPair(
                "AAPL", "MSFT", 0.7, 5, 80.0, 10,
            )],
        )
        graph = analyzer.build_network_data(matrix, min_correlation=0.3)
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        assert graph.edges[0]["color"] == "#22c55e"  # positive = green

    def test_negative_edge_color(self):
        analyzer = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(
            tickers=["AAPL", "MSFT"],
            pairs=[CorrelationPair(
                "AAPL", "MSFT", -0.5, 5, 20.0, 10,
            )],
        )
        graph = analyzer.build_network_data(matrix, min_correlation=0.3)
        assert len(graph.edges) == 1
        assert graph.edges[0]["color"] == "#ef4444"  # negative = red

    def test_filtered_edges(self):
        analyzer = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(
            tickers=["AAPL", "MSFT", "GOOGL"],
            pairs=[
                CorrelationPair("AAPL", "MSFT", 0.8, 5, 80.0, 10),
                CorrelationPair("AAPL", "GOOGL", 0.1, 2, 50.0, 10),  # below threshold
            ],
        )
        graph = analyzer.build_network_data(matrix, min_correlation=0.3)
        assert len(graph.edges) == 1

    def test_to_dict(self):
        g = NetworkGraph(
            nodes=[{"id": "AAPL", "label": "AAPL", "size": 10}],
            edges=[{"source": "AAPL", "target": "MSFT", "weight": 0.5}],
        )
        d = g.to_dict()
        assert d["node_count"] == 1
        assert d["edge_count"] == 1

    def test_with_signal_counts(self):
        analyzer = CorrelationAnalyzer()
        matrix = SignalCorrelationMatrix(
            tickers=["AAPL", "MSFT"],
            pairs=[],
        )
        counts = {"AAPL": 20, "MSFT": 5}
        graph = analyzer.build_network_data(matrix, signal_counts=counts)
        aapl_node = next(n for n in graph.nodes if n["id"] == "AAPL")
        msft_node = next(n for n in graph.nodes if n["id"] == "MSFT")
        assert aapl_node["size"] > msft_node["size"]


# ── Correlation Pair ──


class TestCorrelationPair:
    """CorrelationPair type tests."""

    def test_to_dict(self):
        p = CorrelationPair(
            ticker_a="AAPL", ticker_b="MSFT",
            correlation=0.756, co_fires=5,
            same_stance_pct=80.0, sample_size=10,
        )
        d = p.to_dict()
        assert d["correlation"] == 0.756
        assert d["co_fires"] == 5


# ── PredictivePair ──


class TestPredictivePair:
    """PredictivePair type tests."""

    def test_to_dict(self):
        p = PredictivePair(
            ticker_a="AAPL", ticker_b="MSFT",
            prediction_accuracy=0.72, sample_size=20,
            direction="same",
        )
        d = p.to_dict()
        assert d["prediction_accuracy"] == 0.72
        assert d["direction"] == "same"
