"""Tests for the Strategy Builder RuleEngine.

Tests rule compilation, evaluation, batch filtering, and all 7 operators.
"""

from __future__ import annotations

import pytest

from rot.strategy.rules import (
    MISSING,
    CompiledRule,
    EvalResult,
    RuleEngine,
    RuleEvalDetail,
    compile_rules,
    explain,
)
from rot.strategy.types import StrategyRule


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> RuleEngine:
    """A fresh RuleEngine instance."""
    return RuleEngine()


@pytest.fixture
def signal_basic() -> dict:
    """A basic signal dict with flat fields."""
    return {
        "confidence": 0.7,
        "stance": "bullish",
        "event_type": "earnings_rumor",
        "ticker": "AAPL",
        "trend_score": 0.3,
        "quality_score": 0.85,
        "subreddit": "wallstreetbets",
        "strategy": "debit_spread",
    }


@pytest.fixture
def signal_nested() -> dict:
    """A signal with nested metadata."""
    return {
        "confidence": 0.5,
        "ticker": "TSLA",
        "stance": "bearish",
        "meta": {
            "nlp": {
                "sentiment": {
                    "polarity": 0.8,
                    "conviction": 0.9,
                },
                "sarcasm_probability": 0.0,
            },
            "trend": {
                "score": 0.45,
            },
        },
    }


@pytest.fixture
def signal_with_lists() -> dict:
    """A signal with list fields for 'in' operator tests."""
    return {
        "ticker": "NVDA",
        "tickers": ["NVDA", "AMD", "INTC"],
        "event_types": ["product_news", "earnings_rumor"],
        "subreddit": "stocks-and-options",
    }


# ---------------------------------------------------------------------------
# CompiledRule Tests
# ---------------------------------------------------------------------------


class TestCompiledRule:
    """Test CompiledRule dataclass creation."""

    def test_compiled_rule_creation(self):
        """CompiledRule can be created with split field path."""
        cr = CompiledRule(
            field_parts=["meta", "nlp", "sentiment", "polarity"],
            operator="gte",
            value=0.5,
            raw_field="meta.nlp.sentiment.polarity",
        )
        assert cr.field_parts == ["meta", "nlp", "sentiment", "polarity"]
        assert cr.operator == "gte"
        assert cr.value == 0.5
        assert cr.raw_field == "meta.nlp.sentiment.polarity"

    def test_compiled_rule_frozen(self):
        """CompiledRule is frozen (immutable)."""
        cr = CompiledRule(
            field_parts=["confidence"],
            operator="gt",
            value=0.6,
            raw_field="confidence",
        )
        with pytest.raises(AttributeError):
            cr.operator = "lt"  # type: ignore


# ---------------------------------------------------------------------------
# compile_rules Tests
# ---------------------------------------------------------------------------


class TestCompileRules:
    """Test rule compilation and validation."""

    def test_compile_single_rule(self):
        """Compile a single simple rule."""
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        compiled = compile_rules(rules)

        assert len(compiled) == 1
        assert compiled[0].field_parts == ["confidence"]
        assert compiled[0].operator == "gte"
        assert compiled[0].value == 0.5
        assert compiled[0].raw_field == "confidence"

    def test_compile_nested_field(self):
        """Compile a rule with nested field path."""
        rules = [
            StrategyRule(
                field="meta.nlp.sentiment.polarity",
                operator="gt",
                value=0.7,
            )
        ]
        compiled = compile_rules(rules)

        assert len(compiled) == 1
        assert compiled[0].field_parts == ["meta", "nlp", "sentiment", "polarity"]
        assert compiled[0].raw_field == "meta.nlp.sentiment.polarity"

    def test_compile_multiple_rules(self):
        """Compile multiple rules at once."""
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
            StrategyRule(field="meta.nlp.conviction", operator="gt", value=0.6),
        ]
        compiled = compile_rules(rules)

        assert len(compiled) == 3
        assert compiled[0].field_parts == ["confidence"]
        assert compiled[1].field_parts == ["stance"]
        assert compiled[2].field_parts == ["meta", "nlp", "conviction"]

    def test_compile_invalid_operator(self):
        """Raise ValueError on unknown operator at construction time."""
        with pytest.raises(ValueError, match="operator must be one of"):
            StrategyRule(field="confidence", operator="unknown", value=0.5)

    def test_compile_empty_field(self):
        """Raise ValueError on empty field path at construction time."""
        with pytest.raises(ValueError, match="field must be a non-empty string"):
            StrategyRule(field="", operator="eq", value=1)

    def test_compile_field_with_empty_part(self):
        """Raise ValueError on field with empty component."""
        rules = [StrategyRule(field="meta..nlp", operator="eq", value=1)]
        with pytest.raises(ValueError, match="Invalid field path"):
            compile_rules(rules)

    def test_compile_empty_rules_list(self):
        """Compiling empty rules list returns empty compiled list."""
        compiled = compile_rules([])
        assert compiled == []


# ---------------------------------------------------------------------------
# Operator Tests — All 7 Operators
# ---------------------------------------------------------------------------


class TestOperatorGt:
    """Test 'gt' (greater than) operator."""

    def test_gt_true(self, engine: RuleEngine):
        """gt returns True when signal value > target."""
        signal = {"confidence": 0.8}
        rules = [StrategyRule(field="confidence", operator="gt", value=0.5)]
        assert engine.evaluate(signal, rules) is True

    def test_gt_false_equal(self, engine: RuleEngine):
        """gt returns False when signal value == target."""
        signal = {"confidence": 0.5}
        rules = [StrategyRule(field="confidence", operator="gt", value=0.5)]
        assert engine.evaluate(signal, rules) is False

    def test_gt_false_less(self, engine: RuleEngine):
        """gt returns False when signal value < target."""
        signal = {"confidence": 0.3}
        rules = [StrategyRule(field="confidence", operator="gt", value=0.5)]
        assert engine.evaluate(signal, rules) is False

    def test_gt_non_numeric_value(self, engine: RuleEngine):
        """gt returns False when signal value is not numeric."""
        signal = {"stance": "bullish"}
        rules = [StrategyRule(field="stance", operator="gt", value=0.5)]
        assert engine.evaluate(signal, rules) is False

    def test_gt_non_numeric_target(self, engine: RuleEngine):
        """gt returns False when target is not numeric."""
        signal = {"confidence": 0.7}
        rules = [StrategyRule(field="confidence", operator="gt", value="high")]
        assert engine.evaluate(signal, rules) is False

    def test_gt_bool_excluded(self, engine: RuleEngine):
        """gt returns False when value is bool (not treated as numeric)."""
        signal = {"flag": True}
        rules = [StrategyRule(field="flag", operator="gt", value=0)]
        assert engine.evaluate(signal, rules) is False


class TestOperatorLt:
    """Test 'lt' (less than) operator."""

    def test_lt_true(self, engine: RuleEngine):
        """lt returns True when signal value < target."""
        signal = {"confidence": 0.3}
        rules = [StrategyRule(field="confidence", operator="lt", value=0.5)]
        assert engine.evaluate(signal, rules) is True

    def test_lt_false_equal(self, engine: RuleEngine):
        """lt returns False when signal value == target."""
        signal = {"confidence": 0.5}
        rules = [StrategyRule(field="confidence", operator="lt", value=0.5)]
        assert engine.evaluate(signal, rules) is False

    def test_lt_false_greater(self, engine: RuleEngine):
        """lt returns False when signal value > target."""
        signal = {"confidence": 0.8}
        rules = [StrategyRule(field="confidence", operator="lt", value=0.5)]
        assert engine.evaluate(signal, rules) is False


class TestOperatorGte:
    """Test 'gte' (greater than or equal) operator."""

    def test_gte_true_greater(self, engine: RuleEngine):
        """gte returns True when signal value > target."""
        signal = {"confidence": 0.8}
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        assert engine.evaluate(signal, rules) is True

    def test_gte_true_equal(self, engine: RuleEngine):
        """gte returns True when signal value == target."""
        signal = {"confidence": 0.5}
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        assert engine.evaluate(signal, rules) is True

    def test_gte_false(self, engine: RuleEngine):
        """gte returns False when signal value < target."""
        signal = {"confidence": 0.3}
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        assert engine.evaluate(signal, rules) is False


class TestOperatorLte:
    """Test 'lte' (less than or equal) operator."""

    def test_lte_true_less(self, engine: RuleEngine):
        """lte returns True when signal value < target."""
        signal = {"confidence": 0.3}
        rules = [StrategyRule(field="confidence", operator="lte", value=0.5)]
        assert engine.evaluate(signal, rules) is True

    def test_lte_true_equal(self, engine: RuleEngine):
        """lte returns True when signal value == target."""
        signal = {"confidence": 0.5}
        rules = [StrategyRule(field="confidence", operator="lte", value=0.5)]
        assert engine.evaluate(signal, rules) is True

    def test_lte_false(self, engine: RuleEngine):
        """lte returns False when signal value > target."""
        signal = {"confidence": 0.8}
        rules = [StrategyRule(field="confidence", operator="lte", value=0.5)]
        assert engine.evaluate(signal, rules) is False


class TestOperatorEq:
    """Test 'eq' (equality) operator."""

    def test_eq_true_string(self, engine: RuleEngine):
        """eq returns True when strings match."""
        signal = {"stance": "bullish"}
        rules = [StrategyRule(field="stance", operator="eq", value="bullish")]
        assert engine.evaluate(signal, rules) is True

    def test_eq_false_string(self, engine: RuleEngine):
        """eq returns False when strings don't match."""
        signal = {"stance": "bullish"}
        rules = [StrategyRule(field="stance", operator="eq", value="bearish")]
        assert engine.evaluate(signal, rules) is False

    def test_eq_true_number(self, engine: RuleEngine):
        """eq returns True when numbers match."""
        signal = {"confidence": 0.7}
        rules = [StrategyRule(field="confidence", operator="eq", value=0.7)]
        assert engine.evaluate(signal, rules) is True

    def test_eq_false_number(self, engine: RuleEngine):
        """eq returns False when numbers don't match."""
        signal = {"confidence": 0.7}
        rules = [StrategyRule(field="confidence", operator="eq", value=0.5)]
        assert engine.evaluate(signal, rules) is False

    def test_eq_none_vs_none(self, engine: RuleEngine):
        """eq returns True when both value and target are None."""
        signal = {"optional_field": None}
        rules = [StrategyRule(field="optional_field", operator="eq", value=None)]
        assert engine.evaluate(signal, rules) is True


class TestOperatorNeq:
    """Test 'neq' (not equal) operator."""

    def test_neq_true(self, engine: RuleEngine):
        """neq returns True when values differ."""
        signal = {"stance": "bullish"}
        rules = [StrategyRule(field="stance", operator="neq", value="bearish")]
        assert engine.evaluate(signal, rules) is True

    def test_neq_false(self, engine: RuleEngine):
        """neq returns False when values match."""
        signal = {"stance": "bullish"}
        rules = [StrategyRule(field="stance", operator="neq", value="bullish")]
        assert engine.evaluate(signal, rules) is False


class TestOperatorIn:
    """Test 'in' (containment) operator."""

    def test_in_value_in_list(self, engine: RuleEngine):
        """in returns True when value is in target list."""
        signal = {"stance": "bullish"}
        rules = [
            StrategyRule(
                field="stance",
                operator="in",
                value=["bullish", "bearish"],
            )
        ]
        assert engine.evaluate(signal, rules) is True

    def test_in_value_not_in_list(self, engine: RuleEngine):
        """in returns False when value not in target list."""
        signal = {"stance": "mixed"}
        rules = [
            StrategyRule(
                field="stance",
                operator="in",
                value=["bullish", "bearish"],
            )
        ]
        assert engine.evaluate(signal, rules) is False

    def test_in_substring_match(self, engine: RuleEngine):
        """in checks substring when target is a string."""
        signal = {"subreddit": "wallstreetbets"}
        rules = [StrategyRule(field="subreddit", operator="in", value="street")]
        assert engine.evaluate(signal, rules) is True

    def test_in_substring_no_match(self, engine: RuleEngine):
        """in returns False when substring not found."""
        signal = {"subreddit": "wallstreetbets"}
        rules = [StrategyRule(field="subreddit", operator="in", value="stocks")]
        assert engine.evaluate(signal, rules) is False

    def test_in_list_overlap(self, signal_with_lists: dict, engine: RuleEngine):
        """in checks for overlap when both value and target are lists."""
        signal = signal_with_lists
        rules = [
            StrategyRule(
                field="tickers",
                operator="in",
                value=["NVDA", "TSLA"],
            )
        ]
        # signal.tickers = ["NVDA", "AMD", "INTC"]
        # rule.value = ["NVDA", "TSLA"]
        # intersection = ["NVDA"] => True
        assert engine.evaluate(signal, rules) is True

    def test_in_list_no_overlap(self, signal_with_lists: dict, engine: RuleEngine):
        """in returns False when lists have no overlap."""
        signal = signal_with_lists
        rules = [
            StrategyRule(
                field="tickers",
                operator="in",
                value=["TSLA", "AAPL"],
            )
        ]
        # signal.tickers = ["NVDA", "AMD", "INTC"]
        # no overlap
        assert engine.evaluate(signal, rules) is False

    def test_in_with_tuple(self, engine: RuleEngine):
        """in works with tuple as target."""
        signal = {"stance": "bullish"}
        rules = [
            StrategyRule(
                field="stance",
                operator="in",
                value=("bullish", "bearish"),
            )
        ]
        assert engine.evaluate(signal, rules) is True

    def test_in_with_set(self, engine: RuleEngine):
        """in works with set as target."""
        signal = {"stance": "bullish"}
        rules = [
            StrategyRule(
                field="stance",
                operator="in",
                value={"bullish", "bearish"},
            )
        ]
        assert engine.evaluate(signal, rules) is True


# ---------------------------------------------------------------------------
# Nested Field Access Tests
# ---------------------------------------------------------------------------


class TestNestedFieldAccess:
    """Test dot-notation nested field path traversal."""

    def test_nested_field_found(self, signal_nested: dict, engine: RuleEngine):
        """Nested field is correctly extracted."""
        rules = [
            StrategyRule(
                field="meta.nlp.sentiment.polarity",
                operator="gte",
                value=0.5,
            )
        ]
        # signal.meta.nlp.sentiment.polarity = 0.8
        assert engine.evaluate(signal_nested, rules) is True

    def test_nested_field_deep(self, signal_nested: dict, engine: RuleEngine):
        """Multiple levels of nesting work."""
        rules = [
            StrategyRule(
                field="meta.nlp.sentiment.conviction",
                operator="gt",
                value=0.8,
            )
        ]
        # signal.meta.nlp.sentiment.conviction = 0.9
        assert engine.evaluate(signal_nested, rules) is True

    def test_nested_field_missing_intermediate(
        self, signal_nested: dict, engine: RuleEngine
    ):
        """Missing intermediate key returns False."""
        rules = [
            StrategyRule(
                field="meta.nonexistent.sentiment.polarity",
                operator="gte",
                value=0.5,
            )
        ]
        assert engine.evaluate(signal_nested, rules) is False

    def test_nested_field_missing_leaf(self, signal_nested: dict, engine: RuleEngine):
        """Missing leaf key returns False."""
        rules = [
            StrategyRule(
                field="meta.nlp.sentiment.missing_key",
                operator="gte",
                value=0.5,
            )
        ]
        assert engine.evaluate(signal_nested, rules) is False

    def test_nested_intermediate_not_dict(
        self, signal_nested: dict, engine: RuleEngine
    ):
        """Traversal stops if intermediate value is not a dict."""
        # signal.confidence = 0.5 (a float, not a dict)
        rules = [
            StrategyRule(
                field="confidence.foo.bar",
                operator="eq",
                value=1,
            )
        ]
        assert engine.evaluate(signal_nested, rules) is False

    def test_get_nested_value_with_string(self, engine: RuleEngine):
        """_get_nested_value accepts string field path for convenience."""
        signal = {"meta": {"nlp": {"polarity": 0.9}}}
        value = engine._get_nested_value(signal, "meta.nlp.polarity")
        assert value == 0.9

    def test_get_nested_value_with_list(self, engine: RuleEngine):
        """_get_nested_value accepts pre-split list."""
        signal = {"meta": {"nlp": {"polarity": 0.9}}}
        value = engine._get_nested_value(signal, ["meta", "nlp", "polarity"])
        assert value == 0.9

    def test_get_nested_value_missing(self, engine: RuleEngine):
        """_get_nested_value returns MISSING when path not found."""
        signal = {"meta": {"nlp": {}}}
        value = engine._get_nested_value(signal, ["meta", "nlp", "polarity"])
        assert value is MISSING


# ---------------------------------------------------------------------------
# Missing Fields Tests
# ---------------------------------------------------------------------------


class TestMissingFields:
    """Test behavior when signal fields are missing."""

    def test_missing_field_returns_false(self, signal_basic: dict, engine: RuleEngine):
        """Rule fails when field is missing from signal."""
        rules = [
            StrategyRule(field="nonexistent_field", operator="gte", value=0.5)
        ]
        assert engine.evaluate(signal_basic, rules) is False

    def test_none_value_vs_missing(self, engine: RuleEngine):
        """None value is different from MISSING."""
        signal = {"optional_field": None}
        # This rule should match because the field exists and is None
        rules = [StrategyRule(field="optional_field", operator="eq", value=None)]
        assert engine.evaluate(signal, rules) is True

        # This rule fails because the field doesn't exist
        rules2 = [StrategyRule(field="missing_field", operator="eq", value=None)]
        assert engine.evaluate(signal, rules2) is False

    def test_missing_bool_representation(self):
        """MISSING has bool(MISSING) == False."""
        assert bool(MISSING) is False

    def test_missing_repr(self):
        """MISSING has readable repr."""
        assert repr(MISSING) == "<MISSING>"

    def test_missing_is_singleton(self):
        """MISSING is a singleton."""
        from rot.strategy.rules import _Missing

        m1 = _Missing()
        m2 = _Missing()
        assert m1 is m2
        assert m1 is MISSING


# ---------------------------------------------------------------------------
# evaluate Tests (Single Signal)
# ---------------------------------------------------------------------------


class TestEvaluate:
    """Test single-signal evaluation."""

    def test_evaluate_single_rule_pass(self, signal_basic: dict, engine: RuleEngine):
        """Single rule that matches returns True."""
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        # signal.confidence = 0.7
        assert engine.evaluate(signal_basic, rules) is True

    def test_evaluate_single_rule_fail(self, signal_basic: dict, engine: RuleEngine):
        """Single rule that doesn't match returns False."""
        rules = [StrategyRule(field="confidence", operator="lt", value=0.5)]
        # signal.confidence = 0.7
        assert engine.evaluate(signal_basic, rules) is False

    def test_evaluate_multiple_rules_all_pass(
        self, signal_basic: dict, engine: RuleEngine
    ):
        """All rules pass returns True (AND logic)."""
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
            StrategyRule(field="trend_score", operator="gt", value=0.2),
        ]
        assert engine.evaluate(signal_basic, rules) is True

    def test_evaluate_multiple_rules_some_fail(
        self, signal_basic: dict, engine: RuleEngine
    ):
        """One failing rule returns False (AND logic)."""
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bearish"),  # fails
            StrategyRule(field="trend_score", operator="gt", value=0.2),
        ]
        assert engine.evaluate(signal_basic, rules) is False

    def test_evaluate_empty_rules_list(self, signal_basic: dict, engine: RuleEngine):
        """Empty rules list matches all (no constraints)."""
        assert engine.evaluate(signal_basic, []) is True

    def test_evaluate_complex_nested(self, signal_nested: dict, engine: RuleEngine):
        """Complex nested rules work correctly."""
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.4),
            StrategyRule(
                field="meta.nlp.sentiment.polarity",
                operator="gt",
                value=0.7,
            ),
            StrategyRule(
                field="meta.nlp.sentiment.conviction",
                operator="gte",
                value=0.8,
            ),
        ]
        assert engine.evaluate(signal_nested, rules) is True


# ---------------------------------------------------------------------------
# evaluate_compiled Tests
# ---------------------------------------------------------------------------


class TestEvaluateCompiled:
    """Test evaluation with pre-compiled rules."""

    def test_evaluate_compiled_single_rule(
        self, signal_basic: dict, engine: RuleEngine
    ):
        """Compiled single rule evaluation works."""
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        compiled = engine.compile_rules(rules)
        assert engine.evaluate_compiled(signal_basic, compiled) is True

    def test_evaluate_compiled_multiple_rules(
        self, signal_basic: dict, engine: RuleEngine
    ):
        """Compiled multiple rules work."""
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        compiled = engine.compile_rules(rules)
        assert engine.evaluate_compiled(signal_basic, compiled) is True

    def test_evaluate_compiled_empty_list(
        self, signal_basic: dict, engine: RuleEngine
    ):
        """Empty compiled list returns True."""
        assert engine.evaluate_compiled(signal_basic, []) is True

    def test_evaluate_compiled_reuse(self, engine: RuleEngine):
        """Compiled rules can be reused across multiple signals."""
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        compiled = engine.compile_rules(rules)

        sig1 = {"confidence": 0.7, "stance": "bullish"}
        sig2 = {"confidence": 0.8, "stance": "bullish"}
        sig3 = {"confidence": 0.3, "stance": "bullish"}

        assert engine.evaluate_compiled(sig1, compiled) is True
        assert engine.evaluate_compiled(sig2, compiled) is True
        assert engine.evaluate_compiled(sig3, compiled) is False


# ---------------------------------------------------------------------------
# batch_evaluate Tests
# ---------------------------------------------------------------------------


class TestBatchEvaluate:
    """Test batch signal filtering."""

    def test_batch_evaluate_all_pass(self, engine: RuleEngine):
        """All signals pass rules."""
        signals = [
            {"confidence": 0.7, "stance": "bullish"},
            {"confidence": 0.8, "stance": "bullish"},
            {"confidence": 0.9, "stance": "bullish"},
        ]
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        matched = engine.batch_evaluate(signals, rules)
        assert len(matched) == 3
        assert matched == signals

    def test_batch_evaluate_some_pass(self, engine: RuleEngine):
        """Some signals pass, some fail."""
        signals = [
            {"confidence": 0.7, "stance": "bullish"},
            {"confidence": 0.3, "stance": "bullish"},  # fails confidence
            {"confidence": 0.8, "stance": "bearish"},  # fails stance
            {"confidence": 0.9, "stance": "bullish"},
        ]
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        matched = engine.batch_evaluate(signals, rules)
        assert len(matched) == 2
        assert matched == [signals[0], signals[3]]

    def test_batch_evaluate_none_pass(self, engine: RuleEngine):
        """No signals pass rules."""
        signals = [
            {"confidence": 0.3, "stance": "bearish"},
            {"confidence": 0.2, "stance": "mixed"},
        ]
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        matched = engine.batch_evaluate(signals, rules)
        assert len(matched) == 0

    def test_batch_evaluate_empty_rules(self, engine: RuleEngine):
        """Empty rules match all signals."""
        signals = [
            {"confidence": 0.7},
            {"confidence": 0.3},
        ]
        matched = engine.batch_evaluate(signals, [])
        assert len(matched) == 2
        assert matched == signals

    def test_batch_evaluate_empty_signals(self, engine: RuleEngine):
        """Empty signals list returns empty list."""
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        matched = engine.batch_evaluate([], rules)
        assert matched == []


# ---------------------------------------------------------------------------
# generate_rule_summary Tests
# ---------------------------------------------------------------------------


class TestGenerateRuleSummary:
    """Test human-readable rule summary generation."""

    def test_summary_single_rule(self, engine: RuleEngine):
        """Single rule generates correct summary."""
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        summary = engine.generate_rule_summary(rules)
        assert summary == "confidence >= 0.5"

    def test_summary_multiple_rules(self, engine: RuleEngine):
        """Multiple rules joined with AND."""
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
            StrategyRule(field="trend_score", operator="gt", value=0.3),
        ]
        summary = engine.generate_rule_summary(rules)
        assert summary == 'confidence >= 0.5 AND stance = "bullish" AND trend_score > 0.3'

    def test_summary_all_operators(self, engine: RuleEngine):
        """All 7 operators render correctly."""
        rules = [
            StrategyRule(field="a", operator="gt", value=1),
            StrategyRule(field="b", operator="lt", value=2),
            StrategyRule(field="c", operator="gte", value=3),
            StrategyRule(field="d", operator="lte", value=4),
            StrategyRule(field="e", operator="eq", value="foo"),
            StrategyRule(field="f", operator="neq", value="bar"),
            StrategyRule(field="g", operator="in", value=["x", "y"]),
        ]
        summary = engine.generate_rule_summary(rules)
        assert (
            summary == 'a > 1 AND b < 2 AND c >= 3 AND d <= 4 AND '
            'e = "foo" AND f != "bar" AND g in ["x", "y"]'
        )

    def test_summary_empty_rules(self, engine: RuleEngine):
        """Empty rules returns special message."""
        summary = engine.generate_rule_summary([])
        assert summary == "(no rules)"

    def test_summary_nested_field(self, engine: RuleEngine):
        """Nested field path preserved in summary."""
        rules = [
            StrategyRule(
                field="meta.nlp.sentiment.polarity",
                operator="gte",
                value=0.7,
            )
        ]
        summary = engine.generate_rule_summary(rules)
        assert summary == "meta.nlp.sentiment.polarity >= 0.7"

    def test_summary_list_value(self, engine: RuleEngine):
        """List values formatted correctly."""
        rules = [
            StrategyRule(
                field="stance",
                operator="in",
                value=["bullish", "bearish"],
            )
        ]
        summary = engine.generate_rule_summary(rules)
        assert summary == 'stance in ["bullish", "bearish"]'


# ---------------------------------------------------------------------------
# explain Function Tests
# ---------------------------------------------------------------------------


class TestExplain:
    """Test the explain() diagnostic function."""

    def test_explain_all_pass(self, signal_basic: dict):
        """Explain returns MATCH when all rules pass."""
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bullish"),
        ]
        result = explain(signal_basic, rules)

        assert result.matched is True
        assert result.rules_passed == 2
        assert result.rules_failed == 0
        assert len(result.details) == 2

    def test_explain_some_fail(self, signal_basic: dict):
        """Explain returns NO MATCH when some rules fail."""
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
            StrategyRule(field="stance", operator="eq", value="bearish"),  # fails
        ]
        result = explain(signal_basic, rules)

        assert result.matched is False
        assert result.rules_passed == 1
        assert result.rules_failed == 1
        assert len(result.details) == 2

        # Check detail for failing rule
        fail_detail = result.details[1]
        assert fail_detail.matched is False
        assert fail_detail.field == "stance"
        assert fail_detail.extracted_value == "bullish"
        assert fail_detail.target_value == "bearish"

    def test_explain_missing_field(self, signal_basic: dict):
        """Explain reports missing field in detail."""
        rules = [
            StrategyRule(field="nonexistent", operator="gte", value=0.5),
        ]
        result = explain(signal_basic, rules)

        assert result.matched is False
        assert result.rules_failed == 1

        detail = result.details[0]
        assert detail.matched is False
        assert detail.extracted_value is MISSING
        assert "not found" in detail.reason

    def test_explain_empty_rules(self, signal_basic: dict):
        """Explain with empty rules returns matched=True."""
        result = explain(signal_basic, [])
        assert result.matched is True
        assert len(result.details) == 0

    def test_explain_to_dict(self, signal_basic: dict):
        """EvalResult.to_dict() serializes correctly."""
        rules = [
            StrategyRule(field="confidence", operator="gte", value=0.5),
        ]
        result = explain(signal_basic, rules)
        d = result.to_dict()

        assert d["matched"] is True
        assert d["rules_passed"] == 1
        assert d["rules_failed"] == 0
        assert len(d["details"]) == 1
        assert d["details"][0]["field"] == "confidence"
        assert d["details"][0]["matched"] is True

    def test_explain_detail_repr(self, signal_basic: dict):
        """RuleEvalDetail has readable repr."""
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        result = explain(signal_basic, rules)
        detail = result.details[0]

        repr_str = repr(detail)
        assert "PASS" in repr_str
        assert "confidence" in repr_str
        assert ">=" in repr_str

    def test_eval_result_repr(self, signal_basic: dict):
        """EvalResult has readable repr."""
        rules = [StrategyRule(field="confidence", operator="gte", value=0.5)]
        result = explain(signal_basic, rules)

        repr_str = repr(result)
        assert "MATCH" in repr_str
        assert "1 passed" in repr_str
        assert "0 failed" in repr_str


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    def test_none_value_with_eq(self, engine: RuleEngine):
        """None value can be compared with eq."""
        signal = {"optional": None}
        rules = [StrategyRule(field="optional", operator="eq", value=None)]
        assert engine.evaluate(signal, rules) is True

    def test_zero_vs_none(self, engine: RuleEngine):
        """0 is different from None."""
        signal = {"value": 0}
        rules = [StrategyRule(field="value", operator="eq", value=None)]
        assert engine.evaluate(signal, rules) is False

    def test_empty_string_vs_missing(self, engine: RuleEngine):
        """Empty string is different from missing field."""
        signal = {"name": ""}
        rules = [StrategyRule(field="name", operator="eq", value="")]
        assert engine.evaluate(signal, rules) is True

        rules2 = [StrategyRule(field="missing", operator="eq", value="")]
        assert engine.evaluate(signal, rules2) is False

    def test_negative_numbers(self, engine: RuleEngine):
        """Negative numbers work with numeric operators."""
        signal = {"value": -5}
        rules = [StrategyRule(field="value", operator="lt", value=0)]
        assert engine.evaluate(signal, rules) is True

    def test_float_precision(self, engine: RuleEngine):
        """Float comparison works with expected precision."""
        signal = {"value": 0.1 + 0.2}  # classic float issue
        rules = [StrategyRule(field="value", operator="gte", value=0.3)]
        assert engine.evaluate(signal, rules) is True

    def test_in_operator_empty_list(self, engine: RuleEngine):
        """in operator with empty list target returns False."""
        signal = {"stance": "bullish"}
        rules = [StrategyRule(field="stance", operator="in", value=[])]
        assert engine.evaluate(signal, rules) is False

    def test_in_operator_value_is_empty_list(self, engine: RuleEngine):
        """in operator when signal value is empty list."""
        signal = {"tickers": []}
        rules = [StrategyRule(field="tickers", operator="in", value=["AAPL"])]
        # empty list has no overlap with target
        assert engine.evaluate(signal, rules) is False

    def test_string_number_comparison(self, engine: RuleEngine):
        """String "5" is not > 3 (type safety)."""
        signal = {"value": "5"}
        rules = [StrategyRule(field="value", operator="gt", value=3)]
        assert engine.evaluate(signal, rules) is False

    def test_deeply_nested_path(self, engine: RuleEngine):
        """Very deep nesting works."""
        signal = {
            "a": {"b": {"c": {"d": {"e": {"f": {"g": 42}}}}}}
        }
        rules = [
            StrategyRule(field="a.b.c.d.e.f.g", operator="eq", value=42)
        ]
        assert engine.evaluate(signal, rules) is True
