"""FOMC Tracker — rate decisions, statement analysis, hawkish/dovish scoring."""

from __future__ import annotations

import json
import logging
import time
from difflib import HtmlDiff
from typing import Any, Dict, List, Optional

from rot.macro.types import FOMCMeeting

log = logging.getLogger(__name__)

# ── Hawkish / Dovish keyword dictionaries ────────────────────────────
_HAWKISH_TERMS = {
    "inflation": 1.0,
    "inflationary": 1.0,
    "overheating": 1.2,
    "tighten": 1.5,
    "tightening": 1.5,
    "restrictive": 1.3,
    "rate hike": 2.0,
    "rate increase": 2.0,
    "price stability": 0.8,
    "above target": 1.0,
    "elevated": 0.8,
    "persistent": 0.9,
    "upside risks": 1.0,
    "strong labor market": 0.7,
    "robust": 0.6,
    "further tightening": 1.8,
    "sufficiently restrictive": 1.2,
    "higher for longer": 1.5,
    "reduce balance sheet": 1.0,
    "quantitative tightening": 1.3,
}

_DOVISH_TERMS = {
    "accommodate": 1.0,
    "accommodative": 1.0,
    "easing": 1.5,
    "rate cut": 2.0,
    "rate reduction": 2.0,
    "downside risks": 1.0,
    "slowdown": 1.0,
    "slowing": 0.8,
    "weakening": 1.0,
    "unemployment": 0.7,
    "below target": 0.8,
    "patient": 0.9,
    "gradual": 0.7,
    "supportive": 0.8,
    "stimulus": 1.2,
    "flexible": 0.6,
    "data dependent": 0.5,
    "balanced risks": 0.4,
    "maximum employment": 0.7,
    "pause": 0.8,
    "skip": 0.7,
    "disinflation": 1.0,
    "progress": 0.5,
}


class FOMCTracker:
    """Tracks FOMC meetings, rate decisions, and statement sentiment."""

    def __init__(self, db: Any) -> None:
        self._db = db

    # ── Query methods ────────────────────────────────────────────────

    async def get_next_meeting(self) -> Optional[FOMCMeeting]:
        """Return the next scheduled FOMC meeting."""
        row = await self._db.get_next_fomc_meeting(time.time())
        if row:
            return self._row_to_meeting(row)
        return None

    async def get_history(self, limit: int = 20) -> List[FOMCMeeting]:
        """Return historical FOMC meetings."""
        rows = await self._db.query_fomc_meetings(limit=limit, order="desc")
        return [self._row_to_meeting(r) for r in rows]

    async def get_meeting(self, meeting_id: str) -> Optional[FOMCMeeting]:
        """Return a specific FOMC meeting by ID."""
        row = await self._db.get_fomc_meeting(meeting_id)
        if row:
            return self._row_to_meeting(row)
        return None

    # ── Statement analysis ───────────────────────────────────────────

    def score_hawkish_dovish(self, text: str) -> tuple[float, float]:
        """Score text for hawkish and dovish sentiment.

        Uses keyword matching with intensity weights.
        Returns (hawkish_score, dovish_score) each in [0.0, 1.0].
        """
        if not text:
            return (0.0, 0.0)

        text_lower = text.lower()
        hawk_total = 0.0
        dove_total = 0.0
        hawk_max = sum(_HAWKISH_TERMS.values())
        dove_max = sum(_DOVISH_TERMS.values())

        for term, weight in _HAWKISH_TERMS.items():
            count = text_lower.count(term)
            if count > 0:
                hawk_total += weight * min(count, 3)

        for term, weight in _DOVISH_TERMS.items():
            count = text_lower.count(term)
            if count > 0:
                dove_total += weight * min(count, 3)

        # Normalize to [0, 1] — cap at max plausible score
        hawk_norm = min(hawk_total / (hawk_max * 0.3), 1.0)
        dove_norm = min(dove_total / (dove_max * 0.3), 1.0)

        return (round(hawk_norm, 3), round(dove_norm, 3))

    def generate_statement_diff(self, old_text: str, new_text: str) -> str:
        """Generate HTML diff between two FOMC statements.

        Returns HTML string with additions (green) and deletions (red).
        """
        if not old_text or not new_text:
            return ""

        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()

        differ = HtmlDiff(wrapcolumn=80)
        html = differ.make_table(
            old_lines,
            new_lines,
            fromdesc="Previous Statement",
            todesc="Current Statement",
            context=True,
            numlines=3,
        )
        return html

    def classify_decision(
        self, rate_before: float, rate_after: float
    ) -> str:
        """Classify FOMC rate decision.

        Returns: 'hold', 'raise_25', 'raise_50', 'raise_75',
                 'cut_25', 'cut_50', 'cut_75', etc.
        """
        diff_bps = round((rate_after - rate_before) * 100)
        if diff_bps == 0:
            return "hold"
        direction = "raise" if diff_bps > 0 else "cut"
        magnitude = abs(diff_bps)
        return f"{direction}_{magnitude}"

    # ── Rate probability estimation ──────────────────────────────────

    def estimate_rate_probabilities(
        self, current_rate: float, market_implied_rate: float
    ) -> Dict[str, float]:
        """Estimate probabilities of different rate outcomes.

        Uses simple approach based on market implied rate vs current rate.
        In production, this would use Fed Funds futures data.

        Returns dict of outcome → probability.
        """
        diff_bps = round((market_implied_rate - current_rate) * 100)

        # Simple model: center probability mass around implied move
        outcomes: Dict[str, float] = {}

        if abs(diff_bps) < 5:
            outcomes["hold"] = 0.80
            outcomes["raise_25"] = 0.10
            outcomes["cut_25"] = 0.10
        elif diff_bps > 0:
            # Market expects rate increase
            if diff_bps >= 40:
                outcomes["raise_50"] = 0.60
                outcomes["raise_25"] = 0.30
                outcomes["hold"] = 0.10
            else:
                outcomes["raise_25"] = 0.60
                outcomes["hold"] = 0.30
                outcomes["raise_50"] = 0.10
        else:
            # Market expects rate cut
            if diff_bps <= -40:
                outcomes["cut_50"] = 0.60
                outcomes["cut_25"] = 0.30
                outcomes["hold"] = 0.10
            else:
                outcomes["cut_25"] = 0.60
                outcomes["hold"] = 0.30
                outcomes["cut_50"] = 0.10

        return outcomes

    # ── Meeting persistence ──────────────────────────────────────────

    async def save_meeting(self, meeting: FOMCMeeting) -> None:
        """Save or update a FOMC meeting record."""
        await self._db.upsert_fomc_meeting(meeting)

    async def update_statement(
        self, meeting_id: str, statement_text: str
    ) -> Optional[FOMCMeeting]:
        """Update a meeting with statement text and compute scores."""
        meeting = await self.get_meeting(meeting_id)
        if not meeting:
            return None

        hawk, dove = self.score_hawkish_dovish(statement_text)

        # Get previous meeting for diff
        history = await self.get_history(limit=2)
        prev_statement = ""
        for m in history:
            if m.id != meeting_id and m.statement_text:
                prev_statement = m.statement_text
                break

        diff_html = self.generate_statement_diff(prev_statement, statement_text)

        # Save updated meeting
        updated = FOMCMeeting(
            id=meeting.id,
            meeting_date=meeting.meeting_date,
            rate_decision=meeting.rate_decision,
            rate_before=meeting.rate_before,
            rate_after=meeting.rate_after,
            statement_text=statement_text,
            statement_diff=diff_html,
            hawkish_score=hawk,
            dovish_score=dove,
            dot_plot_median=meeting.dot_plot_median,
            meta=meeting.meta,
        )
        await self.save_meeting(updated)
        return updated

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_meeting(row: Dict[str, Any]) -> FOMCMeeting:
        """Convert a DB row dict to FOMCMeeting."""
        meta = row.get("meta", "{}")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        return FOMCMeeting(
            id=row["id"],
            meeting_date=row["meeting_date"],
            rate_decision=row.get("rate_decision", ""),
            rate_before=row.get("rate_before", 0.0),
            rate_after=row.get("rate_after", 0.0),
            statement_text=row.get("statement_text", ""),
            statement_diff=row.get("statement_diff", ""),
            hawkish_score=row.get("hawkish_score", 0.0),
            dovish_score=row.get("dovish_score", 0.0),
            dot_plot_median=row.get("dot_plot_median"),
            meta=meta,
        )
