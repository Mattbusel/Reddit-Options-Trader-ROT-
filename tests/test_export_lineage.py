"""Tests for signal lineage (provenance) builder."""

from __future__ import annotations

import json
import time

import pytest

from rot.export.lineage import LineageBuilder


# ── Helpers ──


def _make_signal(**overrides) -> dict:
    """Create a minimal signal dict."""
    base = {
        "id": "sig-001",
        "ticker": "AAPL",
        "created_at": 1700000000.0,
        "confidence": 0.65,
        "trend_score": 0.45,
        "strategy": "debit_spread",
        "quality_score": 0.7,
        "subreddit": "wallstreetbets",
        "post_url": "https://reddit.com/r/wsb/abc",
        "event_data": json.dumps({
            "entities": ["AAPL"],
            "meta": {
                "nlp": {
                    "polarity": 0.8,
                    "conviction": 0.6,
                    "sarcasm_probability": 0.1,
                    "classifications": [{"category": "earnings_rumor"}],
                },
                "features": {"score_velocity": 2.5},
                "credibility_factors": ["dd_flair", "high_score"],
                "ml_credibility": {"ml_score": 0.72},
            },
        }),
        "market_data": json.dumps({
            "AAPL": {
                "last_close": 175.50,
                "pct_1d": 1.2,
                "market_cap": 2800000000000,
                "atm_iv": 0.35,
            },
        }),
        "reasoning": json.dumps({
            "thesis": "Strong earnings momentum heading into Q4.",
            "catalyst_window": "2-4 weeks",
            "risk_notes": ["Valuation stretched", "Broad market risk"],
        }),
        "trade_idea": json.dumps({
            "strategy": "debit_spread",
            "quality_score": 0.7,
            "legs": [
                {"side": "buy", "kind": "call", "strike": 175, "expiry": "2024-01-19"},
                {"side": "sell", "kind": "call", "strike": 180, "expiry": "2024-01-19"},
            ],
        }),
    }
    base.update(overrides)
    return base


# ── Tests ──


class TestLineageBuilder:
    """LineageBuilder tests."""

    def test_full_lineage(self):
        builder = LineageBuilder()
        signal = _make_signal()
        lineage = builder.build_lineage(signal)

        assert lineage.signal_id == "sig-001"
        assert lineage.ticker == "AAPL"
        assert lineage.source == "reddit"
        assert lineage.created_at == 1700000000.0

        stages = [s.stage for s in lineage.steps]
        assert "ingestion" in stages
        assert "trend_detection" in stages
        assert "nlp_analysis" in stages
        assert "entity_extraction" in stages
        assert "market_enrichment" in stages
        assert "credibility_scoring" in stages
        assert "llm_reasoning" in stages
        assert "trade_building" in stages
        assert "storage" in stages

    def test_step_order(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage(_make_signal())
        timestamps = [s.timestamp for s in lineage.steps]
        assert timestamps == sorted(timestamps)

    def test_ingestion_step(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage(_make_signal())
        step = lineage.steps[0]
        assert step.stage == "ingestion"
        assert step.details["source"] == "reddit"
        assert step.details["subreddit"] == "wallstreetbets"

    def test_rss_source(self):
        builder = LineageBuilder()
        signal = _make_signal(
            event_data=json.dumps({"meta": {"source_type": "rss"}}),
            subreddit="rss_fda",
        )
        lineage = builder.build_lineage(signal)
        assert lineage.source == "rss"

    def test_nlp_step_details(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage(_make_signal())
        nlp_step = next(s for s in lineage.steps if s.stage == "nlp_analysis")
        assert nlp_step.details["polarity"] == 0.8
        assert nlp_step.details["conviction"] == 0.6

    def test_entity_step(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage(_make_signal())
        entity_step = next(s for s in lineage.steps if s.stage == "entity_extraction")
        assert entity_step.details["entities"] == ["AAPL"]

    def test_market_step(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage(_make_signal())
        market_step = next(s for s in lineage.steps if s.stage == "market_enrichment")
        assert market_step.details["last_close"] == 175.50
        assert market_step.details["atm_iv"] == 0.35

    def test_credibility_step(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage(_make_signal())
        cred_step = next(s for s in lineage.steps if s.stage == "credibility_scoring")
        assert cred_step.details["confidence"] == 0.65
        assert cred_step.details["factors"] == ["dd_flair", "high_score"]
        assert cred_step.details["ml_score"] == 0.72

    def test_reasoning_step(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage(_make_signal())
        reason_step = next(s for s in lineage.steps if s.stage == "llm_reasoning")
        assert "earnings momentum" in reason_step.details["thesis"]
        assert reason_step.details["risk_notes_count"] == 2

    def test_trade_step(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage(_make_signal())
        trade_step = next(s for s in lineage.steps if s.stage == "trade_building")
        assert trade_step.details["strategy"] == "debit_spread"
        assert trade_step.details["legs_count"] == 2

    def test_storage_step(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage(_make_signal())
        storage_step = lineage.steps[-1]
        assert storage_step.stage == "storage"
        assert storage_step.details["signal_id"] == "sig-001"

    def test_minimal_signal(self):
        builder = LineageBuilder()
        signal = {
            "id": "s2",
            "ticker": "TSLA",
            "created_at": 1700000000.0,
            "confidence": 0.3,
        }
        lineage = builder.build_lineage(signal)
        assert lineage.signal_id == "s2"
        assert lineage.ticker == "TSLA"
        # Should always have at least ingestion, credibility, storage
        stages = [s.stage for s in lineage.steps]
        assert "ingestion" in stages
        assert "credibility_scoring" in stages
        assert "storage" in stages

    def test_no_trade_when_none_strategy(self):
        builder = LineageBuilder()
        signal = _make_signal(
            trade_idea=json.dumps({"strategy": "none"}),
        )
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "trade_building" not in stages

    def test_no_reasoning_when_empty(self):
        builder = LineageBuilder()
        signal = _make_signal(reasoning=json.dumps({}))
        lineage = builder.build_lineage(signal)
        stages = [s.stage for s in lineage.steps]
        assert "llm_reasoning" not in stages

    def test_malformed_json_fields(self):
        builder = LineageBuilder()
        signal = _make_signal(
            event_data="not-json",
            market_data="not-json",
            reasoning="not-json",
            trade_idea="not-json",
        )
        lineage = builder.build_lineage(signal)
        # Should not crash — falls back gracefully
        assert lineage.signal_id == "sig-001"

    def test_batch_lineage(self):
        builder = LineageBuilder()
        signals = [
            _make_signal(id="s1", ticker="AAPL"),
            _make_signal(id="s2", ticker="MSFT"),
        ]
        results = builder.build_batch_lineage(signals)
        assert len(results) == 2
        assert results[0].ticker == "AAPL"
        assert results[1].ticker == "MSFT"

    def test_to_dict_round_trip(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage(_make_signal())
        d = lineage.to_dict()
        assert d["signal_id"] == "sig-001"
        assert len(d["steps"]) >= 7
        assert d["total_processing_time_s"] > 0

    def test_processing_time(self):
        builder = LineageBuilder()
        lineage = builder.build_lineage(_make_signal())
        # Steps go from ts+0.0 to ts+0.8, so processing time = 0.8
        assert lineage.total_processing_time_s == pytest.approx(0.8, abs=0.01)

    def test_stocktwits_source_detection(self):
        builder = LineageBuilder()
        signal = _make_signal(
            event_data=json.dumps({"meta": {"stocktwits": True}}),
        )
        lineage = builder.build_lineage(signal)
        assert lineage.source == "stocktwits"
