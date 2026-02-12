from __future__ import annotations

import json
import uuid
import time
import logging
import aiosqlite
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


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
"""

# Columns to add to existing tables (migration-safe)
_MIGRATIONS = [
    ("users", "password_hash", "TEXT NOT NULL DEFAULT ''"),
    ("signal_performance", "created_at", "REAL NOT NULL DEFAULT 0"),
    ("signals", "sector", "TEXT NOT NULL DEFAULT ''"),
    ("signals", "sponsored", "INTEGER NOT NULL DEFAULT 0"),
    ("signals", "sponsored_by", "TEXT NOT NULL DEFAULT ''"),
]


class Database:
    def __init__(self, db_path: str = "storage/rot.db") -> None:
        self.db_path = Path(db_path)
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
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

    async def close(self) -> None:
        if self._db:
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

        await self.db.execute(
            """INSERT INTO signals
               (id, run_id, created_at, ticker, event_type, stance, time_horizon,
                confidence, trend_score, quality_score, strategy,
                subreddit, post_title, post_url,
                market_data, reasoning, trade_idea, event_data, sector)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_id,
                signal_data.get("run_id", ""),
                now,
                ticker,
                event_dict.get("event_type", "other"),
                event_dict.get("stance", "unknown"),
                event_dict.get("time_horizon", "unknown"),
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
                # Defense/DoD: signals from DoD RSS feed OR defense-sector tickers
                conditions.append(
                    "(subreddit = 'dod-contracts'"
                    " OR sector LIKE '%Aerospace%'"
                    " OR ticker IN ('LMT','RTX','NOC','GD','BA','LHX','HII','LDOS','BAH','KTOS'))"
                )
            elif source == "pharma":
                # Pharma/FDA: signals from FDA RSS feed OR healthcare-sector tickers
                conditions.append(
                    "(subreddit = 'fda-press-releases'"
                    " OR sector = 'Healthcare'"
                    " OR event_type = 'regulatory')"
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
        query = """
            SELECT
                COUNT(*) as total_signals,
                AVG(confidence) as avg_confidence,
                SUM(CASE WHEN strategy != 'none' THEN 1 ELSE 0 END) as tradeable_signals,
                SUM(CASE WHEN stance = 'bullish' THEN 1 ELSE 0 END) as bullish_count,
                SUM(CASE WHEN stance = 'bearish' THEN 1 ELSE 0 END) as bearish_count,
                SUM(CASE WHEN stance = 'mixed' THEN 1 ELSE 0 END) as mixed_count
            FROM signals
            WHERE created_at > ?
        """
        async with self.db.execute(query, (cutoff,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {"total_signals": 0}
            return _row_to_dict(row)

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
        # Use COALESCE to pick the best available price: 1d > 4h > 1h
        # 0.5% minimum threshold: ABS(price change) must exceed 0.005 to count
        query = f"""
            SELECT
                COUNT(*) as total_tracked,
                SUM(CASE
                    WHEN s.stance = 'bearish'
                         AND (sp.price_at_signal - COALESCE(sp.price_1d, sp.price_4h, sp.price_1h))
                             / sp.price_at_signal > 0.005
                    THEN 1
                    WHEN COALESCE(s.stance, 'unknown') != 'bearish'
                         AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) - sp.price_at_signal)
                             / sp.price_at_signal > 0.005
                    THEN 1
                    ELSE 0 END) as winners,
                SUM(CASE
                    WHEN s.stance = 'bearish'
                         AND (COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) - sp.price_at_signal)
                             / sp.price_at_signal > 0.005
                    THEN 1
                    WHEN COALESCE(s.stance, 'unknown') != 'bearish'
                         AND (sp.price_at_signal - COALESCE(sp.price_1d, sp.price_4h, sp.price_1h))
                             / sp.price_at_signal > 0.005
                    THEN 1
                    ELSE 0 END) as losers,
                SUM(CASE
                    WHEN ABS(COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) - sp.price_at_signal)
                         / sp.price_at_signal <= 0.005
                    THEN 1 ELSE 0 END) as neutral,
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
                return {"total_tracked": 0, "winners": 0, "losers": 0,
                        "win_rate": 0, "avg_gain_pct": 0, "avg_loss_pct": 0,
                        "neutral": 0}
            d = _row_to_dict(row)
            total = d.get("total_tracked", 0) or 0
            winners = d.get("winners", 0) or 0
            # Win rate based on decided signals only (exclude neutrals)
            decided = winners + (d.get("losers", 0) or 0)
            d["win_rate"] = (winners / decided * 100) if decided > 0 else 0
            return d

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
        query = """
            SELECT
                CAST(s.created_at / ? AS INTEGER) * ? as time_bucket,
                COUNT(*) as total,
                SUM(CASE
                    WHEN (s.stance = 'bearish' AND sp.price_1d < sp.price_at_signal)
                         OR (s.stance != 'bearish' AND sp.price_1d > sp.price_at_signal) THEN 1
                    WHEN sp.price_1d IS NULL AND (
                         (s.stance = 'bearish' AND sp.price_4h < sp.price_at_signal)
                         OR (s.stance != 'bearish' AND sp.price_4h > sp.price_at_signal)) THEN 1
                    ELSE 0 END) as winners,
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
        query = """
            SELECT
                s.strategy,
                COUNT(*) as total,
                SUM(CASE
                    WHEN (s.stance = 'bearish' AND sp.price_1d < sp.price_at_signal)
                         OR (s.stance != 'bearish' AND sp.price_1d > sp.price_at_signal) THEN 1
                    WHEN sp.price_1d IS NULL AND (
                         (s.stance = 'bearish' AND sp.price_4h < sp.price_at_signal)
                         OR (s.stance != 'bearish' AND sp.price_4h > sp.price_at_signal)) THEN 1
                    ELSE 0 END) as winners,
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
        query = """
            SELECT
                sp.ticker,
                COUNT(*) as total_signals,
                SUM(CASE
                    WHEN (s.stance = 'bearish' AND sp.price_1d < sp.price_at_signal)
                         OR (s.stance != 'bearish' AND sp.price_1d > sp.price_at_signal) THEN 1
                    WHEN sp.price_1d IS NULL AND (
                         (s.stance = 'bearish' AND sp.price_4h < sp.price_at_signal)
                         OR (s.stance != 'bearish' AND sp.price_4h > sp.price_at_signal)) THEN 1
                    ELSE 0 END) as winners,
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

    async def vacuum(self) -> None:
        """Run VACUUM to reclaim disk space after bulk deletes."""
        await self.db.execute("VACUUM")
        log.info("Purge: VACUUM complete")

    async def run_full_cleanup(self) -> Dict[str, int]:
        """Run all purge methods and VACUUM. Returns summary."""
        results = {}
        try:
            results["duplicate_signals"] = await self.purge_duplicate_signals()
        except Exception as e:
            log.warning("Purge duplicate signals failed: %s", e)
            results["duplicate_signals"] = 0
        try:
            results["old_signals"] = await self.purge_old_signals(keep_days=90)
        except Exception as e:
            log.warning("Purge old signals failed: %s", e)
            results["old_signals"] = 0
        try:
            results["orphaned_performance"] = await self.purge_orphaned_performance()
        except Exception as e:
            log.warning("Purge orphaned performance failed: %s", e)
            results["orphaned_performance"] = 0
        try:
            results["old_performance"] = await self.purge_old_performance(keep_days=90)
        except Exception as e:
            log.warning("Purge old performance failed: %s", e)
            results["old_performance"] = 0
        try:
            results["old_api_usage"] = await self.cleanup_old_api_usage(older_than_s=172800)
        except Exception as e:
            log.warning("Purge old api usage failed: %s", e)
            results["old_api_usage"] = 0
        try:
            results["old_x_posts"] = await self.purge_old_x_posts(keep_days=30)
        except Exception as e:
            log.warning("Purge old x_posts failed: %s", e)
            results["old_x_posts"] = 0
        try:
            results["old_referral_clicks"] = await self.purge_old_referral_clicks(keep_days=90)
        except Exception as e:
            log.warning("Purge old referral clicks failed: %s", e)
            results["old_referral_clicks"] = 0
        try:
            results["old_paper_trades"] = await self.purge_old_paper_trades(keep_days=180)
        except Exception as e:
            log.warning("Purge old paper trades failed: %s", e)
            results["old_paper_trades"] = 0

        # Reclaim disk space
        try:
            await self.vacuum()
        except Exception as e:
            log.warning("VACUUM failed: %s", e)

        total = sum(results.values())
        log.info("Cleanup complete: %d total rows deleted | %s", total, results)
        return results


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
