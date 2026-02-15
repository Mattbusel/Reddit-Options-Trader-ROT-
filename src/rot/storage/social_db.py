"""
Social Intelligence Database Mixin.

Social intelligence (authors, manipulation, propagation).
Assumes self.db (aiosqlite Connection) exists.
"""
import json
import time
import uuid


class SocialMixin:
    """
    Social intelligence (authors, manipulation, propagation).
    Assumes self.db (aiosqlite Connection) exists.
    """

    # ------------------------------------------------------------------
    # Author Profiles
    # ------------------------------------------------------------------

    async def save_author_profile(self, profile: dict) -> str:
        """Upsert an author profile. Returns the profile id."""
        pid = profile.get("id") or uuid.uuid4().hex[:16]
        now = time.time()
        stats_json = profile.get("stats", profile.get("stats_json", {}))
        if isinstance(stats_json, dict):
            stats_json = json.dumps(stats_json)
        await self.db.execute(
            """INSERT OR REPLACE INTO author_profiles
               (id, platform, username, total_signals, win_count, loss_count,
                accuracy, roi_if_followed, sharpe, reputation_score, stats_json,
                first_seen, last_seen, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid,
                profile.get("platform", "reddit"),
                profile.get("username", ""),
                profile.get("total_signals", 0),
                profile.get("win_count", 0),
                profile.get("loss_count", 0),
                profile.get("accuracy"),
                profile.get("roi_if_followed"),
                profile.get("sharpe"),
                profile.get("reputation_score"),
                stats_json,
                profile.get("first_seen", now),
                profile.get("last_seen"),
                now,
            ),
        )
        await self.db.commit()
        return pid

    async def get_author_profile(self, author_id: str) -> dict | None:
        """Get author profile by id."""
        async with self.db.execute(
            "SELECT * FROM author_profiles WHERE id = ?", (author_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["stats"] = json.loads(d.pop("stats_json", "{}"))
        return d

    async def get_author_profile_by_username(self, platform: str, username: str) -> dict | None:
        """Get author profile by platform + username."""
        async with self.db.execute(
            "SELECT * FROM author_profiles WHERE platform = ? AND username = ?",
            (platform, username),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["stats"] = json.loads(d.pop("stats_json", "{}"))
        return d

    async def get_author_leaderboard(
        self, limit: int = 50, offset: int = 0, min_predictions: int = 10
    ) -> list[dict]:
        """Get author leaderboard sorted by reputation_score DESC."""
        async with self.db.execute(
            """SELECT * FROM author_profiles
               WHERE (win_count + loss_count) >= ?
               ORDER BY reputation_score DESC, accuracy DESC
               LIMIT ? OFFSET ?""",
            (min_predictions, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["stats"] = json.loads(d.pop("stats_json", "{}"))
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Author Predictions
    # ------------------------------------------------------------------

    async def record_author_prediction(self, pred: dict) -> str:
        """Save an author prediction. Returns prediction id."""
        pid = pred.get("id") or uuid.uuid4().hex[:16]
        await self.db.execute(
            """INSERT OR IGNORE INTO author_predictions
               (id, author_id, signal_id, ticker, stance, confidence,
                outcome, pnl_pct, created_at, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid,
                pred["author_id"],
                pred.get("signal_id"),
                pred["ticker"],
                pred.get("stance", "unknown"),
                pred.get("confidence", 0.5),
                pred.get("outcome"),
                pred.get("pnl_pct"),
                pred.get("created_at", time.time()),
                pred.get("resolved_at"),
            ),
        )
        await self.db.commit()
        return pid

    async def resolve_author_prediction(
        self, prediction_id: str, outcome: str, pnl_pct: float
    ) -> None:
        """Resolve a pending prediction with outcome and P&L."""
        now = time.time()
        await self.db.execute(
            """UPDATE author_predictions
               SET outcome = ?, pnl_pct = ?, resolved_at = ?
               WHERE id = ? AND outcome IS NULL""",
            (outcome, pnl_pct, now, prediction_id),
        )
        await self.db.commit()

    async def get_author_predictions(
        self, author_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """Get predictions for an author, newest first."""
        async with self.db.execute(
            """SELECT * FROM author_predictions
               WHERE author_id = ?
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (author_id, limit, offset),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_pending_predictions(self, min_age_hours: int = 1) -> list[dict]:
        """Get unresolved predictions older than min_age_hours."""
        cutoff = time.time() - (min_age_hours * 3600)
        async with self.db.execute(
            """SELECT * FROM author_predictions
               WHERE outcome IS NULL AND created_at < ?
               ORDER BY created_at ASC""",
            (cutoff,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ------------------------------------------------------------------
    # Manipulation Alerts
    # ------------------------------------------------------------------

    async def save_manipulation_alert(self, alert: dict) -> str:
        """Save a manipulation alert. Returns alert id."""
        aid = alert.get("id") or uuid.uuid4().hex[:16]
        await self.db.execute(
            """INSERT OR IGNORE INTO manipulation_alerts
               (id, alert_type, tickers_json, authors_json, evidence_json,
                severity, detected_at, resolved)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                aid,
                alert["alert_type"],
                json.dumps(alert.get("tickers", [])),
                json.dumps(alert.get("authors", [])),
                json.dumps(alert.get("evidence", {})),
                alert.get("severity", 0.0),
                alert.get("detected_at", time.time()),
                1 if alert.get("resolved") else 0,
            ),
        )
        await self.db.commit()
        return aid

    async def get_manipulation_alerts(
        self, limit: int = 100, resolved: bool | None = None, hours: float | None = None
    ) -> list[dict]:
        """Get manipulation alerts, optionally filtered."""
        sql = "SELECT * FROM manipulation_alerts WHERE 1=1"
        params: list = []
        if resolved is not None:
            sql += " AND resolved = ?"
            params.append(1 if resolved else 0)
        if hours is not None:
            sql += " AND detected_at >= ?"
            params.append(time.time() - hours * 3600)
        sql += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)
        async with self.db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["tickers"] = json.loads(d.pop("tickers_json", "[]"))
            d["authors"] = json.loads(d.pop("authors_json", "[]"))
            d["evidence"] = json.loads(d.pop("evidence_json", "{}"))
            d["resolved"] = bool(d.get("resolved"))
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Sentiment Propagation
    # ------------------------------------------------------------------

    async def record_sentiment_propagation(self, prop: dict) -> str:
        """Save a sentiment propagation event. Returns id."""
        pid = prop.get("id") or uuid.uuid4().hex[:16]
        lag = prop.get("lag_seconds", prop.get("spread_ts", 0) - prop.get("origin_ts", 0))
        await self.db.execute(
            """INSERT OR IGNORE INTO sentiment_propagation
               (id, ticker, origin_sub, spread_to, origin_ts, spread_ts, lag_seconds, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid,
                prop["ticker"],
                prop["origin_sub"],
                prop["spread_to"],
                prop["origin_ts"],
                prop["spread_ts"],
                lag,
                prop.get("detected_at", time.time()),
            ),
        )
        await self.db.commit()
        return pid

    async def get_propagation_timeline(self, ticker: str, hours: float = 48.0) -> list[dict]:
        """Get propagation events for a ticker, sorted by origin_ts ASC."""
        cutoff = time.time() - hours * 3600
        async with self.db.execute(
            """SELECT * FROM sentiment_propagation
               WHERE ticker = ? AND origin_ts >= ?
               ORDER BY origin_ts ASC""",
            (ticker, cutoff),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_leading_sources(self, hours: float = 24.0) -> list[dict]:
        """Get sources ranked by how often they originate propagation."""
        cutoff = time.time() - hours * 3600
        async with self.db.execute(
            """SELECT origin_sub, COUNT(*) as lead_count
               FROM sentiment_propagation
               WHERE origin_ts >= ?
               GROUP BY origin_sub
               ORDER BY lead_count DESC""",
            (cutoff,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ------------------------------------------------------------------
    # Author Clusters
    # ------------------------------------------------------------------

    async def save_author_cluster(self, cluster: dict) -> str:
        """Save an author cluster. Returns cluster id."""
        cid = cluster.get("id") or uuid.uuid4().hex[:16]
        await self.db.execute(
            """INSERT OR IGNORE INTO author_clusters
               (id, authors_json, similarity_score, common_tickers_json, detected_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                cid,
                json.dumps(cluster.get("authors", [])),
                cluster.get("similarity_score", 0.0),
                json.dumps(cluster.get("common_tickers", [])),
                cluster.get("detected_at", time.time()),
            ),
        )
        await self.db.commit()
        return cid

    async def get_author_clusters(self, min_similarity: float = 0.5) -> list[dict]:
        """Get author clusters above similarity threshold."""
        async with self.db.execute(
            """SELECT * FROM author_clusters
               WHERE similarity_score >= ?
               ORDER BY similarity_score DESC""",
            (min_similarity,),
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["authors"] = json.loads(d.pop("authors_json", "[]"))
            d["common_tickers"] = json.loads(d.pop("common_tickers_json", "[]"))
            result.append(d)
        return result

