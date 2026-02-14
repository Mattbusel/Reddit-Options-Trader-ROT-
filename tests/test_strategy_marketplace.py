"""Tests for the Strategy Marketplace."""

import time
from uuid import uuid4

import pytest

from rot.strategy.marketplace import Marketplace
from rot.strategy.types import MarketplaceEntry, Strategy, StrategyRule


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def marketplace():
    """Return a fresh Marketplace instance."""
    return Marketplace()


@pytest.fixture
def sample_strategy():
    """Return a basic Strategy for testing."""
    return Strategy(
        id=str(uuid4()),
        user_id="user-1",
        name="My Strategy",
        description="A test strategy",
        rules=[
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ],
        performance={
            "win_rate": 0.65,
            "sharpe": 1.5,
            "total_trades": 100,
        },
    )


@pytest.fixture
def sample_strategy_2():
    """Return a second Strategy with different performance."""
    return Strategy(
        id=str(uuid4()),
        user_id="user-2",
        name="High Sharpe Strategy",
        description="A high performance strategy",
        rules=[
            StrategyRule(field="confidence", operator="gte", value=0.7),
        ],
        performance={
            "win_rate": 0.70,
            "sharpe": 2.5,
            "total_trades": 50,
        },
    )


@pytest.fixture
def sample_strategy_3():
    """Return a third Strategy with lower performance."""
    return Strategy(
        id=str(uuid4()),
        user_id="user-1",
        name="Conservative Strategy",
        description="A conservative approach",
        rules=[
            StrategyRule(field="confidence", operator="gte", value=0.8),
        ],
        performance={
            "win_rate": 0.55,
            "sharpe": 0.8,
            "total_trades": 80,
        },
    )


# ---------------------------------------------------------------------------
# Initialization Tests
# ---------------------------------------------------------------------------


def test_marketplace_init(marketplace):
    """Marketplace initializes with empty state."""
    assert len(marketplace) == 0
    assert marketplace._entries == {}
    assert marketplace._subscriptions == {}
    assert marketplace._ratings == {}


# ---------------------------------------------------------------------------
# Publish Tests
# ---------------------------------------------------------------------------


def test_publish_creates_entry(marketplace, sample_strategy):
    """publish creates a MarketplaceEntry from a Strategy."""
    entry = marketplace.publish(
        strategy=sample_strategy,
        author_id="author-1",
    )

    assert isinstance(entry, MarketplaceEntry)
    assert entry.id != ""
    assert entry.strategy_id == sample_strategy.id
    assert entry.author_id == "author-1"
    assert entry.name == sample_strategy.name
    assert entry.description == sample_strategy.description
    assert entry.performance == sample_strategy.performance
    assert entry.subscriber_count == 0
    assert entry.rating == 0.0
    assert entry.created_at > 0
    assert len(marketplace) == 1
    assert entry.id in marketplace


def test_publish_custom_name_description(marketplace, sample_strategy):
    """publish can override name and description."""
    entry = marketplace.publish(
        strategy=sample_strategy,
        author_id="author-1",
        name="Custom Name",
        description="Custom Description",
    )

    assert entry.name == "Custom Name"
    assert entry.description == "Custom Description"


def test_publish_none_description_uses_strategy_description(marketplace, sample_strategy):
    """publish with description=None uses the strategy's description."""
    entry = marketplace.publish(
        strategy=sample_strategy,
        author_id="author-1",
        description=None,
    )

    assert entry.description == sample_strategy.description


def test_publish_multiple_entries(marketplace, sample_strategy, sample_strategy_2):
    """publish can add multiple entries."""
    entry1 = marketplace.publish(sample_strategy, "author-1")
    entry2 = marketplace.publish(sample_strategy_2, "author-2")

    assert len(marketplace) == 2
    assert entry1.id in marketplace
    assert entry2.id in marketplace
    assert entry1.id != entry2.id


# ---------------------------------------------------------------------------
# Unpublish Tests
# ---------------------------------------------------------------------------


def test_unpublish_removes_entry(marketplace, sample_strategy):
    """unpublish removes the entry if author matches."""
    entry = marketplace.publish(sample_strategy, "author-1")

    result = marketplace.unpublish(entry.id, "author-1")

    assert result is True
    assert len(marketplace) == 0
    assert entry.id not in marketplace


def test_unpublish_non_existent_returns_false(marketplace):
    """unpublish returns False if entry does not exist."""
    result = marketplace.unpublish("non-existent-id", "author-1")
    assert result is False


def test_unpublish_wrong_author_returns_false(marketplace, sample_strategy):
    """unpublish returns False if author does not match."""
    entry = marketplace.publish(sample_strategy, "author-1")

    result = marketplace.unpublish(entry.id, "wrong-author")

    assert result is False
    assert len(marketplace) == 1
    assert entry.id in marketplace


def test_unpublish_cleans_up_subscriptions(marketplace, sample_strategy):
    """unpublish removes all subscriptions to the entry."""
    entry = marketplace.publish(sample_strategy, "author-1")
    marketplace.subscribe("user-1", entry.id)
    marketplace.subscribe("user-2", entry.id)

    assert len(marketplace._subscriptions["user-1"]) == 1
    assert len(marketplace._subscriptions["user-2"]) == 1

    marketplace.unpublish(entry.id, "author-1")

    # Subscriptions cleaned up
    assert entry.id not in marketplace._subscriptions.get("user-1", set())
    assert entry.id not in marketplace._subscriptions.get("user-2", set())


def test_unpublish_cleans_up_ratings(marketplace, sample_strategy):
    """unpublish removes ratings for the entry."""
    entry = marketplace.publish(sample_strategy, "author-1")
    marketplace.rate("user-1", entry.id, 5.0)
    marketplace.rate("user-2", entry.id, 4.0)

    assert entry.id in marketplace._ratings

    marketplace.unpublish(entry.id, "author-1")

    assert entry.id not in marketplace._ratings


# ---------------------------------------------------------------------------
# Subscribe Tests
# ---------------------------------------------------------------------------


def test_subscribe_adds_subscription(marketplace, sample_strategy):
    """subscribe adds a user subscription and increments count."""
    entry = marketplace.publish(sample_strategy, "author-1")

    result = marketplace.subscribe("user-1", entry.id)

    assert result is True
    assert entry.id in marketplace._subscriptions["user-1"]

    # Subscriber count incremented
    updated_entry = marketplace.get_entry(entry.id)
    assert updated_entry.subscriber_count == 1


def test_subscribe_non_existent_returns_false(marketplace):
    """subscribe returns False if entry does not exist."""
    result = marketplace.subscribe("user-1", "non-existent-id")
    assert result is False


def test_subscribe_already_subscribed_returns_false(marketplace, sample_strategy):
    """subscribe returns False if already subscribed."""
    entry = marketplace.publish(sample_strategy, "author-1")

    result1 = marketplace.subscribe("user-1", entry.id)
    result2 = marketplace.subscribe("user-1", entry.id)

    assert result1 is True
    assert result2 is False

    # Count only incremented once
    updated_entry = marketplace.get_entry(entry.id)
    assert updated_entry.subscriber_count == 1


def test_subscribe_multiple_users(marketplace, sample_strategy):
    """subscribe can add multiple users."""
    entry = marketplace.publish(sample_strategy, "author-1")

    marketplace.subscribe("user-1", entry.id)
    marketplace.subscribe("user-2", entry.id)
    marketplace.subscribe("user-3", entry.id)

    updated_entry = marketplace.get_entry(entry.id)
    assert updated_entry.subscriber_count == 3


# ---------------------------------------------------------------------------
# Unsubscribe Tests
# ---------------------------------------------------------------------------


def test_unsubscribe_removes_subscription(marketplace, sample_strategy):
    """unsubscribe removes subscription and decrements count."""
    entry = marketplace.publish(sample_strategy, "author-1")
    marketplace.subscribe("user-1", entry.id)

    result = marketplace.unsubscribe("user-1", entry.id)

    assert result is True
    assert entry.id not in marketplace._subscriptions.get("user-1", set())

    updated_entry = marketplace.get_entry(entry.id)
    assert updated_entry.subscriber_count == 0


def test_unsubscribe_not_subscribed_returns_false(marketplace, sample_strategy):
    """unsubscribe returns False if user is not subscribed."""
    entry = marketplace.publish(sample_strategy, "author-1")

    result = marketplace.unsubscribe("user-1", entry.id)

    assert result is False


def test_unsubscribe_non_existent_entry_returns_false(marketplace):
    """unsubscribe returns False if entry does not exist."""
    result = marketplace.unsubscribe("user-1", "non-existent-id")
    assert result is False


def test_unsubscribe_cleans_up_lingering_subscription(marketplace, sample_strategy):
    """unsubscribe cleans up subscription if entry was deleted."""
    entry = marketplace.publish(sample_strategy, "author-1")
    marketplace.subscribe("user-1", entry.id)

    # Manually delete entry (simulating unpublish)
    del marketplace._entries[entry.id]

    result = marketplace.unsubscribe("user-1", entry.id)

    assert result is False
    assert entry.id not in marketplace._subscriptions.get("user-1", set())


def test_unsubscribe_decrements_count_correctly(marketplace, sample_strategy):
    """unsubscribe decrements subscriber count correctly."""
    entry = marketplace.publish(sample_strategy, "author-1")
    marketplace.subscribe("user-1", entry.id)
    marketplace.subscribe("user-2", entry.id)
    marketplace.subscribe("user-3", entry.id)

    marketplace.unsubscribe("user-2", entry.id)

    updated_entry = marketplace.get_entry(entry.id)
    assert updated_entry.subscriber_count == 2


def test_unsubscribe_never_negative(marketplace, sample_strategy):
    """unsubscribe never makes subscriber count negative."""
    entry = marketplace.publish(sample_strategy, "author-1")

    # Manually set count to 0
    marketplace._entries[entry.id] = MarketplaceEntry(
        id=entry.id,
        strategy_id=entry.strategy_id,
        author_id=entry.author_id,
        name=entry.name,
        description=entry.description,
        performance=entry.performance,
        subscriber_count=0,
        rating=entry.rating,
        created_at=entry.created_at,
    )

    # Add subscription manually
    marketplace._subscriptions["user-1"] = {entry.id}

    marketplace.unsubscribe("user-1", entry.id)

    updated_entry = marketplace.get_entry(entry.id)
    assert updated_entry.subscriber_count == 0


# ---------------------------------------------------------------------------
# Rate Tests
# ---------------------------------------------------------------------------


def test_rate_adds_rating(marketplace, sample_strategy):
    """rate adds a rating and computes average."""
    entry = marketplace.publish(sample_strategy, "author-1")

    avg = marketplace.rate("user-1", entry.id, 5.0)

    assert avg == 5.0
    updated_entry = marketplace.get_entry(entry.id)
    assert updated_entry.rating == 5.0


def test_rate_computes_average(marketplace, sample_strategy):
    """rate computes correct average from multiple ratings."""
    entry = marketplace.publish(sample_strategy, "author-1")

    marketplace.rate("user-1", entry.id, 5.0)
    marketplace.rate("user-2", entry.id, 3.0)
    avg = marketplace.rate("user-3", entry.id, 4.0)

    expected = round((5.0 + 3.0 + 4.0) / 3, 2)
    assert avg == expected
    updated_entry = marketplace.get_entry(entry.id)
    assert updated_entry.rating == expected


def test_rate_updates_existing_rating(marketplace, sample_strategy):
    """rate updates existing rating from the same user."""
    entry = marketplace.publish(sample_strategy, "author-1")

    marketplace.rate("user-1", entry.id, 5.0)
    marketplace.rate("user-1", entry.id, 3.0)

    # Only one rating from user-1
    assert len(marketplace._ratings[entry.id]) == 1
    assert marketplace._ratings[entry.id][0] == ("user-1", 3.0)

    updated_entry = marketplace.get_entry(entry.id)
    assert updated_entry.rating == 3.0


def test_rate_invalid_range_raises_error(marketplace, sample_strategy):
    """rate raises ValueError if rating is outside [1.0, 5.0]."""
    entry = marketplace.publish(sample_strategy, "author-1")

    with pytest.raises(ValueError, match="must be between 1.0 and 5.0"):
        marketplace.rate("user-1", entry.id, 0.5)

    with pytest.raises(ValueError, match="must be between 1.0 and 5.0"):
        marketplace.rate("user-1", entry.id, 5.5)

    with pytest.raises(ValueError, match="must be between 1.0 and 5.0"):
        marketplace.rate("user-1", entry.id, 0.0)

    with pytest.raises(ValueError, match="must be between 1.0 and 5.0"):
        marketplace.rate("user-1", entry.id, 6.0)


def test_rate_non_existent_raises_error(marketplace):
    """rate raises KeyError if entry does not exist."""
    with pytest.raises(KeyError, match="not found"):
        marketplace.rate("user-1", "non-existent-id", 5.0)


def test_rate_boundary_values(marketplace, sample_strategy):
    """rate accepts boundary values 1.0 and 5.0."""
    entry = marketplace.publish(sample_strategy, "author-1")

    marketplace.rate("user-1", entry.id, 1.0)
    marketplace.rate("user-2", entry.id, 5.0)

    avg = round((1.0 + 5.0) / 2, 2)
    updated_entry = marketplace.get_entry(entry.id)
    assert updated_entry.rating == avg


# ---------------------------------------------------------------------------
# Get Entry Tests
# ---------------------------------------------------------------------------


def test_get_entry_returns_entry(marketplace, sample_strategy):
    """get_entry returns the entry if it exists."""
    entry = marketplace.publish(sample_strategy, "author-1")

    retrieved = marketplace.get_entry(entry.id)

    assert retrieved is not None
    assert retrieved.id == entry.id
    assert retrieved.name == entry.name


def test_get_entry_returns_none(marketplace):
    """get_entry returns None if entry does not exist."""
    retrieved = marketplace.get_entry("non-existent-id")
    assert retrieved is None


# ---------------------------------------------------------------------------
# List Entries Tests
# ---------------------------------------------------------------------------


def test_list_entries_empty(marketplace):
    """list_entries returns empty list on empty marketplace."""
    entries = marketplace.list_entries()
    assert entries == []


def test_list_entries_sort_by_rating(marketplace, sample_strategy, sample_strategy_2):
    """list_entries sorts by rating descending."""
    entry1 = marketplace.publish(sample_strategy, "author-1")
    entry2 = marketplace.publish(sample_strategy_2, "author-2")

    marketplace.rate("user-1", entry1.id, 3.0)
    marketplace.rate("user-1", entry2.id, 5.0)

    entries = marketplace.list_entries(sort_by="rating")

    assert len(entries) == 2
    assert entries[0].id == entry2.id  # Higher rating first
    assert entries[1].id == entry1.id


def test_list_entries_sort_by_subscribers(marketplace, sample_strategy, sample_strategy_2):
    """list_entries sorts by subscriber count descending."""
    entry1 = marketplace.publish(sample_strategy, "author-1")
    entry2 = marketplace.publish(sample_strategy_2, "author-2")

    marketplace.subscribe("user-1", entry1.id)
    marketplace.subscribe("user-2", entry1.id)
    marketplace.subscribe("user-3", entry1.id)

    marketplace.subscribe("user-1", entry2.id)

    entries = marketplace.list_entries(sort_by="subscribers")

    assert len(entries) == 2
    assert entries[0].id == entry1.id  # More subscribers first
    assert entries[1].id == entry2.id


def test_list_entries_sort_by_newest(marketplace, sample_strategy, sample_strategy_2):
    """list_entries sorts by created_at descending."""
    entry1 = marketplace.publish(sample_strategy, "author-1")
    time.sleep(0.01)  # Ensure different timestamps
    entry2 = marketplace.publish(sample_strategy_2, "author-2")

    entries = marketplace.list_entries(sort_by="newest")

    assert len(entries) == 2
    assert entries[0].id == entry2.id  # Newer first
    assert entries[1].id == entry1.id


def test_list_entries_pagination_limit(marketplace, sample_strategy, sample_strategy_2, sample_strategy_3):
    """list_entries respects limit parameter."""
    marketplace.publish(sample_strategy, "author-1")
    marketplace.publish(sample_strategy_2, "author-2")
    marketplace.publish(sample_strategy_3, "author-1")

    entries = marketplace.list_entries(limit=2)

    assert len(entries) == 2


def test_list_entries_pagination_offset(marketplace, sample_strategy, sample_strategy_2, sample_strategy_3):
    """list_entries respects offset parameter."""
    entry1 = marketplace.publish(sample_strategy, "author-1")
    entry2 = marketplace.publish(sample_strategy_2, "author-2")
    entry3 = marketplace.publish(sample_strategy_3, "author-1")

    # Rate to establish order
    marketplace.rate("user-1", entry1.id, 1.0)
    marketplace.rate("user-1", entry2.id, 3.0)
    marketplace.rate("user-1", entry3.id, 5.0)

    entries = marketplace.list_entries(sort_by="rating", offset=1, limit=2)

    assert len(entries) == 2
    assert entries[0].id == entry2.id
    assert entries[1].id == entry1.id


def test_list_entries_invalid_sort_uses_default(marketplace, sample_strategy):
    """list_entries uses default sort if sort_by is invalid."""
    entry = marketplace.publish(sample_strategy, "author-1")

    entries = marketplace.list_entries(sort_by="invalid")

    assert len(entries) == 1
    assert entries[0].id == entry.id


# ---------------------------------------------------------------------------
# Get User Subscriptions Tests
# ---------------------------------------------------------------------------


def test_get_user_subscriptions_empty(marketplace):
    """get_user_subscriptions returns empty list if no subscriptions."""
    entries = marketplace.get_user_subscriptions("user-1")
    assert entries == []


def test_get_user_subscriptions_returns_entries(marketplace, sample_strategy, sample_strategy_2):
    """get_user_subscriptions returns correct entries."""
    entry1 = marketplace.publish(sample_strategy, "author-1")
    entry2 = marketplace.publish(sample_strategy_2, "author-2")

    marketplace.subscribe("user-1", entry1.id)
    marketplace.subscribe("user-1", entry2.id)

    entries = marketplace.get_user_subscriptions("user-1")

    assert len(entries) == 2
    entry_ids = {e.id for e in entries}
    assert entry1.id in entry_ids
    assert entry2.id in entry_ids


def test_get_user_subscriptions_sorted_by_rating(marketplace, sample_strategy, sample_strategy_2):
    """get_user_subscriptions returns entries sorted by rating descending."""
    entry1 = marketplace.publish(sample_strategy, "author-1")
    entry2 = marketplace.publish(sample_strategy_2, "author-2")

    marketplace.subscribe("user-1", entry1.id)
    marketplace.subscribe("user-1", entry2.id)

    marketplace.rate("user-2", entry1.id, 3.0)
    marketplace.rate("user-2", entry2.id, 5.0)

    entries = marketplace.get_user_subscriptions("user-1")

    assert entries[0].id == entry2.id  # Higher rating first
    assert entries[1].id == entry1.id


def test_get_user_subscriptions_skips_deleted_entries(marketplace, sample_strategy):
    """get_user_subscriptions skips entries that have been deleted."""
    entry = marketplace.publish(sample_strategy, "author-1")
    marketplace.subscribe("user-1", entry.id)

    # Manually delete entry
    del marketplace._entries[entry.id]

    entries = marketplace.get_user_subscriptions("user-1")

    assert entries == []


# ---------------------------------------------------------------------------
# Get Author Entries Tests
# ---------------------------------------------------------------------------


def test_get_author_entries_empty(marketplace):
    """get_author_entries returns empty list if no entries."""
    entries = marketplace.get_author_entries("author-1")
    assert entries == []


def test_get_author_entries_returns_entries(marketplace, sample_strategy, sample_strategy_2, sample_strategy_3):
    """get_author_entries returns correct entries."""
    entry1 = marketplace.publish(sample_strategy, "author-1")
    entry2 = marketplace.publish(sample_strategy_2, "author-2")
    entry3 = marketplace.publish(sample_strategy_3, "author-1")

    entries = marketplace.get_author_entries("author-1")

    assert len(entries) == 2
    entry_ids = {e.id for e in entries}
    assert entry1.id in entry_ids
    assert entry3.id in entry_ids
    assert entry2.id not in entry_ids


def test_get_author_entries_sorted_by_newest(marketplace, sample_strategy, sample_strategy_3):
    """get_author_entries returns entries sorted by created_at descending."""
    entry1 = marketplace.publish(sample_strategy, "author-1")
    time.sleep(0.01)
    entry2 = marketplace.publish(sample_strategy_3, "author-1")

    entries = marketplace.get_author_entries("author-1")

    assert entries[0].id == entry2.id  # Newer first
    assert entries[1].id == entry1.id


# ---------------------------------------------------------------------------
# Search Tests
# ---------------------------------------------------------------------------


def test_search_empty_query_returns_empty(marketplace, sample_strategy):
    """search returns empty list for empty query."""
    marketplace.publish(sample_strategy, "author-1")

    assert marketplace.search("") == []
    assert marketplace.search("  ") == []


def test_search_finds_by_name(marketplace, sample_strategy, sample_strategy_2):
    """search finds entries by name."""
    entry1 = marketplace.publish(sample_strategy, "author-1")
    marketplace.publish(sample_strategy_2, "author-2")

    results = marketplace.search("My Strategy")

    assert len(results) == 1
    assert results[0].id == entry1.id


def test_search_finds_by_description(marketplace, sample_strategy):
    """search finds entries by description."""
    entry = marketplace.publish(sample_strategy, "author-1")

    results = marketplace.search("test strategy")

    assert len(results) == 1
    assert results[0].id == entry.id


def test_search_case_insensitive(marketplace, sample_strategy):
    """search is case-insensitive."""
    entry = marketplace.publish(sample_strategy, "author-1")

    results = marketplace.search("MY STRATEGY")

    assert len(results) == 1
    assert results[0].id == entry.id


def test_search_partial_match(marketplace, sample_strategy):
    """search matches partial strings."""
    entry = marketplace.publish(sample_strategy, "author-1")

    results = marketplace.search("Strat")

    assert len(results) == 1
    assert results[0].id == entry.id


def test_search_multiple_results_sorted_by_rating(marketplace, sample_strategy, sample_strategy_2):
    """search returns multiple results sorted by rating."""
    entry1 = marketplace.publish(sample_strategy, "author-1", name="Great Strategy")
    entry2 = marketplace.publish(sample_strategy_2, "author-2", name="Better Strategy")

    marketplace.rate("user-1", entry1.id, 3.0)
    marketplace.rate("user-1", entry2.id, 5.0)

    results = marketplace.search("Strategy")

    assert len(results) == 2
    assert results[0].id == entry2.id  # Higher rating first
    assert results[1].id == entry1.id


def test_search_no_matches(marketplace, sample_strategy):
    """search returns empty list if no matches."""
    marketplace.publish(sample_strategy, "author-1")

    results = marketplace.search("nonexistent")

    assert results == []


# ---------------------------------------------------------------------------
# Get Top Performers Tests
# ---------------------------------------------------------------------------


def test_get_top_performers_empty(marketplace):
    """get_top_performers returns empty list on empty marketplace."""
    results = marketplace.get_top_performers()
    assert results == []


def test_get_top_performers_sorts_by_sharpe(marketplace, sample_strategy, sample_strategy_2, sample_strategy_3):
    """get_top_performers sorts by Sharpe ratio descending."""
    entry1 = marketplace.publish(sample_strategy, "author-1")  # Sharpe 1.5
    entry2 = marketplace.publish(sample_strategy_2, "author-2")  # Sharpe 2.5
    entry3 = marketplace.publish(sample_strategy_3, "author-1")  # Sharpe 0.8

    results = marketplace.get_top_performers(limit=3)

    assert len(results) == 3
    assert results[0].id == entry2.id  # Highest Sharpe first
    assert results[1].id == entry1.id
    assert results[2].id == entry3.id


def test_get_top_performers_respects_limit(marketplace, sample_strategy, sample_strategy_2, sample_strategy_3):
    """get_top_performers respects limit parameter."""
    marketplace.publish(sample_strategy, "author-1")
    marketplace.publish(sample_strategy_2, "author-2")
    marketplace.publish(sample_strategy_3, "author-1")

    results = marketplace.get_top_performers(limit=2)

    assert len(results) == 2


def test_get_top_performers_secondary_sort_by_win_rate(marketplace):
    """get_top_performers uses win_rate as secondary sort if Sharpe is equal."""
    strategy1 = Strategy(
        id=str(uuid4()),
        user_id="user-1",
        name="Strategy 1",
        rules=[],
        performance={"sharpe": 1.0, "win_rate": 0.60},
    )
    strategy2 = Strategy(
        id=str(uuid4()),
        user_id="user-2",
        name="Strategy 2",
        rules=[],
        performance={"sharpe": 1.0, "win_rate": 0.70},
    )

    entry1 = marketplace.publish(strategy1, "author-1")
    entry2 = marketplace.publish(strategy2, "author-2")

    results = marketplace.get_top_performers()

    assert results[0].id == entry2.id  # Higher win_rate with same Sharpe
    assert results[1].id == entry1.id


def test_get_top_performers_missing_sharpe(marketplace):
    """get_top_performers treats missing Sharpe as 0.0."""
    strategy = Strategy(
        id=str(uuid4()),
        user_id="user-1",
        name="Strategy",
        rules=[],
        performance={},  # No Sharpe
    )

    entry = marketplace.publish(strategy, "author-1")

    results = marketplace.get_top_performers()

    assert len(results) == 1
    assert results[0].id == entry.id


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


def test_contains_operator(marketplace, sample_strategy):
    """__contains__ checks if entry exists."""
    entry = marketplace.publish(sample_strategy, "author-1")

    assert entry.id in marketplace
    assert "non-existent-id" not in marketplace


def test_len_operator(marketplace, sample_strategy, sample_strategy_2):
    """__len__ returns number of entries."""
    assert len(marketplace) == 0

    marketplace.publish(sample_strategy, "author-1")
    assert len(marketplace) == 1

    marketplace.publish(sample_strategy_2, "author-2")
    assert len(marketplace) == 2


def test_unpublish_with_active_subscriptions_and_ratings(marketplace, sample_strategy):
    """unpublish cleans up both subscriptions and ratings."""
    entry = marketplace.publish(sample_strategy, "author-1")

    marketplace.subscribe("user-1", entry.id)
    marketplace.subscribe("user-2", entry.id)
    marketplace.rate("user-1", entry.id, 5.0)
    marketplace.rate("user-2", entry.id, 4.0)

    marketplace.unpublish(entry.id, "author-1")

    assert entry.id not in marketplace
    assert entry.id not in marketplace._ratings
    assert entry.id not in marketplace._subscriptions.get("user-1", set())
    assert entry.id not in marketplace._subscriptions.get("user-2", set())


def test_multiple_operations_sequence(marketplace, sample_strategy):
    """Test a realistic sequence of marketplace operations."""
    # Publish
    entry = marketplace.publish(sample_strategy, "author-1")
    assert len(marketplace) == 1

    # Subscribe
    marketplace.subscribe("user-1", entry.id)
    marketplace.subscribe("user-2", entry.id)
    assert marketplace.get_entry(entry.id).subscriber_count == 2

    # Rate
    marketplace.rate("user-1", entry.id, 5.0)
    marketplace.rate("user-2", entry.id, 4.0)
    assert marketplace.get_entry(entry.id).rating == 4.5

    # Unsubscribe
    marketplace.unsubscribe("user-1", entry.id)
    assert marketplace.get_entry(entry.id).subscriber_count == 1

    # Update rating
    marketplace.rate("user-1", entry.id, 3.0)
    assert marketplace.get_entry(entry.id).rating == 3.5

    # Unpublish
    marketplace.unpublish(entry.id, "author-1")
    assert len(marketplace) == 0
