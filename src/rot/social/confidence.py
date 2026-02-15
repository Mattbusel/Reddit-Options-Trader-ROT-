"""Author-based confidence adjustment for the Social Intelligence Network.

Pipeline Stage 6 plugin that boosts or penalizes signal confidence based on
the track record of the signal's author.  High-accuracy, reputable authors
get a confidence boost; consistently wrong or low-reputation authors get a
penalty.  The adjustment is bounded by configurable limits and requires a
minimum number of decided predictions before it activates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from rot.social.types import AuthorProfile


# ── Configuration ────────────────────────────────────────────────────────────


@dataclass
class ConfidenceAdjusterConfig:
    """Tuning knobs for author-based confidence adjustment.

    Attributes:
        max_boost:                  Maximum positive adjustment applied to
                                    confidence (e.g. 0.15 means +15pp at most).
        max_penalty:                Maximum negative adjustment magnitude
                                    (applied as a negative value).
        min_predictions_to_adjust:  Minimum decided (win + loss) predictions
                                    before any adjustment kicks in.
        accuracy_neutral_point:     Accuracy at which no adjustment is made.
                                    Authors above this are boosted, below are
                                    penalized.
        reputation_weight:          Weight given to reputation-based component
                                    in the combined score.
        accuracy_weight:            Weight given to accuracy-based component
                                    in the combined score.
        enabled:                    Master switch — set to False to disable
                                    all adjustments (always returns 0.0).
    """

    max_boost: float = 0.15
    max_penalty: float = 0.15
    min_predictions_to_adjust: int = 10
    accuracy_neutral_point: float = 0.50
    reputation_weight: float = 0.6
    accuracy_weight: float = 0.4
    enabled: bool = True


# ── Adjuster ─────────────────────────────────────────────────────────────────


class AuthorConfidenceAdjuster:
    """Adjusts signal confidence based on author track record.

    Maintains an in-memory cache of ``AuthorProfile`` objects keyed by
    ``author_id``.  The cache is populated externally — either in bulk via
    ``update_cache()`` (periodic DB refresh) or one-at-a-time via
    ``set_profile()``.

    The adjustment formula combines two signals:

    * **Accuracy score** — how far the author's accuracy diverges from the
      neutral point (default 50 %).
    * **Reputation score** — the author's reputation score normalised from
      the [0, 100] range to [-1, 1].

    The two are combined with configurable weights, clamped to [-1, 1], then
    scaled to [−max_penalty, +max_boost].
    """

    def __init__(self, config: Optional[ConfidenceAdjusterConfig] = None) -> None:
        self._config = config or ConfidenceAdjusterConfig()
        self._profile_cache: Dict[str, AuthorProfile] = {}

    # ── Cache management ─────────────────────────────────────────────────

    def update_cache(self, profiles: List[AuthorProfile]) -> None:
        """Bulk-update the profile cache.

        Typically called on a timer from a background loop that queries
        the database for author profiles.
        """
        for profile in profiles:
            self._profile_cache[profile.id] = profile

    def set_profile(self, profile: AuthorProfile) -> None:
        """Insert or update a single profile in the cache."""
        self._profile_cache[profile.id] = profile

    def get_cached_profile_count(self) -> int:
        """Return the number of profiles currently in the cache."""
        return len(self._profile_cache)

    def clear_cache(self) -> None:
        """Discard all cached profiles."""
        self._profile_cache.clear()

    # ── Core adjustment logic ────────────────────────────────────────────

    def get_adjustment(self, author_id: str) -> float:
        """Compute the confidence adjustment for *author_id*.

        Returns a value in ``[-max_penalty, +max_boost]``.  Positive values
        mean the author's track record warrants a confidence boost; negative
        values mean a penalty.

        Returns ``0.0`` when:
        * The adjuster is disabled.
        * The author is not in the cache.
        * The author has fewer than ``min_predictions_to_adjust`` decided
          predictions.
        """
        if not self._config.enabled:
            return 0.0

        profile = self._profile_cache.get(author_id)
        if profile is None:
            return 0.0

        if profile.decided_count < self._config.min_predictions_to_adjust:
            return 0.0

        # --- Accuracy component -------------------------------------------
        accuracy = profile.accuracy
        if accuracy is None:
            accuracy = profile.computed_accuracy
        if accuracy is None:
            accuracy = self._config.accuracy_neutral_point  # neutral fallback

        neutral = self._config.accuracy_neutral_point
        if accuracy >= neutral:
            # Scale [neutral, 1.0] → [0, 1]
            denom = 1.0 - neutral
            accuracy_score = (accuracy - neutral) / denom if denom > 0 else 0.0
        else:
            # Scale [0, neutral] → [-1, 0]
            accuracy_score = (accuracy - neutral) / neutral if neutral > 0 else 0.0

        # --- Reputation component ----------------------------------------
        if profile.reputation_score is not None:
            # reputation_score lives in [0, 100]; normalise to [-1, 1]
            reputation_score = (profile.reputation_score - 50.0) / 50.0
        else:
            reputation_score = 0.0

        # --- Combine & scale ---------------------------------------------
        combined = (
            self._config.accuracy_weight * accuracy_score
            + self._config.reputation_weight * reputation_score
        )
        combined = max(-1.0, min(1.0, combined))

        if combined >= 0:
            adjustment = combined * self._config.max_boost
        else:
            adjustment = combined * self._config.max_penalty

        return adjustment

    def adjust_confidence(
        self, author_id: str, current_confidence: float
    ) -> tuple[float, float]:
        """Apply author-based adjustment to *current_confidence*.

        Returns a ``(new_confidence, adjustment_applied)`` tuple.  The
        resulting confidence is clamped to ``[0.05, 1.0]`` to match the
        clamping convention used elsewhere in the pipeline.
        """
        adjustment = self.get_adjustment(author_id)
        new_confidence = current_confidence + adjustment
        new_confidence = max(0.05, min(1.0, new_confidence))
        return new_confidence, adjustment

    # ── Diagnostics ──────────────────────────────────────────────────────

    def get_adjustment_explanation(self, author_id: str) -> Dict[str, Any]:
        """Return a human-readable explanation of the adjustment for *author_id*.

        Useful for audit trails and the signal-detail UI.
        """
        if not self._config.enabled:
            return {
                "author_id": author_id,
                "has_profile": author_id in self._profile_cache,
                "decided_count": 0,
                "accuracy": None,
                "reputation": None,
                "adjustment": 0.0,
                "reason": "disabled",
            }

        profile = self._profile_cache.get(author_id)
        if profile is None:
            return {
                "author_id": author_id,
                "has_profile": False,
                "decided_count": 0,
                "accuracy": None,
                "reputation": None,
                "adjustment": 0.0,
                "reason": "no_profile",
            }

        decided = profile.decided_count
        accuracy = profile.accuracy if profile.accuracy is not None else profile.computed_accuracy
        reputation = profile.reputation_score

        if decided < self._config.min_predictions_to_adjust:
            return {
                "author_id": author_id,
                "has_profile": True,
                "decided_count": decided,
                "accuracy": accuracy,
                "reputation": reputation,
                "adjustment": 0.0,
                "reason": "insufficient_data",
            }

        adjustment = self.get_adjustment(author_id)

        if adjustment > 0:
            reason = "boosted_high_accuracy"
        elif adjustment < 0:
            reason = "penalized_low_accuracy"
        else:
            reason = "neutral"

        return {
            "author_id": author_id,
            "has_profile": True,
            "decided_count": decided,
            "accuracy": accuracy,
            "reputation": reputation,
            "adjustment": round(adjustment, 6),
            "reason": reason,
        }
