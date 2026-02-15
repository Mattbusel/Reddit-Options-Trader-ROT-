"""
Sports Tracker Persistence — Database operations for sports betting intelligence.

This module provides the SportsPersistence class that handles all database operations
for sports news tracking. It wraps the database SportsMixin and provides high-level
methods for saving, querying, and analyzing sports news data.

Key responsibilities:
- Save sports news items to database
- Query news by sport, team, category, date range
- Compute historical betting impact for teams/categories
- Identify high-value betting opportunities
- Purge old news items

Usage:
    from rot.sports import SportsPersistence
    from rot.storage.database import Database

    db = Database()
    await db.connect()

    persistence = SportsPersistence(db)
    await persistence.save_news_item(news_item)
    items = await persistence.get_news_items(sport="NFL", days=7)
    trending = await persistence.get_trending_news(limit=10)

Exports:
    SportsPersistence: Main persistence class
"""
from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from rot.sports.types import (
    BettingImpact,
    NewsCategory,
    SportLeague,
    SportsNewsItem,
    UrgencyLevel,
)

if TYPE_CHECKING:
    from rot.storage.database import Database

log = logging.getLogger(__name__)


class SportsPersistence:
    """
    High-level persistence layer for sports betting intelligence.

    This class wraps the database SportsMixin and provides clean, typed methods
    for working with sports news data. It handles serialization/deserialization
    of complex types and provides analytics queries.

    Attributes:
        db: Database instance with SportsMixin
    """

    def __init__(self, db: Database) -> None:
        """
        Initialize persistence layer.

        Args:
            db: Connected Database instance with SportsMixin
        """
        self.db = db

    async def save_news_item(self, item: SportsNewsItem) -> None:
        """
        Save a sports news item to the database.

        Args:
            item: SportsNewsItem to persist

        Raises:
            Exception: If database insert fails
        """
        # Serialize betting impact to JSON
        betting_impact_json = json.dumps({
            "affected_markets": item.betting_impact.affected_markets,
            "confidence": item.betting_impact.confidence,
            "line_direction": item.betting_impact.line_direction,
            "magnitude": item.betting_impact.magnitude,
            "affected_teams": item.betting_impact.affected_teams,
            "recommended_action": item.betting_impact.recommended_action,
            "notes": item.betting_impact.notes,
        }) if item.betting_impact else "{}"

        await self.db.insert_sports_news(
            item_id=item.item_id,
            headline=item.headline,
            source=item.source,
            published_at=item.published_at,
            teams_json=json.dumps(item.teams),
            sport=item.sport,
            category=item.category,
            urgency=item.urgency,
            line_mover_score=item.line_mover_score,
            betting_impact_json=betting_impact_json,
            url=item.url,
            summary=item.summary,
            all_categories_json=json.dumps(item.all_categories),
            betting_categories_json=json.dumps(item.betting_categories),
            ai_summary=item.ai_summary,
        )

        log.debug("Saved sports news item: %s (score=%d, sport=%s)",
                  item.item_id, item.line_mover_score, item.sport)

    async def get_news_items(
        self,
        sport: Optional[SportLeague] = None,
        days: int = 7,
        category: Optional[NewsCategory] = None,
        urgency: Optional[UrgencyLevel] = None,
        min_score: int = 0,
        limit: int = 100,
    ) -> List[SportsNewsItem]:
        """
        Query sports news items with filters.

        Args:
            sport: Filter by sport/league (NFL, NBA, etc.). None = all sports
            days: Number of days to look back (default: 7)
            category: Filter by news category (injury, trade, etc.). None = all
            urgency: Filter by urgency level (high, medium, low). None = all
            min_score: Minimum line mover score (0-100)
            limit: Maximum number of items to return

        Returns:
            List of SportsNewsItem objects matching filters, sorted by published_at desc
        """
        cutoff = time.time() - (days * 86400)
        rows = await self.db.get_sports_news(
            sport=sport,
            category=category,
            urgency=urgency,
            min_score=min_score,
            since_ts=cutoff,
            limit=limit,
        )

        items = []
        for row in rows:
            items.append(self._row_to_news_item(row))

        return items

    async def get_trending_news(
        self,
        limit: int = 10,
        min_hours: int = 24,
    ) -> List[SportsNewsItem]:
        """
        Get trending sports news (highest line mover scores, recent).

        Args:
            limit: Maximum number of items to return
            min_hours: Only consider news from last N hours (default: 24)

        Returns:
            List of SportsNewsItem objects sorted by line_mover_score desc
        """
        cutoff = time.time() - (min_hours * 3600)
        rows = await self.db.get_sports_news(
            min_score=50,  # Only high-impact news trends
            since_ts=cutoff,
            limit=limit * 2,  # Fetch extra to account for dedup
        )

        items = [self._row_to_news_item(row) for row in rows]

        # Sort by line mover score descending
        items.sort(key=lambda x: x.line_mover_score, reverse=True)

        return items[:limit]

    async def get_news_by_team(
        self,
        team_name: str,
        days: int = 30,
        limit: int = 50,
    ) -> List[SportsNewsItem]:
        """
        Get all news items mentioning a specific team.

        Args:
            team_name: Canonical team name (e.g., "KC Chiefs", "LA Lakers")
            days: Number of days to look back
            limit: Maximum number of items to return

        Returns:
            List of SportsNewsItem objects mentioning the team, sorted by published_at desc
        """
        cutoff = time.time() - (days * 86400)
        rows = await self.db.get_sports_news_by_team(
            team_name=team_name,
            since_ts=cutoff,
            limit=limit,
        )

        return [self._row_to_news_item(row) for row in rows]

    async def compute_historical_impact(
        self,
        team: Optional[str] = None,
        category: Optional[NewsCategory] = None,
        days: int = 90,
    ) -> Dict[str, Any]:
        """
        Compute historical betting impact statistics.

        Analyzes past news items to compute average line mover scores, category
        distributions, and betting impact patterns for a team or category.

        Args:
            team: Optional team name to filter by
            category: Optional news category to filter by
            days: Number of days of history to analyze

        Returns:
            Dictionary with statistics:
            {
                "total_items": int,
                "avg_line_mover_score": float,
                "max_line_mover_score": int,
                "category_distribution": {category: count},
                "urgency_distribution": {urgency: count},
                "avg_score_by_category": {category: avg_score},
                "high_impact_count": int (score >= 70),
                "medium_impact_count": int (40 <= score < 70),
                "low_impact_count": int (score < 40),
            }
        """
        cutoff = time.time() - (days * 86400)

        if team:
            rows = await self.db.get_sports_news_by_team(
                team_name=team,
                since_ts=cutoff,
                limit=1000,
            )
        else:
            rows = await self.db.get_sports_news(
                category=category,
                since_ts=cutoff,
                limit=1000,
            )

        if not rows:
            return {
                "total_items": 0,
                "avg_line_mover_score": 0.0,
                "max_line_mover_score": 0,
                "category_distribution": {},
                "urgency_distribution": {},
                "avg_score_by_category": {},
                "high_impact_count": 0,
                "medium_impact_count": 0,
                "low_impact_count": 0,
            }

        total_items = len(rows)
        scores = [row["line_mover_score"] for row in rows]
        avg_score = sum(scores) / len(scores)
        max_score = max(scores)

        # Category distribution
        category_dist: Dict[str, int] = {}
        for row in rows:
            cat = row["category"]
            category_dist[cat] = category_dist.get(cat, 0) + 1

        # Urgency distribution
        urgency_dist: Dict[str, int] = {}
        for row in rows:
            urg = row["urgency"]
            urgency_dist[urg] = urgency_dist.get(urg, 0) + 1

        # Average score by category
        category_scores: Dict[str, List[int]] = {}
        for row in rows:
            cat = row["category"]
            score = row["line_mover_score"]
            if cat not in category_scores:
                category_scores[cat] = []
            category_scores[cat].append(score)

        avg_by_category = {
            cat: sum(scores) / len(scores)
            for cat, scores in category_scores.items()
        }

        # Impact level counts
        high_count = sum(1 for s in scores if s >= 70)
        medium_count = sum(1 for s in scores if 40 <= s < 70)
        low_count = sum(1 for s in scores if s < 40)

        return {
            "total_items": total_items,
            "avg_line_mover_score": round(avg_score, 2),
            "max_line_mover_score": max_score,
            "category_distribution": category_dist,
            "urgency_distribution": urgency_dist,
            "avg_score_by_category": {k: round(v, 2) for k, v in avg_by_category.items()},
            "high_impact_count": high_count,
            "medium_impact_count": medium_count,
            "low_impact_count": low_count,
        }

    async def get_betting_opportunities(
        self,
        min_score: int = 70,
        max_age_hours: int = 12,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Identify high-value betting opportunities from recent news.

        Analyzes recent high-impact news to suggest actionable betting opportunities.
        Groups related news items by team and provides betting recommendations.

        Args:
            min_score: Minimum line mover score to consider (default: 70)
            max_age_hours: Only consider news from last N hours (default: 12)
            limit: Maximum number of opportunities to return

        Returns:
            List of opportunity dictionaries:
            {
                "team": str,
                "sport": str,
                "news_items": [SportsNewsItem],
                "combined_score": int,
                "recommended_markets": [str],
                "urgency": str,
                "reasoning": str,
            }
        """
        cutoff = time.time() - (max_age_hours * 3600)
        rows = await self.db.get_sports_news(
            min_score=min_score,
            since_ts=cutoff,
            limit=100,
        )

        if not rows:
            return []

        # Group by team
        team_news: Dict[str, List[SportsNewsItem]] = {}
        for row in rows:
            item = self._row_to_news_item(row)
            for team in item.teams:
                if team not in team_news:
                    team_news[team] = []
                team_news[team].append(item)

        opportunities = []
        for team, items in team_news.items():
            if not items:
                continue

            # Compute combined impact
            combined_score = sum(i.line_mover_score for i in items) // len(items)

            # Aggregate recommended markets
            markets: set = set()
            for item in items:
                if item.betting_impact:
                    markets.update(item.betting_impact.affected_markets)

            # Determine urgency
            max_urgency = "low"
            if any(i.urgency == "high" for i in items):
                max_urgency = "high"
            elif any(i.urgency == "medium" for i in items):
                max_urgency = "medium"

            # Build reasoning
            categories = [i.category for i in items]
            reasoning = f"{len(items)} high-impact news item(s) for {team}: {', '.join(set(categories))}. "
            reasoning += f"Combined line mover score: {combined_score}. "

            if markets:
                reasoning += f"Affected markets: {', '.join(markets)}."

            opportunities.append({
                "team": team,
                "sport": items[0].sport,
                "news_items": items,
                "combined_score": combined_score,
                "recommended_markets": sorted(markets),
                "urgency": max_urgency,
                "reasoning": reasoning,
            })

        # Sort by combined score descending
        opportunities.sort(key=lambda x: x["combined_score"], reverse=True)

        return opportunities[:limit]

    async def purge_old_news(self, days: int = 90) -> int:
        """
        Delete sports news older than N days.

        Args:
            days: Delete news older than this many days (default: 90)

        Returns:
            Number of items deleted
        """
        cutoff = time.time() - (days * 86400)
        deleted = await self.db.purge_old_sports_news(before_ts=cutoff)

        if deleted > 0:
            log.info("Purged %d sports news items older than %d days", deleted, days)

        return deleted

    def _row_to_news_item(self, row: Dict[str, Any]) -> SportsNewsItem:
        """
        Convert database row to SportsNewsItem.

        Args:
            row: Database row dict

        Returns:
            SportsNewsItem instance
        """
        # Parse JSON fields
        teams = json.loads(row.get("teams_json", "[]"))
        all_categories = json.loads(row.get("all_categories_json", "[]"))
        betting_categories = json.loads(row.get("betting_categories_json", "[]"))

        # Parse betting impact
        betting_impact = None
        betting_impact_json = row.get("betting_impact_json", "{}")
        if betting_impact_json and betting_impact_json != "{}":
            impact_data = json.loads(betting_impact_json)
            if impact_data:
                betting_impact = BettingImpact(
                    affected_markets=impact_data.get("affected_markets", []),
                    confidence=impact_data.get("confidence", 0.0),
                    line_direction=impact_data.get("line_direction", "tbd"),
                    magnitude=impact_data.get("magnitude", "small"),
                    affected_teams=impact_data.get("affected_teams", []),
                    recommended_action=impact_data.get("recommended_action", "monitor"),
                    notes=impact_data.get("notes", ""),
                )

        return SportsNewsItem(
            item_id=row["item_id"],
            headline=row["headline"],
            source=row["source"],
            published_at=row["published_at"],
            teams=teams,
            sport=row["sport"],
            category=row["category"],
            urgency=row["urgency"],
            line_mover_score=row["line_mover_score"],
            url=row["url"],
            summary=row.get("summary", ""),
            all_categories=all_categories,
            betting_categories=betting_categories,
            betting_impact=betting_impact,
            ai_summary=row.get("ai_summary", ""),
            created_at=row.get("created_at", 0.0),
        )
