"""Tests for signal archive system.

Verifies that signals are archived before purge and that all downstream
queries (backtest, accuracy, calibration, feedback) include archived data.
"""
from __future__ import annotations

import time
import pytest
from rot.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


async def _insert_signal_with_perf(db, ticker="TSLA", stance="bullish",
                                    strategy="debit_spread", event_type="earnings_rumor",
                                    confidence=0.6, subreddit="wallstreetbets",
                                    created_offset_days=0, price_at=100.0,
                                    price_1d=105.0):
    """Helper: insert a signal + signal_performance row."""
    created_at = time.time() - (created_offset_days * 86400)
    signal_data = {
        "run_id": f"run_{ticker}_{created_offset_days}",
        "event": {
            "event_type": event_type,
            "entities": [ticker],
            "stance": stance,
            "time_horizon": "1w",
            "confidence": confidence,
            "evidence": [{"subreddit": subreddit, "excerpt": f"{ticker} test"}],
            "meta": {"trend_score": 1.0, "market": {}},
        },
        "reasoning": {"thesis": "test", "raw": {}},
        "trade_idea": {
            "underlying": ticker,
            "strategy": strategy,
            "quality_score": 0.5,
            "legs": [],
        },
    }
    signal_id = await db.insert_signal(signal_data)
    # Override created_at for age-based testing
    await db.db.execute(
        "UPDATE signals SET created_at = ? WHERE id = ?",
        (created_at, signal_id)
    )
    # Insert performance data
    await db.db.execute("""
        INSERT INTO signal_performance (signal_id, ticker, price_at_signal,
            price_1h, price_4h, price_1d, max_gain_pct, max_loss_pct, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (signal_id, ticker, price_at, price_at * 1.02, price_at * 1.03,
          price_1d, 5.0, -2.0, created_at + 86400))
    await db.db.commit()
    return signal_id


# ── Schema Tests ──

@pytest.mark.asyncio
async def test_archive_table_created(db):
    """signal_archive table should exist after connect()."""
    async with db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_archive'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None


# ── Archive Method Tests ──

@pytest.mark.asyncio
async def test_archive_before_purge_basic(db):
    """Signals older than cutoff should be archived."""
    sid = await _insert_signal_with_perf(db, created_offset_days=20)
    count = await db.archive_before_purge(keep_days=14)
    assert count == 1
    # Verify archive row
    async with db.db.execute(
        "SELECT * FROM signal_archive WHERE id = ?", (sid,)
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row["ticker"] == "TSLA"
    assert row["stance"] == "bullish"
    assert row["price_at_signal"] == 100.0


@pytest.mark.asyncio
async def test_archive_skips_recent_signals(db):
    """Signals newer than cutoff should NOT be archived."""
    await _insert_signal_with_perf(db, created_offset_days=5)
    count = await db.archive_before_purge(keep_days=14)
    assert count == 0


@pytest.mark.asyncio
async def test_archive_skips_no_exit_price(db):
    """Signals without exit price should NOT be archived."""
    sid = await _insert_signal_with_perf(db, created_offset_days=20, price_1d=None)
    # Also clear price_1h and price_4h
    await db.db.execute(
        "UPDATE signal_performance SET price_1d = NULL, price_4h = NULL, price_1h = NULL WHERE signal_id = ?",
        (sid,)
    )
    await db.db.commit()
    count = await db.archive_before_purge(keep_days=14)
    assert count == 0


@pytest.mark.asyncio
async def test_archive_idempotent(db):
    """Calling archive twice should not duplicate rows."""
    await _insert_signal_with_perf(db, created_offset_days=20)
    count1 = await db.archive_before_purge(keep_days=14)
    count2 = await db.archive_before_purge(keep_days=14)
    assert count1 == 1
    assert count2 == 0  # INSERT OR IGNORE
    # Only one archive row
    async with db.db.execute("SELECT COUNT(*) FROM signal_archive") as cursor:
        row = await cursor.fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_purge_old_archives(db):
    """Archives older than keep_days should be purged."""
    sid = await _insert_signal_with_perf(db, created_offset_days=400)
    await db.archive_before_purge(keep_days=14)
    # Archive exists
    async with db.db.execute("SELECT COUNT(*) FROM signal_archive") as cursor:
        assert (await cursor.fetchone())[0] == 1
    # Purge archives older than 365 days
    count = await db.purge_old_archives(keep_days=365)
    assert count == 1
    async with db.db.execute("SELECT COUNT(*) FROM signal_archive") as cursor:
        assert (await cursor.fetchone())[0] == 0


# ── Cleanup Integration ──

@pytest.mark.asyncio
async def test_run_full_cleanup_archives_before_purge(db):
    """run_full_cleanup should archive signals before deleting them."""
    sid = await _insert_signal_with_perf(db, created_offset_days=20)
    results = await db.run_full_cleanup()
    assert results.get("archived_signals", 0) >= 1
    assert results.get("old_signals", 0) >= 1
    # Signal deleted from signals table
    async with db.db.execute(
        "SELECT COUNT(*) FROM signals WHERE id = ?", (sid,)
    ) as cursor:
        assert (await cursor.fetchone())[0] == 0
    # But archived
    async with db.db.execute(
        "SELECT COUNT(*) FROM signal_archive WHERE id = ?", (sid,)
    ) as cursor:
        assert (await cursor.fetchone())[0] == 1


# ── Backtest Includes Archive ──

@pytest.mark.asyncio
async def test_backtest_includes_archived_signals(db):
    """get_backtest_signals should include data from signal_archive."""
    # Insert an old signal, archive it, then purge
    sid = await _insert_signal_with_perf(db, ticker="AAPL", created_offset_days=20,
                                          stance="bearish")
    # Also insert a recent signal
    sid2 = await _insert_signal_with_perf(db, ticker="TSLA", created_offset_days=2)
    # Archive and purge old
    await db.archive_before_purge(keep_days=14)
    await db.purge_old_signals(keep_days=14)
    await db.purge_orphaned_performance()
    # Backtest should find both
    signals = await db.get_backtest_signals(days=30)
    tickers = {s["ticker"] for s in signals}
    assert "AAPL" in tickers  # from archive
    assert "TSLA" in tickers  # from live


@pytest.mark.asyncio
async def test_backtest_filters_on_archive(db):
    """Backtest filters (ticker, stance) should work on archived data."""
    await _insert_signal_with_perf(db, ticker="AAPL", stance="bearish",
                                    created_offset_days=20)
    await _insert_signal_with_perf(db, ticker="TSLA", stance="bullish",
                                    created_offset_days=20)
    await db.archive_before_purge(keep_days=14)
    await db.purge_old_signals(keep_days=14)
    await db.purge_orphaned_performance()
    # Filter by ticker
    signals = await db.get_backtest_signals(days=30, ticker="AAPL")
    assert len(signals) == 1
    assert signals[0]["ticker"] == "AAPL"
    # Filter by stance
    signals = await db.get_backtest_signals(days=30, stance="bullish")
    assert len(signals) == 1
    assert signals[0]["ticker"] == "TSLA"


# ── Accuracy/Performance Queries Include Archive ──

@pytest.mark.asyncio
async def test_accuracy_over_time_includes_archive(db):
    """get_accuracy_over_time should include archived signals."""
    await _insert_signal_with_perf(db, created_offset_days=20)
    await db.archive_before_purge(keep_days=14)
    await db.purge_old_signals(keep_days=14)
    await db.purge_orphaned_performance()
    result = await db.get_accuracy_over_time(days=30)
    assert len(result) >= 1
    assert result[0]["total"] >= 1


@pytest.mark.asyncio
async def test_strategy_pnl_includes_archive(db):
    """get_strategy_pnl should include archived signals."""
    await _insert_signal_with_perf(db, strategy="credit_spread",
                                    created_offset_days=20)
    await db.archive_before_purge(keep_days=14)
    await db.purge_old_signals(keep_days=14)
    await db.purge_orphaned_performance()
    result = await db.get_strategy_pnl(days=30)
    strategies = {r["strategy"] for r in result}
    assert "credit_spread" in strategies


@pytest.mark.asyncio
async def test_accuracy_by_event_type_includes_archive(db):
    """get_accuracy_by_event_type should include archived signals."""
    await _insert_signal_with_perf(db, event_type="regulatory",
                                    created_offset_days=20)
    await db.archive_before_purge(keep_days=14)
    await db.purge_old_signals(keep_days=14)
    await db.purge_orphaned_performance()
    result = await db.get_accuracy_by_event_type(days=30)
    types = {r["event_type"] for r in result}
    assert "regulatory" in types


@pytest.mark.asyncio
async def test_confidence_calibration_includes_archive(db):
    """get_confidence_calibration should include archived signals."""
    await _insert_signal_with_perf(db, confidence=0.75, created_offset_days=20)
    await db.archive_before_purge(keep_days=14)
    await db.purge_old_signals(keep_days=14)
    await db.purge_orphaned_performance()
    result = await db.get_confidence_calibration(days=30)
    assert len(result) >= 1
    # The decile for 0.75 is 7
    deciles = {r["decile"] for r in result}
    assert 7 in deciles


@pytest.mark.asyncio
async def test_accuracy_by_confidence_includes_archive(db):
    """get_accuracy_by_confidence should include archived signals."""
    await _insert_signal_with_perf(db, confidence=0.8, created_offset_days=20)
    await db.archive_before_purge(keep_days=14)
    await db.purge_old_signals(keep_days=14)
    await db.purge_orphaned_performance()
    result = await db.get_accuracy_by_confidence(days=30)
    assert len(result) >= 1


@pytest.mark.asyncio
async def test_performance_by_ticker_includes_archive(db):
    """get_performance_by_ticker should include archived signals."""
    await _insert_signal_with_perf(db, ticker="NVDA", created_offset_days=20)
    await db.archive_before_purge(keep_days=14)
    await db.purge_old_signals(keep_days=14)
    await db.purge_orphaned_performance()
    result = await db.get_performance_by_ticker(days=30)
    tickers = {r["ticker"] for r in result}
    assert "NVDA" in tickers


@pytest.mark.asyncio
async def test_accuracy_by_strategy_includes_archive(db):
    """get_accuracy_by_strategy should include archived signals."""
    await _insert_signal_with_perf(db, strategy="iron_condor",
                                    created_offset_days=20)
    await db.archive_before_purge(keep_days=14)
    await db.purge_old_signals(keep_days=14)
    await db.purge_orphaned_performance()
    result = await db.get_accuracy_by_strategy(days=30)
    strategies = {r["strategy"] for r in result}
    assert "iron_condor" in strategies


# ── Feedback Analyzer Includes Archive ──

@pytest.mark.asyncio
async def test_feedback_category_performance_includes_archive(db):
    """FeedbackAnalyzer.get_category_performance should include archived data."""
    from rot.feedback.analyzer import FeedbackAnalyzer
    analyzer = FeedbackAnalyzer(db)
    await _insert_signal_with_perf(db, event_type="squeeze_chatter",
                                    created_offset_days=20)
    await db.archive_before_purge(keep_days=14)
    await db.purge_old_signals(keep_days=14)
    await db.purge_orphaned_performance()
    result = await analyzer.get_category_performance(days=30)
    types = {r["event_type"] for r in result}
    assert "squeeze_chatter" in types


@pytest.mark.asyncio
async def test_feedback_source_reliability_includes_archive(db):
    """FeedbackAnalyzer.get_source_reliability should include archived data."""
    from rot.feedback.analyzer import FeedbackAnalyzer
    analyzer = FeedbackAnalyzer(db)
    # Insert 5 signals from same source (min count for source reliability)
    for i in range(5):
        await _insert_signal_with_perf(
            db, subreddit="options", created_offset_days=20 + i,
            ticker=f"T{i}LA"  # unique tickers to avoid dedup
        )
    await db.archive_before_purge(keep_days=14)
    await db.purge_old_signals(keep_days=14)
    await db.purge_orphaned_performance()
    result = await analyzer.get_source_reliability(days=60)
    sources = {r["source"] for r in result}
    assert "options" in sources


# ── Migration Test ──

@pytest.mark.asyncio
async def test_initial_migration_archives_existing(tmp_path):
    """connect() should archive existing resolved signals on first run."""
    db = Database(db_path=str(tmp_path / "test.db"))
    await db.connect()
    # Insert a signal with performance (this signal is "current")
    await _insert_signal_with_perf(db, created_offset_days=2)
    await db.close()
    # Reconnect — migration should archive existing signals
    db2 = Database(db_path=str(tmp_path / "test.db"))
    await db2.connect()
    async with db2.db.execute("SELECT COUNT(*) FROM signal_archive") as cursor:
        count = (await cursor.fetchone())[0]
    assert count >= 1
    await db2.close()
