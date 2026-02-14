"""Tests for badge registry and badge lookup functions."""

import pytest

from rot.gamification.badges import (
    BADGE_REGISTRY,
    get_badge_by_id,
    get_badges_by_category,
    get_badges_by_rarity,
)
from rot.gamification.types import Badge

# Point values (from badges module)
POINTS_COMMON = 10
POINTS_RARE = 25
POINTS_EPIC = 50
POINTS_LEGENDARY = 100


# ============================================================================
# BADGE_REGISTRY completeness tests
# ============================================================================


def test_badge_registry_is_list():
    """Test BADGE_REGISTRY is a list."""
    assert isinstance(BADGE_REGISTRY, list)
    assert len(BADGE_REGISTRY) > 0


def test_badge_registry_all_badges():
    """Test BADGE_REGISTRY contains all Badge instances."""
    for badge in BADGE_REGISTRY:
        assert isinstance(badge, Badge)


def test_badge_registry_has_all_categories():
    """Test BADGE_REGISTRY contains badges from all categories."""
    categories = {"activity", "streak", "trading", "accuracy", "social", "premium"}
    found_categories = {b.category for b in BADGE_REGISTRY}
    assert found_categories == categories


def test_badge_registry_has_all_rarities():
    """Test BADGE_REGISTRY contains badges of all rarities."""
    rarities = {"common", "rare", "epic", "legendary"}
    found_rarities = {b.rarity for b in BADGE_REGISTRY}
    assert found_rarities == rarities


def test_badge_registry_activity_badges():
    """Test BADGE_REGISTRY contains expected activity badges."""
    activity_badges = [b for b in BADGE_REGISTRY if b.category == "activity"]
    assert len(activity_badges) >= 2
    badge_ids = {b.id for b in activity_badges}
    assert "first_steps" in badge_ids
    assert "signal_seeker" in badge_ids


def test_badge_registry_streak_badges():
    """Test BADGE_REGISTRY contains expected streak badges."""
    streak_badges = [b for b in BADGE_REGISTRY if b.category == "streak"]
    assert len(streak_badges) >= 3
    badge_ids = {b.id for b in streak_badges}
    assert "weekly_warrior" in badge_ids
    assert "monthly_master" in badge_ids
    assert "rot_addict" in badge_ids


def test_badge_registry_trading_badges():
    """Test BADGE_REGISTRY contains expected trading badges."""
    trading_badges = [b for b in BADGE_REGISTRY if b.category == "trading"]
    assert len(trading_badges) >= 3
    badge_ids = {b.id for b in trading_badges}
    assert "paper_hands" in badge_ids
    assert "day_trader" in badge_ids


def test_badge_registry_accuracy_badges():
    """Test BADGE_REGISTRY contains expected accuracy badges."""
    accuracy_badges = [b for b in BADGE_REGISTRY if b.category == "accuracy"]
    assert len(accuracy_badges) >= 4
    badge_ids = {b.id for b in accuracy_badges}
    assert "lucky_guess" in badge_ids
    assert "sniper" in badge_ids


def test_badge_registry_social_badges():
    """Test BADGE_REGISTRY contains expected social badges."""
    social_badges = [b for b in BADGE_REGISTRY if b.category == "social"]
    assert len(social_badges) >= 2
    badge_ids = {b.id for b in social_badges}
    assert "watchlist_watcher" in badge_ids


def test_badge_registry_premium_badges():
    """Test BADGE_REGISTRY contains expected premium badges."""
    premium_badges = [b for b in BADGE_REGISTRY if b.category == "premium"]
    assert len(premium_badges) >= 4
    badge_ids = {b.id for b in premium_badges}
    assert "supporter" in badge_ids
    assert "power_user" in badge_ids
    assert "ultra_trader" in badge_ids
    assert "enterprise_champion" in badge_ids


# ============================================================================
# Unlock criteria validation tests
# ============================================================================


def test_all_badges_have_unlock_criteria():
    """Test all badges have unlock_criteria defined."""
    for badge in BADGE_REGISTRY:
        assert badge.unlock_criteria is not None
        assert isinstance(badge.unlock_criteria, dict)
        assert "metric" in badge.unlock_criteria
        assert "threshold" in badge.unlock_criteria


def test_all_badges_have_metric():
    """Test all badges have a metric in unlock_criteria."""
    for badge in BADGE_REGISTRY:
        metric = badge.unlock_criteria.get("metric")
        assert metric is not None
        assert isinstance(metric, str)
        assert len(metric) > 0


def test_all_badges_have_threshold():
    """Test all badges have a threshold in unlock_criteria."""
    for badge in BADGE_REGISTRY:
        threshold = badge.unlock_criteria.get("threshold")
        assert threshold is not None
        # Can be int, float, or string (for tier badges)
        assert isinstance(threshold, (int, float, str))


def test_numeric_thresholds_are_positive():
    """Test numeric thresholds are positive values."""
    for badge in BADGE_REGISTRY:
        threshold = badge.unlock_criteria.get("threshold")
        if isinstance(threshold, (int, float)):
            assert threshold > 0


def test_streak_badges_use_streak_metric():
    """Test streak badges use appropriate metrics."""
    streak_badges = [b for b in BADGE_REGISTRY if b.category == "streak"]
    for badge in streak_badges:
        metric = badge.unlock_criteria["metric"]
        assert "streak" in metric.lower() or metric in ["current_streak_days", "longest_streak_days"]


def test_premium_badges_use_tier_metric():
    """Test premium badges use tier metric."""
    premium_badges = [b for b in BADGE_REGISTRY if b.category == "premium"]
    for badge in premium_badges:
        assert badge.unlock_criteria["metric"] == "tier"
        assert isinstance(badge.unlock_criteria["threshold"], str)


# ============================================================================
# Point values match rarity tests
# ============================================================================


def test_point_values_constants():
    """Test point value constants are defined correctly."""
    assert POINTS_COMMON == 10
    assert POINTS_RARE == 25
    assert POINTS_EPIC == 50
    assert POINTS_LEGENDARY == 100


def test_common_badges_have_10_points():
    """Test all common badges have 10 points."""
    common_badges = [b for b in BADGE_REGISTRY if b.rarity == "common"]
    for badge in common_badges:
        assert badge.points == POINTS_COMMON


def test_rare_badges_have_25_points():
    """Test all rare badges have 25 points."""
    rare_badges = [b for b in BADGE_REGISTRY if b.rarity == "rare"]
    for badge in rare_badges:
        assert badge.points == POINTS_RARE


def test_epic_badges_have_50_points():
    """Test all epic badges have 50 points."""
    epic_badges = [b for b in BADGE_REGISTRY if b.rarity == "epic"]
    for badge in epic_badges:
        assert badge.points == POINTS_EPIC


def test_legendary_badges_have_100_points():
    """Test all legendary badges have 100 points."""
    legendary_badges = [b for b in BADGE_REGISTRY if b.rarity == "legendary"]
    for badge in legendary_badges:
        assert badge.points == POINTS_LEGENDARY


def test_all_badges_have_valid_points():
    """Test all badges have points matching their rarity."""
    point_map = {
        "common": POINTS_COMMON,
        "rare": POINTS_RARE,
        "epic": POINTS_EPIC,
        "legendary": POINTS_LEGENDARY,
    }
    for badge in BADGE_REGISTRY:
        expected_points = point_map[badge.rarity]
        assert badge.points == expected_points


# ============================================================================
# Badge ID uniqueness tests
# ============================================================================


def test_no_duplicate_badge_ids():
    """Test all badge IDs are unique."""
    badge_ids = [b.id for b in BADGE_REGISTRY]
    assert len(badge_ids) == len(set(badge_ids))


def test_badge_by_id_lookup_all_badges():
    """Test get_badge_by_id can retrieve all badges."""
    for badge in BADGE_REGISTRY:
        found = get_badge_by_id(badge.id)
        assert found is not None
        assert found == badge


# ============================================================================
# Icon emoji presence tests
# ============================================================================


def test_all_badges_have_icon_emoji():
    """Test all badges have an icon emoji."""
    for badge in BADGE_REGISTRY:
        assert badge.icon_emoji is not None
        assert isinstance(badge.icon_emoji, str)
        assert len(badge.icon_emoji) > 0


def test_icon_emojis_are_unique():
    """Test badge icons are reasonably diverse (at least 50% unique)."""
    icons = [b.icon_emoji for b in BADGE_REGISTRY]
    unique_icons = set(icons)
    # Allow some reuse but expect decent variety
    assert len(unique_icons) >= len(icons) * 0.5


# ============================================================================
# get_badge_by_id() tests
# ============================================================================


def test_get_badge_existing():
    """Test get_badge returns badge for valid ID."""
    badge = get_badge_by_id("first_steps")
    assert badge is not None
    assert isinstance(badge, Badge)
    assert badge.id == "first_steps"


def test_get_badge_nonexistent():
    """Test get_badge returns None for invalid ID."""
    badge = get_badge_by_id("nonexistent_badge")
    assert badge is None


def test_get_badge_all_registry_badges():
    """Test get_badge works for all badges in registry."""
    for expected_badge in BADGE_REGISTRY:
        badge = get_badge_by_id(expected_badge.id)
        assert badge is not None
        assert badge == expected_badge


def test_get_badge_case_sensitive():
    """Test get_badge is case-sensitive."""
    badge = get_badge_by_id("FIRST_STEPS")
    assert badge is None


# ============================================================================
# get_badges_by_category() tests
# ============================================================================


def test_get_badges_by_category_activity():
    """Test get_badges_by_category returns activity badges."""
    badges = get_badges_by_category("activity")
    assert len(badges) > 0
    assert all(b.category == "activity" for b in badges)


def test_get_badges_by_category_streak():
    """Test get_badges_by_category returns streak badges."""
    badges = get_badges_by_category("streak")
    assert len(badges) > 0
    assert all(b.category == "streak" for b in badges)


def test_get_badges_by_category_trading():
    """Test get_badges_by_category returns trading badges."""
    badges = get_badges_by_category("trading")
    assert len(badges) > 0
    assert all(b.category == "trading" for b in badges)


def test_get_badges_by_category_accuracy():
    """Test get_badges_by_category returns accuracy badges."""
    badges = get_badges_by_category("accuracy")
    assert len(badges) > 0
    assert all(b.category == "accuracy" for b in badges)


def test_get_badges_by_category_social():
    """Test get_badges_by_category returns social badges."""
    badges = get_badges_by_category("social")
    assert len(badges) > 0
    assert all(b.category == "social" for b in badges)


def test_get_badges_by_category_premium():
    """Test get_badges_by_category returns premium badges."""
    badges = get_badges_by_category("premium")
    assert len(badges) > 0
    assert all(b.category == "premium" for b in badges)


def test_get_badges_by_category_nonexistent():
    """Test get_badges_by_category returns empty list for invalid category."""
    badges = get_badges_by_category("nonexistent")
    assert badges == []


def test_get_badges_by_category_all_categories():
    """Test get_badges_by_category covers all badges."""
    all_categories = ["activity", "streak", "trading", "accuracy", "social", "premium"]
    total_badges = 0
    for category in all_categories:
        badges = get_badges_by_category(category)
        total_badges += len(badges)
    assert total_badges == len(BADGE_REGISTRY)


# ============================================================================
# get_badges_by_rarity() tests
# ============================================================================


def test_get_badges_by_rarity_common():
    """Test get_badges_by_rarity returns common badges."""
    badges = get_badges_by_rarity("common")
    assert len(badges) > 0
    assert all(b.rarity == "common" for b in badges)
    assert all(b.points == POINTS_COMMON for b in badges)


def test_get_badges_by_rarity_rare():
    """Test get_badges_by_rarity returns rare badges."""
    badges = get_badges_by_rarity("rare")
    assert len(badges) > 0
    assert all(b.rarity == "rare" for b in badges)
    assert all(b.points == POINTS_RARE for b in badges)


def test_get_badges_by_rarity_epic():
    """Test get_badges_by_rarity returns epic badges."""
    badges = get_badges_by_rarity("epic")
    assert len(badges) > 0
    assert all(b.rarity == "epic" for b in badges)
    assert all(b.points == POINTS_EPIC for b in badges)


def test_get_badges_by_rarity_legendary():
    """Test get_badges_by_rarity returns legendary badges."""
    badges = get_badges_by_rarity("legendary")
    assert len(badges) > 0
    assert all(b.rarity == "legendary" for b in badges)
    assert all(b.points == POINTS_LEGENDARY for b in badges)


def test_get_badges_by_rarity_nonexistent():
    """Test get_badges_by_rarity returns empty list for invalid rarity."""
    badges = get_badges_by_rarity("mythic")
    assert badges == []


def test_get_badges_by_rarity_all_rarities():
    """Test get_badges_by_rarity covers all badges."""
    all_rarities = ["common", "rare", "epic", "legendary"]
    total_badges = 0
    for rarity in all_rarities:
        badges = get_badges_by_rarity(rarity)
        total_badges += len(badges)
    assert total_badges == len(BADGE_REGISTRY)


# ============================================================================
# Specific badge validation tests
# ============================================================================


def test_first_steps_badge():
    """Test first_steps badge has correct properties."""
    badge = get_badge_by_id("first_steps")
    assert badge is not None
    assert badge.name == "First Steps"
    assert badge.category == "activity"
    assert badge.rarity == "common"
    assert badge.points == POINTS_COMMON
    assert badge.unlock_criteria["metric"] == "total_logins"
    assert badge.unlock_criteria["threshold"] == 1


def test_weekly_warrior_badge():
    """Test weekly_warrior badge has correct properties."""
    badge = get_badge_by_id("weekly_warrior")
    assert badge is not None
    assert badge.name == "Weekly Warrior"
    assert badge.category == "streak"
    assert badge.rarity == "rare"
    assert badge.points == POINTS_RARE
    assert badge.unlock_criteria["metric"] == "current_streak_days"
    assert badge.unlock_criteria["threshold"] == 7


def test_rot_addict_badge():
    """Test rot_addict badge has correct properties."""
    badge = get_badge_by_id("rot_addict")
    assert badge is not None
    assert badge.name == "ROT Addict"
    assert badge.category == "streak"
    assert badge.rarity == "legendary"
    assert badge.points == POINTS_LEGENDARY
    assert badge.unlock_criteria["metric"] == "current_streak_days"
    assert badge.unlock_criteria["threshold"] == 100


def test_sniper_badge():
    """Test sniper badge has correct properties."""
    badge = get_badge_by_id("sniper")
    assert badge is not None
    assert badge.name == "Sniper"
    assert badge.category == "accuracy"
    assert badge.rarity == "epic"
    assert badge.points == POINTS_EPIC
    assert badge.unlock_criteria["metric"] == "consecutive_correct"
    assert badge.unlock_criteria["threshold"] == 5


def test_enterprise_champion_badge():
    """Test enterprise_champion badge has correct properties."""
    badge = get_badge_by_id("enterprise_champion")
    assert badge is not None
    assert badge.name == "Enterprise Champion"
    assert badge.category == "premium"
    assert badge.rarity == "legendary"
    assert badge.points == POINTS_LEGENDARY
    assert badge.unlock_criteria["metric"] == "tier"
    assert badge.unlock_criteria["threshold"] == "enterprise"


def test_early_adopter_badge():
    """Test early_adopter badge configuration."""
    badge = get_badge_by_id("early_adopter")
    assert badge is not None
    assert badge.name == "Early Adopter"
    assert badge.category == "social"
    assert badge.rarity == "legendary"
    assert badge.unlock_criteria["metric"] == "early_adopter"
    assert badge.unlock_criteria["threshold"] == 1
