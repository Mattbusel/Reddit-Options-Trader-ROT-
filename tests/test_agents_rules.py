"""
Comprehensive tests for agent rules module.

Modules tested:
- rot.agents.rules

Coverage:
- RuleEngine.evaluate_all (AND logic)
- RuleEngine.evaluate_any (OR logic)
- RuleEngine.evaluate_custom (configurable logic)
- RuleEngine.apply_agent_type_logic (contrarian stance flipping)
- RuleEngine.check_confidence_gate (minimum confidence check)
- RuleEngine.check_stance_tradeable (stance validation)
- AgentRule operators: eq, neq, gt, gte, lt, lte, in, not_in, contains
"""
from __future__ import annotations

from rot.agents.rules import RuleEngine
from rot.agents.types import AgentRule


class TestEvaluateAll:
    def test_evaluate_all_empty_rules(self):
        """evaluate_all with no rules returns True."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        result = RuleEngine.evaluate_all([], signal)
        assert result is True

    def test_evaluate_all_single_rule_pass(self):
        """evaluate_all with one passing rule returns True."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        rules = [AgentRule(field="ticker", operator="eq", value="AAPL")]

        result = RuleEngine.evaluate_all(rules, signal)
        assert result is True

    def test_evaluate_all_single_rule_fail(self):
        """evaluate_all with one failing rule returns False."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        rules = [AgentRule(field="ticker", operator="eq", value="MSFT")]

        result = RuleEngine.evaluate_all(rules, signal)
        assert result is False

    def test_evaluate_all_multiple_rules_all_pass(self):
        """evaluate_all with multiple passing rules returns True."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        rules = [
            AgentRule(field="ticker", operator="eq", value="AAPL"),
            AgentRule(field="stance", operator="eq", value="bullish"),
            AgentRule(field="confidence", operator="gt", value=0.5),
        ]

        result = RuleEngine.evaluate_all(rules, signal)
        assert result is True

    def test_evaluate_all_multiple_rules_one_fails(self):
        """evaluate_all with one failing rule returns False (AND logic)."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        rules = [
            AgentRule(field="ticker", operator="eq", value="AAPL"),
            AgentRule(field="stance", operator="eq", value="bearish"),  # Fails
        ]

        result = RuleEngine.evaluate_all(rules, signal)
        assert result is False


class TestEvaluateAny:
    def test_evaluate_any_empty_rules(self):
        """evaluate_any with no rules returns True."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        result = RuleEngine.evaluate_any([], signal)
        assert result is True

    def test_evaluate_any_single_rule_pass(self):
        """evaluate_any with one passing rule returns True."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        rules = [AgentRule(field="ticker", operator="eq", value="AAPL")]

        result = RuleEngine.evaluate_any(rules, signal)
        assert result is True

    def test_evaluate_any_single_rule_fail(self):
        """evaluate_any with one failing rule returns False."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        rules = [AgentRule(field="ticker", operator="eq", value="MSFT")]

        result = RuleEngine.evaluate_any(rules, signal)
        assert result is False

    def test_evaluate_any_multiple_rules_one_passes(self):
        """evaluate_any with one passing rule returns True (OR logic)."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        rules = [
            AgentRule(field="ticker", operator="eq", value="MSFT"),  # Fails
            AgentRule(field="stance", operator="eq", value="bullish"),  # Passes
        ]

        result = RuleEngine.evaluate_any(rules, signal)
        assert result is True

    def test_evaluate_any_multiple_rules_all_fail(self):
        """evaluate_any with all failing rules returns False."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        rules = [
            AgentRule(field="ticker", operator="eq", value="MSFT"),
            AgentRule(field="stance", operator="eq", value="bearish"),
        ]

        result = RuleEngine.evaluate_any(rules, signal)
        assert result is False


class TestEvaluateCustom:
    def test_evaluate_custom_and_logic(self):
        """evaluate_custom with logic='and' behaves like evaluate_all."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        rules = [
            AgentRule(field="ticker", operator="eq", value="AAPL"),
            AgentRule(field="stance", operator="eq", value="bullish"),
        ]

        result = RuleEngine.evaluate_custom(rules, signal, logic="and")
        assert result is True

    def test_evaluate_custom_or_logic(self):
        """evaluate_custom with logic='or' behaves like evaluate_any."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        rules = [
            AgentRule(field="ticker", operator="eq", value="MSFT"),  # Fails
            AgentRule(field="stance", operator="eq", value="bullish"),  # Passes
        ]

        result = RuleEngine.evaluate_custom(rules, signal, logic="or")
        assert result is True

    def test_evaluate_custom_invalid_logic_defaults_to_and(self):
        """evaluate_custom with invalid logic defaults to AND."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        rules = [
            AgentRule(field="ticker", operator="eq", value="AAPL"),
            AgentRule(field="stance", operator="eq", value="bearish"),  # Fails
        ]

        # Invalid logic defaults to AND, so one fail = False
        result = RuleEngine.evaluate_custom(rules, signal, logic="INVALID")
        assert result is False


class TestOperators:
    def test_eq_operator(self):
        """eq operator matches exact string."""
        signal = {"ticker": "AAPL"}

        rule = AgentRule(field="ticker", operator="eq", value="AAPL")
        assert rule.matches(signal) is True

        rule = AgentRule(field="ticker", operator="eq", value="MSFT")
        assert rule.matches(signal) is False

    def test_neq_operator(self):
        """neq operator rejects exact match."""
        signal = {"ticker": "AAPL"}

        rule = AgentRule(field="ticker", operator="neq", value="MSFT")
        assert rule.matches(signal) is True

        rule = AgentRule(field="ticker", operator="neq", value="AAPL")
        assert rule.matches(signal) is False

    def test_gt_operator(self):
        """gt operator compares numbers."""
        signal = {"confidence": 0.8}

        rule = AgentRule(field="confidence", operator="gt", value=0.5)
        assert rule.matches(signal) is True

        rule = AgentRule(field="confidence", operator="gt", value=0.9)
        assert rule.matches(signal) is False

    def test_gte_operator(self):
        """gte operator compares numbers with equality."""
        signal = {"confidence": 0.8}

        rule = AgentRule(field="confidence", operator="gte", value=0.8)
        assert rule.matches(signal) is True

        rule = AgentRule(field="confidence", operator="gte", value=0.9)
        assert rule.matches(signal) is False

    def test_lt_operator(self):
        """lt operator compares numbers."""
        signal = {"confidence": 0.8}

        rule = AgentRule(field="confidence", operator="lt", value=0.9)
        assert rule.matches(signal) is True

        rule = AgentRule(field="confidence", operator="lt", value=0.5)
        assert rule.matches(signal) is False

    def test_lte_operator(self):
        """lte operator compares numbers with equality."""
        signal = {"confidence": 0.8}

        rule = AgentRule(field="confidence", operator="lte", value=0.8)
        assert rule.matches(signal) is True

        rule = AgentRule(field="confidence", operator="lte", value=0.5)
        assert rule.matches(signal) is False

    def test_contains_operator(self):
        """contains operator checks substring presence (case-insensitive)."""
        signal = {"title": "Apple is great"}

        rule = AgentRule(field="title", operator="contains", value="Apple")
        assert rule.matches(signal) is True

        rule = AgentRule(field="title", operator="contains", value="Tesla")
        assert rule.matches(signal) is False

    def test_in_operator(self):
        """in operator checks membership."""
        signal = {"ticker": "AAPL"}

        rule = AgentRule(field="ticker", operator="in", value=["AAPL", "MSFT", "TSLA"])
        assert rule.matches(signal) is True

        rule = AgentRule(field="ticker", operator="in", value=["MSFT", "TSLA"])
        assert rule.matches(signal) is False

    def test_not_in_operator(self):
        """not_in operator rejects membership."""
        signal = {"ticker": "AAPL"}

        rule = AgentRule(field="ticker", operator="not_in", value=["MSFT", "TSLA"])
        assert rule.matches(signal) is True

        rule = AgentRule(field="ticker", operator="not_in", value=["AAPL", "MSFT"])
        assert rule.matches(signal) is False

    def test_unknown_operator_returns_false(self):
        """Unknown operators return False."""
        signal = {"ticker": "AAPL"}

        rule = AgentRule(field="ticker", operator="unknown_operator", value="AAPL")
        assert rule.matches(signal) is False

    def test_missing_field_returns_false(self):
        """Missing field returns False for all operators."""
        signal = {"ticker": "AAPL"}

        rule = AgentRule(field="nonexistent_field", operator="eq", value="test")
        assert rule.matches(signal) is False


class TestApplyAgentTypeLogic:
    def test_apply_agent_type_logic_contrarian_flips_bullish(self):
        """Contrarian agent flips bullish to bearish."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        result = RuleEngine.apply_agent_type_logic("contrarian", signal)
        assert result["stance"] == "bearish"
        assert result["ticker"] == "AAPL"  # Other fields preserved
        assert result["confidence"] == 0.8

    def test_apply_agent_type_logic_contrarian_flips_bearish(self):
        """Contrarian agent flips bearish to bullish."""
        signal = {
            "ticker": "AAPL",
            "stance": "bearish",
            "confidence": 0.8,
        }

        result = RuleEngine.apply_agent_type_logic("contrarian", signal)
        assert result["stance"] == "bullish"

    def test_apply_agent_type_logic_contrarian_preserves_mixed(self):
        """Contrarian agent preserves mixed stance."""
        signal = {
            "ticker": "AAPL",
            "stance": "mixed",
            "confidence": 0.8,
        }

        result = RuleEngine.apply_agent_type_logic("contrarian", signal)
        assert result["stance"] == "mixed"

    def test_apply_agent_type_logic_contrarian_preserves_unknown(self):
        """Contrarian agent preserves unknown stance."""
        signal = {
            "ticker": "AAPL",
            "stance": "unknown",
            "confidence": 0.8,
        }

        result = RuleEngine.apply_agent_type_logic("contrarian", signal)
        assert result["stance"] == "unknown"

    def test_apply_agent_type_logic_non_contrarian_unchanged(self):
        """Non-contrarian agent preserves stance."""
        signal = {
            "ticker": "AAPL",
            "stance": "bullish",
            "confidence": 0.8,
        }

        # Test all non-contrarian types
        for agent_type in ["signal_follower", "momentum_rider", "custom_rule"]:
            result = RuleEngine.apply_agent_type_logic(agent_type, signal)
            assert result["stance"] == "bullish"


class TestCheckConfidenceGate:
    def test_check_confidence_gate_above_threshold(self):
        """Signal above confidence gate passes."""
        signal = {"confidence": 0.8}

        result = RuleEngine.check_confidence_gate(signal, min_confidence=0.5)
        assert result is True

    def test_check_confidence_gate_below_threshold(self):
        """Signal below confidence gate fails."""
        signal = {"confidence": 0.3}

        result = RuleEngine.check_confidence_gate(signal, min_confidence=0.5)
        assert result is False

    def test_check_confidence_gate_exact_threshold(self):
        """Signal at exact confidence threshold passes."""
        signal = {"confidence": 0.5}

        result = RuleEngine.check_confidence_gate(signal, min_confidence=0.5)
        assert result is True

    def test_check_confidence_gate_missing_field(self):
        """Signal without confidence field fails."""
        signal = {"ticker": "AAPL"}

        result = RuleEngine.check_confidence_gate(signal, min_confidence=0.5)
        assert result is False

    def test_check_confidence_gate_invalid_type(self):
        """Signal with non-numeric confidence fails."""
        signal = {"confidence": "high"}

        result = RuleEngine.check_confidence_gate(signal, min_confidence=0.5)
        assert result is False


class TestCheckStanceTradeable:
    def test_check_stance_tradeable_bullish(self):
        """Bullish stance is tradeable."""
        signal = {"stance": "bullish"}

        result = RuleEngine.check_stance_tradeable(signal)
        assert result is True

    def test_check_stance_tradeable_bearish(self):
        """Bearish stance is tradeable."""
        signal = {"stance": "bearish"}

        result = RuleEngine.check_stance_tradeable(signal)
        assert result is True

    def test_check_stance_tradeable_mixed(self):
        """Mixed stance is not tradeable."""
        signal = {"stance": "mixed"}

        result = RuleEngine.check_stance_tradeable(signal)
        assert result is False

    def test_check_stance_tradeable_unknown(self):
        """Unknown stance is not tradeable."""
        signal = {"stance": "unknown"}

        result = RuleEngine.check_stance_tradeable(signal)
        assert result is False

    def test_check_stance_tradeable_missing_field(self):
        """Missing stance field is not tradeable."""
        signal = {"ticker": "AAPL"}

        result = RuleEngine.check_stance_tradeable(signal)
        assert result is False
