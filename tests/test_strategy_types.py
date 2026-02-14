"""Tests for src/rot/strategy/types.py — Strategy Builder & ML Optimizer dataclasses."""

from __future__ import annotations

import time

import pytest

from rot.strategy.types import (
    POSITION_SIZING_MODES,
    REGIME_TYPES,
    RULE_OPERATORS,
    STRATEGY_SOURCES,
    DiscoveryResult,
    MarketRegime,
    MarketplaceEntry,
    RegimeStrategy,
    Strategy,
    StrategyResult,
    StrategyRule,
)


# ---------------------------------------------------------------------------
# Test Constants
# ---------------------------------------------------------------------------


def test_rule_operators_constant():
    assert RULE_OPERATORS == ("gt", "lt", "gte", "lte", "eq", "neq", "in")
    assert isinstance(RULE_OPERATORS, tuple)


def test_strategy_sources_constant():
    assert STRATEGY_SOURCES == (
        "manual",
        "discovered",
        "ml_optimized",
        "genetic",
        "marketplace",
    )
    assert isinstance(STRATEGY_SOURCES, tuple)


def test_regime_types_constant():
    assert REGIME_TYPES == ("bull", "bear", "sideways", "volatile", "crisis")
    assert isinstance(REGIME_TYPES, tuple)


def test_position_sizing_modes_constant():
    assert POSITION_SIZING_MODES == ("fixed", "kelly", "confidence")
    assert isinstance(POSITION_SIZING_MODES, tuple)


# ---------------------------------------------------------------------------
# StrategyRule Tests
# ---------------------------------------------------------------------------


class TestStrategyRule:
    def test_create_with_all_fields(self):
        rule = StrategyRule(field="confidence", operator="gte", value=0.5)
        assert rule.field == "confidence"
        assert rule.operator == "gte"
        assert rule.value == 0.5

    def test_create_with_string_value(self):
        rule = StrategyRule(field="stance", operator="eq", value="bullish")
        assert rule.field == "stance"
        assert rule.operator == "eq"
        assert rule.value == "bullish"

    def test_create_with_list_value(self):
        rule = StrategyRule(
            field="event_type",
            operator="in",
            value=["earnings_rumor", "product_news"],
        )
        assert rule.field == "event_type"
        assert rule.operator == "in"
        assert isinstance(rule.value, list)
        assert len(rule.value) == 2

    def test_all_operators(self):
        for op in RULE_OPERATORS:
            rule = StrategyRule(field="test", operator=op, value=42)
            assert rule.operator == op

    def test_frozen(self):
        rule = StrategyRule(field="confidence", operator="gte", value=0.5)
        with pytest.raises(Exception):  # FrozenInstanceError
            rule.field = "new_field"  # type: ignore

    def test_empty_field_raises(self):
        with pytest.raises(ValueError, match="field must be a non-empty string"):
            StrategyRule(field="", operator="eq", value=1)

    def test_non_string_field_raises(self):
        with pytest.raises(ValueError, match="field must be a non-empty string"):
            StrategyRule(field=123, operator="eq", value=1)  # type: ignore

    def test_invalid_operator_raises(self):
        with pytest.raises(
            ValueError, match="operator must be one of.*got 'invalid'"
        ):
            StrategyRule(field="test", operator="invalid", value=1)

    def test_none_value_allowed(self):
        """None is a valid comparison value (e.g., field eq None)."""
        rule = StrategyRule(field="test", operator="eq", value=None)
        assert rule.value is None

    def test_to_dict(self):
        rule = StrategyRule(field="confidence", operator="gte", value=0.5)
        d = rule.to_dict()
        assert d == {"field": "confidence", "operator": "gte", "value": 0.5}

    def test_to_dict_with_list_value(self):
        rule = StrategyRule(
            field="event_type", operator="in", value=["earnings", "product"]
        )
        d = rule.to_dict()
        assert d["value"] == ["earnings", "product"]

    def test_from_dict(self):
        d = {"field": "confidence", "operator": "gte", "value": 0.5}
        rule = StrategyRule.from_dict(d)
        assert rule.field == "confidence"
        assert rule.operator == "gte"
        assert rule.value == 0.5

    def test_from_dict_round_trip(self):
        original = StrategyRule(
            field="stance", operator="eq", value="bullish"
        )
        d = original.to_dict()
        restored = StrategyRule.from_dict(d)
        assert restored.field == original.field
        assert restored.operator == original.operator
        assert restored.value == original.value


# ---------------------------------------------------------------------------
# Strategy Tests
# ---------------------------------------------------------------------------


class TestStrategy:
    def test_create_with_all_fields(self):
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        strat = Strategy(
            id="s1",
            user_id="u1",
            name="Test Strategy",
            description="A test",
            rules=rules,
            config={"stop_loss": 0.1},
            performance={"win_rate": 0.6},
            health_score=0.9,
            is_active=True,
            source="manual",
            created_at=100.0,
            updated_at=200.0,
        )
        assert strat.id == "s1"
        assert strat.user_id == "u1"
        assert strat.name == "Test Strategy"
        assert strat.description == "A test"
        assert len(strat.rules) == 1
        assert strat.config == {"stop_loss": 0.1}
        assert strat.performance == {"win_rate": 0.6}
        assert strat.health_score == 0.9
        assert strat.is_active is True
        assert strat.source == "manual"
        assert strat.created_at == 100.0
        assert strat.updated_at == 200.0

    def test_create_with_minimal_fields(self):
        strat = Strategy(id="s1", user_id="u1", name="Minimal", rules=[])
        assert strat.id == "s1"
        assert strat.user_id == "u1"
        assert strat.name == "Minimal"
        assert strat.description == ""
        assert strat.rules == []
        assert strat.config == {}
        assert strat.performance == {}
        assert strat.health_score == 1.0
        assert strat.is_active is False
        assert strat.source == "manual"

    def test_all_sources(self):
        for src in STRATEGY_SOURCES:
            strat = Strategy(id="s1", user_id="u1", name="Test", rules=[], source=src)
            assert strat.source == src

    def test_frozen(self):
        strat = Strategy(id="s1", user_id="u1", name="Test", rules=[])
        with pytest.raises(Exception):  # FrozenInstanceError
            strat.name = "New Name"  # type: ignore

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="id must be non-empty"):
            Strategy(id="", user_id="u1", name="Test", rules=[])

    def test_empty_user_id_raises(self):
        with pytest.raises(ValueError, match="user_id must be non-empty"):
            Strategy(id="s1", user_id="", name="Test", rules=[])

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name must be a non-empty string"):
            Strategy(id="s1", user_id="u1", name="", rules=[])

    def test_non_string_name_raises(self):
        with pytest.raises(ValueError, match="name must be a non-empty string"):
            Strategy(id="s1", user_id="u1", name=123, rules=[])  # type: ignore

    def test_non_list_rules_raises(self):
        with pytest.raises(ValueError, match="rules must be a list"):
            Strategy(id="s1", user_id="u1", name="Test", rules="not a list")  # type: ignore

    def test_invalid_source_raises(self):
        with pytest.raises(ValueError, match="source must be one of.*got 'invalid'"):
            Strategy(id="s1", user_id="u1", name="Test", rules=[], source="invalid")

    def test_health_score_below_zero_raises(self):
        with pytest.raises(
            ValueError, match="health_score must be between 0.0 and 1.0"
        ):
            Strategy(
                id="s1", user_id="u1", name="Test", rules=[], health_score=-0.1
            )

    def test_health_score_above_one_raises(self):
        with pytest.raises(
            ValueError, match="health_score must be between 0.0 and 1.0"
        ):
            Strategy(
                id="s1", user_id="u1", name="Test", rules=[], health_score=1.1
            )

    def test_health_score_boundary_zero(self):
        strat = Strategy(
            id="s1", user_id="u1", name="Test", rules=[], health_score=0.0
        )
        assert strat.health_score == 0.0

    def test_health_score_boundary_one(self):
        strat = Strategy(
            id="s1", user_id="u1", name="Test", rules=[], health_score=1.0
        )
        assert strat.health_score == 1.0

    def test_to_dict(self):
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        strat = Strategy(
            id="s1",
            user_id="u1",
            name="Test",
            description="Desc",
            rules=rules,
            config={"key": "val"},
            performance={"win_rate": 0.5},
            health_score=0.8,
            is_active=True,
            source="discovered",
            created_at=100.0,
            updated_at=200.0,
        )
        d = strat.to_dict()
        assert d["id"] == "s1"
        assert d["user_id"] == "u1"
        assert d["name"] == "Test"
        assert d["description"] == "Desc"
        assert len(d["rules"]) == 1
        assert d["rules"][0]["field"] == "confidence"
        assert d["config"] == {"key": "val"}
        assert d["performance"] == {"win_rate": 0.5}
        assert d["health_score"] == 0.8
        assert d["is_active"] is True
        assert d["source"] == "discovered"
        assert d["created_at"] == 100.0
        assert d["updated_at"] == 200.0

    def test_from_dict(self):
        d = {
            "id": "s1",
            "user_id": "u1",
            "name": "Test",
            "description": "Desc",
            "rules": [{"field": "confidence", "operator": "gte", "value": 0.5}],
            "config": {"key": "val"},
            "performance": {"win_rate": 0.6},
            "health_score": 0.7,
            "is_active": True,
            "source": "ml_optimized",
            "created_at": 100.0,
            "updated_at": 200.0,
        }
        strat = Strategy.from_dict(d)
        assert strat.id == "s1"
        assert strat.user_id == "u1"
        assert strat.name == "Test"
        assert strat.description == "Desc"
        assert len(strat.rules) == 1
        assert strat.rules[0].field == "confidence"
        assert strat.config == {"key": "val"}
        assert strat.performance == {"win_rate": 0.6}
        assert strat.health_score == 0.7
        assert strat.is_active is True
        assert strat.source == "ml_optimized"
        assert strat.created_at == 100.0
        assert strat.updated_at == 200.0

    def test_from_dict_with_defaults(self):
        d = {"id": "s1", "user_id": "u1", "name": "Test"}
        strat = Strategy.from_dict(d)
        assert strat.description == ""
        assert strat.rules == []
        assert strat.config == {}
        assert strat.performance == {}
        assert strat.health_score == 1.0
        assert strat.is_active is False
        assert strat.source == "manual"
        assert strat.created_at == 0.0
        assert strat.updated_at == 0.0

    def test_from_dict_round_trip(self):
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        original = Strategy(
            id="s1",
            user_id="u1",
            name="Test",
            rules=rules,
            health_score=0.85,
            source="genetic",
        )
        d = original.to_dict()
        restored = Strategy.from_dict(d)
        assert restored.id == original.id
        assert restored.user_id == original.user_id
        assert restored.name == original.name
        assert len(restored.rules) == len(original.rules)
        assert restored.health_score == original.health_score
        assert restored.source == original.source


# ---------------------------------------------------------------------------
# StrategyResult Tests
# ---------------------------------------------------------------------------


class TestStrategyResult:
    def test_create_with_all_fields(self):
        result = StrategyResult(
            id="r1",
            strategy_id="s1",
            signal_id="sig1",
            ticker="TSLA",
            stance="bullish",
            entry_price=100.0,
            exit_price=110.0,
            pnl_pct=10.0,
            created_at=100.0,
            resolved_at=200.0,
        )
        assert result.id == "r1"
        assert result.strategy_id == "s1"
        assert result.signal_id == "sig1"
        assert result.ticker == "TSLA"
        assert result.stance == "bullish"
        assert result.entry_price == 100.0
        assert result.exit_price == 110.0
        assert result.pnl_pct == 10.0
        assert result.created_at == 100.0
        assert result.resolved_at == 200.0

    def test_create_with_minimal_fields_open_trade(self):
        result = StrategyResult(
            id="r1",
            strategy_id="s1",
            signal_id="sig1",
            ticker="AAPL",
            stance="bearish",
            entry_price=150.0,
        )
        assert result.exit_price is None
        assert result.pnl_pct is None
        assert result.resolved_at is None

    def test_bullish_stance(self):
        result = StrategyResult(
            id="r1",
            strategy_id="s1",
            signal_id="sig1",
            ticker="TSLA",
            stance="bullish",
            entry_price=100.0,
        )
        assert result.stance == "bullish"

    def test_bearish_stance(self):
        result = StrategyResult(
            id="r1",
            strategy_id="s1",
            signal_id="sig1",
            ticker="TSLA",
            stance="bearish",
            entry_price=100.0,
        )
        assert result.stance == "bearish"

    def test_frozen(self):
        result = StrategyResult(
            id="r1",
            strategy_id="s1",
            signal_id="sig1",
            ticker="TSLA",
            stance="bullish",
            entry_price=100.0,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            result.ticker = "AAPL"  # type: ignore

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="id must be non-empty"):
            StrategyResult(
                id="",
                strategy_id="s1",
                signal_id="sig1",
                ticker="TSLA",
                stance="bullish",
                entry_price=100.0,
            )

    def test_empty_strategy_id_raises(self):
        with pytest.raises(ValueError, match="strategy_id must be non-empty"):
            StrategyResult(
                id="r1",
                strategy_id="",
                signal_id="sig1",
                ticker="TSLA",
                stance="bullish",
                entry_price=100.0,
            )

    def test_empty_signal_id_raises(self):
        with pytest.raises(ValueError, match="signal_id must be non-empty"):
            StrategyResult(
                id="r1",
                strategy_id="s1",
                signal_id="",
                ticker="TSLA",
                stance="bullish",
                entry_price=100.0,
            )

    def test_empty_ticker_raises(self):
        with pytest.raises(ValueError, match="ticker must be non-empty"):
            StrategyResult(
                id="r1",
                strategy_id="s1",
                signal_id="sig1",
                ticker="",
                stance="bullish",
                entry_price=100.0,
            )

    def test_invalid_stance_raises(self):
        with pytest.raises(
            ValueError, match="stance must be bullish or bearish, got 'mixed'"
        ):
            StrategyResult(
                id="r1",
                strategy_id="s1",
                signal_id="sig1",
                ticker="TSLA",
                stance="mixed",
                entry_price=100.0,
            )

    def test_zero_entry_price_raises(self):
        with pytest.raises(ValueError, match="entry_price must be positive"):
            StrategyResult(
                id="r1",
                strategy_id="s1",
                signal_id="sig1",
                ticker="TSLA",
                stance="bullish",
                entry_price=0.0,
            )

    def test_negative_entry_price_raises(self):
        with pytest.raises(ValueError, match="entry_price must be positive"):
            StrategyResult(
                id="r1",
                strategy_id="s1",
                signal_id="sig1",
                ticker="TSLA",
                stance="bullish",
                entry_price=-10.0,
            )

    def test_to_dict(self):
        result = StrategyResult(
            id="r1",
            strategy_id="s1",
            signal_id="sig1",
            ticker="TSLA",
            stance="bullish",
            entry_price=100.0,
            exit_price=110.0,
            pnl_pct=10.0,
            created_at=100.0,
            resolved_at=200.0,
        )
        d = result.to_dict()
        assert d["id"] == "r1"
        assert d["strategy_id"] == "s1"
        assert d["signal_id"] == "sig1"
        assert d["ticker"] == "TSLA"
        assert d["stance"] == "bullish"
        assert d["entry_price"] == 100.0
        assert d["exit_price"] == 110.0
        assert d["pnl_pct"] == 10.0
        assert d["created_at"] == 100.0
        assert d["resolved_at"] == 200.0

    def test_to_dict_open_trade(self):
        result = StrategyResult(
            id="r1",
            strategy_id="s1",
            signal_id="sig1",
            ticker="TSLA",
            stance="bullish",
            entry_price=100.0,
        )
        d = result.to_dict()
        assert d["exit_price"] is None
        assert d["pnl_pct"] is None
        assert d["resolved_at"] is None


# ---------------------------------------------------------------------------
# DiscoveryResult Tests
# ---------------------------------------------------------------------------


class TestDiscoveryResult:
    def test_create_with_all_fields(self):
        result = DiscoveryResult(
            id="d1",
            user_id="u1",
            search_config={"min_sharpe": 1.0},
            strategies_found=5,
            best_strategies=[{"id": "s1"}, {"id": "s2"}],
            elapsed_s=10.5,
            created_at=100.0,
        )
        assert result.id == "d1"
        assert result.user_id == "u1"
        assert result.search_config == {"min_sharpe": 1.0}
        assert result.strategies_found == 5
        assert len(result.best_strategies) == 2
        assert result.elapsed_s == 10.5
        assert result.created_at == 100.0

    def test_create_with_minimal_fields(self):
        result = DiscoveryResult(
            id="d1", user_id="u1", search_config={}, strategies_found=0
        )
        assert result.id == "d1"
        assert result.user_id == "u1"
        assert result.search_config == {}
        assert result.strategies_found == 0
        assert result.best_strategies == []
        assert result.elapsed_s == 0.0

    def test_frozen(self):
        result = DiscoveryResult(
            id="d1", user_id="u1", search_config={}, strategies_found=0
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            result.strategies_found = 10  # type: ignore

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="id must be non-empty"):
            DiscoveryResult(
                id="", user_id="u1", search_config={}, strategies_found=0
            )

    def test_empty_user_id_raises(self):
        with pytest.raises(ValueError, match="user_id must be non-empty"):
            DiscoveryResult(
                id="d1", user_id="", search_config={}, strategies_found=0
            )

    def test_negative_strategies_found_raises(self):
        with pytest.raises(ValueError, match="strategies_found must be >= 0"):
            DiscoveryResult(
                id="d1", user_id="u1", search_config={}, strategies_found=-1
            )

    def test_negative_elapsed_s_raises(self):
        with pytest.raises(ValueError, match="elapsed_s must be >= 0"):
            DiscoveryResult(
                id="d1",
                user_id="u1",
                search_config={},
                strategies_found=0,
                elapsed_s=-1.0,
            )

    def test_to_dict(self):
        result = DiscoveryResult(
            id="d1",
            user_id="u1",
            search_config={"key": "val"},
            strategies_found=3,
            best_strategies=[{"id": "s1"}],
            elapsed_s=5.5,
            created_at=100.0,
        )
        d = result.to_dict()
        assert d["id"] == "d1"
        assert d["user_id"] == "u1"
        assert d["search_config"] == {"key": "val"}
        assert d["strategies_found"] == 3
        assert d["best_strategies"] == [{"id": "s1"}]
        assert d["elapsed_s"] == 5.5
        assert d["created_at"] == 100.0


# ---------------------------------------------------------------------------
# MarketRegime Tests
# ---------------------------------------------------------------------------


class TestMarketRegime:
    def test_create_with_all_fields(self):
        regime = MarketRegime(
            id="m1",
            regime_type="bull",
            start_ts=100.0,
            end_ts=200.0,
            indicators={"vix": 15.0},
            confidence=0.9,
            detected_at=105.0,
        )
        assert regime.id == "m1"
        assert regime.regime_type == "bull"
        assert regime.start_ts == 100.0
        assert regime.end_ts == 200.0
        assert regime.indicators == {"vix": 15.0}
        assert regime.confidence == 0.9
        assert regime.detected_at == 105.0

    def test_create_with_minimal_fields(self):
        regime = MarketRegime(id="m1", regime_type="bear", start_ts=100.0)
        assert regime.id == "m1"
        assert regime.regime_type == "bear"
        assert regime.start_ts == 100.0
        assert regime.end_ts is None
        assert regime.indicators == {}
        assert regime.confidence == 0.5

    def test_all_regime_types(self):
        for rt in REGIME_TYPES:
            regime = MarketRegime(id="m1", regime_type=rt, start_ts=100.0)
            assert regime.regime_type == rt

    def test_frozen(self):
        regime = MarketRegime(id="m1", regime_type="bull", start_ts=100.0)
        with pytest.raises(Exception):  # FrozenInstanceError
            regime.confidence = 0.8  # type: ignore

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="id must be non-empty"):
            MarketRegime(id="", regime_type="bull", start_ts=100.0)

    def test_invalid_regime_type_raises(self):
        with pytest.raises(
            ValueError, match="regime_type must be one of.*got 'invalid'"
        ):
            MarketRegime(id="m1", regime_type="invalid", start_ts=100.0)

    def test_confidence_below_zero_raises(self):
        with pytest.raises(
            ValueError, match="confidence must be between 0.0 and 1.0"
        ):
            MarketRegime(
                id="m1", regime_type="bull", start_ts=100.0, confidence=-0.1
            )

    def test_confidence_above_one_raises(self):
        with pytest.raises(
            ValueError, match="confidence must be between 0.0 and 1.0"
        ):
            MarketRegime(
                id="m1", regime_type="bull", start_ts=100.0, confidence=1.1
            )

    def test_confidence_boundary_zero(self):
        regime = MarketRegime(
            id="m1", regime_type="bull", start_ts=100.0, confidence=0.0
        )
        assert regime.confidence == 0.0

    def test_confidence_boundary_one(self):
        regime = MarketRegime(
            id="m1", regime_type="bull", start_ts=100.0, confidence=1.0
        )
        assert regime.confidence == 1.0

    def test_end_ts_before_start_ts_raises(self):
        with pytest.raises(ValueError, match="end_ts must be >= start_ts"):
            MarketRegime(
                id="m1", regime_type="bull", start_ts=100.0, end_ts=50.0
            )

    def test_end_ts_equal_start_ts(self):
        regime = MarketRegime(
            id="m1", regime_type="bull", start_ts=100.0, end_ts=100.0
        )
        assert regime.end_ts == 100.0

    def test_to_dict(self):
        regime = MarketRegime(
            id="m1",
            regime_type="volatile",
            start_ts=100.0,
            end_ts=200.0,
            indicators={"vix": 30.0},
            confidence=0.85,
            detected_at=105.0,
        )
        d = regime.to_dict()
        assert d["id"] == "m1"
        assert d["regime_type"] == "volatile"
        assert d["start_ts"] == 100.0
        assert d["end_ts"] == 200.0
        assert d["indicators"] == {"vix": 30.0}
        assert d["confidence"] == 0.85
        assert d["detected_at"] == 105.0

    def test_to_dict_ongoing_regime(self):
        regime = MarketRegime(id="m1", regime_type="crisis", start_ts=100.0)
        d = regime.to_dict()
        assert d["end_ts"] is None


# ---------------------------------------------------------------------------
# RegimeStrategy Tests
# ---------------------------------------------------------------------------


class TestRegimeStrategy:
    def test_create_with_all_fields(self):
        rs = RegimeStrategy(
            strategy_id="s1",
            regime_type="bull",
            win_rate=0.75,
            sharpe=1.5,
            total_trades=100,
            avg_pnl_pct=5.0,
            recommended=True,
        )
        assert rs.strategy_id == "s1"
        assert rs.regime_type == "bull"
        assert rs.win_rate == 0.75
        assert rs.sharpe == 1.5
        assert rs.total_trades == 100
        assert rs.avg_pnl_pct == 5.0
        assert rs.recommended is True

    def test_create_with_minimal_fields(self):
        rs = RegimeStrategy(strategy_id="s1", regime_type="bear")
        assert rs.strategy_id == "s1"
        assert rs.regime_type == "bear"
        assert rs.win_rate == 0.0
        assert rs.sharpe == 0.0
        assert rs.total_trades == 0
        assert rs.avg_pnl_pct == 0.0
        assert rs.recommended is False

    def test_all_regime_types(self):
        for rt in REGIME_TYPES:
            rs = RegimeStrategy(strategy_id="s1", regime_type=rt)
            assert rs.regime_type == rt

    def test_frozen(self):
        rs = RegimeStrategy(strategy_id="s1", regime_type="bull")
        with pytest.raises(Exception):  # FrozenInstanceError
            rs.win_rate = 0.5  # type: ignore

    def test_empty_strategy_id_raises(self):
        with pytest.raises(ValueError, match="strategy_id must be non-empty"):
            RegimeStrategy(strategy_id="", regime_type="bull")

    def test_invalid_regime_type_raises(self):
        with pytest.raises(
            ValueError, match="regime_type must be one of.*got 'invalid'"
        ):
            RegimeStrategy(strategy_id="s1", regime_type="invalid")

    def test_win_rate_below_zero_raises(self):
        with pytest.raises(ValueError, match="win_rate must be between 0.0 and 1.0"):
            RegimeStrategy(strategy_id="s1", regime_type="bull", win_rate=-0.1)

    def test_win_rate_above_one_raises(self):
        with pytest.raises(ValueError, match="win_rate must be between 0.0 and 1.0"):
            RegimeStrategy(strategy_id="s1", regime_type="bull", win_rate=1.1)

    def test_win_rate_boundary_zero(self):
        rs = RegimeStrategy(strategy_id="s1", regime_type="bull", win_rate=0.0)
        assert rs.win_rate == 0.0

    def test_win_rate_boundary_one(self):
        rs = RegimeStrategy(strategy_id="s1", regime_type="bull", win_rate=1.0)
        assert rs.win_rate == 1.0

    def test_negative_sharpe(self):
        rs = RegimeStrategy(strategy_id="s1", regime_type="bear", sharpe=-0.5)
        assert rs.sharpe == -0.5

    def test_to_dict(self):
        rs = RegimeStrategy(
            strategy_id="s1",
            regime_type="sideways",
            win_rate=0.6,
            sharpe=0.8,
            total_trades=50,
            avg_pnl_pct=2.5,
            recommended=True,
        )
        d = rs.to_dict()
        assert d["strategy_id"] == "s1"
        assert d["regime_type"] == "sideways"
        assert d["win_rate"] == 0.6
        assert d["sharpe"] == 0.8
        assert d["total_trades"] == 50
        assert d["avg_pnl_pct"] == 2.5
        assert d["recommended"] is True


# ---------------------------------------------------------------------------
# MarketplaceEntry Tests
# ---------------------------------------------------------------------------


class TestMarketplaceEntry:
    def test_create_with_all_fields(self):
        entry = MarketplaceEntry(
            id="mp1",
            strategy_id="s1",
            author_id="u1",
            name="Pro Strategy",
            description="A winning strategy",
            performance={"win_rate": 0.8},
            subscriber_count=100,
            rating=4.5,
            created_at=100.0,
        )
        assert entry.id == "mp1"
        assert entry.strategy_id == "s1"
        assert entry.author_id == "u1"
        assert entry.name == "Pro Strategy"
        assert entry.description == "A winning strategy"
        assert entry.performance == {"win_rate": 0.8}
        assert entry.subscriber_count == 100
        assert entry.rating == 4.5
        assert entry.created_at == 100.0

    def test_create_with_minimal_fields(self):
        entry = MarketplaceEntry(
            id="mp1", strategy_id="s1", author_id="u1", name="Basic"
        )
        assert entry.id == "mp1"
        assert entry.strategy_id == "s1"
        assert entry.author_id == "u1"
        assert entry.name == "Basic"
        assert entry.description == ""
        assert entry.performance == {}
        assert entry.subscriber_count == 0
        assert entry.rating == 0.0

    def test_frozen(self):
        entry = MarketplaceEntry(
            id="mp1", strategy_id="s1", author_id="u1", name="Test"
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            entry.rating = 5.0  # type: ignore

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="id must be non-empty"):
            MarketplaceEntry(
                id="", strategy_id="s1", author_id="u1", name="Test"
            )

    def test_empty_strategy_id_raises(self):
        with pytest.raises(ValueError, match="strategy_id must be non-empty"):
            MarketplaceEntry(
                id="mp1", strategy_id="", author_id="u1", name="Test"
            )

    def test_empty_author_id_raises(self):
        with pytest.raises(ValueError, match="author_id must be non-empty"):
            MarketplaceEntry(
                id="mp1", strategy_id="s1", author_id="", name="Test"
            )

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name must be non-empty"):
            MarketplaceEntry(
                id="mp1", strategy_id="s1", author_id="u1", name=""
            )

    def test_rating_below_zero_raises(self):
        with pytest.raises(ValueError, match="rating must be between 0.0 and 5.0"):
            MarketplaceEntry(
                id="mp1",
                strategy_id="s1",
                author_id="u1",
                name="Test",
                rating=-0.1,
            )

    def test_rating_above_five_raises(self):
        with pytest.raises(ValueError, match="rating must be between 0.0 and 5.0"):
            MarketplaceEntry(
                id="mp1",
                strategy_id="s1",
                author_id="u1",
                name="Test",
                rating=5.1,
            )

    def test_rating_boundary_zero(self):
        entry = MarketplaceEntry(
            id="mp1", strategy_id="s1", author_id="u1", name="Test", rating=0.0
        )
        assert entry.rating == 0.0

    def test_rating_boundary_five(self):
        entry = MarketplaceEntry(
            id="mp1", strategy_id="s1", author_id="u1", name="Test", rating=5.0
        )
        assert entry.rating == 5.0

    def test_negative_subscriber_count_raises(self):
        with pytest.raises(ValueError, match="subscriber_count must be >= 0"):
            MarketplaceEntry(
                id="mp1",
                strategy_id="s1",
                author_id="u1",
                name="Test",
                subscriber_count=-1,
            )

    def test_to_dict(self):
        entry = MarketplaceEntry(
            id="mp1",
            strategy_id="s1",
            author_id="u1",
            name="Elite",
            description="The best",
            performance={"sharpe": 2.0},
            subscriber_count=500,
            rating=4.8,
            created_at=100.0,
        )
        d = entry.to_dict()
        assert d["id"] == "mp1"
        assert d["strategy_id"] == "s1"
        assert d["author_id"] == "u1"
        assert d["name"] == "Elite"
        assert d["description"] == "The best"
        assert d["performance"] == {"sharpe": 2.0}
        assert d["subscriber_count"] == 500
        assert d["rating"] == 4.8
        assert d["created_at"] == 100.0
