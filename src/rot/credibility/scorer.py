from __future__ import annotations

import dataclasses
from typing import Dict

from rot.core.types import Event


_SUBREDDIT_WEIGHTS: Dict[str, float] = {
    "wallstreetbets": -0.05,
    "wallstreetbetsogs": -0.03,
    "shortsqueeze": -0.05,
    "pennystocks": -0.05,
    "stocks": 0.0,
    "options": 0.05,
    "investing": 0.05,
    "stockmarket": 0.0,
    "thetagang": 0.05,
    "valueinvesting": 0.05,
}


_INSTITUTIONAL_RSS_LABELS = {
    "fda-press-releases", "fda-drugs", "fda-safety-alerts",
    "fda-recalls", "fda-oncology",
    "fed-press-releases", "sec-8k-filings",
    "dod-contracts", "dod-releases", "dod-news",
    "biopharma-dive", "drugs-com-approvals", "drugs-com-trials",
    "seekingalpha-currents",
}


class CredibilityScorer:
    """Multi-factor credibility scoring for Reddit-sourced events."""

    def score(self, event: Event) -> Event:
        """Apply heuristic credibility factors to *event* and return an updated copy."""
        factors: Dict[str, float] = {}
        adjustment = 0.0

        meta = event.meta or {}

        # Factor 0: RSS source quality — institutional/government feeds are high-signal
        is_rss = meta.get("flair") == "rss"
        if is_rss:
            subreddit_label = ""
            if event.evidence:
                subreddit_label = (event.evidence[0].subreddit or "").lower()
            if subreddit_label in _INSTITUTIONAL_RSS_LABELS:
                factors["institutional_rss"] = 0.15
                adjustment += 0.15
            elif is_rss:
                factors["news_rss"] = 0.05
                adjustment += 0.05

        # Factor 1: Ticker mention quality / DD flair
        # Explicit $TICKER mentions are more intentional than bare uppercase words.
        # DD flair gets full boost only if the post body is substantial (>=200 chars).
        if meta.get("flair") == "DD":
            body = meta.get("body_excerpt", "")
            if isinstance(body, str) and len(body) >= 200:
                factors["dd_flair"] = 0.15
                adjustment += 0.15
            else:
                factors["dd_flair_shallow"] = 0.05
                adjustment += 0.05
        elif meta.get("flair") in ("Discussion", "Technical Analysis", "Fundamentals"):
            factors["quality_flair"] = 0.05
            adjustment += 0.05

        # Factor 2: Entity count - too many tickers = watchlist noise
        entity_count = len(event.entities)
        if entity_count >= 5:
            factors["too_many_tickers"] = -0.08
            adjustment -= 0.08
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

        # Factor 7: Subreddit quality weighting
        subreddit = ""
        if event.evidence:
            subreddit = (event.evidence[0].subreddit or "").lower()
        sub_adj = _SUBREDDIT_WEIGHTS.get(subreddit, 0.0)
        if sub_adj != 0:
            label = "subreddit_boost" if sub_adj > 0 else "subreddit_penalty"
            factors[label] = sub_adj
            adjustment += sub_adj

        # Factor 8.5: Earnings rumor penalty — historically worst-performing event type
        if event.event_type == "earnings_rumor":
            factors["earnings_rumor_penalty"] = -0.10
            adjustment -= 0.10

        # Factor 8: Author credibility (karma, account age)
        author_karma = meta.get("author_karma", 0)
        author_age_days = meta.get("author_age_days", 0)

        if isinstance(author_karma, (int, float)):
            if author_karma >= 50000:
                factors["author_high_karma"] = 0.10
                adjustment += 0.10
            elif author_karma >= 10000:
                factors["author_good_karma"] = 0.05
                adjustment += 0.05
            elif author_karma < 100:
                factors["author_low_karma"] = -0.05
                adjustment -= 0.05

        if isinstance(author_age_days, (int, float)):
            if author_age_days >= 365:
                factors["author_established"] = 0.05
                adjustment += 0.05
            elif author_age_days < 30:
                factors["author_new_account"] = -0.05
                adjustment -= 0.05

        # ── NLP-powered factors (when NLP engine is active) ──
        nlp = meta.get("nlp", {})
        if nlp:
            # Factor 9: Sarcasm penalty — high sarcasm probability = unreliable signal
            sarcasm_prob = nlp.get("sarcasm_probability", 0.0)
            if isinstance(sarcasm_prob, (int, float)) and sarcasm_prob > 0.5:
                penalty = min(0.15, sarcasm_prob * 0.2)
                factors["nlp_sarcasm_penalty"] = -penalty
                adjustment -= penalty

            # Factor 10: Conviction boost/penalty
            conviction = nlp.get("conviction", 0.5)
            if isinstance(conviction, (int, float)):
                if conviction > 0.7:
                    factors["nlp_high_conviction"] = 0.05
                    adjustment += 0.05
                elif conviction < 0.3:
                    factors["nlp_low_conviction"] = -0.05
                    adjustment -= 0.05

            # Factor 11: Thread consensus — community agreement
            thread_consensus = nlp.get("thread_consensus", 0.0)
            if isinstance(thread_consensus, (int, float)) and thread_consensus > 0:
                if thread_consensus > 0.7:
                    factors["nlp_strong_consensus"] = 0.10
                    adjustment += 0.10
                elif thread_consensus > 0.5:
                    factors["nlp_moderate_consensus"] = 0.05
                    adjustment += 0.05
                # Contrarian detection
                if nlp.get("contrarian_detected"):
                    factors["nlp_contrarian_flag"] = -0.05
                    adjustment -= 0.05

            # Factor 12: Temporal actionability — past-tense = less tradeable
            actionability = nlp.get("actionability", 0.5)
            if isinstance(actionability, (int, float)) and actionability < 0.3:
                factors["nlp_low_actionability"] = -0.05
                adjustment -= 0.05

        # Apply adjustment to confidence
        new_confidence = max(0.05, min(1.0, event.confidence + adjustment))

        new_meta = dict(meta)
        new_meta["credibility_breakdown"] = factors
        new_meta["credibility_adjustment"] = adjustment

        return dataclasses.replace(event, confidence=new_confidence, meta=new_meta)
