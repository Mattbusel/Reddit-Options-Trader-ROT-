"""AuthorTracker — manages author profiles and prediction tracking.

Tracks author predictions (bullish/bearish calls), resolves them against
actual price moves, computes accuracy/ROI/Sharpe/reputation, and produces
leaderboards.  All state is held in-memory with import/export helpers for
DB persistence.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

from rot.social.types import (
    AuthorPrediction,
    AuthorProfile,
    OUTCOMES,
    PLATFORMS,
    STANCES,
)


# ── Configuration ────────────────────────────────────────────────────────────


@dataclass
class AuthorTrackerConfig:
    """Tuning knobs for the AuthorTracker.

    Attributes:
        min_predictions_for_score: Minimum decided predictions before
            computing accuracy and reputation scores.  Below this
            threshold the profile returns ``None`` for computed stats.
        resolution_window_hours: How many hours to wait after a
            prediction is recorded before it becomes eligible for
            resolution.
        max_pnl_pct: Absolute cap on ``pnl_pct`` to prevent outlier
            penny-stock moves from dominating aggregates.
    """

    min_predictions_for_score: int = 10
    resolution_window_hours: int = 24
    max_pnl_pct: float = 50.0


# ── Helpers ──────────────────────────────────────────────────────────────────


def _gen_id() -> str:
    """Return a 16-char hex UUID."""
    return uuid.uuid4().hex[:16]


# ── Dead-zone threshold (%) ──────────────────────────────────────────────────
_NEUTRAL_THRESHOLD = 0.5  # abs(pnl_pct) below this → neutral


# ── AuthorTracker ────────────────────────────────────────────────────────────


class AuthorTracker:
    """In-memory author profile and prediction manager.

    Maintains two caches:

    * ``_profiles``    — ``author_id -> AuthorProfile``
    * ``_predictions`` — ``author_id -> List[AuthorPrediction]``

    Both are populated via ``record_prediction`` / ``resolve_prediction``
    during pipeline runs and via ``import_profile`` / ``import_prediction``
    when hydrating from the database at startup.

    The tracker never touches the database directly; the web/storage layer
    is responsible for persisting changes.
    """

    # ── Construction ─────────────────────────────────────────────────────

    def __init__(self, config: AuthorTrackerConfig | None = None) -> None:
        self._config = config or AuthorTrackerConfig()
        self._profiles: Dict[str, AuthorProfile] = {}  # author_id -> profile
        self._predictions: Dict[str, List[AuthorPrediction]] = {}  # author_id -> predictions

    # ── Recording predictions ────────────────────────────────────────────

    def record_prediction(
        self,
        author_id: str,
        platform: str,
        username: str,
        ticker: str,
        stance: str,
        confidence: float,
        signal_id: Optional[str] = None,
    ) -> AuthorPrediction:
        """Record a new prediction for an author.

        Creates the prediction, updates (or creates) the in-memory author
        profile, and returns the prediction.

        Args:
            author_id: Unique identifier for the author (e.g. ``reddit:u_deepvalue``).
            platform: One of ``PLATFORMS`` (reddit, stocktwits, twitter).
            username: Display name on the platform.
            ticker: Ticker symbol the prediction targets.
            stance: One of ``STANCES`` (bullish, bearish, mixed, unknown).
            confidence: Signal confidence in ``[0, 1]``.
            signal_id: Optional link back to the originating ROT signal.

        Returns:
            The newly created ``AuthorPrediction``.
        """
        now = time.time()

        prediction = AuthorPrediction(
            id=_gen_id(),
            author_id=author_id,
            ticker=ticker.upper(),
            stance=stance,
            confidence=confidence,
            signal_id=signal_id,
            outcome=None,
            pnl_pct=None,
            created_at=now,
            resolved_at=None,
        )

        # Ensure prediction list exists, then append.
        if author_id not in self._predictions:
            self._predictions[author_id] = []
        self._predictions[author_id].append(prediction)

        # Update or create the profile.
        profile = self._profiles.get(author_id)
        if profile is None:
            profile = AuthorProfile(
                id=author_id,
                platform=platform,
                username=username,
                total_signals=1,
                first_seen=now,
                last_seen=now,
                updated_at=now,
            )
        else:
            profile = replace(
                profile,
                total_signals=profile.total_signals + 1,
                last_seen=now,
                updated_at=now,
            )
        self._profiles[author_id] = profile

        return prediction

    # ── Resolving predictions ────────────────────────────────────────────

    def resolve_prediction(
        self,
        prediction_id: str,
        author_id: str,
        pnl_pct: float,
    ) -> AuthorPrediction:
        """Resolve a pending prediction with an observed P&L.

        Determines win/loss/neutral from the prediction's stance and the
        actual price move, caps ``pnl_pct`` at ``+/- max_pnl_pct``, and
        updates the author profile's win/loss counts.

        Args:
            prediction_id: The prediction to resolve.
            author_id: The owning author.
            pnl_pct: Observed price change percentage since prediction.

        Returns:
            A new ``AuthorPrediction`` with ``outcome``, ``pnl_pct``,
            and ``resolved_at`` set.

        Raises:
            KeyError: If the prediction or author is not found.
            ValueError: If the prediction is already resolved.
        """
        predictions = self._predictions.get(author_id)
        if predictions is None:
            raise KeyError(f"No predictions for author {author_id!r}")

        # Find the prediction by id.
        pred_idx: Optional[int] = None
        for idx, p in enumerate(predictions):
            if p.id == prediction_id:
                pred_idx = idx
                break

        if pred_idx is None:
            raise KeyError(
                f"Prediction {prediction_id!r} not found for author {author_id!r}"
            )

        pred = predictions[pred_idx]
        if pred.is_resolved:
            raise ValueError(
                f"Prediction {prediction_id!r} is already resolved "
                f"(outcome={pred.outcome!r})"
            )

        # Cap pnl_pct.
        capped_pnl = max(-self._config.max_pnl_pct, min(self._config.max_pnl_pct, pnl_pct))

        # Determine outcome.
        outcome = self._determine_outcome(pred.stance, capped_pnl)

        now = time.time()
        resolved = replace(
            pred,
            outcome=outcome,
            pnl_pct=capped_pnl,
            resolved_at=now,
        )

        # Replace prediction in cache.
        predictions[pred_idx] = resolved

        # Update profile win/loss counts.
        profile = self._profiles.get(author_id)
        if profile is not None:
            if outcome == "win":
                profile = replace(
                    profile,
                    win_count=profile.win_count + 1,
                    updated_at=now,
                )
            elif outcome == "loss":
                profile = replace(
                    profile,
                    loss_count=profile.loss_count + 1,
                    updated_at=now,
                )
            else:
                # neutral — just update timestamp
                profile = replace(profile, updated_at=now)
            self._profiles[author_id] = profile

        return resolved

    def resolve_predictions_batch(
        self,
        resolutions: List[Tuple[str, str, float]],
    ) -> List[AuthorPrediction]:
        """Resolve multiple predictions in one call.

        Args:
            resolutions: List of ``(prediction_id, author_id, pnl_pct)``
                tuples.

        Returns:
            List of resolved ``AuthorPrediction`` objects in the same
            order as the input.  Predictions that cannot be resolved
            (missing, already resolved) are silently skipped.
        """
        results: List[AuthorPrediction] = []
        for prediction_id, author_id, pnl_pct in resolutions:
            try:
                resolved = self.resolve_prediction(prediction_id, author_id, pnl_pct)
                results.append(resolved)
            except (KeyError, ValueError):
                # Skip predictions that can't be resolved.
                continue
        return results

    # ── Profile access ───────────────────────────────────────────────────

    def get_profile(self, author_id: str) -> Optional[AuthorProfile]:
        """Return the cached profile for an author, or ``None``.

        Args:
            author_id: Unique author identifier.

        Returns:
            The ``AuthorProfile`` if found, else ``None``.
        """
        return self._profiles.get(author_id)

    def get_or_create_profile(
        self,
        author_id: str,
        platform: str,
        username: str,
    ) -> AuthorProfile:
        """Return an existing profile or create a new empty one.

        Args:
            author_id: Unique author identifier.
            platform: One of ``PLATFORMS``.
            username: Display name on the platform.

        Returns:
            The existing or newly created ``AuthorProfile``.
        """
        profile = self._profiles.get(author_id)
        if profile is not None:
            return profile

        now = time.time()
        profile = AuthorProfile(
            id=author_id,
            platform=platform,
            username=username,
            total_signals=0,
            first_seen=now,
            last_seen=now,
            updated_at=now,
        )
        self._profiles[author_id] = profile
        return profile

    # ── Stats computation ────────────────────────────────────────────────

    def compute_author_stats(self, author_id: str) -> AuthorProfile:
        """Recompute accuracy, ROI, Sharpe, and reputation for an author.

        Walks all resolved predictions for the author, computes aggregate
        statistics, and updates the cached profile.

        Stats are only populated when the number of decided predictions
        (win + loss) meets ``min_predictions_for_score``.

        Args:
            author_id: Unique author identifier.

        Returns:
            The updated ``AuthorProfile`` with computed statistics.

        Raises:
            KeyError: If the author is not found.
        """
        profile = self._profiles.get(author_id)
        if profile is None:
            raise KeyError(f"Author {author_id!r} not found")

        predictions = self._predictions.get(author_id, [])

        # Gather resolved predictions with a decisive outcome.
        decided_preds: List[AuthorPrediction] = []
        pnl_pcts: List[float] = []
        win_count = 0
        loss_count = 0

        for pred in predictions:
            if not pred.is_resolved:
                continue
            if pred.outcome == "win":
                win_count += 1
                decided_preds.append(pred)
                if pred.pnl_pct is not None:
                    pnl_pcts.append(pred.pnl_pct)
            elif pred.outcome == "loss":
                loss_count += 1
                decided_preds.append(pred)
                if pred.pnl_pct is not None:
                    pnl_pcts.append(pred.pnl_pct)
            # neutral outcomes are not counted as decided

        decided_count = win_count + loss_count
        min_preds = self._config.min_predictions_for_score

        # Default to None until we have enough data.
        accuracy: Optional[float] = None
        roi_if_followed: Optional[float] = None
        sharpe: Optional[float] = None
        reputation_score: Optional[float] = None

        if decided_count >= min_preds:
            # Accuracy: fraction of decided predictions that were wins.
            accuracy = win_count / decided_count if decided_count > 0 else 0.0

            # ROI: mean P&L of decided predictions.
            if pnl_pcts:
                roi_if_followed = sum(pnl_pcts) / len(pnl_pcts)
            else:
                roi_if_followed = 0.0

            # Sharpe: annualized.
            sharpe = self._compute_sharpe(pnl_pcts)

            # Reputation: weighted composite.
            reputation_score = self._compute_reputation(
                accuracy=accuracy,
                roi=roi_if_followed,
                sharpe=sharpe,
                volume=decided_count,
            )

        now = time.time()
        profile = replace(
            profile,
            win_count=win_count,
            loss_count=loss_count,
            accuracy=accuracy,
            roi_if_followed=roi_if_followed,
            sharpe=sharpe,
            reputation_score=reputation_score,
            updated_at=now,
        )
        self._profiles[author_id] = profile
        return profile

    # ── Leaderboard ──────────────────────────────────────────────────────

    def get_leaderboard(
        self,
        min_predictions: int = 10,
        limit: int = 50,
    ) -> List[AuthorProfile]:
        """Build a sorted leaderboard of top authors.

        Filters to authors with at least ``min_predictions`` decided
        predictions, recomputes stats, and returns the top ``limit``
        sorted by reputation score (descending), with accuracy as
        tiebreaker.

        Args:
            min_predictions: Minimum decided predictions to qualify.
            limit: Maximum number of profiles to return.

        Returns:
            Sorted list of ``AuthorProfile`` objects.
        """
        candidates: List[AuthorProfile] = []

        for author_id, profile in self._profiles.items():
            # Quick pre-filter before expensive recompute.
            predictions = self._predictions.get(author_id, [])
            resolved_count = sum(1 for p in predictions if p.is_resolved and p.outcome in ("win", "loss"))
            if resolved_count < min_predictions:
                continue

            # Recompute stats to ensure freshness.
            try:
                updated = self.compute_author_stats(author_id)
            except KeyError:
                continue

            if updated.decided_count >= min_predictions:
                candidates.append(updated)

        # Sort: reputation DESC, then accuracy DESC.
        candidates.sort(
            key=lambda p: (
                p.reputation_score if p.reputation_score is not None else -1.0,
                p.accuracy if p.accuracy is not None else -1.0,
            ),
            reverse=True,
        )

        return candidates[:limit]

    # ── Prediction queries ───────────────────────────────────────────────

    def get_predictions(
        self,
        author_id: str,
        limit: int = 100,
    ) -> List[AuthorPrediction]:
        """Return an author's predictions, most recent first.

        Args:
            author_id: Unique author identifier.
            limit: Maximum predictions to return.

        Returns:
            List of ``AuthorPrediction`` sorted by ``created_at`` DESC.
        """
        predictions = self._predictions.get(author_id, [])
        sorted_preds = sorted(predictions, key=lambda p: p.created_at, reverse=True)
        return sorted_preds[:limit]

    def get_pending_predictions(
        self,
        min_age_hours: int = 1,
    ) -> List[AuthorPrediction]:
        """Return all unresolved predictions older than ``min_age_hours``.

        Used by the resolution loop to find predictions that are ready
        for price checking.

        Args:
            min_age_hours: Minimum age in hours for a prediction to be
                considered pending.

        Returns:
            List of unresolved ``AuthorPrediction`` objects ordered by
            ``created_at`` ASC (oldest first).
        """
        cutoff = time.time() - (min_age_hours * 3600)
        pending: List[AuthorPrediction] = []

        for author_preds in self._predictions.values():
            for pred in author_preds:
                if not pred.is_resolved and pred.created_at <= cutoff:
                    pending.append(pred)

        # Oldest first so we resolve in chronological order.
        pending.sort(key=lambda p: p.created_at)
        return pending

    # ── Import / Export (for DB persistence) ─────────────────────────────

    def import_profile(self, profile: AuthorProfile) -> None:
        """Import an ``AuthorProfile`` into the in-memory cache.

        Typically called at startup to hydrate state from the database.

        Args:
            profile: The profile to import.
        """
        self._profiles[profile.id] = profile

    def import_prediction(self, prediction: AuthorPrediction) -> None:
        """Import an ``AuthorPrediction`` into the in-memory cache.

        Typically called at startup to hydrate state from the database.

        Args:
            prediction: The prediction to import.
        """
        author_id = prediction.author_id
        if author_id not in self._predictions:
            self._predictions[author_id] = []
        self._predictions[author_id].append(prediction)

    def export_profiles(self) -> List[AuthorProfile]:
        """Return all cached profiles.

        Returns:
            List of all ``AuthorProfile`` objects in the cache.
        """
        return list(self._profiles.values())

    def export_predictions(self) -> List[AuthorPrediction]:
        """Return all cached predictions as a flat list.

        Returns:
            List of all ``AuthorPrediction`` objects across all authors.
        """
        result: List[AuthorPrediction] = []
        for preds in self._predictions.values():
            result.extend(preds)
        return result

    # ── Internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _determine_outcome(stance: str, pnl_pct: float) -> str:
        """Determine win/loss/neutral from stance and price move.

        Rules:
            - abs(pnl_pct) < 0.5% (dead zone) -> neutral
            - bullish + pnl > 0 -> win
            - bullish + pnl < 0 -> loss
            - bearish + pnl < 0 -> win  (price dropped as predicted)
            - bearish + pnl > 0 -> loss
            - mixed / unknown stance -> neutral

        Args:
            stance: The prediction's stance.
            pnl_pct: Observed price change.

        Returns:
            One of ``"win"``, ``"loss"``, ``"neutral"``.
        """
        # Mixed or unknown stances are always neutral.
        if stance not in ("bullish", "bearish"):
            return "neutral"

        # Dead zone: moves too small to call.
        if abs(pnl_pct) < _NEUTRAL_THRESHOLD:
            return "neutral"

        if stance == "bullish":
            return "win" if pnl_pct > 0 else "loss"
        else:  # bearish
            return "win" if pnl_pct < 0 else "loss"

    @staticmethod
    def _compute_sharpe(returns: List[float]) -> float:
        """Compute annualized Sharpe ratio from a list of per-trade returns.

        Uses the standard formula: ``mean / std * sqrt(252)``.
        Returns 0.0 if there are fewer than 2 returns or if the standard
        deviation is zero (all identical returns).

        Args:
            returns: List of percentage returns per trade.

        Returns:
            Annualized Sharpe ratio.
        """
        if len(returns) < 2:
            return 0.0

        n = len(returns)
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0

        if std == 0.0:
            return 0.0

        return (mean / std) * math.sqrt(252)

    def _compute_reputation(
        self,
        accuracy: float,
        roi: float,
        sharpe: float,
        volume: int,
    ) -> float:
        """Compute a weighted reputation score in [0, 100].

        Components (weights sum to 1.0):
            - 40% accuracy  (scaled to 0-100 via ``accuracy * 100``)
            - 30% ROI factor (``roi + 50``, clamped to [0, 100])
            - 20% Sharpe factor (``sharpe * 20 + 50``, clamped to [0, 100])
            - 10% volume factor (``decided / min_preds * 50``, clamped to [0, 100])

        Args:
            accuracy: Win rate in [0, 1].
            roi: Mean P&L percentage across decided trades.
            sharpe: Annualized Sharpe ratio.
            volume: Number of decided predictions.

        Returns:
            Reputation score in [0, 100].
        """
        accuracy_component = accuracy * 100.0

        roi_factor = min(100.0, max(0.0, roi + 50.0))

        sharpe_factor = min(100.0, max(0.0, sharpe * 20.0 + 50.0))

        min_preds = max(1, self._config.min_predictions_for_score)
        volume_factor = min(100.0, (volume / min_preds) * 50.0)

        score = (
            0.40 * accuracy_component
            + 0.30 * roi_factor
            + 0.20 * sharpe_factor
            + 0.10 * volume_factor
        )

        # Clamp to [0, 100].
        return min(100.0, max(0.0, score))
