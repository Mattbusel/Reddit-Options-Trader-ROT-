"""Temporal analyzer for the ROT NLP engine.

Detects tense (past/present/future), actionability, urgency,
and time expressions in financial text.
"""
from __future__ import annotations

import re
from typing import Dict, List

from rot.nlp.types import TemporalResult, Tense, Token


# ── Tense marker patterns ──

# Past tense: explicit past words + common financial past-tense verbs
_PAST_MARKERS = re.compile(
    r"\b(?:"
    r"crashed|tanked|dropped|fell|plunged|collapsed|dumped|sold|"
    r"reported|missed|beat|was|were|had|went|did|"
    r"closed|traded|gained|lost|declined|recovered|bounced|"
    r"rallied|surged|sank|dipped|soared|plummeted|"
    r"announced|released|filed|approved|rejected|"
    r"last\s+(?:week|month|quarter|year|friday|monday|tuesday|wednesday|thursday)"
    r")\b",
    re.I,
)

# Present tense: -ing forms + present indicators
_PRESENT_MARKERS = re.compile(
    r"\b(?:"
    r"crashing|tanking|dropping|falling|plunging|collapsing|dumping|"
    r"selling|buying|holding|running|trading|moving|"
    r"rising|surging|pumping|ripping|drilling|bleeding|"
    r"mooning|printing|squeezing|breaking|bouncing|"
    r"is|are|am|currently|right now|today|"
    r"this morning|this afternoon|as we speak"
    r")\b",
    re.I,
)

# Future tense: will, going to, predictions
_FUTURE_MARKERS = re.compile(
    r"\b(?:"
    r"will|gonna|going to|about to|expected to|"
    r"should|predicted|forecast|expecting|anticipating|"
    r"tomorrow|next\s+(?:week|month|quarter|year|friday|monday)|"
    r"by\s+(?:friday|eod|eow|end of|close|tomorrow)|"
    r"upcoming|soon|eventually"
    r")\b",
    re.I,
)

# Time expression patterns
_TIME_EXPRESSIONS = [
    # Relative time
    re.compile(r"\b(?:today|tomorrow|yesterday|tonight)\b", re.I),
    re.compile(r"\b(?:this|next|last)\s+(?:week|month|quarter|year|friday|monday|tuesday|wednesday|thursday)\b", re.I),
    re.compile(r"\bby\s+(?:eod|eow|friday|close|tomorrow|end of (?:week|month|day|year))\b", re.I),
    # Duration
    re.compile(r"\bin\s+\d+\s+(?:hours?|days?|weeks?|months?|minutes?)\b", re.I),
    re.compile(r"\bwithin\s+(?:a|the|this)?\s*(?:hour|day|week|month)\b", re.I),
    # Event-relative
    re.compile(r"\b(?:before|after|pre|post)[- ]?(?:earnings|market|open|close|split|fomc|cpi|meeting)\b", re.I),
    # Calendar
    re.compile(r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b", re.I),
    re.compile(r"\b(?:q[1-4]|h[12])\s*(?:\d{2,4})?\b", re.I),
    # Specific dates
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),
]

# Urgency patterns
_HIGH_URGENCY = re.compile(
    r"\b(?:right now|immediately|urgent|asap|before close today|0dte|0DTE|"
    r"expiring today|expires today|act now|hurry|time sensitive|breaking)\b",
    re.I,
)
_MEDIUM_URGENCY = re.compile(
    r"\b(?:this week|by friday|before earnings|soon|shortly|"
    r"weeklies|weekly|expiring friday|FDs?|fd)\b",
    re.I,
)


class TemporalAnalyzer:
    """Detects tense, actionability, urgency, and time expressions."""

    def analyze(self, tokens: List[Token], full_text: str) -> TemporalResult:
        """Analyze temporal aspects of text."""
        # Count tense signals
        tense_signals: Dict[str, int] = {"past": 0, "present": 0, "future": 0}

        tense_signals["past"] = len(_PAST_MARKERS.findall(full_text))
        tense_signals["present"] = len(_PRESENT_MARKERS.findall(full_text))
        tense_signals["future"] = len(_FUTURE_MARKERS.findall(full_text))

        # Determine dominant tense
        dominant_tense = self._dominant_tense(tense_signals)

        # Extract time expressions
        time_exprs: List[str] = []
        seen: set[str] = set()
        for pattern in _TIME_EXPRESSIONS:
            for m in pattern.finditer(full_text):
                expr = m.group().strip()
                if expr.lower() not in seen:
                    time_exprs.append(expr)
                    seen.add(expr.lower())

        # Actionability scoring
        actionability = self._score_actionability(dominant_tense, tense_signals)

        # Urgency scoring
        urgency = self._score_urgency(full_text)

        return TemporalResult(
            dominant_tense=dominant_tense,
            actionability=actionability,
            urgency=urgency,
            time_expressions=time_exprs,
            tense_signals=tense_signals,
        )

    @staticmethod
    def _dominant_tense(signals: Dict[str, int]) -> Tense:
        """Determine dominant tense from signal counts."""
        total = sum(signals.values())
        if total == 0:
            return "unknown"

        # Find highest count
        max_tense = max(signals, key=lambda k: signals[k])
        max_count = signals[max_tense]

        # Need at least a slight majority or clear winner
        if max_count == 0:
            return "unknown"

        return max_tense  # type: ignore[return-value]

    @staticmethod
    def _score_actionability(dominant: Tense, signals: Dict[str, int]) -> float:
        """Score how actionable the text is based on tense.

        Past events = low (0.1-0.3)
        Present events = high (0.7-1.0)
        Future predictions = medium (0.4-0.6)
        Unknown = neutral (0.5)
        """
        total = sum(signals.values())
        if total == 0:
            return 0.5

        # Weighted score
        present_ratio = signals.get("present", 0) / max(total, 1)
        future_ratio = signals.get("future", 0) / max(total, 1)
        past_ratio = signals.get("past", 0) / max(total, 1)

        score = (
            present_ratio * 0.9
            + future_ratio * 0.5
            + past_ratio * 0.15
        )

        # Normalize to 0-1 range
        return max(0.05, min(1.0, score))

    @staticmethod
    def _score_urgency(full_text: str) -> float:
        """Score urgency level from 0.0 to 1.0."""
        score = 0.0

        high_matches = len(_HIGH_URGENCY.findall(full_text))
        medium_matches = len(_MEDIUM_URGENCY.findall(full_text))

        if high_matches > 0:
            score += min(0.9, 0.6 + 0.15 * high_matches)
        if medium_matches > 0:
            score += min(0.5, 0.25 + 0.1 * medium_matches)

        return min(1.0, score)
