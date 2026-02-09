from __future__ import annotations

import pytest
from rot.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_insert_and_get_signal(db):
    signal_data = {
        "run_id": "test_run_1",
        "event": {
            "event_type": "earnings_rumor",
            "entities": ["TSLA"],
            "stance": "bullish",
            "time_horizon": "earnings",
            "confidence": 0.65,
            "evidence": [{"post_id": "abc", "permalink": "/r/wsb/abc", "subreddit": "wallstreetbets", "excerpt": "TSLA calls"}],
            "meta": {"trend_score": 1.5, "market": {"TSLA": {"last_close": 250.0}}},
        },
        "reasoning": {
            "thesis": "Test thesis",
            "catalyst_window": "next week",
        },
        "trade_idea": {
            "underlying": "TSLA",
            "strategy": "debit_spread",
            "quality_score": 0.6,
            "legs": [],
        },
    }

    signal_id = await db.insert_signal(signal_data)
    assert signal_id

    result = await db.get_signal(signal_id)
    assert result is not None
    assert result["ticker"] == "TSLA"
    assert result["stance"] == "bullish"
    assert result["event_type"] == "earnings_rumor"


@pytest.mark.asyncio
async def test_list_signals_with_filters(db):
    for i in range(5):
        await db.insert_signal({
            "run_id": f"run_{i}",
            "event": {
                "entities": ["TSLA" if i < 3 else "AAPL"],
                "stance": "bullish" if i < 3 else "bearish",
                "confidence": 0.5 + i * 0.1,
                "evidence": [{"subreddit": "test", "excerpt": "test"}],
                "meta": {},
            },
            "trade_idea": {"strategy": "none"},
        })

    all_signals = await db.get_signals(limit=10)
    assert len(all_signals) == 5

    tsla_signals = await db.get_signals(ticker="TSLA")
    assert len(tsla_signals) == 3

    bullish_signals = await db.get_signals(stance="bullish")
    assert len(bullish_signals) == 3


@pytest.mark.asyncio
async def test_trending_tickers(db):
    for _ in range(3):
        await db.insert_signal({
            "run_id": "run_1",
            "event": {"entities": ["TSLA"], "confidence": 0.6, "evidence": [{"subreddit": "wsb"}], "meta": {}},
            "trade_idea": {},
        })
    await db.insert_signal({
        "run_id": "run_2",
        "event": {"entities": ["AAPL"], "confidence": 0.5, "evidence": [{"subreddit": "stocks"}], "meta": {}},
        "trade_idea": {},
    })

    trending = await db.get_trending_tickers(hours=1)
    assert len(trending) >= 1
    assert trending[0]["ticker"] == "TSLA"
    assert trending[0]["signal_count"] == 3


@pytest.mark.asyncio
async def test_signal_count(db):
    assert await db.get_signal_count() == 0
    await db.insert_signal({
        "run_id": "r1",
        "event": {"entities": ["SPY"], "evidence": [{"subreddit": "test"}], "meta": {}},
        "trade_idea": {},
    })
    assert await db.get_signal_count() == 1
