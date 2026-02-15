"""ML-based credibility scorer with heuristic fallback.

Loads a trained scikit-learn model, predicts P(win) from signal features, and
uses that as the event confidence.  If no model is available or inference fails
for any reason, the existing heuristic ``CredibilityScorer`` is used silently.
"""

from __future__ import annotations

import dataclasses
import logging
import pickle
from pathlib import Path
from typing import Any, Optional

from rot.core.types import Event
from rot.credibility.scorer import CredibilityScorer
from rot.credibility.features import (
    FEATURE_NAMES,
    NUM_FEATURES,
    extract_features_from_event,
)

log = logging.getLogger(__name__)


class MLCredibilityScorer:
    """ML-based credibility scorer that wraps the heuristic as fallback."""

    def __init__(
        self,
        model_path: str = "",
        enabled: bool = True,
    ) -> None:
        self._heuristic = CredibilityScorer()
        self._model: Any = None
        self._enabled = enabled
        self._model_path = model_path
        self._load_failed = False

        if enabled and model_path:
            self._try_load(model_path)

    # ── Model lifecycle ────────────────────────────────────────────────

    def _try_load(self, path: str) -> None:
        """Load model from disk.  On failure, log a warning and stay in
        heuristic-only mode."""
        try:
            p = Path(path)
            if not p.is_file():
                log.info(
                    "ML model not found at %s — using heuristic (will train when data available)",
                    path,
                )
                return
            with open(p, "rb") as f:
                # Safe pickle usage - loading from trusted local file created by our training code
                self._model = pickle.load(f)  # nosec B301 - trusted local file only
            log.info("ML credibility model loaded from %s", path)
        except Exception as exc:
            log.warning(
                "ML credibility model load failed (%s) — using heuristic fallback",
                exc,
            )
            self._model = None
            self._load_failed = True

    def reload(self, path: Optional[str] = None) -> bool:
        """Hot-reload the model from disk (called after retraining).

        Returns True if a model was successfully loaded.
        """
        target = path or self._model_path
        if not target:
            return False
        self._try_load(target)
        if path:
            self._model_path = target
        return self._model is not None

    @property
    def ml_available(self) -> bool:
        return self._model is not None and self._enabled

    # ── Scoring ────────────────────────────────────────────────────────

    def score(self, event: Event) -> Event:
        """Score an event.  ML if available, heuristic otherwise.

        The heuristic is *always* run so its breakdown is available in meta
        for comparison and as a ready fallback.
        """
        heuristic_result = self._heuristic.score(event)

        if not self.ml_available:
            return heuristic_result

        try:
            return self._score_ml(event, heuristic_result)
        except Exception as exc:
            log.warning(
                "ML scoring failed for %s: %s — using heuristic",
                event.entities,
                exc,
            )
            return heuristic_result

    def _score_ml(self, event: Event, heuristic_result: Event) -> Event:
        """Run ML inference and return a scored Event."""
        features = extract_features_from_event(event)
        if len(features) != NUM_FEATURES:
            raise ValueError(f"Expected {NUM_FEATURES} features, got {len(features)}")

        # sklearn expects 2-D array
        proba = self._model.predict_proba([features])[0]
        # proba is [P(loss), P(win)] for a binary classifier with classes [0, 1]
        ml_confidence = float(proba[1])

        # Clamp: never 0% or 100% certain
        ml_confidence = max(0.05, min(0.95, ml_confidence))

        # Build enriched meta with both scores for A/B monitoring
        heuristic_meta = heuristic_result.meta or {}
        new_meta = dict(event.meta or {})
        new_meta["credibility_breakdown"] = heuristic_meta.get(
            "credibility_breakdown", {}
        )
        new_meta["credibility_adjustment"] = heuristic_meta.get(
            "credibility_adjustment", 0.0
        )
        new_meta["ml_credibility"] = {
            "ml_confidence": round(ml_confidence, 4),
            "heuristic_confidence": round(heuristic_result.confidence, 4),
            "model_path": self._model_path,
        }

        return dataclasses.replace(event, confidence=ml_confidence, meta=new_meta)
