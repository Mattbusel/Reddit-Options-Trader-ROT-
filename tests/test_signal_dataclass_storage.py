"""Tests for signal storage with real dataclass objects.

Regression test for the silent storage failure where _to_dict() was shallow
and left nested Evidence/OptionLeg dataclasses unconverted, causing every
insert_signal() call to fail with 'Evidence' object has no attribute 'get'.

The pipeline builds Event, ReasoningPacket, and TradeIdea as dataclass objects,
not dicts. These tests verify the full storage path works with real dataclasses
exactly as the pipeline produces them.
"""
from __future__ import annotations

import json

import pytest

from rot.core.types import (
    Event,
    Evidence,
    OptionLeg,
    ReasoningPacket,
    TradeIdea,
)
from rot.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test_dataclass.db"))
    await database.connect()
    yield database
    await database.close()


# ── Evidence dataclass parametrized tests ──


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence_list,expected_subreddit",
    [
        # Single evidence (normal case)
        (
            [Evidence(post_id="abc", permalink="/r/wsb/abc", subreddit="wallstreetbets", excerpt="TSLA moon")],
            "wallstreetbets",
        ),
        # Empty evidence list
        ([], ""),
        # Multiple evidence objects
        (
            [
                Evidence(post_id="1", permalink="/r/wsb/1", subreddit="wallstreetbets", excerpt="first"),
                Evidence(post_id="2", permalink="/r/stocks/2", subreddit="stocks", excerpt="second"),
                Evidence(post_id="3", permalink="/r/options/3", subreddit="options", excerpt="third"),
            ],
            "wallstreetbets",  # first evidence's subreddit is stored
        ),
    ],
    ids=["single-evidence", "empty-evidence", "multi-evidence"],
)
async def test_insert_signal_with_evidence_dataclasses(db, evidence_list, expected_subreddit):
    """Signals with Evidence dataclass objects must store successfully."""
    event = Event(
        event_type="dd",
        entities=["AAPL"],
        stance="bullish",
        time_horizon="1w",
        evidence=evidence_list,
        confidence=0.75,
        meta={"trend_score": 1.2},
    )
    reasoning = ReasoningPacket(
        thesis="Strong earnings momentum",
        catalyst_window="next week",
        market_expectation="beat estimates",
        invalidations=["guidance cut"],
        recommended_structures=["debit_spread"],
        risk_notes=["high IV"],
    )
    trade_idea = TradeIdea(
        underlying="AAPL",
        strategy="debit_spread",
        legs=[
            OptionLeg(side="buy", kind="call", strike=200.0, expiry="2026-03-20", qty=1),
            OptionLeg(side="sell", kind="call", strike=210.0, expiry="2026-03-20", qty=1),
        ],
        max_loss=250.0,
        thesis="Earnings momentum play",
        time_stop="1w",
        quality_score=0.7,
    )

    signal_data = {
        "run_id": "test_dataclass_run",
        "event": event,
        "reasoning": reasoning,
        "trade_idea": trade_idea,
    }

    signal_id = await db.insert_signal(signal_data)
    assert signal_id is not None, "insert_signal must return a signal ID, not None"

    # Verify the signal was actually stored and is retrievable
    result = await db.get_signal(signal_id)
    assert result is not None, "Signal must be retrievable after insert"
    assert result["ticker"] == "AAPL"
    assert result["stance"] == "bullish"
    assert result["event_type"] == "dd"
    assert result["confidence"] == 0.75
    assert result["subreddit"] == expected_subreddit

    # Verify the permalink was stored (used for dedup)
    if evidence_list:
        assert result["post_url"] == evidence_list[0].permalink


@pytest.mark.asyncio
async def test_insert_signal_with_nested_option_legs(db):
    """TradeIdea with OptionLeg dataclasses must serialize to JSON correctly."""
    legs = [
        OptionLeg(side="buy", kind="call", strike=150.0, expiry="2026-04-17", qty=2),
        OptionLeg(side="sell", kind="call", strike=160.0, expiry="2026-04-17", qty=2),
    ]
    event = Event(
        event_type="earnings_rumor",
        entities=["MSFT"],
        stance="bullish",
        time_horizon="earnings",
        evidence=[Evidence(post_id="x1", permalink="/r/wsb/x1", subreddit="wallstreetbets", excerpt="MSFT calls")],
        confidence=0.8,
    )
    trade_idea = TradeIdea(
        underlying="MSFT",
        strategy="debit_spread",
        legs=legs,
        max_loss=400.0,
        thesis="Earnings beat",
        time_stop="2w",
        quality_score=0.65,
    )
    reasoning = ReasoningPacket(
        thesis="Cloud growth",
        catalyst_window="earnings date",
        market_expectation="positive",
        invalidations=[],
        recommended_structures=["debit_spread"],
        risk_notes=[],
    )

    signal_id = await db.insert_signal({
        "run_id": "test_legs_run",
        "event": event,
        "reasoning": reasoning,
        "trade_idea": trade_idea,
    })
    assert signal_id is not None

    result = await db.get_signal(signal_id)
    assert result is not None

    # The trade_idea column should contain valid JSON with leg details
    trade_json = json.loads(result["trade_idea"])
    assert trade_json["strategy"] == "debit_spread"
    assert len(trade_json["legs"]) == 2
    assert trade_json["legs"][0]["strike"] == 150.0
    assert trade_json["legs"][0]["side"] == "buy"
    assert trade_json["legs"][1]["strike"] == 160.0
    assert trade_json["legs"][1]["side"] == "sell"


@pytest.mark.asyncio
async def test_insert_signal_event_data_contains_evidence(db):
    """The event_data JSON column must contain serialized evidence, not raw objects."""
    evidence = [
        Evidence(post_id="ev1", permalink="/r/wsb/ev1", subreddit="wallstreetbets", excerpt="yolo"),
    ]
    event = Event(
        event_type="dd",
        entities=["NVDA"],
        stance="bearish",
        time_horizon="1w",
        evidence=evidence,
        confidence=0.6,
        meta={"nlp": {"polarity": -0.3, "conviction": 0.8}},
    )
    reasoning = ReasoningPacket(
        thesis="Overvalued",
        catalyst_window="next quarter",
        market_expectation="correction",
        invalidations=["new contract"],
        recommended_structures=["credit_spread"],
        risk_notes=["momentum against"],
    )
    trade_idea = TradeIdea(
        underlying="NVDA",
        strategy="credit_spread",
        legs=[],
        max_loss=300.0,
        thesis="Valuation mean reversion",
        time_stop="1m",
        quality_score=0.55,
    )

    signal_id = await db.insert_signal({
        "run_id": "test_event_data_run",
        "event": event,
        "reasoning": reasoning,
        "trade_idea": trade_idea,
    })
    assert signal_id is not None

    result = await db.get_signal(signal_id)
    event_data = json.loads(result["event_data"])

    # Evidence must be serialized as dicts, not "<Evidence ...>" strings
    assert isinstance(event_data["evidence"], list)
    assert len(event_data["evidence"]) == 1
    assert isinstance(event_data["evidence"][0], dict)
    assert event_data["evidence"][0]["subreddit"] == "wallstreetbets"
    assert event_data["evidence"][0]["permalink"] == "/r/wsb/ev1"


@pytest.mark.asyncio
async def test_signal_count_increments_with_dataclass_signals(db):
    """Multiple dataclass signals must all be stored and counted."""
    tickers = ["AAPL", "TSLA", "GOOG", "AMZN", "META"]
    for i, ticker in enumerate(tickers):
        event = Event(
            event_type="dd",
            entities=[ticker],
            stance="bullish",
            time_horizon="1w",
            evidence=[Evidence(
                post_id=f"post_{i}",
                permalink=f"/r/wsb/post_{i}",
                subreddit="wallstreetbets",
                excerpt=f"{ticker} to the moon",
            )],
            confidence=0.5 + i * 0.05,
        )
        reasoning = ReasoningPacket(
            thesis=f"{ticker} analysis",
            catalyst_window="this week",
            market_expectation="up",
            invalidations=[],
            recommended_structures=["debit_spread"],
            risk_notes=[],
        )
        trade_idea = TradeIdea(
            underlying=ticker,
            strategy="debit_spread",
            legs=[],
            max_loss=100.0,
            thesis="momentum",
            time_stop="1w",
            quality_score=0.5,
        )
        signal_id = await db.insert_signal({
            "run_id": f"run_{i}",
            "event": event,
            "reasoning": reasoning,
            "trade_idea": trade_idea,
        })
        assert signal_id is not None, f"Signal for {ticker} must store successfully"

    count = await db.get_signal_count()
    assert count == 5, f"Expected 5 signals stored, got {count}"


@pytest.mark.asyncio
async def test_mixed_dict_and_dataclass_signals(db):
    """Both dict-based and dataclass-based signals must store correctly."""
    # Dict-based (legacy/test pattern)
    dict_id = await db.insert_signal({
        "run_id": "dict_run",
        "event": {
            "event_type": "dd",
            "entities": ["SPY"],
            "stance": "bearish",
            "time_horizon": "intraday",
            "confidence": 0.7,
            "evidence": [{"post_id": "d1", "permalink": "/r/wsb/d1", "subreddit": "wallstreetbets", "excerpt": "puts"}],
            "meta": {},
        },
        "reasoning": {"thesis": "Dict test", "catalyst_window": "today"},
        "trade_idea": {"underlying": "SPY", "strategy": "debit_spread", "quality_score": 0.5, "legs": []},
    })
    assert dict_id is not None

    # Dataclass-based (real pipeline)
    dc_id = await db.insert_signal({
        "run_id": "dc_run",
        "event": Event(
            event_type="dd",
            entities=["QQQ"],
            stance="bullish",
            time_horizon="intraday",
            evidence=[Evidence(post_id="e1", permalink="/r/wsb/e1", subreddit="wallstreetbets", excerpt="calls")],
            confidence=0.8,
        ),
        "reasoning": ReasoningPacket(
            thesis="Dataclass test",
            catalyst_window="today",
            market_expectation="up",
            invalidations=[],
            recommended_structures=[],
            risk_notes=[],
        ),
        "trade_idea": TradeIdea(
            underlying="QQQ",
            strategy="debit_spread",
            legs=[],
            max_loss=200.0,
            thesis="momentum",
            time_stop="1d",
            quality_score=0.6,
        ),
    })
    assert dc_id is not None

    # Both must be retrievable
    count = await db.get_signal_count()
    assert count == 2
    dict_signal = await db.get_signal(dict_id)
    dc_signal = await db.get_signal(dc_id)
    assert dict_signal["ticker"] == "SPY"
    assert dc_signal["ticker"] == "QQQ"
