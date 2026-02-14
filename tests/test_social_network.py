"""Tests for rot.social.network.NetworkAnalyzer.

Covers: config defaults, signal ingestion, co-mention graph building,
agglomerative clustering, contrarian detection, accessors, LRU eviction,
stale-node cleanup, Jaccard similarity, and edge cases.
"""

from __future__ import annotations

import time

import pytest

from rot.social.network import NetworkAnalyzer, NetworkConfig


# ── Helpers ──────────────────────────────────────────────────────────────────

NOW = time.time()


def _make_analyzer(**config_kw) -> NetworkAnalyzer:
    """Create a NetworkAnalyzer with optional config overrides."""
    cfg = NetworkConfig(**config_kw) if config_kw else None
    return NetworkAnalyzer(config=cfg)


def _ingest_authors_with_shared_tickers(
    analyzer: NetworkAnalyzer,
    authors: list[str],
    tickers: list[str],
    stance: str = "bullish",
    ts: float = NOW,
) -> None:
    """Have each author mention every ticker in *tickers*."""
    for author in authors:
        for ticker in tickers:
            analyzer.ingest_signal(author, ticker, stance, ts)


# ── NetworkConfig defaults & custom values ───────────────────────────────────


class TestNetworkConfig:

    def test_defaults(self):
        cfg = NetworkConfig()
        assert cfg.min_co_mentions == 3
        assert cfg.cluster_similarity_threshold == 0.5
        assert cfg.min_cluster_size == 2
        assert cfg.max_clusters == 50
        assert cfg.contrarian_min_consensus == 5
        assert cfg.contrarian_max_against == 2
        assert cfg.contrarian_min_strength == 0.3
        assert cfg.max_graph_nodes == 500

    def test_custom_values(self):
        cfg = NetworkConfig(
            min_co_mentions=1,
            cluster_similarity_threshold=0.8,
            min_cluster_size=3,
            max_clusters=10,
            contrarian_min_consensus=3,
            contrarian_max_against=1,
            contrarian_min_strength=0.5,
            max_graph_nodes=100,
        )
        assert cfg.min_co_mentions == 1
        assert cfg.cluster_similarity_threshold == 0.8
        assert cfg.min_cluster_size == 3
        assert cfg.max_clusters == 10
        assert cfg.contrarian_min_consensus == 3
        assert cfg.contrarian_max_against == 1
        assert cfg.contrarian_min_strength == 0.5
        assert cfg.max_graph_nodes == 100


# ── ingest_signal ────────────────────────────────────────────────────────────


class TestIngestSignal:

    def test_creates_author_node(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "TSLA", "bullish", NOW)
        stats = a.get_network_stats()
        assert stats["total_authors"] == 1

    def test_updates_existing_node_adds_ticker(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "TSLA", "bullish", NOW)
        a.ingest_signal("alice", "AAPL", "bearish", NOW)
        consensus = a.get_ticker_consensus("TSLA")
        assert consensus["total"] == 1
        consensus2 = a.get_ticker_consensus("AAPL")
        assert consensus2["total"] == 1

    def test_updates_stance_for_same_ticker(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "TSLA", "bullish", NOW)
        a.ingest_signal("alice", "TSLA", "bearish", NOW + 1)
        consensus = a.get_ticker_consensus("TSLA")
        assert consensus["bearish_count"] == 1
        assert consensus["bullish_count"] == 0

    def test_increments_signal_count(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "TSLA", "bullish", NOW)
        a.ingest_signal("alice", "AAPL", "bearish", NOW)
        a.ingest_signal("alice", "NVDA", "bullish", NOW)
        # 3 signals ingested -> node.signal_count == 3
        assert a._nodes["alice"].signal_count == 3

    def test_updates_last_seen(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "TSLA", "bullish", 1000.0)
        a.ingest_signal("alice", "AAPL", "bearish", 2000.0)
        assert a._nodes["alice"].last_seen == 2000.0

    def test_last_seen_does_not_decrease(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "TSLA", "bullish", 2000.0)
        a.ingest_signal("alice", "AAPL", "bearish", 1000.0)
        assert a._nodes["alice"].last_seen == 2000.0

    def test_skips_empty_author(self):
        a = _make_analyzer()
        a.ingest_signal("", "TSLA", "bullish", NOW)
        assert a.get_network_stats()["total_authors"] == 0

    def test_skips_empty_ticker(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "", "bullish", NOW)
        assert a.get_network_stats()["total_authors"] == 0


# ── ingest_signals_batch ─────────────────────────────────────────────────────


class TestIngestSignalsBatch:

    def test_batch_ingestion(self):
        a = _make_analyzer()
        signals = [
            {"author": "alice", "ticker": "TSLA", "stance": "bullish", "created_at": NOW},
            {"author": "bob", "ticker": "AAPL", "stance": "bearish", "created_at": NOW},
            {"author": "carol", "ticker": "NVDA", "stance": "bullish", "created_at": NOW},
        ]
        a.ingest_signals_batch(signals)
        assert a.get_network_stats()["total_authors"] == 3

    def test_batch_skips_empty_author_and_ticker(self):
        a = _make_analyzer()
        signals = [
            {"author": "", "ticker": "TSLA", "stance": "bullish", "created_at": NOW},
            {"author": "bob", "ticker": "", "stance": "bearish", "created_at": NOW},
            {"author": "carol", "ticker": "NVDA", "stance": "bullish", "created_at": NOW},
        ]
        a.ingest_signals_batch(signals)
        assert a.get_network_stats()["total_authors"] == 1

    def test_batch_uses_defaults_for_missing_keys(self):
        a = _make_analyzer()
        signals = [{"author": "alice", "ticker": "TSLA"}]
        a.ingest_signals_batch(signals)
        assert a.get_network_stats()["total_authors"] == 1


# ── build_co_mention_graph ───────────────────────────────────────────────────


class TestBuildCoMentionGraph:

    def test_jaccard_similarity_values(self):
        a = _make_analyzer(min_co_mentions=2)
        # alice: {TSLA, AAPL, NVDA}
        # bob:   {TSLA, AAPL, AMZN}
        # shared = {TSLA, AAPL} = 2
        # union  = {TSLA, AAPL, NVDA, AMZN} = 4
        # Jaccard = 2/4 = 0.5
        for t in ("TSLA", "AAPL", "NVDA"):
            a.ingest_signal("alice", t, "bullish", NOW)
        for t in ("TSLA", "AAPL", "AMZN"):
            a.ingest_signal("bob", t, "bullish", NOW)

        edges = a.build_co_mention_graph()
        assert len(edges) == 1
        pair = ("alice", "bob")
        assert pair in edges
        assert abs(edges[pair] - 0.5) < 1e-9

    def test_min_co_mentions_filter(self):
        a = _make_analyzer(min_co_mentions=3)
        # alice and bob share only 2 tickers -> should be filtered out
        for t in ("TSLA", "AAPL", "NVDA"):
            a.ingest_signal("alice", t, "bullish", NOW)
        for t in ("TSLA", "AAPL", "AMZN"):
            a.ingest_signal("bob", t, "bullish", NOW)

        edges = a.build_co_mention_graph()
        assert len(edges) == 0

    def test_identical_ticker_sets_similarity_one(self):
        a = _make_analyzer(min_co_mentions=1)
        for t in ("TSLA", "AAPL"):
            a.ingest_signal("alice", t, "bullish", NOW)
            a.ingest_signal("bob", t, "bullish", NOW)

        edges = a.build_co_mention_graph()
        assert len(edges) == 1
        pair = ("alice", "bob")
        assert abs(edges[pair] - 1.0) < 1e-9

    def test_canonical_pair_ordering(self):
        a = _make_analyzer(min_co_mentions=1)
        for t in ("TSLA", "AAPL"):
            a.ingest_signal("zebra", t, "bullish", NOW)
            a.ingest_signal("apple", t, "bullish", NOW)

        edges = a.build_co_mention_graph()
        # Lexicographically: ("apple", "zebra")
        assert ("apple", "zebra") in edges
        assert ("zebra", "apple") not in edges

    def test_sorted_descending_by_similarity(self):
        a = _make_analyzer(min_co_mentions=1)
        # alice & bob share 1/2 = 0.5
        # alice & carol share 2/2 = 1.0
        for t in ("TSLA", "AAPL"):
            a.ingest_signal("alice", t, "bullish", NOW)
            a.ingest_signal("carol", t, "bullish", NOW)
        a.ingest_signal("bob", "TSLA", "bullish", NOW)
        a.ingest_signal("bob", "NVDA", "bullish", NOW)

        edges = a.build_co_mention_graph()
        sims = list(edges.values())
        assert sims == sorted(sims, reverse=True)


# ── detect_clusters ──────────────────────────────────────────────────────────


class TestDetectClusters:

    def test_agglomerative_clustering(self):
        # Three authors with identical ticker sets -> merged into one cluster
        a = _make_analyzer(min_co_mentions=2, cluster_similarity_threshold=0.4, min_cluster_size=2)
        tickers = ["TSLA", "AAPL", "NVDA"]
        _ingest_authors_with_shared_tickers(a, ["alice", "bob", "carol"], tickers)

        clusters = a.detect_clusters()
        assert len(clusters) == 1
        assert sorted(clusters[0].authors) == ["alice", "bob", "carol"]

    def test_similarity_threshold_prevents_merge(self):
        # Two authors share only 1 of 3 tickers each -> Jaccard = 1/5 = 0.2
        # With threshold 0.5, they should not merge
        a = _make_analyzer(min_co_mentions=1, cluster_similarity_threshold=0.5, min_cluster_size=2)
        for t in ("TSLA", "AAPL", "NVDA"):
            a.ingest_signal("alice", t, "bullish", NOW)
        for t in ("TSLA", "AMZN", "GOOG"):
            a.ingest_signal("bob", t, "bullish", NOW)

        clusters = a.detect_clusters()
        # Each stays as singleton, which is below min_cluster_size -> no clusters
        assert len(clusters) == 0

    def test_min_cluster_size_filters(self):
        # Two authors form a pair, but min_cluster_size=3 filters them
        a = _make_analyzer(min_co_mentions=1, cluster_similarity_threshold=0.3, min_cluster_size=3)
        tickers = ["TSLA", "AAPL"]
        _ingest_authors_with_shared_tickers(a, ["alice", "bob"], tickers)

        clusters = a.detect_clusters()
        assert len(clusters) == 0

    def test_common_tickers_computed_correctly(self):
        a = _make_analyzer(min_co_mentions=2, cluster_similarity_threshold=0.3, min_cluster_size=2)
        # alice: {TSLA, AAPL, NVDA}
        # bob:   {TSLA, AAPL, AMZN}
        # common = {TSLA, AAPL}
        for t in ("TSLA", "AAPL", "NVDA"):
            a.ingest_signal("alice", t, "bullish", NOW)
        for t in ("TSLA", "AAPL", "AMZN"):
            a.ingest_signal("bob", t, "bullish", NOW)

        clusters = a.detect_clusters()
        assert len(clusters) == 1
        assert sorted(clusters[0].common_tickers) == ["AAPL", "TSLA"]

    def test_stored_internally(self):
        a = _make_analyzer(min_co_mentions=1, cluster_similarity_threshold=0.3, min_cluster_size=2)
        tickers = ["TSLA", "AAPL"]
        _ingest_authors_with_shared_tickers(a, ["alice", "bob"], tickers)

        a.detect_clusters()
        assert len(a.get_clusters()) == 1


# ── detect_contrarian_signals ────────────────────────────────────────────────


class TestDetectContrarianSignals:

    def test_consensus_vs_minority(self):
        # 5 bullish, 1 bearish -> consensus=bullish, contrarian=bearish
        # strength = (5-1)/(5+1) = 4/6 = 0.6667
        a = _make_analyzer(
            contrarian_min_consensus=5,
            contrarian_max_against=2,
            contrarian_min_strength=0.3,
        )
        for i in range(5):
            a.ingest_signal(f"bull_{i}", "TSLA", "bullish", NOW)
        a.ingest_signal("lone_bear", "TSLA", "bearish", NOW)

        signals = a.detect_contrarian_signals(window_hours=24.0)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.ticker == "TSLA"
        assert sig.consensus_stance == "bullish"
        assert sig.contrarian_stance == "bearish"
        assert sig.contrarian_authors == ["lone_bear"]
        assert sig.consensus_author_count == 5
        assert abs(sig.strength - round(4 / 6, 4)) < 1e-4

    def test_strength_calculation(self):
        # 6 bearish, 2 bullish -> strength = (6-2)/(6+2) = 0.5
        a = _make_analyzer(
            contrarian_min_consensus=5,
            contrarian_max_against=2,
            contrarian_min_strength=0.3,
        )
        for i in range(6):
            a.ingest_signal(f"bear_{i}", "AAPL", "bearish", NOW)
        a.ingest_signal("bull_0", "AAPL", "bullish", NOW)
        a.ingest_signal("bull_1", "AAPL", "bullish", NOW)

        signals = a.detect_contrarian_signals(window_hours=24.0)
        assert len(signals) == 1
        assert abs(signals[0].strength - 0.5) < 1e-4
        assert signals[0].consensus_stance == "bearish"
        assert signals[0].contrarian_stance == "bullish"

    def test_not_enough_consensus(self):
        # Only 3 bullish (below min_consensus=5) -> no contrarian signal
        a = _make_analyzer(contrarian_min_consensus=5)
        for i in range(3):
            a.ingest_signal(f"bull_{i}", "TSLA", "bullish", NOW)
        a.ingest_signal("lone_bear", "TSLA", "bearish", NOW)

        signals = a.detect_contrarian_signals(window_hours=24.0)
        assert len(signals) == 0

    def test_too_many_contrarians(self):
        # 5 bullish, 3 bearish -> contrarian_count=3 > max_against=2
        a = _make_analyzer(
            contrarian_min_consensus=5,
            contrarian_max_against=2,
        )
        for i in range(5):
            a.ingest_signal(f"bull_{i}", "TSLA", "bullish", NOW)
        for i in range(3):
            a.ingest_signal(f"bear_{i}", "TSLA", "bearish", NOW)

        signals = a.detect_contrarian_signals(window_hours=24.0)
        assert len(signals) == 0

    def test_mixed_stances_ignored(self):
        # 5 bullish + 5 mixed -> mixed doesn't count for either side
        a = _make_analyzer(contrarian_min_consensus=5)
        for i in range(5):
            a.ingest_signal(f"bull_{i}", "TSLA", "bullish", NOW)
        for i in range(5):
            a.ingest_signal(f"mixed_{i}", "TSLA", "mixed", NOW)

        signals = a.detect_contrarian_signals(window_hours=24.0)
        # No bearish at all -> no contrarian signal
        assert len(signals) == 0

    def test_window_filters_old_authors(self):
        old_ts = NOW - 25 * 3600  # 25 hours ago
        a = _make_analyzer(contrarian_min_consensus=5)
        for i in range(5):
            a.ingest_signal(f"bull_{i}", "TSLA", "bullish", old_ts)
        a.ingest_signal("lone_bear", "TSLA", "bearish", old_ts)

        signals = a.detect_contrarian_signals(window_hours=24.0)
        assert len(signals) == 0

    def test_sorted_by_strength_descending(self):
        a = _make_analyzer(
            contrarian_min_consensus=5,
            contrarian_max_against=2,
            contrarian_min_strength=0.3,
        )
        # TSLA: 5 vs 2 -> strength = 3/7 ~= 0.4286
        for i in range(5):
            a.ingest_signal(f"bull_{i}", "TSLA", "bullish", NOW)
        a.ingest_signal("bear_tsla_0", "TSLA", "bearish", NOW)
        a.ingest_signal("bear_tsla_1", "TSLA", "bearish", NOW)

        # AAPL: 7 vs 1 -> strength = 6/8 = 0.75
        for i in range(7):
            a.ingest_signal(f"aapl_bull_{i}", "AAPL", "bullish", NOW)
        a.ingest_signal("aapl_bear_0", "AAPL", "bearish", NOW)

        signals = a.detect_contrarian_signals(window_hours=24.0)
        assert len(signals) == 2
        assert signals[0].strength >= signals[1].strength
        assert signals[0].ticker == "AAPL"


# ── Accessors ────────────────────────────────────────────────────────────────


class TestAccessors:

    def test_get_clusters_returns_copy(self):
        a = _make_analyzer(min_co_mentions=1, cluster_similarity_threshold=0.3, min_cluster_size=2)
        tickers = ["TSLA", "AAPL"]
        _ingest_authors_with_shared_tickers(a, ["alice", "bob"], tickers)
        a.detect_clusters()

        c1 = a.get_clusters()
        c2 = a.get_clusters()
        assert c1 is not c2
        assert len(c1) == len(c2)

    def test_get_contrarian_signals_limit(self):
        a = _make_analyzer(
            contrarian_min_consensus=5,
            contrarian_max_against=1,
            contrarian_min_strength=0.3,
        )
        # Create 3 contrarian-worthy tickers
        for ticker_idx in range(3):
            ticker = f"T{ticker_idx}"
            for i in range(6):
                a.ingest_signal(f"bull_{ticker}_{i}", ticker, "bullish", NOW)
            a.ingest_signal(f"bear_{ticker}", ticker, "bearish", NOW)

        a.detect_contrarian_signals(window_hours=24.0)
        limited = a.get_contrarian_signals(limit=2)
        assert len(limited) == 2

    def test_get_contrarian_signals_sorted_by_strength(self):
        a = _make_analyzer(
            contrarian_min_consensus=5,
            contrarian_max_against=1,
            contrarian_min_strength=0.3,
        )
        for ticker_idx in range(3):
            ticker = f"T{ticker_idx}"
            for i in range(5 + ticker_idx):
                a.ingest_signal(f"bull_{ticker}_{i}", ticker, "bullish", NOW)
            a.ingest_signal(f"bear_{ticker}", ticker, "bearish", NOW)

        a.detect_contrarian_signals(window_hours=24.0)
        signals = a.get_contrarian_signals()
        strengths = [s.strength for s in signals]
        assert strengths == sorted(strengths, reverse=True)


# ── get_author_connections ───────────────────────────────────────────────────


class TestGetAuthorConnections:

    def test_returns_connections(self):
        a = _make_analyzer(min_co_mentions=2)
        tickers = ["TSLA", "AAPL", "NVDA"]
        for t in tickers:
            a.ingest_signal("alice", t, "bullish", NOW)
            a.ingest_signal("bob", t, "bullish", NOW)

        conns = a.get_author_connections("alice")
        assert len(conns) == 1
        assert conns[0]["author_id"] == "bob"
        assert abs(conns[0]["similarity"] - 1.0) < 1e-4
        assert sorted(conns[0]["common_tickers"]) == ["AAPL", "NVDA", "TSLA"]

    def test_unknown_author_returns_empty(self):
        a = _make_analyzer()
        assert a.get_author_connections("nonexistent") == []

    def test_sorted_by_similarity(self):
        a = _make_analyzer(min_co_mentions=2)
        # alice: {A, B, C, D}
        # bob:   {A, B, C, D} -> sim = 1.0
        # carol: {A, B, E, F} -> sim = 2/6 = 0.333
        for t in ("A", "B", "C", "D"):
            a.ingest_signal("alice", t, "bullish", NOW)
            a.ingest_signal("bob", t, "bullish", NOW)
        for t in ("A", "B", "E", "F"):
            a.ingest_signal("carol", t, "bullish", NOW)

        conns = a.get_author_connections("alice")
        assert len(conns) == 2
        assert conns[0]["author_id"] == "bob"
        assert conns[1]["author_id"] == "carol"


# ── get_ticker_consensus ─────────────────────────────────────────────────────


class TestGetTickerConsensus:

    def test_bullish_bearish_mixed_counts(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "TSLA", "bullish", NOW)
        a.ingest_signal("bob", "TSLA", "bullish", NOW)
        a.ingest_signal("carol", "TSLA", "bearish", NOW)
        a.ingest_signal("dave", "TSLA", "mixed", NOW)

        c = a.get_ticker_consensus("TSLA")
        assert c["ticker"] == "TSLA"
        assert c["bullish_count"] == 2
        assert c["bearish_count"] == 1
        assert c["mixed_count"] == 1
        assert c["total"] == 4
        assert c["dominant_stance"] == "bullish"
        assert abs(c["consensus_pct"] - 0.5) < 1e-4

    def test_unknown_ticker_returns_zeros(self):
        a = _make_analyzer()
        c = a.get_ticker_consensus("NONEXIST")
        assert c["total"] == 0
        assert c["dominant_stance"] == "unknown"
        assert c["consensus_pct"] == 0.0

    def test_bearish_dominant(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "AAPL", "bearish", NOW)
        a.ingest_signal("bob", "AAPL", "bearish", NOW)
        a.ingest_signal("carol", "AAPL", "bullish", NOW)

        c = a.get_ticker_consensus("AAPL")
        assert c["dominant_stance"] == "bearish"
        assert abs(c["consensus_pct"] - round(2 / 3, 4)) < 1e-4

    def test_mixed_dominant_when_most_common(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "SPY", "mixed", NOW)
        a.ingest_signal("bob", "SPY", "mixed", NOW)
        a.ingest_signal("carol", "SPY", "bullish", NOW)

        c = a.get_ticker_consensus("SPY")
        assert c["dominant_stance"] == "mixed"


# ── get_network_stats ────────────────────────────────────────────────────────


class TestGetNetworkStats:

    def test_basic_stats(self):
        a = _make_analyzer(min_co_mentions=2)
        tickers = ["TSLA", "AAPL", "NVDA"]
        _ingest_authors_with_shared_tickers(a, ["alice", "bob"], tickers)

        stats = a.get_network_stats()
        assert stats["total_authors"] == 2
        assert stats["total_edges"] == 1
        assert stats["avg_connections"] == 1.0  # (2*1)/2
        assert stats["total_clusters"] == 0  # detect_clusters not called yet
        assert stats["total_contrarian_signals"] == 0

    def test_top_mentioned_tickers(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "TSLA", "bullish", NOW)
        a.ingest_signal("bob", "TSLA", "bullish", NOW)
        a.ingest_signal("carol", "TSLA", "bullish", NOW)
        a.ingest_signal("dave", "AAPL", "bullish", NOW)

        stats = a.get_network_stats()
        top = stats["top_mentioned_tickers"]
        assert len(top) == 2
        assert top[0]["ticker"] == "TSLA"
        assert top[0]["count"] == 3
        assert top[1]["ticker"] == "AAPL"
        assert top[1]["count"] == 1

    def test_empty_graph_stats(self):
        a = _make_analyzer()
        stats = a.get_network_stats()
        assert stats["total_authors"] == 0
        assert stats["total_edges"] == 0
        assert stats["avg_connections"] == 0.0
        assert stats["top_mentioned_tickers"] == []


# ── LRU eviction ─────────────────────────────────────────────────────────────


class TestLRUEviction:

    def test_evicts_oldest_when_exceeding_max(self):
        a = _make_analyzer(max_graph_nodes=3)
        a.ingest_signal("alice", "TSLA", "bullish", NOW)
        a.ingest_signal("bob", "TSLA", "bullish", NOW)
        a.ingest_signal("carol", "TSLA", "bullish", NOW)
        assert a.get_network_stats()["total_authors"] == 3

        # Adding a 4th should evict alice (oldest / first inserted)
        a.ingest_signal("dave", "TSLA", "bullish", NOW)
        assert a.get_network_stats()["total_authors"] == 3
        assert "alice" not in a._nodes
        assert "dave" in a._nodes

    def test_access_refreshes_lru_position(self):
        a = _make_analyzer(max_graph_nodes=3)
        a.ingest_signal("alice", "TSLA", "bullish", NOW)
        a.ingest_signal("bob", "TSLA", "bullish", NOW)
        a.ingest_signal("carol", "TSLA", "bullish", NOW)

        # Re-ingest alice -> moves to end of LRU
        a.ingest_signal("alice", "AAPL", "bullish", NOW)

        # Now bob is the oldest -> adding dave should evict bob
        a.ingest_signal("dave", "TSLA", "bullish", NOW)
        assert "bob" not in a._nodes
        assert "alice" in a._nodes
        assert "carol" in a._nodes
        assert "dave" in a._nodes


# ── clear_old ────────────────────────────────────────────────────────────────


class TestClearOld:

    def test_removes_stale_nodes(self):
        a = _make_analyzer()
        old_ts = NOW - 100 * 3600  # 100 hours ago
        a.ingest_signal("alice", "TSLA", "bullish", old_ts)
        a.ingest_signal("bob", "TSLA", "bullish", NOW)

        removed = a.clear_old(max_age_hours=72.0)
        assert removed == 1
        assert a.get_network_stats()["total_authors"] == 1
        assert "alice" not in a._nodes

    def test_keeps_recent_nodes(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "TSLA", "bullish", NOW)
        a.ingest_signal("bob", "TSLA", "bullish", NOW)

        removed = a.clear_old(max_age_hours=72.0)
        assert removed == 0
        assert a.get_network_stats()["total_authors"] == 2

    def test_clears_all_when_all_stale(self):
        a = _make_analyzer()
        old_ts = NOW - 200 * 3600
        a.ingest_signal("alice", "TSLA", "bullish", old_ts)
        a.ingest_signal("bob", "TSLA", "bullish", old_ts)

        removed = a.clear_old(max_age_hours=72.0)
        assert removed == 2
        assert a.get_network_stats()["total_authors"] == 0


# ── _jaccard ─────────────────────────────────────────────────────────────────


class TestJaccard:

    def test_identical_sets(self):
        assert NetworkAnalyzer._jaccard({"A", "B", "C"}, {"A", "B", "C"}) == 1.0

    def test_disjoint_sets(self):
        assert NetworkAnalyzer._jaccard({"A", "B"}, {"C", "D"}) == 0.0

    def test_partial_overlap(self):
        # {A, B, C} & {B, C, D} = {B, C} / {A, B, C, D} = 2/4 = 0.5
        result = NetworkAnalyzer._jaccard({"A", "B", "C"}, {"B", "C", "D"})
        assert abs(result - 0.5) < 1e-9

    def test_both_empty(self):
        assert NetworkAnalyzer._jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        assert NetworkAnalyzer._jaccard({"A"}, set()) == 0.0


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_graph_clusters(self):
        a = _make_analyzer()
        clusters = a.detect_clusters()
        assert clusters == []

    def test_empty_graph_contrarians(self):
        a = _make_analyzer()
        signals = a.detect_contrarian_signals()
        assert signals == []

    def test_single_author_no_edges(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "TSLA", "bullish", NOW)
        edges = a.build_co_mention_graph()
        assert len(edges) == 0

    def test_single_author_no_clusters(self):
        a = _make_analyzer()
        a.ingest_signal("alice", "TSLA", "bullish", NOW)
        clusters = a.detect_clusters()
        assert clusters == []

    def test_empty_graph_author_connections(self):
        a = _make_analyzer()
        assert a.get_author_connections("alice") == []

    def test_empty_graph_ticker_consensus(self):
        a = _make_analyzer()
        c = a.get_ticker_consensus("TSLA")
        assert c["total"] == 0
        assert c["dominant_stance"] == "unknown"
