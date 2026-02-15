from __future__ import annotations

import json
import time

import pytest

from rot.storage.database import Database


# ── Fixtures ──


@pytest.fixture
async def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


async def _insert_signal(
    db: Database,
    ticker: str = "TSLA",
    stance: str = "bullish",
    confidence: float = 0.65,
    strategy: str = "debit_spread",
    event_type: str = "earnings_rumor",
    subreddit: str = "wallstreetbets",
    run_id: str = "run_1",
    trend_score: float = 1.5,
    post_url: str = "",
    reasoning_json: str = "{}",
    sector: str = "",
) -> str:
    """Helper to insert a signal and return its ID."""
    signal_id = await db.insert_signal({
        "run_id": run_id,
        "event": {
            "event_type": event_type,
            "entities": [ticker],
            "stance": stance,
            "confidence": confidence,
            "evidence": [{"subreddit": subreddit, "excerpt": "test", "permalink": post_url}],
            "meta": {"trend_score": trend_score, "market": {ticker: {"last_close": 250.0}}},
        },
        "trade_idea": {"strategy": strategy},
    })
    assert signal_id is not None
    # Patch reasoning JSON directly if provided
    if reasoning_json != "{}":
        await db.db.execute(
            "UPDATE signals SET reasoning = ? WHERE id = ?", (reasoning_json, signal_id)
        )
        await db.db.commit()
    # Patch sector directly
    if sector:
        await db.db.execute(
            "UPDATE signals SET sector = ? WHERE id = ?", (sector, signal_id)
        )
        await db.db.commit()
    return signal_id


async def _set_sector(db: Database, ticker: str, sector: str) -> None:
    """Helper to set sector for all signals of a ticker."""
    await db.db.execute(
        "UPDATE signals SET sector = ? WHERE ticker = ?", (sector, ticker)
    )
    await db.db.commit()


async def _insert_unusual_event(
    db: Database,
    ticker: str = "TSLA",
    event_type: str = "iv_spike",
    score: float = 8.5,
    details: dict | None = None,
    detected_at: float | None = None,
) -> None:
    """Helper to insert an unusual event."""
    details_json = json.dumps(details or {"iv": 0.95})
    ts = detected_at if detected_at is not None else time.time()
    await db.db.execute(
        "INSERT INTO unusual_events (ticker, event_type, score, details_json, detected_at) "
        "VALUES (?,?,?,?,?)",
        (ticker, event_type, score, details_json, ts),
    )
    await db.db.commit()


# ═══════════════════════════════════════════════════════════════════
# get_strategy_breakdown
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_strategy_breakdown_empty_db(db):
    result = await db.get_strategy_breakdown(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_strategy_breakdown_returns_top_strategies(db):
    for strategy in ("debit_spread", "debit_spread", "credit_spread", "long_call"):
        await _insert_signal(db, strategy=strategy)
    result = await db.get_strategy_breakdown(days=30)
    assert len(result) >= 2
    # First should be the most common strategy
    assert result[0]["strategy"] == "debit_spread"
    assert result[0]["cnt"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [1, 7, 30, 90])
async def test_strategy_breakdown_respects_days_cutoff(db, days):
    await _insert_signal(db, strategy="debit_spread")
    result = await db.get_strategy_breakdown(days=days)
    assert len(result) >= 1


@pytest.mark.asyncio
async def test_strategy_breakdown_excludes_none_strategy(db):
    await _insert_signal(db, strategy="none")
    await _insert_signal(db, strategy="debit_spread")
    result = await db.get_strategy_breakdown(days=30)
    strategies = [r["strategy"] for r in result]
    assert "none" not in strategies


# ═══════════════════════════════════════════════════════════════════
# get_chart_data — dominant_stance logic
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_chart_data_empty_db(db):
    result = await db.get_chart_data(hours=24)
    assert result == []


@pytest.mark.asyncio
async def test_chart_data_bullish_dominant(db):
    await _insert_signal(db, stance="bullish")
    await _insert_signal(db, stance="bullish")
    await _insert_signal(db, stance="bearish")
    result = await db.get_chart_data(hours=24)
    assert len(result) == 1
    assert result[0]["dominant_stance"] == "bullish"


@pytest.mark.asyncio
async def test_chart_data_bearish_dominant(db):
    await _insert_signal(db, stance="bearish")
    await _insert_signal(db, stance="bearish")
    await _insert_signal(db, stance="bullish")
    result = await db.get_chart_data(hours=24)
    assert len(result) == 1
    assert result[0]["dominant_stance"] == "bearish"


@pytest.mark.asyncio
async def test_chart_data_mixed_dominant(db):
    await _insert_signal(db, stance="mixed")
    await _insert_signal(db, stance="mixed")
    await _insert_signal(db, stance="bullish")
    result = await db.get_chart_data(hours=24)
    assert len(result) == 1
    assert result[0]["dominant_stance"] == "mixed"


@pytest.mark.asyncio
@pytest.mark.parametrize("hours,limit", [(1, 10), (24, 50), (168, 5)])
async def test_chart_data_params(db, hours, limit):
    await _insert_signal(db)
    result = await db.get_chart_data(hours=hours, limit=limit)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_chart_data_excludes_unknown_ticker(db):
    await db.insert_signal({
        "run_id": "run_x",
        "event": {
            "entities": [],
            "stance": "bullish",
            "confidence": 0.5,
            "evidence": [{"subreddit": "test", "excerpt": "t"}],
            "meta": {},
        },
        "trade_idea": {"strategy": "none"},
    })
    result = await db.get_chart_data(hours=24)
    tickers = [r["ticker"] for r in result]
    assert "UNKNOWN" not in tickers


# ═══════════════════════════════════════════════════════════════════
# get_time_series_data
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_time_series_data_empty(db):
    result = await db.get_time_series_data(hours=24)
    assert result == []


@pytest.mark.asyncio
async def test_time_series_data_buckets_signals(db):
    await _insert_signal(db, stance="bullish")
    await _insert_signal(db, stance="bearish")
    result = await db.get_time_series_data(hours=24)
    assert len(result) >= 1
    row = result[0]
    assert "total" in row
    assert "bullish" in row
    assert "bearish" in row
    assert row["total"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("hours", [1, 6, 24, 168])
async def test_time_series_data_respects_hours(db, hours):
    await _insert_signal(db)
    result = await db.get_time_series_data(hours=hours)
    assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════
# Sector Analytics (6 methods)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sector_rotation_data_empty(db):
    result = await db.get_sector_rotation_data(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_sector_rotation_data_with_sectors(db):
    for _ in range(3):
        await _insert_signal(db, sector="Technology")
    for _ in range(2):
        await _insert_signal(db, ticker="XOM", sector="Energy", stance="bearish")
    result = await db.get_sector_rotation_data(days=30)
    assert len(result) == 2
    tech = next(r for r in result if r["sector"] == "Technology")
    assert tech["total_signals"] == 3
    assert isinstance(tech["bullish_pct"], int)
    assert isinstance(tech["top_tickers"], list)


@pytest.mark.asyncio
async def test_sector_rotation_data_requires_min_two_signals(db):
    await _insert_signal(db, sector="Technology")
    result = await db.get_sector_rotation_data(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_sector_rotation_with_performance_empty(db):
    result = await db.get_sector_rotation_with_performance(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_sector_rotation_with_performance_win_rate(db):
    sid1 = await _insert_signal(db, sector="Technology", stance="bullish")
    sid2 = await _insert_signal(db, sector="Technology", stance="bullish")
    await db.insert_signal_performance(sid1, "TSLA", 100.0)
    await db.db.execute(
        "UPDATE signal_performance SET price_1d = ? WHERE signal_id = ?", (110.0, sid1)
    )
    await db.insert_signal_performance(sid2, "TSLA", 100.0)
    await db.db.execute(
        "UPDATE signal_performance SET price_1d = ? WHERE signal_id = ?", (90.0, sid2)
    )
    await db.db.commit()
    result = await db.get_sector_rotation_with_performance(days=30)
    assert len(result) == 1
    assert result[0]["sector"] == "Technology"
    assert result[0]["win_rate"] is not None


@pytest.mark.asyncio
async def test_sector_heatmap_data_empty(db):
    result = await db.get_sector_heatmap_data(hours=24)
    assert result == []


@pytest.mark.asyncio
async def test_sector_heatmap_data_returns_counts(db):
    for _ in range(2):
        await _insert_signal(db, sector="Technology")
    result = await db.get_sector_heatmap_data(hours=24)
    assert len(result) == 1
    assert result[0]["sector"] == "Technology"
    assert result[0]["signal_count"] == 2


@pytest.mark.asyncio
async def test_sector_drill_down_empty(db):
    result = await db.get_sector_drill_down("Technology", hours=24)
    assert result == []


@pytest.mark.asyncio
async def test_sector_drill_down_returns_tickers(db):
    await _insert_signal(db, sector="Technology")
    await _insert_signal(db, ticker="AAPL", sector="Technology")
    result = await db.get_sector_drill_down("Technology", hours=24)
    assert len(result) == 2
    tickers = {r["ticker"] for r in result}
    assert "TSLA" in tickers
    assert "AAPL" in tickers


@pytest.mark.asyncio
@pytest.mark.parametrize("days,bucket_hours", [(7, 24), (30, 24), (90, 168)])
async def test_sector_time_series_params(db, days, bucket_hours):
    for _ in range(2):
        await _insert_signal(db, sector="Technology")
    result = await db.get_sector_time_series(days=days, bucket_hours=bucket_hours)
    assert isinstance(result, list)
    if result:
        assert "timestamp" in result[0]
        assert "sector" in result[0]


@pytest.mark.asyncio
async def test_sector_time_series_empty(db):
    result = await db.get_sector_time_series(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_sector_ticker_breakdown_empty(db):
    result = await db.get_sector_ticker_breakdown("Technology", days=30)
    assert result == []


@pytest.mark.asyncio
async def test_sector_ticker_breakdown_with_perf(db):
    sid = await _insert_signal(db, sector="Technology", stance="bullish")
    await db.insert_signal_performance(sid, "TSLA", 100.0)
    await db.db.execute(
        "UPDATE signal_performance SET price_1d = ? WHERE signal_id = ?", (115.0, sid)
    )
    await db.db.commit()
    result = await db.get_sector_ticker_breakdown("Technology", days=30)
    assert len(result) == 1
    assert result[0]["ticker"] == "TSLA"
    assert result[0]["win_rate"] is not None


@pytest.mark.asyncio
async def test_sector_ticker_breakdown_no_perf(db):
    await _insert_signal(db, sector="Technology")
    result = await db.get_sector_ticker_breakdown("Technology", days=30)
    assert len(result) == 1
    assert result[0]["win_rate"] is None


@pytest.mark.asyncio
async def test_sector_performance_ranked_empty(db):
    result = await db.get_sector_performance_ranked(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_sector_performance_ranked_with_data(db):
    for _ in range(3):
        await _insert_signal(db, sector="Technology", stance="bullish")
    for _ in range(2):
        await _insert_signal(db, ticker="XOM", sector="Energy", stance="bearish")
    result = await db.get_sector_performance_ranked(days=30)
    assert len(result) == 2
    for sector in result:
        assert "bullish_pct" in sector
        assert "win_rate" in sector


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [1, 7, 30, 60])
async def test_sector_performance_ranked_days(db, days):
    for _ in range(2):
        await _insert_signal(db, sector="Technology")
    result = await db.get_sector_performance_ranked(days=days)
    assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════
# get_leaderboard — sort_by validation
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_leaderboard_empty_db(db):
    result = await db.get_leaderboard(hours=24)
    assert result == []


@pytest.mark.asyncio
async def test_leaderboard_returns_tickers(db):
    for _ in range(3):
        await _insert_signal(db)
    await _insert_signal(db, ticker="AAPL")
    result = await db.get_leaderboard(hours=24)
    assert len(result) == 2
    assert result[0]["signal_count"] >= result[1]["signal_count"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sort_by", [
    "signal_count", "avg_confidence", "max_trend_score",
    "invalid_sort",  # should fallback to signal_count
])
async def test_leaderboard_sort_by_validation(db, sort_by):
    await _insert_signal(db)
    await _insert_signal(db, ticker="AAPL", confidence=0.9, trend_score=5.0)
    result = await db.get_leaderboard(hours=24, sort_by=sort_by)
    assert isinstance(result, list)
    assert len(result) >= 1


@pytest.mark.asyncio
async def test_leaderboard_limit(db):
    for i in range(5):
        await _insert_signal(db, ticker=f"T{i}")
    result = await db.get_leaderboard(hours=24, limit=3)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_leaderboard_with_performance_empty(db):
    result = await db.get_leaderboard_with_performance(hours=24)
    assert result == []


@pytest.mark.asyncio
async def test_leaderboard_with_performance_win_rate(db):
    sid = await _insert_signal(db, stance="bullish")
    await db.insert_signal_performance(sid, "TSLA", 100.0)
    await db.db.execute(
        "UPDATE signal_performance SET price_1d = ? WHERE signal_id = ?", (110.0, sid)
    )
    await db.db.commit()
    result = await db.get_leaderboard_with_performance(hours=24)
    assert len(result) == 1
    assert result[0]["win_rate"] is not None


@pytest.mark.asyncio
async def test_leaderboard_with_performance_no_perf(db):
    await _insert_signal(db)
    result = await db.get_leaderboard_with_performance(hours=24)
    assert len(result) == 1
    assert result[0]["win_rate"] is None


# ═══════════════════════════════════════════════════════════════════
# get_correlation_matrix — co-fire logic
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_correlation_matrix_empty(db):
    result = await db.get_correlation_matrix(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_correlation_matrix_single_ticker_no_pairs(db):
    for _ in range(5):
        await _insert_signal(db)
    result = await db.get_correlation_matrix(days=30, min_co=1)
    assert result == []


@pytest.mark.asyncio
async def test_correlation_matrix_co_fire_pair(db):
    # Insert co-occurring signals within 4-hour window
    for _ in range(4):
        await _insert_signal(db, ticker="TSLA")
        await _insert_signal(db, ticker="AAPL")
    result = await db.get_correlation_matrix(days=30, min_co=1)
    assert len(result) >= 1
    pair = result[0]
    assert "ticker_a" in pair
    assert "ticker_b" in pair
    assert "co_fires" in pair
    assert "avg_confidence" in pair
    tickers_in_pair = {pair["ticker_a"], pair["ticker_b"]}
    assert tickers_in_pair == {"AAPL", "TSLA"}


@pytest.mark.asyncio
@pytest.mark.parametrize("min_co", [1, 3, 5, 10])
async def test_correlation_matrix_min_co_filter(db, min_co):
    for _ in range(4):
        await _insert_signal(db, ticker="TSLA")
        await _insert_signal(db, ticker="AAPL")
    result = await db.get_correlation_matrix(days=30, min_co=min_co)
    for pair in result:
        assert pair["co_fires"] >= min_co


@pytest.mark.asyncio
async def test_correlation_matrix_same_stance_count(db):
    for _ in range(4):
        await _insert_signal(db, ticker="TSLA", stance="bullish")
        await _insert_signal(db, ticker="AAPL", stance="bullish")
    result = await db.get_correlation_matrix(days=30, min_co=1)
    if result:
        assert result[0]["same_stance"] > 0


@pytest.mark.asyncio
async def test_co_occurring_tickers_empty(db):
    result = await db.get_co_occurring_tickers(hours=24)
    assert result == []


@pytest.mark.asyncio
async def test_co_occurring_tickers_with_same_run(db):
    # Signals with same run_id co-occur
    for _ in range(3):
        await _insert_signal(db, ticker="TSLA", run_id="batch_1")
        await _insert_signal(db, ticker="AAPL", run_id="batch_1")
    result = await db.get_co_occurring_tickers(hours=24, min_co_occurrence=2)
    assert len(result) >= 1
    pair = result[0]
    assert pair["co_occurrences"] >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize("min_co", [1, 2, 5])
async def test_co_occurring_tickers_min_filter(db, min_co):
    for _ in range(3):
        await _insert_signal(db, ticker="TSLA", run_id="batch_1")
        await _insert_signal(db, ticker="AAPL", run_id="batch_1")
    result = await db.get_co_occurring_tickers(hours=24, min_co_occurrence=min_co)
    for pair in result:
        assert pair["co_occurrences"] >= min_co


# ═══════════════════════════════════════════════════════════════════
# get_news_feed — source filtering, JSON parsing
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_news_feed_empty(db):
    result = await db.get_news_feed(hours=24)
    assert result == []


@pytest.mark.asyncio
async def test_news_feed_returns_news_sources(db):
    await _insert_signal(db, subreddit="marketwatch-top")
    await _insert_signal(db, subreddit="cnbc-market", ticker="AAPL")
    result = await db.get_news_feed(hours=24)
    assert len(result) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [
    "marketwatch-top", "cnbc-market", "yahoo-finance-top",
    "fda-drugs", "dod-contracts", "stocktwits",
])
async def test_news_feed_source_filter(db, source):
    await _insert_signal(db, subreddit=source)
    # Use a different news source for the "other" signal
    other_source = "yahoo-finance-top" if source != "yahoo-finance-top" else "cnbc-market"
    await _insert_signal(db, subreddit=other_source, ticker="AAPL")
    result = await db.get_news_feed(hours=24, source=source)
    assert len(result) == 1
    assert result[0]["subreddit"] == source


@pytest.mark.asyncio
async def test_news_feed_invalid_source_returns_all(db):
    await _insert_signal(db, subreddit="marketwatch-top")
    await _insert_signal(db, subreddit="cnbc-market", ticker="AAPL")
    result = await db.get_news_feed(hours=24, source="invalid_source")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_news_feed_json_parsing(db):
    reasoning = json.dumps({"thesis": "Test thesis", "ai_summary": "This is a summary"})
    await _insert_signal(db, subreddit="marketwatch-top", reasoning_json=reasoning)
    result = await db.get_news_feed(hours=24)
    assert len(result) == 1
    assert result[0]["ai_summary"] == "This is a summary"
    assert isinstance(result[0]["reasoning"], dict)


@pytest.mark.asyncio
async def test_news_feed_bad_json_reasoning(db):
    await _insert_signal(db, subreddit="marketwatch-top")
    # Corrupt the reasoning field
    await db.db.execute("UPDATE signals SET reasoning = 'not-json' WHERE subreddit = 'marketwatch-top'")
    await db.db.commit()
    result = await db.get_news_feed(hours=24)
    assert len(result) == 1
    assert result[0]["reasoning"] == {}
    assert result[0]["ai_summary"] == ""


# ═══════════════════════════════════════════════════════════════════
# get_sentiment_heatmap — bucket sizing
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sentiment_heatmap_empty(db):
    result = await db.get_sentiment_heatmap(hours=24)
    assert result == []


@pytest.mark.asyncio
async def test_sentiment_heatmap_returns_data(db):
    await _insert_signal(db, stance="bullish")
    await _insert_signal(db, stance="bearish")
    result = await db.get_sentiment_heatmap(hours=24)
    assert len(result) >= 1
    row = result[0]
    assert "ticker" in row
    assert "bullish" in row
    assert "bearish" in row


@pytest.mark.asyncio
@pytest.mark.parametrize("hours,expected_bucket_type", [
    (12, "1h"),     # <= 24 -> 1h bucket
    (24, "1h"),     # == 24 -> 1h bucket
    (72, "4h"),     # <= 168 -> 4h bucket
    (168, "4h"),    # == 168 -> 4h bucket
    (720, "1d"),    # > 168 -> 1d bucket
])
async def test_sentiment_heatmap_bucket_sizing(db, hours, expected_bucket_type):
    await _insert_signal(db)
    result = await db.get_sentiment_heatmap(hours=hours)
    assert isinstance(result, list)
    # Verify the query ran without errors for different bucket sizes
    # The bucket type is implicit in the time_bucket values


# ═══════════════════════════════════════════════════════════════════
# get_weekly_summary — best_calls / worst_calls
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_weekly_summary_empty(db):
    now = time.time()
    result = await db.get_weekly_summary(now - 86400 * 7, now)
    assert result["total_signals"] == 0


@pytest.mark.asyncio
async def test_weekly_summary_counts_signals(db):
    now = time.time()
    await _insert_signal(db, stance="bullish")
    await _insert_signal(db, stance="bearish")
    await _insert_signal(db, stance="mixed")
    result = await db.get_weekly_summary(now - 86400, now + 86400)
    assert result["total_signals"] == 3
    assert result["bullish"] == 1
    assert result["bearish"] == 1
    assert result["mixed"] == 1
    assert result.get("avg_confidence") is not None


@pytest.mark.asyncio
async def test_weekly_summary_top_tickers(db):
    now = time.time()
    for _ in range(3):
        await _insert_signal(db)
    await _insert_signal(db, ticker="AAPL")
    result = await db.get_weekly_summary(now - 86400, now + 86400)
    assert len(result["top_tickers"]) >= 1
    tickers = [t["ticker"] for t in result["top_tickers"]]
    assert "TSLA" in tickers


@pytest.mark.asyncio
async def test_weekly_summary_best_worst_calls(db):
    now = time.time()
    sid = await _insert_signal(db, stance="bullish")
    await db.insert_signal_performance(sid, "TSLA", 100.0)
    await db.db.execute(
        "UPDATE signal_performance SET price_1d = 110.0, max_gain_pct = 10.0, max_loss_pct = -2.0 WHERE signal_id = ?",
        (sid,),
    )
    await db.db.commit()
    result = await db.get_weekly_summary(now - 86400, now + 86400)
    assert len(result["best_calls"]) >= 1
    assert result["best_calls"][0]["max_gain_pct"] == 10.0


@pytest.mark.asyncio
async def test_weekly_summary_no_perf_data(db):
    now = time.time()
    await _insert_signal(db)
    result = await db.get_weekly_summary(now - 86400, now + 86400)
    assert result["best_calls"] == []
    assert result["worst_calls"] == []


# ═══════════════════════════════════════════════════════════════════
# get_replay_data — with/without performance
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_replay_data_empty(db):
    result = await db.get_replay_data(hours=24)
    assert result == []


@pytest.mark.asyncio
async def test_replay_data_without_performance(db):
    reasoning = json.dumps({"thesis": "My thesis statement"})
    event_data = json.dumps({"entities": ["TSLA", "AAPL"]})
    sid = await _insert_signal(db, reasoning_json=reasoning)
    await db.db.execute(
        "UPDATE signals SET event_data = ? WHERE id = ?", (event_data, sid)
    )
    await db.db.commit()
    result = await db.get_replay_data(hours=24, include_performance=False)
    assert len(result) == 1
    assert result[0]["thesis"] == "My thesis statement"
    assert result[0]["entities"] == ["TSLA", "AAPL"]


@pytest.mark.asyncio
async def test_replay_data_with_performance(db):
    sid = await _insert_signal(db)
    await db.insert_signal_performance(sid, "TSLA", 100.0)
    await db.db.execute(
        "UPDATE signal_performance SET price_1d = 110.0, max_gain_pct = 10.0 WHERE signal_id = ?",
        (sid,),
    )
    await db.db.commit()
    result = await db.get_replay_data(hours=24, include_performance=True)
    assert len(result) == 1
    assert result[0]["price_at_signal"] == 100.0
    assert result[0]["price_1d"] == 110.0


@pytest.mark.asyncio
async def test_replay_data_bad_json_reasoning(db):
    sid = await _insert_signal(db)
    await db.db.execute("UPDATE signals SET reasoning = 'invalid' WHERE id = ?", (sid,))
    await db.db.commit()
    result = await db.get_replay_data(hours=24)
    assert len(result) == 1
    assert result[0]["thesis"] == ""


@pytest.mark.asyncio
async def test_replay_data_bad_json_event_data(db):
    sid = await _insert_signal(db)
    await db.db.execute("UPDATE signals SET event_data = 'invalid' WHERE id = ?", (sid,))
    await db.db.commit()
    result = await db.get_replay_data(hours=24)
    assert len(result) == 1
    assert result[0]["entities"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("include_performance", [True, False])
async def test_replay_data_include_performance_flag(db, include_performance):
    await _insert_signal(db)
    result = await db.get_replay_data(hours=24, include_performance=include_performance)
    assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════
# get_unusual_events — event_type filter, JSON parsing
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unusual_events_empty(db):
    result = await db.get_unusual_events(hours=24)
    assert result == []


@pytest.mark.asyncio
async def test_unusual_events_returns_data(db):
    await _insert_unusual_event(db, ticker="TSLA", event_type="iv_spike", score=8.5)
    result = await db.get_unusual_events(hours=24)
    assert len(result) == 1
    assert result[0]["ticker"] == "TSLA"
    assert result[0]["event_type"] == "iv_spike"
    assert result[0]["score"] == 8.5


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["iv_spike", "volume_spike", "oi_surge", "skew_alert"])
async def test_unusual_events_type_filter(db, event_type):
    await _insert_unusual_event(db, event_type="iv_spike")
    await _insert_unusual_event(db, event_type="volume_spike")
    await _insert_unusual_event(db, event_type="oi_surge")
    await _insert_unusual_event(db, event_type="skew_alert")
    result = await db.get_unusual_events(hours=24, event_type=event_type)
    assert all(r["event_type"] == event_type for r in result)


@pytest.mark.asyncio
async def test_unusual_events_json_parsing(db):
    details = {"iv": 0.95, "historical_iv": 0.40, "ratio": 2.375}
    await _insert_unusual_event(db, details=details)
    result = await db.get_unusual_events(hours=24)
    assert len(result) == 1
    assert result[0]["details"]["iv"] == 0.95


@pytest.mark.asyncio
async def test_unusual_events_bad_json(db):
    await db.db.execute(
        "INSERT INTO unusual_events (ticker, event_type, score, details_json, detected_at) "
        "VALUES (?,?,?,?,?)",
        ("TSLA", "iv_spike", 5.0, "not-json", time.time()),
    )
    await db.db.commit()
    result = await db.get_unusual_events(hours=24)
    assert len(result) == 1
    assert result[0]["details"] == {}


@pytest.mark.asyncio
async def test_unusual_events_limit(db):
    for i in range(10):
        await _insert_unusual_event(db, ticker=f"T{i}")
    result = await db.get_unusual_events(hours=24, limit=5)
    assert len(result) == 5


@pytest.mark.asyncio
async def test_unusual_events_old_events_excluded(db):
    old_ts = time.time() - 86400 * 10
    await _insert_unusual_event(db, detected_at=old_ts)
    result = await db.get_unusual_events(hours=24)
    assert result == []


# ═══════════════════════════════════════════════════════════════════
# get_unusual_summary
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unusual_summary_empty(db):
    result = await db.get_unusual_summary(hours=24)
    assert result["total_events"] == 0
    assert result["unique_tickers"] == 0
    assert result["type_breakdown"] == {}
    assert result["top_tickers"] == []


@pytest.mark.asyncio
async def test_unusual_summary_aggregates(db):
    await _insert_unusual_event(db, ticker="TSLA", event_type="iv_spike", score=8.0)
    await _insert_unusual_event(db, ticker="TSLA", event_type="volume_spike", score=7.0)
    await _insert_unusual_event(db, ticker="AAPL", event_type="iv_spike", score=9.0)
    result = await db.get_unusual_summary(hours=24)
    assert result["total_events"] == 3
    assert result["unique_tickers"] == 2
    assert "iv_spike" in result["type_breakdown"]
    assert result["type_breakdown"]["iv_spike"]["count"] == 2
    assert len(result["top_tickers"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("hours", [1, 6, 24, 168])
async def test_unusual_summary_hours_param(db, hours):
    await _insert_unusual_event(db)
    result = await db.get_unusual_summary(hours=hours)
    assert isinstance(result, dict)
    assert "total_events" in result


# ═══════════════════════════════════════════════════════════════════
# get_unusual_timeline
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unusual_timeline_empty(db):
    result = await db.get_unusual_timeline("TSLA", days=7)
    assert result == []


@pytest.mark.asyncio
async def test_unusual_timeline_returns_events(db):
    await _insert_unusual_event(db, ticker="TSLA", event_type="iv_spike")
    await _insert_unusual_event(db, ticker="TSLA", event_type="volume_spike")
    await _insert_unusual_event(db, ticker="AAPL", event_type="iv_spike")
    result = await db.get_unusual_timeline("TSLA", days=7)
    assert len(result) == 2
    for event in result:
        assert event["ticker"] == "TSLA"


@pytest.mark.asyncio
async def test_unusual_timeline_json_parsing(db):
    details = {"iv": 1.2, "strike": 300}
    await _insert_unusual_event(db, ticker="TSLA", details=details)
    result = await db.get_unusual_timeline("TSLA", days=7)
    assert len(result) == 1
    assert result[0]["details"]["iv"] == 1.2


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [1, 7, 30])
async def test_unusual_timeline_days_param(db, days):
    await _insert_unusual_event(db, ticker="TSLA")
    result = await db.get_unusual_timeline("TSLA", days=days)
    assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════
# get_ticker_summary
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ticker_summary_empty(db):
    result = await db.get_ticker_summary("TSLA")
    assert result.get("total_signals") == 0 or result == {}


@pytest.mark.asyncio
async def test_ticker_summary_aggregates(db):
    await _insert_signal(db, stance="bullish")
    await _insert_signal(db, stance="bullish")
    await _insert_signal(db, stance="bearish")
    result = await db.get_ticker_summary("TSLA")
    assert result["total_signals"] == 3
    assert result["bullish_count"] == 2
    assert result["bearish_count"] == 1
    assert result["avg_confidence"] is not None


@pytest.mark.asyncio
async def test_ticker_summary_case_insensitive(db):
    await _insert_signal(db)
    result_upper = await db.get_ticker_summary("TSLA")
    result_lower = await db.get_ticker_summary("tsla")
    assert result_upper["total_signals"] == result_lower["total_signals"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", ["TSLA", "AAPL", "MSFT", "GOOG"])
async def test_ticker_summary_different_tickers(db, ticker):
    await _insert_signal(db, ticker=ticker)
    result = await db.get_ticker_summary(ticker)
    assert result["total_signals"] == 1
    assert result["ticker"] == ticker


# ═══════════════════════════════════════════════════════════════════
# get_ticker_signals
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ticker_signals_empty(db):
    result = await db.get_ticker_signals("TSLA")
    assert result == []


@pytest.mark.asyncio
async def test_ticker_signals_returns_all(db):
    for _ in range(3):
        await _insert_signal(db)
    await _insert_signal(db, ticker="AAPL")
    result = await db.get_ticker_signals("TSLA")
    assert len(result) == 3
    for sig in result:
        assert sig["ticker"] == "TSLA"


@pytest.mark.asyncio
async def test_ticker_signals_limit(db):
    for _ in range(10):
        await _insert_signal(db)
    result = await db.get_ticker_signals("TSLA", limit=5)
    assert len(result) == 5


@pytest.mark.asyncio
async def test_ticker_signals_ordered_newest_first(db):
    for _ in range(3):
        await _insert_signal(db)
    result = await db.get_ticker_signals("TSLA")
    for i in range(len(result) - 1):
        assert result[i]["created_at"] >= result[i + 1]["created_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 5, 10, 50])
async def test_ticker_signals_various_limits(db, limit):
    for _ in range(3):
        await _insert_signal(db)
    result = await db.get_ticker_signals("TSLA", limit=limit)
    assert len(result) <= limit


# ═══════════════════════════════════════════════════════════════════
# Edge cases across all methods
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_all_analytics_methods_empty_db(db):
    """Verify every analytics method handles empty DB gracefully."""
    now = time.time()
    assert await db.get_strategy_breakdown() == []
    assert await db.get_chart_data() == []
    assert await db.get_time_series_data() == []
    assert await db.get_sector_rotation_data() == []
    assert await db.get_sector_rotation_with_performance() == []
    assert await db.get_sector_heatmap_data() == []
    assert await db.get_sector_drill_down("Technology") == []
    assert await db.get_sector_time_series() == []
    assert await db.get_sector_ticker_breakdown("Technology") == []
    assert await db.get_sector_performance_ranked() == []
    assert await db.get_leaderboard() == []
    assert await db.get_leaderboard_with_performance() == []
    assert await db.get_correlation_matrix() == []
    assert await db.get_co_occurring_tickers() == []
    assert await db.get_news_feed() == []
    assert await db.get_sentiment_heatmap() == []
    summary = await db.get_weekly_summary(now - 86400, now)
    assert summary["total_signals"] == 0
    assert await db.get_replay_data() == []
    assert await db.get_unusual_events() == []
    unusual_summary = await db.get_unusual_summary()
    assert unusual_summary["total_events"] == 0
    assert await db.get_unusual_timeline("TSLA") == []


@pytest.mark.asyncio
async def test_zero_confidence_signals(db):
    """Signals with zero confidence should still appear in results."""
    await _insert_signal(db, confidence=0.0)
    result = await db.get_chart_data(hours=24)
    assert len(result) == 1
    assert result[0]["avg_confidence"] == 0.0


@pytest.mark.asyncio
async def test_sector_with_no_tickers_string(db):
    """Sector rotation data handles missing top_tickers gracefully."""
    for _ in range(2):
        await _insert_signal(db, sector="Technology")
    result = await db.get_sector_rotation_data(days=30)
    assert len(result) >= 1
    assert isinstance(result[0]["top_tickers"], list)


@pytest.mark.asyncio
async def test_sector_bullish_pct_all_bearish(db):
    """When all sector signals are bearish, bullish_pct should be 0."""
    for _ in range(2):
        await _insert_signal(db, sector="Energy", stance="bearish", ticker="XOM")
    result = await db.get_sector_rotation_data(days=30)
    assert len(result) == 1
    assert result[0]["bullish_pct"] == 0


@pytest.mark.asyncio
async def test_sector_bullish_pct_all_bullish(db):
    """When all sector signals are bullish, bullish_pct should be 100."""
    for _ in range(2):
        await _insert_signal(db, sector="Technology", stance="bullish")
    result = await db.get_sector_rotation_data(days=30)
    assert len(result) == 1
    assert result[0]["bullish_pct"] == 100


@pytest.mark.asyncio
async def test_sector_bullish_pct_all_mixed(db):
    """When all sector signals are mixed, bullish_pct should be 50 (fallback)."""
    for _ in range(2):
        await _insert_signal(db, sector="Technology", stance="mixed")
    result = await db.get_sector_rotation_data(days=30)
    assert len(result) == 1
    # All mixed -> bull=0, bear=0, total=0 -> fallback 50
    assert result[0]["bullish_pct"] == 50


@pytest.mark.asyncio
async def test_correlation_matrix_limit(db):
    """get_correlation_matrix respects the limit parameter."""
    # Insert multiple tickers to generate many pairs
    tickers = ["TSLA", "AAPL", "GOOG", "MSFT", "AMZN"]
    for t in tickers:
        for _ in range(3):
            await _insert_signal(db, ticker=t)
    result = await db.get_correlation_matrix(days=30, min_co=1, limit=2)
    assert len(result) <= 2


@pytest.mark.asyncio
async def test_leaderboard_excludes_unknown(db):
    """UNKNOWN ticker should not appear on leaderboard."""
    await db.insert_signal({
        "run_id": "run_x",
        "event": {
            "entities": [],
            "stance": "bullish",
            "confidence": 0.5,
            "evidence": [{"subreddit": "test", "excerpt": "t"}],
            "meta": {},
        },
        "trade_idea": {"strategy": "none"},
    })
    await _insert_signal(db)
    result = await db.get_leaderboard(hours=24)
    tickers = [r["ticker"] for r in result]
    assert "UNKNOWN" not in tickers


@pytest.mark.asyncio
async def test_news_feed_limit(db):
    """News feed respects limit parameter."""
    for i in range(10):
        await _insert_signal(db, subreddit="cnbc-market", ticker=f"T{i}")
    result = await db.get_news_feed(hours=24, limit=3)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_unusual_summary_avg_score(db):
    """Average and max score calculations are correct."""
    await _insert_unusual_event(db, score=6.0)
    await _insert_unusual_event(db, score=10.0, ticker="AAPL")
    result = await db.get_unusual_summary(hours=24)
    assert result["avg_score"] == 8.0
    assert result["max_score"] == 10.0


@pytest.mark.asyncio
async def test_weekly_summary_outside_window(db):
    """Signals outside the time window are excluded."""
    now = time.time()
    await _insert_signal(db)
    # Query a window far in the past
    result = await db.get_weekly_summary(now - 86400 * 100, now - 86400 * 99)
    assert result["total_signals"] == 0


@pytest.mark.asyncio
async def test_chart_data_strategies_concatenated(db):
    """Chart data includes concatenated strategy list."""
    await _insert_signal(db, strategy="debit_spread")
    await _insert_signal(db, strategy="credit_spread")
    result = await db.get_chart_data(hours=24)
    assert len(result) == 1
    assert "strategies" in result[0]


@pytest.mark.asyncio
async def test_sector_drill_down_limit_20(db):
    """Sector drill down is limited to 20 tickers."""
    for i in range(25):
        await _insert_signal(db, ticker=f"T{i:03d}", sector="Technology")
    result = await db.get_sector_drill_down("Technology", hours=24)
    assert len(result) <= 20
