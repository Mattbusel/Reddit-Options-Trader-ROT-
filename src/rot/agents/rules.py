"""Rule evaluation engine for Autonomous Trading Agents."""

from __future__ import annotations

from typing import Any, Dict, List

from rot.agents.types import AgentRule


class RuleEngine:
    """Evaluates agent rules against signals."""

    @staticmethod
    def evaluate_all(rules: List[AgentRule], signal: Dict[str, Any]) -> bool:
        """Check if a signal matches ALL rules (AND logic). Empty rules = match all."""
        if not rules:
            return True
        return all(r.matches(signal) for r in rules)

    @staticmethod
    def evaluate_any(rules: List[AgentRule], signal: Dict[str, Any]) -> bool:
        """Check if a signal matches ANY rule (OR logic). Empty rules = match all."""
        if not rules:
            return True
        return any(r.matches(signal) for r in rules)

    @staticmethod
    def evaluate_custom(
        rules: List[AgentRule],
        signal: Dict[str, Any],
        logic: str = "and",
    ) -> bool:
        """Evaluate rules with configurable AND/OR logic."""
        if logic == "or":
            return RuleEngine.evaluate_any(rules, signal)
        return RuleEngine.evaluate_all(rules, signal)

    @staticmethod
    def apply_agent_type_logic(
        agent_type: str,
        signal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Apply agent-type-specific transformations to a signal before trade execution.

        - signal_follower: pass-through (no changes)
        - contrarian: flip stance (bullish -> bearish, bearish -> bullish)
        - momentum_rider: pass-through (filtering happens in evaluate)
        - custom_rule: pass-through (logic handled by rule evaluation)
        """
        if agent_type == "contrarian":
            modified = dict(signal)
            stance = signal.get("stance", "unknown")
            if stance == "bullish":
                modified["stance"] = "bearish"
            elif stance == "bearish":
                modified["stance"] = "bullish"
            return modified
        # All other types: pass-through
        return signal

    @staticmethod
    def check_confidence_gate(signal: Dict[str, Any], min_confidence: float) -> bool:
        """Check if signal meets minimum confidence threshold."""
        conf = signal.get("confidence", 0)
        try:
            return float(conf) >= min_confidence
        except (TypeError, ValueError):
            return False

    @staticmethod
    def check_stance_tradeable(signal: Dict[str, Any]) -> bool:
        """Only bullish/bearish signals are tradeable (matches DB win/loss logic)."""
        return signal.get("stance") in ("bullish", "bearish")
