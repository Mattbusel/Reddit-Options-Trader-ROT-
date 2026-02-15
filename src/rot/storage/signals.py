"""
Signal CRUD Operations Mixin

This module contains all database operations related to the signals, signal_performance,
and signal_archive tables.

Extracted from database.py for better modularity and maintainability.
"""
from __future__ import annotations

import json
import uuid
import time
import logging
from typing import Any, Dict, List, Optional

from .sql_helpers import (
    _WIN_SQL,
    _LOSS_SQL,
    _NEUTRAL_SQL,
    _UNIFIED_CTE,
)

log = logging.getLogger(__name__)


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert dataclass or dict to dict."""
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return dict(obj) if obj else {}


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert aiosqlite Row to dict."""
    return dict(row) if row else {}


class SignalsMixin:
    """
    Signal CRUD operations. Assumes self.db (aiosqlite Connection) exists.

    This mixin handles all operations on:
    - signals table (core signal storage)
    - signal_performance table (price tracking)
    - signal_archive table (long-term retention)

    Methods are organized into logical groups:
    - Insert/Update/Query signals
    - Signal performance tracking
    - Post-mortem analysis
    - Trending/aggregation
    - Unusual activity detection
    """

    # ── Signal Insert/Update/Query ──

    async def insert_signal(self, signal_data: Dict[str, Any]) -> Optional[str]:
        """
        Insert a new signal into the database.

        Args:
            signal_data: Dict containing:
                - event: Event dataclass/dict
                - reasoning: ReasoningPacket dataclass/dict
                - trade_idea: TradeIdea dataclass/dict
                - run_id: Pipeline run ID (optional)

        Returns:
            Signal ID (str) if inserted, None if duplicate detected
        """
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
        """
        Query signals with filters.

        Args:
            limit: Max signals to return
            offset: Skip N signals
            ticker: Filter by ticker symbol
            stance: Filter by stance (bullish/bearish/mixed/unknown)
            min_confidence: Minimum confidence threshold
            event_type: Filter by event type
            date_from: Unix timestamp lower bound
            date_to: Unix timestamp upper bound
            source: Source filter (supports groups: reddit, rss, defense, pharma)

        Returns:
            List of signal dicts
        """
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
        query = f"SELECT * FROM signals {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"  # nosec B608 - SQL uses constants only, values parameterized
        params.extend([limit, offset])

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]

    async def get_signal(self, signal_id: str) -> Optional[Dict[str, Any]]:
        """Get a single signal by ID."""
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
        """
        Update arbitrary columns on a signal row.

        Only allowed fields: confidence, stance, event_type, strategy, time_horizon
        """
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

    async def get_signal_count(self) -> int:
        """Get total signal count."""
        async with self.db.execute("SELECT COUNT(*) FROM signals") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_signals_since(self, timestamp: float) -> int:
        """Count signals created after the given timestamp."""
        async with self.db.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at > ?", (timestamp,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_signals_for_ticker(
        self, ticker: str, limit: int = 10, days: int = 7,
    ) -> List[Dict[str, Any]]:
        """Get recent signals for a ticker (used by insider cross-reference)."""
        cutoff = time.time() - days * 86400
        async with self.db.execute(
            """SELECT id, stance, confidence, created_at
               FROM signals
               WHERE ticker = ? AND created_at >= ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (ticker, cutoff, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── Signal Performance Tracking ──

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
        query = f"UPDATE signal_performance SET {', '.join(set_clauses)} WHERE id = ?"  # nosec B608 - SQL uses constants only, values parameterized
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
        """
        One-time recalculation of max_gain_pct/max_loss_pct with stance awareness.

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

    # ── Signal Corroboration ──

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
        """
        Mark signals past their expires_at as expired (set confidence to 0).
        Returns count of expired signals.
        """
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
        """
        Generate heuristic post-mortem text for resolved signals without one.

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
            won = False

        outcome = "WIN" if won else "LOSS" if abs_pct > threshold else "NEUTRAL"

        lines = [
            f"[{outcome}] {ticker} {stance.upper()} signal",
            f"Price moved {direction} {abs_pct:.1f}% (${price_at:.2f} → ${price_now:.2f})",
            f"Confidence: {confidence:.2f} | Strategy: {strategy} | Type: {event_type}",
        ]

        if won:
            lines.append("✓ Thesis played out as expected.")
        elif outcome == "LOSS":
            lines.append("✗ Price moved against prediction.")
        else:
            lines.append("○ Price moved within noise threshold (±0.5%).")

        return " | ".join(lines)

    # ── Trending Tickers ──

    async def get_trending_tickers(self, hours: int = 24, limit: int = 20) -> List[Dict[str, Any]]:
        """Get trending tickers by signal count."""
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

    # ── Unusual Activity ──

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
