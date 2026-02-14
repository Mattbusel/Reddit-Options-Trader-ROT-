"""
Storage cleanup mixin — all purge/archive/vacuum operations.

This module contains CleanupMixin, which handles all data retention and database
maintenance operations. It assumes self.db (aiosqlite Connection) exists.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List

log = logging.getLogger(__name__)


class CleanupMixin:
    """All purge/archive/vacuum operations. Assumes self.db (aiosqlite Connection) exists."""

    # ── Archival ──

    async def archive_before_purge(self, keep_days: int = 14) -> int:
        """Archive per-signal data before purging old signals.

        Copies essential columns from signals + signal_performance into
        signal_archive for signals about to be purged. Only archives signals
        with valid price data (resolved outcomes).
        INSERT OR IGNORE ensures idempotent re-runs.
        """
        cutoff = time.time() - (keep_days * 86400)
        now = time.time()
        query = """
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
            WHERE s.created_at < ?
              AND sp.price_at_signal > 0
              AND COALESCE(sp.price_1d, sp.price_4h, sp.price_1h) IS NOT NULL
        """
        async with self.db.execute(query, (now, cutoff)) as cursor:
            count = cursor.rowcount
        await self.db.commit()
        if count > 0:
            log.info("Archive: archived %d signals before purge (cutoff=%d days)", count, keep_days)
        return count

    async def purge_old_archives(self, keep_days: int = 365) -> int:
        """Delete archived signals older than keep_days to bound table growth."""
        cutoff = time.time() - (keep_days * 86400)
        async with self.db.execute(
            "DELETE FROM signal_archive WHERE created_at < ?", (cutoff,)
        ) as cursor:
            count = cursor.rowcount
        if count > 0:
            await self.db.commit()
            log.info("Purge: deleted %d archived signals older than %d days", count, keep_days)
        return count

    async def snapshot_win_rate_before_purge(self, keep_days: int = 14) -> int:
        """Snapshot win/loss counts for signals that are about to be purged.

        Called BEFORE purge_old_signals so the resolved outcomes are preserved
        permanently in the win_rate_snapshots table.
        """
        from rot.storage.database import _WIN_SQL, _LOSS_SQL, _NEUTRAL_SQL, _row_to_dict

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
        log.info("Snapshot: recorded %d signals (win=%d, loss=%d, neutral=%d) before purge",
                 total, d.get("winners", 0), d.get("losers", 0), d.get("neutral", 0))
        return total

    # ── Purge Operations ──

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

    async def purge_old_macro_events(self, keep_days: int = 365) -> int:
        """Purge old macro events older than keep_days. Returns count deleted."""
        cutoff = time.time() - keep_days * 86400
        cursor = await self.db.execute(
            "DELETE FROM macro_events WHERE scheduled_at < ?", (cutoff,)
        )
        deleted = cursor.rowcount
        await self.db.commit()
        return deleted

    async def purge_old_insider_trades(self, keep_days: int = 365) -> int:
        """Purge old insider trades older than keep_days. Returns count deleted."""
        cutoff = time.time() - keep_days * 86400
        cursor = await self.db.execute(
            "DELETE FROM insider_trades WHERE filing_date < ?", (cutoff,)
        )
        deleted = cursor.rowcount
        await self.db.commit()
        return deleted

    async def purge_old_earnings_events(self, keep_days: int = 365) -> int:
        """Purge old earnings events older than keep_days. Returns count deleted."""
        cutoff = time.time() - keep_days * 86400
        cursor = await self.db.execute(
            "DELETE FROM earnings_events WHERE report_date < ?", (cutoff,)
        )
        deleted = cursor.rowcount
        await self.db.commit()
        return deleted

    async def purge_old_flow_data(self, keep_days: int = 90) -> int:
        """Delete flow events, patterns, and convergences older than keep_days.
        Returns total count deleted."""
        cutoff = time.time() - (keep_days * 86400)
        total = 0

        for table in ("flow_events", "flow_patterns", "flow_convergences"):
            async with self.db.execute(
                f"SELECT COUNT(*) as cnt FROM {table} WHERE detected_at < ?",
                (cutoff,),
            ) as cursor:
                row = await cursor.fetchone()
                count = row["cnt"] if row else 0
            if count > 0:
                await self.db.execute(
                    f"DELETE FROM {table} WHERE detected_at < ?",
                    (cutoff,),
                )
                total += count

        if total > 0:
            await self.db.commit()
        return total

    async def purge_old_social_data(self, keep_days: int = 180) -> int:
        """Delete social intelligence data older than keep_days. Returns total deleted."""
        cutoff = time.time() - (keep_days * 86400)
        total = 0
        # Purge predictions
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM author_predictions WHERE created_at < ?",
            (cutoff,),
        ) as cur:
            row = await cur.fetchone()
            count = row["cnt"] if row else 0
        if count > 0:
            await self.db.execute(
                "DELETE FROM author_predictions WHERE created_at < ?", (cutoff,)
            )
            total += count
        # Purge alerts
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM manipulation_alerts WHERE detected_at < ?",
            (cutoff,),
        ) as cur:
            row = await cur.fetchone()
            count = row["cnt"] if row else 0
        if count > 0:
            await self.db.execute(
                "DELETE FROM manipulation_alerts WHERE detected_at < ?", (cutoff,)
            )
            total += count
        # Purge propagation
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM sentiment_propagation WHERE detected_at < ?",
            (cutoff,),
        ) as cur:
            row = await cur.fetchone()
            count = row["cnt"] if row else 0
        if count > 0:
            await self.db.execute(
                "DELETE FROM sentiment_propagation WHERE detected_at < ?", (cutoff,)
            )
            total += count
        # Purge clusters
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM author_clusters WHERE detected_at < ?",
            (cutoff,),
        ) as cur:
            row = await cur.fetchone()
            count = row["cnt"] if row else 0
        if count > 0:
            await self.db.execute(
                "DELETE FROM author_clusters WHERE detected_at < ?", (cutoff,)
            )
            total += count
        if total > 0:
            await self.db.commit()
        return total

    async def purge_old_strategy_data(self, keep_days: int = 90) -> int:
        """Delete old strategy trades and discovery data. Returns total deleted."""
        cutoff = time.time() - (keep_days * 86400)
        total = 0
        # Purge old resolved trades
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM strategy_trades WHERE resolved_at IS NOT NULL AND resolved_at < ?",
            (cutoff,),
        ) as cur:
            row = await cur.fetchone()
            count = row["cnt"] if row else 0
        if count > 0:
            await self.db.execute(
                "DELETE FROM strategy_trades WHERE resolved_at IS NOT NULL AND resolved_at < ?",
                (cutoff,),
            )
            total += count
        # Purge old discovery runs
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM strategy_discoveries WHERE created_at < ?",
            (cutoff,),
        ) as cur:
            row = await cur.fetchone()
            count = row["cnt"] if row else 0
        if count > 0:
            await self.db.execute(
                "DELETE FROM strategy_discoveries WHERE created_at < ?", (cutoff,)
            )
            total += count
        # Purge old regime data
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM market_regimes WHERE detected_at < ?",
            (cutoff,),
        ) as cur:
            row = await cur.fetchone()
            count = row["cnt"] if row else 0
        if count > 0:
            await self.db.execute(
                "DELETE FROM market_regimes WHERE detected_at < ?", (cutoff,)
            )
            total += count
        if total > 0:
            await self.db.commit()
        return total

    # ── Cleanup Helpers ──

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

    async def generate_heuristic_post_mortems(self, limit: int = 50) -> int:
        """Generate heuristic post-mortem text for resolved signals without one.

        This is a rule-based fallback when no LLM is available.
        """
        from rot.storage.database import Database

        # Get signals needing post-mortem
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
            signals = [dict(row) for row in rows]

        count = 0
        for sig in signals:
            try:
                pm = Database._build_post_mortem_text(sig)
                if pm:
                    await self.db.execute(
                        "UPDATE signals SET post_mortem = ? WHERE id = ?",
                        (pm[:500], sig["id"]),
                    )
                    count += 1
            except Exception as e:
                log.warning("Post-mortem generation failed for %s: %s", sig.get("id"), e)

        if count > 0:
            await self.db.commit()
        return count

    # ── Database Maintenance ──

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

    # ── Master Cleanup ──

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
        # Archive per-signal data BEFORE deleting old signals
        try:
            results["archived_signals"] = await self.archive_before_purge(keep_days=14)
        except Exception as e:
            log.warning("Signal archive failed: %s", e)
            results["archived_signals"] = 0
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

        # Purge old signal archives beyond retention window (365 days)
        try:
            results["old_archives"] = await self.purge_old_archives(keep_days=365)
        except Exception as e:
            log.warning("Purge old archives failed: %s", e)
            results["old_archives"] = 0

        # Purge old flow data
        try:
            results["old_flow_events"] = await self.purge_old_flow_data(keep_days=90)
        except Exception as e:
            log.warning("Purge old flow data failed: %s", e)
            results["old_flow_events"] = 0

        # Purge old strategy data
        try:
            results["old_strategy_data"] = await self.purge_old_strategy_data(keep_days=90)
        except Exception as e:
            log.warning("Purge old strategy data failed: %s", e)
            results["old_strategy_data"] = 0

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
