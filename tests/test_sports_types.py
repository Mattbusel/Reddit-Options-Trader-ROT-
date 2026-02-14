"""
Tests for sports betting types module (rot.sports.types).

Tests cover:
- SportsNewsItem creation and serialization
- LineMoverScore dataclass
- BettingImpact dataclass
- SportsBettingOpportunity dataclass
- Type literals and validation
- to_dict() serialization
- Frozen dataclass immutability
"""
from __future__ import annotations

import pytest

from rot.sports.types import (
    BettingImpact,
    LineMoverScore,
    SportsNewsItem,
    SportsBettingOpportunity,
)


class TestSportsNewsItem:
    """Tests for SportsNewsItem dataclass."""

    def test_minimal_creation(self):
        """Test creating a news item with minimal required fields."""
        item = SportsNewsItem(
            item_id="test123",
            headline="Patrick Mahomes injured in practice",
            source="ESPN NFL",
            published_at=1234567890.0,
            teams=["KC Chiefs"],
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=85,
            url="https://example.com/news",
        )

        assert item.item_id == "test123"
        assert item.headline == "Patrick Mahomes injured in practice"
        assert item.source == "ESPN NFL"
        assert item.published_at == 1234567890.0
        assert item.teams == ["KC Chiefs"]
        assert item.sport == "NFL"
        assert item.category == "injury"
        assert item.urgency == "high"
        assert item.line_mover_score == 85
        assert item.url == "https://example.com/news"
        # Defaults
        assert item.summary == ""
        assert item.all_categories == []
        assert item.betting_categories == []
        assert item.betting_impact is None
        assert item.ai_summary == ""
        assert item.created_at == 0.0

    def test_full_creation(self):
        """Test creating a news item with all fields populated."""
        betting_impact = BettingImpact(
            affected_markets=["spread", "total"],
            confidence=0.85,
            line_direction="up",
            magnitude="large",
            affected_teams=["KC Chiefs"],
            recommended_action="bet_now",
            notes="Star QB injury, major line movement expected",
        )

        item = SportsNewsItem(
            item_id="test456",
            headline="LeBron James ruled out for Lakers game",
            source="ESPN NBA",
            published_at=1234567891.0,
            teams=["LA Lakers", "BOS Celtics"],
            sport="NBA",
            category="injury",
            urgency="high",
            line_mover_score=92,
            url="https://example.com/lebron-out",
            summary="LeBron James has been ruled out for tonight's game against the Celtics.",
            all_categories=["injury", "lineup"],
            betting_categories=["spread_impact", "total_impact"],
            betting_impact=betting_impact,
            ai_summary="Major injury news. Lakers spread likely to move 3-5 points.",
            created_at=1234567892.0,
        )

        assert item.item_id == "test456"
        assert item.teams == ["LA Lakers", "BOS Celtics"]
        assert item.summary != ""
        assert item.all_categories == ["injury", "lineup"]
        assert item.betting_categories == ["spread_impact", "total_impact"]
        assert item.betting_impact is not None
        assert item.betting_impact.confidence == 0.85
        assert item.ai_summary == "Major injury news. Lakers spread likely to move 3-5 points."
        assert item.created_at == 1234567892.0

    def test_frozen_dataclass(self):
        """Test that SportsNewsItem is frozen (immutable)."""
        item = SportsNewsItem(
            item_id="test789",
            headline="Trade news",
            source="ESPN",
            published_at=1234567890.0,
            teams=[],
            sport="NFL",
            category="trade",
            urgency="medium",
            line_mover_score=50,
            url="https://example.com",
        )

        with pytest.raises(AttributeError):
            item.headline = "Modified headline"

        with pytest.raises(AttributeError):
            item.line_mover_score = 100

    def test_to_dict(self):
        """Test serialization to dictionary."""
        betting_impact = BettingImpact(
            affected_markets=["spread"],
            confidence=0.75,
            line_direction="down",
            magnitude="medium",
            affected_teams=["DAL Cowboys"],
            recommended_action="monitor",
            notes="Wait for injury report",
        )

        item = SportsNewsItem(
            item_id="dict_test",
            headline="Dak Prescott questionable",
            source="CBS NFL",
            published_at=1234567890.0,
            teams=["DAL Cowboys"],
            sport="NFL",
            category="injury",
            urgency="medium",
            line_mover_score=65,
            url="https://example.com/dak",
            summary="Dak Prescott listed as questionable for Sunday's game.",
            all_categories=["injury", "lineup"],
            betting_categories=["spread_impact"],
            betting_impact=betting_impact,
            ai_summary="Moderate impact, monitor injury report.",
            created_at=1234567893.0,
        )

        data = item.to_dict()

        assert isinstance(data, dict)
        assert data["item_id"] == "dict_test"
        assert data["headline"] == "Dak Prescott questionable"
        assert data["teams"] == ["DAL Cowboys"]
        assert data["line_mover_score"] == 65
        assert data["betting_impact"] is not None
        assert data["betting_impact"]["confidence"] == 0.75
        assert data["betting_impact"]["line_direction"] == "down"

    def test_to_dict_without_betting_impact(self):
        """Test to_dict() when betting_impact is None."""
        item = SportsNewsItem(
            item_id="no_impact",
            headline="General news",
            source="ESPN",
            published_at=1234567890.0,
            teams=[],
            sport="Multi",
            category="news",
            urgency="low",
            line_mover_score=10,
            url="https://example.com",
        )

        data = item.to_dict()
        assert data["betting_impact"] is None


class TestBettingImpact:
    """Tests for BettingImpact dataclass."""

    def test_creation(self):
        """Test creating a BettingImpact instance."""
        impact = BettingImpact(
            affected_markets=["spread", "total", "props"],
            confidence=0.9,
            line_direction="up",
            magnitude="large",
            affected_teams=["KC Chiefs", "BUF Bills"],
            recommended_action="bet_now",
            notes="Star player injury in high-profile matchup",
        )

        assert impact.affected_markets == ["spread", "total", "props"]
        assert impact.confidence == 0.9
        assert impact.line_direction == "up"
        assert impact.magnitude == "large"
        assert impact.affected_teams == ["KC Chiefs", "BUF Bills"]
        assert impact.recommended_action == "bet_now"
        assert impact.notes == "Star player injury in high-profile matchup"

    def test_frozen_dataclass(self):
        """Test that BettingImpact is frozen."""
        impact = BettingImpact(
            affected_markets=["spread"],
            confidence=0.5,
            line_direction="tbd",
            magnitude="small",
            affected_teams=[],
            recommended_action="wait",
        )

        with pytest.raises(AttributeError):
            impact.confidence = 0.8

    def test_default_notes(self):
        """Test that notes defaults to empty string."""
        impact = BettingImpact(
            affected_markets=[],
            confidence=0.0,
            line_direction="tbd",
            magnitude="small",
            affected_teams=[],
            recommended_action="avoid",
        )

        assert impact.notes == ""


class TestLineMoverScore:
    """Tests for LineMoverScore dataclass."""

    def test_creation(self):
        """Test creating a LineMoverScore instance."""
        score = LineMoverScore(
            total=85,
            base_category_score=40,
            severity_boost=20,
            star_player_boost=15,
            team_count_boost=5,
            recency_boost=10,
            source_boost=5,
            betting_keyword_boost=0,
        )

        assert score.total == 85
        assert score.base_category_score == 40
        assert score.severity_boost == 20
        assert score.star_player_boost == 15
        assert score.team_count_boost == 5
        assert score.recency_boost == 10
        assert score.source_boost == 5
        assert score.betting_keyword_boost == 0

    def test_frozen_dataclass(self):
        """Test that LineMoverScore is frozen."""
        score = LineMoverScore(
            total=50,
            base_category_score=25,
            severity_boost=10,
            star_player_boost=0,
            team_count_boost=5,
            recency_boost=10,
            source_boost=0,
            betting_keyword_boost=0,
        )

        with pytest.raises(AttributeError):
            score.total = 100

    def test_all_boost_components(self):
        """Test that all boost components sum correctly."""
        # This is a conceptual test - the actual scoring logic is in persistence
        base = 40
        severity = 20
        star = 15
        team = 5
        recency = 10
        source = 5
        betting = 5

        expected_total = min(100, base + severity + star + team + recency + source + betting)

        score = LineMoverScore(
            total=expected_total,
            base_category_score=base,
            severity_boost=severity,
            star_player_boost=star,
            team_count_boost=team,
            recency_boost=recency,
            source_boost=source,
            betting_keyword_boost=betting,
        )

        assert score.total == expected_total
        assert score.total <= 100


class TestSportsBettingOpportunity:
    """Tests for SportsBettingOpportunity dataclass."""

    def test_creation(self):
        """Test creating a betting opportunity."""
        opp = SportsBettingOpportunity(
            opportunity_id="opp123",
            news_item_ids=["item1", "item2", "item3"],
            primary_team="KC Chiefs",
            opponent_team="BUF Bills",
            sport="NFL",
            market_type="spread",
            recommendation="Bet Chiefs -3.5",
            confidence=0.85,
            expires_at=1234567900.0,
            reasoning="Multiple high-impact injury news favoring Chiefs",
            created_at=1234567890.0,
        )

        assert opp.opportunity_id == "opp123"
        assert len(opp.news_item_ids) == 3
        assert opp.primary_team == "KC Chiefs"
        assert opp.opponent_team == "BUF Bills"
        assert opp.sport == "NFL"
        assert opp.market_type == "spread"
        assert opp.recommendation == "Bet Chiefs -3.5"
        assert opp.confidence == 0.85
        assert opp.expires_at == 1234567900.0
        assert "injury" in opp.reasoning.lower()

    def test_frozen_dataclass(self):
        """Test that SportsBettingOpportunity is frozen."""
        opp = SportsBettingOpportunity(
            opportunity_id="opp456",
            news_item_ids=[],
            primary_team="LA Lakers",
            opponent_team="BOS Celtics",
            sport="NBA",
            market_type="total",
            recommendation="Bet under 220.5",
            confidence=0.75,
            expires_at=1234567900.0,
            reasoning="Key players out",
            created_at=1234567890.0,
        )

        with pytest.raises(AttributeError):
            opp.confidence = 0.9


class TestTypeLiterals:
    """Tests for type literal values."""

    def test_sport_league_values(self):
        """Test that all expected sport leagues can be used."""
        # These should all be valid SportLeague values
        valid_sports = ["NFL", "NBA", "MLB", "NHL", "NCAA", "Soccer", "Multi"]

        for sport in valid_sports:
            item = SportsNewsItem(
                item_id=f"test_{sport}",
                headline=f"{sport} news",
                source="ESPN",
                published_at=1234567890.0,
                teams=[],
                sport=sport,  # type: ignore
                category="news",
                urgency="low",
                line_mover_score=0,
                url="https://example.com",
            )
            assert item.sport == sport

    def test_news_category_values(self):
        """Test that all expected news categories can be used."""
        valid_categories = ["injury", "trade", "suspension", "lineup", "game", "news"]

        for category in valid_categories:
            item = SportsNewsItem(
                item_id=f"test_{category}",
                headline=f"{category} news",
                source="ESPN",
                published_at=1234567890.0,
                teams=[],
                sport="NFL",
                category=category,  # type: ignore
                urgency="low",
                line_mover_score=0,
                url="https://example.com",
            )
            assert item.category == category

    def test_urgency_level_values(self):
        """Test that all expected urgency levels can be used."""
        valid_urgencies = ["high", "medium", "low"]

        for urgency in valid_urgencies:
            item = SportsNewsItem(
                item_id=f"test_{urgency}",
                headline="Test news",
                source="ESPN",
                published_at=1234567890.0,
                teams=[],
                sport="NFL",
                category="news",
                urgency=urgency,  # type: ignore
                line_mover_score=0,
                url="https://example.com",
            )
            assert item.urgency == urgency

    def test_betting_category_values(self):
        """Test that all expected betting categories can be used."""
        valid_betting_cats = ["spread_impact", "total_impact", "prop_impact"]

        item = SportsNewsItem(
            item_id="test_betting_cats",
            headline="Test news",
            source="ESPN",
            published_at=1234567890.0,
            teams=[],
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=75,
            url="https://example.com",
            betting_categories=valid_betting_cats,
        )

        assert item.betting_categories == valid_betting_cats


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_teams_list(self):
        """Test news item with no teams."""
        item = SportsNewsItem(
            item_id="no_teams",
            headline="General sports news",
            source="ESPN",
            published_at=1234567890.0,
            teams=[],
            sport="Multi",
            category="news",
            urgency="low",
            line_mover_score=5,
            url="https://example.com",
        )

        assert item.teams == []

    def test_multiple_teams(self):
        """Test news item with many teams."""
        teams = ["KC Chiefs", "BUF Bills", "CIN Bengals", "BAL Ravens"]
        item = SportsNewsItem(
            item_id="multi_team",
            headline="AFC playoff race update",
            source="ESPN",
            published_at=1234567890.0,
            teams=teams,
            sport="NFL",
            category="game",
            urgency="medium",
            line_mover_score=35,
            url="https://example.com",
        )

        assert len(item.teams) == 4
        assert "KC Chiefs" in item.teams

    def test_zero_line_mover_score(self):
        """Test news item with zero score."""
        item = SportsNewsItem(
            item_id="zero_score",
            headline="Low impact news",
            source="ESPN",
            published_at=1234567890.0,
            teams=[],
            sport="Multi",
            category="news",
            urgency="low",
            line_mover_score=0,
            url="https://example.com",
        )

        assert item.line_mover_score == 0

    def test_max_line_mover_score(self):
        """Test news item with maximum score."""
        item = SportsNewsItem(
            item_id="max_score",
            headline="Major breaking news",
            source="ESPN",
            published_at=1234567890.0,
            teams=["KC Chiefs"],
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=100,
            url="https://example.com",
        )

        assert item.line_mover_score == 100

    def test_long_ai_summary(self):
        """Test news item with long AI summary."""
        long_summary = "A" * 1000  # 1000 character summary
        item = SportsNewsItem(
            item_id="long_summary",
            headline="Test",
            source="ESPN",
            published_at=1234567890.0,
            teams=[],
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=0,
            url="https://example.com",
            ai_summary=long_summary,
        )

        assert len(item.ai_summary) == 1000
