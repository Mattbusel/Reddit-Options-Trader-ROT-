"""
Sports Betting Intelligence Module — Track news, score line movers, identify opportunities.

This module provides sports news tracking with betting-focused intelligence. It combines
RSS feed ingestion, team extraction, news classification, line mover scoring, and AI
analysis to deliver actionable sports betting insights.

Key features:
- Multi-league support (NFL, NBA, MLB, NHL, NCAA, Soccer)
- Automatic team extraction from headlines
- News classification (injury, trade, suspension, lineup, game)
- Line Mover Scores (0-100 algorithmic betting impact)
- AI-generated betting analysis (Premium+)
- Historical impact analytics
- Betting opportunity detection

Architecture:
- types.py: Core data structures (SportsNewsItem, BettingImpact, etc.)
- persistence.py: High-level database operations (SportsPersistence)
- Database layer: SportsMixin in storage/sports_db.py

Usage:
    from rot.sports import SportsPersistence, SportsNewsItem
    from rot.storage.database import Database

    db = Database()
    await db.connect()

    persistence = SportsPersistence(db)
    await persistence.save_news_item(news_item)

    # Query by sport
    nfl_news = await persistence.get_news_items(sport="NFL", days=7)

    # Get trending news
    trending = await persistence.get_trending_news(limit=10)

    # Analyze historical impact
    stats = await persistence.compute_historical_impact(team="KC Chiefs", days=90)

    # Find betting opportunities
    opps = await persistence.get_betting_opportunities(min_score=70)

Exports:
    SportsPersistence: Main persistence class
    SportsNewsItem: Core news item type
    BettingImpact: Betting impact analysis type
    LineMoverScore: Line mover score breakdown
    SportsBettingOpportunity: Betting opportunity type
"""
from __future__ import annotations

from rot.sports.persistence import SportsPersistence
from rot.sports.types import (
    BettingCategory,
    BettingImpact,
    LineMoverScore,
    NewsCategory,
    SportLeague,
    SportsBettingOpportunity,
    SportsNewsItem,
    UrgencyLevel,
)

__all__ = [
    # Main persistence class
    "SportsPersistence",
    # Core data types
    "SportsNewsItem",
    "BettingImpact",
    "LineMoverScore",
    "SportsBettingOpportunity",
    # Type literals
    "SportLeague",
    "NewsCategory",
    "UrgencyLevel",
    "BettingCategory",
]
