"""Frozen dataclasses for Autonomous Trading Agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal

AgentType = Literal["signal_follower", "contrarian", "momentum_rider", "custom_rule"]
AgentStatus = Literal["active", "paused", "stopped", "error"]

AGENT_TYPES = frozenset({"signal_follower", "contrarian", "momentum_rider", "custom_rule"})


@dataclass(frozen=True)
class AgentRule:
    """A single filtering/matching rule for an agent."""

    field: str       # "ticker", "confidence", "stance", "event_type", "sector", "strategy"
    operator: str    # "eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "contains"
    value: Any       # the comparison value

    def matches(self, signal: Dict[str, Any]) -> bool:
        """Evaluate this rule against a signal dict."""
        actual = signal.get(self.field)
        if actual is None:
            return False
        op = self.operator
        if op == "eq":
            return actual == self.value
        if op == "neq":
            return actual != self.value
        if op == "gt":
            return float(actual) > float(self.value)
        if op == "gte":
            return float(actual) >= float(self.value)
        if op == "lt":
            return float(actual) < float(self.value)
        if op == "lte":
            return float(actual) <= float(self.value)
        if op == "in":
            return actual in self.value
        if op == "not_in":
            return actual not in self.value
        if op == "contains":
            return str(self.value).lower() in str(actual).lower()
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the agent rule to a JSON-compatible dictionary."""
        return {"field": self.field, "operator": self.operator, "value": self.value}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentRule":
        """Deserialise an agent rule from a plain dictionary."""
        return cls(field=d["field"], operator=d["operator"], value=d["value"])


@dataclass(frozen=True)
class AgentPerformance:
    """Aggregate performance snapshot for an agent."""

    agent_id: str
    total_trades: int
    winning_trades: int
    total_pnl: float
    sharpe_ratio: float
    max_drawdown_pct: float
    avg_trade_pnl: float
    win_rate: float
    trades_today: int

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the agent performance snapshot to a JSON-compatible dictionary."""
        return {
            "agent_id": self.agent_id,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "total_pnl": round(self.total_pnl, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "avg_trade_pnl": round(self.avg_trade_pnl, 2),
            "win_rate": round(self.win_rate, 3),
            "trades_today": self.trades_today,
        }
