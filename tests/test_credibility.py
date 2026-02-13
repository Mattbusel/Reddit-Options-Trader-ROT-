from __future__ import annotations

import dataclasses

from rot.credibility.scorer import CredibilityScorer
from rot.core.types import Event, Evidence


def _make_event(**meta_overrides) -> Event:
    meta = {
        "trend_score": 0.5,
        "features": {},
        "score": 50,
        "num_comments": 10,
        "upvote_ratio": 0.85,
        "author": "testuser",
        "flair": None,
        "is_crosspost": False,
        "body_excerpt": "",
    }
    meta.update(meta_overrides)
    return Event(
        event_type="other",
        entities=["TSLA"],
        stance="unknown",
        time_horizon="unknown",
        evidence=[Evidence(post_id="x", permalink="", subreddit="test", excerpt="test")],
        confidence=0.3,
        meta=meta,
    )


class TestCredibilityScorer:
    def setup_method(self):
        self.scorer = CredibilityScorer()

    def test_dd_flair_boosts_confidence(self):
        # DD flair with substantial body (>= 200 chars) should get full dd_flair boost
        event = _make_event(flair="DD", body_excerpt="x" * 250)
        scored = self.scorer.score(event)
        assert scored.confidence > event.confidence
        assert scored.meta["credibility_breakdown"]["dd_flair"] == 0.15

    def test_crosspost_reduces_confidence(self):
        event = _make_event(is_crosspost=True)
        scored = self.scorer.score(event)
        assert scored.confidence < event.confidence
        assert scored.meta["credibility_breakdown"]["crosspost_penalty"] == -0.1

    def test_too_many_tickers_penalized(self):
        event = dataclasses.replace(
            _make_event(),
            entities=["AAPL", "TSLA", "GOOGL", "MSFT", "AMZN"],
        )
        scored = self.scorer.score(event)
        assert scored.confidence < event.confidence

    def test_focused_ticker_bonus(self):
        event = dataclasses.replace(_make_event(), entities=["TSLA"])
        scored = self.scorer.score(event)
        assert "focused_ticker" in scored.meta["credibility_breakdown"]

    def test_high_score_bonus(self):
        event = _make_event(score=500)
        scored = self.scorer.score(event)
        assert "high_score" in scored.meta["credibility_breakdown"]

    def test_controversial_penalty(self):
        event = _make_event(upvote_ratio=0.5)
        scored = self.scorer.score(event)
        assert "controversial" in scored.meta["credibility_breakdown"]

    def test_body_analysis_bonus(self):
        event = _make_event(body_excerpt="A" * 150)
        scored = self.scorer.score(event)
        assert "has_body_analysis" in scored.meta["credibility_breakdown"]

    def test_confidence_clamped_to_range(self):
        # Stack all bonuses
        event = dataclasses.replace(
            _make_event(flair="DD", score=500, body_excerpt="A" * 200, num_comments=300),
            confidence=0.9,
        )
        scored = self.scorer.score(event)
        assert 0.05 <= scored.confidence <= 1.0
