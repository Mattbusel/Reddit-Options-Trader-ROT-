"""Rule evaluation engine for the Strategy Builder.

Evaluates signal dicts against a list of ``StrategyRule`` objects.  Rules use
AND logic: *all* rules must match for a signal to pass.  Supports seven
comparison operators (``gt``, ``lt``, ``gte``, ``lte``, ``eq``, ``neq``,
``in``) and dot-notation field paths for traversing nested signal dicts
(e.g. ``"meta.nlp.sentiment.polarity"``).

Typical usage::

    from rot.strategy.rules import RuleEngine
    from rot.strategy.types import StrategyRule

    engine = RuleEngine()
    rules = [
        StrategyRule(field="confidence", operator="gte", value=0.5),
        StrategyRule(field="stance", operator="eq", value="bullish"),
    ]
    signal = {"confidence": 0.72, "stance": "bullish", "ticker": "AAPL"}
    assert engine.evaluate(signal, rules) is True

    # Batch filter
    signals = [signal, {"confidence": 0.3, "stance": "bearish", "ticker": "TSLA"}]
    matched = engine.batch_evaluate(signals, rules)
    assert len(matched) == 1
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from rot.strategy.types import RULE_OPERATORS, StrategyRule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CompiledRule — pre-parsed for fast evaluation
# ---------------------------------------------------------------------------


_OPERATOR_LABELS: dict[str, str] = {
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
    "eq": "=",
    "neq": "!=",
    "in": "in",
}
"""Human-readable symbols for each operator."""


@dataclass(frozen=True, slots=True)
class CompiledRule:
    """A pre-compiled version of a :class:`StrategyRule`.

    Splitting the field path at compile time avoids repeated ``str.split``
    on every evaluation call.

    Attributes:
        field_parts: The field path already split on ``"."``.
        operator: One of :data:`~rot.strategy.types.RULE_OPERATORS`.
        value: The target comparison value.
        raw_field: The original unsplit field string (kept for logging /
            summary generation).
    """

    field_parts: list[str]
    operator: str
    value: Any
    raw_field: str


# ---------------------------------------------------------------------------
# Sentinel for missing keys
# ---------------------------------------------------------------------------

class _Missing:
    """Sentinel singleton for ``_get_nested_value`` to distinguish a genuinely
    ``None`` value from a missing key."""

    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


# ---------------------------------------------------------------------------
# RuleEngine
# ---------------------------------------------------------------------------

class RuleEngine:
    """Stateless engine that evaluates signal dicts against strategy rules.

    All public methods are safe to call from any thread; the engine holds no
    mutable state.
    """

    # ------------------------------------------------------------------
    # Compilation
    # ------------------------------------------------------------------

    @staticmethod
    def compile_rules(rules: list[StrategyRule]) -> list[CompiledRule]:
        """Pre-compile a list of :class:`StrategyRule` for fast evaluation.

        Each rule's field path is split on ``"."`` so that nested dict
        traversal does not need to re-split on every signal.  The operator
        is validated against :data:`RULE_OPERATORS`.

        Args:
            rules: Strategy rules to compile.

        Returns:
            A list of :class:`CompiledRule` in the same order.

        Raises:
            ValueError: If any rule contains an invalid operator or an empty
                field path.
        """

        compiled: list[CompiledRule] = []
        for rule in rules:
            # Validate operator (StrategyRule.__post_init__ already checks,
            # but we guard against hand-built dicts sneaking past).
            if rule.operator not in RULE_OPERATORS:
                raise ValueError(
                    f"Unknown operator '{rule.operator}'; "
                    f"expected one of {RULE_OPERATORS}"
                )

            parts = rule.field.split(".")
            if not parts or any(p == "" for p in parts):
                raise ValueError(
                    f"Invalid field path '{rule.field}': "
                    "must be a non-empty dot-separated path"
                )

            compiled.append(
                CompiledRule(
                    field_parts=parts,
                    operator=rule.operator,
                    value=rule.value,
                    raw_field=rule.field,
                )
            )

        return compiled

    # ------------------------------------------------------------------
    # Single-signal evaluation
    # ------------------------------------------------------------------

    def evaluate(self, signal: dict, rules: list[StrategyRule]) -> bool:
        """Return ``True`` if *signal* matches **all** *rules* (AND logic).

        This is the convenience entry-point that compiles rules on every call.
        For hot loops prefer :meth:`evaluate_compiled`.

        Args:
            signal: A signal dict (typically a row from the signals table
                with parsed JSON blobs such as ``event_data``, ``market_data``
                etc. already expanded).
            rules: Strategy rules to check.

        Returns:
            ``True`` if every rule matches, ``False`` otherwise.
            An empty rule list is trivially ``True`` (no constraints).
        """

        if not rules:
            return True

        compiled = self.compile_rules(rules)
        return self.evaluate_compiled(signal, compiled)

    def evaluate_compiled(
        self, signal: dict, compiled: list[CompiledRule]
    ) -> bool:
        """Return ``True`` if *signal* matches **all** pre-compiled rules.

        Faster than :meth:`evaluate` when the same rule set is applied to
        many signals (avoids repeated compilation).

        Args:
            signal: A signal dict.
            compiled: Pre-compiled rules from :meth:`compile_rules`.

        Returns:
            ``True`` if every compiled rule matches.
        """

        if not compiled:
            return True

        for cr in compiled:
            value = self._get_nested_value(signal, cr.field_parts)

            # If the field is missing the signal cannot satisfy the rule.
            if value is MISSING:
                logger.debug(
                    "Field '%s' missing from signal — rule fails",
                    cr.raw_field,
                )
                return False

            if not self._compare(value, cr.operator, cr.value):
                return False

        return True

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def batch_evaluate(
        self,
        signals: list[dict],
        rules: list[StrategyRule],
    ) -> list[dict]:
        """Filter *signals*, returning only those matching **all** *rules*.

        Rules are compiled once and reused for every signal.

        Args:
            signals: List of signal dicts to filter.
            rules: Strategy rules to apply.

        Returns:
            A (possibly empty) list of signal dicts that passed all rules.
        """

        if not rules:
            return list(signals)

        compiled = self.compile_rules(rules)

        matched: list[dict] = []
        for sig in signals:
            if self.evaluate_compiled(sig, compiled):
                matched.append(sig)

        logger.debug(
            "batch_evaluate: %d / %d signals matched %d rules",
            len(matched),
            len(signals),
            len(compiled),
        )
        return matched

    # ------------------------------------------------------------------
    # Human-readable summary
    # ------------------------------------------------------------------

    @staticmethod
    def generate_rule_summary(rules: list[StrategyRule]) -> str:
        """Return a human-readable summary of *rules*.

        Each rule is rendered as ``field <op> value`` and joined with
        `` AND ``.

        Examples::

            >>> RuleEngine.generate_rule_summary([
            ...     StrategyRule(field="confidence", operator="gte", value=0.5),
            ...     StrategyRule(field="stance", operator="eq", value="bullish"),
            ... ])
            'confidence >= 0.5 AND stance = bullish'

            >>> RuleEngine.generate_rule_summary([])
            '(no rules)'

        Args:
            rules: The rules to summarise.

        Returns:
            A single-line string.
        """

        if not rules:
            return "(no rules)"

        parts: list[str] = []
        for rule in rules:
            op_label = _OPERATOR_LABELS.get(rule.operator, rule.operator)
            value_str = _format_value(rule.value)
            parts.append(f"{rule.field} {op_label} {value_str}")

        return " AND ".join(parts)

    # ------------------------------------------------------------------
    # Nested field access
    # ------------------------------------------------------------------

    @staticmethod
    def _get_nested_value(signal: dict, field_parts: list[str]) -> Any:
        """Traverse *signal* using the pre-split *field_parts*.

        Supports nested dicts only (not lists).  If any intermediate key is
        missing or the intermediate value is not a dict, returns
        :data:`MISSING`.

        This method also accepts a plain ``str`` for *field_parts* for
        backward compatibility with callers that pass unsplit paths; in
        that case it will split internally.

        Args:
            signal: The signal dict.
            field_parts: Already-split field path (e.g. ``["meta", "nlp",
                "sentiment", "polarity"]``).

        Returns:
            The resolved value, or :data:`MISSING` if the path does not
            exist.
        """

        # Accept a plain string for convenience / safety.
        if isinstance(field_parts, str):
            field_parts = field_parts.split(".")

        current: Any = signal
        for part in field_parts:
            if not isinstance(current, dict):
                return MISSING
            if part not in current:
                return MISSING
            current = current[part]

        return current

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    @staticmethod
    def _compare(value: Any, operator: str, target: Any) -> bool:
        """Apply a comparison *operator* between *value* and *target*.

        Operator semantics:

        ``gt`` / ``lt`` / ``gte`` / ``lte``
            Numeric comparison.  Returns ``False`` if either operand is not
            a number (``int`` or ``float``).

        ``eq``
            Exact equality (``==``).

        ``neq``
            Not equal (``!=``).

        ``in``
            If *target* is a list (or tuple/set), checks ``value in target``.
            If *target* is a string, checks ``target in str(value)``
            (substring match on the signal value).
            If *value* is a list, checks for any overlap between *value*
            and *target* (when *target* is also a list).
            Returns ``False`` for other type combinations.

        Args:
            value: The value extracted from the signal.
            operator: One of :data:`RULE_OPERATORS`.
            target: The target value from the rule.

        Returns:
            ``True`` if the comparison holds, ``False`` otherwise.
        """

        # --- numeric operators -------------------------------------------
        if operator == "gt":
            return _is_numeric(value) and _is_numeric(target) and value > target

        if operator == "lt":
            return _is_numeric(value) and _is_numeric(target) and value < target

        if operator == "gte":
            return _is_numeric(value) and _is_numeric(target) and value >= target

        if operator == "lte":
            return _is_numeric(value) and _is_numeric(target) and value <= target

        # --- equality ----------------------------------------------------
        if operator == "eq":
            return value == target

        if operator == "neq":
            return value != target

        # --- containment ------------------------------------------------
        if operator == "in":
            return _check_in(value, target)

        # Unknown operator — shouldn't happen after compile validation.
        logger.warning("Unknown operator '%s' — treating as non-match", operator)
        return False


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _is_numeric(v: Any) -> bool:
    """Return ``True`` if *v* is an ``int`` or ``float`` (but not ``bool``)."""
    # ``bool`` is a subclass of ``int`` in Python; we exclude it so that
    # ``True``/``False`` are not silently treated as ``1``/``0``.
    if isinstance(v, bool):
        return False
    return isinstance(v, (int, float))


def _check_in(value: Any, target: Any) -> bool:
    """Implement the ``in`` operator with flexible type handling.

    Priority:

    1. If *target* is a collection (list / tuple / set / frozenset):
       a. If *value* is also a list/tuple/set, check for **any** overlap
          (i.e. non-empty intersection).
       b. Otherwise check ``value in target``.

    2. If *target* is a string, check ``target in str(value)``
       (substring search — useful for e.g. checking if a subreddit
       name appears within a longer source string).

    3. Any other type combination returns ``False``.
    """

    if isinstance(target, (list, tuple, set, frozenset)):
        # value is itself a collection — check intersection
        if isinstance(value, (list, tuple, set, frozenset)):
            target_set = set(target)
            return bool(target_set.intersection(value))
        # scalar value — membership test
        return value in target

    if isinstance(target, str):
        # Substring check: is the target string *in* the stringified value?
        return target in str(value)

    # Fallback: cannot determine containment.
    logger.debug(
        "in operator: unsupported target type %s for value %r",
        type(target).__name__,
        value,
    )
    return False


def _format_value(v: Any) -> str:
    """Format a rule value for :meth:`RuleEngine.generate_rule_summary`.

    * Strings are shown in double quotes.
    * Lists are shown as ``[a, b, c]``.
    * Everything else uses ``str()``.
    """

    if isinstance(v, str):
        return f'"{v}"'

    if isinstance(v, (list, tuple)):
        inner = ", ".join(_format_value(item) for item in v)
        return f"[{inner}]"

    return str(v)


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def compile_rules(rules: list[StrategyRule]) -> list[CompiledRule]:
    """Module-level shortcut for :meth:`RuleEngine.compile_rules`.

    Useful for callers that want to compile once without instantiating the
    full engine::

        from rot.strategy.rules import compile_rules
        compiled = compile_rules(my_rules)
    """

    return RuleEngine.compile_rules(rules)


# ---------------------------------------------------------------------------
# Explain helpers — why did a signal match or not?
# ---------------------------------------------------------------------------

class RuleEvalDetail:
    """Diagnostic detail for a single rule evaluation.

    Attributes:
        rule: The original strategy rule.
        field: The field path that was inspected.
        extracted_value: The value found in the signal (or :data:`MISSING`).
        target_value: The comparison target from the rule.
        operator: The operator used.
        matched: Whether the rule matched.
        reason: Human-readable explanation.
    """

    __slots__ = (
        "rule",
        "field",
        "extracted_value",
        "target_value",
        "operator",
        "matched",
        "reason",
    )

    def __init__(
        self,
        rule: StrategyRule,
        extracted_value: Any,
        matched: bool,
        reason: str,
    ) -> None:
        self.rule = rule
        self.field = rule.field
        self.extracted_value = extracted_value
        self.target_value = rule.value
        self.operator = rule.operator
        self.matched = matched
        self.reason = reason

    def __repr__(self) -> str:
        status = "PASS" if self.matched else "FAIL"
        return (
            f"<RuleEvalDetail {status}: {self.field} "
            f"{_OPERATOR_LABELS.get(self.operator, self.operator)} "
            f"{_format_value(self.target_value)} "
            f"(actual={self.extracted_value!r})>"
        )

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "operator": self.operator,
            "target_value": self.target_value,
            "extracted_value": (
                None if self.extracted_value is MISSING else self.extracted_value
            ),
            "matched": self.matched,
            "reason": self.reason,
        }


class EvalResult:
    """Full evaluation result with per-rule details.

    Attributes:
        matched: Whether the signal passed all rules.
        details: Per-rule diagnostic details.
        rules_passed: Count of rules that matched.
        rules_failed: Count of rules that did not match.
    """

    __slots__ = ("matched", "details", "rules_passed", "rules_failed")

    def __init__(
        self,
        matched: bool,
        details: list[RuleEvalDetail],
    ) -> None:
        self.matched = matched
        self.details = details
        self.rules_passed = sum(1 for d in details if d.matched)
        self.rules_failed = sum(1 for d in details if not d.matched)

    def __repr__(self) -> str:
        status = "MATCH" if self.matched else "NO MATCH"
        return (
            f"<EvalResult {status}: "
            f"{self.rules_passed} passed, {self.rules_failed} failed>"
        )

    def to_dict(self) -> dict:
        return {
            "matched": self.matched,
            "rules_passed": self.rules_passed,
            "rules_failed": self.rules_failed,
            "details": [d.to_dict() for d in self.details],
        }


def explain(
    signal: dict,
    rules: list[StrategyRule],
) -> EvalResult:
    """Evaluate *signal* against *rules* and return diagnostic details.

    Unlike :meth:`RuleEngine.evaluate`, this function does **not**
    short-circuit on the first failing rule.  It evaluates every rule so
    that the caller gets a complete picture of which rules passed, which
    failed, and why.

    Args:
        signal: A signal dict.
        rules: Strategy rules to check.

    Returns:
        An :class:`EvalResult` with per-rule diagnostics.
    """

    engine = RuleEngine()

    if not rules:
        return EvalResult(matched=True, details=[])

    compiled = engine.compile_rules(rules)
    details: list[RuleEvalDetail] = []
    all_matched = True

    for rule, cr in zip(rules, compiled):
        extracted = engine._get_nested_value(signal, cr.field_parts)

        if extracted is MISSING:
            details.append(
                RuleEvalDetail(
                    rule=rule,
                    extracted_value=MISSING,
                    matched=False,
                    reason=f"Field '{rule.field}' not found in signal",
                )
            )
            all_matched = False
            continue

        passed = engine._compare(extracted, cr.operator, cr.value)
        op_label = _OPERATOR_LABELS.get(rule.operator, rule.operator)

        if passed:
            reason = (
                f"{rule.field} = {extracted!r} "
                f"{op_label} {_format_value(rule.value)} => PASS"
            )
        else:
            reason = (
                f"{rule.field} = {extracted!r} "
                f"{op_label} {_format_value(rule.value)} => FAIL"
            )

        details.append(
            RuleEvalDetail(
                rule=rule,
                extracted_value=extracted,
                matched=passed,
                reason=reason,
            )
        )

        if not passed:
            all_matched = False

    return EvalResult(matched=all_matched, details=details)
