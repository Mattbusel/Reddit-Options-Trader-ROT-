"""
Tests for sports database mixin (rot.storage.sports_db.SportsMixin).

Tests cover:
- Table creation and schema
- insert_sports_news()
- get_sports_news() with filters
- get_sports_news_by_team()
- get_sports_news_by_id()
- update_sports_news_ai_summary()
- get_sports_news_count()
- get_top_scored_news()
- purge_old_sports_news()
- Indexes and performance
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from rot.storage.database import Database


@pytest.fixture
async def db():
    """Create a temporary test database."""
    db_path = Path("test_sports_db.db")
    database = Database(str(db_path))
    await database.connect()
    yield database
    await database.close()
    if db_path.exists():
        db_path.unlink()


class TestTableCreation:
    """Tests for sports_news table creation and schema."""

    async def test_table_exists(self, db):
        """Test that sports_news table is created."""
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sports_news'"
        )
        result = await cursor.fetchone()
        assert result is not None
        assert result[0] == "sports_news"

    async def test_table_columns(self, db):
        """Test that all required columns exist."""
        cursor = await db.db.execute("PRAGMA table_info(sports_news)")
        columns = await cursor.fetchall()
        column_names = {col[1] for col in columns}

        required_columns = {
            "id", "item_id", "headline", "source", "published_at",
            "teams_json", "sport", "category", "urgency", "line_mover_score",
            "betting_impact_json", "url", "summary", "all_categories_json",
            "betting_categories_json", "ai_summary", "created_at",
        }

        assert required_columns.issubset(column_names)

    async def test_indexes_created(self, db):
        """Test that performance indexes are created."""
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='sports_news'"
        )
        indexes = await cursor.fetchall()
        index_names = {idx[0] for idx in indexes}

        expected_indexes = {
            "idx_sports_news_published",
            "idx_sports_news_score",
            "idx_sports_news_sport",
            "idx_sports_news_category",
        }

        assert expected_indexes.issubset(index_names)


class TestInsertSportsNews:
    """Tests for insert_sports_news()."""

    async def test_insert_minimal(self, db):
        """Test inserting a news item with minimal fields."""
        await db.insert_sports_news(
            item_id="test_001",
            headline="Test headline",
            source="ESPN",
            published_at=1234567890.0,
            teams_json="[]",
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=10,
            betting_impact_json="{}",
            url="https://example.com",
        )

        # Verify insertion
        cursor = await db.db.execute("SELECT * FROM sports_news WHERE item_id = ?", ("test_001",))
        row = await cursor.fetchone()
        assert row is not None
        assert row["headline"] == "Test headline"
        assert row["line_mover_score"] == 10

    async def test_insert_full(self, db):
        """Test inserting a news item with all fields."""
        betting_impact = json.dumps({
            "affected_markets": ["spread", "total"],
            "confidence": 0.85,
            "line_direction": "up",
            "magnitude": "large",
            "affected_teams": ["KC Chiefs"],
            "recommended_action": "bet_now",
            "notes": "Star player injury",
        })

        await db.insert_sports_news(
            item_id="test_full",
            headline="Mahomes injured",
            source="ESPN NFL",
            published_at=1234567890.0,
            teams_json='["KC Chiefs"]',
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=92,
            betting_impact_json=betting_impact,
            url="https://example.com/mahomes",
            summary="Patrick Mahomes ruled out",
            all_categories_json='["injury", "lineup"]',
            betting_categories_json='["spread_impact", "total_impact"]',
            ai_summary="Major betting impact expected",
        )

        cursor = await db.db.execute("SELECT * FROM sports_news WHERE item_id = ?", ("test_full",))
        row = await cursor.fetchone()
        assert row is not None
        assert row["sport"] == "NFL"
        assert row["category"] == "injury"
        assert row["urgency"] == "high"
        assert row["line_mover_score"] == 92
        assert row["ai_summary"] == "Major betting impact expected"

    async def test_insert_or_replace(self, db):
        """Test that INSERT OR REPLACE works for duplicate item_id."""
        # Insert first time
        await db.insert_sports_news(
            item_id="duplicate",
            headline="First headline",
            source="ESPN",
            published_at=1234567890.0,
            teams_json="[]",
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            betting_impact_json="{}",
            url="https://example.com",
        )

        # Insert again with different data
        await db.insert_sports_news(
            item_id="duplicate",
            headline="Updated headline",
            source="ESPN",
            published_at=1234567891.0,
            teams_json="[]",
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=80,
            betting_impact_json="{}",
            url="https://example.com/updated",
        )

        # Should only have one row with updated data
        cursor = await db.db.execute("SELECT COUNT(*) FROM sports_news WHERE item_id = ?", ("duplicate",))
        count = (await cursor.fetchone())[0]
        assert count == 1

        cursor = await db.db.execute("SELECT * FROM sports_news WHERE item_id = ?", ("duplicate",))
        row = await cursor.fetchone()
        assert row["headline"] == "Updated headline"
        assert row["line_mover_score"] == 80


class TestGetSportsNews:
    """Tests for get_sports_news()."""

    async def test_get_all(self, db):
        """Test retrieving all news items."""
        # Insert multiple items
        for i in range(5):
            await db.insert_sports_news(
                item_id=f"item_{i}",
                headline=f"Headline {i}",
                source="ESPN",
                published_at=time.time(),
                teams_json="[]",
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=10 + i,
                betting_impact_json="{}",
                url=f"https://example.com/{i}",
            )

        items = await db.get_sports_news(since_ts=0.0, limit=100)
        assert len(items) == 5

    async def test_filter_by_sport(self, db):
        """Test filtering by sport."""
        await db.insert_sports_news(
            item_id="nfl_1",
            headline="NFL news",
            source="ESPN",
            published_at=time.time(),
            teams_json="[]",
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            betting_impact_json="{}",
            url="https://example.com/nfl",
        )

        await db.insert_sports_news(
            item_id="nba_1",
            headline="NBA news",
            source="ESPN",
            published_at=time.time(),
            teams_json="[]",
            sport="NBA",
            category="news",
            urgency="low",
            line_mover_score=25,
            betting_impact_json="{}",
            url="https://example.com/nba",
        )

        nfl_items = await db.get_sports_news(sport="NFL", since_ts=0.0)
        assert len(nfl_items) == 1
        assert nfl_items[0]["sport"] == "NFL"

    async def test_filter_by_category(self, db):
        """Test filtering by category."""
        await db.insert_sports_news(
            item_id="injury_1",
            headline="Injury",
            source="ESPN",
            published_at=time.time(),
            teams_json="[]",
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=75,
            betting_impact_json="{}",
            url="https://example.com",
        )

        await db.insert_sports_news(
            item_id="trade_1",
            headline="Trade",
            source="ESPN",
            published_at=time.time(),
            teams_json="[]",
            sport="NFL",
            category="trade",
            urgency="medium",
            line_mover_score=50,
            betting_impact_json="{}",
            url="https://example.com",
        )

        injury_items = await db.get_sports_news(category="injury", since_ts=0.0)
        assert len(injury_items) == 1
        assert injury_items[0]["category"] == "injury"

    async def test_filter_by_urgency(self, db):
        """Test filtering by urgency."""
        await db.insert_sports_news(
            item_id="high_urgency",
            headline="High",
            source="ESPN",
            published_at=time.time(),
            teams_json="[]",
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=80,
            betting_impact_json="{}",
            url="https://example.com",
        )

        await db.insert_sports_news(
            item_id="low_urgency",
            headline="Low",
            source="ESPN",
            published_at=time.time(),
            teams_json="[]",
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            betting_impact_json="{}",
            url="https://example.com",
        )

        high_items = await db.get_sports_news(urgency="high", since_ts=0.0)
        assert len(high_items) == 1
        assert high_items[0]["urgency"] == "high"

    async def test_filter_by_min_score(self, db):
        """Test filtering by minimum line mover score."""
        for i, score in enumerate([20, 50, 75, 90]):
            await db.insert_sports_news(
                item_id=f"score_{i}",
                headline=f"Score {score}",
                source="ESPN",
                published_at=time.time(),
                teams_json="[]",
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=score,
                betting_impact_json="{}",
                url=f"https://example.com/{i}",
            )

        high_score_items = await db.get_sports_news(min_score=60, since_ts=0.0)
        assert len(high_score_items) == 2
        assert all(item["line_mover_score"] >= 60 for item in high_score_items)

    async def test_filter_by_time(self, db):
        """Test filtering by time window."""
        now = time.time()

        # Recent item
        await db.insert_sports_news(
            item_id="recent",
            headline="Recent",
            source="ESPN",
            published_at=now - 3600,  # 1 hour ago
            teams_json="[]",
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            betting_impact_json="{}",
            url="https://example.com",
        )

        # Old item
        await db.insert_sports_news(
            item_id="old",
            headline="Old",
            source="ESPN",
            published_at=now - (2 * 86400),  # 2 days ago
            teams_json="[]",
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            betting_impact_json="{}",
            url="https://example.com",
        )

        cutoff = now - 86400  # 1 day ago
        items = await db.get_sports_news(since_ts=cutoff)
        assert len(items) == 1
        assert items[0]["item_id"] == "recent"

    async def test_limit(self, db):
        """Test limiting results."""
        for i in range(10):
            await db.insert_sports_news(
                item_id=f"limit_{i}",
                headline=f"Item {i}",
                source="ESPN",
                published_at=time.time(),
                teams_json="[]",
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=i,
                betting_impact_json="{}",
                url=f"https://example.com/{i}",
            )

        items = await db.get_sports_news(since_ts=0.0, limit=5)
        assert len(items) == 5

    async def test_sort_by_published_desc(self, db):
        """Test that results are sorted by published_at descending."""
        now = time.time()
        timestamps = [now - 3600, now - 7200, now - 1800]  # 1h, 2h, 30m ago

        for i, ts in enumerate(timestamps):
            await db.insert_sports_news(
                item_id=f"ts_{i}",
                headline=f"Item {i}",
                source="ESPN",
                published_at=ts,
                teams_json="[]",
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=10,
                betting_impact_json="{}",
                url=f"https://example.com/{i}",
            )

        items = await db.get_sports_news(since_ts=0.0)

        # Should be in descending order (most recent first)
        assert items[0]["published_at"] > items[1]["published_at"]
        assert items[1]["published_at"] > items[2]["published_at"]


class TestGetSportsNewsByTeam:
    """Tests for get_sports_news_by_team()."""

    async def test_get_by_team(self, db):
        """Test retrieving news for a specific team."""
        await db.insert_sports_news(
            item_id="chiefs_1",
            headline="Chiefs news",
            source="ESPN",
            published_at=time.time(),
            teams_json='["KC Chiefs"]',
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=50,
            betting_impact_json="{}",
            url="https://example.com",
        )

        await db.insert_sports_news(
            item_id="lakers_1",
            headline="Lakers news",
            source="ESPN",
            published_at=time.time(),
            teams_json='["LA Lakers"]',
            sport="NBA",
            category="news",
            urgency="low",
            line_mover_score=50,
            betting_impact_json="{}",
            url="https://example.com",
        )

        chiefs_items = await db.get_sports_news_by_team("KC Chiefs", since_ts=0.0)
        assert len(chiefs_items) == 1
        teams = json.loads(chiefs_items[0]["teams_json"])
        assert "KC Chiefs" in teams

    async def test_get_by_team_multiple(self, db):
        """Test retrieving multiple items for same team."""
        for i in range(3):
            await db.insert_sports_news(
                item_id=f"chiefs_{i}",
                headline=f"Chiefs news {i}",
                source="ESPN",
                published_at=time.time() - (i * 3600),
                teams_json='["KC Chiefs"]',
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=50 + i,
                betting_impact_json="{}",
                url=f"https://example.com/{i}",
            )

        chiefs_items = await db.get_sports_news_by_team("KC Chiefs", since_ts=0.0)
        assert len(chiefs_items) == 3

    async def test_get_by_team_respects_time(self, db):
        """Test that get_by_team respects time cutoff."""
        now = time.time()

        await db.insert_sports_news(
            item_id="recent",
            headline="Recent",
            source="ESPN",
            published_at=now - 3600,
            teams_json='["KC Chiefs"]',
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=50,
            betting_impact_json="{}",
            url="https://example.com",
        )

        await db.insert_sports_news(
            item_id="old",
            headline="Old",
            source="ESPN",
            published_at=now - (10 * 86400),
            teams_json='["KC Chiefs"]',
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=50,
            betting_impact_json="{}",
            url="https://example.com",
        )

        cutoff = now - (7 * 86400)
        items = await db.get_sports_news_by_team("KC Chiefs", since_ts=cutoff)
        assert len(items) == 1
        assert items[0]["item_id"] == "recent"


class TestGetSportsNewsById:
    """Tests for get_sports_news_by_id()."""

    async def test_get_existing_item(self, db):
        """Test retrieving an existing item by ID."""
        await db.insert_sports_news(
            item_id="test_id",
            headline="Test",
            source="ESPN",
            published_at=time.time(),
            teams_json="[]",
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=30,
            betting_impact_json="{}",
            url="https://example.com",
        )

        item = await db.get_sports_news_by_id("test_id")
        assert item is not None
        assert item["item_id"] == "test_id"
        assert item["headline"] == "Test"

    async def test_get_nonexistent_item(self, db):
        """Test retrieving a nonexistent item returns None."""
        item = await db.get_sports_news_by_id("does_not_exist")
        assert item is None


class TestUpdateSportsNewsAiSummary:
    """Tests for update_sports_news_ai_summary()."""

    async def test_update_ai_summary(self, db):
        """Test updating AI summary for an item."""
        await db.insert_sports_news(
            item_id="update_test",
            headline="Test",
            source="ESPN",
            published_at=time.time(),
            teams_json="[]",
            sport="NFL",
            category="injury",
            urgency="high",
            line_mover_score=75,
            betting_impact_json="{}",
            url="https://example.com",
            ai_summary="",
        )

        # Update AI summary
        updated = await db.update_sports_news_ai_summary(
            "update_test",
            "This is a major injury with significant betting impact.",
        )
        assert updated is True

        # Verify update
        item = await db.get_sports_news_by_id("update_test")
        assert item["ai_summary"] == "This is a major injury with significant betting impact."

    async def test_update_nonexistent_item(self, db):
        """Test updating AI summary for nonexistent item returns False."""
        updated = await db.update_sports_news_ai_summary("does_not_exist", "Summary")
        assert updated is False


class TestGetSportsNewsCount:
    """Tests for get_sports_news_count()."""

    async def test_count_all(self, db):
        """Test counting all news items."""
        for i in range(5):
            await db.insert_sports_news(
                item_id=f"count_{i}",
                headline=f"Item {i}",
                source="ESPN",
                published_at=time.time(),
                teams_json="[]",
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=20,
                betting_impact_json="{}",
                url=f"https://example.com/{i}",
            )

        count = await db.get_sports_news_count(since_ts=0.0)
        assert count == 5

    async def test_count_by_sport(self, db):
        """Test counting items for specific sport."""
        await db.insert_sports_news(
            item_id="nfl_count",
            headline="NFL",
            source="ESPN",
            published_at=time.time(),
            teams_json="[]",
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            betting_impact_json="{}",
            url="https://example.com",
        )

        await db.insert_sports_news(
            item_id="nba_count",
            headline="NBA",
            source="ESPN",
            published_at=time.time(),
            teams_json="[]",
            sport="NBA",
            category="news",
            urgency="low",
            line_mover_score=20,
            betting_impact_json="{}",
            url="https://example.com",
        )

        nfl_count = await db.get_sports_news_count(sport="NFL", since_ts=0.0)
        assert nfl_count == 1


class TestGetTopScoredNews:
    """Tests for get_top_scored_news()."""

    async def test_top_scored(self, db):
        """Test retrieving top-scored news items."""
        for i, score in enumerate([30, 55, 75, 85, 95]):
            await db.insert_sports_news(
                item_id=f"top_{i}",
                headline=f"Score {score}",
                source="ESPN",
                published_at=time.time(),
                teams_json="[]",
                sport="NFL",
                category="news",
                urgency="low",
                line_mover_score=score,
                betting_impact_json="{}",
                url=f"https://example.com/{i}",
            )

        top_items = await db.get_top_scored_news(limit=3, since_ts=0.0)

        assert len(top_items) == 3
        assert top_items[0]["line_mover_score"] == 95
        assert top_items[1]["line_mover_score"] == 85
        assert top_items[2]["line_mover_score"] == 75


class TestPurgeOldSportsNews:
    """Tests for purge_old_sports_news()."""

    async def test_purge(self, db):
        """Test purging old news items."""
        now = time.time()

        # Old item
        await db.insert_sports_news(
            item_id="very_old",
            headline="Old",
            source="ESPN",
            published_at=now - (100 * 86400),
            teams_json="[]",
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            betting_impact_json="{}",
            url="https://example.com",
        )

        # Recent item
        await db.insert_sports_news(
            item_id="recent",
            headline="Recent",
            source="ESPN",
            published_at=now - 86400,
            teams_json="[]",
            sport="NFL",
            category="news",
            urgency="low",
            line_mover_score=20,
            betting_impact_json="{}",
            url="https://example.com",
        )

        # Purge items older than 90 days
        cutoff = now - (90 * 86400)
        deleted = await db.purge_old_sports_news(before_ts=cutoff)

        assert deleted == 1

        # Verify only recent item remains
        remaining = await db.get_sports_news(since_ts=0.0)
        assert len(remaining) == 1
        assert remaining[0]["item_id"] == "recent"
