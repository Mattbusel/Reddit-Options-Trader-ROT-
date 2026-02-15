from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

from rot.core.types import ReasoningPacket

log = logging.getLogger(__name__)

# Valid values for typed fields
_VALID_EVENT_TYPES = {"earnings_rumor", "product_news", "regulatory", "squeeze_chatter", "macro", "other"}
_VALID_STANCES = {"bullish", "bearish", "mixed", "unknown"}
_VALID_HORIZONS = {"intraday", "1w", "earnings", "longer", "unknown"}


def _extract_json(text: str) -> Dict[str, Any]:
    """Extract JSON from LLM response, handling markdown fencing."""
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass  # Intentionally suppressed

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass  # Intentionally suppressed

    # Try finding first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass  # Intentionally suppressed

    raise ValueError(f"Could not extract valid JSON from LLM response: {text[:200]}")


def parse_reasoning_response(raw_text: str, entities: list[str]) -> ReasoningPacket:
    """Parse LLM JSON response into a ReasoningPacket."""
    try:
        data = _extract_json(raw_text)
    except ValueError as e:
        log.warning("Failed to parse LLM response: %s", e)
        return _fallback_packet(entities, raw_text, str(e))

    # Validate and coerce typed fields
    event_type = data.get("event_type", "other")
    if event_type not in _VALID_EVENT_TYPES:
        event_type = "other"

    stance = data.get("stance", "unknown")
    if stance not in _VALID_STANCES:
        stance = "unknown"

    horizon = data.get("time_horizon", "unknown")
    if horizon not in _VALID_HORIZONS:
        horizon = "unknown"

    confidence = data.get("confidence", 0.3)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.3

    return ReasoningPacket(
        thesis=str(data.get("thesis", f"LLM analysis for {', '.join(entities)}")),
        catalyst_window=str(data.get("catalyst_window", "unknown")),
        market_expectation=str(data.get("market_expectation", "unclear")),
        invalidations=_ensure_str_list(data.get("invalidations", [])),
        recommended_structures=_ensure_str_list(data.get("recommended_structures", [])),
        risk_notes=_ensure_str_list(data.get("risk_notes", [])),
        raw={
            "llm_response": data,
            "event_type": event_type,
            "stance": stance,
            "time_horizon": horizon,
            "confidence": confidence,
        },
    )


def _ensure_str_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x) for x in val]
    if isinstance(val, str):
        return [val]
    return []


def _fallback_packet(entities: list[str], raw_text: str, error: str) -> ReasoningPacket:
    return ReasoningPacket(
        thesis=f"Reddit chatter mentions {', '.join(entities)}; LLM parse failed.",
        catalyst_window="unknown",
        market_expectation="unclear",
        invalidations=["LLM response could not be parsed"],
        recommended_structures=[],
        risk_notes=["Do not trade - reasoning unavailable"],
        raw={"error": error, "raw_text": raw_text[:1000]},
    )
