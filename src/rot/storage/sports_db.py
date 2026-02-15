"""
Sports news database operations — mixin for Database class.

This mixin handles all sports betting intelligence database operations including:
- Sports news item CRUD
- Team-based queries
- Score-based filtering
- Historical lookback with time cutoffs
- Data purging

Schema:
    sports_news table:
    - id: INTEGER PRIMARY KEY
    - item_id: TEXT UNIQUE (MD5 hash of headline+url)
    - headline: TEXT (news headline)
    - source: TEXT (feed label like "ESPN NFL")
    - published_at: REAL (unix timestamp)
    - teams_json: TEXT (JSON array of canonical team names)
    - sport: TEXT (NFL, NBA, MLB, NHL, NCAA, Soccer, Multi)
    - category: TEXT (injury, trade, suspension, lineup, game, news)
    - urgency: TEXT (high, medium, low)
    - line_mover_score: INTEGER (0-100 betting impact score)
    - betting_impact_json: TEXT (JSON object with betting analysis)
    - url: TEXT (link to original article)
    - summary: TEXT (brief description from RSS)
    - all_categories_json: TEXT (JSON array of all detected categories)
    - betting_categories_json: TEXT (JSON array of betting-specific categories)
    - ai_summary: TEXT (AI-generated betting analysis, Premium+ feature)
    - created_at: REAL (unix timestamp when saved to DB)

    Indexes:
    - idx_sports_news_published for time-based queries
    - idx_sports_news_score for high-impact filtering
    - idx_sports_news_sport for sport-specific queries
    - idx_sports_news_category for category filtering

Assumes self.db (aiosqlite Connection) exists.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class SportsMixin:
    """Sports betting intelligence database operations. Assumes self.db (aiosqlite Connection) exists."""

    # ── Schema Creation ──────────────────────────────────────────────────────

    async def _create_sports_tables(self) -> None:
        """
        Create sports_news table and indexes.

        This method is called during database initialization. It creates the
        sports_news table if it doesn't exist and sets up performance indexes.
        """
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS sports_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT UNIQUE NOT NULL,
                headline TEXT NOT NULL,
                source TEXT NOT NULL,
                published_at REAL NOT NULL,
                teams_json TEXT NOT NULL DEFAULT '[]',
                sport TEXT NOT NULL,
                category TEXT NOT NULL,
                urgency TEXT NOT NULL DEFAULT 'low',
                line_mover_score INTEGER NOT NULL DEFAULT 0,
                betting_impact_json TEXT NOT NULL DEFAULT '{}',
                url TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                all_categories_json TEXT NOT NULL DEFAULT '[]',
                betting_categories_json TEXT NOT NULL DEFAULT '[]',
                ai_summary TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )
        """)

        # Performance indexes
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_sports_news_published
            ON sports_news(published_at DESC)
        """)

        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_sports_news_score
            ON sports_news(line_mover_score DESC)
        """)

        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_sports_news_sport
            ON sports_news(sport)
        """)

        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_sports_news_category
            ON sports_news(category)
        """)

        await self.db.commit()

    # ── CRUD Operations ──────────────────────────────────────────────────────

    async def insert_sports_news(
        self,
        item_id: str,
        headline: str,
        source: str,
        published_at: float,
        teams_json: str,
        sport: str,
        category: str,
        urgency: str,
        line_mover_score: int,
        betting_impact_json: str,
        url: str,
        summary: str = "",
        all_categories_json: str = "[]",
        betting_categories_json: str = "[]",
        ai_summary: str = "",
    ) -> None:
        """
        Insert a sports news item.

        Args:
            item_id: Unique identifier (MD5 hash)
            headline: News headline
            source: Feed source label
            published_at: Unix timestamp
            teams_json: JSON array of team names
            sport: Sport/league (NFL, NBA, etc.)
            category: Primary category (injury, trade, etc.)
            urgency: Urgency level (high, medium, low)
            line_mover_score: 0-100 betting impact score
            betting_impact_json: JSON object with betting analysis
            url: Link to original article
            summary: Brief description
            all_categories_json: JSON array of all categories
            betting_categories_json: JSON array of betting categories
            ai_summary: AI-generated analysis

        Raises:
            Exception: If database insert fails
        """
        created_at = time.time()

        await self.db.execute(
            """INSERT OR REPLACE INTO sports_news
               (item_id, headline, source, published_at, teams_json, sport, category,
                urgency, line_mover_score, betting_impact_json, url, summary,
                all_categories_json, betting_categories_json, ai_summary, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id,
                headline,
                source,
                published_at,
                teams_json,
                sport,
                category,
                urgency,
                line_mover_score,
                betting_impact_json,
                url,
                summary,
                all_categories_json,
                betting_categories_json,
                ai_summary,
                created_at,
            ),
        )
        await self.db.commit()

    async def get_sports_news(
        self,
        sport: Optional[str] = None,
        category: Optional[str] = None,
        urgency: Optional[str] = None,
        min_score: int = 0,
        since_ts: float = 0.0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query sports news items with filters.

        Args:
            sport: Filter by sport (NFL, NBA, etc.). None = all sports
            category: Filter by category (injury, trade, etc.). None = all
            urgency: Filter by urgency (high, medium, low). None = all
            min_score: Minimum line mover score (0-100)
            since_ts: Unix timestamp cutoff (only return items after this time)
            limit: Maximum number of items to return

        Returns:
            List of row dictionaries sorted by published_at DESC
        """
        clauses = ["published_at >= ?"]
        params: List[Any] = [since_ts]

        if sport:
            clauses.append("sport = ?")
            params.append(sport)

        if category:
            clauses.append("category = ?")
            params.append(category)

        if urgency:
            clauses.append("urgency = ?")
            params.append(urgency)

        if min_score > 0:
            clauses.append("line_mover_score >= ?")
            params.append(min_score)

        where_clause = " AND ".join(clauses)
        params.append(limit)

        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            SELECT * FROM sports_news
            WHERE {where_clause}
            ORDER BY published_at DESC
            LIMIT ?
        """

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_sports_news_by_team(
        self,
        team_name: str,
        since_ts: float = 0.0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get all news items mentioning a specific team.

        Uses JSON LIKE query to search teams_json array. Not the most performant
        but works for moderate data volumes. For high-volume production use,
        consider adding a separate teams junction table.

        Args:
            team_name: Canonical team name (e.g., "KC Chiefs")
            since_ts: Unix timestamp cutoff
            limit: Maximum number of items to return

        Returns:
            List of row dictionaries sorted by published_at DESC
        """
        # Use LIKE to search within JSON array
        # teams_json format: ["KC Chiefs", "BUF Bills"]
        # This will match any team name substring
        team_pattern = f'%"{team_name}"%'

        query = """
            SELECT * FROM sports_news
            WHERE published_at >= ?
              AND teams_json LIKE ?
            ORDER BY published_at DESC
            LIMIT ?
        """

        async with self.db.execute(query, (since_ts, team_pattern, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_sports_news_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single news item by item_id.

        Args:
            item_id: Unique item identifier

        Returns:
            Row dictionary or None if not found
        """
        async with self.db.execute(
            "SELECT * FROM sports_news WHERE item_id = ?",
            (item_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_sports_news_ai_summary(
        self,
        item_id: str,
        ai_summary: str,
    ) -> bool:
        """
        Update AI summary for a news item.

        This allows lazy AI summary generation — items can be saved without AI
        summaries and updated later when AI processing completes.

        Args:
            item_id: Unique item identifier
            ai_summary: AI-generated betting analysis

        Returns:
            True if updated, False if item not found
        """
        cursor = await self.db.execute(
            "UPDATE sports_news SET ai_summary = ? WHERE item_id = ?",
            (ai_summary, item_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    # ── Analytics & Stats ─────────────────────────────────────────────────────

    async def get_sports_news_count(
        self,
        sport: Optional[str] = None,
        since_ts: float = 0.0,
    ) -> int:
        """
        Get total count of news items matching filters.

        Args:
            sport: Filter by sport. None = all sports
            since_ts: Unix timestamp cutoff

        Returns:
            Count of matching items
        """
        if sport:
            query = "SELECT COUNT(*) FROM sports_news WHERE sport = ? AND published_at >= ?"
            params = (sport, since_ts)
        else:
            query = "SELECT COUNT(*) FROM sports_news WHERE published_at >= ?"
            params = (since_ts,)

        async with self.db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_top_scored_news(
        self,
        limit: int = 10,
        since_ts: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Get highest-scored news items (for trending/highlights).

        Args:
            limit: Maximum number of items
            since_ts: Unix timestamp cutoff

        Returns:
            List of row dictionaries sorted by line_mover_score DESC
        """
        query = """
            SELECT * FROM sports_news
            WHERE published_at >= ?
            ORDER BY line_mover_score DESC, published_at DESC
            LIMIT ?
        """

        async with self.db.execute(query, (since_ts, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ── Data Purging ──────────────────────────────────────────────────────────

    async def purge_old_sports_news(self, before_ts: float) -> int:
        """
        Delete sports news older than a given timestamp.

        Args:
            before_ts: Unix timestamp cutoff (delete items published before this)

        Returns:
            Number of items deleted
        """
        cursor = await self.db.execute(
            "DELETE FROM sports_news WHERE published_at < ?",
            (before_ts,),
        )
        await self.db.commit()
        return cursor.rowcount
