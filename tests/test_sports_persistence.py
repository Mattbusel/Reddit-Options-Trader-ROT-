"""
Tests for sports persistence layer (rot.sports.persistence.SportsPersistence).

Tests cover:
- save_news_item()
- get_news_items() with various filters
- get_trending_news()
- get_news_by_team()
- compute_historical_impact()
- get_betting_opportunities()
- purge_old_news()
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from rot.sports import SportsPersistence, SportsNewsItem, BettingImpact
from rot.storage.database import Database


@pytest.fixture
async def db():
    """Create a temporary test database."""
    db_path = Path("test_sports_persistence.db")
    database = Database(str(db_path))
    await database.connect()
    yield database
    await database.close()
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
async def persistence(db):
    """Create SportsPersistence instance."""
    return SportsPersistence(db)


@pytest.fixture
def sample_news_item():
    """Create a sample SportsNewsItem for testing."""
    return SportsNewsItem(
        item_id="test_nfl_injury_001",
        headline="Patrick Mahomes ruled out for Week 10",
        source="ESPN NFL",
        published_at=time.time(),
        teams=["KC Chiefs"],
        sport="NFL",
        category="injury",
        urgency="high",
        line_mover_score=92,
        url="https://example.com/mahomes-injury",
        summary="Patrick Mahomes has been ruled out with a high ankle sprain.",
        all_categories=["injury", "lineup"],
        betting_categories=["spread_impact", "total_impact", "prop_impact"],
        betting_impact=BettingImpact(
            affected_markets=["spread", "total", "props"],
            confidence=0.95,
            line_direction="up",
            magnitude="large",
            affected_teams=["KC Chiefs", "BUF Bills"],
            recommended_action="bet_now",
            notes="Star QB out, expect 6-7 point line movement",
        ),
        ai_summary="Major injury to star QB. Spread will move significantly.",
        created_at=time.time(),
    )


class TestSaveNewsItem:
    """Tests for save_news_item()."""

    async def test_save_minimal_item(self, persistence):
        """Test saving a minimal news item."""
        item = SportsNewsItem(
            item_id="minimal_001",
            headline="Test headline",
            source="ESPN",
            published_at=time.time(),
            teams=[],
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=10,
            url="https://example.com/test",
        )

        await persistence.save_news_item(item)

        # Verify it was saved
        retrieved = await persistence.db.get_sports_news_by_id("minimal_001")
        assert retrieved is not None
        assert retrieved["headline"] == "Test headline"
        assert retrieved["line_mover_score"] == 10

    async def test_save_full_item(self, persistence, sample_news_item):
        """Test saving a news item with all fields populated."""
        await persistence.save_news_item(sample_news_item)

        retrieved = await persistence.db.get_sports_news_by_id("test_nfl_injury_001")
        assert retrieved is not None
        assert retrieved["headline"] == "Patrick Mahomes ruled out for Week 10"
        assert retrieved["line_mover_score"] == 92
        assert retrieved["sport"] == "NFL"
        assert retrieved["category"] == "injury"
        assert retrieved["urgency"] == "high"

        # Check JSON fields were serialized
        teams = json.loads(retrieved["teams_json"])
        assert teams == ["KC Chiefs"]

        betting_impact = json.loads(retrieved["betting_impact_json"])
        assert betting_impact["confidence"] == 0.95
        assert betting_impact["line_direction"] == "up"

    async def test_save_duplicate_item(self, persistence, sample_news_item):
        """Test that saving the same item twice uses INSERT OR REPLACE."""
        await persistence.save_news_item(sample_news_item)
        await persistence.save_news_item(sample_news_item)

        # Should only have one item, not two
        items = await persistence.get_news_items(days=1)
        matching = [i for i in items if i.item_id == "test_nfl_injury_001"]
        assert len(matching) == 1

    async def test_save_without_betting_impact(self, persistence):
        """Test saving an item without betting impact."""
        item = SportsNewsItem(
            item_id="no_impact",
            headline="General news",
            source="ESPN",
            published_at=time.time(),
            teams=[],
            sport="Multi",
            category="news",
            urgency="low",
            line_mover_score=5,
            url="https://example.com",
            betting_impact=None,
        )

        await persistence.save_news_item(item)

        retrieved = await persistence.db.get_sports_news_by_id("no_impact")
        assert retrieved is not None
        assert retrieved["betting_impact_json"] == "{}"


class TestGetNewsItems:
    """Tests for get_news_items()."""

    async def test_get_all_items(self, persistence):
        """Test retrieving all news items."""
        # Save multiple items
        for i in range(5):
            item = SportsNewsItem(
                item_id=f"test_{i}",
                headline=f"Headline {i}",
                source="ESPN",
                published_at=time.time() - (i * 3600),  # 1 hour apart
                teams=[],
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=10 + i,
                url=f"https://example.com/{i}",
            )
            await persistence.save_news_item(item)

        items = await persistence.get_news_items(days=1)
        assert len(items) == 5

    async def test_filter_by_sport(self, persistence):
        """Test filtering by sport."""
        # Save NFL item
        nfl_item = SportsNewsItem(
            item_id="nfl_1",
            headline="NFL news",
            source="ESPN",
            published_at=time.time(),
            teams=[],
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            url="https://example.com/nfl",
        )
        await persistence.save_news_item(nfl_item)

        # Save NBA item
        nba_item = SportsNewsItem(
            item_id="nba_1",
            headline="NBA news",
            source="ESPN",
            published_at=time.time(),
            teams=[],
            sport="NBA",
            category="news",
            urgency="low",
            line_mover_score=25,
            url="https://example.com/nba",
        )
        await persistence.save_news_item(nba_item)

        # Filter for NFL only
        nfl_items = await persistence.get_news_items(sport="NFL", days=1)
        assert len(nfl_items) == 1
        assert nfl_items[0].sport == "NFL"

    async def test_filter_by_category(self, persistence):
        """Test filtering by category."""
        # Save injury item
        injury_item = SportsNewsItem(
            item_id="injury_1",
            headline="Player injured",
            source="ESPN",
            published_at=time.time(),
            teams=[],
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=75,
            url="https://example.com/injury",
        )
        await persistence.save_news_item(injury_item)

        # Save trade item
        trade_item = SportsNewsItem(
            item_id="trade_1",
            headline="Player traded",
            source="ESPN",
            published_at=time.time(),
            teams=[],
            sport="NFL",
            category="trade",
            urgency="medium",
            line_mover_score=50,
            url="https://example.com/trade",
        )
        await persistence.save_news_item(trade_item)

        # Filter for injuries only
        injury_items = await persistence.get_news_items(category="injury", days=1)
        assert len(injury_items) == 1
        assert injury_items[0].category == "injury"

    async def test_filter_by_min_score(self, persistence):
        """Test filtering by minimum line mover score."""
        # Save items with different scores
        for i, score in enumerate([20, 50, 75, 90]):
            item = SportsNewsItem(
                item_id=f"score_{i}",
                headline=f"News {score}",
                source="ESPN",
                published_at=time.time(),
                teams=[],
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=score,
                url=f"https://example.com/{i}",
            )
            await persistence.save_news_item(item)

        # Get items with score >= 60
        high_score_items = await persistence.get_news_items(min_score=60, days=1)
        assert len(high_score_items) == 2
        assert all(i.line_mover_score >= 60 for i in high_score_items)

    async def test_filter_by_days(self, persistence):
        """Test filtering by time window."""
        now = time.time()

        # Recent item (within 1 day)
        recent_item = SportsNewsItem(
            item_id="recent",
            headline="Recent news",
            source="ESPN",
            published_at=now - 3600,  # 1 hour ago
            teams=[],
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            url="https://example.com/recent",
        )
        await persistence.save_news_item(recent_item)

        # Old item (beyond 1 day)
        old_item = SportsNewsItem(
            item_id="old",
            headline="Old news",
            source="ESPN",
            published_at=now - (2 * 86400),  # 2 days ago
            teams=[],
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            url="https://example.com/old",
        )
        await persistence.save_news_item(old_item)

        # Get only recent items (last 1 day)
        items = await persistence.get_news_items(days=1)
        assert len(items) == 1
        assert items[0].item_id == "recent"

    async def test_limit(self, persistence):
        """Test limiting number of results."""
        # Save 10 items
        for i in range(10):
            item = SportsNewsItem(
                item_id=f"limit_test_{i}",
                headline=f"News {i}",
                source="ESPN",
                published_at=time.time(),
                teams=[],
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=i,
                url=f"https://example.com/{i}",
            )
            await persistence.save_news_item(item)

        # Get only 5 items
        items = await persistence.get_news_items(days=1, limit=5)
        assert len(items) == 5


class TestGetTrendingNews:
    """Tests for get_trending_news()."""

    async def test_trending_returns_high_scores(self, persistence):
        """Test that trending returns highest-scored items."""
        # Save items with varying scores
        for i, score in enumerate([30, 55, 75, 85, 95]):
            item = SportsNewsItem(
                item_id=f"trending_{i}",
                headline=f"News {score}",
                source="ESPN",
                published_at=time.time(),
                teams=[],
                sport="NFL",
                category="injury" if score >= 70 else "news",
                urgency="high" if score >= 70 else "low",
                line_mover_score=score,
                url=f"https://example.com/{i}",
            )
            await persistence.save_news_item(item)

        trending = await persistence.get_trending_news(limit=3)

        # Should get top 3 scores: 95, 85, 75
        assert len(trending) == 3
        assert trending[0].line_mover_score >= trending[1].line_mover_score
        assert trending[1].line_mover_score >= trending[2].line_mover_score

    async def test_trending_respects_time_window(self, persistence):
        """Test that trending only considers recent news."""
        now = time.time()

        # Recent high-score item
        recent = SportsNewsItem(
            item_id="recent_high",
            headline="Recent high score",
            source="ESPN",
            published_at=now - 3600,  # 1 hour ago
            teams=[],
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=90,
            url="https://example.com/recent",
        )
        await persistence.save_news_item(recent)

        # Old high-score item (beyond window)
        old = SportsNewsItem(
            item_id="old_high",
            headline="Old high score",
            source="ESPN",
            published_at=now - (48 * 3600),  # 48 hours ago
            teams=[],
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=95,
            url="https://example.com/old",
        )
        await persistence.save_news_item(old)

        # Get trending (default 24 hours)
        trending = await persistence.get_trending_news(min_hours=24)

        # Should only get recent item, not old one
        assert len(trending) == 1
        assert trending[0].item_id == "recent_high"


class TestGetNewsByTeam:
    """Tests for get_news_by_team()."""

    async def test_get_team_news(self, persistence):
        """Test retrieving news for a specific team."""
        # Save Chiefs news
        chiefs_item = SportsNewsItem(
            item_id="chiefs_1",
            headline="Mahomes update",
            source="ESPN",
            published_at=time.time(),
            teams=["KC Chiefs"],
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=85,
            url="https://example.com/chiefs",
        )
        await persistence.save_news_item(chiefs_item)

        # Save Lakers news
        lakers_item = SportsNewsItem(
            item_id="lakers_1",
            headline="LeBron update",
            source="ESPN",
            published_at=time.time(),
            teams=["LA Lakers"],
            sport="NBA",
            category="injury",
            urgency="high",
            line_mover_score=90,
            url="https://example.com/lakers",
        )
        await persistence.save_news_item(lakers_item)

        # Get Chiefs news
        chiefs_news = await persistence.get_news_by_team("KC Chiefs", days=7)
        assert len(chiefs_news) == 1
        assert "KC Chiefs" in chiefs_news[0].teams

    async def test_get_team_news_multiple_items(self, persistence):
        """Test retrieving multiple news items for the same team."""
        # Save multiple Chiefs items
        for i in range(3):
            item = SportsNewsItem(
                item_id=f"chiefs_{i}",
                headline=f"Chiefs news {i}",
                source="ESPN",
                published_at=time.time() - (i * 3600),
                teams=["KC Chiefs"],
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=50 + i,
                url=f"https://example.com/chiefs/{i}",
            )
            await persistence.save_news_item(item)

        chiefs_news = await persistence.get_news_by_team("KC Chiefs", days=1)
        assert len(chiefs_news) == 3


class TestComputeHistoricalImpact:
    """Tests for compute_historical_impact()."""

    async def test_compute_for_team(self, persistence):
        """Test computing historical impact for a specific team."""
        # Save multiple Chiefs items with varying scores
        for i, score in enumerate([60, 75, 85]):
            item = SportsNewsItem(
                item_id=f"chiefs_hist_{i}",
                headline=f"Chiefs news {i}",
                source="ESPN",
                published_at=time.time() - (i * 86400),  # Days apart
                teams=["KC Chiefs"],
                sport="NFL",
                category="injury" if score >= 70 else "news",
                urgency="high" if score >= 70 else "medium",
                line_mover_score=score,
                url=f"https://example.com/{i}",
            )
            await persistence.save_news_item(item)

        stats = await persistence.compute_historical_impact(team="KC Chiefs", days=30)

        assert stats["total_items"] == 3
        assert stats["avg_line_mover_score"] > 0
        assert stats["max_line_mover_score"] == 85
        assert stats["high_impact_count"] >= 1  # 75 and 85 are both >= 70
        assert "injury" in stats["category_distribution"]

    async def test_compute_for_category(self, persistence):
        """Test computing historical impact for a category."""
        # Save injury items across different teams
        for i, score in enumerate([70, 80, 90]):
            item = SportsNewsItem(
                item_id=f"injury_hist_{i}",
                headline=f"Injury {i}",
                source="ESPN",
                published_at=time.time(),
                teams=[f"Team {i}"],
                sport="NFL",
                category="injury",
                urgency="high",
                line_mover_score=score,
                url=f"https://example.com/{i}",
            )
            await persistence.save_news_item(item)

        stats = await persistence.compute_historical_impact(category="injury", days=7)

        assert stats["total_items"] == 3
        assert stats["avg_line_mover_score"] == 80.0
        assert stats["category_distribution"]["injury"] == 3

    async def test_compute_empty_dataset(self, persistence):
        """Test computing stats when no data exists."""
        stats = await persistence.compute_historical_impact(team="Nonexistent Team", days=7)

        assert stats["total_items"] == 0
        assert stats["avg_line_mover_score"] == 0.0
        assert stats["max_line_mover_score"] == 0
        assert stats["category_distribution"] == {}


class TestGetBettingOpportunities:
    """Tests for get_betting_opportunities()."""

    async def test_identify_opportunities(self, persistence):
        """Test identifying betting opportunities from high-impact news."""
        # Save multiple high-impact items for Chiefs
        for i in range(3):
            item = SportsNewsItem(
                item_id=f"opp_chiefs_{i}",
                headline=f"Chiefs news {i}",
                source="ESPN",
                published_at=time.time(),
                teams=["KC Chiefs"],
                sport="NFL",
                category="injury",
                urgency="high",
                line_mover_score=75 + i,
                url=f"https://example.com/{i}",
                betting_impact=BettingImpact(
                    affected_markets=["spread", "total"],
                    confidence=0.8,
                    line_direction="up",
                    magnitude="medium",
                    affected_teams=["KC Chiefs"],
                    recommended_action="monitor",
                ),
            )
            await persistence.save_news_item(item)

        opps = await persistence.get_betting_opportunities(min_score=70)

        assert len(opps) > 0
        chiefs_opp = opps[0]
        assert chiefs_opp["team"] == "KC Chiefs"
        assert chiefs_opp["sport"] == "NFL"
        assert len(chiefs_opp["news_items"]) == 3
        assert "spread" in chiefs_opp["recommended_markets"]

    async def test_no_opportunities_below_threshold(self, persistence):
        """Test that low-score items don't create opportunities."""
        # Save low-score items
        for i in range(3):
            item = SportsNewsItem(
                item_id=f"low_score_{i}",
                headline=f"Low impact {i}",
                source="ESPN",
                published_at=time.time(),
                teams=["Team A"],
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=30,
                url=f"https://example.com/{i}",
            )
            await persistence.save_news_item(item)

        opps = await persistence.get_betting_opportunities(min_score=70)
        assert len(opps) == 0


class TestPurgeOldNews:
    """Tests for purge_old_news()."""

    async def test_purge_old_items(self, persistence):
        """Test purging news older than threshold."""
        now = time.time()

        # Save old item (100 days ago)
        old_item = SportsNewsItem(
            item_id="very_old",
            headline="Old news",
            source="ESPN",
            published_at=now - (100 * 86400),
            teams=[],
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            url="https://example.com/old",
        )
        await persistence.save_news_item(old_item)

        # Save recent item (1 day ago)
        recent_item = SportsNewsItem(
            item_id="recent",
            headline="Recent news",
            source="ESPN",
            published_at=now - 86400,
            teams=[],
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            url="https://example.com/recent",
        )
        await persistence.save_news_item(recent_item)

        # Purge items older than 90 days
        deleted = await persistence.purge_old_news(days=90)

        assert deleted == 1

        # Verify old item is gone, recent remains
        items = await persistence.get_news_items(days=365)
        assert len(items) == 1
        assert items[0].item_id == "recent"

    async def test_purge_no_items(self, persistence):
        """Test purging when no items meet criteria."""
        # Save only recent items
        now = time.time()
        item = SportsNewsItem(
            item_id="recent",
            headline="Recent",
            source="ESPN",
            published_at=now - 86400,
            teams=[],
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            url="https://example.com",
        )
        await persistence.save_news_item(item)

        # Try to purge items older than 90 days (should delete nothing)
        deleted = await persistence.purge_old_news(days=90)
        assert deleted == 0
