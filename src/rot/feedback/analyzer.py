"""Signal feedback analysis engine.

Computes category performance, source reliability, feature importance,
quality trends, suppression candidates, and detailed confidence calibration
from historical signal outcomes.  Results are cached in memory and refreshed
by a background loop every N hours (configurable).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Reuse the stance-aware win/loss SQL from sql_helpers.py — single source of truth.
from rot.storage.sql_helpers import (
    _A_WIN_SQL, _A_LOSS_SQL, _A_NEUTRAL_SQL, _A_PRICE_COL, _UNIFIED_CTE,
)


class FeedbackAnalyzer:
    """Core feedback analysis engine.

    Queries the database for historical signal outcomes and computes analytics
    that power the Signal Quality dashboard and adaptive suppression.

    Usage::

        analyzer = FeedbackAnalyzer(db)
        await analyzer.run_analysis(ml_scorer=scorer)
        results = analyzer.get_cached_results()
    """

    def __init__(self, db: Any) -> None:
        self.db = db
        self._last_analysis: Dict[str, Any] = {}

    # ── Public API ────────────────────────────────────────────────────

    async def run_analysis(
        self,
        ml_scorer: Any = None,
        days: int = 30,
        suppress_threshold: float = 0.20,
        min_signals: int = 30,
    ) -> Dict[str, Any]:
        """Run all analysis methods and cache the results.

        Called by the background loop every N hours.
        """
        t0 = time.time()
        results: Dict[str, Any] = {}

        try:
            results["category_performance"] = await self.get_category_performance(days)
        except Exception as exc:
            log.warning("category_performance failed: %s", exc)
            results["category_performance"] = []

        try:
            results["source_reliability"] = await self.get_source_reliability(days)
        except Exception as exc:
            log.warning("source_reliability failed: %s", exc)
            results["source_reliability"] = []

        try:
            results["feature_importance"] = self.get_feature_importance(ml_scorer)
        except Exception as exc:
            log.warning("feature_importance failed: %s", exc)
            results["feature_importance"] = []

        try:
            results["quality_trend"] = await self.get_quality_trend(days)
        except Exception as exc:
            log.warning("quality_trend failed: %s", exc)
            results["quality_trend"] = {}

        try:
            results["suppression_candidates"] = self._compute_suppression_candidates(
                results.get("category_performance", []),
                results.get("source_reliability", []),
                suppress_threshold,
                min_signals,
            )
        except Exception as exc:
            log.warning("suppression_candidates failed: %s", exc)
            results["suppression_candidates"] = []

        try:
            results["calibration_detailed"] = await self.get_confidence_calibration_detailed(days)
        except Exception as exc:
            log.warning("calibration_detailed failed: %s", exc)
            results["calibration_detailed"] = []

        elapsed = time.time() - t0
        results["computed_at"] = time.time()
        results["elapsed_s"] = round(elapsed, 2)
        self._last_analysis = results

        log.info(
            "Feedback analysis complete: %d categories, %d sources, %d features, %.1fs",
            len(results.get("category_performance", [])),
            len(results.get("source_reliability", [])),
            len(results.get("feature_importance", [])),
            elapsed,
        )
        return results

    def get_cached_results(self) -> Dict[str, Any]:
        """Return the last analysis results (thread-safe read for suppressor)."""
        return self._last_analysis

    # ── Category Performance ──────────────────────────────────────────

    async def get_category_performance(self, days: int = 30) -> List[Dict[str, Any]]:
        """Win rate grouped by (event_type, stance, strategy)."""
        cutoff = time.time() - days * 86400
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT
                event_type,
                stance,
                strategy,
                COUNT(*) as total,
                SUM({_A_WIN_SQL}) as winners,
                SUM({_A_LOSS_SQL}) as losers,
                SUM({_A_NEUTRAL_SQL}) as neutral,
                AVG(confidence) as avg_confidence
            FROM _unified
            WHERE created_at > ?
              AND price_at_signal > 0
              AND {_A_PRICE_COL} IS NOT NULL
            GROUP BY event_type, stance, strategy
            ORDER BY total DESC
        """
        rows = []
        async with self.db.db.execute(query, (cutoff,)) as cursor:
            async for row in cursor:
                winners = row[4] or 0
                losers = row[5] or 0
                decided = winners + losers
                win_rate = (winners / decided * 100) if decided > 0 else None
                rows.append({
                    "event_type": row[0] or "unknown",
                    "stance": row[1] or "unknown",
                    "strategy": row[2] or "none",
                    "total": row[3],
                    "winners": winners,
                    "losers": losers,
                    "neutral": row[6] or 0,
                    "decided": decided,
                    "win_rate": round(win_rate, 1) if win_rate is not None else None,
                    "avg_confidence": round(row[7], 3) if row[7] else None,
                })
        return rows

    # ── Source Reliability ────────────────────────────────────────────

    async def get_source_reliability(self, days: int = 30) -> List[Dict[str, Any]]:
        """Win rate grouped by (subreddit/source, event_type), min 5 signals."""
        cutoff = time.time() - days * 86400
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT
                subreddit as source,
                event_type,
                COUNT(*) as total,
                SUM({_A_WIN_SQL}) as winners,
                SUM({_A_LOSS_SQL}) as losers,
                AVG(confidence) as avg_confidence
            FROM _unified
            WHERE created_at > ?
              AND price_at_signal > 0
              AND {_A_PRICE_COL} IS NOT NULL
            GROUP BY subreddit, event_type
            HAVING COUNT(*) >= 5
            ORDER BY total DESC
        """
        rows = []
        async with self.db.db.execute(query, (cutoff,)) as cursor:
            async for row in cursor:
                winners = row[3] or 0
                losers = row[4] or 0
                decided = winners + losers
                win_rate = (winners / decided * 100) if decided > 0 else None
                rows.append({
                    "source": row[0] or "unknown",
                    "event_type": row[1] or "unknown",
                    "total": row[2],
                    "winners": winners,
                    "losers": losers,
                    "decided": decided,
                    "win_rate": round(win_rate, 1) if win_rate is not None else None,
                    "avg_confidence": round(row[5], 3) if row[5] else None,
                })
        return rows

    # ── Feature Importance ────────────────────────────────────────────

    def get_feature_importance(self, ml_scorer: Any) -> List[Dict[str, Any]]:
        """Extract feature importances from the trained ML model.

        Reads feature_importances_ from the GradientBoosting classifier inside
        the MLCredibilityScorer's sklearn pipeline.  No DB query needed.
        """
        if ml_scorer is None:
            return []
        if not getattr(ml_scorer, "ml_available", False):
            return []
        model = getattr(ml_scorer, "_model", None)
        if model is None:
            return []
        # Navigate sklearn pipeline: Pipeline -> named_steps["clf"]
        named_steps = getattr(model, "named_steps", None)
        clf = named_steps.get("clf") if named_steps else None
        if clf is None or not hasattr(clf, "feature_importances_"):
            return []

        importances = clf.feature_importances_

        try:
            from rot.credibility.features import FEATURE_NAMES
        except ImportError:
            return []

        result = []
        for name, imp in sorted(
            zip(FEATURE_NAMES, importances), key=lambda x: -x[1]
        ):
            result.append({"feature": name, "importance": round(float(imp), 4)})
        return result

    # ── Quality Trend ─────────────────────────────────────────────────

    async def get_quality_trend(self, days: int = 30) -> Dict[str, Any]:
        """Daily win rate trend with simple linear regression slope."""
        cutoff = time.time() - days * 86400
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT
                DATE(created_at, 'unixepoch') as day,
                COUNT(*) as total,
                SUM({_A_WIN_SQL}) as winners,
                SUM({_A_LOSS_SQL}) as losers,
                AVG(confidence) as avg_confidence
            FROM _unified
            WHERE created_at > ?
              AND price_at_signal > 0
              AND {_A_PRICE_COL} IS NOT NULL
            GROUP BY DATE(created_at, 'unixepoch')
            ORDER BY day ASC
        """
        daily: List[Dict[str, Any]] = []
        async with self.db.db.execute(query, (cutoff,)) as cursor:
            async for row in cursor:
                winners = row[2] or 0
                losers = row[3] or 0
                decided = winners + losers
                win_rate = (winners / decided * 100) if decided > 0 else None
                daily.append({
                    "day": row[0],
                    "total": row[1],
                    "winners": winners,
                    "losers": losers,
                    "decided": decided,
                    "win_rate": round(win_rate, 1) if win_rate is not None else None,
                    "avg_confidence": round(row[4], 3) if row[4] else None,
                })

        # Compute linear regression slope on daily win rates
        slope = self._compute_slope(daily)

        # 7-day moving average
        ma7 = self._compute_moving_average(daily, window=7)

        return {
            "daily": daily,
            "slope": slope,
            "ma7": ma7,
            "direction": "improving" if slope and slope > 0.02 else (
                "degrading" if slope and slope < -0.02 else "stable"
            ),
        }

    # ── Confidence Calibration (Detailed) ─────────────────────────────

    async def get_confidence_calibration_detailed(
        self, days: int = 30
    ) -> List[Dict[str, Any]]:
        """Per-decile confidence calibration: expected vs actual win rate."""
        cutoff = time.time() - days * 86400
        query = f"""  # nosec B608 - SQL uses constants only, values parameterized
            {_UNIFIED_CTE}
            SELECT
                CAST(confidence * 10 AS INTEGER) as decile,
                COUNT(*) as total,
                SUM({_A_WIN_SQL}) as winners,
                SUM({_A_LOSS_SQL}) as losers,
                AVG(confidence) as avg_confidence
            FROM _unified
            WHERE created_at > ?
              AND price_at_signal > 0
              AND {_A_PRICE_COL} IS NOT NULL
            GROUP BY decile
            ORDER BY decile ASC
        """
        rows = []
        async with self.db.db.execute(query, (cutoff,)) as cursor:
            async for row in cursor:
                decile = row[0] or 0
                winners = row[2] or 0
                losers = row[3] or 0
                decided = winners + losers
                actual_win_rate = (winners / decided * 100) if decided > 0 else None
                avg_conf = row[4] or 0
                rows.append({
                    "decile": decile,
                    "decile_label": f"{decile * 10}-{min((decile + 1) * 10, 100)}%",
                    "total": row[1],
                    "winners": winners,
                    "losers": losers,
                    "decided": decided,
                    "actual_win_rate": round(actual_win_rate, 1) if actual_win_rate is not None else None,
                    "expected_win_rate": round(avg_conf * 100, 1),
                })
        return rows

    # ── Suppression Candidates ────────────────────────────────────────

    def _compute_suppression_candidates(
        self,
        category_perf: List[Dict[str, Any]],
        source_rel: List[Dict[str, Any]],
        threshold: float,
        min_signals: int,
    ) -> List[Dict[str, Any]]:
        """Identify categories and sources below the win rate threshold."""
        candidates = []
        threshold_pct = threshold * 100

        # Category-level suppression
        for row in category_perf:
            if row["decided"] >= min_signals and row["win_rate"] is not None:
                if row["win_rate"] < threshold_pct:
                    candidates.append({
                        "level": "category",
                        "event_type": row["event_type"],
                        "stance": row["stance"],
                        "strategy": row["strategy"],
                        "source": None,
                        "win_rate": row["win_rate"],
                        "decided": row["decided"],
                    })

        # Source-level suppression
        for row in source_rel:
            if row["decided"] >= min_signals and row["win_rate"] is not None:
                if row["win_rate"] < threshold_pct:
                    candidates.append({
                        "level": "source",
                        "event_type": row["event_type"],
                        "stance": None,
                        "strategy": None,
                        "source": row["source"],
                        "win_rate": row["win_rate"],
                        "decided": row["decided"],
                    })

        return sorted(candidates, key=lambda c: c["win_rate"])

    # ── Private helpers ───────────────────────────────────────────────

    @staticmethod
    def _compute_slope(daily: List[Dict[str, Any]]) -> Optional[float]:
        """Simple linear regression slope on daily win rates.

        Uses the sum-of-products formula to avoid numpy dependency.
        Returns slope in win-rate-percentage-points per day, or None.
        """
        points = [(i, d["win_rate"]) for i, d in enumerate(daily) if d["win_rate"] is not None]
        n = len(points)
        if n < 3:
            return None

        sum_x = sum(p[0] for p in points)
        sum_y = sum(p[1] for p in points)
        sum_xy = sum(p[0] * p[1] for p in points)
        sum_x2 = sum(p[0] ** 2 for p in points)

        denom = n * sum_x2 - sum_x ** 2
        if denom == 0:
            return None

        slope = (n * sum_xy - sum_x * sum_y) / denom
        return round(slope, 4)

    @staticmethod
    def _compute_moving_average(
        daily: List[Dict[str, Any]], window: int = 7
    ) -> List[Optional[float]]:
        """Compute moving average on daily win rates."""
        win_rates = [d["win_rate"] for d in daily]
        ma = []
        for i in range(len(win_rates)):
            window_vals = [
                v for v in win_rates[max(0, i - window + 1) : i + 1] if v is not None
            ]
            if window_vals:
                ma.append(round(sum(window_vals) / len(window_vals), 1))
            else:
                ma.append(None)
        return ma
