"""Tests for flow intelligence database operations."""

from __future__ import annotations

import json
import time
import uuid

import pytest

from rot.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    """Create a temporary database with schema."""
    db_path = str(tmp_path / "test_flow.db")
    d = Database(db_path=db_path)
    await d.connect()
    yield d
    await d.close()


# ── Helpers ──────────────────────────────────────────────


def _make_flow_event(
    ticker: str = "SPY",
    flow_type: str = "sweep",
    direction: str = "bullish",
    premium: float = 150000.0,
    volume: int = 500,
    oi_change: int = 200,
    score: float = 72.0,
    details: dict | None = None,
    signal_id: str | None = None,
    detected_at: float | None = None,
    id: str | None = None,
) -> dict:
    return {
        "id": id or str(uuid.uuid4()),
        "ticker": ticker,
        "flow_type": flow_type,
        "direction": direction,
        "premium": premium,
        "volume": volume,
        "oi_change": oi_change,
        "score": score,
        "details": details or {"strike": 450, "expiry": "2026-03-20"},
        "signal_id": signal_id,
        "detected_at": detected_at or time.time(),
    }


def _make_flow_pattern(
    pattern_type: str = "repeat_buyer",
    tickers: list | None = None,
    confidence: float = 0.85,
    timeframe: str = "1d",
    event_count: int = 5,
    details: dict | None = None,
    detected_at: float | None = None,
    id: str | None = None,
) -> dict:
    return {
        "id": id or str(uuid.uuid4()),
        "pattern_type": pattern_type,
        "tickers": tickers or ["AAPL", "MSFT"],
        "confidence": confidence,
        "timeframe": timeframe,
        "event_count": event_count,
        "details": details or {"total_premium": 500000},
        "detected_at": detected_at or time.time(),
    }


def _make_flow_convergence(
    signal_id: str = "sig-001",
    ticker: str = "TSLA",
    flow_event_ids: list | None = None,
    convergence_score: float = 78.5,
    convergence_type: str = "aligned",
    signal_stance: str = "bullish",
    flow_direction: str = "bullish",
    net_flow_premium: float = 250000.0,
    details: dict | None = None,
    detected_at: float | None = None,
    id: str | None = None,
) -> dict:
    return {
        "id": id or str(uuid.uuid4()),
        "signal_id": signal_id,
        "ticker": ticker,
        "flow_event_ids": flow_event_ids or ["fe-001", "fe-002"],
        "convergence_score": convergence_score,
        "convergence_type": convergence_type,
        "signal_stance": signal_stance,
        "flow_direction": flow_direction,
        "net_flow_premium": net_flow_premium,
        "details": details or {"boost": 0.15},
        "detected_at": detected_at or time.time(),
    }


# ── save_flow_event ──────────────────────────────────────


class TestSaveFlowEvent:
    """Tests for single flow event insertion."""

    @pytest.mark.asyncio
    async def test_save_returns_id(self, db):
        event = _make_flow_event()
        returned_id = await db.save_flow_event(event)
        assert returned_id == event["id"]

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, db):
        event = _make_flow_event(
            ticker="AAPL", flow_type="block_trade", direction="bearish",
            premium=200000.0, volume=1000, oi_change=500, score=88.0,
            signal_id="sig-123",
        )
        await db.save_flow_event(event)
        results = await db.get_flow_events(hours=1)
        assert len(results) == 1
        r = results[0]
        assert r["ticker"] == "AAPL"
        assert r["flow_type"] == "block_trade"
        assert r["direction"] == "bearish"
        assert r["premium"] == 200000.0
        assert r["volume"] == 1000
        assert r["oi_change"] == 500
        assert r["score"] == 88.0
        assert r["signal_id"] == "sig-123"

    @pytest.mark.asyncio
    async def test_save_preserves_details(self, db):
        details = {"strike": 200, "expiry": "2026-04-17", "iv": 0.45}
        event = _make_flow_event(details=details)
        await db.save_flow_event(event)
        results = await db.get_flow_events(hours=1)
        assert results[0]["details"]["strike"] == 200
        assert results[0]["details"]["iv"] == 0.45

    @pytest.mark.asyncio
    async def test_save_generates_id_if_missing(self, db):
        event = _make_flow_event()
        del event["id"]
        returned_id = await db.save_flow_event(event)
        assert returned_id  # non-empty UUID generated
        results = await db.get_flow_events(hours=1)
        assert len(results) == 1
        assert results[0]["id"] == returned_id

    @pytest.mark.asyncio
    async def test_save_without_signal_id(self, db):
        event = _make_flow_event(signal_id=None)
        await db.save_flow_event(event)
        results = await db.get_flow_events(hours=1)
        assert results[0]["signal_id"] is None

    @pytest.mark.asyncio
    async def test_idempotent_save_same_id(self, db):
        """INSERT OR IGNORE: saving same ID twice should not create duplicate."""
        fixed_id = str(uuid.uuid4())
        event = _make_flow_event(id=fixed_id, score=60.0)
        await db.save_flow_event(event)
        # Save again with same ID but different score
        event2 = _make_flow_event(id=fixed_id, score=90.0)
        await db.save_flow_event(event2)
        results = await db.get_flow_events(hours=1)
        assert len(results) == 1
        # INSERT OR IGNORE keeps the first insert
        assert results[0]["score"] == 60.0


# ── save_flow_events_batch ───────────────────────────────


class TestSaveFlowEventsBatch:
    """Tests for batch flow event insertion."""

    @pytest.mark.asyncio
    async def test_batch_empty(self, db):
        count = await db.save_flow_events_batch([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_batch_single(self, db):
        events = [_make_flow_event()]
        count = await db.save_flow_events_batch(events)
        assert count == 1

    @pytest.mark.asyncio
    async def test_batch_multiple(self, db):
        events = [
            _make_flow_event("SPY", "sweep", "bullish", 100000),
            _make_flow_event("AAPL", "block_trade", "bearish", 200000),
            _make_flow_event("TSLA", "dark_pool", "neutral", 300000),
        ]
        count = await db.save_flow_events_batch(events)
        assert count == 3
        results = await db.get_flow_events(hours=1)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_batch_preserves_all_fields(self, db):
        event = _make_flow_event(
            ticker="NVDA", flow_type="accumulation", direction="bullish",
            premium=500000.0, volume=2000, oi_change=1500, score=95.0,
            signal_id="sig-batch-1",
        )
        await db.save_flow_events_batch([event])
        results = await db.get_flow_events(hours=1)
        r = results[0]
        assert r["ticker"] == "NVDA"
        assert r["flow_type"] == "accumulation"
        assert r["volume"] == 2000
        assert r["oi_change"] == 1500
        assert r["signal_id"] == "sig-batch-1"


# ── get_flow_events ──────────────────────────────────────


class TestGetFlowEvents:
    """Tests for filtered flow event queries."""

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        results = await db.get_flow_events()
        assert results == []

    @pytest.mark.asyncio
    async def test_basic_query(self, db):
        await db.save_flow_events_batch([
            _make_flow_event("SPY"),
            _make_flow_event("AAPL"),
        ])
        results = await db.get_flow_events(hours=1)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_filter_by_ticker(self, db):
        await db.save_flow_events_batch([
            _make_flow_event("SPY"),
            _make_flow_event("AAPL"),
            _make_flow_event("SPY"),
        ])
        results = await db.get_flow_events(hours=1, ticker="SPY")
        assert len(results) == 2
        assert all(r["ticker"] == "SPY" for r in results)

    @pytest.mark.asyncio
    async def test_filter_by_flow_type(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(flow_type="sweep"),
            _make_flow_event(flow_type="block_trade"),
            _make_flow_event(flow_type="sweep"),
        ])
        results = await db.get_flow_events(hours=1, flow_type="sweep")
        assert len(results) == 2
        assert all(r["flow_type"] == "sweep" for r in results)

    @pytest.mark.asyncio
    async def test_filter_by_direction(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(direction="bullish"),
            _make_flow_event(direction="bearish"),
            _make_flow_event(direction="bullish"),
        ])
        results = await db.get_flow_events(hours=1, direction="bearish")
        assert len(results) == 1
        assert results[0]["direction"] == "bearish"

    @pytest.mark.asyncio
    async def test_filter_by_min_score(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(score=80.0),
            _make_flow_event(score=30.0),
            _make_flow_event(score=65.0),
        ])
        results = await db.get_flow_events(hours=1, min_score=60.0)
        assert len(results) == 2
        assert all(r["score"] >= 60.0 for r in results)

    @pytest.mark.asyncio
    async def test_filter_by_time_window(self, db):
        old = _make_flow_event(detected_at=time.time() - 7200)  # 2h ago
        recent = _make_flow_event(detected_at=time.time())
        await db.save_flow_events_batch([old, recent])
        results = await db.get_flow_events(hours=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_limit(self, db):
        events = [_make_flow_event(ticker=f"T{i}") for i in range(10)]
        await db.save_flow_events_batch(events)
        results = await db.get_flow_events(hours=1, limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_ordered_desc(self, db):
        t1 = time.time() - 120
        t2 = time.time()
        await db.save_flow_events_batch([
            _make_flow_event("SPY", detected_at=t1),
            _make_flow_event("AAPL", detected_at=t2),
        ])
        results = await db.get_flow_events(hours=1)
        assert results[0]["ticker"] == "AAPL"  # newest first

    @pytest.mark.asyncio
    async def test_combined_filters(self, db):
        await db.save_flow_events_batch([
            _make_flow_event("SPY", "sweep", "bullish", score=90.0),
            _make_flow_event("SPY", "sweep", "bearish", score=85.0),
            _make_flow_event("SPY", "block_trade", "bullish", score=80.0),
            _make_flow_event("AAPL", "sweep", "bullish", score=70.0),
        ])
        results = await db.get_flow_events(
            hours=1, ticker="SPY", flow_type="sweep", direction="bullish",
            min_score=50.0,
        )
        assert len(results) == 1
        assert results[0]["score"] == 90.0

    @pytest.mark.asyncio
    async def test_details_parsed_from_json(self, db):
        details = {"strike": 450, "expiry": "2026-03-20", "iv_rank": 85.0}
        await db.save_flow_event(_make_flow_event(details=details))
        results = await db.get_flow_events(hours=1)
        assert isinstance(results[0]["details"], dict)
        assert results[0]["details"]["strike"] == 450
        assert results[0]["details"]["iv_rank"] == 85.0


# ── get_flow_timeline ────────────────────────────────────


class TestGetFlowTimeline:
    """Tests for per-ticker flow timeline."""

    @pytest.mark.asyncio
    async def test_empty_timeline(self, db):
        results = await db.get_flow_timeline("SPY")
        assert results == []

    @pytest.mark.asyncio
    async def test_timeline_for_ticker(self, db):
        await db.save_flow_events_batch([
            _make_flow_event("SPY", "sweep", score=80.0),
            _make_flow_event("AAPL", "block_trade", score=60.0),
            _make_flow_event("SPY", "dark_pool", score=50.0),
        ])
        results = await db.get_flow_timeline("SPY", days=1)
        assert len(results) == 2
        assert all(r["ticker"] == "SPY" for r in results)

    @pytest.mark.asyncio
    async def test_timeline_ordered_asc(self, db):
        t1 = time.time() - 3600
        t2 = time.time()
        await db.save_flow_events_batch([
            _make_flow_event("SPY", detected_at=t2),
            _make_flow_event("SPY", detected_at=t1),
        ])
        results = await db.get_flow_timeline("SPY", days=1)
        assert results[0]["detected_at"] < results[1]["detected_at"]

    @pytest.mark.asyncio
    async def test_timeline_respects_days_window(self, db):
        old = _make_flow_event("SPY", detected_at=time.time() - (8 * 86400))  # 8d ago
        recent = _make_flow_event("SPY", detected_at=time.time())
        await db.save_flow_events_batch([old, recent])
        results = await db.get_flow_timeline("SPY", days=7)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_timeline_details_parsed(self, db):
        details = {"strike": 200, "contract": "SPY 450C 3/20"}
        await db.save_flow_event(_make_flow_event("SPY", details=details))
        results = await db.get_flow_timeline("SPY", days=1)
        assert results[0]["details"]["strike"] == 200


# ── get_flow_summary ─────────────────────────────────────


class TestGetFlowSummary:
    """Tests for aggregate flow summary."""

    @pytest.mark.asyncio
    async def test_empty_summary(self, db):
        summary = await db.get_flow_summary()
        assert summary["total_events"] == 0
        assert summary["unique_tickers"] == 0
        assert summary["total_premium"] == 0
        assert summary["avg_score"] == 0

    @pytest.mark.asyncio
    async def test_summary_counts(self, db):
        await db.save_flow_events_batch([
            _make_flow_event("SPY", premium=100000),
            _make_flow_event("AAPL", premium=200000),
            _make_flow_event("SPY", premium=50000),
        ])
        summary = await db.get_flow_summary(hours=1)
        assert summary["total_events"] == 3
        assert summary["unique_tickers"] == 2

    @pytest.mark.asyncio
    async def test_summary_total_premium(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(premium=100000.0, direction="bullish"),
            _make_flow_event(premium=200000.0, direction="bearish"),
        ])
        summary = await db.get_flow_summary(hours=1)
        assert summary["total_premium"] == 300000.0

    @pytest.mark.asyncio
    async def test_summary_net_premium(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(premium=300000.0, direction="bullish"),
            _make_flow_event(premium=100000.0, direction="bearish"),
            _make_flow_event(premium=50000.0, direction="neutral"),
        ])
        summary = await db.get_flow_summary(hours=1)
        # net = bullish_premium - bearish_premium = 300000 - 100000 = 200000
        assert summary["net_premium"] == 200000.0

    @pytest.mark.asyncio
    async def test_summary_avg_score(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(score=80.0),
            _make_flow_event(score=60.0),
        ])
        summary = await db.get_flow_summary(hours=1)
        assert summary["avg_score"] == 70.0

    @pytest.mark.asyncio
    async def test_summary_direction_counts(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(direction="bullish"),
            _make_flow_event(direction="bullish"),
            _make_flow_event(direction="bearish"),
            _make_flow_event(direction="neutral"),
        ])
        summary = await db.get_flow_summary(hours=1)
        assert summary["bullish_count"] == 2
        assert summary["bearish_count"] == 1
        assert summary["neutral_count"] == 1

    @pytest.mark.asyncio
    async def test_summary_type_breakdown(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(flow_type="sweep", premium=100000),
            _make_flow_event(flow_type="sweep", premium=150000),
            _make_flow_event(flow_type="block_trade", premium=200000),
        ])
        summary = await db.get_flow_summary(hours=1)
        tb = summary["type_breakdown"]
        assert "sweep" in tb
        assert tb["sweep"]["count"] == 2
        assert tb["sweep"]["premium"] == 250000.0
        assert "block_trade" in tb
        assert tb["block_trade"]["count"] == 1

    @pytest.mark.asyncio
    async def test_summary_top_tickers(self, db):
        await db.save_flow_events_batch([
            _make_flow_event("SPY", premium=500000),
            _make_flow_event("SPY", premium=300000),
            _make_flow_event("AAPL", premium=100000),
        ])
        summary = await db.get_flow_summary(hours=1)
        tickers = summary["top_tickers"]
        assert len(tickers) >= 2
        # SPY should be first (higher total premium)
        assert tickers[0]["ticker"] == "SPY"
        assert tickers[0]["count"] == 2
        assert tickers[0]["premium"] == 800000.0

    @pytest.mark.asyncio
    async def test_summary_respects_time_window(self, db):
        old = _make_flow_event(detected_at=time.time() - 7200)  # 2h ago
        recent = _make_flow_event(detected_at=time.time())
        await db.save_flow_events_batch([old, recent])
        summary = await db.get_flow_summary(hours=1)
        assert summary["total_events"] == 1


# ── save_flow_pattern ────────────────────────────────────


class TestSaveFlowPattern:
    """Tests for flow pattern insertion."""

    @pytest.mark.asyncio
    async def test_save_returns_id(self, db):
        pattern = _make_flow_pattern()
        returned_id = await db.save_flow_pattern(pattern)
        assert returned_id == pattern["id"]

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, db):
        pattern = _make_flow_pattern(
            pattern_type="accumulation_sequence",
            tickers=["TSLA", "NVDA"],
            confidence=0.92,
            timeframe="4h",
            event_count=8,
        )
        await db.save_flow_pattern(pattern)
        results = await db.get_flow_patterns(hours=1)
        assert len(results) == 1
        r = results[0]
        assert r["pattern_type"] == "accumulation_sequence"
        assert r["confidence"] == 0.92
        assert r["timeframe"] == "4h"
        assert r["event_count"] == 8

    @pytest.mark.asyncio
    async def test_tickers_stored_as_json(self, db):
        pattern = _make_flow_pattern(tickers=["AAPL", "MSFT", "GOOG"])
        await db.save_flow_pattern(pattern)
        results = await db.get_flow_patterns(hours=1)
        assert results[0]["tickers"] == ["AAPL", "MSFT", "GOOG"]

    @pytest.mark.asyncio
    async def test_details_preserved(self, db):
        details = {"total_premium": 1000000, "repeat_count": 5}
        pattern = _make_flow_pattern(details=details)
        await db.save_flow_pattern(pattern)
        results = await db.get_flow_patterns(hours=1)
        assert results[0]["details"]["total_premium"] == 1000000

    @pytest.mark.asyncio
    async def test_generates_id_if_missing(self, db):
        pattern = _make_flow_pattern()
        del pattern["id"]
        returned_id = await db.save_flow_pattern(pattern)
        assert returned_id  # generated UUID
        results = await db.get_flow_patterns(hours=1)
        assert results[0]["id"] == returned_id

    @pytest.mark.asyncio
    async def test_idempotent_save_same_id(self, db):
        fixed_id = str(uuid.uuid4())
        p1 = _make_flow_pattern(id=fixed_id, confidence=0.5)
        p2 = _make_flow_pattern(id=fixed_id, confidence=0.9)
        await db.save_flow_pattern(p1)
        await db.save_flow_pattern(p2)
        results = await db.get_flow_patterns(hours=1)
        assert len(results) == 1


# ── get_flow_patterns ────────────────────────────────────


class TestGetFlowPatterns:
    """Tests for flow pattern queries."""

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        results = await db.get_flow_patterns()
        assert results == []

    @pytest.mark.asyncio
    async def test_basic_query(self, db):
        await db.save_flow_pattern(_make_flow_pattern())
        await db.save_flow_pattern(_make_flow_pattern())
        results = await db.get_flow_patterns(hours=1)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_filter_by_hours(self, db):
        old = _make_flow_pattern(detected_at=time.time() - 7200)
        recent = _make_flow_pattern(detected_at=time.time())
        await db.save_flow_pattern(old)
        await db.save_flow_pattern(recent)
        results = await db.get_flow_patterns(hours=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_filter_by_pattern_type(self, db):
        await db.save_flow_pattern(_make_flow_pattern(pattern_type="hedging"))
        await db.save_flow_pattern(_make_flow_pattern(pattern_type="rolling"))
        results = await db.get_flow_patterns(hours=1, pattern_type="hedging")
        assert len(results) == 1
        assert results[0]["pattern_type"] == "hedging"

    @pytest.mark.asyncio
    async def test_limit(self, db):
        for _ in range(10):
            await db.save_flow_pattern(_make_flow_pattern())
        results = await db.get_flow_patterns(hours=1, limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_ordered_desc(self, db):
        t1 = time.time() - 120
        t2 = time.time()
        await db.save_flow_pattern(_make_flow_pattern(detected_at=t1))
        await db.save_flow_pattern(_make_flow_pattern(detected_at=t2))
        results = await db.get_flow_patterns(hours=1)
        assert results[0]["detected_at"] >= results[1]["detected_at"]


# ── save_flow_convergence ────────────────────────────────


class TestSaveFlowConvergence:
    """Tests for flow-signal convergence insertion."""

    @pytest.mark.asyncio
    async def test_save_returns_id(self, db):
        conv = _make_flow_convergence()
        returned_id = await db.save_flow_convergence(conv)
        assert returned_id == conv["id"]

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, db):
        conv = _make_flow_convergence(
            signal_id="sig-999",
            ticker="NVDA",
            convergence_score=92.0,
            convergence_type="amplified",
            signal_stance="bullish",
            flow_direction="bullish",
            net_flow_premium=750000.0,
        )
        await db.save_flow_convergence(conv)
        results = await db.get_flow_convergences(hours=1)
        assert len(results) == 1
        r = results[0]
        assert r["signal_id"] == "sig-999"
        assert r["ticker"] == "NVDA"
        assert r["convergence_score"] == 92.0
        assert r["convergence_type"] == "amplified"
        assert r["signal_stance"] == "bullish"
        assert r["flow_direction"] == "bullish"
        assert r["net_flow_premium"] == 750000.0

    @pytest.mark.asyncio
    async def test_flow_event_ids_stored_as_json(self, db):
        ids = ["fe-aaa", "fe-bbb", "fe-ccc"]
        conv = _make_flow_convergence(flow_event_ids=ids)
        await db.save_flow_convergence(conv)
        results = await db.get_flow_convergences(hours=1)
        assert results[0]["flow_event_ids"] == ids

    @pytest.mark.asyncio
    async def test_details_preserved(self, db):
        details = {"boost": 0.25, "flow_count": 3}
        conv = _make_flow_convergence(details=details)
        await db.save_flow_convergence(conv)
        results = await db.get_flow_convergences(hours=1)
        assert results[0]["details"]["boost"] == 0.25

    @pytest.mark.asyncio
    async def test_generates_id_if_missing(self, db):
        conv = _make_flow_convergence()
        del conv["id"]
        returned_id = await db.save_flow_convergence(conv)
        assert returned_id
        results = await db.get_flow_convergences(hours=1)
        assert results[0]["id"] == returned_id

    @pytest.mark.asyncio
    async def test_idempotent_save_same_id(self, db):
        fixed_id = str(uuid.uuid4())
        c1 = _make_flow_convergence(id=fixed_id, convergence_score=50.0)
        c2 = _make_flow_convergence(id=fixed_id, convergence_score=99.0)
        await db.save_flow_convergence(c1)
        await db.save_flow_convergence(c2)
        results = await db.get_flow_convergences(hours=1)
        assert len(results) == 1


# ── get_flow_convergences ────────────────────────────────


class TestGetFlowConvergences:
    """Tests for flow convergence queries."""

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        results = await db.get_flow_convergences()
        assert results == []

    @pytest.mark.asyncio
    async def test_basic_query(self, db):
        await db.save_flow_convergence(_make_flow_convergence())
        await db.save_flow_convergence(_make_flow_convergence())
        results = await db.get_flow_convergences(hours=1)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_filter_by_hours(self, db):
        old = _make_flow_convergence(detected_at=time.time() - 7200)
        recent = _make_flow_convergence(detected_at=time.time())
        await db.save_flow_convergence(old)
        await db.save_flow_convergence(recent)
        results = await db.get_flow_convergences(hours=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_filter_by_ticker(self, db):
        await db.save_flow_convergence(_make_flow_convergence(ticker="TSLA"))
        await db.save_flow_convergence(_make_flow_convergence(ticker="AAPL"))
        results = await db.get_flow_convergences(hours=1, ticker="TSLA")
        assert len(results) == 1
        assert results[0]["ticker"] == "TSLA"

    @pytest.mark.asyncio
    async def test_filter_by_convergence_type(self, db):
        await db.save_flow_convergence(
            _make_flow_convergence(convergence_type="aligned"),
        )
        await db.save_flow_convergence(
            _make_flow_convergence(convergence_type="contradictory"),
        )
        results = await db.get_flow_convergences(
            hours=1, convergence_type="contradictory",
        )
        assert len(results) == 1
        assert results[0]["convergence_type"] == "contradictory"

    @pytest.mark.asyncio
    async def test_limit(self, db):
        for _ in range(10):
            await db.save_flow_convergence(_make_flow_convergence())
        results = await db.get_flow_convergences(hours=1, limit=4)
        assert len(results) == 4

    @pytest.mark.asyncio
    async def test_ordered_by_score_desc(self, db):
        await db.save_flow_convergence(
            _make_flow_convergence(convergence_score=50.0),
        )
        await db.save_flow_convergence(
            _make_flow_convergence(convergence_score=90.0),
        )
        await db.save_flow_convergence(
            _make_flow_convergence(convergence_score=70.0),
        )
        results = await db.get_flow_convergences(hours=1)
        scores = [r["convergence_score"] for r in results]
        assert scores == sorted(scores, reverse=True)


# ── purge_old_flow_data ──────────────────────────────────


class TestPurgeOldFlowData:
    """Tests for flow data cleanup."""

    @pytest.mark.asyncio
    async def test_purge_nothing(self, db):
        count = await db.purge_old_flow_data(keep_days=90)
        assert count == 0

    @pytest.mark.asyncio
    async def test_purge_nothing_when_recent(self, db):
        await db.save_flow_event(_make_flow_event(detected_at=time.time()))
        await db.save_flow_pattern(_make_flow_pattern(detected_at=time.time()))
        await db.save_flow_convergence(_make_flow_convergence(detected_at=time.time()))
        count = await db.purge_old_flow_data(keep_days=90)
        assert count == 0

    @pytest.mark.asyncio
    async def test_purge_old_events(self, db):
        old_time = time.time() - (91 * 86400)  # 91 days ago
        await db.save_flow_events_batch([
            _make_flow_event("SPY", detected_at=old_time),
            _make_flow_event("AAPL", detected_at=time.time()),
        ])
        count = await db.purge_old_flow_data(keep_days=90)
        assert count >= 1
        remaining = await db.get_flow_events(hours=24 * 365)
        assert len(remaining) == 1
        assert remaining[0]["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_purge_old_patterns(self, db):
        old_time = time.time() - (91 * 86400)
        await db.save_flow_pattern(_make_flow_pattern(detected_at=old_time))
        await db.save_flow_pattern(_make_flow_pattern(detected_at=time.time()))
        count = await db.purge_old_flow_data(keep_days=90)
        assert count >= 1
        remaining = await db.get_flow_patterns(hours=24 * 365)
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_purge_old_convergences(self, db):
        old_time = time.time() - (91 * 86400)
        await db.save_flow_convergence(
            _make_flow_convergence(detected_at=old_time),
        )
        await db.save_flow_convergence(
            _make_flow_convergence(detected_at=time.time()),
        )
        count = await db.purge_old_flow_data(keep_days=90)
        assert count >= 1
        remaining = await db.get_flow_convergences(hours=24 * 365)
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_purge_all_tables_at_once(self, db):
        old_time = time.time() - (91 * 86400)
        await db.save_flow_event(_make_flow_event(detected_at=old_time))
        await db.save_flow_pattern(_make_flow_pattern(detected_at=old_time))
        await db.save_flow_convergence(
            _make_flow_convergence(detected_at=old_time),
        )
        count = await db.purge_old_flow_data(keep_days=90)
        assert count == 3

    @pytest.mark.asyncio
    async def test_purge_custom_keep_days(self, db):
        t_15d = time.time() - (15 * 86400)  # 15 days ago
        await db.save_flow_event(_make_flow_event(detected_at=t_15d))
        # keep_days=30 should NOT purge 15-day-old data
        count_30 = await db.purge_old_flow_data(keep_days=30)
        assert count_30 == 0
        # keep_days=10 SHOULD purge 15-day-old data
        count_10 = await db.purge_old_flow_data(keep_days=10)
        assert count_10 == 1


# ── Multiple flow types ──────────────────────────────────


class TestMultipleFlowTypes:
    """Tests for saving and querying events of different types."""

    @pytest.mark.asyncio
    async def test_all_flow_types_in_summary(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(flow_type="sweep", premium=100000),
            _make_flow_event(flow_type="block_trade", premium=200000),
            _make_flow_event(flow_type="dark_pool", premium=300000),
            _make_flow_event(flow_type="accumulation", premium=50000),
            _make_flow_event(flow_type="distribution", premium=75000),
        ])
        summary = await db.get_flow_summary(hours=1)
        assert summary["total_events"] == 5
        tb = summary["type_breakdown"]
        assert len(tb) == 5
        for ft in ("sweep", "block_trade", "dark_pool", "accumulation", "distribution"):
            assert ft in tb
            assert tb[ft]["count"] == 1

    @pytest.mark.asyncio
    async def test_filter_each_flow_type(self, db):
        types = ["sweep", "block_trade", "dark_pool", "accumulation", "distribution"]
        for ft in types:
            await db.save_flow_event(_make_flow_event(flow_type=ft))
        for ft in types:
            results = await db.get_flow_events(hours=1, flow_type=ft)
            assert len(results) == 1
            assert results[0]["flow_type"] == ft


# ── Direction summary ────────────────────────────────────


class TestDirectionSummary:
    """Tests for direction-based aggregation in summary."""

    @pytest.mark.asyncio
    async def test_all_bullish(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(direction="bullish", premium=100000),
            _make_flow_event(direction="bullish", premium=200000),
        ])
        summary = await db.get_flow_summary(hours=1)
        assert summary["bullish_count"] == 2
        assert summary["bearish_count"] == 0
        assert summary["neutral_count"] == 0
        assert summary["net_premium"] == 300000.0

    @pytest.mark.asyncio
    async def test_mixed_directions(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(direction="bullish", premium=500000),
            _make_flow_event(direction="bearish", premium=300000),
            _make_flow_event(direction="neutral", premium=50000),
        ])
        summary = await db.get_flow_summary(hours=1)
        assert summary["bullish_count"] == 1
        assert summary["bearish_count"] == 1
        assert summary["neutral_count"] == 1
        # net = bullish_premium - bearish_premium = 500000 - 300000 = 200000
        assert summary["net_premium"] == 200000.0

    @pytest.mark.asyncio
    async def test_bearish_dominant(self, db):
        await db.save_flow_events_batch([
            _make_flow_event(direction="bullish", premium=100000),
            _make_flow_event(direction="bearish", premium=400000),
        ])
        summary = await db.get_flow_summary(hours=1)
        assert summary["net_premium"] == -300000.0
