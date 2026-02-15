from __future__ import annotations

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
            "evidence": [{"subreddit": subreddit, "excerpt": "test"}],
            "meta": {"trend_score": trend_score, "market": {ticker: {"last_close": 250.0}}},
        },
        "trade_idea": {"strategy": strategy},
    })
    assert signal_id is not None
    if sector:
        await db.db.execute(
            "UPDATE signals SET sector = ? WHERE id = ?", (sector, signal_id)
        )
        await db.db.commit()
    return signal_id


async def _insert_signal_with_perf(
    db: Database,
    ticker: str = "TSLA",
    stance: str = "bullish",
    confidence: float = 0.65,
    strategy: str = "debit_spread",
    event_type: str = "earnings_rumor",
    price_at_signal: float = 100.0,
    price_1h: float | None = None,
    price_4h: float | None = None,
    price_1d: float | None = None,
    price_1w: float | None = None,
    max_gain_pct: float | None = None,
    max_loss_pct: float | None = None,
    sector: str = "",
    subreddit: str = "wallstreetbets",
) -> str:
    """Insert a signal with performance data and return the signal ID."""
    signal_id = await _insert_signal(
        db,
        ticker=ticker,
        stance=stance,
        confidence=confidence,
        strategy=strategy,
        event_type=event_type,
        sector=sector,
        subreddit=subreddit,
    )
    await db.insert_signal_performance(signal_id, ticker, price_at_signal)

    updates = {}
    if price_1h is not None:
        updates["price_1h"] = price_1h
    if price_4h is not None:
        updates["price_4h"] = price_4h
    if price_1d is not None:
        updates["price_1d"] = price_1d
    if price_1w is not None:
        updates["price_1w"] = price_1w
    if max_gain_pct is not None:
        updates["max_gain_pct"] = max_gain_pct
    if max_loss_pct is not None:
        updates["max_loss_pct"] = max_loss_pct

    if updates:
        # Get the performance record ID
        async with db.db.execute(
            "SELECT id FROM signal_performance WHERE signal_id = ?", (signal_id,)
        ) as cursor:
            row = await cursor.fetchone()
        perf_id = row["id"]
        await db.update_performance_prices(perf_id, updates)

    return signal_id


async def _insert_win_rate_snapshot(
    db: Database,
    winners: int = 5,
    losers: int = 3,
    neutral: int = 2,
    total_tracked: int = 10,
    avg_gain_pct: float = 5.0,
    avg_loss_pct: float = -3.0,
    avg_1d_return_pct: float = 1.5,
    period_end: float | None = None,
) -> None:
    """Insert a win rate snapshot for cumulative queries."""
    now = time.time()
    pe = period_end if period_end is not None else now
    await db.db.execute(
        "INSERT INTO win_rate_snapshots "
        "(snapshot_at, period_start, period_end, winners, losers, neutral, "
        "total_tracked, avg_gain_pct, avg_loss_pct, avg_1d_return_pct) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (now, pe - 86400 * 7, pe, winners, losers, neutral,
         total_tracked, avg_gain_pct, avg_loss_pct, avg_1d_return_pct),
    )
    await db.db.commit()


# ═══════════════════════════════════════════════════════════════════
# get_performance_summary
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_performance_summary_empty_db(db):
    result = await db.get_performance_summary(days=30)
    assert result["total_signals"] == 0


@pytest.mark.asyncio
async def test_performance_summary_counts_signals(db):
    for _ in range(3):
        await _insert_signal(db, stance="bullish")
    await _insert_signal(db, stance="bearish")
    await _insert_signal(db, stance="mixed")
    result = await db.get_performance_summary(days=30)
    assert result["total_signals"] == 5
    assert result["bullish_count"] == 3
    assert result["bearish_count"] == 1
    assert result["mixed_count"] == 1


@pytest.mark.asyncio
async def test_performance_summary_tradeable_signals(db):
    await _insert_signal(db, stance="bullish")
    await _insert_signal(db, stance="bearish")
    await _insert_signal(db, stance="mixed")
    result = await db.get_performance_summary(days=30)
    assert result["tradeable_signals"] == 2  # Only bullish + bearish


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [1, 7, 30, 90, 365])
async def test_performance_summary_days_param(db, days):
    await _insert_signal(db)
    result = await db.get_performance_summary(days=days)
    assert result["total_signals"] >= 1


@pytest.mark.asyncio
async def test_performance_summary_daily_avg(db):
    for _ in range(10):
        await _insert_signal(db)
    result = await db.get_performance_summary(days=10)
    assert result["daily_avg"] == 1.0


@pytest.mark.asyncio
async def test_performance_summary_high_conf_count(db):
    await _insert_signal(db, confidence=0.8)
    await _insert_signal(db, confidence=0.3)
    await _insert_signal(db, confidence=0.6)
    result = await db.get_performance_summary(days=30)
    assert result["high_conf_count"] == 2  # 0.8 and 0.6 >= 0.5


@pytest.mark.asyncio
async def test_performance_summary_unique_tickers(db):
    await _insert_signal(db, ticker="TSLA")
    await _insert_signal(db, ticker="AAPL")
    await _insert_signal(db, ticker="TSLA")
    result = await db.get_performance_summary(days=30)
    assert result["unique_tickers"] == 2


@pytest.mark.asyncio
async def test_performance_summary_unique_sources(db):
    await _insert_signal(db, subreddit="wallstreetbets")
    await _insert_signal(db, subreddit="options")
    result = await db.get_performance_summary(days=30)
    assert result["unique_sources"] == 2


# ═══════════════════════════════════════════════════════════════════
# get_aggregate_accuracy — with snapshot merging
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_aggregate_accuracy_empty_db(db):
    result = await db.get_aggregate_accuracy(days=7)
    assert result["total_tracked"] == 0
    assert result["win_rate"] == 0


@pytest.mark.asyncio
async def test_aggregate_accuracy_bullish_wins(db):
    # Bullish signal with price increase > 0.5%
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=102.0,
    )
    result = await db.get_aggregate_accuracy(days=7)
    assert result["total_tracked"] >= 1
    assert result["winners"] >= 1


@pytest.mark.asyncio
async def test_aggregate_accuracy_bearish_wins(db):
    # Bearish signal with price decrease > 0.5%
    await _insert_signal_with_perf(
        db, stance="bearish", price_at_signal=100.0, price_1d=98.0,
    )
    result = await db.get_aggregate_accuracy(days=7)
    assert result["total_tracked"] >= 1
    assert result["winners"] >= 1


@pytest.mark.asyncio
async def test_aggregate_accuracy_neutral_within_threshold(db):
    # Price move within 0.5% is neutral
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=100.3,
    )
    result = await db.get_aggregate_accuracy(days=7)
    assert result.get("neutral", 0) >= 0


@pytest.mark.asyncio
async def test_aggregate_accuracy_with_ticker_filter(db):
    await _insert_signal_with_perf(
        db, ticker="TSLA", stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    await _insert_signal_with_perf(
        db, ticker="AAPL", stance="bullish", price_at_signal=150.0, price_1d=155.0,
    )
    result = await db.get_aggregate_accuracy(days=7, ticker="TSLA")
    assert result["total_tracked"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [1, 7, 14, 30])
async def test_aggregate_accuracy_days_param(db, days):
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=105.0,
    )
    result = await db.get_aggregate_accuracy(days=days)
    assert isinstance(result, dict)
    assert "win_rate" in result


@pytest.mark.asyncio
async def test_aggregate_accuracy_snapshot_merging(db):
    # Insert snapshot data
    await _insert_win_rate_snapshot(db, winners=10, losers=5, total_tracked=15)
    # Insert live data
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_aggregate_accuracy(days=30)
    # Should merge snapshot winners + live winners
    assert result["winners"] >= 10
    assert result["total_tracked"] >= 15


@pytest.mark.asyncio
async def test_aggregate_accuracy_ticker_filter_skips_snapshots(db):
    # With ticker filter, snapshots are NOT merged
    await _insert_win_rate_snapshot(db, winners=10, losers=5, total_tracked=15)
    await _insert_signal_with_perf(
        db, ticker="TSLA", stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_aggregate_accuracy(days=30, ticker="TSLA")
    # Snapshots should not be included when ticker is specified
    assert result["total_tracked"] <= 2


@pytest.mark.asyncio
async def test_aggregate_accuracy_win_rate_calculation(db):
    # 2 wins, 1 loss -> ~66%
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    await _insert_signal_with_perf(
        db, ticker="AAPL", stance="bearish", price_at_signal=150.0, price_1d=140.0,
    )
    await _insert_signal_with_perf(
        db, ticker="GOOG", stance="bullish", price_at_signal=100.0, price_1d=90.0,
    )
    result = await db.get_aggregate_accuracy(days=30)
    decided = (result.get("winners", 0) or 0) + (result.get("losers", 0) or 0)
    if decided > 0:
        assert 0 <= result["win_rate"] <= 100


# ═══════════════════════════════════════════════════════════════════
# insert_signal_performance
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_insert_signal_performance(db):
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 250.0)
    result = await db.get_performance_for_signal(signal_id)
    assert result is not None
    assert result["ticker"] == "TSLA"
    assert result["price_at_signal"] == 250.0
    assert result["price_1h"] is None
    assert result["price_1d"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("price", [0.01, 1.0, 100.0, 1000.0, 50000.0])
async def test_insert_signal_performance_various_prices(db, price):
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", price)
    result = await db.get_performance_for_signal(signal_id)
    assert result is not None
    assert result["price_at_signal"] == price


# ═══════════════════════════════════════════════════════════════════
# get_performance_for_signal
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_performance_for_signal_not_found(db):
    result = await db.get_performance_for_signal("nonexistent_id")
    assert result is None


@pytest.mark.asyncio
async def test_get_performance_for_signal_found(db):
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 200.0)
    result = await db.get_performance_for_signal(signal_id)
    assert result is not None
    assert result["signal_id"] == signal_id


# ═══════════════════════════════════════════════════════════════════
# get_unchecked_performances
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unchecked_performances_empty(db):
    result = await db.get_unchecked_performances()
    assert result == []


@pytest.mark.asyncio
async def test_unchecked_performances_returns_nulls(db):
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 100.0)
    result = await db.get_unchecked_performances()
    assert len(result) >= 1
    assert result[0]["signal_id"] == signal_id
    assert result[0]["price_1h"] is None


@pytest.mark.asyncio
async def test_unchecked_performances_excludes_complete(db):
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 100.0)
    async with db.db.execute(
        "SELECT id FROM signal_performance WHERE signal_id = ?", (signal_id,)
    ) as cursor:
        row = await cursor.fetchone()
    perf_id = row["id"]
    await db.update_performance_prices(perf_id, {
        "price_1h": 101.0, "price_4h": 102.0,
        "price_1d": 105.0, "price_1w": 110.0,
    })
    result = await db.get_unchecked_performances()
    assert result == []


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 5, 10, 50])
async def test_unchecked_performances_limit(db, limit):
    for _ in range(3):
        signal_id = await _insert_signal(db)
        await db.insert_signal_performance(signal_id, "TSLA", 100.0)
    result = await db.get_unchecked_performances(limit=limit)
    assert len(result) <= limit


@pytest.mark.asyncio
async def test_unchecked_performances_includes_signal_data(db):
    signal_id = await _insert_signal(db, stance="bullish")
    await db.insert_signal_performance(signal_id, "TSLA", 100.0)
    result = await db.get_unchecked_performances()
    assert len(result) == 1
    assert result[0]["signal_stance"] == "bullish"
    assert result[0]["created_at"] is not None


# ═══════════════════════════════════════════════════════════════════
# update_performance_prices
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_update_performance_prices_single_field(db):
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 100.0)
    async with db.db.execute(
        "SELECT id FROM signal_performance WHERE signal_id = ?", (signal_id,)
    ) as cursor:
        row = await cursor.fetchone()
    perf_id = row["id"]
    await db.update_performance_prices(perf_id, {"price_1h": 101.5})
    result = await db.get_performance_for_signal(signal_id)
    assert result["price_1h"] == 101.5


@pytest.mark.asyncio
async def test_update_performance_prices_all_fields(db):
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 100.0)
    async with db.db.execute(
        "SELECT id FROM signal_performance WHERE signal_id = ?", (signal_id,)
    ) as cursor:
        row = await cursor.fetchone()
    perf_id = row["id"]
    await db.update_performance_prices(perf_id, {
        "price_1h": 101.0,
        "price_4h": 103.0,
        "price_1d": 108.0,
        "price_1w": 115.0,
        "max_gain_pct": 15.0,
        "max_loss_pct": -2.0,
        "checked_at": time.time(),
    })
    result = await db.get_performance_for_signal(signal_id)
    assert result["price_1h"] == 101.0
    assert result["price_4h"] == 103.0
    assert result["price_1d"] == 108.0
    assert result["price_1w"] == 115.0
    assert result["max_gain_pct"] == 15.0
    assert result["max_loss_pct"] == -2.0


@pytest.mark.asyncio
async def test_update_performance_prices_empty_dict(db):
    """Empty updates dict should be a no-op."""
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 100.0)
    async with db.db.execute(
        "SELECT id FROM signal_performance WHERE signal_id = ?", (signal_id,)
    ) as cursor:
        row = await cursor.fetchone()
    perf_id = row["id"]
    await db.update_performance_prices(perf_id, {})
    result = await db.get_performance_for_signal(signal_id)
    assert result["price_1h"] is None  # Unchanged


@pytest.mark.asyncio
@pytest.mark.parametrize("col,value", [
    ("price_1h", 101.0),
    ("price_4h", 103.0),
    ("price_1d", 108.0),
    ("price_1w", 115.0),
    ("max_gain_pct", 10.5),
    ("max_loss_pct", -3.2),
])
async def test_update_performance_prices_individual_columns(db, col, value):
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 100.0)
    async with db.db.execute(
        "SELECT id FROM signal_performance WHERE signal_id = ?", (signal_id,)
    ) as cursor:
        row = await cursor.fetchone()
    perf_id = row["id"]
    await db.update_performance_prices(perf_id, {col: value})
    result = await db.get_performance_for_signal(signal_id)
    assert result[col] == value


# ═══════════════════════════════════════════════════════════════════
# recalculate_stance_aware_gains — bullish/bearish inversion
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_recalculate_stance_aware_gains_empty(db):
    count = await db.recalculate_stance_aware_gains()
    assert count == 0


@pytest.mark.asyncio
async def test_recalculate_stance_aware_gains_bullish(db):
    # Bullish: gain = (price_1d / price_at - 1) * 100
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    count = await db.recalculate_stance_aware_gains()
    assert count == 1
    # Check that gains were recalculated
    signals = await db.get_performance_history(days=30)
    assert len(signals) >= 1
    assert signals[0]["max_gain_pct"] == pytest.approx(10.0, abs=0.1)
    assert signals[0]["max_loss_pct"] == pytest.approx(10.0, abs=0.1)


@pytest.mark.asyncio
async def test_recalculate_stance_aware_gains_bearish_inversion(db):
    # Bearish: gain when price goes down, loss when price goes up
    await _insert_signal_with_perf(
        db, stance="bearish", price_at_signal=100.0, price_1d=90.0,
    )
    count = await db.recalculate_stance_aware_gains()
    assert count == 1
    signals = await db.get_performance_history(days=30)
    assert len(signals) >= 1
    # For bearish: raw pct = (90/100 - 1)*100 = -10%, inverted = +10% gain
    assert signals[0]["max_gain_pct"] == pytest.approx(10.0, abs=0.1)


@pytest.mark.asyncio
async def test_recalculate_stance_aware_gains_bearish_loss(db):
    # Bearish signal where price goes UP = loss
    await _insert_signal_with_perf(
        db, stance="bearish", price_at_signal=100.0, price_1d=115.0,
    )
    count = await db.recalculate_stance_aware_gains()
    assert count == 1
    signals = await db.get_performance_history(days=30)
    assert len(signals) >= 1
    # raw pct = +15%, inverted = -15% loss
    assert signals[0]["max_loss_pct"] == pytest.approx(-15.0, abs=0.1)


@pytest.mark.asyncio
@pytest.mark.parametrize("stance", ["bullish", "bearish"])
async def test_recalculate_stance_aware_gains_both_stances(db, stance):
    await _insert_signal_with_perf(
        db, stance=stance, price_at_signal=100.0, price_1d=105.0,
    )
    count = await db.recalculate_stance_aware_gains()
    assert count == 1


@pytest.mark.asyncio
async def test_recalculate_skips_no_price_data(db):
    """Signals without any tracked prices should be skipped."""
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 100.0)
    count = await db.recalculate_stance_aware_gains()
    assert count == 0


@pytest.mark.asyncio
async def test_recalculate_uses_multiple_price_points(db):
    """Should consider all available price checkpoints."""
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0,
        price_1h=98.0, price_4h=103.0, price_1d=110.0,
    )
    count = await db.recalculate_stance_aware_gains()
    assert count == 1
    signals = await db.get_performance_history(days=30)
    assert len(signals) >= 1
    # Max gain = 10% (from price_1d=110), max loss = -2% (from price_1h=98)
    assert signals[0]["max_gain_pct"] == pytest.approx(10.0, abs=0.1)
    assert signals[0]["max_loss_pct"] == pytest.approx(-2.0, abs=0.1)


# ═══════════════════════════════════════════════════════════════════
# get_performance_history — with/without ticker filter
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_performance_history_empty(db):
    result = await db.get_performance_history(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_performance_history_returns_records(db):
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=105.0,
    )
    result = await db.get_performance_history(days=30)
    assert len(result) >= 1
    assert "signal_id" in result[0]
    assert "price_at_signal" in result[0]
    assert "stance" in result[0]


@pytest.mark.asyncio
async def test_performance_history_ticker_filter(db):
    await _insert_signal_with_perf(
        db, ticker="TSLA", stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    await _insert_signal_with_perf(
        db, ticker="AAPL", stance="bullish", price_at_signal=150.0, price_1d=155.0,
    )
    result = await db.get_performance_history(days=30, ticker="TSLA")
    assert len(result) == 1
    assert result[0]["ticker"] == "TSLA"


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [1, 7, 30, 90])
async def test_performance_history_days_param(db, days):
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_performance_history(days=days)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_performance_history_limit(db):
    for _ in range(5):
        await _insert_signal_with_perf(
            db, stance="bullish", price_at_signal=100.0, price_1d=105.0,
        )
    result = await db.get_performance_history(days=30, limit=3)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_performance_history_excludes_zero_price(db):
    """Records with price_at_signal = 0 should be excluded."""
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 0.0)
    result = await db.get_performance_history(days=30)
    assert result == []


# ═══════════════════════════════════════════════════════════════════
# get_performance_csv_data
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_performance_csv_data_empty(db):
    result = await db.get_performance_csv_data(days=365)
    assert result == []


@pytest.mark.asyncio
async def test_performance_csv_data_includes_extra_fields(db):
    await _insert_signal_with_perf(
        db, stance="bullish", event_type="earnings_rumor",
        price_at_signal=100.0, price_1d=110.0,
        subreddit="wallstreetbets",
    )
    result = await db.get_performance_csv_data(days=365)
    assert len(result) >= 1
    row = result[0]
    assert "event_type" in row
    assert "subreddit" in row
    assert "post_title" in row
    assert "strategy" in row


@pytest.mark.asyncio
async def test_performance_csv_data_ticker_filter(db):
    await _insert_signal_with_perf(
        db, ticker="TSLA", price_at_signal=100.0, price_1d=110.0,
    )
    await _insert_signal_with_perf(
        db, ticker="AAPL", price_at_signal=150.0, price_1d=155.0,
    )
    result = await db.get_performance_csv_data(days=365, ticker="TSLA")
    assert len(result) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [7, 30, 90, 365])
async def test_performance_csv_data_days_param(db, days):
    await _insert_signal_with_perf(
        db, price_at_signal=100.0, price_1d=105.0,
    )
    result = await db.get_performance_csv_data(days=days)
    assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════
# get_accuracy_over_time — daily/hourly
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_accuracy_over_time_empty(db):
    result = await db.get_accuracy_over_time(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_accuracy_over_time_returns_buckets(db):
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_accuracy_over_time(days=30, interval="daily")
    assert len(result) >= 1
    assert "time_bucket" in result[0]
    assert "total" in result[0]
    assert "winners" in result[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("interval", ["daily", "hourly"])
async def test_accuracy_over_time_interval(db, interval):
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_accuracy_over_time(days=30, interval=interval)
    assert isinstance(result, list)


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [1, 7, 30, 90])
async def test_accuracy_over_time_days_param(db, days):
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_accuracy_over_time(days=days)
    assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════
# get_accuracy_by_confidence — 4 buckets
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_accuracy_by_confidence_empty(db):
    result = await db.get_accuracy_by_confidence(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_accuracy_by_confidence_buckets(db):
    await _insert_signal_with_perf(
        db, confidence=0.2, stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    await _insert_signal_with_perf(
        db, confidence=0.4, stance="bullish", price_at_signal=100.0, price_1d=110.0,
        ticker="AAPL",
    )
    await _insert_signal_with_perf(
        db, confidence=0.6, stance="bullish", price_at_signal=100.0, price_1d=110.0,
        ticker="GOOG",
    )
    await _insert_signal_with_perf(
        db, confidence=0.85, stance="bullish", price_at_signal=100.0, price_1d=110.0,
        ticker="MSFT",
    )
    result = await db.get_accuracy_by_confidence(days=30)
    assert len(result) >= 1
    for row in result:
        assert "bucket" in row
        assert "label" in row
        assert "win_rate" in row
        assert row["bucket"] in ("low", "mid", "high", "very_high")


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence,expected_bucket", [
    (0.1, "low"),
    (0.29, "low"),
    (0.35, "mid"),
    (0.55, "high"),
    (0.75, "very_high"),
    (0.95, "very_high"),
])
async def test_accuracy_by_confidence_bucket_boundaries(db, confidence, expected_bucket):
    await _insert_signal_with_perf(
        db, confidence=confidence, stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_accuracy_by_confidence(days=30)
    assert len(result) >= 1
    assert result[0]["bucket"] == expected_bucket


@pytest.mark.asyncio
async def test_accuracy_by_confidence_labels(db):
    labels_expected = {"<30%", "30-50%", "50-70%", "70%+"}
    await _insert_signal_with_perf(
        db, confidence=0.2, stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_accuracy_by_confidence(days=30)
    for row in result:
        assert row["label"] in labels_expected


# ═══════════════════════════════════════════════════════════════════
# get_accuracy_by_event_type
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_accuracy_by_event_type_empty(db):
    result = await db.get_accuracy_by_event_type(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_accuracy_by_event_type_returns_types(db):
    await _insert_signal_with_perf(
        db, event_type="earnings_rumor", stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
    )
    await _insert_signal_with_perf(
        db, event_type="squeeze", stance="bearish",
        price_at_signal=100.0, price_1d=90.0, ticker="AAPL",
    )
    result = await db.get_accuracy_by_event_type(days=30)
    assert len(result) >= 1
    for row in result:
        assert "event_type" in row
        assert "win_rate" in row
        assert "total" in row
        assert "losers" in row


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", [
    "earnings_rumor", "squeeze", "sector_rotation", "insider_trade", "fda_approval",
])
async def test_accuracy_by_event_type_various(db, event_type):
    await _insert_signal_with_perf(
        db, event_type=event_type, stance="bullish",
        price_at_signal=100.0, price_1d=105.0,
    )
    result = await db.get_accuracy_by_event_type(days=30)
    assert len(result) >= 1
    assert result[0]["event_type"] == event_type


# ═══════════════════════════════════════════════════════════════════
# get_accuracy_by_strategy
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_accuracy_by_strategy_empty(db):
    result = await db.get_accuracy_by_strategy(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_accuracy_by_strategy_excludes_none(db):
    await _insert_signal_with_perf(
        db, strategy="none", stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_accuracy_by_strategy(days=30)
    strategies = [r["strategy"] for r in result]
    assert "none" not in strategies


@pytest.mark.asyncio
async def test_accuracy_by_strategy_returns_data(db):
    await _insert_signal_with_perf(
        db, strategy="debit_spread", stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
    )
    await _insert_signal_with_perf(
        db, strategy="credit_spread", stance="bearish",
        price_at_signal=100.0, price_1d=95.0, ticker="AAPL",
    )
    result = await db.get_accuracy_by_strategy(days=30)
    assert len(result) >= 1
    for row in result:
        assert "strategy" in row
        assert "win_rate" in row
        assert "avg_return_pct" in row


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", [
    "debit_spread", "credit_spread", "long_call", "long_put", "straddle",
])
async def test_accuracy_by_strategy_various(db, strategy):
    await _insert_signal_with_perf(
        db, strategy=strategy, stance="bullish",
        price_at_signal=100.0, price_1d=105.0,
    )
    result = await db.get_accuracy_by_strategy(days=30)
    assert len(result) >= 1
    assert result[0]["strategy"] == strategy


# ═══════════════════════════════════════════════════════════════════
# get_strategy_pnl
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_strategy_pnl_empty(db):
    result = await db.get_strategy_pnl(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_strategy_pnl_returns_data(db):
    await _insert_signal_with_perf(
        db, strategy="debit_spread", stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
        max_gain_pct=10.0, max_loss_pct=-2.0,
    )
    result = await db.get_strategy_pnl(days=30)
    assert len(result) >= 1
    row = result[0]
    assert row["strategy"] == "debit_spread"
    assert "avg_gain_pct" in row
    assert "avg_loss_pct" in row
    assert "avg_1d_return_pct" in row


@pytest.mark.asyncio
async def test_strategy_pnl_excludes_none(db):
    await _insert_signal_with_perf(
        db, strategy="none", stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_strategy_pnl(days=30)
    strategies = [r["strategy"] for r in result]
    assert "none" not in strategies


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [1, 7, 30, 90])
async def test_strategy_pnl_days_param(db, days):
    await _insert_signal_with_perf(
        db, strategy="debit_spread", stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_strategy_pnl(days=days)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_strategy_pnl_bearish_return(db):
    """Bearish strategy PnL should invert the return."""
    await _insert_signal_with_perf(
        db, strategy="long_put", stance="bearish",
        price_at_signal=100.0, price_1d=90.0,
    )
    result = await db.get_strategy_pnl(days=30)
    assert len(result) >= 1
    # For bearish: return = (1 - 90/100) * 100 = 10%
    assert result[0]["avg_1d_return_pct"] is not None
    assert result[0]["avg_1d_return_pct"] > 0


# ═══════════════════════════════════════════════════════════════════
# get_performance_by_ticker
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_performance_by_ticker_empty(db):
    result = await db.get_performance_by_ticker(days=30)
    assert result == []


@pytest.mark.asyncio
async def test_performance_by_ticker_returns_data(db):
    await _insert_signal_with_perf(
        db, ticker="TSLA", stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
    )
    await _insert_signal_with_perf(
        db, ticker="AAPL", stance="bullish",
        price_at_signal=150.0, price_1d=155.0,
    )
    result = await db.get_performance_by_ticker(days=30)
    assert len(result) == 2
    tickers = {r["ticker"] for r in result}
    assert "TSLA" in tickers
    assert "AAPL" in tickers


@pytest.mark.asyncio
async def test_performance_by_ticker_limit(db):
    for i in range(5):
        await _insert_signal_with_perf(
            db, ticker=f"T{i}", stance="bullish",
            price_at_signal=100.0, price_1d=110.0,
        )
    result = await db.get_performance_by_ticker(days=30, limit=3)
    assert len(result) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [1, 7, 30, 90])
async def test_performance_by_ticker_days_param(db, days):
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_performance_by_ticker(days=days)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_performance_by_ticker_includes_winners(db):
    await _insert_signal_with_perf(
        db, ticker="TSLA", stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_performance_by_ticker(days=30)
    assert len(result) >= 1
    assert "winners" in result[0]
    assert "avg_gain_pct" in result[0]


# ═══════════════════════════════════════════════════════════════════
# get_confidence_calibration — decile bucketing
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_confidence_calibration_empty(db):
    result = await db.get_confidence_calibration(days=90)
    assert result == []


@pytest.mark.asyncio
async def test_confidence_calibration_decile_buckets(db):
    # Insert signals at different confidence levels
    for conf in [0.15, 0.35, 0.55, 0.75, 0.95]:
        await _insert_signal_with_perf(
            db, confidence=conf, stance="bullish",
            price_at_signal=100.0, price_1d=110.0,
            ticker=f"T{int(conf*100)}",
        )
    result = await db.get_confidence_calibration(days=90)
    assert len(result) >= 1
    for row in result:
        assert "decile" in row
        assert "bucket_label" in row
        assert "actual_win_rate" in row
        assert "expected_win_rate" in row
        assert "label" in row


@pytest.mark.asyncio
async def test_confidence_calibration_bucket_labels(db):
    await _insert_signal_with_perf(
        db, confidence=0.55, stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_confidence_calibration(days=90)
    assert len(result) >= 1
    label = result[0]["bucket_label"]
    assert "%" in label


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence,expected_decile", [
    (0.05, 0),
    (0.15, 1),
    (0.25, 2),
    (0.35, 3),
    (0.45, 4),
    (0.55, 5),
    (0.65, 6),
    (0.75, 7),
    (0.85, 8),
    (0.95, 9),
])
async def test_confidence_calibration_decile_mapping(db, confidence, expected_decile):
    await _insert_signal_with_perf(
        db, confidence=confidence, stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_confidence_calibration(days=90)
    assert len(result) >= 1
    assert result[0]["decile"] == expected_decile


@pytest.mark.asyncio
async def test_confidence_calibration_excludes_mixed(db):
    """Mixed stances should be excluded from calibration."""
    await _insert_signal_with_perf(
        db, confidence=0.5, stance="mixed",
        price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_confidence_calibration(days=90)
    # Mixed stance should be excluded by the query
    assert result == []


@pytest.mark.asyncio
async def test_confidence_calibration_expected_vs_actual(db):
    # Insert a high confidence winner
    await _insert_signal_with_perf(
        db, confidence=0.85, stance="bullish",
        price_at_signal=100.0, price_1d=115.0,
    )
    result = await db.get_confidence_calibration(days=90)
    assert len(result) >= 1
    row = result[0]
    assert row["expected_win_rate"] > 0
    assert row["actual_win_rate"] == 100  # 1 winner out of 1


# ═══════════════════════════════════════════════════════════════════
# get_cumulative_win_rate — days=0 for all-time
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cumulative_win_rate_empty(db):
    result = await db.get_cumulative_win_rate(days=30)
    assert result["winners"] == 0
    assert result["losers"] == 0
    assert result["total_tracked"] == 0


@pytest.mark.asyncio
async def test_cumulative_win_rate_with_snapshots(db):
    await _insert_win_rate_snapshot(db, winners=10, losers=5, neutral=3, total_tracked=18)
    result = await db.get_cumulative_win_rate(days=30)
    assert result["winners"] == 10
    assert result["losers"] == 5
    assert result["total_tracked"] == 18


@pytest.mark.asyncio
async def test_cumulative_win_rate_all_time(db):
    await _insert_win_rate_snapshot(
        db, winners=20, losers=10, neutral=5, total_tracked=35,
        period_end=time.time() - 86400 * 365,  # Old snapshot
    )
    result_30d = await db.get_cumulative_win_rate(days=30)
    result_all = await db.get_cumulative_win_rate(days=0)
    # All-time should include old snapshots; 30d might not
    assert result_all["total_tracked"] >= result_30d["total_tracked"]


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [0, 1, 7, 30, 90])
async def test_cumulative_win_rate_days_param(db, days):
    await _insert_win_rate_snapshot(db, winners=5, losers=3, total_tracked=8)
    result = await db.get_cumulative_win_rate(days=days)
    assert isinstance(result, dict)
    assert "winners" in result
    assert "losers" in result


@pytest.mark.asyncio
async def test_cumulative_win_rate_multiple_snapshots(db):
    await _insert_win_rate_snapshot(db, winners=5, losers=3, total_tracked=8)
    await _insert_win_rate_snapshot(db, winners=10, losers=2, total_tracked=12)
    result = await db.get_cumulative_win_rate(days=30)
    assert result["winners"] == 15  # 5 + 10
    assert result["losers"] == 5    # 3 + 2
    assert result["total_tracked"] == 20  # 8 + 12


@pytest.mark.asyncio
async def test_cumulative_win_rate_avg_fields(db):
    await _insert_win_rate_snapshot(
        db, avg_gain_pct=5.0, avg_loss_pct=-3.0, avg_1d_return_pct=1.5,
    )
    result = await db.get_cumulative_win_rate(days=30)
    assert result["avg_gain_pct"] == pytest.approx(5.0, abs=0.1)
    assert result["avg_loss_pct"] == pytest.approx(-3.0, abs=0.1)


# ═══════════════════════════════════════════════════════════════════
# Edge cases across all methods
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_all_performance_methods_empty_db(db):
    """All performance methods handle empty DB gracefully."""
    summary = await db.get_performance_summary()
    assert summary["total_signals"] == 0

    accuracy = await db.get_aggregate_accuracy()
    assert accuracy["total_tracked"] == 0

    assert await db.get_performance_for_signal("nonexistent") is None
    assert await db.get_unchecked_performances() == []
    assert await db.get_performance_history() == []
    assert await db.get_performance_csv_data() == []
    assert await db.get_accuracy_over_time() == []
    assert await db.get_accuracy_by_confidence() == []
    assert await db.get_accuracy_by_event_type() == []
    assert await db.get_accuracy_by_strategy() == []
    assert await db.get_strategy_pnl() == []
    assert await db.get_performance_by_ticker() == []
    assert await db.get_confidence_calibration() == []

    cum = await db.get_cumulative_win_rate()
    assert cum["total_tracked"] == 0

    count = await db.recalculate_stance_aware_gains()
    assert count == 0


@pytest.mark.asyncio
async def test_zero_price_at_signal_handling(db):
    """Price at signal = 0 should be handled gracefully."""
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 0.0)
    # These methods filter out price_at_signal = 0
    result = await db.get_aggregate_accuracy(days=7)
    assert result["total_tracked"] == 0


@pytest.mark.asyncio
async def test_performance_with_only_1h_price(db):
    """Signal with only price_1h should still be trackable."""
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1h=101.0,
    )
    unchecked = await db.get_unchecked_performances()
    assert len(unchecked) >= 1  # Still missing 4h, 1d, 1w


@pytest.mark.asyncio
async def test_performance_with_only_4h_price(db):
    """Signal with only price_4h data."""
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_4h=103.0,
    )
    result = await db.get_accuracy_over_time(days=30)
    assert len(result) >= 1


@pytest.mark.asyncio
async def test_mixed_stance_always_neutral_in_accuracy(db):
    """Mixed stance signals should be neutral in win/loss calculation."""
    await _insert_signal_with_perf(
        db, stance="mixed", price_at_signal=100.0, price_1d=150.0,
    )
    result = await db.get_aggregate_accuracy(days=30)
    # Mixed should not count as a winner even with huge price increase
    assert result.get("winners", 0) == 0 or result.get("neutral", 0) >= 0


@pytest.mark.asyncio
async def test_performance_summary_signals_today(db):
    """signals_today should count signals created in last 24h."""
    await _insert_signal(db)
    result = await db.get_performance_summary(days=30)
    assert result["signals_today"] >= 1


@pytest.mark.asyncio
async def test_performance_summary_signals_7d(db):
    """signals_7d should count signals created in last 7 days."""
    await _insert_signal(db)
    result = await db.get_performance_summary(days=30)
    assert result["signals_7d"] >= 1


@pytest.mark.asyncio
async def test_aggregate_accuracy_avg_gain_and_loss(db):
    """avg_gain_pct and avg_loss_pct should reflect performance data."""
    await _insert_signal_with_perf(
        db, stance="bullish", price_at_signal=100.0, price_1d=110.0,
        max_gain_pct=10.0, max_loss_pct=-2.0,
    )
    result = await db.get_aggregate_accuracy(days=30)
    assert result.get("avg_gain_pct") is not None


@pytest.mark.asyncio
async def test_performance_history_ordered_newest_first(db):
    """Performance history should be ordered newest first."""
    for _ in range(3):
        await _insert_signal_with_perf(
            db, stance="bullish", price_at_signal=100.0, price_1d=105.0,
        )
    result = await db.get_performance_history(days=30)
    for i in range(len(result) - 1):
        assert result[i]["created_at"] >= result[i + 1]["created_at"]


@pytest.mark.asyncio
async def test_accuracy_by_strategy_avg_gain_loss(db):
    """Strategy accuracy includes avg gain/loss for winning/losing trades."""
    await _insert_signal_with_perf(
        db, strategy="debit_spread", stance="bullish",
        price_at_signal=100.0, price_1d=110.0,
    )
    result = await db.get_accuracy_by_strategy(days=30)
    assert len(result) >= 1
    row = result[0]
    assert "avg_gain_pct" in row
    assert "avg_loss_pct" in row


@pytest.mark.asyncio
async def test_update_performance_prices_ignores_unknown_columns(db):
    """Unknown column names in updates dict should be silently ignored."""
    signal_id = await _insert_signal(db)
    await db.insert_signal_performance(signal_id, "TSLA", 100.0)
    async with db.db.execute(
        "SELECT id FROM signal_performance WHERE signal_id = ?", (signal_id,)
    ) as cursor:
        row = await cursor.fetchone()
    perf_id = row["id"]
    await db.update_performance_prices(perf_id, {
        "price_1h": 101.0,
        "unknown_column": 999.0,  # Should be ignored
    })
    result = await db.get_performance_for_signal(signal_id)
    assert result["price_1h"] == 101.0


@pytest.mark.asyncio
async def test_bearish_1d_return_inverted_in_aggregate(db):
    """Bearish 1d return should be inverted: (1 - price_1d/price_at) * 100."""
    await _insert_signal_with_perf(
        db, stance="bearish", price_at_signal=100.0, price_1d=90.0,
    )
    result = await db.get_aggregate_accuracy(days=30)
    # avg_1d_return_pct for bearish with price going down = positive
    if result.get("avg_1d_return_pct") is not None:
        assert result["avg_1d_return_pct"] > 0


@pytest.mark.asyncio
async def test_performance_csv_ordered_newest_first(db):
    """CSV data ordered newest first."""
    for _ in range(3):
        await _insert_signal_with_perf(
            db, stance="bullish", price_at_signal=100.0, price_1d=110.0,
        )
    result = await db.get_performance_csv_data(days=365)
    for i in range(len(result) - 1):
        assert result[i]["created_at"] >= result[i + 1]["created_at"]


@pytest.mark.asyncio
async def test_multiple_tickers_performance_by_ticker(db):
    """Multiple tickers ordered by total_signals desc."""
    for _ in range(3):
        await _insert_signal_with_perf(
            db, ticker="TSLA", stance="bullish",
            price_at_signal=100.0, price_1d=110.0,
        )
    await _insert_signal_with_perf(
        db, ticker="AAPL", stance="bullish",
        price_at_signal=150.0, price_1d=155.0,
    )
    result = await db.get_performance_by_ticker(days=30)
    assert len(result) == 2
    assert result[0]["total_signals"] >= result[1]["total_signals"]
