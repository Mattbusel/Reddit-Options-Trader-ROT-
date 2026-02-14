"""Tests for Autonomous Trading Agent types and rule engine."""

import pytest

from rot.agents.types import AGENT_TYPES, AgentPerformance, AgentRule
from rot.agents.rules import RuleEngine


# ============================================================================
# AgentRule creation and basic operations
# ============================================================================


def test_agent_rule_creation_all_fields():
    """Test AgentRule creation with all fields."""
    rule = AgentRule(field="ticker", operator="eq", value="AAPL")
    assert rule.field == "ticker"
    assert rule.operator == "eq"
    assert rule.value == "AAPL"


def test_agent_rule_frozen():
    """Test AgentRule is frozen (immutable)."""
    rule = AgentRule(field="confidence", operator="gte", value=0.5)
    with pytest.raises(Exception):  # FrozenInstanceError
        rule.field = "ticker"


# ============================================================================
# AgentRule.matches() - all operators
# ============================================================================


def test_agent_rule_matches_eq():
    """Test AgentRule.matches() with eq operator."""
    rule = AgentRule(field="ticker", operator="eq", value="TSLA")
    assert rule.matches({"ticker": "TSLA"}) is True
    assert rule.matches({"ticker": "AAPL"}) is False


def test_agent_rule_matches_neq():
    """Test AgentRule.matches() with neq operator."""
    rule = AgentRule(field="stance", operator="neq", value="mixed")
    assert rule.matches({"stance": "bullish"}) is True
    assert rule.matches({"stance": "mixed"}) is False


def test_agent_rule_matches_gt():
    """Test AgentRule.matches() with gt operator."""
    rule = AgentRule(field="confidence", operator="gt", value=0.5)
    assert rule.matches({"confidence": 0.6}) is True
    assert rule.matches({"confidence": 0.5}) is False
    assert rule.matches({"confidence": 0.4}) is False


def test_agent_rule_matches_gte():
    """Test AgentRule.matches() with gte operator."""
    rule = AgentRule(field="confidence", operator="gte", value=0.5)
    assert rule.matches({"confidence": 0.6}) is True
    assert rule.matches({"confidence": 0.5}) is True
    assert rule.matches({"confidence": 0.4}) is False


def test_agent_rule_matches_lt():
    """Test AgentRule.matches() with lt operator."""
    rule = AgentRule(field="quality_score", operator="lt", value=0.7)
    assert rule.matches({"quality_score": 0.6}) is True
    assert rule.matches({"quality_score": 0.7}) is False
    assert rule.matches({"quality_score": 0.8}) is False


def test_agent_rule_matches_lte():
    """Test AgentRule.matches() with lte operator."""
    rule = AgentRule(field="quality_score", operator="lte", value=0.7)
    assert rule.matches({"quality_score": 0.6}) is True
    assert rule.matches({"quality_score": 0.7}) is True
    assert rule.matches({"quality_score": 0.8}) is False


def test_agent_rule_matches_in():
    """Test AgentRule.matches() with in operator."""
    rule = AgentRule(field="event_type", operator="in", value=["earnings_rumor", "product_news"])
    assert rule.matches({"event_type": "earnings_rumor"}) is True
    assert rule.matches({"event_type": "product_news"}) is True
    assert rule.matches({"event_type": "regulatory"}) is False


def test_agent_rule_matches_not_in():
    """Test AgentRule.matches() with not_in operator."""
    rule = AgentRule(field="strategy", operator="not_in", value=["none", "straddle"])
    assert rule.matches({"strategy": "debit_spread"}) is True
    assert rule.matches({"strategy": "none"}) is False
    assert rule.matches({"strategy": "straddle"}) is False


def test_agent_rule_matches_contains():
    """Test AgentRule.matches() with contains operator."""
    rule = AgentRule(field="sector", operator="contains", value="tech")
    assert rule.matches({"sector": "Technology"}) is True
    assert rule.matches({"sector": "TECHNOLOGY"}) is True
    assert rule.matches({"sector": "Healthcare"}) is False


# ============================================================================
# AgentRule.matches() - edge cases
# ============================================================================


def test_agent_rule_matches_missing_field():
    """Test AgentRule.matches() returns False when field is missing."""
    rule = AgentRule(field="ticker", operator="eq", value="AAPL")
    assert rule.matches({"confidence": 0.5}) is False


def test_agent_rule_matches_case_insensitive_contains():
    """Test AgentRule.matches() contains is case-insensitive."""
    rule = AgentRule(field="post_title", operator="contains", value="EARNINGS")
    assert rule.matches({"post_title": "Great earnings coming!"}) is True
    assert rule.matches({"post_title": "EARNINGS BEAT"}) is True
    assert rule.matches({"post_title": "Nothing here"}) is False


def test_agent_rule_matches_numeric_conversion():
    """Test AgentRule.matches() handles numeric operators with string values."""
    rule = AgentRule(field="confidence", operator="gt", value="0.5")
    assert rule.matches({"confidence": 0.6}) is True
    assert rule.matches({"confidence": "0.7"}) is True


# ============================================================================
# AgentRule serialization
# ============================================================================


def test_agent_rule_to_dict():
    """Test AgentRule.to_dict() serialization."""
    rule = AgentRule(field="confidence", operator="gte", value=0.5)
    d = rule.to_dict()
    assert d == {"field": "confidence", "operator": "gte", "value": 0.5}


def test_agent_rule_from_dict():
    """Test AgentRule.from_dict() deserialization."""
    d = {"field": "ticker", "operator": "in", "value": ["AAPL", "TSLA"]}
    rule = AgentRule.from_dict(d)
    assert rule.field == "ticker"
    assert rule.operator == "in"
    assert rule.value == ["AAPL", "TSLA"]


def test_agent_rule_roundtrip():
    """Test AgentRule to_dict/from_dict roundtrip."""
    original = AgentRule(field="stance", operator="eq", value="bullish")
    d = original.to_dict()
    restored = AgentRule.from_dict(d)
    assert restored == original


# ============================================================================
# AgentPerformance
# ============================================================================


def test_agent_performance_creation():
    """Test AgentPerformance creation with all fields."""
    perf = AgentPerformance(
        agent_id="agent-123",
        total_trades=100,
        winning_trades=60,
        total_pnl=1234.56,
        sharpe_ratio=1.5,
        max_drawdown_pct=-15.2,
        avg_trade_pnl=12.35,
        win_rate=0.6,
        trades_today=5,
    )
    assert perf.agent_id == "agent-123"
    assert perf.total_trades == 100
    assert perf.winning_trades == 60
    assert perf.win_rate == 0.6


def test_agent_performance_win_rate_calculation():
    """Test AgentPerformance win_rate can be calculated externally."""
    perf = AgentPerformance(
        agent_id="agent-123",
        total_trades=50,
        winning_trades=30,
        total_pnl=500.0,
        sharpe_ratio=1.2,
        max_drawdown_pct=-10.0,
        avg_trade_pnl=10.0,
        win_rate=30 / 50,  # explicit calculation
        trades_today=3,
    )
    assert perf.win_rate == 0.6


def test_agent_performance_to_dict():
    """Test AgentPerformance.to_dict() with rounding."""
    perf = AgentPerformance(
        agent_id="agent-123",
        total_trades=100,
        winning_trades=55,
        total_pnl=1234.5678,
        sharpe_ratio=1.5555,
        max_drawdown_pct=-15.2222,
        avg_trade_pnl=12.3456,
        win_rate=0.555555,
        trades_today=5,
    )
    d = perf.to_dict()
    assert d["total_pnl"] == 1234.57  # 2 decimals
    assert d["sharpe_ratio"] == 1.556  # 3 decimals
    assert d["max_drawdown_pct"] == -15.22  # 2 decimals
    assert d["avg_trade_pnl"] == 12.35  # 2 decimals
    assert d["win_rate"] == 0.556  # 3 decimals


# ============================================================================
# AGENT_TYPES
# ============================================================================


def test_agent_types_frozenset():
    """Test AGENT_TYPES contains all expected types."""
    assert AGENT_TYPES == frozenset({"signal_follower", "contrarian", "momentum_rider", "custom_rule"})
    assert "signal_follower" in AGENT_TYPES
    assert "contrarian" in AGENT_TYPES
    assert "momentum_rider" in AGENT_TYPES
    assert "custom_rule" in AGENT_TYPES
    assert "unknown_type" not in AGENT_TYPES


# ============================================================================
# RuleEngine.evaluate_all() - AND logic
# ============================================================================


def test_rule_engine_evaluate_all_empty_rules():
    """Test RuleEngine.evaluate_all() with empty rules matches all signals."""
    signal = {"ticker": "AAPL", "confidence": 0.5}
    assert RuleEngine.evaluate_all([], signal) is True


def test_rule_engine_evaluate_all_single_match():
    """Test RuleEngine.evaluate_all() with single matching rule."""
    rules = [AgentRule(field="ticker", operator="eq", value="AAPL")]
    signal = {"ticker": "AAPL"}
    assert RuleEngine.evaluate_all(rules, signal) is True


def test_rule_engine_evaluate_all_single_no_match():
    """Test RuleEngine.evaluate_all() with single non-matching rule."""
    rules = [AgentRule(field="ticker", operator="eq", value="AAPL")]
    signal = {"ticker": "TSLA"}
    assert RuleEngine.evaluate_all(rules, signal) is False


def test_rule_engine_evaluate_all_multiple_all_match():
    """Test RuleEngine.evaluate_all() with multiple matching rules (AND)."""
    rules = [
        AgentRule(field="ticker", operator="eq", value="AAPL"),
        AgentRule(field="confidence", operator="gte", value=0.5),
        AgentRule(field="stance", operator="eq", value="bullish"),
    ]
    signal = {"ticker": "AAPL", "confidence": 0.6, "stance": "bullish"}
    assert RuleEngine.evaluate_all(rules, signal) is True


def test_rule_engine_evaluate_all_multiple_one_fails():
    """Test RuleEngine.evaluate_all() fails if one rule fails (AND)."""
    rules = [
        AgentRule(field="ticker", operator="eq", value="AAPL"),
        AgentRule(field="confidence", operator="gte", value=0.5),
        AgentRule(field="stance", operator="eq", value="bullish"),
    ]
    signal = {"ticker": "AAPL", "confidence": 0.4, "stance": "bullish"}  # confidence too low
    assert RuleEngine.evaluate_all(rules, signal) is False


# ============================================================================
# RuleEngine.evaluate_any() - OR logic
# ============================================================================


def test_rule_engine_evaluate_any_empty_rules():
    """Test RuleEngine.evaluate_any() with empty rules matches all signals."""
    signal = {"ticker": "AAPL", "confidence": 0.5}
    assert RuleEngine.evaluate_any([], signal) is True


def test_rule_engine_evaluate_any_single_match():
    """Test RuleEngine.evaluate_any() with single matching rule."""
    rules = [AgentRule(field="ticker", operator="eq", value="AAPL")]
    signal = {"ticker": "AAPL"}
    assert RuleEngine.evaluate_any(rules, signal) is True


def test_rule_engine_evaluate_any_multiple_one_matches():
    """Test RuleEngine.evaluate_any() succeeds if one rule matches (OR)."""
    rules = [
        AgentRule(field="ticker", operator="eq", value="AAPL"),
        AgentRule(field="confidence", operator="gte", value=0.5),
        AgentRule(field="stance", operator="eq", value="bullish"),
    ]
    signal = {"ticker": "TSLA", "confidence": 0.6, "stance": "bearish"}  # only confidence matches
    assert RuleEngine.evaluate_any(rules, signal) is True


def test_rule_engine_evaluate_any_none_match():
    """Test RuleEngine.evaluate_any() fails if no rules match."""
    rules = [
        AgentRule(field="ticker", operator="eq", value="AAPL"),
        AgentRule(field="confidence", operator="gte", value=0.8),
    ]
    signal = {"ticker": "TSLA", "confidence": 0.5}
    assert RuleEngine.evaluate_any(rules, signal) is False


# ============================================================================
# RuleEngine.evaluate_custom() - configurable logic
# ============================================================================


def test_rule_engine_evaluate_custom_and_logic():
    """Test RuleEngine.evaluate_custom() with logic='and'."""
    rules = [
        AgentRule(field="ticker", operator="eq", value="AAPL"),
        AgentRule(field="confidence", operator="gte", value=0.5),
    ]
    signal = {"ticker": "AAPL", "confidence": 0.6}
    assert RuleEngine.evaluate_custom(rules, signal, logic="and") is True
    signal = {"ticker": "AAPL", "confidence": 0.4}
    assert RuleEngine.evaluate_custom(rules, signal, logic="and") is False


def test_rule_engine_evaluate_custom_or_logic():
    """Test RuleEngine.evaluate_custom() with logic='or'."""
    rules = [
        AgentRule(field="ticker", operator="eq", value="AAPL"),
        AgentRule(field="confidence", operator="gte", value=0.8),
    ]
    signal = {"ticker": "AAPL", "confidence": 0.5}  # only ticker matches
    assert RuleEngine.evaluate_custom(rules, signal, logic="or") is True
    signal = {"ticker": "TSLA", "confidence": 0.5}  # neither matches
    assert RuleEngine.evaluate_custom(rules, signal, logic="or") is False


# ============================================================================
# RuleEngine.apply_agent_type_logic() - agent transformations
# ============================================================================


def test_rule_engine_apply_signal_follower_passthrough():
    """Test signal_follower agent type passes signal unchanged."""
    signal = {"ticker": "AAPL", "stance": "bullish", "confidence": 0.6}
    result = RuleEngine.apply_agent_type_logic("signal_follower", signal)
    assert result == signal


def test_rule_engine_apply_contrarian_flips_bullish():
    """Test contrarian agent flips bullish -> bearish."""
    signal = {"ticker": "AAPL", "stance": "bullish", "confidence": 0.6}
    result = RuleEngine.apply_agent_type_logic("contrarian", signal)
    assert result["stance"] == "bearish"
    assert result["ticker"] == "AAPL"  # other fields unchanged


def test_rule_engine_apply_contrarian_flips_bearish():
    """Test contrarian agent flips bearish -> bullish."""
    signal = {"ticker": "AAPL", "stance": "bearish", "confidence": 0.6}
    result = RuleEngine.apply_agent_type_logic("contrarian", signal)
    assert result["stance"] == "bullish"


def test_rule_engine_apply_contrarian_unknown_unchanged():
    """Test contrarian agent leaves unknown stance unchanged."""
    signal = {"ticker": "AAPL", "stance": "unknown", "confidence": 0.6}
    result = RuleEngine.apply_agent_type_logic("contrarian", signal)
    assert result["stance"] == "unknown"


def test_rule_engine_apply_contrarian_mixed_unchanged():
    """Test contrarian agent leaves mixed stance unchanged."""
    signal = {"ticker": "AAPL", "stance": "mixed", "confidence": 0.6}
    result = RuleEngine.apply_agent_type_logic("contrarian", signal)
    assert result["stance"] == "mixed"


def test_rule_engine_apply_momentum_rider_passthrough():
    """Test momentum_rider agent type passes signal unchanged."""
    signal = {"ticker": "AAPL", "stance": "bullish", "confidence": 0.6}
    result = RuleEngine.apply_agent_type_logic("momentum_rider", signal)
    assert result == signal


def test_rule_engine_apply_custom_rule_passthrough():
    """Test custom_rule agent type passes signal unchanged."""
    signal = {"ticker": "AAPL", "stance": "bullish", "confidence": 0.6}
    result = RuleEngine.apply_agent_type_logic("custom_rule", signal)
    assert result == signal


# ============================================================================
# RuleEngine.check_confidence_gate()
# ============================================================================


def test_rule_engine_confidence_gate_pass():
    """Test check_confidence_gate() passes when confidence >= threshold."""
    signal = {"confidence": 0.6}
    assert RuleEngine.check_confidence_gate(signal, 0.5) is True
    assert RuleEngine.check_confidence_gate(signal, 0.6) is True


def test_rule_engine_confidence_gate_fail():
    """Test check_confidence_gate() fails when confidence < threshold."""
    signal = {"confidence": 0.4}
    assert RuleEngine.check_confidence_gate(signal, 0.5) is False


def test_rule_engine_confidence_gate_missing():
    """Test check_confidence_gate() fails when confidence is missing."""
    signal = {"ticker": "AAPL"}
    assert RuleEngine.check_confidence_gate(signal, 0.5) is False


def test_rule_engine_confidence_gate_invalid_type():
    """Test check_confidence_gate() fails gracefully on invalid confidence type."""
    signal = {"confidence": "not_a_number"}
    assert RuleEngine.check_confidence_gate(signal, 0.5) is False


# ============================================================================
# RuleEngine.check_stance_tradeable()
# ============================================================================


def test_rule_engine_stance_tradeable_bullish():
    """Test check_stance_tradeable() returns True for bullish."""
    signal = {"stance": "bullish"}
    assert RuleEngine.check_stance_tradeable(signal) is True


def test_rule_engine_stance_tradeable_bearish():
    """Test check_stance_tradeable() returns True for bearish."""
    signal = {"stance": "bearish"}
    assert RuleEngine.check_stance_tradeable(signal) is True


def test_rule_engine_stance_tradeable_mixed():
    """Test check_stance_tradeable() returns False for mixed."""
    signal = {"stance": "mixed"}
    assert RuleEngine.check_stance_tradeable(signal) is False


def test_rule_engine_stance_tradeable_unknown():
    """Test check_stance_tradeable() returns False for unknown."""
    signal = {"stance": "unknown"}
    assert RuleEngine.check_stance_tradeable(signal) is False


def test_rule_engine_stance_tradeable_missing():
    """Test check_stance_tradeable() returns False when stance is missing."""
    signal = {"ticker": "AAPL"}
    assert RuleEngine.check_stance_tradeable(signal) is False
