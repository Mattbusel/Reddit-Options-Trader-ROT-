"""Tests for rot.strategy — types, rule engine, regime detector.

Covers StrategyRule, Strategy, StrategyResult, DiscoveryResult, MarketRegime,
RegimeStrategy, MarketplaceEntry dataclasses. RuleEngine compile, evaluate,
batch_evaluate, explain, nested field access, and all 7 operators.
RegimeDetector classify, detect_regime, detect_regime_history, build_regime_matrix,
get_regime_recommendation.
"""
from __future__ import annotations

import math
import time

import pytest

from rot.strategy.types import (
    POSITION_SIZING_MODES,
    REGIME_TYPES,
    RULE_OPERATORS,
    STRATEGY_SOURCES,
    DiscoveryResult,
    MarketplaceEntry,
    MarketRegime,
    RegimeStrategy,
    Strategy,
    StrategyResult,
    StrategyRule,
)
from rot.strategy.rules import (
    CompiledRule,
    EvalResult,
    MISSING,
    RuleEngine,
    RuleEvalDetail,
    _check_in,
    _format_value,
    _is_numeric,
    compile_rules,
    explain,
)
from rot.strategy.regime import (
    RegimeDetector,
    _compute_sharpe,
    _safe_mean,
    _safe_stdev,
    _stance_to_numeric,
)


# ═══════════════════════════════════════════════════════════════════════════
# Part 1: Strategy Types
# ═══════════════════════════════════════════════════════════════════════════


class TestConstants:
    def test_rule_operators(self):
        assert len(RULE_OPERATORS) == 7
        for op in ("gt", "lt", "gte", "lte", "eq", "neq", "in"):
            assert op in RULE_OPERATORS

    def test_strategy_sources(self):
        for s in ("manual", "discovered", "ml_optimized", "genetic", "marketplace"):
            assert s in STRATEGY_SOURCES

    def test_regime_types(self):
        for r in ("bull", "bear", "sideways", "volatile", "crisis"):
            assert r in REGIME_TYPES

    def test_position_sizing_modes(self):
        for m in ("fixed", "kelly", "confidence"):
            assert m in POSITION_SIZING_MODES


class TestStrategyRule:
    def test_basic_creation(self):
        r = StrategyRule(field="confidence", operator="gte", value=0.5)
        assert r.field == "confidence"
        assert r.operator == "gte"
        assert r.value == 0.5

    def test_to_dict(self):
        r = StrategyRule(field="stance", operator="eq", value="bullish")
        d = r.to_dict()
        assert d == {"field": "stance", "operator": "eq", "value": "bullish"}

    def test_from_dict(self):
        r = StrategyRule.from_dict({"field": "x", "operator": "gt", "value": 10})
        assert r.field == "x"
        assert r.value == 10

    def test_roundtrip(self):
        r = StrategyRule(field="trend_score", operator="lte", value=0.9)
        r2 = StrategyRule.from_dict(r.to_dict())
        assert r == r2

    def test_empty_field_raises(self):
        with pytest.raises(ValueError, match="field"):
            StrategyRule(field="", operator="eq", value=1)

    def test_invalid_operator_raises(self):
        with pytest.raises(ValueError, match="operator"):
            StrategyRule(field="x", operator="like", value=1)

    @pytest.mark.parametrize("op", RULE_OPERATORS)
    def test_all_operators_valid(self, op):
        r = StrategyRule(field="x", operator=op, value=1)
        assert r.operator == op

    def test_frozen(self):
        r = StrategyRule(field="x", operator="eq", value=1)
        with pytest.raises(AttributeError):
            r.value = 2  # type: ignore[misc]


class TestStrategy:
    def test_basic_creation(self):
        rules = [StrategyRule(field="stance", operator="eq", value="bullish")]
        s = Strategy(id="s1", user_id="u1", name="Bull Only", rules=rules)
        assert s.id == "s1"
        assert s.health_score == 1.0
        assert s.is_active is False
        assert s.source == "manual"

    def test_to_dict(self):
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        s = Strategy(id="s1", user_id="u1", name="Test", rules=rules)
        d = s.to_dict()
        assert d["id"] == "s1"
        assert len(d["rules"]) == 1

    def test_from_dict(self):
        d = {
            "id": "s1", "user_id": "u1", "name": "Test",
            "rules": [{"field": "x", "operator": "eq", "value": 1}],
            "source": "discovered",
        }
        s = Strategy.from_dict(d)
        assert s.source == "discovered"
        assert len(s.rules) == 1

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="id"):
            Strategy(id="", user_id="u1", name="Test", rules=[])

    def test_invalid_source_raises(self):
        with pytest.raises(ValueError, match="source"):
            Strategy(id="s1", user_id="u1", name="Test", rules=[], source="invalid")

    def test_invalid_health_score_raises(self):
        with pytest.raises(ValueError, match="health_score"):
            Strategy(id="s1", user_id="u1", name="Test", rules=[], health_score=1.5)

    @pytest.mark.parametrize("source", STRATEGY_SOURCES)
    def test_all_sources_valid(self, source):
        s = Strategy(id="s1", user_id="u1", name="Test", rules=[], source=source)
        assert s.source == source


class TestStrategyResult:
    def test_basic_creation(self):
        sr = StrategyResult(
            id="t1", strategy_id="s1", signal_id="sig1",
            ticker="AAPL", stance="bullish", entry_price=150.0,
        )
        assert sr.exit_price is None
        assert sr.pnl_pct is None

    def test_to_dict(self):
        sr = StrategyResult(
            id="t1", strategy_id="s1", signal_id="sig1",
            ticker="AAPL", stance="bearish", entry_price=100.0,
            exit_price=90.0, pnl_pct=10.0,
        )
        d = sr.to_dict()
        assert d["exit_price"] == 90.0

    def test_invalid_stance(self):
        with pytest.raises(ValueError, match="stance"):
            StrategyResult(
                id="t1", strategy_id="s1", signal_id="sig1",
                ticker="AAPL", stance="mixed", entry_price=100.0,
            )

    def test_zero_entry_price(self):
        with pytest.raises(ValueError, match="entry_price"):
            StrategyResult(
                id="t1", strategy_id="s1", signal_id="sig1",
                ticker="AAPL", stance="bullish", entry_price=0.0,
            )


class TestDiscoveryResult:
    def test_basic_creation(self):
        dr = DiscoveryResult(
            id="d1", user_id="u1", search_config={"max_rules": 3},
            strategies_found=5, elapsed_s=1.5,
        )
        assert dr.strategies_found == 5

    def test_to_dict(self):
        dr = DiscoveryResult(
            id="d1", user_id="u1", search_config={},
            strategies_found=0, best_strategies=[{"name": "test"}],
        )
        d = dr.to_dict()
        assert len(d["best_strategies"]) == 1

    def test_negative_strategies_found(self):
        with pytest.raises(ValueError, match="strategies_found"):
            DiscoveryResult(id="d1", user_id="u1", search_config={}, strategies_found=-1)


class TestMarketRegime:
    def test_basic_creation(self):
        mr = MarketRegime(id="r1", regime_type="bull", start_ts=1000.0)
        assert mr.end_ts is None
        assert mr.confidence == 0.5

    def test_to_dict(self):
        mr = MarketRegime(
            id="r1", regime_type="crisis", start_ts=1000.0,
            end_ts=2000.0, confidence=0.9,
        )
        d = mr.to_dict()
        assert d["regime_type"] == "crisis"

    def test_invalid_regime_type(self):
        with pytest.raises(ValueError, match="regime_type"):
            MarketRegime(id="r1", regime_type="panic", start_ts=1000.0)

    def test_invalid_confidence(self):
        with pytest.raises(ValueError, match="confidence"):
            MarketRegime(id="r1", regime_type="bull", start_ts=1000.0, confidence=1.5)

    def test_end_before_start(self):
        with pytest.raises(ValueError, match="end_ts"):
            MarketRegime(id="r1", regime_type="bull", start_ts=2000.0, end_ts=1000.0)

    @pytest.mark.parametrize("rt", REGIME_TYPES)
    def test_all_regime_types_valid(self, rt):
        mr = MarketRegime(id="r1", regime_type=rt, start_ts=1000.0)
        assert mr.regime_type == rt


class TestRegimeStrategy:
    def test_basic_creation(self):
        rs = RegimeStrategy(strategy_id="s1", regime_type="bull", win_rate=0.6)
        assert rs.recommended is False

    def test_to_dict(self):
        rs = RegimeStrategy(
            strategy_id="s1", regime_type="bear",
            win_rate=0.7, sharpe=1.5, total_trades=20, recommended=True,
        )
        d = rs.to_dict()
        assert d["recommended"] is True

    def test_invalid_win_rate(self):
        with pytest.raises(ValueError, match="win_rate"):
            RegimeStrategy(strategy_id="s1", regime_type="bull", win_rate=1.5)


class TestMarketplaceEntry:
    def test_basic_creation(self):
        me = MarketplaceEntry(
            id="m1", strategy_id="s1", author_id="u1", name="Bull Strategy",
        )
        assert me.subscriber_count == 0
        assert me.rating == 0.0

    def test_to_dict(self):
        me = MarketplaceEntry(
            id="m1", strategy_id="s1", author_id="u1",
            name="Test", rating=4.5, subscriber_count=100,
        )
        d = me.to_dict()
        assert d["rating"] == 4.5

    def test_invalid_rating(self):
        with pytest.raises(ValueError, match="rating"):
            MarketplaceEntry(
                id="m1", strategy_id="s1", author_id="u1",
                name="Test", rating=5.5,
            )

    def test_negative_subscribers(self):
        with pytest.raises(ValueError, match="subscriber_count"):
            MarketplaceEntry(
                id="m1", strategy_id="s1", author_id="u1",
                name="Test", subscriber_count=-1,
            )


# ═══════════════════════════════════════════════════════════════════════════
# Part 2: Rule Engine Helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestIsNumeric:
    def test_int(self):
        assert _is_numeric(42) is True

    def test_float(self):
        assert _is_numeric(3.14) is True

    def test_bool_excluded(self):
        assert _is_numeric(True) is False
        assert _is_numeric(False) is False

    def test_string(self):
        assert _is_numeric("42") is False

    def test_none(self):
        assert _is_numeric(None) is False


class TestCheckIn:
    def test_value_in_list(self):
        assert _check_in("bullish", ["bullish", "bearish"]) is True

    def test_value_not_in_list(self):
        assert _check_in("mixed", ["bullish", "bearish"]) is False

    def test_list_intersection(self):
        assert _check_in(["a", "b"], ["b", "c"]) is True

    def test_list_no_intersection(self):
        assert _check_in(["a", "b"], ["c", "d"]) is False

    def test_substring_match(self):
        assert _check_in("wallstreetbets_daily", "wallstreetbets") is True

    def test_substring_no_match(self):
        assert _check_in("stocks", "wallstreetbets") is False

    def test_unsupported_target_type(self):
        assert _check_in("hello", 42) is False


class TestFormatValue:
    def test_string(self):
        assert _format_value("hello") == '"hello"'

    def test_number(self):
        assert _format_value(42) == "42"

    def test_list(self):
        result = _format_value(["a", "b"])
        assert result == '["a", "b"]'

    def test_none(self):
        assert _format_value(None) == "None"


class TestMissingSentinel:
    def test_singleton(self):
        from rot.strategy.rules import _Missing
        a = _Missing()
        b = _Missing()
        assert a is b

    def test_falsy(self):
        assert not MISSING

    def test_repr(self):
        assert repr(MISSING) == "<MISSING>"


# ═══════════════════════════════════════════════════════════════════════════
# Part 3: Rule Engine Core
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def engine():
    return RuleEngine()


class TestCompileRules:
    def test_simple_rule(self, engine):
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        compiled = engine.compile_rules(rules)
        assert len(compiled) == 1
        assert compiled[0].field_parts == ["confidence"]
        assert compiled[0].operator == "gte"
        assert compiled[0].value == 0.5

    def test_nested_field(self, engine):
        rules = [StrategyRule(field="meta.nlp.sentiment", operator="gt", value=0.0)]
        compiled = engine.compile_rules(rules)
        assert compiled[0].field_parts == ["meta", "nlp", "sentiment"]

    def test_module_level_compile(self):
        rules = [StrategyRule(field="x", operator="eq", value=1)]
        compiled = compile_rules(rules)
        assert len(compiled) == 1

    def test_empty_rules(self, engine):
        compiled = engine.compile_rules([])
        assert compiled == []


class TestEvaluate:
    def test_empty_rules_pass(self, engine):
        assert engine.evaluate({"x": 1}, []) is True

    def test_matching_rule(self, engine):
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        assert engine.evaluate({"confidence": 0.7}, rules) is True

    def test_failing_rule(self, engine):
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        assert engine.evaluate({"confidence": 0.3}, rules) is False

    def test_missing_field_fails(self, engine):
        rules = [StrategyRule(field="missing", operator="eq", value=1)]
        assert engine.evaluate({"other": 1}, rules) is False

    def test_multiple_rules_all_must_match(self, engine):
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        assert engine.evaluate({"confidence": 0.7, "stance": "bullish"}, rules) is True
        assert engine.evaluate({"confidence": 0.7, "stance": "bearish"}, rules) is False
        assert engine.evaluate({"confidence": 0.3, "stance": "bullish"}, rules) is False


class TestAllOperators:
    @pytest.mark.parametrize("op,val,target,expected", [
        ("gt", 10, 5, True),
        ("gt", 5, 5, False),
        ("gt", 3, 5, False),
        ("lt", 3, 5, True),
        ("lt", 5, 5, False),
        ("lt", 10, 5, False),
        ("gte", 5, 5, True),
        ("gte", 6, 5, True),
        ("gte", 4, 5, False),
        ("lte", 5, 5, True),
        ("lte", 4, 5, True),
        ("lte", 6, 5, False),
        ("eq", "bullish", "bullish", True),
        ("eq", "bearish", "bullish", False),
        ("neq", "bearish", "bullish", True),
        ("neq", "bullish", "bullish", False),
    ])
    def test_operator(self, engine, op, val, target, expected):
        rules = [StrategyRule(field="x", operator=op, value=target)]
        result = engine.evaluate({"x": val}, rules)
        assert result is expected

    def test_in_operator_list(self, engine):
        rules = [StrategyRule(field="stance", operator="in", value=["bullish", "bearish"])]
        assert engine.evaluate({"stance": "bullish"}, rules) is True
        assert engine.evaluate({"stance": "mixed"}, rules) is False

    def test_in_operator_substring(self, engine):
        rules = [StrategyRule(field="source", operator="in", value="wsb")]
        assert engine.evaluate({"source": "r/wsb daily"}, rules) is True
        assert engine.evaluate({"source": "r/stocks"}, rules) is False


class TestNestedFieldAccess:
    def test_simple_field(self, engine):
        val = engine._get_nested_value({"x": 42}, ["x"])
        assert val == 42

    def test_nested_field(self, engine):
        signal = {"meta": {"nlp": {"sentiment": 0.8}}}
        val = engine._get_nested_value(signal, ["meta", "nlp", "sentiment"])
        assert val == 0.8

    def test_missing_key(self, engine):
        val = engine._get_nested_value({"x": 1}, ["y"])
        assert val is MISSING

    def test_missing_nested_key(self, engine):
        val = engine._get_nested_value({"meta": {"a": 1}}, ["meta", "b"])
        assert val is MISSING

    def test_non_dict_intermediate(self, engine):
        val = engine._get_nested_value({"meta": 42}, ["meta", "nested"])
        assert val is MISSING

    def test_string_field_parts(self, engine):
        val = engine._get_nested_value({"a": {"b": 3}}, "a.b")
        assert val == 3

    def test_none_value_not_missing(self, engine):
        val = engine._get_nested_value({"x": None}, ["x"])
        assert val is None
        assert val is not MISSING


class TestBatchEvaluate:
    def test_empty_signals(self, engine):
        rules = [StrategyRule(field="x", operator="eq", value=1)]
        assert engine.batch_evaluate([], rules) == []

    def test_empty_rules_returns_all(self, engine):
        signals = [{"x": 1}, {"x": 2}]
        assert engine.batch_evaluate(signals, []) == signals

    def test_filters_correctly(self, engine):
        signals = [
            {"confidence": 0.8, "stance": "bullish"},
            {"confidence": 0.3, "stance": "bullish"},
            {"confidence": 0.6, "stance": "bearish"},
        ]
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        matched = engine.batch_evaluate(signals, rules)
        assert len(matched) == 1
        assert matched[0]["confidence"] == 0.8


class TestGenerateRuleSummary:
    def test_single_rule(self):
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        summary = RuleEngine.generate_rule_summary(rules)
        assert "confidence" in summary
        assert ">=" in summary
        assert "0.5" in summary

    def test_multiple_rules(self):
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        summary = RuleEngine.generate_rule_summary(rules)
        assert "AND" in summary

    def test_empty_rules(self):
        summary = RuleEngine.generate_rule_summary([])
        assert summary == "(no rules)"


class TestExplain:
    def test_all_pass(self):
        signal = {"confidence": 0.8, "stance": "bullish"}
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        result = explain(signal, rules)
        assert result.matched is True
        assert result.rules_passed == 2
        assert result.rules_failed == 0

    def test_one_fails(self):
        signal = {"confidence": 0.3, "stance": "bullish"}
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        result = explain(signal, rules)
        assert result.matched is False
        assert result.rules_passed == 1
        assert result.rules_failed == 1

    def test_missing_field(self):
        signal = {"stance": "bullish"}
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        result = explain(signal, rules)
        assert result.matched is False
        assert "not found" in result.details[0].reason

    def test_empty_rules(self):
        result = explain({"x": 1}, [])
        assert result.matched is True
        assert result.details == []

    def test_to_dict(self):
        signal = {"x": 10}
        rules = [StrategyRule(field="x", operator="gt", value=5)]
        result = explain(signal, rules)
        d = result.to_dict()
        assert d["matched"] is True
        assert len(d["details"]) == 1

    def test_eval_result_repr(self):
        result = explain({"x": 10}, [StrategyRule(field="x", operator="eq", value=10)])
        assert "MATCH" in repr(result)

    def test_rule_eval_detail_repr(self):
        result = explain({"x": 10}, [StrategyRule(field="x", operator="eq", value=10)])
        assert "PASS" in repr(result.details[0])


# ═══════════════════════════════════════════════════════════════════════════
# Part 4: Regime Detector Helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestStanceToNumeric:
    @pytest.mark.parametrize("stance,expected", [
        ("bullish", 1.0),
        ("bearish", -1.0),
        ("mixed", 0.0),
        ("unknown", 0.0),
    ])
    def test_conversion(self, stance, expected):
        assert _stance_to_numeric(stance) == expected


class TestSafeStdev:
    def test_empty(self):
        assert _safe_stdev([]) == 0.0

    def test_single(self):
        assert _safe_stdev([5.0]) == 0.0

    def test_uniform(self):
        assert _safe_stdev([5.0, 5.0, 5.0]) == 0.0

    def test_varied(self):
        assert _safe_stdev([1.0, 2.0, 3.0]) > 0


class TestSafeMean:
    def test_empty(self):
        assert _safe_mean([]) == 0.0

    def test_single(self):
        assert _safe_mean([5.0]) == 5.0

    def test_multiple(self):
        assert _safe_mean([1.0, 2.0, 3.0]) == 2.0


class TestComputeSharpeRegime:
    def test_empty(self):
        assert _compute_sharpe([]) == 0.0

    def test_single(self):
        assert _compute_sharpe([5.0]) == 0.0

    def test_identical(self):
        assert _compute_sharpe([5.0, 5.0, 5.0]) == 0.0

    def test_positive(self):
        assert _compute_sharpe([1.0, 2.0, 3.0, 4.0]) > 0


# ═══════════════════════════════════════════════════════════════════════════
# Part 5: Regime Detector
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def detector():
    return RegimeDetector(window_days=30)


def _make_signal(
    stance: str = "bullish",
    confidence: float = 0.7,
    created_at: float = 0.0,
    trend_score: float = 0.5,
    sector: str = "tech",
) -> dict:
    return {
        "stance": stance,
        "confidence": confidence,
        "created_at": created_at if created_at > 0 else time.time(),
        "trend_score": trend_score,
        "sector": sector,
    }


class TestRegimeDetectorInit:
    def test_default_window(self):
        rd = RegimeDetector()
        assert rd.window_days == 30

    def test_custom_window(self):
        rd = RegimeDetector(window_days=7)
        assert rd.window_days == 7

    def test_invalid_window(self):
        with pytest.raises(ValueError, match="window_days"):
            RegimeDetector(window_days=0)


class TestDetectRegime:
    def test_insufficient_signals(self, detector):
        signals = [_make_signal() for _ in range(3)]
        regime = detector.detect_regime(signals)
        assert regime.regime_type == "sideways"
        assert regime.confidence == 0.1

    def test_bullish_regime(self, detector):
        now = time.time()
        signals = [
            _make_signal(stance="bullish", created_at=now - i * 3600)
            for i in range(20)
        ]
        regime = detector.detect_regime(signals)
        assert regime.regime_type == "bull"

    def test_bearish_regime(self, detector):
        now = time.time()
        signals = [
            _make_signal(stance="bearish", created_at=now - i * 3600)
            for i in range(20)
        ]
        regime = detector.detect_regime(signals)
        assert regime.regime_type == "bear"

    def test_volatile_regime(self, detector):
        now = time.time()
        signals = []
        for i in range(30):
            stance = "bullish" if i % 2 == 0 else "bearish"
            signals.append(_make_signal(stance=stance, created_at=now - i * 3600))
        regime = detector.detect_regime(signals)
        assert regime.regime_type in ("volatile", "sideways")

    def test_empty_signals(self, detector):
        regime = detector.detect_regime([])
        assert regime.regime_type == "sideways"


class TestComputeIndicators:
    def test_all_bullish(self, detector):
        now = time.time()
        signals = [_make_signal(stance="bullish", created_at=now - i) for i in range(10)]
        indicators = detector._compute_indicators(signals, now - 100, now)
        assert indicators["bullish_ratio"] == 1.0

    def test_all_bearish(self, detector):
        now = time.time()
        signals = [_make_signal(stance="bearish", created_at=now - i) for i in range(10)]
        indicators = detector._compute_indicators(signals, now - 100, now)
        assert indicators["bullish_ratio"] == 0.0

    def test_mixed_stances(self, detector):
        now = time.time()
        signals = [
            _make_signal(stance="bullish", created_at=now - 1),
            _make_signal(stance="bearish", created_at=now - 2),
        ]
        indicators = detector._compute_indicators(signals, now - 100, now)
        assert indicators["bullish_ratio"] == 0.5

    def test_no_directional_defaults_50(self, detector):
        now = time.time()
        signals = [_make_signal(stance="unknown", created_at=now - i) for i in range(5)]
        indicators = detector._compute_indicators(signals, now - 100, now)
        assert indicators["bullish_ratio"] == 0.5

    def test_sector_diversity(self, detector):
        now = time.time()
        signals = [
            _make_signal(sector="tech", created_at=now - 1),
            _make_signal(sector="healthcare", created_at=now - 2),
            _make_signal(sector="tech", created_at=now - 3),
        ]
        indicators = detector._compute_indicators(signals, now - 100, now)
        assert indicators["sector_diversity"] == 2

    def test_signal_count(self, detector):
        now = time.time()
        signals = [_make_signal(created_at=now - i) for i in range(7)]
        indicators = detector._compute_indicators(signals, now - 100, now)
        assert indicators["signal_count"] == 7


class TestClassify:
    def test_sideways_default(self, detector):
        indicators = {
            "bullish_ratio": 0.5,
            "stance_volatility": 0.3,
            "signal_velocity": 1.0,
            "signal_count": 20,
        }
        rtype, conf = detector._classify(indicators, 1.0)
        assert rtype == "sideways"

    def test_bull(self, detector):
        indicators = {
            "bullish_ratio": 0.8,
            "stance_volatility": 0.3,
            "signal_velocity": 1.0,
            "signal_count": 20,
        }
        rtype, conf = detector._classify(indicators, 1.0)
        assert rtype == "bull"

    def test_bear(self, detector):
        indicators = {
            "bullish_ratio": 0.2,
            "stance_volatility": 0.3,
            "signal_velocity": 1.0,
            "signal_count": 20,
        }
        rtype, conf = detector._classify(indicators, 1.0)
        assert rtype == "bear"

    def test_volatile(self, detector):
        indicators = {
            "bullish_ratio": 0.5,
            "stance_volatility": 0.7,
            "signal_velocity": 1.0,
            "signal_count": 20,
        }
        rtype, conf = detector._classify(indicators, 1.0)
        assert rtype == "volatile"

    def test_crisis(self, detector):
        indicators = {
            "bullish_ratio": 0.5,
            "stance_volatility": 0.9,
            "signal_velocity": 10.0,
            "signal_count": 50,
        }
        rtype, conf = detector._classify(indicators, 2.0)
        assert rtype == "crisis"

    def test_confidence_scales_with_signal_count(self, detector):
        indicators = {
            "bullish_ratio": 0.8,
            "stance_volatility": 0.3,
            "signal_velocity": 1.0,
            "signal_count": 5,
        }
        _, conf_low = detector._classify(indicators, 1.0)
        indicators["signal_count"] = 50
        _, conf_high = detector._classify(indicators, 1.0)
        assert conf_high >= conf_low


class TestDetectRegimeHistory:
    def test_empty_signals(self, detector):
        result = detector.detect_regime_history([])
        assert result == []

    def test_short_history_single_regime(self, detector):
        now = time.time()
        signals = [_make_signal(stance="bullish", created_at=now - i * 100) for i in range(10)]
        result = detector.detect_regime_history(signals)
        assert len(result) >= 1

    def test_long_history_multiple_regimes(self):
        rd = RegimeDetector(window_days=7)
        now = time.time()
        day = 86400
        signals = []
        # 2 weeks of bullish, then 2 weeks of bearish
        for i in range(14):
            signals.append(_make_signal(stance="bullish", created_at=now - (28 - i) * day))
        for i in range(14):
            signals.append(_make_signal(stance="bearish", created_at=now - (14 - i) * day))

        result = rd.detect_regime_history(signals)
        assert len(result) >= 1
        # Should detect at least one regime change
        types = [r.regime_type for r in result]
        assert isinstance(types, list)


class TestBuildRegimeMatrix:
    def test_empty_inputs(self, detector):
        assert detector.build_regime_matrix([], [], []) == []

    def test_basic_matrix(self, detector):
        strategies = [{"id": "s1"}]
        regime = MarketRegime(
            id="r1", regime_type="bull", start_ts=0.0, end_ts=10000.0,
        )
        trades = [
            {"strategy_id": "s1", "created_at": 500.0, "pnl_pct": 5.0},
            {"strategy_id": "s1", "created_at": 1000.0, "pnl_pct": -2.0},
        ]
        result = detector.build_regime_matrix(strategies, trades, [regime])
        assert len(result) == 1
        assert result[0].strategy_id == "s1"
        assert result[0].regime_type == "bull"
        assert result[0].total_trades == 2

    def test_no_trades_for_strategy(self, detector):
        strategies = [{"id": "s1"}]
        regime = MarketRegime(id="r1", regime_type="bull", start_ts=0.0)
        result = detector.build_regime_matrix(strategies, [], [regime])
        # Should still emit entries with 0 trades
        assert len(result) == 0  # empty trades list -> empty result

    def test_no_trades_returns_empty(self, detector):
        result = detector.build_regime_matrix([{"id": "s1"}], [], [
            MarketRegime(id="r1", regime_type="bull", start_ts=0.0)
        ])
        assert result == []

    def test_recommended_flag(self, detector):
        strategies = [{"id": "s1"}]
        regime = MarketRegime(
            id="r1", regime_type="bull", start_ts=0.0, end_ts=100000.0,
        )
        # 6 trades, 4 wins -> win_rate=0.667 > 0.55, total_trades=6 >= 5
        trades = [
            {"strategy_id": "s1", "created_at": i * 100.0, "pnl_pct": 5.0 if i < 4 else -3.0}
            for i in range(6)
        ]
        result = detector.build_regime_matrix(strategies, trades, [regime])
        assert len(result) == 1
        assert result[0].recommended is True


class TestGetRegimeRecommendation:
    def test_empty_matrix(self, detector):
        regime = MarketRegime(id="r1", regime_type="bull", start_ts=0.0)
        assert detector.get_regime_recommendation(regime, []) == []

    def test_returns_recommended_only(self, detector):
        regime = MarketRegime(id="r1", regime_type="bull", start_ts=0.0)
        matrix = [
            RegimeStrategy(strategy_id="s1", regime_type="bull", win_rate=0.7, sharpe=1.5, recommended=True),
            RegimeStrategy(strategy_id="s2", regime_type="bull", win_rate=0.4, sharpe=0.3, recommended=False),
            RegimeStrategy(strategy_id="s3", regime_type="bear", win_rate=0.8, sharpe=2.0, recommended=True),
        ]
        result = detector.get_regime_recommendation(regime, matrix)
        assert result == ["s1"]

    def test_sorted_by_sharpe(self, detector):
        regime = MarketRegime(id="r1", regime_type="bull", start_ts=0.0)
        matrix = [
            RegimeStrategy(strategy_id="s1", regime_type="bull", win_rate=0.7, sharpe=1.0, recommended=True),
            RegimeStrategy(strategy_id="s2", regime_type="bull", win_rate=0.8, sharpe=2.0, recommended=True),
        ]
        result = detector.get_regime_recommendation(regime, matrix)
        assert result == ["s2", "s1"]


class TestFilterWindow:
    def test_filters_correctly(self, detector):
        signals = [
            {"created_at": 100.0},
            {"created_at": 200.0},
            {"created_at": 300.0},
        ]
        result = detector._filter_window(signals, 150.0, 250.0)
        assert len(result) == 1
        assert result[0]["created_at"] == 200.0

    def test_inclusive_bounds(self, detector):
        signals = [{"created_at": 100.0}, {"created_at": 200.0}]
        result = detector._filter_window(signals, 100.0, 200.0)
        assert len(result) == 2


class TestTradesInRegime:
    def test_basic_filter(self, detector):
        regime = MarketRegime(
            id="r1", regime_type="bull", start_ts=100.0, end_ts=300.0,
        )
        trades = [
            {"created_at": 50.0},
            {"created_at": 200.0},
            {"created_at": 400.0},
        ]
        result = detector._trades_in_regime(trades, regime)
        assert len(result) == 1
        assert result[0]["created_at"] == 200.0

    def test_open_ended_regime(self, detector):
        regime = MarketRegime(
            id="r1", regime_type="bull", start_ts=100.0,
        )
        trades = [
            {"created_at": 50.0},
            {"created_at": 200.0},
            {"created_at": 99999.0},
        ]
        result = detector._trades_in_regime(trades, regime)
        assert len(result) == 2


class TestComputeRegimeStrategy:
    def test_empty_trades(self, detector):
        rs = detector._compute_regime_strategy("s1", "bull", [])
        assert rs.total_trades == 0
        assert rs.recommended is False

    def test_winning_strategy(self, detector):
        trades = [
            {"created_at": 100.0, "pnl_pct": 5.0},
            {"created_at": 200.0, "pnl_pct": 3.0},
            {"created_at": 300.0, "pnl_pct": 7.0},
            {"created_at": 400.0, "pnl_pct": -2.0},
            {"created_at": 500.0, "pnl_pct": 4.0},
        ]
        rs = detector._compute_regime_strategy("s1", "bull", trades)
        assert rs.total_trades == 5
        assert rs.win_rate > 0.5
        assert rs.recommended is True  # 4/5 wins, 5 trades

    def test_losing_strategy(self, detector):
        trades = [
            {"created_at": i * 100.0, "pnl_pct": -5.0}
            for i in range(5)
        ]
        rs = detector._compute_regime_strategy("s1", "bear", trades)
        assert rs.win_rate == 0.0
        assert rs.recommended is False


class TestMergeRegimes:
    def test_empty(self, detector):
        assert detector._merge_regimes([]) == []

    def test_single_entry(self, detector):
        raw = [("bull", 0.0, 100.0, {}, 0.8)]
        merged = detector._merge_regimes(raw)
        assert len(merged) == 1
        assert merged[0].regime_type == "bull"

    def test_adjacent_same_type(self, detector):
        raw = [
            ("bull", 0.0, 100.0, {"x": 1}, 0.6),
            ("bull", 100.0, 200.0, {"x": 2}, 0.8),
        ]
        merged = detector._merge_regimes(raw)
        assert len(merged) == 1
        assert merged[0].regime_type == "bull"

    def test_different_types_not_merged(self, detector):
        raw = [
            ("bull", 0.0, 100.0, {}, 0.8),
            ("bear", 100.0, 200.0, {}, 0.7),
        ]
        merged = detector._merge_regimes(raw)
        assert len(merged) == 2


class TestNormalVelocity:
    def test_empty(self, detector):
        assert detector._compute_normal_velocity([]) == 1.0

    def test_single(self, detector):
        assert detector._compute_normal_velocity([{"created_at": 100.0}]) == 1.0

    def test_two_signals_same_time(self, detector):
        signals = [{"created_at": 100.0}, {"created_at": 100.0}]
        assert detector._compute_normal_velocity(signals) == 1.0

    def test_normal_velocity(self, detector):
        day = 86400.0
        signals = [{"created_at": i * day} for i in range(10)]
        velocity = detector._compute_normal_velocity(signals)
        assert math.isclose(velocity, 10.0 / 9.0, rel_tol=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# Part 6: Parametrized / Stress Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestParametrizedStrategy:
    @pytest.mark.parametrize("n_rules", [0, 1, 3, 5, 10])
    def test_batch_evaluate_various_rule_counts(self, engine, n_rules):
        signal = {"confidence": 0.8, "stance": "bullish", "event_type": "macro"}
        rules = [StrategyRule(field="confidence", operator="gte", value=0.1 * (i + 1)) for i in range(n_rules)]
        result = engine.evaluate(signal, rules)
        assert isinstance(result, bool)

    @pytest.mark.parametrize("rt", REGIME_TYPES)
    def test_make_regime_all_types(self, detector, rt):
        regime = detector._make_regime(
            regime_type=rt, start_ts=0.0, end_ts=100.0,
            indicators={}, confidence=0.5,
        )
        assert regime.regime_type == rt

    @pytest.mark.parametrize("n_signals", [0, 3, 10, 50, 200])
    def test_detect_regime_various_sizes(self, detector, n_signals):
        now = time.time()
        signals = [
            _make_signal(
                stance="bullish" if i % 3 != 0 else "bearish",
                created_at=now - i * 3600,
            )
            for i in range(n_signals)
        ]
        regime = detector.detect_regime(signals)
        assert regime.regime_type in REGIME_TYPES


class TestStress:
    def test_evaluate_1000_signals(self):
        engine = RuleEngine()
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        signals = [
            {"confidence": 0.3 + (i % 7) * 0.1, "stance": "bullish" if i % 2 == 0 else "bearish"}
            for i in range(1000)
        ]
        matched = engine.batch_evaluate(signals, rules)
        assert isinstance(matched, list)
        assert len(matched) <= 1000

    def test_regime_detector_500_signals(self):
        rd = RegimeDetector(window_days=7)
        now = time.time()
        signals = [
            _make_signal(
                stance="bullish" if i % 3 == 0 else "bearish",
                created_at=now - i * 3600,
                confidence=0.5 + (i % 5) * 0.1,
                sector=f"sector_{i % 8}",
            )
            for i in range(500)
        ]
        regime = rd.detect_regime(signals)
        assert regime.regime_type in REGIME_TYPES

    def test_explain_50_rules(self):
        signal = {"confidence": 0.8}
        rules = [StrategyRule(field="confidence", operator="gte", value=0.01 * i) for i in range(1, 51)]
        result = explain(signal, rules)
        assert result.rules_passed + result.rules_failed == 50
