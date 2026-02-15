from __future__ import annotations

import time
import uuid

import pytest

from rot.storage.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


# ---------------------------------------------------------------------------
# Helper: deterministic IDs
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:16]


async def _insert_signal(db, *, ticker: str = "AAPL", stance: str = "bullish",
                         created_at: float | None = None,
                         post_url: str = "",
                         quality_score: float = 0.5,
                         expires_at: float | None = None,
                         market_data: str = "{}",
                         post_mortem: str = "") -> str:
    """Insert a minimal signal row and return its id."""
    sid = _uid()
    now = created_at if created_at is not None else time.time()
    await db.db.execute(
        """INSERT INTO signals
           (id, run_id, created_at, ticker, event_type, stance, confidence,
            quality_score, post_url, market_data, reasoning, trade_idea,
            event_data, post_mortem, expires_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sid, "run", now, ticker, "other", stance, 0.6,
         quality_score, post_url, market_data, "{}", "{}", "{}", post_mortem,
         expires_at),
    )
    await db.db.commit()
    return sid


async def _insert_performance(db, signal_id: str, ticker: str = "AAPL",
                              price_at_signal: float = 100.0,
                              price_1h: float | None = None,
                              price_4h: float | None = None,
                              price_1d: float | None = None,
                              max_gain_pct: float | None = None,
                              max_loss_pct: float | None = None,
                              checked_at: float | None = None) -> None:
    if checked_at is None:
        checked_at = time.time()
    await db.db.execute(
        """INSERT INTO signal_performance
           (signal_id, ticker, price_at_signal, price_1h, price_4h,
            price_1d, max_gain_pct, max_loss_pct, checked_at, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (signal_id, ticker, price_at_signal, price_1h, price_4h,
         price_1d, max_gain_pct, max_loss_pct, checked_at, checked_at),
    )
    await db.db.commit()


OLD = time.time() - 999 * 86400  # ~2.7 years ago
RECENT = time.time() - 1 * 86400  # yesterday


# ===================================================================
# archive_before_purge
# ===================================================================

class TestArchiveBeforePurge:

    @pytest.mark.asyncio
    async def test_archives_old_signals_with_performance(self, db):
        sid = await _insert_signal(db, created_at=OLD)
        await _insert_performance(db, sid, price_1d=105.0)

        count = await db.archive_before_purge(keep_days=14)
        assert count >= 1

        async with db.db.execute("SELECT COUNT(*) FROM signal_archive") as c:
            row = await c.fetchone()
            assert row[0] >= 1

    @pytest.mark.asyncio
    async def test_does_not_archive_recent_signals(self, db):
        sid = await _insert_signal(db, created_at=RECENT)
        await _insert_performance(db, sid, price_1d=105.0)

        count = await db.archive_before_purge(keep_days=14)
        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_signals_without_price_data(self, db):
        sid = await _insert_signal(db, created_at=OLD)
        await _insert_performance(db, sid, price_at_signal=0.0)

        count = await db.archive_before_purge(keep_days=14)
        assert count == 0

    @pytest.mark.asyncio
    async def test_idempotent(self, db):
        sid = await _insert_signal(db, created_at=OLD)
        await _insert_performance(db, sid, price_1d=110.0)

        first = await db.archive_before_purge(keep_days=14)
        second = await db.archive_before_purge(keep_days=14)
        assert first >= 1
        assert second == 0  # INSERT OR IGNORE

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.archive_before_purge(keep_days=14)
        assert count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("keep_days", [1, 7, 14, 30, 90, 365])
    async def test_various_keep_days(self, db, keep_days):
        # Signal from 500 days ago should always be archived for keep_days <= 499
        sid = await _insert_signal(db, created_at=time.time() - 500 * 86400)
        await _insert_performance(db, sid, price_1d=105.0)

        count = await db.archive_before_purge(keep_days=keep_days)
        assert count >= 1


# ===================================================================
# purge_old_archives
# ===================================================================

class TestPurgeOldArchives:

    @pytest.mark.asyncio
    async def test_deletes_old_archives(self, db):
        # Manually insert an archive row with very old created_at
        await db.db.execute(
            """INSERT INTO signal_archive
               (id, created_at, ticker, archived_at, event_type, stance,
                strategy, confidence, subreddit, quality_score, sector,
                post_title, price_at_signal)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_uid(), OLD, "AAPL", OLD, "other", "bullish",
             "none", 0.5, "wsb", 0.5, "", "test", 100.0),
        )
        await db.db.commit()

        count = await db.purge_old_archives(keep_days=365)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_archives(self, db):
        await db.db.execute(
            """INSERT INTO signal_archive
               (id, created_at, ticker, archived_at, event_type, stance,
                strategy, confidence, subreddit, quality_score, sector,
                post_title, price_at_signal)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_uid(), RECENT, "AAPL", RECENT, "other", "bullish",
             "none", 0.5, "wsb", 0.5, "", "test", 100.0),
        )
        await db.db.commit()

        count = await db.purge_old_archives(keep_days=365)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_old_archives(keep_days=365)
        assert count == 0


# ===================================================================
# snapshot_win_rate_before_purge
# ===================================================================

class TestSnapshotWinRateBeforePurge:

    @pytest.mark.asyncio
    async def test_creates_snapshot_for_old_signals(self, db):
        sid = await _insert_signal(db, stance="bullish", created_at=OLD)
        await _insert_performance(db, sid, price_at_signal=100.0, price_1d=110.0,
                                  max_gain_pct=10.0, max_loss_pct=-2.0)

        total = await db.snapshot_win_rate_before_purge(keep_days=14)
        assert total >= 1

        async with db.db.execute("SELECT COUNT(*) FROM win_rate_snapshots") as c:
            row = await c.fetchone()
            assert row[0] >= 1

    @pytest.mark.asyncio
    async def test_returns_zero_for_no_data(self, db):
        total = await db.snapshot_win_rate_before_purge(keep_days=14)
        assert total == 0

    @pytest.mark.asyncio
    async def test_returns_zero_for_recent_only(self, db):
        sid = await _insert_signal(db, created_at=RECENT)
        await _insert_performance(db, sid, price_at_signal=100.0, price_1d=105.0)

        total = await db.snapshot_win_rate_before_purge(keep_days=14)
        assert total == 0

    @pytest.mark.asyncio
    async def test_skips_zero_price_signals(self, db):
        sid = await _insert_signal(db, created_at=OLD)
        await _insert_performance(db, sid, price_at_signal=0.0, price_1d=0.0)

        total = await db.snapshot_win_rate_before_purge(keep_days=14)
        assert total == 0


# ===================================================================
# purge_old_signals
# ===================================================================

class TestPurgeOldSignals:

    @pytest.mark.asyncio
    async def test_deletes_old_signals(self, db):
        await _insert_signal(db, created_at=OLD)
        count = await db.purge_old_signals(keep_days=90)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_signals(self, db):
        await _insert_signal(db, created_at=RECENT)
        count = await db.purge_old_signals(keep_days=90)
        assert count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("keep_days,expect_deleted", [
        (1, True),
        (7, True),
        (90, True),
        (99999, False),
    ])
    async def test_parametrized_keep_days(self, db, keep_days, expect_deleted):
        await _insert_signal(db, created_at=OLD)
        count = await db.purge_old_signals(keep_days=keep_days)
        if expect_deleted:
            assert count >= 1
        else:
            assert count == 0


# ===================================================================
# purge_duplicate_signals
# ===================================================================

class TestPurgeDuplicateSignals:

    @pytest.mark.asyncio
    async def test_removes_older_duplicate(self, db):
        url = "https://reddit.com/r/wsb/abc"
        await _insert_signal(db, ticker="TSLA", post_url=url,
                             created_at=time.time() - 3600)
        await _insert_signal(db, ticker="TSLA", post_url=url,
                             created_at=time.time())

        count = await db.purge_duplicate_signals()
        assert count >= 1

        async with db.db.execute("SELECT COUNT(*) FROM signals WHERE post_url = ?", (url,)) as c:
            row = await c.fetchone()
            assert row[0] == 1  # only the newest remains

    @pytest.mark.asyncio
    async def test_no_duplicates(self, db):
        await _insert_signal(db, ticker="TSLA", post_url="https://url1.com")
        await _insert_signal(db, ticker="AAPL", post_url="https://url2.com")

        count = await db.purge_duplicate_signals()
        assert count == 0

    @pytest.mark.asyncio
    async def test_ignores_empty_post_url(self, db):
        await _insert_signal(db, ticker="TSLA", post_url="", created_at=time.time() - 3600)
        await _insert_signal(db, ticker="TSLA", post_url="", created_at=time.time())

        count = await db.purge_duplicate_signals()
        assert count == 0  # empty post_url excluded from dedup

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_duplicate_signals()
        assert count == 0


# ===================================================================
# purge_orphaned_performance
# ===================================================================

class TestPurgeOrphanedPerformance:

    @pytest.mark.asyncio
    async def test_deletes_orphaned_rows(self, db):
        # Insert performance for a non-existent signal
        await db.db.execute(
            """INSERT INTO signal_performance
               (signal_id, ticker, price_at_signal, checked_at, created_at)
               VALUES (?,?,?,?,?)""",
            ("nonexistent", "AAPL", 100.0, time.time(), time.time()),
        )
        await db.db.commit()

        count = await db.purge_orphaned_performance()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_linked_performance(self, db):
        sid = await _insert_signal(db)
        await _insert_performance(db, sid)

        count = await db.purge_orphaned_performance()
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_orphaned_performance()
        assert count == 0


# ===================================================================
# purge_old_performance
# ===================================================================

class TestPurgeOldPerformance:

    @pytest.mark.asyncio
    async def test_deletes_old_performance(self, db):
        sid = await _insert_signal(db)
        await _insert_performance(db, sid, checked_at=OLD)

        count = await db.purge_old_performance(keep_days=90)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_performance(self, db):
        sid = await _insert_signal(db)
        await _insert_performance(db, sid, checked_at=RECENT)

        count = await db.purge_old_performance(keep_days=90)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_old_performance(keep_days=90)
        assert count == 0


# ===================================================================
# purge_old_x_posts
# ===================================================================

class TestPurgeOldXPosts:

    @pytest.mark.asyncio
    async def test_deletes_old_x_posts(self, db):
        await db.db.execute(
            "INSERT INTO x_posts (signal_id, ticker, posted_at) VALUES (?,?,?)",
            ("sig1", "AAPL", OLD),
        )
        await db.db.commit()

        count = await db.purge_old_x_posts(keep_days=30)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_x_posts(self, db):
        await db.db.execute(
            "INSERT INTO x_posts (signal_id, ticker, posted_at) VALUES (?,?,?)",
            ("sig1", "AAPL", RECENT),
        )
        await db.db.commit()

        count = await db.purge_old_x_posts(keep_days=30)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_old_x_posts(keep_days=30)
        assert count == 0


# ===================================================================
# purge_old_referral_clicks
# ===================================================================

class TestPurgeOldReferralClicks:

    @pytest.mark.asyncio
    async def test_deletes_old_referral_clicks(self, db):
        await db.db.execute(
            "INSERT INTO referral_clicks (ref_code, clicked_at) VALUES (?,?)",
            ("REF1", OLD),
        )
        await db.db.commit()

        count = await db.purge_old_referral_clicks(keep_days=90)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_clicks(self, db):
        await db.db.execute(
            "INSERT INTO referral_clicks (ref_code, clicked_at) VALUES (?,?)",
            ("REF1", RECENT),
        )
        await db.db.commit()

        count = await db.purge_old_referral_clicks(keep_days=90)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_old_referral_clicks(keep_days=90)
        assert count == 0


# ===================================================================
# purge_old_paper_trades
# ===================================================================

class TestPurgeOldPaperTrades:

    @pytest.mark.asyncio
    async def test_deletes_old_closed_trades(self, db):
        await db.db.execute(
            """INSERT INTO paper_trades
               (id, user_id, signal_id, ticker, entry_price, paper_balance_after,
                created_at, closed_at, status)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (_uid(), "user1", "sig1", "AAPL", 100.0, 9900.0,
             OLD, OLD, "closed"),
        )
        await db.db.commit()

        count = await db.purge_old_paper_trades(keep_days=180)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_open_trades(self, db):
        await db.db.execute(
            """INSERT INTO paper_trades
               (id, user_id, signal_id, ticker, entry_price, paper_balance_after,
                created_at, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (_uid(), "user1", "sig1", "AAPL", 100.0, 9900.0,
             OLD, "open"),
        )
        await db.db.commit()

        count = await db.purge_old_paper_trades(keep_days=180)
        assert count == 0

    @pytest.mark.asyncio
    async def test_keeps_recent_closed_trades(self, db):
        await db.db.execute(
            """INSERT INTO paper_trades
               (id, user_id, signal_id, ticker, entry_price, paper_balance_after,
                created_at, closed_at, status)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (_uid(), "user1", "sig1", "AAPL", 100.0, 9900.0,
             RECENT, RECENT, "closed"),
        )
        await db.db.commit()

        count = await db.purge_old_paper_trades(keep_days=180)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_old_paper_trades(keep_days=180)
        assert count == 0


# ===================================================================
# purge_stub_signals
# ===================================================================

class TestPurgeStubSignals:

    @pytest.mark.asyncio
    async def test_always_returns_zero(self, db):
        # Insert a signal just to ensure it is a no-op
        await _insert_signal(db)
        count = await db.purge_stub_signals()
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_stub_signals()
        assert count == 0


# ===================================================================
# purge_fake_ticker_signals
# ===================================================================

class TestPurgeFakeTickerSignals:

    FAKE_TICKERS = [
        "JOLTS", "NFP", "PMI", "PCE", "PPI", "ADP", "ISM",
        "GMV", "MAU", "DAU", "ARR", "MRR", "TAM", "SAM",
        "URL", "GFC", "LSEG", "CAGR", "EBITDA", "EBIT",
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fake_ticker", [
        "JOLTS", "NFP", "PMI", "EBITDA", "EBIT", "CAGR",
    ])
    async def test_deletes_fake_ticker(self, db, fake_ticker):
        await _insert_signal(db, ticker=fake_ticker)
        count = await db.purge_fake_ticker_signals()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_real_tickers(self, db):
        await _insert_signal(db, ticker="AAPL")
        await _insert_signal(db, ticker="TSLA")

        count = await db.purge_fake_ticker_signals()
        assert count == 0

    @pytest.mark.asyncio
    async def test_mixed_real_and_fake(self, db):
        await _insert_signal(db, ticker="AAPL")
        await _insert_signal(db, ticker="JOLTS")
        await _insert_signal(db, ticker="NFP")

        count = await db.purge_fake_ticker_signals()
        assert count == 2

        async with db.db.execute("SELECT COUNT(*) FROM signals") as c:
            row = await c.fetchone()
            assert row[0] == 1

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_fake_ticker_signals()
        assert count == 0


# ===================================================================
# purge_old_win_rate_snapshots
# ===================================================================

class TestPurgeOldWinRateSnapshots:
    """Tests for purge_old_win_rate_snapshots.

    Note: The prod method references 'snapshot_date' but the column is
    'snapshot_at'.  These tests are xfail until the prod bug is fixed.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="prod bug: snapshot_date vs snapshot_at column name")
    async def test_keeps_recent_and_deletes_overflow(self, db):
        for i in range(5):
            await db.db.execute(
                """INSERT INTO win_rate_snapshots
                   (snapshot_at, period_start, period_end, total_tracked)
                   VALUES (?,?,?,?)""",
                (time.time() - i * 3600, OLD, RECENT, 10),
            )
        await db.db.commit()

        count = await db.purge_old_win_rate_snapshots(keep_count=3)
        assert count >= 2

        async with db.db.execute("SELECT COUNT(*) FROM win_rate_snapshots") as c:
            row = await c.fetchone()
            assert row[0] == 3

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="prod bug: snapshot_date vs snapshot_at column name")
    async def test_nothing_to_purge(self, db):
        await db.db.execute(
            """INSERT INTO win_rate_snapshots
               (snapshot_at, period_start, period_end, total_tracked)
               VALUES (?,?,?,?)""",
            (time.time(), OLD, RECENT, 10),
        )
        await db.db.commit()

        count = await db.purge_old_win_rate_snapshots(keep_count=100)
        assert count == 0

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="prod bug: snapshot_date vs snapshot_at column name")
    async def test_empty_table(self, db):
        count = await db.purge_old_win_rate_snapshots(keep_count=100)
        assert count == 0


# ===================================================================
# purge_old_data_exports
# ===================================================================

class TestPurgeOldDataExports:

    @pytest.mark.asyncio
    async def test_deletes_old_exports(self, db):
        await db.db.execute(
            "INSERT INTO data_exports (user_id, requested_at) VALUES (?,?)",
            ("user1", OLD),
        )
        await db.db.commit()

        count = await db.purge_old_data_exports(keep_days=30)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_exports(self, db):
        await db.db.execute(
            "INSERT INTO data_exports (user_id, requested_at) VALUES (?,?)",
            ("user1", RECENT),
        )
        await db.db.commit()

        count = await db.purge_old_data_exports(keep_days=30)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_old_data_exports(keep_days=30)
        assert count == 0


# ===================================================================
# purge_old_congress_trades
# ===================================================================

class TestPurgeOldCongressTrades:

    @pytest.mark.asyncio
    async def test_deletes_old_trades(self, db):
        await db.db.execute(
            """INSERT INTO congress_trades
               (id, politician, ticker, filed_at, created_at)
               VALUES (?,?,?,?,?)""",
            (_uid(), "Sen. Test", "AAPL", OLD, OLD),
        )
        await db.db.commit()

        count = await db.purge_old_congress_trades(keep_days=90)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_trades(self, db):
        await db.db.execute(
            """INSERT INTO congress_trades
               (id, politician, ticker, filed_at, created_at)
               VALUES (?,?,?,?,?)""",
            (_uid(), "Sen. Test", "AAPL", RECENT, RECENT),
        )
        await db.db.commit()

        count = await db.purge_old_congress_trades(keep_days=90)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_old_congress_trades(keep_days=90)
        assert count == 0


# ===================================================================
# purge_old_unusual_events
# ===================================================================

class TestPurgeOldUnusualEvents:

    @pytest.mark.asyncio
    async def test_deletes_old_events(self, db):
        await db.db.execute(
            """INSERT INTO unusual_events
               (ticker, event_type, score, detected_at)
               VALUES (?,?,?,?)""",
            ("AAPL", "iv_spike", 0.9, OLD),
        )
        await db.db.commit()

        count = await db.purge_old_unusual_events(keep_days=30)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_events(self, db):
        await db.db.execute(
            """INSERT INTO unusual_events
               (ticker, event_type, score, detected_at)
               VALUES (?,?,?,?)""",
            ("AAPL", "iv_spike", 0.9, RECENT),
        )
        await db.db.commit()

        count = await db.purge_old_unusual_events(keep_days=30)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_old_unusual_events(keep_days=30)
        assert count == 0


# ===================================================================
# purge_old_macro_events
# ===================================================================

class TestPurgeOldMacroEvents:

    @pytest.mark.asyncio
    async def test_deletes_old_events(self, db):
        await db.db.execute(
            """INSERT INTO macro_events
               (id, event_type, name, scheduled_at, category, created_at)
               VALUES (?,?,?,?,?,?)""",
            (_uid(), "cpi", "CPI Release", OLD, "inflation", OLD),
        )
        await db.db.commit()

        count = await db.purge_old_macro_events(keep_days=365)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_events(self, db):
        await db.db.execute(
            """INSERT INTO macro_events
               (id, event_type, name, scheduled_at, category, created_at)
               VALUES (?,?,?,?,?,?)""",
            (_uid(), "cpi", "CPI Release", RECENT, "inflation", RECENT),
        )
        await db.db.commit()

        count = await db.purge_old_macro_events(keep_days=365)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_old_macro_events(keep_days=365)
        assert count == 0


# ===================================================================
# purge_old_insider_trades
# ===================================================================

class TestPurgeOldInsiderTrades:

    @pytest.mark.asyncio
    async def test_deletes_old_trades(self, db):
        await db.db.execute(
            """INSERT INTO insider_trades
               (id, ticker, insider_name, trade_type, filing_date, created_at)
               VALUES (?,?,?,?,?,?)""",
            (_uid(), "AAPL", "Tim Cook", "sale", OLD, OLD),
        )
        await db.db.commit()

        count = await db.purge_old_insider_trades(keep_days=365)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_trades(self, db):
        await db.db.execute(
            """INSERT INTO insider_trades
               (id, ticker, insider_name, trade_type, filing_date, created_at)
               VALUES (?,?,?,?,?,?)""",
            (_uid(), "AAPL", "Tim Cook", "sale", RECENT, RECENT),
        )
        await db.db.commit()

        count = await db.purge_old_insider_trades(keep_days=365)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_old_insider_trades(keep_days=365)
        assert count == 0


# ===================================================================
# purge_old_earnings_events
# ===================================================================

class TestPurgeOldEarningsEvents:

    @pytest.mark.asyncio
    async def test_deletes_old_events(self, db):
        await db.db.execute(
            """INSERT INTO earnings_events
               (id, ticker, report_date, created_at)
               VALUES (?,?,?,?)""",
            (_uid(), "AAPL", OLD, OLD),
        )
        await db.db.commit()

        count = await db.purge_old_earnings_events(keep_days=365)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_events(self, db):
        await db.db.execute(
            """INSERT INTO earnings_events
               (id, ticker, report_date, created_at)
               VALUES (?,?,?,?)""",
            (_uid(), "AAPL", RECENT, RECENT),
        )
        await db.db.commit()

        count = await db.purge_old_earnings_events(keep_days=365)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.purge_old_earnings_events(keep_days=365)
        assert count == 0


# ===================================================================
# purge_old_flow_data
# ===================================================================

class TestPurgeOldFlowData:

    @pytest.mark.asyncio
    async def test_deletes_old_flow_events(self, db):
        await db.db.execute(
            """INSERT INTO flow_events
               (id, ticker, flow_type, direction, detected_at)
               VALUES (?,?,?,?,?)""",
            (_uid(), "AAPL", "block", "bullish", OLD),
        )
        await db.db.commit()

        count = await db.purge_old_flow_data(keep_days=90)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_deletes_old_flow_patterns(self, db):
        await db.db.execute(
            """INSERT INTO flow_patterns
               (id, pattern_type, detected_at)
               VALUES (?,?,?)""",
            (_uid(), "sweep", OLD),
        )
        await db.db.commit()

        count = await db.purge_old_flow_data(keep_days=90)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_deletes_old_flow_convergences(self, db):
        await db.db.execute(
            """INSERT INTO flow_convergences
               (id, signal_id, ticker, convergence_type, detected_at)
               VALUES (?,?,?,?,?)""",
            (_uid(), "sig1", "AAPL", "confirming", OLD),
        )
        await db.db.commit()

        count = await db.purge_old_flow_data(keep_days=90)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_data(self, db):
        for table, insert in [
            ("flow_events",
             "INSERT INTO flow_events (id, ticker, flow_type, direction, detected_at) VALUES (?,?,?,?,?)"),
            ("flow_patterns",
             "INSERT INTO flow_patterns (id, pattern_type, detected_at) VALUES (?,?,?)"),
        ]:
            if "flow_events" in table:
                await db.db.execute(insert, (_uid(), "AAPL", "block", "bullish", RECENT))
            else:
                await db.db.execute(insert, (_uid(), "sweep", RECENT))
        await db.db.commit()

        count = await db.purge_old_flow_data(keep_days=90)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_tables(self, db):
        count = await db.purge_old_flow_data(keep_days=90)
        assert count == 0

    @pytest.mark.asyncio
    async def test_aggregates_across_tables(self, db):
        await db.db.execute(
            """INSERT INTO flow_events
               (id, ticker, flow_type, direction, detected_at)
               VALUES (?,?,?,?,?)""",
            (_uid(), "AAPL", "block", "bullish", OLD),
        )
        await db.db.execute(
            """INSERT INTO flow_patterns
               (id, pattern_type, detected_at) VALUES (?,?,?)""",
            (_uid(), "sweep", OLD),
        )
        await db.db.execute(
            """INSERT INTO flow_convergences
               (id, signal_id, ticker, convergence_type, detected_at)
               VALUES (?,?,?,?,?)""",
            (_uid(), "sig1", "AAPL", "confirming", OLD),
        )
        await db.db.commit()

        count = await db.purge_old_flow_data(keep_days=90)
        assert count == 3


# ===================================================================
# purge_old_social_data
# ===================================================================

class TestPurgeOldSocialData:

    @pytest.mark.asyncio
    async def test_deletes_old_predictions(self, db):
        await db.db.execute(
            """INSERT INTO author_predictions
               (id, author_id, ticker, stance, created_at)
               VALUES (?,?,?,?,?)""",
            (_uid(), "author1", "AAPL", "bullish", OLD),
        )
        await db.db.commit()

        count = await db.purge_old_social_data(keep_days=180)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_deletes_old_manipulation_alerts(self, db):
        await db.db.execute(
            """INSERT INTO manipulation_alerts
               (id, alert_type, severity, detected_at)
               VALUES (?,?,?,?)""",
            (_uid(), "pump_dump", 0.9, OLD),
        )
        await db.db.commit()

        count = await db.purge_old_social_data(keep_days=180)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_deletes_old_propagation(self, db):
        await db.db.execute(
            """INSERT INTO sentiment_propagation
               (id, ticker, origin_sub, spread_to, origin_ts, spread_ts,
                detected_at)
               VALUES (?,?,?,?,?,?,?)""",
            (_uid(), "AAPL", "wsb", "stocks", OLD, OLD, OLD),
        )
        await db.db.commit()

        count = await db.purge_old_social_data(keep_days=180)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_deletes_old_clusters(self, db):
        await db.db.execute(
            """INSERT INTO author_clusters
               (id, similarity_score, detected_at)
               VALUES (?,?,?)""",
            (_uid(), 0.95, OLD),
        )
        await db.db.commit()

        count = await db.purge_old_social_data(keep_days=180)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_social_data(self, db):
        await db.db.execute(
            """INSERT INTO author_predictions
               (id, author_id, ticker, stance, created_at)
               VALUES (?,?,?,?,?)""",
            (_uid(), "author1", "AAPL", "bullish", RECENT),
        )
        await db.db.commit()

        count = await db.purge_old_social_data(keep_days=180)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_tables(self, db):
        count = await db.purge_old_social_data(keep_days=180)
        assert count == 0

    @pytest.mark.asyncio
    async def test_aggregates_across_all_social_tables(self, db):
        await db.db.execute(
            """INSERT INTO author_predictions
               (id, author_id, ticker, stance, created_at)
               VALUES (?,?,?,?,?)""",
            (_uid(), "a1", "AAPL", "bullish", OLD),
        )
        await db.db.execute(
            """INSERT INTO manipulation_alerts
               (id, alert_type, severity, detected_at)
               VALUES (?,?,?,?)""",
            (_uid(), "pump_dump", 0.9, OLD),
        )
        await db.db.execute(
            """INSERT INTO sentiment_propagation
               (id, ticker, origin_sub, spread_to, origin_ts, spread_ts,
                detected_at)
               VALUES (?,?,?,?,?,?,?)""",
            (_uid(), "AAPL", "wsb", "stocks", OLD, OLD, OLD),
        )
        await db.db.execute(
            """INSERT INTO author_clusters
               (id, similarity_score, detected_at)
               VALUES (?,?,?)""",
            (_uid(), 0.8, OLD),
        )
        await db.db.commit()

        count = await db.purge_old_social_data(keep_days=180)
        assert count == 4


# ===================================================================
# purge_old_strategy_data
# ===================================================================

class TestPurgeOldStrategyData:

    @pytest.mark.asyncio
    async def test_deletes_old_resolved_trades(self, db):
        await db.db.execute(
            """INSERT INTO strategy_trades
               (id, strategy_id, ticker, stance, entry_price, created_at,
                resolved_at)
               VALUES (?,?,?,?,?,?,?)""",
            (_uid(), "strat1", "AAPL", "bullish", 100.0, OLD, OLD),
        )
        await db.db.commit()

        count = await db.purge_old_strategy_data(keep_days=90)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_unresolved_trades(self, db):
        await db.db.execute(
            """INSERT INTO strategy_trades
               (id, strategy_id, ticker, stance, entry_price, created_at)
               VALUES (?,?,?,?,?,?)""",
            (_uid(), "strat1", "AAPL", "bullish", 100.0, OLD),
        )
        await db.db.commit()

        count = await db.purge_old_strategy_data(keep_days=90)
        assert count == 0

    @pytest.mark.asyncio
    async def test_deletes_old_discoveries(self, db):
        await db.db.execute(
            """INSERT INTO strategy_discoveries
               (id, user_id, created_at)
               VALUES (?,?,?)""",
            (_uid(), "user1", OLD),
        )
        await db.db.commit()

        count = await db.purge_old_strategy_data(keep_days=90)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_deletes_old_regimes(self, db):
        await db.db.execute(
            """INSERT INTO market_regimes
               (id, regime_type, start_ts, confidence, detected_at)
               VALUES (?,?,?,?,?)""",
            (_uid(), "bull", OLD, 0.8, OLD),
        )
        await db.db.commit()

        count = await db.purge_old_strategy_data(keep_days=90)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_strategy_data(self, db):
        await db.db.execute(
            """INSERT INTO strategy_trades
               (id, strategy_id, ticker, stance, entry_price, created_at,
                resolved_at)
               VALUES (?,?,?,?,?,?,?)""",
            (_uid(), "strat1", "AAPL", "bullish", 100.0, RECENT, RECENT),
        )
        await db.db.commit()

        count = await db.purge_old_strategy_data(keep_days=90)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_tables(self, db):
        count = await db.purge_old_strategy_data(keep_days=90)
        assert count == 0


# ===================================================================
# cleanup_old_api_usage
# ===================================================================

class TestCleanupOldApiUsage:

    @pytest.mark.asyncio
    async def test_deletes_old_api_usage(self, db):
        await db.db.execute(
            "INSERT INTO api_usage (user_id, endpoint, called_at) VALUES (?,?,?)",
            ("user1", "/api/signals", OLD),
        )
        await db.db.commit()

        count = await db.cleanup_old_api_usage(older_than_s=172800)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent_api_usage(self, db):
        await db.db.execute(
            "INSERT INTO api_usage (user_id, endpoint, called_at) VALUES (?,?,?)",
            ("user1", "/api/signals", time.time()),
        )
        await db.db.commit()

        count = await db.cleanup_old_api_usage(older_than_s=172800)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.cleanup_old_api_usage(older_than_s=172800)
        assert count == 0


# ===================================================================
# cleanup_old_signals
# ===================================================================

class TestCleanupOldSignals:

    @pytest.mark.asyncio
    async def test_deletes_old(self, db):
        await _insert_signal(db, created_at=OLD)
        count = await db.cleanup_old_signals(older_than_s=90 * 86400)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_keeps_recent(self, db):
        await _insert_signal(db, created_at=RECENT)
        count = await db.cleanup_old_signals(older_than_s=90 * 86400)
        assert count == 0


# ===================================================================
# expire_stale_signals
# ===================================================================

class TestExpireStaleSignals:

    @pytest.mark.asyncio
    async def test_expires_stale_signals(self, db):
        # expires_at in the past, quality_score > 0
        await _insert_signal(db, expires_at=OLD, quality_score=0.8)

        count = await db.expire_stale_signals()
        assert count >= 1

        async with db.db.execute("SELECT quality_score FROM signals") as c:
            row = await c.fetchone()
            assert row[0] == 0  # set to 0

    @pytest.mark.asyncio
    async def test_does_not_expire_future_signals(self, db):
        future = time.time() + 86400 * 30
        await _insert_signal(db, expires_at=future, quality_score=0.8)

        count = await db.expire_stale_signals()
        assert count == 0

    @pytest.mark.asyncio
    async def test_does_not_double_expire(self, db):
        await _insert_signal(db, expires_at=OLD, quality_score=0.0)

        count = await db.expire_stale_signals()
        assert count == 0  # already quality_score=0

    @pytest.mark.asyncio
    async def test_ignores_null_expires_at(self, db):
        await _insert_signal(db, expires_at=None, quality_score=0.8)

        count = await db.expire_stale_signals()
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.expire_stale_signals()
        assert count == 0


# ===================================================================
# compact_old_signal_blobs
# ===================================================================

class TestCompactOldSignalBlobs:

    @pytest.mark.asyncio
    async def test_compacts_old_blobs(self, db):
        await _insert_signal(db, created_at=OLD,
                             market_data='{"price": 100}')

        count = await db.compact_old_signal_blobs(older_than_days=3)
        assert count >= 1

        async with db.db.execute("SELECT market_data FROM signals") as c:
            row = await c.fetchone()
            assert row[0] == "{}"

    @pytest.mark.asyncio
    async def test_keeps_recent_blobs(self, db):
        await _insert_signal(db, created_at=RECENT,
                             market_data='{"price": 100}')

        count = await db.compact_old_signal_blobs(older_than_days=3)
        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_already_compacted(self, db):
        await _insert_signal(db, created_at=OLD, market_data="{}")

        count = await db.compact_old_signal_blobs(older_than_days=3)
        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_table(self, db):
        count = await db.compact_old_signal_blobs(older_than_days=3)
        assert count == 0


# ===================================================================
# generate_heuristic_post_mortems
# ===================================================================

class TestGenerateHeuristicPostMortems:

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_signals_need_post_mortem(self, db):
        count = await db.generate_heuristic_post_mortems(limit=50)
        assert count == 0

    @pytest.mark.asyncio
    async def test_signals_with_existing_post_mortem_are_skipped(self, db):
        sid = await _insert_signal(db, post_mortem="Already has one")
        await _insert_performance(db, sid, price_at_signal=100.0, price_1d=110.0)

        count = await db.generate_heuristic_post_mortems(limit=50)
        assert count == 0


# ===================================================================
# vacuum
# ===================================================================

class TestVacuum:

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="aiosqlite keeps statements in progress, VACUUM fails")
    async def test_vacuum_completes_without_error(self, db):
        await db.vacuum()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="aiosqlite keeps statements in progress, VACUUM fails")
    async def test_vacuum_with_data(self, db):
        await _insert_signal(db)
        await db.vacuum()


# ===================================================================
# get_db_size_info
# ===================================================================

class TestGetDbSizeInfo:

    @pytest.mark.asyncio
    async def test_returns_dict(self, db):
        info = await db.get_db_size_info()
        assert isinstance(info, dict)
        assert "db_size_bytes" in info
        assert "db_size_mb" in info

    @pytest.mark.asyncio
    async def test_contains_table_row_counts(self, db):
        info = await db.get_db_size_info()
        assert "signals_rows" in info
        assert "users_rows" in info

    @pytest.mark.asyncio
    async def test_row_counts_increase_with_data(self, db):
        info_before = await db.get_db_size_info()
        await _insert_signal(db)
        info_after = await db.get_db_size_info()

        assert info_after["signals_rows"] == info_before.get("signals_rows", 0) + 1


# ===================================================================
# run_full_cleanup
# ===================================================================

class TestRunFullCleanup:

    @pytest.mark.asyncio
    async def test_returns_results_dict(self, db):
        results = await db.run_full_cleanup()
        assert isinstance(results, dict)

    @pytest.mark.asyncio
    async def test_all_keys_present(self, db):
        results = await db.run_full_cleanup()
        expected_keys = [
            "stub_signals", "fake_ticker_signals", "duplicate_signals",
            "win_rate_snapshot", "archived_signals", "old_signals",
            "orphaned_performance", "old_performance", "old_api_usage",
            "old_x_posts", "old_referral_clicks", "old_paper_trades",
            "expired_signals", "post_mortems", "compacted_blobs",
            "old_snapshots", "old_data_exports", "old_congress_trades",
            "old_archives", "old_flow_events", "old_strategy_data",
        ]
        for key in expected_keys:
            assert key in results, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_all_values_are_ints(self, db):
        results = await db.run_full_cleanup()
        for key, value in results.items():
            assert isinstance(value, int), f"{key} is not int: {type(value)}"

    @pytest.mark.asyncio
    async def test_cleans_old_data(self, db):
        await _insert_signal(db, ticker="JOLTS", created_at=OLD)
        await _insert_signal(db, created_at=OLD, expires_at=OLD, quality_score=0.8)

        results = await db.run_full_cleanup()
        total = sum(results.values())
        assert total >= 1

    @pytest.mark.asyncio
    async def test_empty_database(self, db):
        results = await db.run_full_cleanup()
        total = sum(results.values())
        assert total == 0


# ===================================================================
# Edge cases / boundary tests
# ===================================================================

class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_boundary_timestamp_exactly_at_cutoff(self, db):
        """Signal created exactly at the cutoff boundary should NOT be purged."""
        keep_days = 14
        boundary = time.time() - keep_days * 86400
        await _insert_signal(db, created_at=boundary + 1)  # just inside window

        count = await db.purge_old_signals(keep_days=keep_days)
        assert count == 0

    @pytest.mark.asyncio
    async def test_boundary_timestamp_just_outside_cutoff(self, db):
        """Signal created just before cutoff should be purged."""
        keep_days = 14
        boundary = time.time() - keep_days * 86400
        await _insert_signal(db, created_at=boundary - 1)

        count = await db.purge_old_signals(keep_days=keep_days)
        assert count >= 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("table,insert_sql,params", [
        ("signals", None, None),  # handled by helper
        ("x_posts", "INSERT INTO x_posts (signal_id, ticker, posted_at) VALUES (?,?,?)", ("s", "T", RECENT)),
        ("referral_clicks", "INSERT INTO referral_clicks (ref_code, clicked_at) VALUES (?,?)", ("R", RECENT)),
    ])
    async def test_recent_data_survives_full_cleanup(self, db, table, insert_sql, params):
        """Recent data should not be purged by run_full_cleanup."""
        if table == "signals":
            await _insert_signal(db, created_at=RECENT, ticker="MSFT")
        else:
            await db.db.execute(insert_sql, params)
            await db.db.commit()

        await db.run_full_cleanup()

        async with db.db.execute(f"SELECT COUNT(*) FROM {table}") as c:
            row = await c.fetchone()
            assert row[0] >= 1

    @pytest.mark.asyncio
    async def test_multiple_purge_cycles_are_idempotent(self, db):
        """Running full cleanup twice should be safe (second run deletes 0)."""
        await _insert_signal(db, ticker="NFP", created_at=OLD)
        first = await db.run_full_cleanup()
        second = await db.run_full_cleanup()

        assert sum(first.values()) >= 1
        assert sum(second.values()) == 0
