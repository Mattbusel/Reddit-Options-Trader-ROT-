"""Tests for rot.agents — types, rules, and engine.

Covers AgentRule (all 9 operators), AgentPerformance, RuleEngine (AND/OR/custom logic,
confidence gate, stance check, agent type transformations, contrarian flip),
AgentEngine (flatten, safety rails, performance, Sharpe, max drawdown, signal evaluation).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from rot.agents.types import AGENT_TYPES, AgentPerformance, AgentRule
from rot.agents.rules import RuleEngine
from rot.agents.engine import AgentEngine


# ═══════════════════════════════════════════════════════════════════════════
# Part 1: AgentRule
# ═══════════════════════════════════════════════════════════════════════════


class TestAgentRuleBasic:
    def test_creation(self):
        r = AgentRule(field="ticker", operator="eq", value="AAPL")
        assert r.field == "ticker"
        assert r.operator == "eq"
        assert r.value == "AAPL"

    def test_to_dict(self):
        r = AgentRule(field="confidence", operator="gte", value=0.5)
        d = r.to_dict()
        assert d == {"field": "confidence", "operator": "gte", "value": 0.5}

    def test_from_dict(self):
        r = AgentRule.from_dict({"field": "x", "operator": "gt", "value": 10})
        assert r.field == "x"
        assert r.operator == "gt"
        assert r.value == 10

    def test_roundtrip(self):
        r = AgentRule(field="stance", operator="eq", value="bullish")
        r2 = AgentRule.from_dict(r.to_dict())
        assert r == r2

    def test_frozen(self):
        r = AgentRule(field="x", operator="eq", value=1)
        with pytest.raises(AttributeError):
            r.value = 2  # type: ignore[misc]


class TestAgentRuleMatches:
    def test_eq_match(self):
        r = AgentRule(field="ticker", operator="eq", value="AAPL")
        assert r.matches({"ticker": "AAPL"}) is True
        assert r.matches({"ticker": "TSLA"}) is False

    def test_neq_match(self):
        r = AgentRule(field="stance", operator="neq", value="bearish")
        assert r.matches({"stance": "bullish"}) is True
        assert r.matches({"stance": "bearish"}) is False

    def test_gt_match(self):
        r = AgentRule(field="confidence", operator="gt", value=0.5)
        assert r.matches({"confidence": 0.7}) is True
        assert r.matches({"confidence": 0.5}) is False
        assert r.matches({"confidence": 0.3}) is False

    def test_gte_match(self):
        r = AgentRule(field="confidence", operator="gte", value=0.5)
        assert r.matches({"confidence": 0.5}) is True
        assert r.matches({"confidence": 0.7}) is True
        assert r.matches({"confidence": 0.3}) is False

    def test_lt_match(self):
        r = AgentRule(field="price", operator="lt", value=100)
        assert r.matches({"price": 50}) is True
        assert r.matches({"price": 100}) is False
        assert r.matches({"price": 150}) is False

    def test_lte_match(self):
        r = AgentRule(field="price", operator="lte", value=100)
        assert r.matches({"price": 100}) is True
        assert r.matches({"price": 50}) is True
        assert r.matches({"price": 150}) is False

    def test_in_match(self):
        r = AgentRule(field="event_type", operator="in", value=["earnings_rumor", "macro"])
        assert r.matches({"event_type": "earnings_rumor"}) is True
        assert r.matches({"event_type": "other"}) is False

    def test_not_in_match(self):
        r = AgentRule(field="sector", operator="not_in", value=["energy", "utilities"])
        assert r.matches({"sector": "tech"}) is True
        assert r.matches({"sector": "energy"}) is False

    def test_contains_match(self):
        r = AgentRule(field="ticker", operator="contains", value="SPY")
        assert r.matches({"ticker": "SPY"}) is True
        assert r.matches({"ticker": "SPYG"}) is True
        assert r.matches({"ticker": "AAPL"}) is False

    def test_contains_case_insensitive(self):
        r = AgentRule(field="ticker", operator="contains", value="aapl")
        assert r.matches({"ticker": "AAPL"}) is True

    def test_missing_field_returns_false(self):
        r = AgentRule(field="nonexistent", operator="eq", value="x")
        assert r.matches({"other": "y"}) is False

    def test_none_field_value_returns_false(self):
        r = AgentRule(field="ticker", operator="eq", value="AAPL")
        assert r.matches({"ticker": None}) is False

    def test_unknown_operator_returns_false(self):
        r = AgentRule(field="x", operator="unknown_op", value=1)
        assert r.matches({"x": 1}) is False

    @pytest.mark.parametrize("op,val,target,expected", [
        ("eq", "AAPL", "AAPL", True),
        ("eq", "TSLA", "AAPL", False),
        ("neq", "TSLA", "AAPL", True),
        ("gt", 10, 5, True),
        ("gte", 5, 5, True),
        ("lt", 3, 5, True),
        ("lte", 5, 5, True),
        ("in", "a", ["a", "b"], True),
        ("not_in", "c", ["a", "b"], True),
        ("contains", "hello world", "hello", True),
    ])
    def test_parametrized_operators(self, op, val, target, expected):
        r = AgentRule(field="x", operator=op, value=target)
        assert r.matches({"x": val}) is expected


# ═══════════════════════════════════════════════════════════════════════════
# Part 2: AgentPerformance
# ═══════════════════════════════════════════════════════════════════════════


class TestAgentPerformance:
    def test_creation(self):
        p = AgentPerformance(
            agent_id="a1", total_trades=10, winning_trades=7,
            total_pnl=500.0, sharpe_ratio=1.5, max_drawdown_pct=8.0,
            avg_trade_pnl=50.0, win_rate=0.7, trades_today=2,
        )
        assert p.agent_id == "a1"
        assert p.win_rate == 0.7

    def test_to_dict(self):
        p = AgentPerformance(
            agent_id="a1", total_trades=0, winning_trades=0,
            total_pnl=0.0, sharpe_ratio=0.0, max_drawdown_pct=0.0,
            avg_trade_pnl=0.0, win_rate=0.0, trades_today=0,
        )
        d = p.to_dict()
        assert d["agent_id"] == "a1"
        assert d["total_pnl"] == 0.0
        # Check rounding
        assert d["sharpe_ratio"] == 0.0

    def test_to_dict_rounds_values(self):
        p = AgentPerformance(
            agent_id="a1", total_trades=10, winning_trades=7,
            total_pnl=123.456789, sharpe_ratio=1.23456,
            max_drawdown_pct=5.6789, avg_trade_pnl=12.3456,
            win_rate=0.71234, trades_today=3,
        )
        d = p.to_dict()
        assert d["total_pnl"] == 123.46
        assert d["sharpe_ratio"] == 1.235
        assert d["max_drawdown_pct"] == 5.68
        assert d["avg_trade_pnl"] == 12.35
        assert d["win_rate"] == 0.712

    def test_frozen(self):
        p = AgentPerformance(
            agent_id="a1", total_trades=0, winning_trades=0,
            total_pnl=0.0, sharpe_ratio=0.0, max_drawdown_pct=0.0,
            avg_trade_pnl=0.0, win_rate=0.0, trades_today=0,
        )
        with pytest.raises(AttributeError):
            p.total_trades = 5  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════
# Part 3: RuleEngine (agents)
# ═══════════════════════════════════════════════════════════════════════════


class TestRuleEngineEvaluateAll:
    def test_empty_rules_matches(self):
        assert RuleEngine.evaluate_all([], {"x": 1}) is True

    def test_single_matching_rule(self):
        rules = [AgentRule(field="stance", operator="eq", value="bullish")]
        assert RuleEngine.evaluate_all(rules, {"stance": "bullish"}) is True

    def test_single_failing_rule(self):
        rules = [AgentRule(field="stance", operator="eq", value="bullish")]
        assert RuleEngine.evaluate_all(rules, {"stance": "bearish"}) is False

    def test_all_must_match(self):
        rules = [
            AgentRule(field="stance", operator="eq", value="bullish"),
            AgentRule(field="confidence", operator="gte", value=0.5),
        ]
        assert RuleEngine.evaluate_all(rules, {"stance": "bullish", "confidence": 0.7}) is True
        assert RuleEngine.evaluate_all(rules, {"stance": "bullish", "confidence": 0.3}) is False


class TestRuleEngineEvaluateAny:
    def test_empty_rules_matches(self):
        assert RuleEngine.evaluate_any([], {"x": 1}) is True

    def test_single_matching_rule(self):
        rules = [AgentRule(field="stance", operator="eq", value="bullish")]
        assert RuleEngine.evaluate_any(rules, {"stance": "bullish"}) is True

    def test_any_can_match(self):
        rules = [
            AgentRule(field="stance", operator="eq", value="bullish"),
            AgentRule(field="confidence", operator="gte", value=0.9),
        ]
        assert RuleEngine.evaluate_any(rules, {"stance": "bullish", "confidence": 0.3}) is True

    def test_none_match(self):
        rules = [
            AgentRule(field="stance", operator="eq", value="bullish"),
            AgentRule(field="confidence", operator="gte", value=0.9),
        ]
        assert RuleEngine.evaluate_any(rules, {"stance": "bearish", "confidence": 0.3}) is False


class TestRuleEngineCustom:
    def test_and_logic(self):
        rules = [
            AgentRule(field="confidence", operator="gte", value=0.5),
            AgentRule(field="stance", operator="eq", value="bullish"),
        ]
        assert RuleEngine.evaluate_custom(rules, {"confidence": 0.7, "stance": "bullish"}, "and") is True
        assert RuleEngine.evaluate_custom(rules, {"confidence": 0.3, "stance": "bullish"}, "and") is False

    def test_or_logic(self):
        rules = [
            AgentRule(field="confidence", operator="gte", value=0.9),
            AgentRule(field="stance", operator="eq", value="bullish"),
        ]
        assert RuleEngine.evaluate_custom(rules, {"confidence": 0.3, "stance": "bullish"}, "or") is True
        assert RuleEngine.evaluate_custom(rules, {"confidence": 0.3, "stance": "bearish"}, "or") is False

    def test_defaults_to_and(self):
        rules = [AgentRule(field="stance", operator="eq", value="bullish")]
        assert RuleEngine.evaluate_custom(rules, {"stance": "bullish"}) is True


class TestAgentTypeLogic:
    def test_signal_follower_passthrough(self):
        signal = {"stance": "bullish", "ticker": "AAPL"}
        result = RuleEngine.apply_agent_type_logic("signal_follower", signal)
        assert result == signal

    def test_contrarian_flips_bullish(self):
        signal = {"stance": "bullish", "ticker": "AAPL"}
        result = RuleEngine.apply_agent_type_logic("contrarian", signal)
        assert result["stance"] == "bearish"
        assert result["ticker"] == "AAPL"

    def test_contrarian_flips_bearish(self):
        signal = {"stance": "bearish", "ticker": "TSLA"}
        result = RuleEngine.apply_agent_type_logic("contrarian", signal)
        assert result["stance"] == "bullish"

    def test_contrarian_unknown_no_flip(self):
        signal = {"stance": "unknown", "ticker": "SPY"}
        result = RuleEngine.apply_agent_type_logic("contrarian", signal)
        assert result["stance"] == "unknown"

    def test_contrarian_does_not_modify_original(self):
        signal = {"stance": "bullish", "ticker": "AAPL"}
        RuleEngine.apply_agent_type_logic("contrarian", signal)
        assert signal["stance"] == "bullish"  # original unchanged

    def test_momentum_rider_passthrough(self):
        signal = {"stance": "bullish"}
        result = RuleEngine.apply_agent_type_logic("momentum_rider", signal)
        assert result == signal

    def test_custom_rule_passthrough(self):
        signal = {"stance": "bearish"}
        result = RuleEngine.apply_agent_type_logic("custom_rule", signal)
        assert result == signal


class TestConfidenceGate:
    def test_above_threshold(self):
        assert RuleEngine.check_confidence_gate({"confidence": 0.7}, 0.5) is True

    def test_below_threshold(self):
        assert RuleEngine.check_confidence_gate({"confidence": 0.3}, 0.5) is False

    def test_at_threshold(self):
        assert RuleEngine.check_confidence_gate({"confidence": 0.5}, 0.5) is True

    def test_missing_confidence(self):
        assert RuleEngine.check_confidence_gate({}, 0.5) is False

    def test_string_confidence(self):
        assert RuleEngine.check_confidence_gate({"confidence": "0.7"}, 0.5) is True

    def test_invalid_confidence(self):
        assert RuleEngine.check_confidence_gate({"confidence": "abc"}, 0.5) is False

    def test_none_confidence(self):
        assert RuleEngine.check_confidence_gate({"confidence": None}, 0.5) is False


class TestStanceTradeable:
    def test_bullish(self):
        assert RuleEngine.check_stance_tradeable({"stance": "bullish"}) is True

    def test_bearish(self):
        assert RuleEngine.check_stance_tradeable({"stance": "bearish"}) is True

    def test_mixed(self):
        assert RuleEngine.check_stance_tradeable({"stance": "mixed"}) is False

    def test_unknown(self):
        assert RuleEngine.check_stance_tradeable({"stance": "unknown"}) is False

    def test_missing(self):
        assert RuleEngine.check_stance_tradeable({}) is False


# ═══════════════════════════════════════════════════════════════════════════
# Part 4: AgentEngine helpers
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_active_agents = AsyncMock(return_value=[])
    db.get_agent_trade_by_signal = AsyncMock(return_value=None)
    db.create_agent_trade = AsyncMock()
    db.get_agent_daily_trade_count = AsyncMock(return_value=0)
    db.get_paper_portfolio = AsyncMock(return_value={"balance": 10000})
    db.get_agent_trades = AsyncMock(return_value=[])
    db.get_agent_daily_pnl = AsyncMock(return_value=0.0)
    db.update_agent_status = AsyncMock()
    db.get_agent_performance_stats = AsyncMock(return_value={
        "total_trades": 0, "winning_trades": 0, "total_pnl": 0.0, "returns": [],
    })
    return db


@pytest.fixture
def engine(mock_db):
    return AgentEngine(mock_db)


class TestFlattenSignal:
    def test_dict_event(self, engine):
        signal_data = {
            "event": {
                "entities": ["AAPL"],
                "event_type": "earnings_rumor",
                "stance": "bullish",
                "confidence": 0.8,
                "time_horizon": "1d",
                "meta": {"sector": "tech"},
            },
            "trade_idea": {
                "strategy": "long_call",
                "quality_score": 0.9,
            },
            "id": "sig_123",
            "market_data": {
                "last_close": 150.0,
                "market_cap": 2.5e12,
            },
        }
        flat = engine._flatten_signal(signal_data)
        assert flat["ticker"] == "AAPL"
        assert flat["stance"] == "bullish"
        assert flat["confidence"] == 0.8
        assert flat["strategy"] == "long_call"
        assert flat["id"] == "sig_123"
        assert flat["price"] == 150.0

    def test_empty_event(self, engine):
        flat = engine._flatten_signal({})
        assert flat.get("ticker") is None
        assert flat.get("id") == ""

    def test_missing_entities(self, engine):
        signal_data = {
            "event": {
                "entities": [],
                "event_type": "other",
                "stance": "unknown",
                "confidence": 0.0,
                "time_horizon": "unknown",
                "meta": {},
            },
        }
        flat = engine._flatten_signal(signal_data)
        assert flat["ticker"] == "UNKNOWN"


class TestGetPriceFromSignal:
    def test_valid_price(self, engine):
        assert engine._get_price_from_signal({"price": 150.0}) == 150.0

    def test_string_price(self, engine):
        assert engine._get_price_from_signal({"price": "100.5"}) == 100.5

    def test_zero_price(self, engine):
        assert engine._get_price_from_signal({"price": 0}) == 0.0

    def test_missing_price(self, engine):
        assert engine._get_price_from_signal({}) == 0.0

    def test_invalid_price(self, engine):
        assert engine._get_price_from_signal({"price": "abc"}) == 0.0

    def test_none_price(self, engine):
        assert engine._get_price_from_signal({"price": None}) == 0.0


class TestComputeSharpe:
    def test_empty(self):
        assert AgentEngine._compute_sharpe([]) == 0.0

    def test_single(self):
        assert AgentEngine._compute_sharpe([5.0]) == 0.0

    def test_identical(self):
        assert AgentEngine._compute_sharpe([5.0, 5.0, 5.0]) == 0.0

    def test_positive(self):
        sharpe = AgentEngine._compute_sharpe([1.0, 2.0, 3.0, 4.0])
        assert sharpe > 0

    def test_negative(self):
        sharpe = AgentEngine._compute_sharpe([-5.0, -6.0, -7.0, -8.0])
        assert sharpe < 0


class TestComputeMaxDrawdown:
    def test_empty(self):
        assert AgentEngine._compute_max_drawdown([]) == 0.0

    def test_all_positive(self):
        dd = AgentEngine._compute_max_drawdown([1.0, 2.0, 3.0])
        assert dd == 0.0  # always going up

    def test_simple_drawdown(self):
        # cumulative: 10, 5, 2, 7
        dd = AgentEngine._compute_max_drawdown([10.0, -5.0, -3.0, 5.0])
        assert dd == 8.0  # peak=10, trough=2

    def test_single_loss(self):
        dd = AgentEngine._compute_max_drawdown([-5.0])
        assert dd == 5.0

    def test_recovery(self):
        # cumulative: 5, 2, 10
        dd = AgentEngine._compute_max_drawdown([5.0, -3.0, 8.0])
        assert dd == 3.0  # peak=5, trough=2

    def test_multiple_drawdowns(self):
        # cumulative: 10, 3, 8, 1
        dd = AgentEngine._compute_max_drawdown([10.0, -7.0, 5.0, -7.0])
        assert dd == 9.0  # peak=10 at first, peak=10 -> 1 at end: max dd = 9 (or 7 + later)
        # Actually: cumulative=10, dd=0; cumulative=3, dd=7; cumulative=8, dd=2; cumulative=1, dd=9
        assert dd == 9.0


# ═══════════════════════════════════════════════════════════════════════════
# Part 5: AgentEngine safety rails (async)
# ═══════════════════════════════════════════════════════════════════════════


class TestSafetyRails:
    @pytest.mark.asyncio
    async def test_safe_by_default(self, engine, mock_db):
        agent = {"id": "a1", "user_id": "u1", "max_daily_trades": 5}
        safe, reason = await engine.check_safety_rails(agent)
        assert safe is True
        assert reason == ""

    @pytest.mark.asyncio
    async def test_daily_limit_reached(self, engine, mock_db):
        mock_db.get_agent_daily_trade_count = AsyncMock(return_value=5)
        agent = {"id": "a1", "user_id": "u1", "max_daily_trades": 5}
        safe, reason = await engine.check_safety_rails(agent)
        assert safe is False
        assert "daily trade limit" in reason

    @pytest.mark.asyncio
    async def test_exposure_limit(self, engine, mock_db):
        mock_db.get_paper_portfolio = AsyncMock(return_value={"balance": 10000})
        mock_db.get_agent_trades = AsyncMock(return_value=[{"dollars": 5500}])
        agent = {"id": "a1", "user_id": "u1", "max_portfolio_exposure_pct": 50.0}
        safe, reason = await engine.check_safety_rails(agent)
        assert safe is False
        assert "exposure limit" in reason

    @pytest.mark.asyncio
    async def test_stop_loss_triggered(self, engine, mock_db):
        mock_db.get_paper_portfolio = AsyncMock(return_value={"balance": 10000})
        mock_db.get_agent_daily_pnl = AsyncMock(return_value=-1500.0)
        agent = {"id": "a1", "user_id": "u1", "stop_loss_pct": 10.0}
        safe, reason = await engine.check_safety_rails(agent)
        assert safe is False
        assert "stop loss" in reason
        mock_db.update_agent_status.assert_awaited_once_with("a1", "paused")

    @pytest.mark.asyncio
    async def test_no_portfolio_skips_exposure(self, engine, mock_db):
        mock_db.get_paper_portfolio = AsyncMock(return_value=None)
        agent = {"id": "a1", "user_id": "u1"}
        safe, reason = await engine.check_safety_rails(agent)
        assert safe is True


class TestEvaluateSignal:
    @pytest.mark.asyncio
    async def test_non_tradeable_signal(self, engine, mock_db):
        signal = {"event": {"entities": ["SPY"], "event_type": "other", "stance": "mixed",
                            "confidence": 0.5, "time_horizon": "1d", "meta": {}}}
        trades = await engine.evaluate_signal(signal)
        assert trades == []

    @pytest.mark.asyncio
    async def test_no_active_agents(self, engine, mock_db):
        signal = {"event": {"entities": ["SPY"], "event_type": "other", "stance": "bullish",
                            "confidence": 0.5, "time_horizon": "1d", "meta": {}}}
        mock_db.get_active_agents = AsyncMock(return_value=[])
        trades = await engine.evaluate_signal(signal)
        assert trades == []


class TestExecuteTrade:
    @pytest.mark.asyncio
    async def test_successful_trade(self, engine, mock_db):
        agent = {"id": "agent_1", "user_id": "u1", "max_position_dollars": 1000}
        signal = {"ticker": "AAPL", "stance": "bullish", "id": "sig1", "price": 150.0}
        trade = await engine.execute_trade(agent, signal)
        assert trade is not None
        assert trade["ticker"] == "AAPL"
        assert trade["stance"] == "bullish"
        assert trade["entry_price"] == 150.0
        assert trade["status"] == "open"
        assert math.isclose(trade["quantity"], 1000 / 150, rel_tol=0.01)

    @pytest.mark.asyncio
    async def test_no_price_returns_none(self, engine, mock_db):
        agent = {"id": "a1", "user_id": "u1"}
        signal = {"ticker": "X", "stance": "bullish", "id": "s1"}
        trade = await engine.execute_trade(agent, signal)
        assert trade is None


class TestGetAgentPerformance:
    @pytest.mark.asyncio
    async def test_empty_stats(self, engine, mock_db):
        perf = await engine.get_agent_performance("a1")
        assert perf.total_trades == 0
        assert perf.win_rate == 0.0
        assert perf.sharpe_ratio == 0.0

    @pytest.mark.asyncio
    async def test_with_stats(self, engine, mock_db):
        mock_db.get_agent_performance_stats = AsyncMock(return_value={
            "total_trades": 20, "winning_trades": 14, "total_pnl": 500.0,
            "returns": [5.0, -2.0, 3.0, 4.0, -1.0, 6.0, 2.0, -3.0, 5.0, 1.0],
        })
        mock_db.get_agent_daily_trade_count = AsyncMock(return_value=3)
        perf = await engine.get_agent_performance("a1")
        assert perf.total_trades == 20
        assert perf.winning_trades == 14
        assert perf.win_rate == 0.7
        assert perf.trades_today == 3
        assert perf.sharpe_ratio != 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Part 6: Constants & Parametrized
# ═══════════════════════════════════════════════════════════════════════════


class TestAgentConstants:
    def test_agent_types(self):
        assert "signal_follower" in AGENT_TYPES
        assert "contrarian" in AGENT_TYPES
        assert "momentum_rider" in AGENT_TYPES
        assert "custom_rule" in AGENT_TYPES
        assert len(AGENT_TYPES) == 4


class TestParametrized:
    @pytest.mark.parametrize("agent_type", sorted(AGENT_TYPES))
    def test_agent_type_logic_all_types(self, agent_type):
        signal = {"stance": "bullish", "ticker": "AAPL"}
        result = RuleEngine.apply_agent_type_logic(agent_type, signal)
        assert isinstance(result, dict)
        assert "stance" in result

    @pytest.mark.parametrize("confidence,threshold,expected", [
        (0.0, 0.0, True),
        (0.5, 0.5, True),
        (0.99, 1.0, False),
        (1.0, 1.0, True),
        (0.0, 0.5, False),
    ])
    def test_confidence_gate_parametrized(self, confidence, threshold, expected):
        assert RuleEngine.check_confidence_gate({"confidence": confidence}, threshold) is expected

    @pytest.mark.parametrize("stance,tradeable", [
        ("bullish", True),
        ("bearish", True),
        ("mixed", False),
        ("unknown", False),
        ("neutral", False),
    ])
    def test_stance_tradeable_parametrized(self, stance, tradeable):
        assert RuleEngine.check_stance_tradeable({"stance": stance}) is tradeable


class TestStress:
    def test_evaluate_500_rules(self):
        rules = [AgentRule(field="confidence", operator="gte", value=0.01 * i) for i in range(50)]
        signal = {"confidence": 0.99}
        assert RuleEngine.evaluate_all(rules, signal) is True

    def test_sharpe_1000_returns(self):
        returns = [float(i % 10 - 5) for i in range(1000)]
        sharpe = AgentEngine._compute_sharpe(returns)
        assert isinstance(sharpe, float)

    def test_max_drawdown_1000_returns(self):
        returns = [float(i % 10 - 3) for i in range(1000)]
        dd = AgentEngine._compute_max_drawdown(returns)
        assert dd >= 0.0

    def test_rule_matching_many_signals(self):
        rule = AgentRule(field="confidence", operator="gte", value=0.5)
        count = sum(
            1 for i in range(1000)
            if rule.matches({"confidence": 0.01 * (i % 100)})
        )
        assert count == 500  # values 0.50..0.99 repeated 10 times
