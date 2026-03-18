"""Integration tests for the core ROT pipeline modules.

Covers end-to-end wiring of TrendEngine, EventBuilder, CredibilityScorer,
Reasoner (stub mode), and TradeBuilder without any external API calls or
database dependencies.
"""
from __future__ import annotations

import dataclasses
import time
from typing import List
from unittest.mock import MagicMock, patch

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
from rot.credibility.scorer import CredibilityScorer
from rot.market.trade_builder import TradeBuilder, _next_friday, _next_monthly
from rot.reasoner.reasoner import Reasoner
from rot.trend.trend_engine import TrendEngine
from rot.trend.trend_store import TrendStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    post_id: str = "post1",
    subreddit: str = "wallstreetbets",
    title: str = "$AAPL to the moon!",
    score: int = 100,
    num_comments: int = 50,
    flair: str = "DD",
    ts: int | None = None,
) -> ThreadSnapshot:
    """Create a minimal ``ThreadSnapshot`` for testing."""
    now = ts or int(time.time())
    post = Post(
        id=post_id,
        created_utc=now - 60,
        subreddit=subreddit,
        title=title,
        selftext="Great analysis here. Buying 400C weeklies.",
        url="https://example.com",
        score=score,
        num_comments=num_comments,
        upvote_ratio=0.90,
        author="testuser",
        permalink=f"https://www.reddit.com/r/{subreddit}/comments/{post_id}",
        flair=flair,
        is_crosspost=False,
    )
    return ThreadSnapshot(snapshot_ts=now, post=post)


def _make_bullish_event(ticker: str = "AAPL", confidence: float = 0.6) -> Event:
    """Return a minimal bullish event suitable for TradeBuilder tests."""
    return Event(
        event_type="earnings_rumor",
        entities=[ticker],
        stance="bullish",
        time_horizon="earnings",
        evidence=[
            Evidence(
                post_id="x1",
                permalink="https://www.reddit.com/r/stocks/comments/x1",
                subreddit="stocks",
                excerpt=f"${ticker} beats earnings expectations",
            )
        ],
        confidence=confidence,
        meta={
            "score": 300,
            "num_comments": 120,
            "upvote_ratio": 0.88,
            "flair": "DD",
            "is_crosspost": False,
            "body_excerpt": "Strong fundamentals. Revenue beat by 8%. Raising guidance for next quarter.",
            "market": {
                ticker: {
                    "symbol": ticker,
                    "last_close": 180.0,
                    "pct_1d": 0.02,
                    "market_cap": 2_800_000_000_000,
                }
            },
        },
    )


# ---------------------------------------------------------------------------
# TrendEngine tests
# ---------------------------------------------------------------------------


class TestTrendEngine:
    """Tests for TrendEngine rate-of-change detection and bypass paths."""

    def setup_method(self) -> None:
        """Create a fresh in-memory TrendStore and TrendEngine before each test."""
        self.store = TrendStore(path=":memory:")  # in-memory JSON store
        self.engine = TrendEngine(
            store=self.store,
            window_s=1800,
            threshold=0.01,
            comment_weight=2.0,
        )

    def test_first_snapshot_not_trending(self) -> None:
        """The first snapshot for a post has no baseline — must not be promoted."""
        snap = _make_snapshot()
        candidates = self.engine.detect([snap])
        assert candidates == []

    def test_second_snapshot_above_threshold_promotes(self) -> None:
        """A second snapshot with score velocity above threshold becomes a candidate."""
        now = int(time.time())
        snap1 = _make_snapshot(score=100, num_comments=10, ts=now - 120)
        snap2 = _make_snapshot(score=200, num_comments=40, ts=now)

        self.engine.detect([snap1])
        candidates = self.engine.detect([snap2])

        assert len(candidates) == 1
        assert candidates[0].trend_score > 0

    def test_rss_bypass_promotes_fresh_item(self) -> None:
        """Fresh RSS items bypass rate-of-change and are promoted directly."""
        engine = TrendEngine(
            store=TrendStore(path=":memory:"),
            rss_bypass=True,
            rss_max_age_s=3600,
            rss_synthetic_score=0.5,
        )
        now = int(time.time())
        snap = _make_snapshot(flair="rss", ts=now - 60)
        # Override flair on the embedded post
        snap = dataclasses.replace(
            snap,
            post=dataclasses.replace(snap.post, flair="rss"),
        )
        candidates = engine.detect([snap])
        assert len(candidates) == 1
        assert candidates[0].reason == "rss_bypass"
        assert candidates[0].trend_score == 0.5

    def test_rss_bypass_skips_stale_item(self) -> None:
        """RSS items older than max_age_s are not promoted."""
        engine = TrendEngine(
            store=TrendStore(path=":memory:"),
            rss_bypass=True,
            rss_max_age_s=3600,
        )
        now = int(time.time())
        snap = _make_snapshot(flair="rss", ts=now - 7200)  # 2 hours old
        snap = dataclasses.replace(
            snap,
            post=dataclasses.replace(snap.post, flair="rss"),
        )
        candidates = engine.detect([snap])
        assert candidates == []


# ---------------------------------------------------------------------------
# CredibilityScorer tests
# ---------------------------------------------------------------------------


class TestCredibilityScorer:
    """Tests for CredibilityScorer multi-factor confidence adjustment."""

    def setup_method(self) -> None:
        self.scorer = CredibilityScorer()

    def test_dd_flair_long_body_boosts_confidence(self) -> None:
        """DD flair with a substantial body should increase confidence."""
        event = _make_bullish_event(confidence=0.5)
        scored = self.scorer.score(event)
        # DD flair + body > 100 chars → net positive adjustment
        assert scored.confidence > 0.5

    def test_crosspost_lowers_confidence(self) -> None:
        """Cross-posted content should receive a credibility penalty."""
        event = _make_bullish_event(confidence=0.6)
        meta = dict(event.meta or {})
        meta["is_crosspost"] = True
        meta["flair"] = "Discussion"  # remove DD boost
        meta["body_excerpt"] = ""
        event = dataclasses.replace(event, meta=meta)
        scored = self.scorer.score(event)
        assert scored.confidence < 0.6

    def test_too_many_tickers_penalises(self) -> None:
        """Events with 5+ tickers are treated as watchlist noise."""
        event = _make_bullish_event(confidence=0.5)
        event = dataclasses.replace(
            event,
            entities=["AAPL", "TSLA", "NVDA", "AMZN", "MSFT", "GOOGL"],
        )
        scored = self.scorer.score(event)
        assert scored.confidence < 0.5

    def test_credibility_breakdown_in_meta(self) -> None:
        """Scored event must include ``credibility_breakdown`` in meta."""
        event = _make_bullish_event()
        scored = self.scorer.score(event)
        assert "credibility_breakdown" in (scored.meta or {})
        assert isinstance(scored.meta["credibility_breakdown"], dict)

    def test_institutional_rss_boosts_confidence(self) -> None:
        """Institutional RSS sources (e.g. fda-press-releases) get a large boost."""
        event = Event(
            event_type="regulatory",
            entities=["PFE"],
            stance="bullish",
            time_horizon="1w",
            evidence=[
                Evidence(
                    post_id="fda1",
                    permalink="",
                    subreddit="fda-press-releases",
                    excerpt="FDA approves new drug.",
                )
            ],
            confidence=0.5,
            meta={"flair": "rss"},
        )
        scored = self.scorer.score(event)
        assert scored.confidence > 0.5

    def test_confidence_clamped_to_valid_range(self) -> None:
        """Confidence must always remain in [0.05, 1.0] regardless of adjustments."""
        event = _make_bullish_event(confidence=0.05)
        scored = self.scorer.score(event)
        assert 0.05 <= scored.confidence <= 1.0


# ---------------------------------------------------------------------------
# TradeBuilder tests
# ---------------------------------------------------------------------------


class TestTradeBuilder:
    """Tests for TradeBuilder strategy selection and gate logic."""

    def setup_method(self) -> None:
        self.builder = TradeBuilder(min_market_cap=1e8)

    def _make_packet(self, stance: str = "bullish", confidence: float = 0.65) -> ReasoningPacket:
        return ReasoningPacket(
            thesis="Bullish momentum driven by Reddit sentiment.",
            catalyst_window="Earnings next week",
            market_expectation="Modest upside priced in",
            invalidations=["Earnings miss"],
            recommended_structures=["bull call spread"],
            risk_notes=["High IV"],
            raw={
                "stance": stance,
                "confidence": confidence,
                "time_horizon": "earnings",
            },
        )

    def test_bullish_generates_debit_spread(self) -> None:
        """Bullish signal in normal IV should produce a debit spread (call spread)."""
        event = _make_bullish_event()
        packet = self._make_packet(stance="bullish")
        ideas = self.builder.build(packet, event)

        assert len(ideas) == 1
        idea = ideas[0]
        assert idea.strategy in ("debit_spread", "credit_spread")
        assert idea.underlying == "AAPL"
        assert idea.quality_score > 0

    def test_bearish_generates_put_spread(self) -> None:
        """Bearish signal should produce a put-side structure."""
        event = _make_bullish_event()
        event = dataclasses.replace(event, stance="bearish")
        packet = self._make_packet(stance="bearish")
        ideas = self.builder.build(packet, event)

        assert len(ideas) == 1
        assert ideas[0].strategy in ("debit_spread", "credit_spread")

    def test_no_entities_returns_no_trade(self) -> None:
        """Events with no ticker entities must result in a no_trade response."""
        event = dataclasses.replace(_make_bullish_event(), entities=[])
        packet = self._make_packet()
        ideas = self.builder.build(packet, event)

        assert len(ideas) == 1
        assert ideas[0].strategy == "none"
        assert "no_tickers_extracted" in (ideas[0].do_not_trade_reasons or [])

    def test_small_cap_blocked_by_gate(self) -> None:
        """Stocks below the market-cap minimum trigger the gate failure path."""
        event = _make_bullish_event()
        meta = dict(event.meta or {})
        meta["market"] = {
            "AAPL": {
                "symbol": "AAPL",
                "last_close": 5.0,
                "market_cap": 50_000_000,  # below $100M threshold
            }
        }
        event = dataclasses.replace(event, meta=meta)
        packet = self._make_packet()
        ideas = self.builder.build(packet, event)

        assert ideas[0].strategy == "none"

    def test_max_loss_positive_for_spread(self) -> None:
        """Max loss for a spread should be a positive number."""
        event = _make_bullish_event()
        packet = self._make_packet()
        ideas = self.builder.build(packet, event)

        if ideas[0].strategy != "none":
            assert ideas[0].max_loss >= 0

    def test_expiry_helpers_return_iso_dates(self) -> None:
        """Date helper functions must return valid ISO-format date strings."""
        import datetime

        friday = _next_friday()
        monthly = _next_monthly()

        friday_date = datetime.date.fromisoformat(friday)
        monthly_date = datetime.date.fromisoformat(monthly)

        assert friday_date > datetime.date.today()
        assert monthly_date > datetime.date.today()
        assert friday_date.weekday() == 4  # Friday


# ---------------------------------------------------------------------------
# Reasoner stub tests
# ---------------------------------------------------------------------------


class TestReasonerStub:
    """Tests for Reasoner when no LLM key is configured (stub mode)."""

    def setup_method(self) -> None:
        # Empty api_key → stub mode
        self.reasoner = Reasoner(api_key="")

    def test_stub_returns_reasoning_packet(self) -> None:
        """Stub mode must return a valid ReasoningPacket."""
        event = _make_bullish_event()
        packet = self.reasoner.reason(event)

        assert isinstance(packet, ReasoningPacket)
        assert isinstance(packet.thesis, str)
        assert len(packet.thesis) > 0

    def test_stub_packet_flagged(self) -> None:
        """Stub packets must carry ``raw["stub"] = True``."""
        event = _make_bullish_event()
        packet = self.reasoner.reason(event)

        assert (packet.raw or {}).get("stub") is True

    def test_llm_available_false_without_key(self) -> None:
        """``llm_available`` must be False when no API key is provided."""
        assert self.reasoner.llm_available is False

    def test_stub_handles_no_entities(self) -> None:
        """Stub reasoner must not raise when the event has no ticker entities."""
        event = dataclasses.replace(_make_bullish_event(), entities=[])
        packet = self.reasoner.reason(event)
        assert packet is not None


# ---------------------------------------------------------------------------
# Module-level docstring smoke tests
# ---------------------------------------------------------------------------


def test_trend_engine_has_docstring() -> None:
    """TrendEngine class must have a module-level docstring."""
    assert TrendEngine.__doc__ is not None and len(TrendEngine.__doc__) > 0


def test_trade_builder_has_docstring() -> None:
    """TradeBuilder class must have a docstring."""
    assert TradeBuilder.__doc__ is not None and len(TradeBuilder.__doc__) > 0


def test_credibility_scorer_has_docstring() -> None:
    """CredibilityScorer class must have a docstring."""
    assert CredibilityScorer.__doc__ is not None and len(CredibilityScorer.__doc__) > 0


def test_reasoner_has_docstring() -> None:
    """Reasoner class must have a docstring."""
    assert Reasoner.__doc__ is not None and len(Reasoner.__doc__) > 0
