"""
Badge registry with all available badges and unlock criteria.

This module defines the complete set of badges users can unlock,
organized by category with appropriate point values based on rarity.
"""

from .types import Badge

# Point values by rarity
POINTS_COMMON = 10
POINTS_RARE = 25
POINTS_EPIC = 50
POINTS_LEGENDARY = 100

# Complete badge registry
BADGE_REGISTRY: list[Badge] = [
    # === ACTIVITY BADGES ===
    Badge(
        id="first_steps",
        name="First Steps",
        description="Complete your first login",
        category="activity",
        rarity="common",
        icon_emoji="👣",
        unlock_criteria={"metric": "total_logins", "threshold": 1},
        points=POINTS_COMMON,
    ),
    Badge(
        id="weekly_warrior",
        name="Weekly Warrior",
        description="Login 7 days in a row",
        category="streak",
        rarity="rare",
        icon_emoji="⚔️",
        unlock_criteria={"metric": "current_streak_days", "threshold": 7},
        points=POINTS_RARE,
    ),
    Badge(
        id="monthly_master",
        name="Monthly Master",
        description="Login 30 days in a row",
        category="streak",
        rarity="epic",
        icon_emoji="👑",
        unlock_criteria={"metric": "current_streak_days", "threshold": 30},
        points=POINTS_EPIC,
    ),
    Badge(
        id="rot_addict",
        name="ROT Addict",
        description="Login 100 days in a row",
        category="streak",
        rarity="legendary",
        icon_emoji="🔥",
        unlock_criteria={"metric": "current_streak_days", "threshold": 100},
        points=POINTS_LEGENDARY,
    ),
    Badge(
        id="signal_seeker",
        name="Signal Seeker",
        description="View 50 signals",
        category="activity",
        rarity="common",
        icon_emoji="🔍",
        unlock_criteria={"metric": "signals_viewed", "threshold": 50},
        points=POINTS_COMMON,
    ),
    Badge(
        id="signal_scholar",
        name="Signal Scholar",
        description="View 500 signals",
        category="activity",
        rarity="rare",
        icon_emoji="📚",
        unlock_criteria={"metric": "signals_viewed", "threshold": 500},
        points=POINTS_RARE,
    ),

    # === TRADING BADGES ===
    Badge(
        id="paper_hands",
        name="Paper Hands",
        description="Execute your first paper trade",
        category="trading",
        rarity="common",
        icon_emoji="📄",
        unlock_criteria={"metric": "trades_executed", "threshold": 1},
        points=POINTS_COMMON,
    ),
    Badge(
        id="day_trader",
        name="Day Trader",
        description="Execute 10 trades in a single day",
        category="trading",
        rarity="rare",
        icon_emoji="📈",
        unlock_criteria={"metric": "trades_in_day", "threshold": 10},
        points=POINTS_RARE,
    ),
    Badge(
        id="portfolio_builder",
        name="Portfolio Builder",
        description="Execute 100 trades total",
        category="trading",
        rarity="epic",
        icon_emoji="💼",
        unlock_criteria={"metric": "trades_executed", "threshold": 100},
        points=POINTS_EPIC,
    ),
    Badge(
        id="whale_watcher",
        name="Whale Watcher",
        description="Execute a trade with >$10,000 notional value",
        category="trading",
        rarity="rare",
        icon_emoji="🐋",
        unlock_criteria={"metric": "max_trade_notional", "threshold": 10000},
        points=POINTS_RARE,
    ),

    # === ACCURACY BADGES ===
    Badge(
        id="lucky_guess",
        name="Lucky Guess",
        description="Make your first correct prediction",
        category="accuracy",
        rarity="common",
        icon_emoji="🎲",
        unlock_criteria={"metric": "predictions_correct", "threshold": 1},
        points=POINTS_COMMON,
    ),
    Badge(
        id="sharp_eye",
        name="Sharp Eye",
        description="Make 10 correct predictions",
        category="accuracy",
        rarity="rare",
        icon_emoji="👁️",
        unlock_criteria={"metric": "predictions_correct", "threshold": 10},
        points=POINTS_RARE,
    ),
    Badge(
        id="oracle",
        name="Oracle",
        description="Make 50 correct predictions",
        category="accuracy",
        rarity="epic",
        icon_emoji="🔮",
        unlock_criteria={"metric": "predictions_correct", "threshold": 50},
        points=POINTS_EPIC,
    ),
    Badge(
        id="nostradamus",
        name="Nostradamus",
        description="Make 100 correct predictions",
        category="accuracy",
        rarity="legendary",
        icon_emoji="✨",
        unlock_criteria={"metric": "predictions_correct", "threshold": 100},
        points=POINTS_LEGENDARY,
    ),
    Badge(
        id="sniper",
        name="Sniper",
        description="Make 5 consecutive correct predictions",
        category="accuracy",
        rarity="epic",
        icon_emoji="🎯",
        unlock_criteria={"metric": "consecutive_correct", "threshold": 5},
        points=POINTS_EPIC,
    ),

    # === SOCIAL BADGES ===
    Badge(
        id="watchlist_watcher",
        name="Watchlist Watcher",
        description="Add 5 tickers to your watchlist",
        category="social",
        rarity="common",
        icon_emoji="📝",
        unlock_criteria={"metric": "watchlist_tickers", "threshold": 5},
        points=POINTS_COMMON,
    ),
    Badge(
        id="filter_master",
        name="Filter Master",
        description="Create 3 filter presets",
        category="social",
        rarity="rare",
        icon_emoji="⚙️",
        unlock_criteria={"metric": "filter_presets", "threshold": 3},
        points=POINTS_RARE,
    ),
    Badge(
        id="early_adopter",
        name="Early Adopter",
        description="Account created in the first month of launch",
        category="social",
        rarity="legendary",
        icon_emoji="🌟",
        unlock_criteria={"metric": "account_age_days", "threshold": 30, "reverse": True},
        points=POINTS_LEGENDARY,
    ),

    # === PREMIUM BADGES ===
    Badge(
        id="supporter",
        name="Supporter",
        description="Upgrade to Pro tier",
        category="premium",
        rarity="rare",
        icon_emoji="💎",
        unlock_criteria={"metric": "tier", "threshold": "pro"},
        points=POINTS_RARE,
    ),
    Badge(
        id="power_user",
        name="Power User",
        description="Upgrade to Premium tier",
        category="premium",
        rarity="epic",
        icon_emoji="⚡",
        unlock_criteria={"metric": "tier", "threshold": "premium"},
        points=POINTS_EPIC,
    ),
    Badge(
        id="ultra_trader",
        name="Ultra Trader",
        description="Upgrade to Ultra tier",
        category="premium",
        rarity="epic",
        icon_emoji="🚀",
        unlock_criteria={"metric": "tier", "threshold": "ultra"},
        points=POINTS_EPIC,
    ),
    Badge(
        id="enterprise_champion",
        name="Enterprise Champion",
        description="Upgrade to Enterprise tier",
        category="premium",
        rarity="legendary",
        icon_emoji="🏆",
        unlock_criteria={"metric": "tier", "threshold": "enterprise"},
        points=POINTS_LEGENDARY,
    ),
]

# Create lookup dict for fast access
BADGE_BY_ID = {badge.id: badge for badge in BADGE_REGISTRY}


def get_badge(badge_id: str) -> Badge | None:
    """Get a badge by its ID."""
    return BADGE_BY_ID.get(badge_id)


def get_badge_by_id(badge_id: str) -> Badge | None:
    """Get a badge by its ID (alias for get_badge)."""
    return get_badge(badge_id)


def get_badges_by_category(category: str) -> list[Badge]:
    """Get all badges in a specific category."""
    return [b for b in BADGE_REGISTRY if b.category == category]


def get_badges_by_rarity(rarity: str) -> list[Badge]:
    """Get all badges of a specific rarity."""
    return [b for b in BADGE_REGISTRY if b.rarity == rarity]
