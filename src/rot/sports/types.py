"""
Sports Tracker Types — Data structures for sports betting intelligence.

This module defines the core data types for sports news tracking, betting impact
analysis, and line mover scoring. All types are frozen dataclasses following the
ROT pattern established in rot.core.types.

Exports:
    SportsNewsItem: Core news item with classification and teams
    LineMoverScore: Detailed line movement impact scoring
    BettingImpact: Betting-specific impact analysis
    SportLeague: Literal type for supported sports leagues
    NewsCategory: Literal type for news classification
    UrgencyLevel: Literal type for urgency classification
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Any

# Type definitions for sports leagues
SportLeague = Literal["NFL", "NBA", "MLB", "NHL", "NCAA", "Soccer", "Multi"]

# News category types
NewsCategory = Literal["injury", "trade", "suspension", "lineup", "game", "news"]

# Urgency levels
UrgencyLevel = Literal["high", "medium", "low"]

# Betting impact categories
BettingCategory = Literal["spread_impact", "total_impact", "prop_impact"]


@dataclass(frozen=True)
class LineMoverScore:
    """
    Detailed line mover scoring breakdown.

    Line Mover Score is a 0-100 algorithmic score indicating likelihood that
    this news will move betting lines. Higher scores indicate stronger impact.

    Attributes:
        total: Final computed score (0-100)
        base_category_score: Base score from news category (injury=40, suspension=35, etc.)
        severity_boost: Boost from injury severity (high-impact keywords)
        star_player_boost: Boost for star player involvement
        team_count_boost: Boost for multi-team matchup context
        recency_boost: Boost for very recent news (<6 hours)
        source_boost: Boost for credible sources (ESPN, CBS)
        betting_keyword_boost: Boost for betting-related keywords
    """
    total: int
    base_category_score: int
    severity_boost: int
    star_player_boost: int
    team_count_boost: int
    recency_boost: int
    source_boost: int
    betting_keyword_boost: int


@dataclass(frozen=True)
class BettingImpact:
    """
    Betting-specific impact analysis.

    This dataclass captures the specific betting markets affected by a news item
    and provides actionable intelligence for bettors.

    Attributes:
        affected_markets: List of betting markets impacted (spread, total, props, etc.)
        confidence: Confidence level in the impact assessment (0.0-1.0)
        line_direction: Expected direction of line movement (up, down, tbd)
        magnitude: Expected magnitude of movement (small, medium, large)
        affected_teams: Teams directly affected by the news
        recommended_action: Suggested betting action (wait, bet_now, avoid, etc.)
        notes: Additional context or warnings
    """
    affected_markets: List[str]
    confidence: float  # 0.0-1.0
    line_direction: str  # "up", "down", "tbd"
    magnitude: str  # "small", "medium", "large"
    affected_teams: List[str]
    recommended_action: str  # "wait", "bet_now", "avoid", "monitor"
    notes: str = ""


@dataclass(frozen=True)
class SportsNewsItem:
    """
    Core sports news item with full classification and analysis.

    This is the primary data structure for sports news tracked by ROT. It combines
    RSS feed data with intelligent classification, team extraction, betting impact
    analysis, and AI-generated summaries.

    Attributes:
        item_id: Unique identifier (MD5 hash of title+link)
        headline: News headline/title
        source: Feed source label (e.g., "ESPN NFL", "CBS NBA")
        published_at: Unix timestamp of publication
        teams: List of canonical team names extracted from headline/summary
        sport: Sport/league (NFL, NBA, MLB, NHL, NCAA, Soccer, Multi)
        category: Primary news category (injury, trade, suspension, lineup, game, news)
        urgency: Urgency level (high, medium, low)
        line_mover_score: 0-100 line movement likelihood score
        betting_impact: Detailed betting impact analysis (optional)
        url: Link to original article
        summary: Brief summary/description from RSS feed
        all_categories: All detected categories (list)
        betting_categories: Betting-specific categories (spread_impact, total_impact, prop_impact)
        ai_summary: AI-generated betting analysis (Premium+ feature)
        created_at: Timestamp when item was saved to database
    """
    item_id: str
    headline: str
    source: str
    published_at: float
    teams: List[str]
    sport: SportLeague
    category: NewsCategory
    urgency: UrgencyLevel
    line_mover_score: int
    url: str
    summary: str = ""
    all_categories: List[NewsCategory] = field(default_factory=list)
    betting_categories: List[BettingCategory] = field(default_factory=list)
    betting_impact: BettingImpact | None = None
    ai_summary: str = ""
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "item_id": self.item_id,
            "headline": self.headline,
            "source": self.source,
            "published_at": self.published_at,
            "teams": self.teams,
            "sport": self.sport,
            "category": self.category,
            "urgency": self.urgency,
            "line_mover_score": self.line_mover_score,
            "url": self.url,
            "summary": self.summary,
            "all_categories": self.all_categories,
            "betting_categories": self.betting_categories,
            "betting_impact": {
                "affected_markets": self.betting_impact.affected_markets,
                "confidence": self.betting_impact.confidence,
                "line_direction": self.betting_impact.line_direction,
                "magnitude": self.betting_impact.magnitude,
                "affected_teams": self.betting_impact.affected_teams,
                "recommended_action": self.betting_impact.recommended_action,
                "notes": self.betting_impact.notes,
            } if self.betting_impact else None,
            "ai_summary": self.ai_summary,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SportsBettingOpportunity:
    """
    High-value betting opportunity identified from recent news.

    This type represents actionable betting opportunities detected by analyzing
    recent sports news with high line mover scores and betting impact.

    Attributes:
        opportunity_id: Unique identifier for the opportunity
        news_item_ids: List of news item IDs contributing to this opportunity
        primary_team: Main team affected
        opponent_team: Opponent team (if known)
        sport: Sport/league
        market_type: Betting market (spread, total, props, moneyline)
        recommendation: Specific betting recommendation
        confidence: Confidence in recommendation (0.0-1.0)
        expires_at: Unix timestamp when opportunity expires (game time, etc.)
        reasoning: Explanation of why this is an opportunity
        created_at: Timestamp when opportunity was identified
    """
    opportunity_id: str
    news_item_ids: List[str]
    primary_team: str
    opponent_team: str
    sport: SportLeague
    market_type: str
    recommendation: str
    confidence: float
    expires_at: float
    reasoning: str
    created_at: float
