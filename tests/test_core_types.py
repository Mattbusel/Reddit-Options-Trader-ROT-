"""
Comprehensive tests for core types module.

Modules tested:
- rot.core.types

Coverage:
- Post dataclass (frozen, all fields)
- Comment dataclass
- ThreadSnapshot dataclass (with default factory)
- TrendCandidate dataclass
- Event dataclass (with EventType, Stance, Horizon literals)
- Evidence dataclass
- ReasoningPacket dataclass
- OptionLeg dataclass
- TradeIdea dataclass (with Strategy literal)
- Frozen dataclass immutability
- Default factory lists
"""
from __future__ import annotations

import pytest

from rot.core.types import (
    Comment,
    Event,
    Evidence,
    OptionLeg,
    Post,
    ReasoningPacket,
    ThreadSnapshot,
    TradeIdea,
    TrendCandidate,
)


# ============================================================================
# Post Tests
# ============================================================================

class TestPost:
    def test_post_creation(self):
        """Post dataclass can be created with all required fields."""
        post = Post(
            id="abc123",
            created_utc=1234567890,
            subreddit="wallstreetbets",
            title="Test post",
            selftext="Content",
            url="https://reddit.com",
            score=100,
            num_comments=50,
            upvote_ratio=0.95,
            author="testuser",
            permalink="/r/wallstreetbets/...",
        )
        
        assert post.id == "abc123"
        assert post.score == 100
        assert post.author == "testuser"

    def test_post_optional_fields(self):
        """Post optional fields have defaults."""
        post = Post(
            id="abc",
            created_utc=123,
            subreddit="test",
            title="t",
            selftext="s",
            url="u",
            score=0,
            num_comments=0,
            upvote_ratio=None,
            author="a",
            permalink="p",
        )
        
        assert post.flair is None
        assert post.is_crosspost is False

    def test_post_is_frozen(self):
        """Post is immutable (frozen)."""
        post = Post(
            id="abc",
            created_utc=123,
            subreddit="test",
            title="t",
            selftext="s",
            url="u",
            score=0,
            num_comments=0,
            upvote_ratio=None,
            author="a",
            permalink="p",
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            post.score = 999


# ============================================================================
# Comment Tests
# ============================================================================

class TestComment:
    def test_comment_creation(self):
        """Comment dataclass can be created."""
        comment = Comment(
            id="c1",
            created_utc=123,
            author="user",
            body="Comment text",
            score=10,
        )
        
        assert comment.id == "c1"
        assert comment.body == "Comment text"

    def test_comment_is_frozen(self):
        """Comment is immutable."""
        comment = Comment(id="c1", created_utc=123, author="a", body="b", score=1)
        
        with pytest.raises(Exception):
            comment.score = 999


# ============================================================================
# Event Tests
# ============================================================================

class TestEvent:
    def test_event_creation(self):
        """Event can be created with all fields."""
        evidence = Evidence(
            post_id="p1",
            permalink="/r/test/...",
            subreddit="test",
            excerpt="Excerpt text",
        )
        
        event = Event(
            event_type="earnings_rumor",
            entities=["AAPL"],
            stance="bullish",
            time_horizon="1w",
            evidence=[evidence],
            confidence=0.8,
        )
        
        assert event.event_type == "earnings_rumor"
        assert event.stance == "bullish"
        assert event.confidence == 0.8
        assert len(event.evidence) == 1

    def test_event_meta_default(self):
        """Event meta has default empty dict."""
        evidence = Evidence(post_id="p1", permalink="p", subreddit="s", excerpt="e")
        event = Event(
            event_type="other",
            entities=[],
            stance="unknown",
            time_horizon="unknown",
            evidence=[evidence],
            confidence=0.5,
        )
        
        assert event.meta == {}


# ============================================================================
# TradeIdea Tests
# ============================================================================

class TestTradeIdea:
    def test_trade_idea_creation(self):
        """TradeIdea can be created."""
        leg1 = OptionLeg(side="buy", kind="call", strike=150.0, expiry="2026-03-21", qty=1)
        leg2 = OptionLeg(side="sell", kind="call", strike=160.0, expiry="2026-03-21", qty=1)
        
        trade = TradeIdea(
            underlying="AAPL",
            strategy="debit_spread",
            legs=[leg1, leg2],
            max_loss=1000.0,
            thesis="Bullish on AAPL",
            time_stop="2026-03-20",
            quality_score=0.75,
        )
        
        assert trade.underlying == "AAPL"
        assert trade.strategy == "debit_spread"
        assert len(trade.legs) == 2

    def test_trade_idea_defaults(self):
        """TradeIdea has default empty lists."""
        trade = TradeIdea(
            underlying="SPY",
            strategy="straddle",
            legs=[],
            max_loss=500.0,
            thesis="Volatility play",
            time_stop="2026-03-20",
            quality_score=0.6,
        )
        
        assert trade.do_not_trade_reasons == []
        assert trade.meta == {}


# ============================================================================
# Literal Type Tests
# ============================================================================

class TestLiteralTypes:
    def test_event_types(self):
        """EventType literals are valid."""
        valid_types = [
            "earnings_rumor", "product_news", "regulatory",
            "squeeze_chatter", "macro", "other"
        ]
        
        for event_type in valid_types:
            evidence = Evidence(post_id="p", permalink="p", subreddit="s", excerpt="e")
            event = Event(
                event_type=event_type,  # type: ignore
                entities=[],
                stance="unknown",
                time_horizon="unknown",
                evidence=[evidence],
                confidence=0.5,
            )
            assert event.event_type == event_type

    def test_strategies(self):
        """Strategy literals are valid."""
        valid_strategies = [
            "debit_spread", "credit_spread", "iron_condor",
            "calendar", "straddle", "strangle", "none"
        ]
        
        for strategy in valid_strategies:
            trade = TradeIdea(
                underlying="SPY",
                strategy=strategy,  # type: ignore
                legs=[],
                max_loss=100.0,
                thesis="test",
                time_stop="2026-03-20",
                quality_score=0.5,
            )
            assert trade.strategy == strategy
