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


# ── Backtest Run CRUD ──


@pytest.mark.asyncio
async def test_save_and_get_backtest_run(db):
    run_id = await db.save_backtest_run(
        user_id="user-1",
        name="Test Run",
        config_json='{"starting_capital": 10000}',
        result_json='{"total_trades": 5}',
    )
    assert run_id

    run = await db.get_backtest_run(run_id)
    assert run is not None
    assert run["name"] == "Test Run"
    assert run["user_id"] == "user-1"
    assert run["config_json"] == '{"starting_capital": 10000}'
    assert run["result_json"] == '{"total_trades": 5}'


@pytest.mark.asyncio
async def test_get_user_backtests(db):
    await db.save_backtest_run("user-1", "Run A", "{}", "{}")
    await db.save_backtest_run("user-1", "Run B", "{}", "{}")
    await db.save_backtest_run("user-2", "Other", "{}", "{}")

    runs = await db.get_user_backtests("user-1")
    assert len(runs) == 2
    # Both runs belong to user-1
    names = {r["name"] for r in runs}
    assert names == {"Run A", "Run B"}


@pytest.mark.asyncio
async def test_delete_backtest_run(db):
    run_id = await db.save_backtest_run("user-1", "ToDelete", "{}", "{}")
    assert await db.delete_backtest_run(run_id, "user-1") is True
    assert await db.get_backtest_run(run_id) is None


@pytest.mark.asyncio
async def test_delete_backtest_run_wrong_user(db):
    run_id = await db.save_backtest_run("user-1", "Protected", "{}", "{}")
    assert await db.delete_backtest_run(run_id, "user-2") is False
    assert await db.get_backtest_run(run_id) is not None


# ── Backtest Strategy CRUD ──


@pytest.mark.asyncio
async def test_save_and_get_strategy(db):
    strat_id = await db.save_backtest_strategy(
        user_id="user-1",
        name="My Strategy",
        description="A test strategy",
        config_json='{"position_size_pct": 5}',
    )
    assert strat_id

    strat = await db.get_backtest_strategy(strat_id)
    assert strat is not None
    assert strat["name"] == "My Strategy"
    assert strat["description"] == "A test strategy"
    assert strat["is_active"] == 1


@pytest.mark.asyncio
async def test_get_user_strategies(db):
    await db.save_backtest_strategy("user-1", "Strat A", "", "{}")
    await db.save_backtest_strategy("user-1", "Strat B", "", "{}")
    await db.save_backtest_strategy("user-2", "Other", "", "{}")

    strats = await db.get_user_backtest_strategies("user-1")
    assert len(strats) == 2


@pytest.mark.asyncio
async def test_update_strategy_result(db):
    strat_id = await db.save_backtest_strategy("user-1", "ToUpdate", "", "{}")
    await db.update_strategy_result(strat_id, '{"total_return": 12.5}')

    strat = await db.get_backtest_strategy(strat_id)
    assert strat["last_result_json"] == '{"total_return": 12.5}'
    assert strat["last_run_at"] > 0


@pytest.mark.asyncio
async def test_delete_strategy_soft(db):
    strat_id = await db.save_backtest_strategy("user-1", "ToDelete", "", "{}")
    assert await db.delete_backtest_strategy(strat_id, "user-1") is True

    # Soft-deleted: still exists but is_active=0
    strat = await db.get_backtest_strategy(strat_id)
    assert strat is not None
    assert strat["is_active"] == 0

    # Not returned in user strategies list
    strats = await db.get_user_backtest_strategies("user-1")
    assert len(strats) == 0


@pytest.mark.asyncio
async def test_delete_strategy_wrong_user(db):
    strat_id = await db.save_backtest_strategy("user-1", "Protected", "", "{}")
    assert await db.delete_backtest_strategy(strat_id, "user-2") is False
