"""Adaptive signal suppression based on historical feedback.

Called during the pipeline AFTER credibility scoring, BEFORE LLM reasoning.
Suppresses event categories with historically poor win rates to save LLM
API costs and improve overall signal accuracy.

Suppressed signals are still emitted (with ``meta["suppressed"]=True``)
but skip LLM reasoning and trade building.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, Optional, Tuple

from rot.core.types import Event

log = logging.getLogger(__name__)


class SignalSuppressor:
    """Decides whether to suppress a signal based on historical feedback.

    Usage::

        suppressor = SignalSuppressor(analyzer, threshold=0.20)
        event, was_suppressed = suppressor.apply(event)
        if was_suppressed:
            # skip LLM reasoning, emit with stub
    """

    def __init__(
        self,
        analyzer: Any,
        threshold: float = 0.20,
        source_threshold: float = 0.15,
        min_signals: int = 30,
        enabled: bool = True,
    ) -> None:
        self.analyzer = analyzer
        self.threshold = threshold
        self.source_threshold = source_threshold
        self.min_signals = min_signals
        self.enabled = enabled

    def should_suppress(self, event: Event) -> Tuple[bool, str]:
        """Check whether this event should be suppressed.

        Returns ``(should_suppress, reason_string)``.
        Never suppresses if disabled, or if no analysis is available yet.
        """
        if not self.enabled:
            return False, ""

        results = self.analyzer.get_cached_results()
        if not results:
            return False, ""

        candidates = results.get("suppression_candidates", [])
        if not candidates:
            return False, ""

        event_type = event.event_type or "unknown"
        meta = event.meta or {}
        subreddit = meta.get("subreddit", "") or ""
        # Normalise for RSS items that store source as subreddit
        if not subreddit and event.evidence:
            subreddit = (event.evidence[0].subreddit or "").lower()

        # Check category-level suppression
        for c in candidates:
            if c["level"] == "category" and c["event_type"] == event_type:
                reason = (
                    f"category_low_win_rate: {event_type} "
                    f"win_rate={c['win_rate']:.1f}% "
                    f"({c['decided']} decided signals)"
                )
                log.info("Suppressing signal: %s", reason)
                return True, reason

        # Check source-level suppression
        for c in candidates:
            if (
                c["level"] == "source"
                and c["event_type"] == event_type
                and c["source"]
                and c["source"].lower() == subreddit.lower()
            ):
                reason = (
                    f"source_low_win_rate: {event_type}+{subreddit} "
                    f"win_rate={c['win_rate']:.1f}% "
                    f"({c['decided']} decided signals)"
                )
                log.info("Suppressing signal: %s", reason)
                return True, reason

        # Check low-confidence + historically poor event type
        # (looser match: any category candidate for this event_type + confidence < 0.3)
        if event.confidence < 0.3:
            for c in candidates:
                if c["event_type"] == event_type:
                    reason = (
                        f"low_confidence_poor_category: confidence={event.confidence:.2f} "
                        f"+ {event_type} win_rate={c['win_rate']:.1f}%"
                    )
                    log.info("Suppressing signal: %s", reason)
                    return True, reason

        return False, ""

    def apply(self, event: Event) -> Tuple[Event, bool]:
        """Apply suppression check and annotate the event if suppressed.

        Returns ``(event, was_suppressed)``.  If suppressed, the returned
        event has ``meta["suppressed"]=True`` and ``meta["suppression_reason"]``
        set.  The original event is unchanged if not suppressed.
        """
        suppress, reason = self.should_suppress(event)
        if not suppress:
            return event, False

        meta = dict(event.meta) if event.meta else {}
        meta["suppressed"] = True
        meta["suppression_reason"] = reason
        return dataclasses.replace(event, meta=meta), True
