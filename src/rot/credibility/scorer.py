from __future__ import annotations

import dataclasses
from typing import Dict

from rot.core.types import Event


class CredibilityScorer:
    """Multi-factor credibility scoring for Reddit-sourced events."""

    def score(self, event: Event) -> Event:
        factors: Dict[str, float] = {}
        adjustment = 0.0

        meta = event.meta or {}

        # Factor 1: Ticker mention quality
        # Explicit $TICKER mentions are more intentional than bare uppercase words
        if meta.get("flair") == "DD":
            factors["dd_flair"] = 0.15
            adjustment += 0.15
        elif meta.get("flair") in ("Discussion", "Technical Analysis", "Fundamentals"):
            factors["quality_flair"] = 0.05
            adjustment += 0.05

        # Factor 2: Entity count - too many tickers = watchlist noise
        entity_count = len(event.entities)
        if entity_count >= 5:
            factors["too_many_tickers"] = -0.15
            adjustment -= 0.15
        elif entity_count == 1:
            factors["focused_ticker"] = 0.05
            adjustment += 0.05

        # Factor 3: Cross-post penalty
        if meta.get("is_crosspost"):
            factors["crosspost_penalty"] = -0.1
            adjustment -= 0.1

        # Factor 4: Post engagement quality
        score = meta.get("score", 0)
        num_comments = meta.get("num_comments", 0)
        upvote_ratio = meta.get("upvote_ratio")

        if isinstance(score, (int, float)) and score > 100:
            factors["high_score"] = 0.05
            adjustment += 0.05
        if isinstance(upvote_ratio, (int, float)) and upvote_ratio < 0.6:
            factors["controversial"] = -0.05
            adjustment -= 0.05

        # Factor 5: Comment engagement (high comments relative to score = discussion)
        if isinstance(num_comments, (int, float)) and isinstance(score, (int, float)):
            if score > 0 and num_comments > score * 0.5:
                factors["high_discussion"] = 0.05
                adjustment += 0.05

        # Factor 6: Body content exists (post with analysis > title-only)
        body_excerpt = meta.get("body_excerpt", "")
        if isinstance(body_excerpt, str) and len(body_excerpt) > 100:
            factors["has_body_analysis"] = 0.05
            adjustment += 0.05

        # Apply adjustment to confidence
        new_confidence = max(0.05, min(1.0, event.confidence + adjustment))

        new_meta = dict(meta)
        new_meta["credibility_breakdown"] = factors
        new_meta["credibility_adjustment"] = adjustment

        return dataclasses.replace(event, confidence=new_confidence, meta=new_meta)
