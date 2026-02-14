"""Frozen dataclasses for the Strategy Builder & ML Optimizer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RULE_OPERATORS = ("gt", "lt", "gte", "lte", "eq", "neq", "in")
"""Supported comparison operators for strategy rules."""

STRATEGY_SOURCES = (
    "manual",
    "discovered",
    "ml_optimized",
    "genetic",
    "marketplace",
)
"""How a strategy was created."""

REGIME_TYPES = ("bull", "bear", "sideways", "volatile", "crisis")
"""Market regime classifications."""

POSITION_SIZING_MODES = ("fixed", "kelly", "confidence")
"""How to size positions in auto-trading."""


# ---------------------------------------------------------------------------
# StrategyRule — single filter condition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyRule:
    """A single filter rule applied to a signal dict.

    Examples:
        StrategyRule(field="confidence", operator="gte", value=0.5)
        StrategyRule(field="stance", operator="eq", value="bullish")
        StrategyRule(field="event_type", operator="in", value=["earnings_rumor", "product_news"])
    """

    field: str
    operator: str
    value: Any

    def __post_init__(self) -> None:
        if not self.field or not isinstance(self.field, str):
            raise ValueError("field must be a non-empty string")
        if self.operator not in RULE_OPERATORS:
            raise ValueError(
                f"operator must be one of {RULE_OPERATORS}, got '{self.operator}'"
            )

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "operator": self.operator,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyRule":
        return cls(
            field=d["field"],
            operator=d["operator"],
            value=d["value"],
        )


# ---------------------------------------------------------------------------
# Strategy — collection of rules + config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Strategy:
    """A named set of rules that filters signals for auto paper-trading.

    Attributes:
        id: Unique identifier (UUID).
        user_id: Owner user ID.
        name: Human-readable name.
        description: Optional description.
        rules: List of StrategyRule that must ALL match (AND logic).
        config: Extra config (position_sizing, stop_loss_pct, take_profit_pct, max_concurrent).
        performance: Cached performance stats (win_rate, sharpe, total_trades, etc.).
        health_score: Rolling health metric 0.0-1.0 (1.0 = healthy).
        is_active: Whether auto-trading is enabled.
        source: How the strategy was created.
        created_at: Unix timestamp.
        updated_at: Unix timestamp.
    """

    id: str
    user_id: str
    name: str
    rules: list[StrategyRule]
    description: str = ""
    config: dict = field(default_factory=dict)
    performance: dict = field(default_factory=dict)
    health_score: float = 1.0
    is_active: bool = False
    source: str = "manual"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.user_id:
            raise ValueError("user_id must be non-empty")
        if not self.name or not isinstance(self.name, str):
            raise ValueError("name must be a non-empty string")
        if not isinstance(self.rules, list):
            raise ValueError("rules must be a list")
        if self.source not in STRATEGY_SOURCES:
            raise ValueError(
                f"source must be one of {STRATEGY_SOURCES}, got '{self.source}'"
            )
        if not (0.0 <= self.health_score <= 1.0):
            raise ValueError("health_score must be between 0.0 and 1.0")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "description": self.description,
            "rules": [r.to_dict() for r in self.rules],
            "config": self.config,
            "performance": self.performance,
            "health_score": self.health_score,
            "is_active": self.is_active,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Strategy":
        return cls(
            id=d["id"],
            user_id=d["user_id"],
            name=d["name"],
            description=d.get("description", ""),
            rules=[StrategyRule.from_dict(r) for r in d.get("rules", [])],
            config=d.get("config", {}),
            performance=d.get("performance", {}),
            health_score=d.get("health_score", 1.0),
            is_active=d.get("is_active", False),
            source=d.get("source", "manual"),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
        )


# ---------------------------------------------------------------------------
# StrategyResult — one trade outcome for a strategy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyResult:
    """A single trade executed by a strategy.

    Attributes:
        id: Unique trade ID.
        strategy_id: Owning strategy.
        signal_id: Signal that triggered the trade.
        ticker: Ticker symbol.
        stance: bullish/bearish.
        entry_price: Entry price.
        exit_price: Exit price (None if open).
        pnl_pct: Realised P&L percentage (None if open).
        created_at: When the trade was opened.
        resolved_at: When the trade was closed (None if open).
    """

    id: str
    strategy_id: str
    signal_id: str
    ticker: str
    stance: str
    entry_price: float
    exit_price: float | None = None
    pnl_pct: float | None = None
    created_at: float = field(default_factory=time.time)
    resolved_at: float | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")
        if not self.signal_id:
            raise ValueError("signal_id must be non-empty")
        if not self.ticker:
            raise ValueError("ticker must be non-empty")
        if self.stance not in ("bullish", "bearish"):
            raise ValueError(f"stance must be bullish or bearish, got '{self.stance}'")
        if self.entry_price <= 0:
            raise ValueError("entry_price must be positive")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "strategy_id": self.strategy_id,
            "signal_id": self.signal_id,
            "ticker": self.ticker,
            "stance": self.stance,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl_pct": self.pnl_pct,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


# ---------------------------------------------------------------------------
# DiscoveryResult — output of strategy search
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiscoveryResult:
    """Result of a strategy discovery / search run.

    Attributes:
        id: Unique discovery run ID.
        user_id: Who ran the discovery.
        search_config: The search parameters used.
        strategies_found: Number of strategies that met criteria.
        best_strategies: Top N strategies discovered (as dicts).
        elapsed_s: Wall-clock time in seconds.
        created_at: Unix timestamp.
    """

    id: str
    user_id: str
    search_config: dict
    strategies_found: int
    best_strategies: list[dict] = field(default_factory=list)
    elapsed_s: float = 0.0
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.user_id:
            raise ValueError("user_id must be non-empty")
        if self.strategies_found < 0:
            raise ValueError("strategies_found must be >= 0")
        if self.elapsed_s < 0:
            raise ValueError("elapsed_s must be >= 0")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "search_config": self.search_config,
            "strategies_found": self.strategies_found,
            "best_strategies": self.best_strategies,
            "elapsed_s": self.elapsed_s,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# MarketRegime — current or historical market regime
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MarketRegime:
    """A detected market regime period.

    Attributes:
        id: Unique ID.
        regime_type: One of REGIME_TYPES.
        start_ts: Unix timestamp when regime started.
        end_ts: Unix timestamp when regime ended (None = ongoing).
        indicators: Dict of indicator values that determined the regime.
        confidence: How confident the detection is (0.0-1.0).
        detected_at: When the regime was first detected.
    """

    id: str
    regime_type: str
    start_ts: float
    indicators: dict = field(default_factory=dict)
    end_ts: float | None = None
    confidence: float = 0.5
    detected_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if self.regime_type not in REGIME_TYPES:
            raise ValueError(
                f"regime_type must be one of {REGIME_TYPES}, got '{self.regime_type}'"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.end_ts is not None and self.end_ts < self.start_ts:
            raise ValueError("end_ts must be >= start_ts")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "regime_type": self.regime_type,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "indicators": self.indicators,
            "confidence": self.confidence,
            "detected_at": self.detected_at,
        }


# ---------------------------------------------------------------------------
# RegimeStrategy — maps a strategy to its regime performance
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegimeStrategy:
    """Performance of a strategy under a specific market regime.

    Attributes:
        strategy_id: The strategy.
        regime_type: Which regime.
        win_rate: Win rate in this regime.
        sharpe: Sharpe ratio in this regime.
        total_trades: Number of trades in this regime.
        avg_pnl_pct: Average P&L per trade.
        recommended: Whether the strategy is recommended for this regime.
    """

    strategy_id: str
    regime_type: str
    win_rate: float = 0.0
    sharpe: float = 0.0
    total_trades: int = 0
    avg_pnl_pct: float = 0.0
    recommended: bool = False

    def __post_init__(self) -> None:
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")
        if self.regime_type not in REGIME_TYPES:
            raise ValueError(
                f"regime_type must be one of {REGIME_TYPES}, got '{self.regime_type}'"
            )
        if not (0.0 <= self.win_rate <= 1.0):
            raise ValueError("win_rate must be between 0.0 and 1.0")

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "regime_type": self.regime_type,
            "win_rate": self.win_rate,
            "sharpe": self.sharpe,
            "total_trades": self.total_trades,
            "avg_pnl_pct": self.avg_pnl_pct,
            "recommended": self.recommended,
        }


# ---------------------------------------------------------------------------
# MarketplaceEntry — published strategy for sharing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MarketplaceEntry:
    """A strategy published to the marketplace.

    Attributes:
        id: Unique marketplace entry ID.
        strategy_id: The underlying strategy.
        author_id: Publisher user ID.
        name: Display name.
        description: Marketing description.
        performance: Published performance stats.
        subscriber_count: Number of subscribers.
        rating: Average rating (0.0-5.0).
        created_at: Published timestamp.
    """

    id: str
    strategy_id: str
    author_id: str
    name: str
    description: str = ""
    performance: dict = field(default_factory=dict)
    subscriber_count: int = 0
    rating: float = 0.0
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")
        if not self.author_id:
            raise ValueError("author_id must be non-empty")
        if not self.name:
            raise ValueError("name must be non-empty")
        if not (0.0 <= self.rating <= 5.0):
            raise ValueError("rating must be between 0.0 and 5.0")
        if self.subscriber_count < 0:
            raise ValueError("subscriber_count must be >= 0")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "strategy_id": self.strategy_id,
            "author_id": self.author_id,
            "name": self.name,
            "description": self.description,
            "performance": self.performance,
            "subscriber_count": self.subscriber_count,
            "rating": self.rating,
            "created_at": self.created_at,
        }
