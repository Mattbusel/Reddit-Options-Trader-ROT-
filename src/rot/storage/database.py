from __future__ import annotations

import json
import uuid
import time
import logging
import aiosqlite
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Stance-aware win/loss SQL helpers ──
# Only bullish and bearish signals count as trades for win/loss evaluation.
# Mixed and unknown stances are always neutral (no directional bet to evaluate).
# Use {price_col} as placeholder for the evaluated price column expression.

_WIN_CASE_SQL = """
    CASE
        /* bullish: price went up >0.5% */
        WHEN s.stance = 'bullish'
             AND ({price_col} - sp.price_at_signal) / sp.price_at_signal > 0.005
        THEN 1
        /* bearish: price went down >0.5% */
        WHEN s.stance = 'bearish'
             AND (sp.price_at_signal - {price_col}) / sp.price_at_signal > 0.005
        THEN 1
        /* mixed/unknown: always 0 (no directional bet) */
        ELSE 0
    END"""

_LOSS_CASE_SQL = """
    CASE
        /* bullish: price went down >0.5% */
        WHEN s.stance = 'bullish'
             AND (sp.price_at_signal - {price_col}) / sp.price_at_signal > 0.005
        THEN 1
        /* bearish: price went up >0.5% */
        WHEN s.stance = 'bearish'
             AND ({price_col} - sp.price_at_signal) / sp.price_at_signal > 0.005
        THEN 1
        /* mixed/unknown: always 0 (no directional bet) */
        ELSE 0
    END"""

_NEUTRAL_CASE_SQL = """
    CASE
        /* unknown/mixed stance: always neutral */
        WHEN COALESCE(s.stance, 'unknown') IN ('unknown', 'mixed') THEN 1
        /* directional: price within 0.5% = noise */
        WHEN s.stance IN ('bullish', 'bearish')
             AND ABS({price_col} - sp.price_at_signal) / sp.price_at_signal <= 0.005
        THEN 1
        ELSE 0
    END"""

# Pre-formatted with the standard COALESCE price column
_PRICE_COL = "COALESCE(sp.price_1d, sp.price_4h, sp.price_1h)"
_WIN_SQL = _WIN_CASE_SQL.format(price_col=_PRICE_COL)
_LOSS_SQL = _LOSS_CASE_SQL.format(price_col=_PRICE_COL)
_NEUTRAL_SQL = _NEUTRAL_CASE_SQL.format(price_col=_PRICE_COL)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'other',
    stance TEXT NOT NULL DEFAULT 'unknown',
    time_horizon TEXT NOT NULL DEFAULT 'unknown',
    confidence REAL NOT NULL DEFAULT 0.0,
    trend_score REAL NOT NULL DEFAULT 0.0,
    quality_score REAL NOT NULL DEFAULT 0.0,
    strategy TEXT NOT NULL DEFAULT 'none',
    subreddit TEXT NOT NULL DEFAULT '',
    post_title TEXT NOT NULL DEFAULT '',
    post_url TEXT NOT NULL DEFAULT '',
    market_data TEXT NOT NULL DEFAULT '{}',
    reasoning TEXT NOT NULL DEFAULT '{}',
    trade_idea TEXT NOT NULL DEFAULT '{}',
    event_data TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_confidence ON signals(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_signals_stance ON signals(stance);
CREATE INDEX IF NOT EXISTS idx_signals_dedup ON signals(post_url, ticker, created_at);
CREATE INDEX IF NOT EXISTS idx_signals_event_type ON signals(event_type);
CREATE INDEX IF NOT EXISTS idx_signals_strategy ON signals(strategy);

CREATE TABLE IF NOT EXISTS signal_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL REFERENCES signals(id),
    ticker TEXT NOT NULL,
    price_at_signal REAL,
    price_1h REAL,
    price_4h REAL,
    price_1d REAL,
    price_1w REAL,
    max_gain_pct REAL,
    max_loss_pct REAL,
    checked_at REAL
);

CREATE INDEX IF NOT EXISTS idx_perf_signal ON signal_performance(signal_id);
CREATE INDEX IF NOT EXISTS idx_perf_ticker ON signal_performance(ticker);
CREATE INDEX IF NOT EXISTS idx_perf_checked ON signal_performance(checked_at);
CREATE INDEX IF NOT EXISTS idx_signals_created_ticker ON signals(created_at DESC, ticker);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',
    api_key_hash TEXT UNIQUE,
    tier TEXT NOT NULL DEFAULT 'free',
    created_at REAL NOT NULL,
    settings TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key_hash);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    called_at REAL NOT NULL,
    ip_address TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_api_usage_user_day ON api_usage(user_id, called_at);

CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL REFERENCES users(id),
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    tier TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'active',
    current_period_end REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe ON subscriptions(stripe_subscription_id);

CREATE TABLE IF NOT EXISTS email_alert_settings (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    enabled INTEGER NOT NULL DEFAULT 0,
    digest_enabled INTEGER NOT NULL DEFAULT 1,
    realtime_enabled INTEGER NOT NULL DEFAULT 0,
    min_confidence REAL NOT NULL DEFAULT 0.6,
    tickers TEXT NOT NULL DEFAULT '[]',
    stances TEXT NOT NULL DEFAULT '[]',
    event_types TEXT NOT NULL DEFAULT '[]',
    last_digest_at REAL NOT NULL DEFAULT 0,
    webhook_url TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS x_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    tweet_id TEXT NOT NULL DEFAULT '',
    tweet_text TEXT NOT NULL DEFAULT '',
    posted_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_x_posts_posted ON x_posts(posted_at DESC);

CREATE TABLE IF NOT EXISTS referral_clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_code TEXT NOT NULL,
    ip_address TEXT NOT NULL DEFAULT '',
    clicked_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_referral_clicks_code ON referral_clicks(ref_code);

CREATE TABLE IF NOT EXISTS referral_conversions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_code TEXT NOT NULL,
    referred_user_id TEXT NOT NULL,
    converted_at REAL NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free',
    commission_amount REAL NOT NULL DEFAULT 0.0,
    paid_out INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_referral_conv_code ON referral_conversions(ref_code);

CREATE TABLE IF NOT EXISTS sponsored_signals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT '',
    ticker TEXT NOT NULL DEFAULT '',
    press_url TEXT NOT NULL DEFAULT '',
    press_content TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    signal_id TEXT DEFAULT NULL,
    created_at REAL NOT NULL,
    analyzed_at REAL DEFAULT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sponsored_user ON sponsored_signals(user_id);
CREATE INDEX IF NOT EXISTS idx_sponsored_status ON sponsored_signals(status);
CREATE INDEX IF NOT EXISTS idx_sponsored_created ON sponsored_signals(created_at DESC);

CREATE TABLE IF NOT EXISTS data_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    export_type TEXT NOT NULL DEFAULT 'signals',
    format TEXT NOT NULL DEFAULT 'csv',
    requested_at REAL NOT NULL,
    completed_at REAL DEFAULT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    filters TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_data_exports_user ON data_exports(user_id);

CREATE TABLE IF NOT EXISTS paper_portfolios (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    balance REAL NOT NULL DEFAULT 10000.0,
    initial_balance REAL NOT NULL DEFAULT 10000.0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    winning_trades INTEGER NOT NULL DEFAULT 0,
    total_pnl REAL NOT NULL DEFAULT 0.0,
    last_trade_at REAL
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    signal_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    stance TEXT NOT NULL DEFAULT 'unknown',
    entry_price REAL NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    paper_balance_after REAL NOT NULL,
    created_at REAL NOT NULL,
    closed_at REAL,
    exit_price REAL,
    pnl_dollars REAL,
    pnl_pct REAL,
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_user ON paper_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);

CREATE TABLE IF NOT EXISTS win_rate_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at REAL NOT NULL,
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,
    winners INTEGER NOT NULL DEFAULT 0,
    losers INTEGER NOT NULL DEFAULT 0,
    neutral INTEGER NOT NULL DEFAULT 0,
    total_tracked INTEGER NOT NULL DEFAULT 0,
    avg_gain_pct REAL,
    avg_loss_pct REAL,
    avg_1d_return_pct REAL
);

CREATE INDEX IF NOT EXISTS idx_wr_snapshot_at ON win_rate_snapshots(snapshot_at DESC);

CREATE TABLE IF NOT EXISTS congress_trades (
    id TEXT PRIMARY KEY,
    politician TEXT NOT NULL DEFAULT '',
    party TEXT NOT NULL DEFAULT '',
    chamber TEXT NOT NULL DEFAULT '',
    ticker TEXT NOT NULL DEFAULT '',
    trade_type TEXT NOT NULL DEFAULT '',
    amount_range TEXT NOT NULL DEFAULT '',
    filed_at REAL NOT NULL,
    disclosure_date TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_congress_ticker ON congress_trades(ticker);
CREATE INDEX IF NOT EXISTS idx_congress_filed ON congress_trades(filed_at DESC);
CREATE INDEX IF NOT EXISTS idx_congress_politician ON congress_trades(politician);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    monte_carlo_json TEXT NOT NULL DEFAULT '{}',
    risk_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_user ON backtest_runs(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS backtest_strategies (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    last_result_json TEXT NOT NULL DEFAULT '{}',
    last_run_at REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_backtest_strats_user ON backtest_strategies(user_id, is_active, created_at DESC);

CREATE TABLE IF NOT EXISTS unusual_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.0,
    details_json TEXT NOT NULL DEFAULT '{}',
    signal_id TEXT DEFAULT NULL,
    detected_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_unusual_ticker ON unusual_events(ticker);
CREATE INDEX IF NOT EXISTS idx_unusual_type ON unusual_events(event_type);
CREATE INDEX IF NOT EXISTS idx_unusual_detected ON unusual_events(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_unusual_score ON unusual_events(score DESC);
CREATE INDEX IF NOT EXISTS idx_unusual_signal ON unusual_events(signal_id);
"""

# Columns to add to existing tables (migration-safe)
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


class Database:
    def __init__(self, db_path: str = "storage/rot.db") -> None:
        self.db_path = Path(db_path)
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row

        # SQLite performance optimizations
        await self._db.execute("PRAGMA journal_mode=WAL")       # Write-Ahead Logging for concurrent reads
        await self._db.execute("PRAGMA synchronous=NORMAL")     # Faster writes, safe with WAL
        await self._db.execute("PRAGMA cache_size=-8000")       # 8MB page cache (default 2MB)
        await self._db.execute("PRAGMA temp_store=MEMORY")      # Keep temp tables in memory
        await self._db.execute("PRAGMA mmap_size=67108864")     # 64MB memory-mapped I/O
        await self._db.execute("PRAGMA busy_timeout=5000")      # 5s busy timeout instead of immediate fail
        await self._db.execute("PRAGMA auto_vacuum=INCREMENTAL") # Incremental auto-vacuum
        await self._db.execute("PRAGMA wal_autocheckpoint=500")  # Checkpoint every 500 pages (shrink WAL file)
        log.info("SQLite PRAGMAs applied (WAL, 8MB cache, 64MB mmap, incremental auto_vacuum)")

        await self._db.executescript(_SCHEMA)
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

    async def close(self) -> None:
        if self._db:
            try:
                await self._db.execute("PRAGMA optimize")  # Optimize query planner stats
            except Exception:
                pass
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if not self._db:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    # ── Signal CRUD ──

    async def insert_signal(self, signal_data: Dict[str, Any]) -> Optional[str]:
        signal_id = str(uuid.uuid4())[:12]
        now = time.time()

        event = signal_data.get("event")
        reasoning = signal_data.get("reasoning")
        trade_idea = signal_data.get("trade_idea")

        # Extract fields from dataclass-like objects
        event_dict = _to_dict(event) if event else {}
        reasoning_dict = _to_dict(reasoning) if reasoning else {}
        idea_dict = _to_dict(trade_idea) if trade_idea else {}

        entities = event_dict.get("entities", [])
        ticker = entities[0] if entities else "UNKNOWN"
        evidence = event_dict.get("evidence", [{}])
        first_evidence = evidence[0] if evidence else {}
        meta = event_dict.get("meta", {})

        # Dedup: skip if signal for same (post_url, ticker) exists in last 24h
        post_url = first_evidence.get("permalink", "")
        if post_url and ticker != "UNKNOWN":
            cutoff = now - 86400
            async with self.db.execute(
                "SELECT id FROM signals WHERE post_url = ? AND ticker = ? AND created_at > ? LIMIT 1",
                (post_url, ticker, cutoff),
            ) as cursor:
                if await cursor.fetchone():
                    return None  # Duplicate, skip

        # Extract sector from market data if available
        market = meta.get("market", {})
        sector = ""
        if isinstance(market, dict) and ticker in market:
            ticker_market = market[ticker]
            if isinstance(ticker_market, dict):
                sector = ticker_market.get("sector", "")

        # Compute expires_at from time_horizon
        time_horizon = event_dict.get("time_horizon", "unknown")
        _HORIZON_SECONDS = {
            "intraday": 86400,      # 1 day
            "1w": 7 * 86400,        # 1 week
            "earnings": 14 * 86400, # 2 weeks
            "1m": 30 * 86400,       # 1 month
            "swing": 14 * 86400,    # 2 weeks
        }
        horizon_ttl = _HORIZON_SECONDS.get(time_horizon, 14 * 86400)  # default 14 days
        expires_at = now + horizon_ttl

        # Extract author credibility metadata
        author = first_evidence.get("author", meta.get("author", ""))
        author_karma = meta.get("author_karma", 0) or 0
        author_age_days = meta.get("author_age_days", 0) or 0

        # Extract NLP engine metrics
        nlp = meta.get("nlp", {})
        sarcasm_score = nlp.get("sarcasm_probability", 0.0) if isinstance(nlp, dict) else 0.0
        conviction_val = nlp.get("conviction", 0.5) if isinstance(nlp, dict) else 0.5
        consensus_val = nlp.get("thread_consensus", 0.0) if isinstance(nlp, dict) else 0.0
        actionability_val = nlp.get("actionability", 0.5) if isinstance(nlp, dict) else 0.5
        nlp_polarity_val = nlp.get("polarity", 0.0) if isinstance(nlp, dict) else 0.0

        await self.db.execute(
            """INSERT INTO signals
               (id, run_id, created_at, ticker, event_type, stance, time_horizon,
                confidence, trend_score, quality_score, strategy,
                subreddit, post_title, post_url,
                market_data, reasoning, trade_idea, event_data, sector,
                expires_at, author, author_karma, author_age_days,
                sarcasm_score, conviction, consensus_score, actionability, nlp_polarity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?)""",
            (
                signal_id,
                signal_data.get("run_id", ""),
                now,
                ticker,
                event_dict.get("event_type", "other"),
                event_dict.get("stance", "unknown"),
                time_horizon,
                event_dict.get("confidence", 0.0),
                meta.get("trend_score", 0.0),
                idea_dict.get("quality_score", 0.0),
                idea_dict.get("strategy", "none"),
                first_evidence.get("subreddit", ""),
                first_evidence.get("excerpt", ""),
                first_evidence.get("permalink", ""),
                json.dumps(market),
                json.dumps(reasoning_dict),
                json.dumps(idea_dict),
                json.dumps(event_dict),
                sector,
                expires_at,
                author,
                author_karma,
                author_age_days,
                sarcasm_score,
                conviction_val,
                consensus_val,
                actionability_val,
                nlp_polarity_val,
            ),
        )
        await self.db.commit()
        return signal_id

    async def get_signals(
        self,
        limit: int = 50,
        offset: int = 0,
        ticker: Optional[str] = None,
        stance: Optional[str] = None,
        min_confidence: Optional[float] = None,
        event_type: Optional[str] = None,
        date_from: Optional[float] = None,
        date_to: Optional[float] = None,
        source: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        conditions = []
        params: list = []

        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker.upper())
        if stance:
            conditions.append("stance = ?")
            params.append(stance)
        if min_confidence is not None:
            conditions.append("confidence >= ?")
            params.append(min_confidence)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if date_from is not None:
            conditions.append("created_at >= ?")
            params.append(date_from)
        if date_to is not None:
            conditions.append("created_at <= ?")
            params.append(date_to)

        # Source filter: supports group values and exact subreddit/label matches
        if source:
            if source == "defense":
                # Defense/DoD: signals from DoD RSS feeds only
                # Don't include Reddit signals just because they mention defense tickers
                conditions.append(
                    "subreddit IN ('dod-contracts', 'dod-releases', 'dod-news')"
                )
            elif source == "pharma":
                # Pharma/FDA: signals from FDA/pharma RSS feeds only
                conditions.append(
                    "subreddit IN ('fda-press-releases', 'fda-drugs', 'fda-safety-alerts',"
                    " 'fda-recalls', 'fda-oncology', 'biopharma-dive',"
                    " 'drugs-com-approvals', 'drugs-com-trials')"
                )
            elif source == "reddit":
                conditions.append(
                    "subreddit IN ('wallstreetbets','options','stocks','investing',"
                    "'thetagang','stockmarket','smallstreetbets')"
                )
            elif source == "rss":
                conditions.append("json_extract(event_data, '$.flair') = 'rss'")
            else:
                # Exact match: stocktwits, twitter, specific feed label, etc.
                conditions.append("subreddit = ?")
                params.append(source)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM signals {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_signal(self, signal_id: str) -> Optional[Dict[str, Any]]:
        async with self.db.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    async def update_signal_reasoning(self, signal_id: str, reasoning: Dict[str, Any]) -> None:
        """Update a signal's reasoning JSON (used by BYOK re-analysis)."""
        await self.db.execute(
            "UPDATE signals SET reasoning = ? WHERE id = ?",
            (json.dumps(reasoning), signal_id),
        )
        await self.db.commit()

    async def update_signal_fields(self, signal_id: str, fields: Dict[str, Any]) -> None:
        """Update arbitrary columns on a signal row."""
        if not fields:
            return
        allowed = {"confidence", "stance", "event_type", "strategy", "time_horizon"}
        safe_fields = {k: v for k, v in fields.items() if k in allowed}
        if not safe_fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in safe_fields)
        params = list(safe_fields.values()) + [signal_id]
        await self.db.execute(f"UPDATE signals SET {set_clause} WHERE id = ?", params)
        await self.db.commit()

    async def get_trending_tickers(self, hours: int = 24, limit: int = 20) -> List[Dict[str, Any]]:
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT ticker,
                   COUNT(*) as signal_count,
                   AVG(confidence) as avg_confidence,
                   MAX(trend_score) as max_trend_score,
                   GROUP_CONCAT(DISTINCT stance) as stances,
                   MAX(created_at) as latest_at
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            GROUP BY ticker
            ORDER BY signal_count DESC, avg_confidence DESC
            LIMIT ?
        """
        async with self.db.execute(query, (cutoff, limit)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_signal_count(self) -> int:
        async with self.db.execute("SELECT COUNT(*) FROM signals") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_performance_summary(self, days: int = 30) -> Dict[str, Any]:
        cutoff = time.time() - (days * 86400)
        now = time.time()
        cutoff_24h = now - 86400
        cutoff_7d = now - 7 * 86400
        query = """
            SELECT
                COUNT(*) as total_signals,
                AVG(confidence) as avg_confidence,
                SUM(CASE WHEN stance IN ('bullish', 'bearish') THEN 1 ELSE 0 END) as tradeable_signals,
                SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish_count,
                SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish_count,
                SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed_count,
                SUM(CASE WHEN created_at > ? THEN 1 ELSE 0 END) as signals_today,
                SUM(CASE WHEN created_at > ? THEN 1 ELSE 0 END) as signals_7d,
                SUM(CASE WHEN confidence >= 0.5 THEN 1 ELSE 0 END) as high_conf_count,
                SUM(CASE WHEN strategy = 'debit_spread' THEN 1
                         WHEN strategy = 'credit_spread' THEN 1
                         WHEN strategy = 'long_call' OR strategy = 'long_put' THEN 1
                         ELSE 0 END) as _strat_dummy,
                COUNT(DISTINCT ticker) as unique_tickers,
                COUNT(DISTINCT subreddit) as unique_sources
            FROM signals
            WHERE created_at > ?
        """
        async with self.db.execute(query, (cutoff_24h, cutoff_7d, cutoff)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {"total_signals": 0}
            d = _row_to_dict(row)
            total = d.get("total_signals", 0) or 0
            d["daily_avg"] = round(total / max(days, 1), 1)
            return d

    async def get_strategy_breakdown(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get top strategies by count for the stat card."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT strategy, COUNT(*) as cnt
            FROM signals
            WHERE created_at > ? AND strategy != 'none' AND strategy != ''
            GROUP BY strategy
            ORDER BY cnt DESC
            LIMIT 4
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(r) for r in rows]

    # ── Chart Data ──

    async def get_chart_data(self, hours: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
        """Aggregated ticker data for quadrant bubble chart."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                ticker,
                AVG(confidence) as avg_confidence,
                MAX(trend_score) as max_trend_score,
                COUNT(*) as signal_count,
                SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish_count,
                SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish_count,
                SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed_count,
                GROUP_CONCAT(DISTINCT strategy) as strategies
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            GROUP BY ticker
            HAVING signal_count > 0
            ORDER BY signal_count DESC, avg_confidence DESC
            LIMIT ?
        """
        async with self.db.execute(query, (cutoff, limit)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                # Determine dominant stance
                bc = d.get("bullish_count", 0) or 0
                brc = d.get("bearish_count", 0) or 0
                mc = d.get("mixed_count", 0) or 0
                if bc >= brc and bc >= mc:
                    d["dominant_stance"] = "bullish"
                elif brc > bc and brc >= mc:
                    d["dominant_stance"] = "bearish"
                else:
                    d["dominant_stance"] = "mixed"
                results.append(d)
            return results

    async def get_time_series_data(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Hourly signal counts for timeline chart."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                CAST(created_at / 3600 AS INTEGER) * 3600 as hour_bucket,
                COUNT(*) as total,
                SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed
            FROM signals
            WHERE created_at > ?
            GROUP BY hour_bucket
            ORDER BY hour_bucket ASC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    # ── User CRUD ──

    async def create_user(self, email: str, password_hash: str) -> Dict[str, Any]:
        user_id = str(uuid.uuid4())[:12]
        now = time.time()
        await self.db.execute(
            "INSERT INTO users (id, email, password_hash, tier, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, email, password_hash, "free", now),
        )
        await self.db.commit()
        return {"id": user_id, "email": email, "tier": "free", "created_at": now, "settings": {}}

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        async with self.db.execute("SELECT * FROM users WHERE email = ?", (email,)) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        async with self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    async def get_user_by_api_key_hash(self, api_key_hash: str) -> Optional[Dict[str, Any]]:
        async with self.db.execute(
            "SELECT * FROM users WHERE api_key_hash = ?", (api_key_hash,)
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    async def update_user_tier(self, user_id: str, tier: str) -> None:
        await self.db.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user_id))
        await self.db.commit()

    async def set_user_api_key(self, user_id: str, api_key_hash: str) -> None:
        await self.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?", (api_key_hash, user_id)
        )
        await self.db.commit()

    async def update_user_password(self, user_id: str, password_hash: str) -> None:
        """Update a user's password hash."""
        await self.db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
        )
        await self.db.commit()

    async def update_user_settings(self, user_id: str, settings: Dict[str, Any]) -> None:
        await self.db.execute(
            "UPDATE users SET settings = ? WHERE id = ?", (json.dumps(settings), user_id)
        )
        await self.db.commit()

    # ── Rate Limiting ──

    async def record_api_call(self, user_id: str, endpoint: str, ip: str = "") -> None:
        await self.db.execute(
            "INSERT INTO api_usage (user_id, endpoint, called_at, ip_address) VALUES (?, ?, ?, ?)",
            (user_id, endpoint, time.time(), ip),
        )
        await self.db.commit()

    async def get_api_call_count(self, user_id: str, since: float) -> int:
        async with self.db.execute(
            "SELECT COUNT(*) FROM api_usage WHERE user_id = ? AND called_at > ?",
            (user_id, since),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def cleanup_old_api_usage(self, older_than_s: int = 172800) -> int:
        cutoff = time.time() - older_than_s
        async with self.db.execute(
            "DELETE FROM api_usage WHERE called_at < ?", (cutoff,)
        ) as cursor:
            count = cursor.rowcount
        await self.db.commit()
        return count

    async def cleanup_old_signals(self, older_than_s: int = 90 * 86400) -> int:
        """Delete signals older than older_than_s seconds (default 90 days)."""
        cutoff = time.time() - older_than_s
        async with self.db.execute(
            "DELETE FROM signals WHERE created_at < ?", (cutoff,)
        ) as cursor:
            count = cursor.rowcount
        await self.db.commit()
        return count

    # ── Subscriptions ──

    async def upsert_subscription(self, user_id: str, data: Dict[str, Any]) -> None:
        now = time.time()
        existing = await self.get_subscription(user_id)
        if existing:
            await self.db.execute(
                """UPDATE subscriptions SET
                    stripe_customer_id = ?, stripe_subscription_id = ?,
                    tier = ?, status = ?, current_period_end = ?, updated_at = ?
                   WHERE user_id = ?""",
                (
                    data.get("stripe_customer_id", existing.get("stripe_customer_id")),
                    data.get("stripe_subscription_id", existing.get("stripe_subscription_id")),
                    data.get("tier", existing.get("tier")),
                    data.get("status", existing.get("status")),
                    data.get("current_period_end", existing.get("current_period_end")),
                    now,
                    user_id,
                ),
            )
        else:
            sub_id = str(uuid.uuid4())[:12]
            await self.db.execute(
                """INSERT INTO subscriptions
                   (id, user_id, stripe_customer_id, stripe_subscription_id,
                    tier, status, current_period_end, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sub_id,
                    user_id,
                    data.get("stripe_customer_id", ""),
                    data.get("stripe_subscription_id", ""),
                    data.get("tier", "free"),
                    data.get("status", "active"),
                    data.get("current_period_end"),
                    now,
                    now,
                ),
            )
        await self.db.commit()

    async def get_subscription(self, user_id: str) -> Optional[Dict[str, Any]]:
        async with self.db.execute(
            "SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    async def get_subscription_by_stripe_id(
        self, stripe_subscription_id: str
    ) -> Optional[Dict[str, Any]]:
        async with self.db.execute(
            "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?",
            (stripe_subscription_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None


    # ── Signal Performance (Price Tracking) ──

    async def insert_signal_performance(
        self, signal_id: str, ticker: str, price_at_signal: float
    ) -> None:
        """Record initial price when a signal is first created."""
        now = time.time()
        await self.db.execute(
            """INSERT INTO signal_performance
               (signal_id, ticker, price_at_signal, created_at, checked_at)
               VALUES (?, ?, ?, ?, ?)""",
            (signal_id, ticker, price_at_signal, now, now),
        )
        await self.db.commit()

    async def get_unchecked_performances(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Find performance records that still need price updates."""
        query = """
            SELECT sp.*, s.created_at as signal_created_at, s.stance as signal_stance
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE sp.price_1h IS NULL OR sp.price_4h IS NULL
                  OR sp.price_1d IS NULL OR sp.price_1w IS NULL
            ORDER BY s.created_at ASC
            LIMIT ?
        """
        async with self.db.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                # Use signal_created_at for age calculation
                if d.get("signal_created_at"):
                    d["created_at"] = d["signal_created_at"]
                results.append(d)
            return results

    async def update_performance_prices(
        self, perf_id: int, updates: Dict[str, Any]
    ) -> None:
        """Update price columns for a performance record."""
        set_clauses = []
        params = []
        for col in ("price_1h", "price_4h", "price_1d", "price_1w",
                     "max_gain_pct", "max_loss_pct", "checked_at"):
            if col in updates:
                set_clauses.append(f"{col} = ?")
                params.append(updates[col])
        if not set_clauses:
            return
        params.append(perf_id)
        query = f"UPDATE signal_performance SET {', '.join(set_clauses)} WHERE id = ?"
        await self.db.execute(query, params)
        await self.db.commit()

    async def get_performance_for_signal(
        self, signal_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get performance record for a specific signal."""
        async with self.db.execute(
            "SELECT * FROM signal_performance WHERE signal_id = ?", (signal_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None

    async def recalculate_stance_aware_gains(self) -> int:
        """One-time recalculation of max_gain_pct/max_loss_pct with stance awareness.

        Fixes old records that were calculated without considering signal stance.
        """
        query = """
            SELECT sp.id, sp.price_at_signal, sp.price_1h, sp.price_4h,
                   sp.price_1d, sp.price_1w, s.stance
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE sp.price_at_signal > 0
              AND (sp.price_1h IS NOT NULL OR sp.price_4h IS NOT NULL
                   OR sp.price_1d IS NOT NULL OR sp.price_1w IS NOT NULL)
        """
        updated = 0
        async with self.db.execute(query) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                d = dict(row)
                price_at = d["price_at_signal"]
                stance = d.get("stance", "bullish")
                tracked = []
                for key in ("price_1h", "price_4h", "price_1d", "price_1w"):
                    if d.get(key) is not None:
                        tracked.append(d[key])
                if not tracked:
                    continue
                raw_pcts = [(p / price_at - 1.0) * 100 for p in tracked]
                if stance == "bearish":
                    pcts = [-pct for pct in raw_pcts]
                else:
                    pcts = raw_pcts
                new_gain = max(pcts)
                new_loss = min(pcts)
                await self.db.execute(
                    "UPDATE signal_performance SET max_gain_pct = ?, max_loss_pct = ? WHERE id = ?",
                    (new_gain, new_loss, d["id"]),
                )
                updated += 1
        if updated > 0:
            await self.db.commit()
            log.info("Recalculated stance-aware gains for %d performance records", updated)
        return updated

    async def get_aggregate_accuracy(
        self, days: int = 7, ticker: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get aggregate win/loss stats for signal performance.

        Uses the best available price snapshot (1d > 4h > 1h) for evaluation.
        Applies a 0.5% minimum movement threshold — price changes below
        this are classified as neutral (noise within bid-ask spread).
        """
        cutoff = time.time() - (days * 86400)
        conditions = ["s.created_at > ?"]
        params: list = [cutoff]

        if ticker:
            conditions.append("sp.ticker = ?")
            params.append(ticker.upper())

        where = f"WHERE {' AND '.join(conditions)}"
        # Stance-aware win/loss evaluation: bullish/bearish only
        query = f"""
            SELECT
                COUNT(*) as total_tracked,
                SUM({_WIN_SQL}) as winners,
                SUM({_LOSS_SQL}) as losers,
                SUM({_NEUTRAL_SQL}) as neutral,
                AVG(sp.max_gain_pct) as avg_gain_pct,
                AVG(sp.max_loss_pct) as avg_loss_pct,
                AVG(CASE WHEN sp.price_1d IS NOT NULL
                    THEN CASE WHEN s.stance = 'bearish'
                        THEN (1.0 - sp.price_1d / sp.price_at_signal) * 100
                        ELSE (sp.price_1d / sp.price_at_signal - 1.0) * 100
                    END
                    ELSE NULL END) as avg_1d_return_pct
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            {where}
            AND sp.price_at_signal > 0
            AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                 OR sp.max_gain_pct IS NOT NULL)
        """
        async with self.db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if not row:
                d = {"total_tracked": 0, "winners": 0, "losers": 0,
                     "win_rate": 0, "avg_gain_pct": 0, "avg_loss_pct": 0,
                     "neutral": 0}
            else:
                d = _row_to_dict(row)

        # Merge in snapshot data (only for non-ticker-filtered queries)
        if not ticker:
            snap = await self.get_cumulative_win_rate(days=days)
            snap_w = snap.get("winners", 0) or 0
            snap_l = snap.get("losers", 0) or 0
            snap_n = snap.get("neutral", 0) or 0
            snap_total = snap.get("total_tracked", 0) or 0
            if snap_total > 0:
                d["winners"] = (d.get("winners", 0) or 0) + snap_w
                d["losers"] = (d.get("losers", 0) or 0) + snap_l
                d["neutral"] = (d.get("neutral", 0) or 0) + snap_n
                d["total_tracked"] = (d.get("total_tracked", 0) or 0) + snap_total

        winners = d.get("winners", 0) or 0
        losers = d.get("losers", 0) or 0
        decided = winners + losers
        d["win_rate"] = (winners / decided * 100) if decided > 0 else 0
        return d

    async def get_accuracy_by_confidence(self, days: int = 30) -> List[Dict[str, Any]]:
        """Win rate broken down by confidence buckets: <30%, 30-50%, 50-70%, 70%+."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT
                CASE
                    WHEN s.confidence < 0.3 THEN 'low'
                    WHEN s.confidence < 0.5 THEN 'mid'
                    WHEN s.confidence < 0.7 THEN 'high'
                    ELSE 'very_high'
                END as bucket,
                COUNT(*) as total,
                SUM({_WIN_SQL}) as winners,
                SUM({_LOSS_SQL}) as losers
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE s.created_at > ?
            AND sp.price_at_signal > 0
            AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
            GROUP BY bucket
            ORDER BY s.confidence ASC
        """
        labels = {"low": "<30%", "mid": "30-50%", "high": "50-70%", "very_high": "70%+"}
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                w = d.get("winners", 0) or 0
                l = d.get("losers", 0) or 0
                decided = w + l
                d["win_rate"] = round(w / decided * 100) if decided > 0 else 0
                d["label"] = labels.get(d.get("bucket", ""), "?")
                results.append(d)
            return results

    async def get_performance_history(
        self, days: int = 30, ticker: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get per-signal performance records."""
        cutoff = time.time() - (days * 86400)
        conditions = ["s.created_at > ?"]
        params: list = [cutoff]

        if ticker:
            conditions.append("sp.ticker = ?")
            params.append(ticker.upper())

        where = f"WHERE {' AND '.join(conditions)}"
        query = f"""
            SELECT sp.*, s.stance, s.confidence, s.strategy
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            {where}
            AND sp.price_at_signal > 0
            ORDER BY s.created_at DESC
            LIMIT ?
        """
        params.append(limit)
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_performance_csv_data(
        self, days: int = 365, ticker: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get detailed performance data for CSV export."""
        cutoff = time.time() - (days * 86400)
        conditions = ["s.created_at > ?"]
        params: list = [cutoff]

        if ticker:
            conditions.append("sp.ticker = ?")
            params.append(ticker.upper())

        where = f"WHERE {' AND '.join(conditions)}"
        query = f"""
            SELECT sp.*, s.ticker, s.stance, s.confidence, s.strategy,
                   s.event_type, s.subreddit, s.post_title
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            {where}
            AND sp.price_at_signal > 0
            ORDER BY s.created_at DESC
        """
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_accuracy_over_time(
        self, days: int = 30, interval: str = "daily"
    ) -> List[Dict[str, Any]]:
        """Get time-bucketed accuracy for performance charts."""
        cutoff = time.time() - (days * 86400)
        bucket_s = 86400 if interval == "daily" else 3600
        query = f"""
            SELECT
                CAST(s.created_at / ? AS INTEGER) * ? as time_bucket,
                COUNT(*) as total,
                SUM({_WIN_SQL}) as winners,
                AVG(sp.max_gain_pct) as avg_gain_pct,
                AVG(sp.max_loss_pct) as avg_loss_pct
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE s.created_at > ? AND sp.price_at_signal > 0
                  AND (sp.price_1d IS NOT NULL OR sp.price_4h IS NOT NULL)
            GROUP BY time_bucket
            ORDER BY time_bucket ASC
        """
        async with self.db.execute(query, (bucket_s, bucket_s, cutoff)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_strategy_pnl(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get P&L breakdown by strategy."""
        cutoff = time.time() - (days * 86400)
        query = f"""
            SELECT
                s.strategy,
                COUNT(*) as total,
                SUM({_WIN_SQL}) as winners,
                AVG(sp.max_gain_pct) as avg_gain_pct,
                AVG(sp.max_loss_pct) as avg_loss_pct,
                AVG(CASE WHEN sp.price_1d IS NOT NULL
                    THEN CASE WHEN s.stance = 'bearish'
                        THEN (1.0 - sp.price_1d / sp.price_at_signal) * 100
                        ELSE (sp.price_1d / sp.price_at_signal - 1.0) * 100
                    END
                    ELSE NULL END) as avg_1d_return_pct
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE s.created_at > ? AND sp.price_at_signal > 0
                  AND s.strategy != 'none'
            GROUP BY s.strategy
            ORDER BY total DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_performance_by_ticker(
        self, days: int = 30, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get performance breakdown by ticker."""
        cutoff = time.time() - (days * 86400)
        query = f"""
            SELECT
                sp.ticker,
                COUNT(*) as total_signals,
                SUM({_WIN_SQL}) as winners,
                AVG(sp.max_gain_pct) as avg_gain_pct,
                AVG(sp.max_loss_pct) as avg_loss_pct
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE s.created_at > ? AND sp.price_at_signal > 0
              AND (sp.price_1d IS NOT NULL OR sp.price_4h IS NOT NULL)
            GROUP BY sp.ticker
            ORDER BY total_signals DESC
            LIMIT ?
        """
        async with self.db.execute(query, (cutoff, limit)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    # ── Accuracy by Event Type / Strategy (Premium) ──

    async def get_accuracy_by_event_type(self, days: int = 30) -> List[Dict[str, Any]]:
        """Win rate broken down by event_type (earnings_rumor, squeeze, etc.)."""
        cutoff = time.time() - (days * 86400)
        query = f"""
            SELECT
                s.event_type,
                COUNT(*) as total,
                SUM({_WIN_SQL}) as winners,
                SUM({_LOSS_SQL}) as losers,
                SUM({_NEUTRAL_SQL}) as neutral,
                AVG(CASE WHEN sp.price_1d IS NOT NULL
                    THEN CASE WHEN s.stance = 'bearish'
                        THEN (1.0 - sp.price_1d / sp.price_at_signal) * 100
                        ELSE (sp.price_1d / sp.price_at_signal - 1.0) * 100
                    END ELSE NULL END) as avg_return_pct
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE s.created_at > ? AND sp.price_at_signal > 0
                  AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
            GROUP BY s.event_type
            ORDER BY total DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                w = d.get("winners", 0) or 0
                l = d.get("losers", 0) or 0
                decided = w + l
                d["win_rate"] = round(w / decided * 100) if decided > 0 else 0
                results.append(d)
            return results

    async def get_accuracy_by_strategy(self, days: int = 30) -> List[Dict[str, Any]]:
        """Win rate broken down by strategy (debit_spread, credit_spread, etc.)."""
        cutoff = time.time() - (days * 86400)
        # stance_return: positive = trade direction was right, negative = wrong
        # Use 1d-only price column for avg_gain/avg_loss (more reliable)
        _1d_win = _WIN_CASE_SQL.format(price_col="sp.price_1d")
        _1d_loss = _LOSS_CASE_SQL.format(price_col="sp.price_1d")
        query = f"""
            SELECT
                s.strategy,
                COUNT(*) as total,
                SUM({_WIN_SQL}) as winners,
                SUM({_LOSS_SQL}) as losers,
                AVG(CASE WHEN sp.price_1d IS NOT NULL
                    THEN CASE WHEN s.stance = 'bearish'
                        THEN (1.0 - sp.price_1d / sp.price_at_signal) * 100
                        ELSE (sp.price_1d / sp.price_at_signal - 1.0) * 100
                    END ELSE NULL END) as avg_return_pct,
                AVG(CASE
                    WHEN sp.price_1d IS NOT NULL AND {_1d_win} = 1
                    THEN CASE WHEN s.stance = 'bearish'
                        THEN (1.0 - sp.price_1d / sp.price_at_signal) * 100
                        ELSE (sp.price_1d / sp.price_at_signal - 1.0) * 100
                    END ELSE NULL END) as avg_gain_pct,
                AVG(CASE
                    WHEN sp.price_1d IS NOT NULL AND {_1d_loss} = 1
                    THEN CASE WHEN s.stance = 'bearish'
                        THEN (1.0 - sp.price_1d / sp.price_at_signal) * 100
                        ELSE (sp.price_1d / sp.price_at_signal - 1.0) * 100
                    END ELSE NULL END) as avg_loss_pct
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE s.created_at > ? AND sp.price_at_signal > 0
                  AND s.strategy != 'none'
                  AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
            GROUP BY s.strategy
            ORDER BY total DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                w = d.get("winners", 0) or 0
                l = d.get("losers", 0) or 0
                decided = w + l
                d["win_rate"] = round(w / decided * 100) if decided > 0 else 0
                results.append(d)
            return results

    # ── Confidence Calibration ──

    async def get_confidence_calibration(self, days: int = 90) -> List[Dict[str, Any]]:
        """Expected vs actual win rate by confidence decile for calibration chart."""
        cutoff = time.time() - (days * 86400)
        query = f"""
            SELECT
                CAST(s.confidence * 10 AS INTEGER) as decile,
                COUNT(*) as total,
                SUM({_WIN_SQL}) as winners,
                AVG(s.confidence) as avg_confidence
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE s.created_at > ? AND sp.price_at_signal > 0
                  AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
            GROUP BY decile
            ORDER BY decile ASC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                total = d.get("total", 0) or 0
                w = d.get("winners", 0) or 0
                d["actual_win_rate"] = round(w / total * 100) if total > 0 else 0
                d["expected_win_rate"] = round((d.get("avg_confidence", 0) or 0) * 100)
                decile = d.get("decile", 0) or 0
                d["bucket_label"] = f"{decile * 10}-{decile * 10 + 10}%"
                d["label"] = d["bucket_label"]  # backward compat
                results.append(d)
            return results

    # ── Sector Rotation ──

    async def get_sector_rotation_data(self, days: int = 30) -> List[Dict[str, Any]]:
        """Sector-level signal aggregation with win rate for rotation insights."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT
                s.sector,
                COUNT(*) as total_signals,
                SUM(CASE WHEN s.stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN s.stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                AVG(s.confidence) as avg_confidence,
                COUNT(DISTINCT s.ticker) as unique_tickers,
                GROUP_CONCAT(DISTINCT s.ticker) as top_tickers
            FROM signals s
            WHERE s.created_at > ? AND s.sector != '' AND s.ticker != 'UNKNOWN'
            GROUP BY s.sector
            HAVING total_signals >= 2
            ORDER BY total_signals DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                bull = d.get("bullish", 0) or 0
                bear = d.get("bearish", 0) or 0
                total = bull + bear
                d["bullish_pct"] = round(bull / total * 100) if total > 0 else 50
                if d.get("top_tickers"):
                    d["top_tickers"] = d["top_tickers"].split(",")[:5]
                else:
                    d["top_tickers"] = []
                results.append(d)
            return results

    async def get_sector_rotation_with_performance(self, days: int = 30) -> List[Dict[str, Any]]:
        """Sector rotation with win rate overlay."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT
                s.sector,
                COUNT(*) as total_signals,
                SUM(CASE WHEN s.stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN s.stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                AVG(s.confidence) as avg_confidence,
                SUM(CASE
                    WHEN sp.price_at_signal > 0 AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                    THEN CASE
                        WHEN s.stance = 'bearish'
                             AND (sp.price_at_signal - COALESCE(sp.price_1d, sp.price_4h, sp.price_1h))
                                 / sp.price_at_signal > 0.005 THEN 1
                        WHEN s.stance = 'bullish'
                             AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) - sp.price_at_signal)
                                 / sp.price_at_signal > 0.005 THEN 1
                        ELSE 0
                    END ELSE NULL END) as winners,
                SUM(CASE
                    WHEN sp.price_at_signal > 0 AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                    THEN 1 ELSE 0 END) as tracked
            FROM signals s
            LEFT JOIN signal_performance sp ON sp.signal_id = s.id
            WHERE s.created_at > ? AND s.sector != '' AND s.ticker != 'UNKNOWN'
            GROUP BY s.sector
            HAVING total_signals >= 2
            ORDER BY total_signals DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                bull = d.get("bullish", 0) or 0
                bear = d.get("bearish", 0) or 0
                total = bull + bear
                d["bullish_pct"] = round(bull / total * 100) if total > 0 else 50
                w = d.get("winners", 0) or 0
                tracked = d.get("tracked", 0) or 0
                d["win_rate"] = round(w / tracked * 100) if tracked > 0 else None
                results.append(d)
            return results

    # ── Cross-Source Corroboration ──

    async def update_corroboration(self, signal_id: str, count: int, sources: List[str]) -> None:
        """Update corroboration count and sources for a signal."""
        await self.db.execute(
            "UPDATE signals SET corroboration_count = ?, corroboration_sources = ? WHERE id = ?",
            (count, json.dumps(sources), signal_id),
        )
        await self.db.commit()

    async def find_corroborating_signals(
        self, ticker: str, stance: str, window_s: int = 3600
    ) -> List[Dict[str, Any]]:
        """Find recent signals for the same ticker+stance from different sources."""
        cutoff = time.time() - window_s
        query = """
            SELECT id, subreddit, confidence, created_at
            FROM signals
            WHERE ticker = ? AND stance = ? AND created_at > ?
            ORDER BY created_at DESC
        """
        async with self.db.execute(query, (ticker, stance, cutoff)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    # ── Signal Expiration ──

    async def expire_stale_signals(self) -> int:
        """Mark signals past their expires_at as expired (set confidence to 0).
        Returns count of expired signals."""
        now = time.time()
        async with self.db.execute(
            """UPDATE signals SET quality_score = 0
               WHERE expires_at IS NOT NULL AND expires_at < ?
               AND quality_score > 0""",
            (now,),
        ) as cursor:
            count = cursor.rowcount
        if count > 0:
            await self.db.commit()
            log.info("Expired %d stale signals past their expires_at", count)
        return count

    # ── Post-Mortem ──

    async def save_post_mortem(self, signal_id: str, post_mortem: str) -> None:
        """Save a post-mortem analysis for a resolved signal."""
        await self.db.execute(
            "UPDATE signals SET post_mortem = ? WHERE id = ?",
            (post_mortem, signal_id),
        )
        await self.db.commit()

    async def get_signals_needing_post_mortem(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get resolved signals that don't have a post-mortem yet."""
        query = """
            SELECT s.id, s.ticker, s.stance, s.confidence, s.event_type, s.strategy,
                   s.post_title, s.created_at,
                   sp.price_at_signal, sp.price_1d, sp.price_4h, sp.price_1h,
                   sp.max_gain_pct, sp.max_loss_pct
            FROM signals s
            JOIN signal_performance sp ON sp.signal_id = s.id
            WHERE s.post_mortem = '' AND sp.price_at_signal > 0
                  AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
            ORDER BY s.created_at DESC
            LIMIT ?
        """
        async with self.db.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def generate_heuristic_post_mortems(self, limit: int = 50) -> int:
        """Generate heuristic post-mortem text for resolved signals without one.

        This is a rule-based fallback when no LLM is available.
        """
        signals = await self.get_signals_needing_post_mortem(limit=limit)
        count = 0
        for sig in signals:
            try:
                pm = self._build_post_mortem_text(sig)
                if pm:
                    await self.save_post_mortem(sig["id"], pm)
                    count += 1
            except Exception as e:
                log.warning("Post-mortem generation failed for %s: %s", sig.get("id"), e)
        return count

    @staticmethod
    def _build_post_mortem_text(sig: dict) -> str:
        """Build a heuristic post-mortem from price performance data."""
        ticker = sig.get("ticker", "?")
        stance = sig.get("stance", "unknown")
        confidence = sig.get("confidence", 0)
        strategy = sig.get("strategy", "none")
        event_type = sig.get("event_type", "other")

        price_at = sig.get("price_at_signal", 0)
        price_now = sig.get("price_1d") or sig.get("price_4h") or sig.get("price_1h")
        if not price_at or not price_now or price_at <= 0:
            return ""

        pct_change = ((price_now - price_at) / price_at) * 100
        direction = "up" if pct_change > 0 else "down" if pct_change < 0 else "flat"
        abs_pct = abs(pct_change)

        threshold = 0.5
        if stance == "bullish":
            won = pct_change > threshold
        elif stance == "bearish":
            won = pct_change < -threshold
        else:
            won = abs_pct > threshold

        outcome = "WIN" if won else "LOSS" if abs_pct > threshold else "NEUTRAL"
        max_gain = sig.get("max_gain_pct") or 0
        max_loss = sig.get("max_loss_pct") or 0

        parts = [
            f"Signal: {stance.upper()} {ticker} ({confidence*100:.0f}% conf, {strategy.replace('_',' ')})",
            f"Outcome: {outcome} — Price moved {direction} {abs_pct:.1f}%",
        ]
        if max_gain > 0:
            parts.append(f"Peak gain: +{max_gain:.1f}%")
        if max_loss < 0:
            parts.append(f"Max drawdown: {max_loss:.1f}%")

        if won:
            if abs_pct > 5:
                parts.append(f"Strong directional move validated the {stance} thesis.")
            else:
                parts.append(f"Modest gain aligned with the {stance} outlook.")
        elif abs_pct <= threshold:
            parts.append("Price stayed within noise range; no decisive move.")
        else:
            if stance == "bullish" and pct_change < 0:
                parts.append("Price moved against the bullish thesis.")
            elif stance == "bearish" and pct_change > 0:
                parts.append("Price rose despite bearish call.")
            else:
                parts.append("Mixed signal did not produce a clear directional winner.")

        if event_type not in ("other", "unknown", ""):
            parts.append(f"Event type: {event_type.replace('_', ' ')}")

        return " | ".join(parts)

    # ── Signal Count Badge ──

    async def get_signals_since(self, timestamp: float) -> int:
        """Count signals created after the given timestamp."""
        async with self.db.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at > ?", (timestamp,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def update_last_visit(self, user_id: str) -> None:
        """Update the user's last_visit_at timestamp in settings."""
        user = await self.get_user_by_id(user_id)
        if not user:
            return
        settings = user.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}
        settings["last_visit_at"] = time.time()
        await self.update_user_settings(user_id, settings)

    # ── Sector Heatmap ──

    async def get_sector_heatmap_data(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get sector-level signal aggregation for heatmap."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                sector,
                COUNT(*) as signal_count,
                AVG(confidence) as avg_confidence,
                SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish_count,
                SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish_count,
                SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed_count,
                GROUP_CONCAT(DISTINCT ticker) as tickers
            FROM signals
            WHERE created_at > ? AND sector != '' AND ticker != 'UNKNOWN'
            GROUP BY sector
            ORDER BY signal_count DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_sector_drill_down(
        self, sector: str, hours: int = 24
    ) -> List[Dict[str, Any]]:
        """Get ticker-level data within a sector."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                ticker,
                COUNT(*) as signal_count,
                AVG(confidence) as avg_confidence,
                MAX(trend_score) as max_trend_score,
                GROUP_CONCAT(DISTINCT stance) as stances
            FROM signals
            WHERE created_at > ? AND sector = ? AND ticker != 'UNKNOWN'
            GROUP BY ticker
            ORDER BY signal_count DESC
            LIMIT 20
        """
        async with self.db.execute(query, (cutoff, sector)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    # ── Leaderboard ──

    async def get_leaderboard(
        self, hours: int = 24, limit: int = 20, sort_by: str = "signal_count"
    ) -> List[Dict[str, Any]]:
        """Get ticker leaderboard ranked by various metrics."""
        cutoff = time.time() - (hours * 3600)
        valid_sorts = {"signal_count", "avg_confidence", "max_trend_score"}
        order = sort_by if sort_by in valid_sorts else "signal_count"
        query = f"""
            SELECT
                ticker,
                COUNT(*) as signal_count,
                AVG(confidence) as avg_confidence,
                MAX(trend_score) as max_trend_score,
                GROUP_CONCAT(DISTINCT stance) as stances,
                GROUP_CONCAT(DISTINCT strategy) as strategies,
                MAX(created_at) as latest_at
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            GROUP BY ticker
            ORDER BY {order} DESC
            LIMIT ?
        """
        async with self.db.execute(query, (cutoff, limit)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_leaderboard_with_performance(
        self, hours: int = 24, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get leaderboard with win rate from performance data."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                s.ticker,
                COUNT(DISTINCT s.id) as signal_count,
                AVG(s.confidence) as avg_confidence,
                MAX(s.trend_score) as max_trend_score,
                GROUP_CONCAT(DISTINCT s.stance) as stances,
                COUNT(CASE
                    WHEN sp.price_at_signal IS NOT NULL AND sp.price_1d IS NOT NULL THEN
                        CASE WHEN (s.stance = 'bearish' AND sp.price_1d < sp.price_at_signal)
                                  OR (s.stance != 'bearish' AND sp.price_1d > sp.price_at_signal)
                             THEN 1 END
                    WHEN sp.price_at_signal IS NOT NULL AND sp.price_1h IS NOT NULL THEN
                        CASE WHEN (s.stance = 'bearish' AND sp.price_1h < sp.price_at_signal)
                                  OR (s.stance != 'bearish' AND sp.price_1h > sp.price_at_signal)
                             THEN 1 END
                    END) as perf_winners,
                COUNT(CASE WHEN sp.price_at_signal IS NOT NULL
                           AND (sp.price_1h IS NOT NULL OR sp.price_1d IS NOT NULL)
                      THEN 1 END) as perf_tracked
            FROM signals s
            LEFT JOIN signal_performance sp ON s.id = sp.signal_id
            WHERE s.created_at > ? AND s.ticker != 'UNKNOWN'
            GROUP BY s.ticker
            ORDER BY signal_count DESC
            LIMIT ?
        """
        async with self.db.execute(query, (cutoff, limit)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                tracked = d.get("perf_tracked", 0) or 0
                winners = d.get("perf_winners", 0) or 0
                d["win_rate"] = (winners / tracked * 100) if tracked > 0 else None
                results.append(d)
            return results

    # ── Correlation View ──

    async def get_co_occurring_tickers(
        self, hours: int = 24, min_co_occurrence: int = 2
    ) -> List[Dict[str, Any]]:
        """Find tickers that appear in signals within the same run/batch."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                a.ticker as ticker_a,
                b.ticker as ticker_b,
                COUNT(*) as co_occurrences,
                AVG(a.confidence + b.confidence) / 2 as avg_joint_confidence
            FROM signals a
            JOIN signals b ON a.run_id = b.run_id AND a.ticker < b.ticker
            WHERE a.created_at > ?
                  AND a.ticker != 'UNKNOWN' AND b.ticker != 'UNKNOWN'
            GROUP BY a.ticker, b.ticker
            HAVING co_occurrences >= ?
            ORDER BY co_occurrences DESC
            LIMIT 50
        """
        async with self.db.execute(query, (cutoff, min_co_occurrence)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    # ── Email Alert Settings ──

    async def upsert_email_alert_settings(
        self, user_id: str, settings: Dict[str, Any]
    ) -> None:
        """Create or update email alert settings for a user."""
        existing = await self.get_email_alert_settings(user_id)
        if existing:
            set_clauses = []
            params = []
            for col in ("enabled", "digest_enabled", "realtime_enabled",
                         "min_confidence", "tickers", "stances", "event_types",
                         "webhook_url"):
                if col in settings:
                    set_clauses.append(f"{col} = ?")
                    val = settings[col]
                    if isinstance(val, (list, dict)):
                        val = json.dumps(val)
                    params.append(val)
            if set_clauses:
                params.append(user_id)
                query = f"UPDATE email_alert_settings SET {', '.join(set_clauses)} WHERE user_id = ?"
                await self.db.execute(query, params)
                await self.db.commit()
        else:
            tickers = json.dumps(settings.get("tickers", []))
            stances = json.dumps(settings.get("stances", []))
            event_types = json.dumps(settings.get("event_types", []))
            await self.db.execute(
                """INSERT INTO email_alert_settings
                   (user_id, enabled, digest_enabled, realtime_enabled,
                    min_confidence, tickers, stances, event_types, webhook_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    settings.get("enabled", 0),
                    settings.get("digest_enabled", 1),
                    settings.get("realtime_enabled", 0),
                    settings.get("min_confidence", 0.6),
                    tickers, stances, event_types,
                    settings.get("webhook_url", ""),
                ),
            )
            await self.db.commit()

    async def get_email_alert_settings(
        self, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get email alert settings for a user."""
        async with self.db.execute(
            "SELECT * FROM email_alert_settings WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            for key in ("tickers", "stances", "event_types"):
                if key in d and isinstance(d[key], str):
                    try:
                        d[key] = json.loads(d[key])
                    except (json.JSONDecodeError, TypeError):
                        d[key] = []
            return d

    async def get_users_for_digest(self) -> List[Dict[str, Any]]:
        """Get users who need a daily digest email."""
        cutoff = time.time() - 86400  # users not emailed in last 24h
        query = """
            SELECT u.id, u.email, u.tier, eas.*
            FROM email_alert_settings eas
            JOIN users u ON eas.user_id = u.id
            WHERE eas.enabled = 1 AND eas.digest_enabled = 1
                  AND eas.last_digest_at < ?
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_users_for_realtime_alert(
        self, ticker: str, stance: str, confidence: float, event_type: str
    ) -> List[Dict[str, Any]]:
        """Get users whose realtime alert filters match a signal."""
        query = """
            SELECT u.id, u.email, u.tier, eas.*
            FROM email_alert_settings eas
            JOIN users u ON eas.user_id = u.id
            WHERE eas.enabled = 1 AND eas.realtime_enabled = 1
                  AND ? >= eas.min_confidence
                  AND u.tier IN ('pro', 'premium', 'ultra', 'enterprise')
        """
        async with self.db.execute(query, (confidence,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                # Parse JSON filter fields
                for key in ("tickers", "stances", "event_types"):
                    if key in d and isinstance(d[key], str):
                        try:
                            d[key] = json.loads(d[key])
                        except (json.JSONDecodeError, TypeError):
                            d[key] = []
                # Check filter match
                filter_tickers = d.get("tickers", [])
                filter_stances = d.get("stances", [])
                filter_events = d.get("event_types", [])

                if filter_tickers and ticker.upper() not in filter_tickers:
                    continue
                if filter_stances and stance not in filter_stances:
                    continue
                if filter_events and event_type not in filter_events:
                    continue
                results.append(d)
            return results

    async def get_users_with_watchlist_ticker(self, ticker: str) -> List[Dict[str, Any]]:
        """Get paid users who have this ticker on their watchlist (stored in settings JSON)."""
        query = """
            SELECT id, email, tier, settings
            FROM users
            WHERE tier IN ('pro', 'premium', 'ultra', 'enterprise')
        """
        async with self.db.execute(query) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                settings = d.get("settings", "{}")
                if isinstance(settings, str):
                    try:
                        settings = json.loads(settings)
                    except (json.JSONDecodeError, TypeError):
                        settings = {}
                watchlist = settings.get("watchlist", [])
                if isinstance(watchlist, list) and ticker.upper() in [t.upper() for t in watchlist]:
                    results.append(d)
            return results

    async def update_digest_sent(self, user_id: str) -> None:
        """Mark that a digest was sent to the user."""
        await self.db.execute(
            "UPDATE email_alert_settings SET last_digest_at = ? WHERE user_id = ?",
            (time.time(), user_id),
        )
        await self.db.commit()

    # ── X / Twitter posting ──

    async def get_top_signal_for_x_post(
        self, min_confidence: float = 0.7
    ) -> Optional[Dict[str, Any]]:
        """Get the best recent signal that hasn't been posted to X yet.

        Picks the highest-confidence signal from the last 6 hours that:
          - meets the confidence threshold
          - has a tradeable strategy (not 'none')
          - hasn't already been posted
          - isn't the same ticker as the most recent post (avoids repeats)
        """
        cutoff = time.time() - 21600  # last 6 hours

        # Get the most recently posted ticker to avoid back-to-back duplicates
        async with self.db.execute(
            "SELECT ticker FROM x_posts ORDER BY posted_at DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            last_ticker = row[0] if row else None

        query = """
            SELECT id, ticker, stance, confidence, event_type,
                   strategy, time_horizon, created_at, post_title,
                   subreddit, reasoning
            FROM signals
            WHERE created_at > ?
              AND confidence >= ?
              AND strategy != 'none'
              AND ticker != 'UNKNOWN'
              AND id NOT IN (SELECT signal_id FROM x_posts)
        """
        params: list = [cutoff, min_confidence]

        if last_ticker:
            query += " AND ticker != ?"
            params.append(last_ticker)

        query += " ORDER BY confidence DESC, created_at DESC LIMIT 1"

        async with self.db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def record_x_post(
        self, signal_id: str, ticker: str, tweet_id: str, tweet_text: str
    ) -> None:
        """Record that a signal was posted to X/Twitter."""
        await self.db.execute(
            "INSERT INTO x_posts (signal_id, ticker, tweet_id, tweet_text, posted_at) VALUES (?, ?, ?, ?, ?)",
            (signal_id, ticker, tweet_id, tweet_text, time.time()),
        )
        await self.db.commit()


    # ── Sentiment Heatmap ──

    async def get_sentiment_heatmap(
        self, hours: int = 24, ticker_limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get sentiment data bucketed by ticker and time period for heatmap."""
        cutoff = time.time() - (hours * 3600)
        # Use 1h buckets for <= 24h, 4h for <= 7d, 1d for longer
        if hours <= 24:
            bucket_s = 3600
        elif hours <= 168:
            bucket_s = 14400
        else:
            bucket_s = 86400

        query = """
            SELECT ticker,
                   CAST(created_at / ? AS INTEGER) * ? as time_bucket,
                   COUNT(*) as signal_count,
                   AVG(confidence) as avg_confidence,
                   SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                   SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                   SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            GROUP BY ticker, time_bucket
            ORDER BY signal_count DESC
        """
        async with self.db.execute(query, (bucket_s, bucket_s, cutoff)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ── Ticker Deep Dive ──

    async def get_ticker_summary(self, ticker: str) -> Dict[str, Any]:
        """Get aggregate summary for a single ticker."""
        query = """
            SELECT ticker,
                   COUNT(*) as total_signals,
                   AVG(confidence) as avg_confidence,
                   SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish_count,
                   SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish_count,
                   SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed_count,
                   MIN(created_at) as first_signal_at,
                   MAX(created_at) as latest_signal_at
            FROM signals
            WHERE ticker = ? AND ticker != 'UNKNOWN'
        """
        async with self.db.execute(query, (ticker.upper(),)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {}

    async def get_ticker_signals(
        self, ticker: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get signals for a specific ticker, newest first."""
        query = """
            SELECT * FROM signals
            WHERE ticker = ? AND ticker != 'UNKNOWN'
            ORDER BY created_at DESC
            LIMIT ?
        """
        async with self.db.execute(query, (ticker.upper(), limit)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(r) for r in rows]

    # ── Weekly Wrap ──

    async def get_weekly_summary(
        self, start_ts: float, end_ts: float
    ) -> Dict[str, Any]:
        """Get aggregated signal data for a given time window (week)."""
        # Total signals and stance breakdown
        query = """
            SELECT COUNT(*) as total_signals,
                   SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                   SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                   SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed,
                   AVG(confidence) as avg_confidence
            FROM signals
            WHERE created_at >= ? AND created_at < ?
              AND ticker != 'UNKNOWN'
        """
        async with self.db.execute(query, (start_ts, end_ts)) as cursor:
            row = await cursor.fetchone()
            summary = dict(row) if row else {}

        # Top tickers by signal count
        query2 = """
            SELECT ticker, COUNT(*) as count,
                   AVG(confidence) as avg_conf,
                   SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bull,
                   SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bear
            FROM signals
            WHERE created_at >= ? AND created_at < ?
              AND ticker != 'UNKNOWN'
            GROUP BY ticker
            ORDER BY count DESC
            LIMIT 20
        """
        async with self.db.execute(query2, (start_ts, end_ts)) as cursor:
            rows = await cursor.fetchall()
            summary["top_tickers"] = [dict(r) for r in rows]

        # Best and worst performers (from signal_performance)
        try:
            query3 = """
                SELECT sp.ticker, sp.max_gain_pct, sp.max_loss_pct,
                       s.stance, s.confidence, s.event_type
                FROM signal_performance sp
                JOIN signals s ON sp.signal_id = s.id
                WHERE s.created_at >= ? AND s.created_at < ?
                  AND sp.max_gain_pct IS NOT NULL
                  AND sp.max_gain_pct > 0.5
                  AND s.stance != 'unknown'
                  AND s.ticker != 'UNKNOWN'
                ORDER BY sp.max_gain_pct DESC
                LIMIT 5
            """
            async with self.db.execute(query3, (start_ts, end_ts)) as cursor:
                rows = await cursor.fetchall()
                summary["best_calls"] = [dict(r) for r in rows]

            query4 = """
                SELECT sp.ticker, sp.max_gain_pct, sp.max_loss_pct,
                       s.stance, s.confidence, s.event_type
                FROM signal_performance sp
                JOIN signals s ON sp.signal_id = s.id
                WHERE s.created_at >= ? AND s.created_at < ?
                  AND sp.max_loss_pct IS NOT NULL
                  AND sp.max_loss_pct < -0.5
                  AND s.stance != 'unknown'
                  AND s.ticker != 'UNKNOWN'
                ORDER BY sp.max_loss_pct ASC
                LIMIT 5
            """
            async with self.db.execute(query4, (start_ts, end_ts)) as cursor:
                rows = await cursor.fetchall()
                summary["worst_calls"] = [dict(r) for r in rows]
        except Exception:
            summary["best_calls"] = []
            summary["worst_calls"] = []

        return summary

    # ── Signal Replay ──

    async def get_replay_data(
        self, hours: int = 24, include_performance: bool = False
    ) -> List[Dict[str, Any]]:
        """Get signals ordered by creation time for replay animation."""
        cutoff = time.time() - (hours * 3600)

        if include_performance:
            query = """
                SELECT s.id, s.ticker, s.stance, s.confidence, s.event_type,
                       s.created_at, s.strategy, s.trend_score,
                       sp.price_at_signal, sp.price_1d, sp.max_gain_pct, sp.max_loss_pct
                FROM signals s
                LEFT JOIN signal_performance sp ON s.id = sp.signal_id
                WHERE s.created_at > ? AND s.ticker != 'UNKNOWN'
                ORDER BY s.created_at ASC
            """
        else:
            query = """
                SELECT id, ticker, stance, confidence, event_type,
                       created_at, strategy, trend_score
                FROM signals
                WHERE created_at > ? AND ticker != 'UNKNOWN'
                ORDER BY created_at ASC
            """

        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ── Referral / Affiliate Program ──

    async def record_referral_click(self, ref_code: str, ip_address: str = "") -> None:
        """Record a referral link click."""
        await self.db.execute(
            "INSERT INTO referral_clicks (ref_code, ip_address, clicked_at) VALUES (?, ?, ?)",
            (ref_code, ip_address, time.time()),
        )
        await self.db.commit()

    async def count_referrals(self, ref_code: str) -> int:
        """Count total referral link clicks."""
        async with self.db.execute(
            "SELECT COUNT(*) FROM referral_clicks WHERE ref_code = ?", (ref_code,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def record_referral_conversion(
        self, ref_code: str, referred_user_id: str, tier: str = "free", commission: float = 0.0
    ) -> None:
        """Record when a referred user signs up or upgrades."""
        await self.db.execute(
            """INSERT INTO referral_conversions
               (ref_code, referred_user_id, converted_at, tier, commission_amount)
               VALUES (?, ?, ?, ?, ?)""",
            (ref_code, referred_user_id, time.time(), tier, commission),
        )
        await self.db.commit()

    async def count_referral_conversions(self, ref_code: str) -> int:
        """Count total conversions for a referral code."""
        async with self.db.execute(
            "SELECT COUNT(*) FROM referral_conversions WHERE ref_code = ?", (ref_code,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_recent_referrals(self, ref_code: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent referral conversions for dashboard display."""
        query = """
            SELECT ref_code, converted_at, tier, commission_amount, paid_out
            FROM referral_conversions
            WHERE ref_code = ?
            ORDER BY converted_at DESC
            LIMIT ?
        """
        async with self.db.execute(query, (ref_code, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ── Sponsored Signals (Enterprise) ──

    async def create_sponsored_signal(self, user_id: str, data: Dict[str, Any]) -> str:
        """Create a sponsored signal submission."""
        sid = str(uuid.uuid4())[:12]
        now = time.time()
        await self.db.execute(
            """INSERT INTO sponsored_signals
               (id, user_id, company_name, ticker, press_url, press_content,
                priority, status, created_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sid, user_id,
                data.get("company_name", ""),
                data.get("ticker", "").upper(),
                data.get("press_url", ""),
                data.get("press_content", ""),
                data.get("priority", 0),
                "pending",
                now,
                data.get("notes", ""),
            ),
        )
        await self.db.commit()
        return sid

    async def get_sponsored_signals(
        self, user_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get sponsored signal submissions, optionally filtered."""
        conditions: List[str] = []
        params: list = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM sponsored_signals {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_sponsored_signal_status(
        self, sponsored_id: str, status: str, signal_id: Optional[str] = None
    ) -> None:
        """Update status of a sponsored signal (pending -> analyzing -> completed)."""
        if signal_id:
            await self.db.execute(
                "UPDATE sponsored_signals SET status = ?, signal_id = ?, analyzed_at = ? WHERE id = ?",
                (status, signal_id, time.time(), sponsored_id),
            )
        else:
            await self.db.execute(
                "UPDATE sponsored_signals SET status = ? WHERE id = ?",
                (status, sponsored_id),
            )
        await self.db.commit()

    async def get_pending_sponsored_count(self, user_id: str) -> int:
        """Count pending sponsored signals for a user."""
        async with self.db.execute(
            "SELECT COUNT(*) FROM sponsored_signals WHERE user_id = ? AND status = 'pending'",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    # ── Data Export Tracking (Enterprise) ──

    async def record_data_export(
        self, user_id: str, export_type: str, fmt: str, row_count: int, filters: Dict[str, Any]
    ) -> int:
        """Record a data export request."""
        now = time.time()
        await self.db.execute(
            """INSERT INTO data_exports
               (user_id, export_type, format, requested_at, completed_at, row_count, filters)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, export_type, fmt, now, now, row_count, json.dumps(filters)),
        )
        await self.db.commit()
        async with self.db.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_data_exports(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get data export history for a user."""
        async with self.db.execute(
            "SELECT * FROM data_exports WHERE user_id = ? ORDER BY requested_at DESC LIMIT ?",
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_full_signal_export(
        self, ticker: Optional[str] = None,
        date_from: Optional[float] = None,
        date_to: Optional[float] = None,
        limit: int = 100000,
    ) -> List[Dict[str, Any]]:
        """Get full signal data for enterprise data licensing export."""
        conditions = ["s.ticker != 'UNKNOWN'"]
        params: list = []
        if ticker:
            conditions.append("s.ticker = ?")
            params.append(ticker.upper())
        if date_from:
            conditions.append("s.created_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("s.created_at <= ?")
            params.append(date_to)
        where = f"WHERE {' AND '.join(conditions)}"
        query = f"""
            SELECT s.*, sp.price_at_signal, sp.price_1h, sp.price_4h,
                   sp.price_1d, sp.price_1w, sp.max_gain_pct, sp.max_loss_pct
            FROM signals s
            LEFT JOIN signal_performance sp ON s.id = sp.signal_id
            {where}
            ORDER BY s.created_at DESC
            LIMIT ?
        """
        params.append(limit)
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ── Paper Trading ──

    async def init_paper_portfolio(self, user_id: str) -> None:
        """Initialize a paper portfolio for a user."""
        await self.db.execute(
            "INSERT OR IGNORE INTO paper_portfolios (user_id) VALUES (?)",
            (user_id,),
        )
        await self.db.commit()

    async def get_paper_portfolio(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get paper portfolio for a user."""
        async with self.db.execute(
            "SELECT * FROM paper_portfolios WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def create_paper_trade(
        self, user_id: str, signal_id: str, ticker: str, stance: str,
        entry_price: float, quantity: float, dollars: float,
    ) -> Dict[str, Any]:
        """Create a paper trade and deduct from balance."""
        trade_id = str(uuid.uuid4())[:12]
        now = time.time()

        # Deduct from balance
        portfolio = await self.get_paper_portfolio(user_id)
        new_balance = portfolio["balance"] - dollars

        await self.db.execute("""
            INSERT INTO paper_trades
            (id, user_id, signal_id, ticker, stance, entry_price, quantity, paper_balance_after, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
        """, (trade_id, user_id, signal_id, ticker, stance, entry_price, quantity, new_balance, now))

        await self.db.execute(
            "UPDATE paper_portfolios SET balance = ?, last_trade_at = ? WHERE user_id = ?",
            (new_balance, now, user_id),
        )
        await self.db.commit()

        return {
            "id": trade_id, "ticker": ticker, "stance": stance,
            "entry_price": entry_price, "quantity": quantity,
            "balance_after": new_balance,
        }

    async def get_paper_trade(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Get a single paper trade."""
        async with self.db.execute(
            "SELECT * FROM paper_trades WHERE id = ?", (trade_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def close_paper_trade(self, trade_id: str, exit_price: float) -> Dict[str, Any]:
        """Close a paper trade and update portfolio stats."""
        trade = await self.get_paper_trade(trade_id)
        if not trade:
            return {}

        now = time.time()
        entry = trade["entry_price"]
        qty = trade["quantity"]
        stance = trade["stance"]

        # Calculate P&L (stance-aware: bearish = profit on price drop)
        if stance == "bearish":
            pnl_pct = ((entry - exit_price) / entry) * 100
        else:
            pnl_pct = ((exit_price - entry) / entry) * 100

        cost = entry * qty
        pnl_dollars = cost * (pnl_pct / 100)

        # Update trade
        await self.db.execute("""
            UPDATE paper_trades
            SET closed_at = ?, exit_price = ?, pnl_dollars = ?, pnl_pct = ?, status = 'closed'
            WHERE id = ?
        """, (now, exit_price, pnl_dollars, pnl_pct, trade_id))

        # Update portfolio
        portfolio = await self.get_paper_portfolio(trade["user_id"])
        new_balance = portfolio["balance"] + cost + pnl_dollars
        new_total = portfolio["total_trades"] + 1
        new_winning = portfolio["winning_trades"] + (1 if pnl_dollars > 0 else 0)
        new_pnl = portfolio["total_pnl"] + pnl_dollars

        await self.db.execute("""
            UPDATE paper_portfolios
            SET balance = ?, total_trades = ?, winning_trades = ?, total_pnl = ?
            WHERE user_id = ?
        """, (new_balance, new_total, new_winning, new_pnl, trade["user_id"]))

        await self.db.commit()

        return {
            "id": trade_id, "ticker": trade["ticker"],
            "entry_price": entry, "exit_price": exit_price,
            "pnl_dollars": round(pnl_dollars, 2), "pnl_pct": round(pnl_pct, 2),
            "new_balance": round(new_balance, 2),
        }

    async def get_paper_trades(
        self, user_id: str, status: Optional[str] = None, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get paper trades for a user."""
        if status:
            query = "SELECT * FROM paper_trades WHERE user_id = ? AND status = ? ORDER BY created_at DESC LIMIT ?"
            params = (user_id, status, limit)
        else:
            query = "SELECT * FROM paper_trades WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
            params = (user_id, limit)
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ── Correlation Engine ──

    async def get_ticker_correlations(
        self, ticker: str, days: int = 90, window_hours: int = 4,
    ) -> List[Dict[str, Any]]:
        """Find tickers that fire signals within N hours of the given ticker."""
        cutoff = time.time() - (days * 86400)
        window_s = window_hours * 3600

        # Fetch signals for the target ticker
        q1 = """
            SELECT id, ticker, stance, confidence, created_at
            FROM signals WHERE ticker = ? AND created_at > ?
            ORDER BY created_at DESC LIMIT 500
        """
        async with self.db.execute(q1, (ticker, cutoff)) as cursor:
            target_rows = await cursor.fetchall()
            target_signals = [dict(r) for r in target_rows]

        if not target_signals:
            return []

        # Fetch all other signals in the time range
        q2 = """
            SELECT id, ticker, stance, confidence, created_at
            FROM signals WHERE ticker != ? AND ticker != 'UNKNOWN' AND created_at > ?
            ORDER BY created_at DESC LIMIT 2000
        """
        async with self.db.execute(q2, (ticker, cutoff)) as cursor:
            other_rows = await cursor.fetchall()
            other_signals = [dict(r) for r in other_rows]

        if not other_signals:
            return []

        # Count co-fires in Python (much faster than SQL self-join)
        from collections import defaultdict
        ticker_stats: Dict[str, dict] = defaultdict(
            lambda: {"co_fires": 0, "same_stance": 0, "conf_sum": 0.0}
        )

        for ts in target_signals:
            for os_ in other_signals:
                if abs(ts["created_at"] - os_["created_at"]) < window_s:
                    st = ticker_stats[os_["ticker"]]
                    st["co_fires"] += 1
                    if ts["stance"] == os_["stance"]:
                        st["same_stance"] += 1
                    st["conf_sum"] += os_["confidence"]

        results = []
        for t, st in ticker_stats.items():
            if st["co_fires"] >= 3:
                results.append({
                    "ticker": t,
                    "co_fires": st["co_fires"],
                    "same_stance": st["same_stance"],
                    "avg_confidence": round(st["conf_sum"] / st["co_fires"], 3),
                })

        results.sort(key=lambda x: x["co_fires"], reverse=True)
        return results[:20]

    async def get_correlation_matrix(
        self, days: int = 30, min_co: int = 3, limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get top correlated ticker pairs globally.

        Uses a two-step approach to avoid O(n²) self-join:
        1. Bucket signals into 4-hour time windows
        2. Count co-occurrences within the same window
        """
        cutoff = time.time() - (days * 86400)
        window_s = 14400  # 4 hours

        # Step 1: Fetch recent signals (id, ticker, stance, confidence, created_at)
        fetch_q = """
            SELECT id, ticker, stance, confidence, created_at
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            ORDER BY created_at DESC
            LIMIT 2000
        """
        async with self.db.execute(fetch_q, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            signals = [dict(r) for r in rows]

        if not signals:
            return []

        # Step 2: Bucket by time window and count co-fires in Python
        from collections import defaultdict
        pair_stats: Dict[tuple, dict] = defaultdict(
            lambda: {"co_fires": 0, "same_stance": 0, "conf_sum": 0.0}
        )

        # Group signals by time bucket
        buckets: Dict[int, list] = defaultdict(list)
        for s in signals:
            bucket_id = int(s["created_at"] // window_s)
            buckets[bucket_id].append(s)
            # Also add to adjacent bucket to catch cross-boundary pairs
            buckets[bucket_id + 1].append(s)

        seen_pairs: Dict[tuple, set] = defaultdict(set)
        for _bucket_id, bucket_signals in buckets.items():
            for i, a in enumerate(bucket_signals):
                for b in bucket_signals[i + 1:]:
                    if a["ticker"] == b["ticker"] or a["id"] == b["id"]:
                        continue
                    if abs(a["created_at"] - b["created_at"]) >= window_s:
                        continue
                    pair_key = (min(a["ticker"], b["ticker"]), max(a["ticker"], b["ticker"]))
                    signal_pair = (a["id"], b["id"]) if a["id"] < b["id"] else (b["id"], a["id"])
                    if signal_pair in seen_pairs[pair_key]:
                        continue
                    seen_pairs[pair_key].add(signal_pair)
                    ps = pair_stats[pair_key]
                    ps["co_fires"] += 1
                    if a["stance"] == b["stance"]:
                        ps["same_stance"] += 1
                    ps["conf_sum"] += (a["confidence"] + b["confidence"]) / 2

        # Step 3: Filter and sort
        results = []
        for (ta, tb), ps in pair_stats.items():
            if ps["co_fires"] >= min_co:
                results.append({
                    "ticker_a": ta,
                    "ticker_b": tb,
                    "co_fires": ps["co_fires"],
                    "same_stance": ps["same_stance"],
                    "avg_confidence": round(ps["conf_sum"] / ps["co_fires"], 3),
                })

        results.sort(key=lambda x: x["co_fires"], reverse=True)
        return results[:limit]

    # ── Unusual Activity Detection ──

    async def get_unusual_activity_signals(
        self, hours: int = 24, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get signals with unusual options activity from market_data JSON."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT * FROM signals
            WHERE created_at > ? AND market_data != '{}'
            ORDER BY created_at DESC
            LIMIT 500
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()

        unusual = []
        for row in rows:
            d = _row_to_dict(dict(row))
            md = d.get("market_data", {})
            ticker = d.get("ticker", "")
            ticker_data = md.get(ticker, md) if isinstance(md, dict) else {}
            if not isinstance(ticker_data, dict):
                continue

            flags = []
            detail = {}

            # Check ATM IV (high implied volatility)
            atm_iv = ticker_data.get("atm_iv") or ticker_data.get("impliedVolatility")
            if atm_iv and isinstance(atm_iv, (int, float)) and atm_iv > 0.6:
                flags.append("High IV")
                detail["atm_iv"] = atm_iv

            # Check put/call ratio
            pc_ratio = ticker_data.get("pc_ratio") or ticker_data.get("putCallRatio")
            if pc_ratio and isinstance(pc_ratio, (int, float)):
                if pc_ratio > 3.0 or pc_ratio < 0.3:
                    flags.append("Extreme P/C Ratio")
                    detail["pc_ratio"] = pc_ratio

            # Check volume vs OI (volume spike)
            vol = ticker_data.get("volume") or ticker_data.get("totalVolume", 0)
            oi = ticker_data.get("openInterest") or ticker_data.get("totalOpenInterest", 0)
            if vol and oi and isinstance(vol, (int, float)) and isinstance(oi, (int, float)) and oi > 0:
                ratio = vol / oi
                if ratio > 2.0:
                    flags.append("Volume Spike")
                    detail["vol_oi_ratio"] = round(ratio, 2)

            if flags:
                d["unusual_flags"] = flags
                d["unusual_detail"] = detail
                unusual.append(d)

                if len(unusual) >= limit:
                    break

        return unusual

    # ── Unusual Events Table (new detection engine) ──

    async def save_unusual_events(
        self, events: List[Dict[str, Any]],
    ) -> int:
        """Batch insert unusual events. Returns count inserted.

        Each event dict should have: ticker, event_type, score, details (dict),
        detected_at, and optionally signal_id.
        """
        if not events:
            return 0
        rows = []
        for e in events:
            rows.append((
                e.get("ticker", ""),
                e.get("event_type", ""),
                e.get("score", 0.0),
                json.dumps(e.get("details", {})),
                e.get("signal_id"),
                e.get("detected_at", time.time()),
            ))
        await self.db.executemany(
            """INSERT INTO unusual_events
               (ticker, event_type, score, details_json, signal_id, detected_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await self.db.commit()
        return len(rows)

    async def get_unusual_events(
        self,
        hours: int = 24,
        ticker: Optional[str] = None,
        min_score: float = 0.0,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query unusual events with filters."""
        cutoff = time.time() - (hours * 3600)
        clauses = ["detected_at > ?"]
        params: list = [cutoff]

        if ticker:
            clauses.append("ticker = ?")
            params.append(ticker)
        if min_score > 0:
            clauses.append("score >= ?")
            params.append(min_score)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)

        where = " AND ".join(clauses)
        query = f"""
            SELECT * FROM unusual_events
            WHERE {where}
            ORDER BY detected_at DESC
            LIMIT ?
        """
        params.append(limit)

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            try:
                d["details"] = json.loads(d.pop("details_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["details"] = {}
            results.append(d)
        return results

    async def get_unusual_summary(
        self, hours: int = 24,
    ) -> Dict[str, Any]:
        """Get aggregate unusual activity stats for a time period."""
        cutoff = time.time() - (hours * 3600)
        query = """
            SELECT
                COUNT(*) as total_events,
                COUNT(DISTINCT ticker) as unique_tickers,
                COALESCE(AVG(score), 0) as avg_score,
                MAX(score) as max_score
            FROM unusual_events
            WHERE detected_at > ?
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            row = await cursor.fetchone()

        if row:
            summary = dict(row)
            # SQL aggregates return NULL on empty tables — coerce to safe defaults
            summary["total_events"] = summary.get("total_events") or 0
            summary["unique_tickers"] = summary.get("unique_tickers") or 0
            summary["avg_score"] = summary.get("avg_score") or 0
            summary["max_score"] = summary.get("max_score") or 0
        else:
            summary = {
                "total_events": 0, "unique_tickers": 0,
                "avg_score": 0, "max_score": 0,
            }

        # Type breakdown
        type_query = """
            SELECT event_type, COUNT(*) as cnt
            FROM unusual_events
            WHERE detected_at > ?
            GROUP BY event_type
            ORDER BY cnt DESC
        """
        async with self.db.execute(type_query, (cutoff,)) as cursor:
            type_rows = await cursor.fetchall()
        summary["type_breakdown"] = {r["event_type"]: r["cnt"] for r in type_rows}

        # Top tickers
        ticker_query = """
            SELECT ticker, COUNT(*) as cnt, AVG(score) as avg_score
            FROM unusual_events
            WHERE detected_at > ?
            GROUP BY ticker
            ORDER BY cnt DESC
            LIMIT 10
        """
        async with self.db.execute(ticker_query, (cutoff,)) as cursor:
            ticker_rows = await cursor.fetchall()
        summary["top_tickers"] = [
            {"ticker": r["ticker"], "count": r["cnt"],
             "avg_score": round(r["avg_score"], 1)}
            for r in ticker_rows
        ]

        return summary

    async def get_unusual_timeline(
        self, ticker: str, days: int = 7,
    ) -> List[Dict[str, Any]]:
        """Get unusual events timeline for a specific ticker."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT * FROM unusual_events
            WHERE ticker = ? AND detected_at > ?
            ORDER BY detected_at ASC
        """
        async with self.db.execute(query, (ticker, cutoff)) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            try:
                d["details"] = json.loads(d.pop("details_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["details"] = {}
            results.append(d)
        return results

    async def purge_old_unusual_events(self, keep_days: int = 30) -> int:
        """Delete unusual events older than keep_days. Returns count deleted."""
        cutoff = time.time() - (keep_days * 86400)
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM unusual_events WHERE detected_at < ?",
            (cutoff,),
        ) as cursor:
            row = await cursor.fetchone()
            count = row["cnt"] if row else 0

        if count > 0:
            await self.db.execute(
                "DELETE FROM unusual_events WHERE detected_at < ?",
                (cutoff,),
            )
            await self.db.commit()
        return count

    # ── Sector Rotation (Enhanced) ──

    async def get_sector_time_series(
        self, days: int = 30, bucket_hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """Time-bucketed sector signal counts for rotation timeline."""
        cutoff = time.time() - (days * 86400)
        bucket_s = bucket_hours * 3600
        query = """
            SELECT
                sector,
                CAST((created_at / ?) AS INTEGER) as bucket,
                COUNT(*) as signal_count,
                SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                AVG(confidence) as avg_confidence
            FROM signals
            WHERE created_at > ? AND sector != '' AND ticker != 'UNKNOWN'
            GROUP BY sector, bucket
            ORDER BY bucket, sector
        """
        async with self.db.execute(query, (bucket_s, cutoff)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                d["timestamp"] = d["bucket"] * bucket_s
                results.append(d)
            return results

    async def get_sector_ticker_breakdown(
        self, sector: str, days: int = 30,
    ) -> List[Dict[str, Any]]:
        """Tickers within a sector with signal count and performance."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT
                s.ticker,
                COUNT(*) as signal_count,
                SUM(CASE WHEN s.stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN s.stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                AVG(s.confidence) as avg_confidence,
                MAX(s.created_at) as latest_at,
                SUM(CASE
                    WHEN sp.price_at_signal > 0 AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                    THEN CASE
                        WHEN s.stance = 'bearish'
                             AND (sp.price_at_signal - COALESCE(sp.price_1d, sp.price_4h, sp.price_1h))
                                 / sp.price_at_signal > 0.005 THEN 1
                        WHEN s.stance = 'bullish'
                             AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) - sp.price_at_signal)
                                 / sp.price_at_signal > 0.005 THEN 1
                        ELSE 0
                    END ELSE NULL END) as winners,
                SUM(CASE WHEN sp.price_at_signal IS NOT NULL
                         AND (sp.price_1h IS NOT NULL OR sp.price_1d IS NOT NULL)
                    THEN 1 ELSE 0 END) as tracked
            FROM signals s
            LEFT JOIN signal_performance sp ON sp.signal_id = s.id
            WHERE s.created_at > ? AND s.sector = ? AND s.ticker != 'UNKNOWN'
            GROUP BY s.ticker
            ORDER BY signal_count DESC
            LIMIT 20
        """
        async with self.db.execute(query, (cutoff, sector)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                w = d.get("winners", 0) or 0
                tracked = d.get("tracked", 0) or 0
                d["win_rate"] = round(w / tracked * 100) if tracked > 0 else None
                results.append(d)
            return results

    async def get_sector_performance_ranked(
        self, days: int = 30,
    ) -> List[Dict[str, Any]]:
        """All sectors ranked by win rate + signal count."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT
                s.sector,
                COUNT(*) as total_signals,
                SUM(CASE WHEN s.stance = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN s.stance = 'bearish' THEN 1 ELSE 0 END) as bearish,
                AVG(s.confidence) as avg_confidence,
                COUNT(DISTINCT s.ticker) as unique_tickers,
                SUM(CASE
                    WHEN sp.price_at_signal > 0 AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                    THEN CASE
                        WHEN s.stance = 'bearish'
                             AND (sp.price_at_signal - COALESCE(sp.price_1d, sp.price_4h, sp.price_1h))
                                 / sp.price_at_signal > 0.005 THEN 1
                        WHEN s.stance = 'bullish'
                             AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) - sp.price_at_signal)
                                 / sp.price_at_signal > 0.005 THEN 1
                        ELSE 0
                    END ELSE NULL END) as winners,
                SUM(CASE WHEN sp.price_at_signal IS NOT NULL
                         AND (sp.price_1h IS NOT NULL OR sp.price_1d IS NOT NULL)
                    THEN 1 ELSE 0 END) as tracked
            FROM signals s
            LEFT JOIN signal_performance sp ON sp.signal_id = s.id
            WHERE s.created_at > ? AND s.sector != '' AND s.ticker != 'UNKNOWN'
            GROUP BY s.sector
            HAVING total_signals >= 2
            ORDER BY total_signals DESC
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                bull = d.get("bullish", 0) or 0
                bear = d.get("bearish", 0) or 0
                total = bull + bear
                d["bullish_pct"] = round(bull / total * 100) if total > 0 else 50
                w = d.get("winners", 0) or 0
                tracked = d.get("tracked", 0) or 0
                d["win_rate"] = round(w / tracked * 100) if tracked > 0 else None
                results.append(d)
            return results

    # ── Correlation (Enhanced) ──

    async def get_signal_pairs_for_correlation(
        self, days: int = 30, limit: int = 3000,
    ) -> List[Dict[str, Any]]:
        """Fetch signals for correlation analysis."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT id, ticker, stance, confidence, created_at
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            ORDER BY created_at DESC
            LIMIT ?
        """
        async with self.db.execute(query, (cutoff, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_ticker_signal_counts(
        self, days: int = 30,
    ) -> Dict[str, int]:
        """Signal counts per ticker for node sizing in network viz."""
        cutoff = time.time() - (days * 86400)
        query = """
            SELECT ticker, COUNT(*) as cnt
            FROM signals
            WHERE created_at > ? AND ticker != 'UNKNOWN'
            GROUP BY ticker
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
            return {row["ticker"]: row["cnt"] for row in rows}

    # ── Enterprise Export (Enhanced) ──

    async def get_export_schedules(
        self, user_id: str, limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get export schedules for a user from data_exports table."""
        query = """
            SELECT * FROM data_exports
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        async with self.db.execute(query, (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_enterprise_analytics_signals(
        self, date_from: float | None = None,
        date_to: float | None = None,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        """Fetch signals with performance data for analytics API."""
        conditions = ["s.ticker != 'UNKNOWN'"]
        params: list = []
        if date_from:
            conditions.append("s.created_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("s.created_at <= ?")
            params.append(date_to)
        where = " AND ".join(conditions)
        query = f"""
            SELECT s.*, sp.price_at_signal, sp.price_1h, sp.price_4h,
                   sp.price_1d, sp.price_1w, sp.max_gain_pct, sp.max_loss_pct
            FROM signals s
            LEFT JOIN signal_performance sp ON sp.signal_id = s.id
            WHERE {where}
            ORDER BY s.created_at DESC
            LIMIT ?
        """
        params.append(limit)
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    # ── Win Rate Snapshots ──

    async def snapshot_win_rate_before_purge(self, keep_days: int = 14) -> int:
        """Snapshot win/loss counts for signals that are about to be purged.

        Called BEFORE purge_old_signals so the resolved outcomes are preserved
        permanently in the win_rate_snapshots table.
        """
        cutoff = time.time() - (keep_days * 86400)
        # Only snapshot signals that will be deleted (older than cutoff)
        # AND that have price data to evaluate
        query = f"""
            SELECT
                COUNT(*) as total_tracked,
                MIN(s.created_at) as period_start,
                MAX(s.created_at) as period_end,
                SUM({_WIN_SQL}) as winners,
                SUM({_LOSS_SQL}) as losers,
                SUM({_NEUTRAL_SQL}) as neutral,
                AVG(sp.max_gain_pct) as avg_gain_pct,
                AVG(sp.max_loss_pct) as avg_loss_pct,
                AVG(CASE WHEN sp.price_1d IS NOT NULL
                    THEN CASE WHEN s.stance = 'bearish'
                        THEN (1.0 - sp.price_1d / sp.price_at_signal) * 100
                        ELSE (sp.price_1d / sp.price_at_signal - 1.0) * 100
                    END
                    ELSE NULL END) as avg_1d_return_pct
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE s.created_at < ?
            AND sp.price_at_signal > 0
            AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
                 OR sp.max_gain_pct IS NOT NULL)
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return 0
            d = _row_to_dict(row)

        total = d.get("total_tracked", 0) or 0
        if total == 0:
            return 0

        now = time.time()
        await self.db.execute(
            """INSERT INTO win_rate_snapshots
               (snapshot_at, period_start, period_end, winners, losers, neutral,
                total_tracked, avg_gain_pct, avg_loss_pct, avg_1d_return_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                d.get("period_start", 0) or 0,
                d.get("period_end", 0) or 0,
                d.get("winners", 0) or 0,
                d.get("losers", 0) or 0,
                d.get("neutral", 0) or 0,
                total,
                d.get("avg_gain_pct"),
                d.get("avg_loss_pct"),
                d.get("avg_1d_return_pct"),
            ),
        )
        await self.db.commit()
        log.info(
            "Win-rate snapshot: %dW / %dL / %dN (total %d) from signals before %d days",
            d.get("winners", 0) or 0,
            d.get("losers", 0) or 0,
            d.get("neutral", 0) or 0,
            total,
            keep_days,
        )
        return total

    async def get_cumulative_win_rate(self, days: int = 30) -> Dict[str, Any]:
        """Get cumulative win/loss from snapshots, optionally filtered by time range.

        If days=0, returns all-time stats from snapshots.
        """
        if days > 0:
            cutoff = time.time() - (days * 86400)
            query = """
                SELECT
                    COALESCE(SUM(winners), 0) as winners,
                    COALESCE(SUM(losers), 0) as losers,
                    COALESCE(SUM(neutral), 0) as neutral,
                    COALESCE(SUM(total_tracked), 0) as total_tracked,
                    AVG(avg_gain_pct) as avg_gain_pct,
                    AVG(avg_loss_pct) as avg_loss_pct,
                    AVG(avg_1d_return_pct) as avg_1d_return_pct
                FROM win_rate_snapshots
                WHERE period_end > ?
            """
            params = (cutoff,)
        else:
            query = """
                SELECT
                    COALESCE(SUM(winners), 0) as winners,
                    COALESCE(SUM(losers), 0) as losers,
                    COALESCE(SUM(neutral), 0) as neutral,
                    COALESCE(SUM(total_tracked), 0) as total_tracked,
                    AVG(avg_gain_pct) as avg_gain_pct,
                    AVG(avg_loss_pct) as avg_loss_pct,
                    AVG(avg_1d_return_pct) as avg_1d_return_pct
                FROM win_rate_snapshots
            """
            params = ()
        async with self.db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {"winners": 0, "losers": 0, "neutral": 0,
                        "total_tracked": 0, "win_rate": 0}
            d = _row_to_dict(row)
            winners = d.get("winners", 0) or 0
            losers = d.get("losers", 0) or 0
            decided = winners + losers
            d["win_rate"] = (winners / decided * 100) if decided > 0 else 0
            return d

    # ── Storage Cleanup / Purge ──

    async def purge_old_signals(self, keep_days: int = 90) -> int:
        """Delete signals older than keep_days. Returns count deleted."""
        cutoff = time.time() - (keep_days * 86400)
        async with self.db.execute(
            "DELETE FROM signals WHERE created_at < ?", (cutoff,)
        ) as cursor:
            count = cursor.rowcount
        await self.db.commit()
        log.info("Purge: deleted %d signals older than %d days", count, keep_days)
        return count

    async def purge_duplicate_signals(self) -> int:
        """Remove duplicate signals (same post_url + ticker), keep the newest."""
        query = """
            DELETE FROM signals WHERE id NOT IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY post_url, ticker ORDER BY created_at DESC
                    ) AS rn
                    FROM signals
                    WHERE post_url != ''
                )
                WHERE rn = 1
            ) AND post_url != '' AND id IN (
                SELECT s1.id FROM signals s1
                INNER JOIN signals s2
                ON s1.post_url = s2.post_url
                AND s1.ticker = s2.ticker
                AND s1.id != s2.id
                AND s1.created_at < s2.created_at
            )
        """
        async with self.db.execute(query) as cursor:
            count = cursor.rowcount
        await self.db.commit()
        log.info("Purge: deleted %d duplicate signals", count)
        return count

    async def purge_orphaned_performance(self) -> int:
        """Delete signal_performance rows whose signal no longer exists."""
        query = """
            DELETE FROM signal_performance
            WHERE signal_id NOT IN (SELECT id FROM signals)
        """
        async with self.db.execute(query) as cursor:
            count = cursor.rowcount
        await self.db.commit()
        log.info("Purge: deleted %d orphaned performance rows", count)
        return count

    async def purge_old_performance(self, keep_days: int = 90) -> int:
        """Delete signal_performance rows older than keep_days."""
        cutoff = time.time() - (keep_days * 86400)
        async with self.db.execute(
            "DELETE FROM signal_performance WHERE checked_at < ? AND checked_at > 0",
            (cutoff,)
        ) as cursor:
            count = cursor.rowcount
        await self.db.commit()
        log.info("Purge: deleted %d old performance rows", count)
        return count

    async def purge_old_x_posts(self, keep_days: int = 30) -> int:
        """Delete x_posts older than keep_days."""
        cutoff = time.time() - (keep_days * 86400)
        async with self.db.execute(
            "DELETE FROM x_posts WHERE posted_at < ?", (cutoff,)
        ) as cursor:
            count = cursor.rowcount
        await self.db.commit()
        log.info("Purge: deleted %d old x_posts", count)
        return count

    async def purge_old_referral_clicks(self, keep_days: int = 90) -> int:
        """Delete referral_clicks older than keep_days."""
        cutoff = time.time() - (keep_days * 86400)
        async with self.db.execute(
            "DELETE FROM referral_clicks WHERE clicked_at < ?", (cutoff,)
        ) as cursor:
            count = cursor.rowcount
        await self.db.commit()
        log.info("Purge: deleted %d old referral clicks", count)
        return count

    async def purge_old_paper_trades(self, keep_days: int = 180) -> int:
        """Delete CLOSED paper_trades older than keep_days. Never touches open trades."""
        cutoff = time.time() - (keep_days * 86400)
        async with self.db.execute(
            "DELETE FROM paper_trades WHERE status = 'closed' AND closed_at < ?",
            (cutoff,)
        ) as cursor:
            count = cursor.rowcount
        await self.db.commit()
        log.info("Purge: deleted %d old closed paper trades", count)
        return count

    async def purge_stub_signals(self) -> int:
        """No-op: stub signals are now kept. The LLM is a BYOK summarizer,
        not a quality gate. Signals without LLM reasoning still have valid
        heuristic confidence from the credibility scorer."""
        return 0

    async def purge_fake_ticker_signals(self) -> int:
        """Delete signals with fake tickers (economic indicators, jargon, etc.)."""
        fake_tickers = [
            "JOLTS", "NFP", "PMI", "PCE", "PPI", "ADP", "ISM",
            "GMV", "MAU", "DAU", "ARR", "MRR", "TAM", "SAM",
            "URL", "GFC", "LSEG", "CAGR", "EBITDA", "EBIT",
        ]
        placeholders = ",".join("?" for _ in fake_tickers)
        query = f"DELETE FROM signals WHERE ticker IN ({placeholders})"
        async with self.db.execute(query, fake_tickers) as cursor:
            count = cursor.rowcount
        await self.db.commit()
        if count > 0:
            log.info("Purge: deleted %d signals with fake tickers %s", count, fake_tickers)
        return count

    async def compact_old_signal_blobs(self, older_than_days: int = 3) -> int:
        """Strip heavy JSON blobs from signals older than N days.

        After 1-day price tracking completes, market_data/reasoning/trade_idea/event_data
        are dead weight (1-10KB each). Replace with '{}' to reclaim ~80% of signal row size.
        Keeps: id, ticker, stance, confidence, event_type, strategy, sector, quality_score,
               post_title, post_url, subreddit, created_at, and all perf-related columns.
        """
        cutoff = time.time() - (older_than_days * 86400)
        query = """
            UPDATE signals
            SET market_data = '{}', reasoning = '{}', trade_idea = '{}', event_data = '{}'
            WHERE created_at < ? AND market_data != '{}'
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            count = cursor.rowcount
        if count > 0:
            await self.db.commit()
            log.info("Compact: stripped JSON blobs from %d old signals (older than %d days)", count, older_than_days)
        return count

    async def purge_old_win_rate_snapshots(self, keep_count: int = 100) -> int:
        """Keep only the most recent N win_rate_snapshots to prevent unbounded growth."""
        query = """
            DELETE FROM win_rate_snapshots
            WHERE id NOT IN (
                SELECT id FROM win_rate_snapshots ORDER BY snapshot_date DESC LIMIT ?
            )
        """
        async with self.db.execute(query, (keep_count,)) as cursor:
            count = cursor.rowcount
        if count > 0:
            await self.db.commit()
            log.info("Purge: deleted %d old win_rate_snapshots (keeping %d)", count, keep_count)
        return count

    async def purge_old_data_exports(self, keep_days: int = 30) -> int:
        """Delete data_exports records older than keep_days."""
        cutoff = time.time() - (keep_days * 86400)
        async with self.db.execute(
            "DELETE FROM data_exports WHERE requested_at < ?", (cutoff,)
        ) as cursor:
            count = cursor.rowcount
        if count > 0:
            await self.db.commit()
            log.info("Purge: deleted %d old data_export records", count)
        return count

    # ── News Feed ──

    async def get_news_feed(
        self, hours: int = 24, limit: int = 50, source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get recent signals from RSS/news sources for the live news feed."""
        cutoff = time.time() - (hours * 3600)
        conditions = ["created_at > ?"]
        params: list = [cutoff]

        _NEWS_SUBS = (
            "marketwatch", "investing-com", "yahoo-finance", "cnbc", "seekingalpha",
            "reuters", "dod-contracts", "dod-releases", "dod-news",
            "fda-press-releases", "fda-drugs", "fda-safety-alerts", "fda-recalls",
            "fda-oncology", "biopharma-dive", "drugs-com-approvals", "drugs-com-trials",
            "fed-press-releases", "stocktwits", "twitter",
        )
        if source and source in _NEWS_SUBS:
            conditions.append("subreddit = ?")
            params.append(source)
        else:
            placeholders = ",".join("?" for _ in _NEWS_SUBS)
            conditions.append(f"subreddit IN ({placeholders})")
            params.extend(_NEWS_SUBS)

        where = " AND ".join(conditions)
        query = f"""
            SELECT id, created_at, ticker, event_type, stance, confidence,
                   subreddit, post_title, post_url, sector, ai_summary
            FROM signals
            WHERE {where}
            ORDER BY created_at DESC LIMIT ?
        """
        params.append(limit)
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ── AI Summary ──

    async def get_signals_needing_ai_summary(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Find recent signals that have no ai_summary yet."""
        cutoff = time.time() - 86400  # Only summarise signals from last 24h
        async with self.db.execute(
            """SELECT id, ticker, event_type, stance, confidence, post_title, subreddit,
                      reasoning, trade_idea, market_data
               FROM signals
               WHERE ai_summary = '' AND created_at > ? AND ticker != 'UNKNOWN'
               ORDER BY confidence DESC LIMIT ?""",
            (cutoff, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def set_ai_summary(self, signal_id: str, summary: str) -> None:
        """Store a platform-generated AI summary on a signal."""
        await self.db.execute(
            "UPDATE signals SET ai_summary = ? WHERE id = ?",
            (summary[:500], signal_id),
        )
        await self.db.commit()

    # ── Paper Trading Leaderboard ──

    async def get_paper_trading_leaderboard(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Public leaderboard: top paper traders by total P&L."""
        query = """
            SELECT
                pp.user_id,
                COALESCE(SUBSTR(u.email, 1, INSTR(u.email, '@') - 1), 'anon') as username,
                pp.balance,
                pp.initial_balance,
                pp.total_pnl,
                pp.total_trades,
                pp.winning_trades,
                CASE WHEN pp.total_trades > 0
                     THEN ROUND(pp.winning_trades * 100.0 / pp.total_trades, 1)
                     ELSE 0 END as win_rate,
                ROUND(pp.total_pnl / pp.initial_balance * 100, 1) as return_pct,
                pp.last_trade_at
            FROM paper_portfolios pp
            JOIN users u ON pp.user_id = u.id
            WHERE pp.total_trades >= 3
            ORDER BY pp.total_pnl DESC
            LIMIT ?
        """
        async with self.db.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ── Congressional Trading (placeholder queries) ──

    async def get_congress_trades(
        self, days: int = 30, limit: int = 100, ticker: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get congressional trades from the congress_trades table."""
        cutoff = time.time() - (days * 86400)
        conditions = ["filed_at > ?"]
        params: list = [cutoff]
        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker.upper())
        where = " AND ".join(conditions)
        query = f"""
            SELECT * FROM congress_trades
            WHERE {where}
            ORDER BY filed_at DESC LIMIT ?
        """
        params.append(limit)
        try:
            async with self.db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception:
            return []

    async def insert_congress_trade(self, trade: Dict[str, Any]) -> Optional[str]:
        """Insert a congressional trade record."""
        trade_id = str(uuid.uuid4())[:12]
        now = time.time()
        await self.db.execute(
            """INSERT OR IGNORE INTO congress_trades
               (id, politician, party, chamber, ticker, trade_type, amount_range,
                filed_at, disclosure_date, source_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade_id,
                trade.get("politician", ""),
                trade.get("party", ""),
                trade.get("chamber", ""),
                trade.get("ticker", "").upper(),
                trade.get("trade_type", ""),
                trade.get("amount_range", ""),
                trade.get("filed_at", now),
                trade.get("disclosure_date", ""),
                trade.get("source_url", ""),
                now,
            ),
        )
        await self.db.commit()
        return trade_id

    async def get_congress_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get summary stats for congressional trading."""
        cutoff = time.time() - (days * 86400)
        try:
            async with self.db.execute(
                """SELECT COUNT(*) as total_trades,
                          COUNT(DISTINCT politician) as politicians,
                          COUNT(DISTINCT ticker) as tickers,
                          SUM(CASE WHEN trade_type = 'purchase' THEN 1 ELSE 0 END) as buys,
                          SUM(CASE WHEN trade_type = 'sale' THEN 1 ELSE 0 END) as sells
                   FROM congress_trades WHERE filed_at > ?""",
                (cutoff,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else {}
        except Exception:
            return {}

    async def purge_old_congress_trades(self, keep_days: int = 90) -> int:
        """Delete congressional trades older than keep_days."""
        cutoff = time.time() - (keep_days * 86400)
        try:
            async with self.db.execute(
                "DELETE FROM congress_trades WHERE filed_at < ?", (cutoff,)
            ) as cursor:
                count = cursor.rowcount
            await self.db.commit()
            return count
        except Exception:
            return 0

    async def get_db_size_info(self) -> Dict[str, Any]:
        """Get database size diagnostics for monitoring."""
        info: Dict[str, Any] = {}
        try:
            async with self.db.execute("PRAGMA page_count") as c:
                row = await c.fetchone()
                page_count = row[0] if row else 0
            async with self.db.execute("PRAGMA page_size") as c:
                row = await c.fetchone()
                page_size = row[0] if row else 4096
            info["db_size_bytes"] = page_count * page_size
            info["db_size_mb"] = round(info["db_size_bytes"] / (1024 * 1024), 2)

            # Row counts for major tables
            for table in ("signals", "signal_performance", "users", "win_rate_snapshots",
                          "api_usage", "x_posts", "paper_trades", "data_exports",
                          "congress_trades"):
                try:
                    async with self.db.execute(f"SELECT COUNT(*) FROM {table}") as c:
                        row = await c.fetchone()
                        info[f"{table}_rows"] = row[0] if row else 0
                except Exception:
                    info[f"{table}_rows"] = -1
        except Exception as e:
            log.warning("DB size info failed: %s", e)
        return info

    async def vacuum(self) -> None:
        """Run incremental auto-vacuum then WAL checkpoint to reclaim disk space."""
        try:
            await self.db.execute("PRAGMA incremental_vacuum(200)")  # Free up to 200 pages
        except Exception:
            pass
        try:
            await self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # Shrink WAL file
        except Exception:
            pass
        await self.db.execute("VACUUM")
        log.info("Purge: VACUUM + WAL checkpoint complete")

    async def run_full_cleanup(self) -> Dict[str, int]:
        """Run all purge methods and VACUUM. Returns summary."""
        results = {}
        try:
            results["stub_signals"] = await self.purge_stub_signals()
        except Exception as e:
            log.warning("Purge stub signals failed: %s", e)
            results["stub_signals"] = 0
        try:
            results["fake_ticker_signals"] = await self.purge_fake_ticker_signals()
        except Exception as e:
            log.warning("Purge fake ticker signals failed: %s", e)
            results["fake_ticker_signals"] = 0
        try:
            results["duplicate_signals"] = await self.purge_duplicate_signals()
        except Exception as e:
            log.warning("Purge duplicate signals failed: %s", e)
            results["duplicate_signals"] = 0
        # Snapshot win/loss data BEFORE deleting old signals
        try:
            results["win_rate_snapshot"] = await self.snapshot_win_rate_before_purge(keep_days=14)
        except Exception as e:
            log.warning("Win-rate snapshot failed: %s", e)
            results["win_rate_snapshot"] = 0
        try:
            results["old_signals"] = await self.purge_old_signals(keep_days=14)
        except Exception as e:
            log.warning("Purge old signals failed: %s", e)
            results["old_signals"] = 0
        try:
            results["orphaned_performance"] = await self.purge_orphaned_performance()
        except Exception as e:
            log.warning("Purge orphaned performance failed: %s", e)
            results["orphaned_performance"] = 0
        try:
            results["old_performance"] = await self.purge_old_performance(keep_days=14)
        except Exception as e:
            log.warning("Purge old performance failed: %s", e)
            results["old_performance"] = 0
        try:
            results["old_api_usage"] = await self.cleanup_old_api_usage(older_than_s=86400)
        except Exception as e:
            log.warning("Purge old api usage failed: %s", e)
            results["old_api_usage"] = 0
        try:
            results["old_x_posts"] = await self.purge_old_x_posts(keep_days=30)
        except Exception as e:
            log.warning("Purge old x_posts failed: %s", e)
            results["old_x_posts"] = 0
        try:
            results["old_referral_clicks"] = await self.purge_old_referral_clicks(keep_days=30)
        except Exception as e:
            log.warning("Purge old referral clicks failed: %s", e)
            results["old_referral_clicks"] = 0
        try:
            results["old_paper_trades"] = await self.purge_old_paper_trades(keep_days=60)
        except Exception as e:
            log.warning("Purge old paper trades failed: %s", e)
            results["old_paper_trades"] = 0

        # Expire stale signals (set quality_score=0 for signals past expires_at)
        try:
            results["expired_signals"] = await self.expire_stale_signals()
        except Exception as e:
            log.warning("Expire stale signals failed: %s", e)
            results["expired_signals"] = 0

        # Generate post-mortems for resolved signals that don't have one
        try:
            results["post_mortems"] = await self.generate_heuristic_post_mortems(limit=50)
        except Exception as e:
            log.warning("Post-mortem generation failed: %s", e)
            results["post_mortems"] = 0

        # Compact old signal JSON blobs (strip market_data/reasoning/trade_idea/event_data
        # from signals older than 3 days — price tracking is done by then)
        try:
            results["compacted_blobs"] = await self.compact_old_signal_blobs(older_than_days=3)
        except Exception as e:
            log.warning("Compact old signal blobs failed: %s", e)
            results["compacted_blobs"] = 0

        # Cap win_rate_snapshots to prevent unbounded growth
        try:
            results["old_snapshots"] = await self.purge_old_win_rate_snapshots(keep_count=100)
        except Exception as e:
            log.warning("Purge old win_rate_snapshots failed: %s", e)
            results["old_snapshots"] = 0

        # Clean up old data_exports records
        try:
            results["old_data_exports"] = await self.purge_old_data_exports(keep_days=30)
        except Exception as e:
            log.warning("Purge old data_exports failed: %s", e)
            results["old_data_exports"] = 0

        # Clean up old congressional trades
        try:
            results["old_congress_trades"] = await self.purge_old_congress_trades(keep_days=90)
        except Exception as e:
            log.warning("Purge old congress trades failed: %s", e)
            results["old_congress_trades"] = 0

        # Reclaim disk space
        try:
            await self.vacuum()
        except Exception as e:
            log.warning("VACUUM failed: %s", e)

        # Log DB size after cleanup for monitoring
        try:
            size_info = await self.get_db_size_info()
            log.info("DB size after cleanup: %.1f MB | signals=%d, performance=%d, users=%d",
                     size_info.get("db_size_mb", 0),
                     size_info.get("signals_rows", 0),
                     size_info.get("signal_performance_rows", 0),
                     size_info.get("users_rows", 0))
        except Exception:
            pass

        total = sum(results.values())
        log.info("Cleanup complete: %d total rows deleted/compacted | %s", total, results)
        return results

    # ── Backtest methods ──

    async def get_backtest_signals(
        self,
        days: int = 90,
        ticker: Optional[str] = None,
        stance: Optional[str] = None,
        strategy: Optional[str] = None,
        event_type: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        """Get signals with performance data for backtesting.

        Joins signals + signal_performance and returns rows with the
        fields the BacktestEngine needs: signal_id, ticker, stance,
        strategy, event_type, confidence, created_at, price_at_signal,
        price_1h, price_4h, price_1d, max_gain_pct, max_loss_pct.
        """
        cutoff = time.time() - (days * 86400)
        conditions = [
            "s.created_at > ?",
            "sp.price_at_signal > 0",
            "COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL",
        ]
        params: list = [cutoff]

        if ticker:
            conditions.append("s.ticker = ?")
            params.append(ticker.upper())
        if stance:
            conditions.append("s.stance = ?")
            params.append(stance)
        if strategy:
            conditions.append("s.strategy = ?")
            params.append(strategy)
        if event_type:
            conditions.append("s.event_type = ?")
            params.append(event_type)
        if min_confidence > 0:
            conditions.append("s.confidence >= ?")
            params.append(min_confidence)

        where = f"WHERE {' AND '.join(conditions)}"
        query = f"""
            SELECT
                s.id as signal_id,
                s.ticker,
                s.stance,
                s.strategy,
                s.event_type,
                s.confidence,
                s.created_at,
                sp.price_at_signal,
                sp.price_1h,
                sp.price_4h,
                sp.price_1d,
                sp.max_gain_pct,
                sp.max_loss_pct
            FROM signals s
            JOIN signal_performance sp ON sp.signal_id = s.id
            {where}
            ORDER BY s.created_at ASC
            LIMIT ?
        """
        params.append(limit)
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def save_backtest_run(
        self,
        user_id: str,
        name: str,
        config_json: str,
        result_json: str,
        monte_carlo_json: str = "{}",
        risk_json: str = "{}",
    ) -> str:
        """Save a backtest run. Returns the run ID."""
        run_id = str(uuid.uuid4())
        await self.db.execute(
            """INSERT INTO backtest_runs
               (id, user_id, name, config_json, result_json, monte_carlo_json, risk_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, user_id, name, config_json, result_json, monte_carlo_json, risk_json, time.time()),
        )
        await self.db.commit()
        return run_id

    async def get_user_backtests(
        self, user_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get saved backtest runs for a user (summary only)."""
        async with self.db.execute(
            """SELECT id, name, config_json, created_at
               FROM backtest_runs
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_backtest_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get a single backtest run with full data."""
        async with self.db.execute(
            "SELECT * FROM backtest_runs WHERE id = ?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def delete_backtest_run(self, run_id: str, user_id: str) -> bool:
        """Delete a backtest run (only if owned by user). Returns True if deleted."""
        cursor = await self.db.execute(
            "DELETE FROM backtest_runs WHERE id = ? AND user_id = ?",
            (run_id, user_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def save_backtest_strategy(
        self,
        user_id: str,
        name: str,
        description: str,
        config_json: str,
    ) -> str:
        """Save a named backtest strategy. Returns the strategy ID."""
        strat_id = str(uuid.uuid4())
        await self.db.execute(
            """INSERT INTO backtest_strategies
               (id, user_id, name, description, config_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (strat_id, user_id, name, description, config_json, time.time()),
        )
        await self.db.commit()
        return strat_id

    async def get_user_strategies(
        self, user_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get saved strategies for a user."""
        async with self.db.execute(
            """SELECT id, name, description, config_json, last_run_at, created_at, is_active
               FROM backtest_strategies
               WHERE user_id = ? AND is_active = 1
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_backtest_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """Get a single strategy."""
        async with self.db.execute(
            "SELECT * FROM backtest_strategies WHERE id = ?", (strategy_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_strategy_result(
        self, strategy_id: str, result_json: str
    ) -> None:
        """Update a strategy's last run result."""
        await self.db.execute(
            """UPDATE backtest_strategies
               SET last_result_json = ?, last_run_at = ?
               WHERE id = ?""",
            (result_json, time.time(), strategy_id),
        )
        await self.db.commit()

    async def delete_backtest_strategy(self, strategy_id: str, user_id: str) -> bool:
        """Soft-delete a strategy (set is_active=0). Returns True if updated."""
        cursor = await self.db.execute(
            "UPDATE backtest_strategies SET is_active = 0 WHERE id = ? AND user_id = ?",
            (strategy_id, user_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert dataclass or dict to plain dict."""
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(obj)
    if isinstance(obj, dict):
        return obj
    return {}


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert sqlite Row to dict, parsing JSON fields."""
    if row is None:
        return {}
    d = dict(row)
    for key in ("market_data", "reasoning", "trade_idea", "event_data", "settings"):
        if key in d:
            val = d[key]
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    d[key] = parsed if isinstance(parsed, dict) else {}
                except (json.JSONDecodeError, TypeError):
                    d[key] = {}
            elif not isinstance(val, dict):
                # Raw non-string, non-dict value (e.g. float, int, None) — reset to empty dict
                d[key] = {}
    return d
