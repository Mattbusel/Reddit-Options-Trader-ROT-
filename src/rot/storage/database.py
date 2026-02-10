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
"""

# Columns to add to existing tables (migration-safe)
_MIGRATIONS = [
    ("users", "password_hash", "TEXT NOT NULL DEFAULT ''"),
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

        await self.db.execute(
            """INSERT INTO signals
               (id, run_id, created_at, ticker, event_type, stance, time_horizon,
                confidence, trend_score, quality_score, strategy,
                subreddit, post_title, post_url,
                market_data, reasoning, trade_idea, event_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                json.dumps(meta.get("market", {})),
                json.dumps(reasoning_dict),
                json.dumps(idea_dict),
                json.dumps(event_dict),
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
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d
