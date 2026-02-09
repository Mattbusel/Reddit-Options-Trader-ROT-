from __future__ import annotations

import pytest
from rot.core.types import (
    Post, Comment, ThreadSnapshot, TrendCandidate, Event, Evidence,
    ReasoningPacket, TradeIdea, OptionLeg,
)


@pytest.fixture
def sample_post() -> Post:
    return Post(
        id="abc123",
        created_utc=1700000000,
        subreddit="wallstreetbets",
        title="$TSLA to the moon! Calls printing 🚀",
        selftext="Bought $TSLA 300C weeklies. Earnings next week, this thing is gonna rip.",
        url="https://reddit.com/r/wallstreetbets/abc123",
        score=500,
        num_comments=200,
        upvote_ratio=0.92,
        author="diamondhands42",
        permalink="https://www.reddit.com/r/wallstreetbets/comments/abc123",
        flair="DD",
        is_crosspost=False,
    )


@pytest.fixture
def sample_snapshot(sample_post) -> ThreadSnapshot:
    return ThreadSnapshot(snapshot_ts=1700000100, post=sample_post)


@pytest.fixture
def sample_candidate(sample_snapshot) -> TrendCandidate:
    return TrendCandidate(
        key="wallstreetbets:abc123",
        window_s=1800,
        features={"score_rate": 0.5, "comment_rate": 0.3},
        trend_score=1.1,
        reason="rate_threshold",
        snapshot=sample_snapshot,
    )


@pytest.fixture
def sample_event() -> Event:
    return Event(
        event_type="earnings_rumor",
        entities=["TSLA"],
        stance="bullish",
        time_horizon="earnings",
        evidence=[
            Evidence(
                post_id="abc123",
                permalink="https://www.reddit.com/r/wallstreetbets/comments/abc123",
                subreddit="wallstreetbets",
                excerpt="$TSLA to the moon! Calls printing",
            )
        ],
        confidence=0.5,
        meta={
            "trend_score": 1.1,
            "features": {"score_rate": 0.5, "comment_rate": 0.3},
            "score": 500,
            "num_comments": 200,
            "upvote_ratio": 0.92,
            "author": "diamondhands42",
            "flair": "DD",
            "is_crosspost": False,
            "body_excerpt": "Bought $TSLA 300C weeklies.",
            "market": {
                "TSLA": {
                    "symbol": "TSLA",
                    "last_close": 250.0,
                    "pct_1d": 0.03,
                    "market_cap": 800_000_000_000,
                }
            },
        },
    )


@pytest.fixture
def sample_reasoning() -> ReasoningPacket:
    return ReasoningPacket(
        thesis="TSLA showing bullish momentum ahead of earnings with strong Reddit conviction.",
        catalyst_window="Earnings report next week",
        market_expectation="Market pricing in modest upside; IV elevated",
        invalidations=["Earnings miss", "Macro selloff"],
        recommended_structures=["bull call spread 5% OTM, weekly expiry"],
        risk_notes=["High IV means expensive premiums", "Single-source signal"],
        raw={
            "event_type": "earnings_rumor",
            "stance": "bullish",
            "time_horizon": "earnings",
            "confidence": 0.65,
        },
    )
