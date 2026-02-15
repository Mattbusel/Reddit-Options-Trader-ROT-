"""Backtest configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional


PositionSizeMode = Literal["fixed_pct", "kelly", "confidence_weighted"]


@dataclass(frozen=True)
class BacktestConfig:
    """Immutable configuration for a single backtest run.

    All filter fields use ``None`` to mean "no filter".
    """

    # ── Portfolio ──
    starting_capital: float = 10_000.0
    position_size_mode: PositionSizeMode = "fixed_pct"
    position_size_pct: float = 5.0  # % of equity per trade (for fixed_pct)
    max_concurrent_positions: int = 5

    # ── Exit rules ──
    stop_loss_pct: float = 0.0   # 0 = disabled
    take_profit_pct: float = 0.0  # 0 = disabled

    # ── Signal filters ──
    min_confidence: float = 0.0
    strategy_filter: Optional[str] = None
    event_type_filter: Optional[str] = None
    stance_filter: Optional[str] = None
    ticker_filter: Optional[str] = None
    days: int = 90

    # ── Price column preference ──
    use_1d_price: bool = True  # True→prefer price_1d, False→prefer price_4h

    def validate(self) -> List[str]:
        """Return a list of validation error strings (empty = valid)."""
        errors: List[str] = []
        if self.starting_capital <= 0:
            errors.append("starting_capital must be > 0")
        if not (0.1 <= self.position_size_pct <= 100):
            errors.append("position_size_pct must be between 0.1 and 100")
        if self.max_concurrent_positions < 1:
            errors.append("max_concurrent_positions must be >= 1")
        if self.stop_loss_pct < 0 or self.stop_loss_pct > 50:
            errors.append("stop_loss_pct must be between 0 and 50")
        if self.take_profit_pct < 0 or self.take_profit_pct > 500:
            errors.append("take_profit_pct must be between 0 and 500")
        if not (0.0 <= self.min_confidence <= 1.0):
            errors.append("min_confidence must be between 0.0 and 1.0")
        if self.days < 1:
            errors.append("days must be >= 1")
        if self.position_size_mode not in ("fixed_pct", "kelly", "confidence_weighted"):
            errors.append("position_size_mode must be fixed_pct, kelly, or confidence_weighted")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict (JSON-safe)."""
        return {
            "starting_capital": self.starting_capital,
            "position_size_mode": self.position_size_mode,
            "position_size_pct": self.position_size_pct,
            "max_concurrent_positions": self.max_concurrent_positions,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "min_confidence": self.min_confidence,
            "strategy_filter": self.strategy_filter,
            "event_type_filter": self.event_type_filter,
            "stance_filter": self.stance_filter,
            "ticker_filter": self.ticker_filter,
            "days": self.days,
            "use_1d_price": self.use_1d_price,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BacktestConfig":
        """Create from a plain dict (e.g. loaded from JSON)."""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known_fields}
        return cls(**filtered)
