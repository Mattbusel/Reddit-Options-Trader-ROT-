"""
Base database class with connection/migration/pragma logic.

This module provides the DatabaseBase class that all database mixins inherit from.
It handles:
- Database connection with aiosqlite
- WAL mode and performance pragmas
- Schema creation and migrations
- Connection lifecycle management

Exports:
    DatabaseBase: Base class for database operations
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import aiosqlite

from .schema import SCHEMA_SQL

log = logging.getLogger(__name__)

# Migration list: (table, column, col_type)
# These are safe ADD COLUMN operations that won't fail if the column already exists.
_MIGRATIONS = [
    ("users", "password_hash", "TEXT NOT NULL DEFAULT ''"),
    ("signal_performance", "created_at", "REAL NOT NULL DEFAULT 0"),
    ("signals", "sector", "TEXT NOT NULL DEFAULT ''"),
    ("signals", "sponsored", "INTEGER NOT NULL DEFAULT 0"),
    ("signals", "sponsored_by", "TEXT NOT NULL DEFAULT ''"),
    # Signal expiration & author credibility
    ("signals", "expires_at", "REAL"),
    ("signals", "author", "TEXT NOT NULL DEFAULT ''"),
    ("signals", "author_karma", "INTEGER NOT NULL DEFAULT 0"),
    ("signals", "author_age_days", "INTEGER NOT NULL DEFAULT 0"),
    ("signals", "corroboration_count", "INTEGER NOT NULL DEFAULT 0"),
    ("signals", "corroboration_sources", "TEXT NOT NULL DEFAULT '[]'"),
    ("signals", "post_mortem", "TEXT NOT NULL DEFAULT ''"),
    # Universal AI summary (platform-generated, not BYOK)
    ("signals", "ai_summary", "TEXT NOT NULL DEFAULT ''"),
    # NLP engine columns — custom pipeline metrics
    ("signals", "sarcasm_score", "REAL NOT NULL DEFAULT 0.0"),
    ("signals", "conviction", "REAL NOT NULL DEFAULT 0.5"),
    ("signals", "consensus_score", "REAL NOT NULL DEFAULT 0.0"),
    ("signals", "actionability", "REAL NOT NULL DEFAULT 0.5"),
    ("signals", "nlp_polarity", "REAL NOT NULL DEFAULT 0.0"),
]


class DatabaseBase:
    """
    Base database class with connection/migration/pragma logic.

    This class provides the foundation for all database operations in ROT.
    It handles SQLite connection management, WAL mode setup, performance
    optimizations via PRAGMAs, and schema migrations.

    Usage:
        db = DatabaseBase(db_path="storage/rot.db")
        await db.connect()
        # ... use db.db for queries
        await db.close()
    """

    def __init__(self, db_path: str = "storage/rot.db") -> None:
        """
        Initialize the database connection.

        Args:
            db_path: Path to the SQLite database file. Parent directory
                     will be created if it doesn't exist.
        """
        self.db_path = Path(db_path)
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """
        Connect to the database and apply schema/migrations.

        This method:
        1. Creates the database directory if it doesn't exist
        2. Opens a connection with Row factory for dict-like access
        3. Applies WAL mode and performance PRAGMAs
        4. Creates schema via SCHEMA_SQL
        5. Runs column migrations from _MIGRATIONS
        6. Creates post-migration indexes
        7. Backfills data from JSON columns (confidence, stance, event_type)
        8. Clears outdated win_rate_snapshots
        9. Archives existing resolved signals for long-term analytics

        Raises:
            Exception: If database connection or schema creation fails
        """
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Open connection with Row factory for dict-like access
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row

        # Apply WAL mode and performance optimizations
        await self._apply_wal_pragmas()

        # Create schema and run migrations
        await self._run_migrations()

    async def _apply_wal_pragmas(self) -> None:
        """
        Apply SQLite performance optimizations.

        PRAGMAs applied:
        - journal_mode=WAL: Write-Ahead Logging for concurrent reads
        - synchronous=NORMAL: Faster writes, safe with WAL
        - cache_size=-16000: 16MB page cache (increased from 8MB)
        - temp_store=MEMORY: Keep temp tables in memory
        - mmap_size=134217728: 128MB memory-mapped I/O (increased from 64MB)
        - page_size=4096: 4KB pages (optimal for modern SSDs)
        - busy_timeout=5000: 5s busy timeout instead of immediate fail
        - auto_vacuum=INCREMENTAL: Incremental auto-vacuum
        - wal_autocheckpoint=1000: Checkpoint every 1000 pages (reduced checkpoint frequency)
        - optimize: Analyze query planner statistics for better performance
        - analysis_limit=400: Limit ANALYZE to 400 rows (faster, good enough)
        - threads=4: Enable parallel query execution
        """
        if not self._db:
            raise RuntimeError("Database connection not initialized")

        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA cache_size=-16000")  # 16MB cache (up from 8MB)
        await self._db.execute("PRAGMA temp_store=MEMORY")
        await self._db.execute("PRAGMA mmap_size=134217728")  # 128MB mmap (up from 64MB)
        await self._db.execute("PRAGMA page_size=4096")  # 4KB pages for SSD
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        await self._db.execute("PRAGMA wal_autocheckpoint=1000")  # Less frequent checkpoints
        await self._db.execute("PRAGMA analysis_limit=400")  # Faster ANALYZE
        await self._db.execute("PRAGMA threads=4")  # Parallel queries

        # Run OPTIMIZE to update query planner statistics
        await self._db.execute("PRAGMA optimize")

        log.info("SQLite PRAGMAs applied (WAL, 16MB cache, 128MB mmap, 4 threads, optimized)")

    async def _run_migrations(self) -> None:
        """
        Apply schema and run migrations.

        This method:
        1. Executes SCHEMA_SQL to create all tables
        2. Runs safe ADD COLUMN migrations from _MIGRATIONS
        3. Creates post-migration indexes
        4. Backfills LLM confidence from reasoning JSON
        5. Backfills LLM stance from reasoning JSON
        6. Backfills LLM event_type from reasoning JSON
        7. Clears old win_rate_snapshots (uses broken evaluation logic)
        8. Archives existing resolved signals into signal_archive

        All migrations are wrapped in try/except to be idempotent and safe
        to run multiple times.
        """
        if not self._db:
            raise RuntimeError("Database connection not initialized")

        # Create schema
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()

        # Safe migrations: add columns that may not exist yet
        for table, column, col_type in _MIGRATIONS:
            try:
                await self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                await self._db.commit()
                log.info("Migration: added %s.%s", table, column)
            except Exception:
                pass  # column already exists

        # Post-migration indexes: these reference columns added by _MIGRATIONS
        _POST_MIGRATION_INDEXES = [
            "CREATE INDEX IF NOT EXISTS idx_signals_sector ON signals(sector)",
            "CREATE INDEX IF NOT EXISTS idx_signals_sarcasm ON signals(sarcasm_score)",
            "CREATE INDEX IF NOT EXISTS idx_signals_conviction ON signals(conviction)",
            "CREATE INDEX IF NOT EXISTS idx_signals_nlp_polarity ON signals(nlp_polarity)",
        ]
        for idx_sql in _POST_MIGRATION_INDEXES:
            try:
                await self._db.execute(idx_sql)
            except Exception:
                pass  # column may not exist yet on very old DBs
        await self._db.commit()

        # One-time backfill: update stored confidence from LLM-calibrated value
        # where reasoning JSON contains raw.confidence that differs from the heuristic
        try:
            await self._db.execute(
                """UPDATE signals SET confidence = CAST(
                       json_extract(reasoning, '$.raw.confidence') AS REAL
                   )
                   WHERE json_extract(reasoning, '$.raw.confidence') IS NOT NULL
                     AND json_extract(reasoning, '$.raw.error') IS NULL
                     AND json_extract(reasoning, '$.raw.stub') IS NULL
                     AND ABS(confidence - CAST(json_extract(reasoning, '$.raw.confidence') AS REAL)) > 0.01"""
            )
            changes = self._db.total_changes
            await self._db.commit()
            log.info("Migration: backfilled LLM confidence for existing signals (rows affected: %d)", changes)
        except Exception as e:
            log.warning("LLM confidence backfill skipped: %s", e)

        # Backfill LLM stance from reasoning JSON — fixes the root cause of
        # anti-correlated win rates (EventBuilder regex stance was stored instead
        # of LLM's calibrated stance).
        try:
            cursor = await self._db.execute(
                """UPDATE signals SET stance = json_extract(reasoning, '$.raw.stance')
                   WHERE json_extract(reasoning, '$.raw.stance') IS NOT NULL
                     AND json_extract(reasoning, '$.raw.error') IS NULL
                     AND json_extract(reasoning, '$.raw.stub') IS NULL
                     AND json_extract(reasoning, '$.raw.stance') IN ('bullish', 'bearish', 'mixed', 'unknown')
                     AND stance != json_extract(reasoning, '$.raw.stance')"""
            )
            stance_changes = cursor.rowcount
            await self._db.commit()
            log.info("Migration: backfilled LLM stance for %d signals", stance_changes)
        except Exception as e:
            log.warning("LLM stance backfill skipped: %s", e)

        # Backfill LLM event_type from reasoning JSON
        try:
            cursor = await self._db.execute(
                """UPDATE signals SET event_type = json_extract(reasoning, '$.raw.event_type')
                   WHERE json_extract(reasoning, '$.raw.event_type') IS NOT NULL
                     AND json_extract(reasoning, '$.raw.error') IS NULL
                     AND json_extract(reasoning, '$.raw.stub') IS NULL
                     AND json_extract(reasoning, '$.raw.event_type') IN (
                         'earnings_rumor', 'product_news', 'regulatory',
                         'squeeze_chatter', 'macro', 'other'
                     )
                     AND event_type != json_extract(reasoning, '$.raw.event_type')"""
            )
            et_changes = cursor.rowcount
            await self._db.commit()
            log.info("Migration: backfilled LLM event_type for %d signals", et_changes)
        except Exception as e:
            log.warning("LLM event_type backfill skipped: %s", e)

        # Clear old win_rate_snapshots since they used broken evaluation logic.
        # They'll be re-generated on the next purge cycle with correct stance-aware SQL.
        try:
            cursor = await self._db.execute("DELETE FROM win_rate_snapshots")
            snap_deleted = cursor.rowcount
            await self._db.commit()
            if snap_deleted > 0:
                log.info("Migration: cleared %d old win_rate_snapshots (will regenerate with stance-aware logic)", snap_deleted)
        except Exception as e:
            log.warning("win_rate_snapshots clear skipped: %s", e)

        # One-time: archive existing resolved signals into signal_archive
        # so backtests + analytics can see data beyond 14-day purge window
        try:
            cursor = await self._db.execute("""
                INSERT OR IGNORE INTO signal_archive
                    (id, created_at, ticker, event_type, stance, strategy,
                     confidence, subreddit, quality_score, sector, post_title,
                     price_at_signal, price_1h, price_4h, price_1d,
                     max_gain_pct, max_loss_pct, archived_at)
                SELECT
                    s.id, s.created_at, s.ticker, s.event_type, s.stance, s.strategy,
                    s.confidence, s.subreddit, s.quality_score, s.sector, s.post_title,
                    sp.price_at_signal, sp.price_1h, sp.price_4h, sp.price_1d,
                    sp.max_gain_pct, sp.max_loss_pct, ?
                FROM signals s
                JOIN signal_performance sp ON sp.signal_id = s.id
                WHERE sp.price_at_signal > 0
                  AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
            """, (time.time(),))
            if cursor.rowcount > 0:
                await self._db.commit()
                log.info("Migration: archived %d existing signals to signal_archive", cursor.rowcount)
        except Exception as e:
            log.warning("Initial signal archive migration skipped: %s", e)

        # Initialize gamification tables if they exist (via GamificationMixin)
        if hasattr(self, '_init_gamification_tables'):
            try:
                await self._init_gamification_tables()
                log.info("Gamification tables initialized")
            except Exception as e:
                log.warning("Gamification tables init skipped: %s", e)

        # Initialize sports tables (via SportsMixin)
        if hasattr(self, '_create_sports_tables'):
            try:
                await self._create_sports_tables()
                log.info("Sports betting tables initialized")
            except Exception as e:
                log.warning("Sports betting tables init skipped: %s", e)

        # Initialize affiliates tables (via AffiliatesMixin)
        if hasattr(self, '_init_affiliates_tables'):
            try:
                await self._init_affiliates_tables()
                log.info("Affiliates tables initialized")
            except Exception as e:
                log.warning("Affiliates tables init skipped: %s", e)

    async def close(self) -> None:
        """
        Close the database connection.

        Runs PRAGMA optimize before closing to update query planner statistics.
        This improves query performance on the next connection.
        """
        if self._db:
            try:
                await self._db.execute("PRAGMA optimize")  # Optimize query planner stats
            except Exception:
                pass  # Intentionally suppressed
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        """
        Get the database connection.

        Returns:
            aiosqlite.Connection: The active database connection

        Raises:
            RuntimeError: If connect() hasn't been called yet
        """
        if not self._db:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    async def execute_fetchone(self, sql: str, parameters: tuple = ()):
        """Execute SQL and fetch one row."""
        cursor = await self.db.execute(sql, parameters)
        return await cursor.fetchone()

    async def execute_fetchall(self, sql: str, parameters: tuple = ()):
        """Execute SQL and fetch all rows."""
        cursor = await self.db.execute(sql, parameters)
        return await cursor.fetchall()
