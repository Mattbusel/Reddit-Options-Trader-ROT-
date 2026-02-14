"""Event Impact Analyzer — historical reaction analysis and predictions."""

from __future__ import annotations

import logging
import statistics
import time
from typing import Any, Dict, List, Optional

from rot.macro.types import (
    CATEGORY_SECTOR_SENSITIVITY,
    EVENT_TYPE_CATEGORY,
    EventImpact,
    HistoricalReaction,
)

log = logging.getLogger(__name__)


class EventImpactAnalyzer:
    """Computes and caches historical market impact for event types."""

    def __init__(self, db: Any) -> None:
        self._db = db

    # ── Core analysis ────────────────────────────────────────────────

    async def analyze_impact(
        self, event_type: str, lookback_years: int = 5
    ) -> EventImpact:
        """Compute aggregated historical impact for an event type.

        Looks at SPY price changes and VIX changes on event dates.
        """
        # Check cache first
        cached = await self._db.get_event_impact_cache(event_type)
        if cached and (time.time() - cached.get("computed_at", 0)) < 86400:
            return self._cache_to_impact(cached)

        # Query historical events with actual values
        cutoff = time.time() - lookback_years * 365 * 86400
        rows = await self._db.query_macro_events(
            event_type=event_type,
            end_ts=time.time(),
            start_ts=cutoff,
            has_actual=True,
            order="desc",
            limit=200,
        )

        if not rows:
            return EventImpact(
                event_type=event_type,
                avg_spy_move_pct=0.0,
                avg_vix_change=0.0,
                sample_size=0,
            )

        # Compute reactions
        reactions: List[HistoricalReaction] = []
        spy_moves: List[float] = []
        vix_changes: List[float] = []

        for row in rows:
            meta = row.get("meta", {})
            if isinstance(meta, str):
                import json
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}

            spy_move = meta.get("spy_move_pct", 0.0)
            vix_change = meta.get("vix_change", 0.0)
            surprise = row.get("surprise_pct", 0.0) or 0.0

            spy_moves.append(spy_move)
            vix_changes.append(vix_change)

            reactions.append(
                HistoricalReaction(
                    date=row["scheduled_at"],
                    spy_move_pct=spy_move,
                    vix_change=vix_change,
                    surprise_pct=surprise,
                    sector_moves=meta.get("sector_moves", {}),
                )
            )

        avg_spy = statistics.mean(spy_moves) if spy_moves else 0.0
        avg_vix = statistics.mean(vix_changes) if vix_changes else 0.0
        max_spy = max(spy_moves) if spy_moves else 0.0
        min_spy = min(spy_moves) if spy_moves else 0.0

        category = EVENT_TYPE_CATEGORY.get(event_type, "other")
        affected = CATEGORY_SECTOR_SENSITIVITY.get(category, [])

        impact = EventImpact(
            event_type=event_type,
            avg_spy_move_pct=round(avg_spy, 4),
            avg_vix_change=round(avg_vix, 4),
            max_spy_move_pct=round(max_spy, 4),
            min_spy_move_pct=round(min_spy, 4),
            historical_reactions=reactions[:50],  # Limit for memory
            most_affected_sectors=affected,
            sample_size=len(reactions),
        )

        # Cache result
        await self._db.save_event_impact_cache(
            event_type=event_type,
            avg_spy_move=impact.avg_spy_move_pct,
            avg_vix_change=impact.avg_vix_change,
            sample_size=impact.sample_size,
            reactions_json=reactions[:20],
            sector_sensitivity=affected,
        )

        return impact

    # ── Predictions ──────────────────────────────────────────────────

    async def predict_impact(self, event_type: str) -> Dict[str, Any]:
        """Predict market impact for an upcoming event.

        Returns dict with expected_spy_move, expected_vix_change,
        confidence, affected_sectors, recommendation.
        """
        impact = await self.analyze_impact(event_type)

        if impact.sample_size < 5:
            return {
                "expected_spy_move_pct": 0.0,
                "expected_vix_change": 0.0,
                "confidence": "low",
                "affected_sectors": impact.most_affected_sectors,
                "sample_size": impact.sample_size,
                "recommendation": "Insufficient historical data for prediction.",
            }

        # Determine confidence based on sample size + consistency
        abs_moves = [abs(r.spy_move_pct) for r in impact.historical_reactions]
        move_std = statistics.stdev(abs_moves) if len(abs_moves) > 1 else 0.0
        avg_abs = statistics.mean(abs_moves) if abs_moves else 0.0

        # CV (coefficient of variation) — lower = more predictable
        cv = move_std / avg_abs if avg_abs > 0.01 else 999.0

        if impact.sample_size >= 20 and cv < 1.0:
            confidence = "high"
        elif impact.sample_size >= 10 and cv < 2.0:
            confidence = "medium"
        else:
            confidence = "low"

        # Strategy recommendation
        avg_abs_move = statistics.mean(abs_moves) if abs_moves else 0.0
        if avg_abs_move > 1.0:
            rec = (
                "High-impact event. Consider straddle/strangle for volatility play, "
                "or reduce directional exposure before release."
            )
        elif avg_abs_move > 0.5:
            rec = (
                "Moderate impact. Watch for surprise deviations from consensus. "
                "Consider widening stops on open positions."
            )
        else:
            rec = "Low historical impact. Unlikely to cause significant moves."

        return {
            "expected_spy_move_pct": round(impact.avg_spy_move_pct, 3),
            "expected_vix_change": round(impact.avg_vix_change, 3),
            "max_historical_move": round(impact.max_spy_move_pct, 3),
            "avg_absolute_move": round(avg_abs_move, 3),
            "confidence": confidence,
            "affected_sectors": impact.most_affected_sectors,
            "sample_size": impact.sample_size,
            "recommendation": rec,
        }

    # ── Sector sensitivity ───────────────────────────────────────────

    async def get_sector_sensitivity(
        self, event_type: str
    ) -> Dict[str, float]:
        """Return sector sensitivity scores for an event type.

        Returns dict mapping sector → average absolute move on event days.
        """
        impact = await self.analyze_impact(event_type)
        sector_moves: Dict[str, List[float]] = {}
        for r in impact.historical_reactions:
            for sector, move in r.sector_moves.items():
                sector_moves.setdefault(sector, []).append(abs(move))
        return {
            sector: round(statistics.mean(moves), 4)
            for sector, moves in sector_moves.items()
            if moves
        }

    # ── Surprise correlation ─────────────────────────────────────────

    async def get_surprise_correlation(self, event_type: str) -> float:
        """Compute correlation between surprise magnitude and market move.

        Returns Pearson correlation coefficient (-1 to 1).
        """
        impact = await self.analyze_impact(event_type)
        surprises = []
        moves = []
        for r in impact.historical_reactions:
            if r.surprise_pct != 0.0:
                surprises.append(abs(r.surprise_pct))
                moves.append(abs(r.spy_move_pct))

        if len(surprises) < 5:
            return 0.0

        return self._pearson(surprises, moves)

    @staticmethod
    def _pearson(x: List[float], y: List[float]) -> float:
        """Simple Pearson correlation coefficient."""
        n = len(x)
        if n < 2:
            return 0.0
        mx = statistics.mean(x)
        my = statistics.mean(y)
        num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        dx = (sum((xi - mx) ** 2 for xi in x)) ** 0.5
        dy = (sum((yi - my) ** 2 for yi in y)) ** 0.5
        if dx * dy == 0:
            return 0.0
        return round(num / (dx * dy), 4)

    # ── Cache helpers ────────────────────────────────────────────────

    @staticmethod
    def _cache_to_impact(cached: Dict[str, Any]) -> EventImpact:
        """Convert cache row to EventImpact."""
        import json

        reactions_raw = cached.get("reactions_json", "[]")
        if isinstance(reactions_raw, str):
            try:
                reactions_raw = json.loads(reactions_raw)
            except (json.JSONDecodeError, TypeError):
                reactions_raw = []

        reactions = [
            HistoricalReaction(
                date=r.get("date", 0),
                spy_move_pct=r.get("spy_move_pct", 0.0),
                vix_change=r.get("vix_change", 0.0),
                surprise_pct=r.get("surprise_pct", 0.0),
                sector_moves=r.get("sector_moves", {}),
            )
            for r in reactions_raw
            if isinstance(r, dict)
        ]

        sectors_raw = cached.get("sector_sensitivity_json", "[]")
        if isinstance(sectors_raw, str):
            try:
                sectors_raw = json.loads(sectors_raw)
            except (json.JSONDecodeError, TypeError):
                sectors_raw = []

        return EventImpact(
            event_type=cached.get("event_type", ""),
            avg_spy_move_pct=cached.get("avg_spy_move", 0.0),
            avg_vix_change=cached.get("avg_vix_change", 0.0),
            historical_reactions=reactions,
            most_affected_sectors=sectors_raw,
            sample_size=cached.get("sample_size", 0),
        )
