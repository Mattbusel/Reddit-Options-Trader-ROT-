"""End-to-end tests for the full 9-stage PipelineRunner.

Tests run ``PipelineRunner.run_once()`` with fully-mocked components so
no network, disk, or external API access is required.  Each test verifies
a different scenario:

  - Happy path (all stages complete, signal emitted)
  - Empty ingest (no snapshots)
  - Invalid symbols filtered out
  - Suppressor enabled (event suppressed)
  - Informational-only source (skips LLM / trade building)
  - on_signal deduplication
  - Return-dict shape and counts
  - Multiple candidates with mixed validity
  - Enricher failure resilience
  - Stub reasoning (circuit-breaker mode)
  - Multiple events from a single candidate
  - Suppressor disabled (no suppression even if set)
  - No on_signal callback (None)
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from rot.app.runner import PipelineRunner
from rot.core.types import (
    Event,
    Evidence,
    OptionLeg,
    Post,
    ReasoningPacket,
    ThreadSnapshot,
    TradeIdea,
    TrendCandidate,
)


# ---------------------------------------------------------------------------
# Helpers — build realistic mock data
# ---------------------------------------------------------------------------

def _make_post(
    post_id: str = "abc123",
    title: str = "$TSLA moon calls 🚀",
    selftext: str = "TSLA going to 500, loading calls",
    subreddit: str = "wallstreetbets",
    flair: str | None = None,
) -> Post:
    return Post(
        id=post_id,
        created_utc=int(time.time()) - 300,
        subreddit=subreddit,
        title=title,
        selftext=selftext,
        url=f"https://reddit.com/r/{subreddit}/comments/{post_id}",
        score=150,
        num_comments=42,
        upvote_ratio=0.92,
        author="test_user",
        permalink=f"/r/{subreddit}/comments/{post_id}/tsla_moon",
        flair=flair,
    )


def _make_snapshot(post: Post | None = None) -> ThreadSnapshot:
    return ThreadSnapshot(
        snapshot_ts=int(time.time()),
        post=post or _make_post(),
    )


def _make_candidate(
    snapshot: ThreadSnapshot | None = None,
    key: str = "cand_1",
    trend_score: float = 0.85,
) -> TrendCandidate:
    snap = snapshot or _make_snapshot()
    return TrendCandidate(
        key=key,
        window_s=600,
        features={"velocity": 1.2, "volume": 3.5},
        trend_score=trend_score,
        reason="rapid upvote velocity",
        snapshot=snap,
    )


def _make_event(
    entities: list[str] | None = None,
    subreddit: str = "wallstreetbets",
    post_id: str = "abc123",
    flair: str | None = None,
    confidence: float = 0.75,
    event_type: str = "squeeze_chatter",
    stance: str = "bullish",
) -> Event:
    ents = entities if entities is not None else ["TSLA"]
    return Event(
        event_type=event_type,
        entities=ents,
        stance=stance,
        time_horizon="1w",
        evidence=[
            Evidence(
                post_id=post_id,
                permalink=f"/r/{subreddit}/comments/{post_id}/tsla_moon",
                subreddit=subreddit,
                excerpt="TSLA going to the moon, loading weekly calls",
            )
        ],
        confidence=confidence,
        meta={"flair": flair} if flair else {},
    )


def _make_reasoning_packet(stub: bool = False) -> ReasoningPacket:
    raw: Dict[str, Any] = {}
    if stub:
        raw = {"stub": True}
    else:
        raw = {"confidence": 0.8, "stance": "bullish", "event_type": "squeeze_chatter"}
    return ReasoningPacket(
        thesis="TSLA shows strong squeeze characteristics",
        catalyst_window="1 week",
        market_expectation="bullish breakout above 450",
        invalidations=["Break below 400 support"],
        recommended_structures=["debit_spread"],
        risk_notes=["High IV environment"],
        raw=raw,
    )


def _make_trade_idea(underlying: str = "TSLA") -> TradeIdea:
    return TradeIdea(
        underlying=underlying,
        strategy="debit_spread",
        legs=[
            OptionLeg(side="buy", kind="call", strike=450.0, expiry="2026-02-20", qty=1),
            OptionLeg(side="sell", kind="call", strike=470.0, expiry="2026-02-20", qty=1),
        ],
        max_loss=350.0,
        thesis="Bullish squeeze setup on TSLA",
        time_stop="2026-02-20",
        quality_score=0.72,
    )


# ---------------------------------------------------------------------------
# Fixture — wired PipelineRunner with all mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_parts():
    """Return a dict of mock components and the assembled PipelineRunner.

    Every external dependency is a ``MagicMock`` pre-wired with sensible
    defaults that produce a single happy-path signal.
    """
    snapshot = _make_snapshot()
    candidate = _make_candidate(snapshot=snapshot)
    event = _make_event()
    packet = _make_reasoning_packet()
    idea = _make_trade_idea()

    ingestor = MagicMock()
    ingestor.poll.return_value = [snapshot]

    trend_engine = MagicMock()
    trend_engine.detect.return_value = [candidate]
    trend_engine.store = MagicMock(spec=[])  # no save method by default

    event_builder = MagicMock()
    event_builder.extract_entities.return_value = ["TSLA"]
    event_builder.from_candidate.return_value = [event]

    enricher = MagicMock()
    enricher.enrich_event.side_effect = lambda e: e  # identity

    symbol_validator = MagicMock()
    symbol_validator.is_valid.side_effect = lambda sym: sym.upper() in {"TSLA", "AAPL", "NVDA"}
    symbol_validator.normalize.side_effect = lambda sym: sym.strip().upper()

    cred = MagicMock()
    cred.score.side_effect = lambda e: e  # identity

    reasoner = MagicMock()
    reasoner.reason.return_value = packet

    trade_builder = MagicMock()
    trade_builder.build.return_value = [idea]

    logger = MagicMock()

    signals_received: List[Dict[str, Any]] = []

    def on_signal(data: Dict[str, Any]) -> None:
        signals_received.append(data)

    runner = PipelineRunner(
        ingestor=ingestor,
        trend_engine=trend_engine,
        event_builder=event_builder,
        cred=cred,
        reasoner=reasoner,
        trade_builder=trade_builder,
        logger=logger,
        enricher=enricher,
        symbol_validator=symbol_validator,
        top_n=10,
        on_signal=on_signal,
    )

    return {
        "runner": runner,
        "ingestor": ingestor,
        "trend_engine": trend_engine,
        "event_builder": event_builder,
        "enricher": enricher,
        "symbol_validator": symbol_validator,
        "cred": cred,
        "reasoner": reasoner,
        "trade_builder": trade_builder,
        "logger": logger,
        "signals": signals_received,
        # raw data used to build the mocks
        "snapshot": snapshot,
        "candidate": candidate,
        "event": event,
        "packet": packet,
        "idea": idea,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipelineE2EHappyPath:
    """Full happy-path: ingest -> trend -> event -> enrich -> score -> reason -> trade -> signal."""

    def test_happy_path_returns_correct_counts(self, pipeline_parts):
        result = pipeline_parts["runner"].run_once()

        assert result["snapshots"] == 1
        assert result["candidates"] == 1
        assert result["events"] == 1
        assert result["trade_ideas"] == 1
        assert result["suppressed"] == 0
        assert result["informational_only"] == 0
        assert result["stubs_skipped"] == 0

    def test_happy_path_signal_emitted(self, pipeline_parts):
        pipeline_parts["runner"].run_once()

        signals = pipeline_parts["signals"]
        assert len(signals) == 1
        sig = signals[0]
        assert "run_id" in sig
        assert "event" in sig
        assert "reasoning" in sig
        assert "trade_idea" in sig

    def test_happy_path_calls_all_stages(self, pipeline_parts):
        pipeline_parts["runner"].run_once()

        pipeline_parts["ingestor"].poll.assert_called_once()
        pipeline_parts["trend_engine"].detect.assert_called_once()
        pipeline_parts["event_builder"].extract_entities.assert_called()
        pipeline_parts["event_builder"].from_candidate.assert_called()
        pipeline_parts["enricher"].enrich_event.assert_called()
        pipeline_parts["cred"].score.assert_called()
        pipeline_parts["reasoner"].reason.assert_called()
        pipeline_parts["trade_builder"].build.assert_called()

    def test_happy_path_return_dict_has_all_keys(self, pipeline_parts):
        result = pipeline_parts["runner"].run_once()

        expected_keys = {
            "run_id",
            "snapshots",
            "candidates",
            "ticker_candidates",
            "ticker_candidate_count",
            "events",
            "suppressed",
            "stubs_skipped",
            "informational_only",
            "trade_ideas",
            "top_signals",
            "top_ticker_signals",
        }
        assert set(result.keys()) == expected_keys

    def test_happy_path_run_id_format(self, pipeline_parts):
        result = pipeline_parts["runner"].run_once()
        assert result["run_id"].startswith("run_")


class TestPipelineE2EEmptyIngest:
    """No snapshots from ingestor -> pipeline should short-circuit gracefully."""

    def test_empty_ingest_no_events(self, pipeline_parts):
        pipeline_parts["ingestor"].poll.return_value = []
        pipeline_parts["trend_engine"].detect.return_value = []
        result = pipeline_parts["runner"].run_once()

        assert result["snapshots"] == 0
        assert result["candidates"] == 0
        assert result["events"] == 0
        assert result["trade_ideas"] == 0

    def test_empty_ingest_no_signals(self, pipeline_parts):
        pipeline_parts["ingestor"].poll.return_value = []
        pipeline_parts["trend_engine"].detect.return_value = []
        pipeline_parts["runner"].run_once()

        assert len(pipeline_parts["signals"]) == 0

    def test_empty_ingest_no_reasoning(self, pipeline_parts):
        pipeline_parts["ingestor"].poll.return_value = []
        pipeline_parts["trend_engine"].detect.return_value = []
        pipeline_parts["runner"].run_once()

        pipeline_parts["reasoner"].reason.assert_not_called()
        pipeline_parts["trade_builder"].build.assert_not_called()


class TestPipelineE2EInvalidSymbols:
    """Events with only invalid symbols should be filtered out entirely."""

    def test_invalid_symbol_filtered(self, pipeline_parts):
        # Event has only XYZ123 (invalid)
        bad_event = _make_event(entities=["XYZ123"])
        pipeline_parts["event_builder"].from_candidate.return_value = [bad_event]

        result = pipeline_parts["runner"].run_once()

        assert result["events"] == 0
        assert result["trade_ideas"] == 0
        pipeline_parts["reasoner"].reason.assert_not_called()

    def test_invalid_symbol_no_signal(self, pipeline_parts):
        bad_event = _make_event(entities=["XYZ123"])
        pipeline_parts["event_builder"].from_candidate.return_value = [bad_event]
        pipeline_parts["runner"].run_once()

        assert len(pipeline_parts["signals"]) == 0

    def test_mixed_valid_invalid_symbols_keeps_valid(self, pipeline_parts):
        # Event has both valid TSLA and invalid XYZ123
        mixed_event = _make_event(entities=["TSLA", "XYZ123"])
        pipeline_parts["event_builder"].from_candidate.return_value = [mixed_event]

        result = pipeline_parts["runner"].run_once()

        assert result["events"] == 1
        assert result["trade_ideas"] == 1

        # The enricher should receive an event with only "TSLA"
        enriched_call_arg = pipeline_parts["enricher"].enrich_event.call_args[0][0]
        assert "TSLA" in enriched_call_arg.entities
        assert "XYZ123" not in enriched_call_arg.entities


class TestPipelineE2ESuppression:
    """Suppressor enabled: events can be suppressed before LLM reasoning."""

    def test_suppressed_event_skips_reasoning(self, pipeline_parts):
        suppressor = MagicMock()
        event = pipeline_parts["event"]
        suppressed_meta = dict(event.meta)
        suppressed_meta["suppressed"] = True
        suppressed_meta["suppression_reason"] = "category_low_win_rate: squeeze_chatter"
        suppressed_event = dataclasses.replace(event, meta=suppressed_meta)
        suppressor.apply.return_value = (suppressed_event, True)

        pipeline_parts["runner"].suppressor = suppressor
        result = pipeline_parts["runner"].run_once()

        assert result["suppressed"] == 1
        assert result["trade_ideas"] == 0
        pipeline_parts["reasoner"].reason.assert_not_called()

    def test_suppressed_event_still_emits_signal(self, pipeline_parts):
        suppressor = MagicMock()
        event = pipeline_parts["event"]
        suppressed_meta = dict(event.meta)
        suppressed_meta["suppressed"] = True
        suppressed_meta["suppression_reason"] = "low win rate"
        suppressed_event = dataclasses.replace(event, meta=suppressed_meta)
        suppressor.apply.return_value = (suppressed_event, True)

        pipeline_parts["runner"].suppressor = suppressor
        pipeline_parts["runner"].run_once()

        signals = pipeline_parts["signals"]
        assert len(signals) == 1
        sig = signals[0]
        assert sig["trade_idea"].strategy == "none"
        assert "suppressed" in sig["trade_idea"].do_not_trade_reasons

    def test_suppressor_disabled_no_suppression(self, pipeline_parts):
        """Suppressor is set but does not suppress this event."""
        suppressor = MagicMock()
        suppressor.apply.side_effect = lambda e: (e, False)

        pipeline_parts["runner"].suppressor = suppressor
        result = pipeline_parts["runner"].run_once()

        assert result["suppressed"] == 0
        assert result["trade_ideas"] == 1
        pipeline_parts["reasoner"].reason.assert_called_once()


class TestPipelineE2EInformationalSource:
    """Informational-only sources (DoD, FDA) skip LLM reasoning + trade building."""

    def test_informational_source_skips_reasoning(self, pipeline_parts):
        # RSS item from FDA press releases
        fda_event = _make_event(
            entities=["PFE"],
            subreddit="fda-press-releases",
            flair="rss",
            event_type="regulatory",
        )
        # Need PFE to be a valid symbol
        pipeline_parts["symbol_validator"].is_valid.side_effect = (
            lambda sym: sym.upper() in {"TSLA", "PFE"}
        )
        pipeline_parts["event_builder"].from_candidate.return_value = [fda_event]
        pipeline_parts["event_builder"].extract_entities.return_value = ["PFE"]

        result = pipeline_parts["runner"].run_once()

        assert result["informational_only"] == 1
        assert result["trade_ideas"] == 0
        pipeline_parts["reasoner"].reason.assert_not_called()

    def test_informational_source_emits_signal_with_no_trade(self, pipeline_parts):
        fda_event = _make_event(
            entities=["PFE"],
            subreddit="fda-press-releases",
            flair="rss",
            event_type="regulatory",
        )
        pipeline_parts["symbol_validator"].is_valid.side_effect = (
            lambda sym: sym.upper() in {"TSLA", "PFE"}
        )
        pipeline_parts["event_builder"].from_candidate.return_value = [fda_event]
        pipeline_parts["event_builder"].extract_entities.return_value = ["PFE"]

        pipeline_parts["runner"].run_once()

        signals = pipeline_parts["signals"]
        assert len(signals) == 1
        sig = signals[0]
        assert sig["trade_idea"].strategy == "none"
        assert "informational_source" in sig["trade_idea"].do_not_trade_reasons
        assert sig["reasoning"].raw.get("informational") is True

    def test_dod_source_is_informational(self, pipeline_parts):
        dod_event = _make_event(
            entities=["LMT"],
            subreddit="dod-contracts",
            flair="rss",
            event_type="product_news",
        )
        pipeline_parts["symbol_validator"].is_valid.side_effect = (
            lambda sym: sym.upper() in {"TSLA", "LMT"}
        )
        pipeline_parts["event_builder"].from_candidate.return_value = [dod_event]
        pipeline_parts["event_builder"].extract_entities.return_value = ["LMT"]

        result = pipeline_parts["runner"].run_once()

        assert result["informational_only"] == 1
        pipeline_parts["reasoner"].reason.assert_not_called()


class TestPipelineE2EDeduplication:
    """on_signal deduplication: same (permalink, ticker) only emitted once."""

    def test_duplicate_signal_not_emitted_twice(self, pipeline_parts):
        # Two identical candidates producing identical events
        snapshot = pipeline_parts["snapshot"]
        cand1 = _make_candidate(snapshot=snapshot, key="cand_1", trend_score=0.9)
        cand2 = _make_candidate(snapshot=snapshot, key="cand_2", trend_score=0.8)

        pipeline_parts["trend_engine"].detect.return_value = [cand1, cand2]

        event = pipeline_parts["event"]
        pipeline_parts["event_builder"].from_candidate.return_value = [event]

        result = pipeline_parts["runner"].run_once()

        # Two events go through reasoning, but only one unique signal emitted
        signals = pipeline_parts["signals"]
        assert len(signals) == 1

    def test_different_tickers_not_deduped(self, pipeline_parts):
        snapshot1 = _make_snapshot(_make_post(post_id="post1", title="$TSLA moon"))
        snapshot2 = _make_snapshot(_make_post(post_id="post2", title="$AAPL calls"))

        cand1 = _make_candidate(snapshot=snapshot1, key="cand_1", trend_score=0.9)
        cand2 = _make_candidate(snapshot=snapshot2, key="cand_2", trend_score=0.8)

        pipeline_parts["trend_engine"].detect.return_value = [cand1, cand2]

        event1 = _make_event(entities=["TSLA"], post_id="post1")
        event2 = _make_event(entities=["AAPL"], post_id="post2")

        # from_candidate returns different events per candidate
        pipeline_parts["event_builder"].from_candidate.side_effect = [
            [event1], [event2]
        ]
        pipeline_parts["event_builder"].extract_entities.side_effect = [
            ["TSLA"], ["AAPL"]
        ]

        pipeline_parts["runner"].run_once()

        signals = pipeline_parts["signals"]
        tickers = {s["event"].entities[0] for s in signals}
        assert tickers == {"TSLA", "AAPL"}

    def test_dedup_set_clears_after_threshold(self, pipeline_parts):
        runner = pipeline_parts["runner"]
        # Stuff 2001 keys into the dedup set
        for i in range(2001):
            runner._emitted_keys.add((f"/r/wsb/comments/{i}", f"SYM{i}"))

        assert len(runner._emitted_keys) == 2001

        # Next run_once triggers _emit_signal which clears if > 2000
        pipeline_parts["runner"].run_once()

        # After clear + new emission, should be small
        assert len(runner._emitted_keys) <= 10


class TestPipelineE2EStubReasoning:
    """Stub reasoning (circuit-breaker mode) increments stubs_skipped count."""

    def test_stub_reasoning_counted(self, pipeline_parts):
        stub_packet = _make_reasoning_packet(stub=True)
        pipeline_parts["reasoner"].reason.return_value = stub_packet

        result = pipeline_parts["runner"].run_once()

        assert result["stubs_skipped"] == 1
        # Trade building still happens for stubs
        assert result["trade_ideas"] == 1

    def test_stub_reasoning_does_not_merge_llm_fields(self, pipeline_parts):
        stub_packet = _make_reasoning_packet(stub=True)
        pipeline_parts["reasoner"].reason.return_value = stub_packet

        pipeline_parts["runner"].run_once()

        # trade_builder.build receives the original event, not one merged with LLM fields
        build_call_args = pipeline_parts["trade_builder"].build.call_args[0]
        event_passed = build_call_args[1]
        # Stub keeps the heuristic confidence (0.75), not the LLM confidence
        assert event_passed.confidence == 0.75


class TestPipelineE2EMultipleEvents:
    """A single candidate can produce multiple events."""

    def test_multiple_events_from_one_candidate(self, pipeline_parts):
        event1 = _make_event(entities=["TSLA"], post_id="abc123")
        event2 = _make_event(entities=["NVDA"], post_id="abc123")

        pipeline_parts["event_builder"].from_candidate.return_value = [event1, event2]

        result = pipeline_parts["runner"].run_once()

        # Both events should flow through the pipeline
        assert result["events"] == 2
        assert result["trade_ideas"] == 2

    def test_multiple_events_emit_multiple_signals(self, pipeline_parts):
        event1 = _make_event(entities=["TSLA"], post_id="abc123")
        event2 = _make_event(entities=["NVDA"], post_id="abc123")

        pipeline_parts["event_builder"].from_candidate.return_value = [event1, event2]

        pipeline_parts["runner"].run_once()

        signals = pipeline_parts["signals"]
        # Different tickers on the same post_id = different dedup keys
        assert len(signals) == 2


class TestPipelineE2EMultipleCandidates:
    """Multiple candidates with mixed symbol validity."""

    def test_mixed_candidates_valid_and_invalid(self, pipeline_parts):
        snap_valid = _make_snapshot(_make_post(post_id="good", title="$TSLA moon"))
        snap_invalid = _make_snapshot(_make_post(post_id="bad", title="$XYZ123 rocket"))

        cand_valid = _make_candidate(snapshot=snap_valid, key="good", trend_score=0.9)
        cand_invalid = _make_candidate(snapshot=snap_invalid, key="bad", trend_score=0.7)

        pipeline_parts["trend_engine"].detect.return_value = [cand_valid, cand_invalid]

        event_valid = _make_event(entities=["TSLA"], post_id="good")
        event_invalid = _make_event(entities=["XYZ123"], post_id="bad")

        pipeline_parts["event_builder"].from_candidate.side_effect = [
            [event_valid], [event_invalid]
        ]
        pipeline_parts["event_builder"].extract_entities.side_effect = [
            ["TSLA"], ["XYZ123"]
        ]

        result = pipeline_parts["runner"].run_once()

        # Only the valid event proceeds
        assert result["events"] == 1
        assert result["trade_ideas"] == 1
        assert result["ticker_candidate_count"] == 1


class TestPipelineE2ENoCallback:
    """on_signal=None should not cause errors."""

    def test_no_callback_runs_without_error(self, pipeline_parts):
        pipeline_parts["runner"].on_signal = None

        result = pipeline_parts["runner"].run_once()

        assert result["trade_ideas"] == 1
        assert result["events"] == 1


class TestPipelineE2ETrendStorePeristence:
    """Trend store save is called when store supports it."""

    def test_trend_store_save_called(self, pipeline_parts):
        pipeline_parts["trend_engine"].store = MagicMock()
        pipeline_parts["trend_engine"].store.save = MagicMock()

        pipeline_parts["runner"].run_once()

        pipeline_parts["trend_engine"].store.save.assert_called_once()

    def test_trend_store_without_save_no_error(self, pipeline_parts):
        # store has no save attribute
        pipeline_parts["trend_engine"].store = object()

        # Should not raise
        result = pipeline_parts["runner"].run_once()
        assert result["snapshots"] == 1


class TestPipelineE2ELLMMerge:
    """LLM-calibrated fields are merged back onto Event for non-stub packets."""

    def test_llm_fields_merged_onto_event(self, pipeline_parts):
        # Packet with LLM-calibrated stance and confidence
        packet = ReasoningPacket(
            thesis="Strong bullish thesis",
            catalyst_window="2 weeks",
            market_expectation="bullish continuation",
            invalidations=["break below support"],
            recommended_structures=["debit_spread"],
            risk_notes=["elevated IV"],
            raw={"confidence": 0.95, "stance": "bullish", "event_type": "earnings_rumor"},
        )
        pipeline_parts["reasoner"].reason.return_value = packet

        pipeline_parts["runner"].run_once()

        # trade_builder receives event with merged LLM confidence
        build_call_args = pipeline_parts["trade_builder"].build.call_args[0]
        event_passed = build_call_args[1]
        assert event_passed.confidence == 0.95
        assert event_passed.stance == "bullish"
        assert event_passed.event_type == "earnings_rumor"

    def test_error_packet_does_not_merge(self, pipeline_parts):
        packet = ReasoningPacket(
            thesis="Error during reasoning",
            catalyst_window="N/A",
            market_expectation="unknown",
            invalidations=[],
            recommended_structures=[],
            risk_notes=[],
            raw={"error": True, "confidence": 0.99},
        )
        pipeline_parts["reasoner"].reason.return_value = packet

        pipeline_parts["runner"].run_once()

        build_call_args = pipeline_parts["trade_builder"].build.call_args[0]
        event_passed = build_call_args[1]
        # Original confidence preserved when packet has error
        assert event_passed.confidence == 0.75


class TestPipelineE2ESignalCallbackError:
    """Signal callback errors must not break the pipeline."""

    def test_callback_exception_does_not_crash(self, pipeline_parts):
        def bad_callback(data: Dict[str, Any]) -> None:
            raise RuntimeError("callback boom")

        pipeline_parts["runner"].on_signal = bad_callback

        # Should not raise
        result = pipeline_parts["runner"].run_once()
        assert result["trade_ideas"] == 1
