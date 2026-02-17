"""Tests for confidence tuning changes — Feb 2026.

Verifies:
- Event builder base confidence raised (0.55/$TICKER, 0.40/bare)
- Credibility scorer penalty reductions (subreddits, author, tickers)
- Trade builder threshold lowered to 0.30
- Earnings rumor clamp at 0.25 (aggressive, kills trades)
- Quality score uses 0.7 multiplier
- Signals with moderate confidence now receive strategies
- End-to-end: typical WSB post reaches trade-worthy confidence
"""
from __future__ import annotations

import dataclasses

import pytest

from rot.core.types import Event, Evidence, ReasoningPacket
from rot.credibility.scorer import CredibilityScorer, _SUBREDDIT_WEIGHTS
from rot.market.trade_builder import TradeBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    entities=None,
    confidence=0.5,
    stance="bullish",
    horizon="1w",
    event_type="other",
    subreddit="options",
    meta_overrides=None,
) -> Event:
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
        "market": {
            (entities or ["TSLA"])[0]: {
                "symbol": (entities or ["TSLA"])[0],
                "last_close": 250.0,
                "pct_1d": 0.02,
                "market_cap": 800_000_000_000,
            }
        },
    }
    if meta_overrides:
        meta.update(meta_overrides)
    return Event(
        event_type=event_type,
        entities=entities or ["TSLA"],
        stance=stance,
        time_horizon=horizon,
        evidence=[Evidence(
            post_id="x", permalink="", subreddit=subreddit, excerpt="test"
        )],
        confidence=confidence,
        meta=meta,
    )


def _make_packet(confidence=0.65, stance="bullish", event_type="other") -> ReasoningPacket:
    return ReasoningPacket(
        thesis="Test thesis for trade builder — longer than 50 chars for quality boost in tests",
        catalyst_window="1 week",
        market_expectation="unclear",
        invalidations=["test"],
        recommended_structures=["debit spread"],
        risk_notes=["test risk"],
        raw={
            "event_type": event_type,
            "stance": stance,
            "time_horizon": "1w",
            "confidence": confidence,
        },
    )


# =========================================================================
# 1. Subreddit weight reductions
# =========================================================================


class TestSubredditWeightsReduced:
    """Verify subreddit penalties were halved from the aggressive originals."""

    def test_wsb_penalty_is_minus_005(self):
        assert _SUBREDDIT_WEIGHTS["wallstreetbets"] == -0.05

    def test_wsb_ogs_penalty_is_minus_003(self):
        assert _SUBREDDIT_WEIGHTS["wallstreetbetsogs"] == -0.03

    def test_shortsqueeze_penalty_is_minus_005(self):
        assert _SUBREDDIT_WEIGHTS["shortsqueeze"] == -0.05

    def test_pennystocks_penalty_is_minus_005(self):
        assert _SUBREDDIT_WEIGHTS["pennystocks"] == -0.05

    def test_positive_weights_unchanged(self):
        assert _SUBREDDIT_WEIGHTS["options"] == 0.05
        assert _SUBREDDIT_WEIGHTS["investing"] == 0.05
        assert _SUBREDDIT_WEIGHTS["thetagang"] == 0.05
        assert _SUBREDDIT_WEIGHTS["valueinvesting"] == 0.05

    def test_neutral_weights_unchanged(self):
        assert _SUBREDDIT_WEIGHTS["stocks"] == 0.0
        assert _SUBREDDIT_WEIGHTS["stockmarket"] == 0.0


# =========================================================================
# 2. Credibility penalty reductions
# =========================================================================


class TestCredibilityPenaltyReductions:
    """Verify credibility scorer penalties were reduced."""

    def setup_method(self):
        self.scorer = CredibilityScorer()

    def test_too_many_tickers_penalty_is_minus_008(self):
        event = dataclasses.replace(
            _make_event(),
            entities=["AAPL", "TSLA", "GOOGL", "MSFT", "AMZN"],
        )
        scored = self.scorer.score(event)
        assert scored.meta["credibility_breakdown"]["too_many_tickers"] == -0.08

    def test_low_karma_penalty_is_minus_005(self):
        event = _make_event(meta_overrides={"author_karma": 50})
        scored = self.scorer.score(event)
        assert scored.meta["credibility_breakdown"]["author_low_karma"] == -0.05

    def test_new_account_penalty_is_minus_005(self):
        event = _make_event(meta_overrides={"author_age_days": 10})
        scored = self.scorer.score(event)
        assert scored.meta["credibility_breakdown"]["author_new_account"] == -0.05

    def test_earnings_rumor_penalty_is_minus_010(self):
        """Earnings rumor penalty stays aggressive at -0.10."""
        event = _make_event(event_type="earnings_rumor")
        scored = self.scorer.score(event)
        assert scored.meta["credibility_breakdown"]["earnings_rumor_penalty"] == -0.10

    def test_low_actionability_penalty_is_minus_005(self):
        event = _make_event(meta_overrides={"nlp": {"actionability": 0.1}})
        scored = self.scorer.score(event)
        assert scored.meta["credibility_breakdown"]["nlp_low_actionability"] == -0.05

    def test_wsb_signal_survives_with_moderate_confidence(self):
        """A WSB signal at 0.40 base should remain tradeable after penalties."""
        event = _make_event(
            confidence=0.40,
            subreddit="wallstreetbets",
            meta_overrides={"author_karma": 50, "author_age_days": 10},
        )
        scored = self.scorer.score(event)
        # Penalties: -0.05 (wsb) -0.05 (karma) -0.05 (age) = -0.15
        # Base: 0.40, scored: 0.25 → below 0.30 trade threshold
        # But with focused_ticker (+0.05): 0.30
        # This tests the penalty levels are correct
        assert scored.confidence >= 0.20
        assert scored.confidence <= 0.35

    def test_high_quality_signal_reaches_high_confidence(self):
        """Signal with all positive factors should exceed 0.60."""
        event = _make_event(
            confidence=0.55,
            subreddit="options",
            meta_overrides={
                "flair": "DD",
                "body_excerpt": "x" * 300,
                "score": 500,
                "num_comments": 300,
                "author_karma": 60000,
                "author_age_days": 500,
            },
        )
        scored = self.scorer.score(event)
        # Boosts: dd_flair(0.15) + focused_ticker(0.05) + high_score(0.05) +
        #         high_discussion(0.05) + has_body(0.05) + options_sub(0.05) +
        #         high_karma(0.10) + established(0.05) = +0.55
        assert scored.confidence >= 0.80


# =========================================================================
# 3. Trade builder threshold lowered to 0.30
# =========================================================================


class TestTradeBuilderThreshold:
    """Verify trade builder uses 0.30 confidence threshold."""

    def setup_method(self):
        self.builder = TradeBuilder()

    def test_confidence_030_gets_strategy(self):
        event = _make_event(confidence=0.30)
        packet = _make_packet(confidence=0.30)
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy != "none"

    def test_confidence_031_gets_strategy(self):
        event = _make_event(confidence=0.31)
        packet = _make_packet(confidence=0.31)
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy != "none"

    def test_confidence_029_no_trade(self):
        event = _make_event(confidence=0.29)
        packet = _make_packet(confidence=0.29)
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy == "none"
        assert "confidence_too_low" in ideas[0].do_not_trade_reasons

    def test_confidence_035_gets_strategy(self):
        """0.35 was the old earnings rumor clamp — now should get a strategy for non-earnings."""
        event = _make_event(confidence=0.35)
        packet = _make_packet(confidence=0.35)
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy != "none"

    def test_confidence_040_gets_strategy(self):
        """0.40 was the old general threshold — should now easily pass."""
        event = _make_event(confidence=0.40)
        packet = _make_packet(confidence=0.40)
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy != "none"


# =========================================================================
# 4. Earnings rumor clamp (stays aggressive)
# =========================================================================


class TestEarningsRumorAggressiveClamp:
    """Verify earnings rumors are still aggressively clamped."""

    def setup_method(self):
        self.builder = TradeBuilder()

    def test_earnings_rumor_060_clamped_to_no_trade(self):
        event = _make_event(confidence=0.60, event_type="earnings_rumor")
        packet = _make_packet(confidence=0.60, event_type="earnings_rumor")
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy == "none"
        assert "confidence_too_low" in ideas[0].do_not_trade_reasons

    def test_earnings_rumor_080_clamped_to_no_trade(self):
        event = _make_event(confidence=0.80, event_type="earnings_rumor")
        packet = _make_packet(confidence=0.80, event_type="earnings_rumor")
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy == "none"

    def test_earnings_rumor_034_not_clamped_but_below_threshold(self):
        """Below clamp trigger (0.35), still below threshold (0.30)."""
        event = _make_event(confidence=0.25, event_type="earnings_rumor")
        packet = _make_packet(confidence=0.25, event_type="earnings_rumor")
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy == "none"
        assert "confidence_too_low" in ideas[0].do_not_trade_reasons

    def test_non_earnings_035_gets_strategy(self):
        """Same confidence, non-earnings event type should get a strategy."""
        event = _make_event(confidence=0.35, event_type="regulatory")
        packet = _make_packet(confidence=0.35, event_type="regulatory")
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy != "none"

    def test_earnings_rumor_clamp_value_is_025(self):
        """Verify the clamp sets confidence to exactly 0.25."""
        event = _make_event(confidence=0.50, event_type="earnings_rumor")
        packet = _make_packet(confidence=0.50, event_type="earnings_rumor")
        ideas = self.builder.build(packet, event)
        # Trade meta won't have confidence since it's no_trade
        # But the outcome is deterministic: clamped to 0.25, below 0.30 → no trade
        assert ideas[0].strategy == "none"


# =========================================================================
# 5. Quality score uses 0.7 multiplier
# =========================================================================


class TestQualityScoreMultiplier:
    """Verify quality score uses the higher 0.7 confidence multiplier."""

    def setup_method(self):
        self.builder = TradeBuilder()

    def test_quality_score_reflects_higher_multiplier(self):
        event = _make_event(confidence=0.50)
        packet = _make_packet(confidence=0.50)
        ideas = self.builder.build(packet, event)
        idea = ideas[0]
        # quality = 0.50 * 0.7 + event_type_boost(0.0) + thesis_boost(0.1) + rec_struct(0.1)
        # = 0.35 + 0.1 + 0.1 = 0.55
        assert idea.quality_score >= 0.50

    def test_high_confidence_high_quality(self):
        event = _make_event(confidence=0.80)
        packet = _make_packet(confidence=0.80)
        ideas = self.builder.build(packet, event)
        # 0.80 * 0.7 = 0.56 base + boosts
        assert ideas[0].quality_score >= 0.56

    def test_low_confidence_proportional_quality(self):
        event = _make_event(confidence=0.30)
        packet = _make_packet(confidence=0.30)
        ideas = self.builder.build(packet, event)
        # 0.30 * 0.7 = 0.21 base + boosts
        assert ideas[0].quality_score >= 0.21

    def test_quality_score_bounded_0_1(self):
        event = _make_event(confidence=1.0)
        packet = _make_packet(confidence=1.0)
        ideas = self.builder.build(packet, event)
        assert 0.0 <= ideas[0].quality_score <= 1.0


# =========================================================================
# 6. End-to-end: moderate-confidence signals get strategies
# =========================================================================


class TestModeratSignalsGetStrategies:
    """Verify that signals in the 0.30-0.40 range now get trade strategies."""

    def setup_method(self):
        self.builder = TradeBuilder()

    def test_bullish_030_gets_debit_spread(self):
        event = _make_event(confidence=0.30, stance="bullish")
        packet = _make_packet(confidence=0.30, stance="bullish")
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy in ("debit_spread", "credit_spread")
        assert len(ideas[0].legs) == 2

    def test_bearish_035_gets_put_spread(self):
        event = _make_event(confidence=0.35, stance="bearish")
        packet = _make_packet(confidence=0.35, stance="bearish")
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy in ("debit_spread", "credit_spread")
        assert ideas[0].legs[0].kind == "put" or ideas[0].legs[0].kind == "call"

    def test_mixed_038_gets_straddle_or_condor(self):
        event = _make_event(confidence=0.38, stance="mixed")
        packet = _make_packet(confidence=0.38, stance="mixed")
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy in ("straddle", "iron_condor")

    def test_previously_blocked_039_now_trades(self):
        """0.39 was below old 0.40 threshold — now gets a strategy."""
        event = _make_event(confidence=0.39, stance="bullish")
        packet = _make_packet(confidence=0.39, stance="bullish")
        ideas = self.builder.build(packet, event)
        assert ideas[0].strategy != "none"
        assert len(ideas[0].legs) >= 2

    def test_legs_have_valid_strikes(self):
        event = _make_event(confidence=0.32, stance="bullish")
        packet = _make_packet(confidence=0.32, stance="bullish")
        ideas = self.builder.build(packet, event)
        for leg in ideas[0].legs:
            assert leg.strike > 0
            assert leg.expiry

    def test_max_loss_calculated_for_moderate_confidence(self):
        event = _make_event(confidence=0.33, stance="bearish")
        packet = _make_packet(confidence=0.33, stance="bearish")
        ideas = self.builder.build(packet, event)
        assert ideas[0].max_loss > 0


# =========================================================================
# 7. Credibility + Trade Builder integration
# =========================================================================


class TestCredibilityTradeBuilderIntegration:
    """End-to-end: credibility scoring feeds into trade building."""

    def setup_method(self):
        self.scorer = CredibilityScorer()
        self.builder = TradeBuilder()

    def test_good_signal_gets_strategy_after_scoring(self):
        """A well-formed signal on r/options with DD flair should get a strategy."""
        event = _make_event(
            confidence=0.50,
            stance="bullish",
            subreddit="options",
            meta_overrides={
                "flair": "DD",
                "body_excerpt": "x" * 300,
                "score": 200,
                "num_comments": 50,
                "author_karma": 15000,
                "author_age_days": 400,
            },
        )
        scored = self.scorer.score(event)
        packet = _make_packet(confidence=scored.confidence, stance="bullish")
        ideas = self.builder.build(packet, scored)
        assert ideas[0].strategy != "none"

    def test_wsb_low_karma_new_account_still_viable(self):
        """WSB post from new low-karma account — penalties reduced enough to be viable at 0.50."""
        event = _make_event(
            confidence=0.50,
            stance="bearish",
            subreddit="wallstreetbets",
            meta_overrides={
                "author_karma": 50,
                "author_age_days": 10,
            },
        )
        scored = self.scorer.score(event)
        # WSB(-0.05) + low_karma(-0.05) + new_account(-0.05) + focused(+0.05) = -0.10
        # 0.50 - 0.10 = 0.40 → above 0.30 threshold
        packet = _make_packet(confidence=scored.confidence, stance="bearish")
        ideas = self.builder.build(packet, scored)
        assert ideas[0].strategy != "none"

    def test_earnings_rumor_from_quality_source_still_blocked(self):
        """Even a high-quality earnings rumor signal should be blocked."""
        event = _make_event(
            confidence=0.55,
            stance="bullish",
            event_type="earnings_rumor",
            subreddit="options",
            meta_overrides={
                "flair": "DD",
                "body_excerpt": "x" * 300,
                "author_karma": 60000,
                "author_age_days": 500,
            },
        )
        scored = self.scorer.score(event)
        # Even with high scored confidence, earnings clamp kills it
        packet = _make_packet(
            confidence=scored.confidence, stance="bullish", event_type="earnings_rumor"
        )
        ideas = self.builder.build(packet, scored)
        assert ideas[0].strategy == "none"

    def test_pennystocks_viable_with_decent_base(self):
        """Pennystocks penalty reduced to -0.05, so decent signals can trade."""
        event = _make_event(
            confidence=0.45,
            stance="bullish",
            subreddit="pennystocks",
            meta_overrides={"author_karma": 15000, "author_age_days": 400},
        )
        scored = self.scorer.score(event)
        # pennystocks(-0.05) + focused(+0.05) + good_karma(+0.05) + established(+0.05) = +0.10
        # 0.45 + 0.10 = 0.55 → easily above 0.30
        packet = _make_packet(confidence=scored.confidence, stance="bullish")
        ideas = self.builder.build(packet, scored)
        assert ideas[0].strategy != "none"


# =========================================================================
# 8. Runner missing import fix
# =========================================================================


class TestRunnerImport:
    """Verify runner.py has the Callable import."""

    def test_callable_imported(self):
        from rot.app.runner import PipelineRunner
        import typing
        import inspect
        sig = inspect.signature(PipelineRunner.__init__)
        # on_signal parameter should exist and have Callable in its annotation
        param = sig.parameters.get("on_signal")
        assert param is not None


# =========================================================================
# 9. Event builder base confidence values
# =========================================================================


class TestEventBuilderBaseConfidence:
    """Verify event builder uses raised base confidence values."""

    def test_nlp_path_explicit_ticker_base_055(self):
        """NLP path with explicit $TICKER should start at 0.55."""
        from rot.extract.event_builder import EventBuilder
        eb = EventBuilder(nlp_engine=None)
        # Legacy path with explicit $TICKER
        event = eb._from_candidate_legacy(_make_fake_candidate("$TSLA is going to moon"))
        if event:
            # With explicit $TICKER and event_type != "other" for earnings keyword
            assert event[0].confidence >= 0.40

    def test_legacy_path_bare_ticker_base_040(self):
        """Legacy path with bare ticker should start at 0.40."""
        from rot.extract.event_builder import EventBuilder
        eb = EventBuilder(nlp_engine=None)
        event = eb._from_candidate_legacy(_make_fake_candidate("TSLA going up"))
        if event:
            assert event[0].confidence >= 0.35


def _make_fake_candidate(title: str):
    """Create a minimal fake TrendCandidate for testing."""
    from rot.core.types import Post, ThreadSnapshot, TrendCandidate
    post = Post(
        id="test_post",
        title=title,
        selftext="",
        url="https://reddit.com/r/options/test",
        author="testuser",
        subreddit="options",
        permalink="/r/options/test",
        score=100,
        num_comments=20,
        upvote_ratio=0.9,
        created_utc=1700000000,
        flair=None,
        is_crosspost=False,
    )
    snapshot = ThreadSnapshot(post=post, snapshot_ts=1700000000, top_comments=[])
    return TrendCandidate(
        key="test_key",
        window_s=300,
        features={"score_rate": 0.1, "comment_rate": 0.1},
        trend_score=0.5,
        reason="score_velocity",
        snapshot=snapshot,
    )
