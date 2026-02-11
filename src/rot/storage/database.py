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
"""

# Columns to add to existing tables (migration-safe)
_MIGRATIONS = [
    ("users", "password_hash", "TEXT NOT NULL DEFAULT ''"),
    ("signal_performance", "created_at", "REAL NOT NULL DEFAULT 0"),
    ("signals", "sector", "TEXT NOT NULL DEFAULT ''"),
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

    async def insert_signal(self, signal_data: Dict[str, Any]) -> str:
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
            SELECT sp.*, s.created_at as signal_created_at
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE sp.price_1h IS NULL OR sp.price_4h IS NULL
                  OR sp.price_1d IS NULL OR sp.price_1w IS NULL
            ORDER BY sp.created_at ASC
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

    async def get_aggregate_accuracy(
        self, days: int = 7, ticker: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get aggregate win/loss stats for signal performance."""
        cutoff = time.time() - (days * 86400)
        conditions = ["sp.created_at > ?"]
        params: list = [cutoff]

        if ticker:
            conditions.append("sp.ticker = ?")
            params.append(ticker.upper())

        where = f"WHERE {' AND '.join(conditions)}"
        query = f"""
            SELECT
                COUNT(*) as total_tracked,
                SUM(CASE WHEN sp.max_gain_pct > 0 THEN 1 ELSE 0 END) as winners,
                SUM(CASE WHEN sp.max_gain_pct <= 0 THEN 1 ELSE 0 END) as losers,
                AVG(sp.max_gain_pct) as avg_gain_pct,
                AVG(sp.max_loss_pct) as avg_loss_pct,
                AVG(CASE WHEN sp.price_1d IS NOT NULL
                    THEN (sp.price_1d / sp.price_at_signal - 1.0) * 100
                    ELSE NULL END) as avg_1d_return_pct
            FROM signal_performance sp
            {where}
            AND sp.price_at_signal > 0
            AND (sp.price_1h IS NOT NULL OR sp.price_4h IS NOT NULL
                 OR sp.price_1d IS NOT NULL)
        """
        async with self.db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {"total_tracked": 0, "winners": 0, "losers": 0,
                        "win_rate": 0, "avg_gain_pct": 0, "avg_loss_pct": 0}
            d = _row_to_dict(row)
            total = d.get("total_tracked", 0) or 0
            winners = d.get("winners", 0) or 0
            d["win_rate"] = (winners / total * 100) if total > 0 else 0
            return d

    async def get_performance_history(
        self, days: int = 30, ticker: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get per-signal performance records."""
        cutoff = time.time() - (days * 86400)
        conditions = ["sp.created_at > ?"]
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
            ORDER BY sp.created_at DESC
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
        conditions = ["sp.created_at > ?"]
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
            ORDER BY sp.created_at DESC
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
                CAST(sp.created_at / ? AS INTEGER) * ? as time_bucket,
                COUNT(*) as total,
                SUM(CASE WHEN sp.max_gain_pct > 0 THEN 1 ELSE 0 END) as winners,
                AVG(sp.max_gain_pct) as avg_gain_pct,
                AVG(sp.max_loss_pct) as avg_loss_pct
            FROM signal_performance sp
            WHERE sp.created_at > ? AND sp.price_at_signal > 0
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
                SUM(CASE WHEN sp.max_gain_pct > 0 THEN 1 ELSE 0 END) as winners,
                AVG(sp.max_gain_pct) as avg_gain_pct,
                AVG(sp.max_loss_pct) as avg_loss_pct,
                AVG(CASE WHEN sp.price_1d IS NOT NULL
                    THEN (sp.price_1d / sp.price_at_signal - 1.0) * 100
                    ELSE NULL END) as avg_1d_return_pct
            FROM signal_performance sp
            JOIN signals s ON sp.signal_id = s.id
            WHERE sp.created_at > ? AND sp.price_at_signal > 0
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
                SUM(CASE WHEN sp.max_gain_pct > 0 THEN 1 ELSE 0 END) as winners,
                AVG(sp.max_gain_pct) as avg_gain_pct,
                AVG(sp.max_loss_pct) as avg_loss_pct
            FROM signal_performance sp
            WHERE sp.created_at > ? AND sp.price_at_signal > 0
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
                COUNT(CASE WHEN sp.max_gain_pct > 0 THEN 1 END) as perf_winners,
                COUNT(CASE WHEN sp.price_at_signal IS NOT NULL THEN 1 END) as perf_tracked
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
                  AND u.tier IN ('pro', 'premium', 'ultra')
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
