"""Tests for rot.reasoner.prompts module.

Tests system prompt structure, event prompt template, field substitution,
formatting, and NLP data inclusion.
"""
from __future__ import annotations

from rot.reasoner.prompts import (
    EVENT_TEMPLATE,
    SYSTEM_PROMPT,
    _SUBREDDIT_TIERS,
    _format_nlp_section,
    format_event_prompt,
)


class TestSystemPrompt:
    """Test SYSTEM_PROMPT structure and content."""

    def test_system_prompt_contains_role_definition(self):
        """System prompt should define the analyst role."""
        assert "options trading analyst" in SYSTEM_PROMPT.lower()
        assert "reddit" in SYSTEM_PROMPT.lower()

    def test_system_prompt_requires_json_output(self):
        """System prompt should require JSON output."""
        assert "JSON" in SYSTEM_PROMPT
        assert "json" in SYSTEM_PROMPT.lower()

    def test_system_prompt_defines_schema(self):
        """System prompt should define the output schema."""
        required_fields = [
            "event_type",
            "stance",
            "time_horizon",
            "confidence",
            "thesis",
            "catalyst_window",
            "market_expectation",
            "invalidations",
            "recommended_structures",
            "risk_notes",
        ]
        for field in required_fields:
            assert field in SYSTEM_PROMPT

    def test_system_prompt_defines_event_types(self):
        """System prompt should list valid event types."""
        event_types = [
            "earnings_rumor",
            "product_news",
            "regulatory",
            "squeeze_chatter",
            "macro",
            "other",
        ]
        for event_type in event_types:
            assert event_type in SYSTEM_PROMPT

    def test_system_prompt_defines_stances(self):
        """System prompt should list valid stances."""
        stances = ["bullish", "bearish", "mixed", "unknown"]
        for stance in stances:
            assert stance in SYSTEM_PROMPT

    def test_system_prompt_defines_time_horizons(self):
        """System prompt should list valid time horizons."""
        horizons = ["intraday", "1w", "earnings", "longer", "unknown"]
        for horizon in horizons:
            assert horizon in SYSTEM_PROMPT

    def test_system_prompt_includes_confidence_calibration(self):
        """System prompt should include confidence calibration guidance."""
        assert "confidence" in SYSTEM_PROMPT.lower()
        assert "0.0-1.0" in SYSTEM_PROMPT or "0-1" in SYSTEM_PROMPT
        # Should mention calibration ranges
        assert "0.10" in SYSTEM_PROMPT or "0.1" in SYSTEM_PROMPT
        assert "0.85" in SYSTEM_PROMPT

    def test_system_prompt_includes_hard_caps(self):
        """System prompt should include hard confidence caps."""
        assert "NEVER set confidence >" in SYSTEM_PROMPT
        assert "squeeze_chatter" in SYSTEM_PROMPT
        assert "earnings_rumor" in SYSTEM_PROMPT
        # Should cap squeeze_chatter at 0.65
        assert "0.65" in SYSTEM_PROMPT

    def test_system_prompt_includes_market_data_discounts(self):
        """System prompt should mention market data contradictions."""
        assert "market data contradicts" in SYSTEM_PROMPT.lower() or "contradicts" in SYSTEM_PROMPT

    def test_system_prompt_includes_subreddit_credibility(self):
        """System prompt should mention subreddit credibility adjustments."""
        assert "wallstreetbets" in SYSTEM_PROMPT.lower()
        assert "discount" in SYSTEM_PROMPT.lower()

    def test_system_prompt_includes_rss_boost(self):
        """System prompt should mention RSS feed credibility boost."""
        assert "RSS" in SYSTEM_PROMPT or "rss" in SYSTEM_PROMPT
        assert "boost" in SYSTEM_PROMPT.lower()

    def test_system_prompt_requires_invalidations(self):
        """System prompt should require at least one invalidation."""
        assert "at least one invalidation" in SYSTEM_PROMPT.lower()

    def test_system_prompt_requires_risk_notes(self):
        """System prompt should require at least one risk note."""
        assert "at least one" in SYSTEM_PROMPT.lower()
        assert "risk" in SYSTEM_PROMPT.lower()

    def test_system_prompt_mentions_iv_data(self):
        """System prompt should mention IV (implied volatility) usage."""
        assert "IV" in SYSTEM_PROMPT

    def test_system_prompt_mentions_put_call_ratio(self):
        """System prompt should mention put/call ratio analysis."""
        assert "put/call" in SYSTEM_PROMPT or "put-call" in SYSTEM_PROMPT


class TestSubredditTiers:
    """Test subreddit credibility tier mapping."""

    def test_wsb_is_low_tier(self):
        """WallStreetBets should be low credibility tier."""
        assert _SUBREDDIT_TIERS["wallstreetbets"] == "low"
        assert _SUBREDDIT_TIERS["wallstreetbetsogs"] == "low"

    def test_pennystocks_is_low_tier(self):
        """Penny stocks should be low credibility tier."""
        assert _SUBREDDIT_TIERS["pennystocks"] == "low"

    def test_shortsqueeze_is_low_tier(self):
        """Short squeeze subreddit should be low tier."""
        assert _SUBREDDIT_TIERS["shortsqueeze"] == "low"

    def test_stocks_is_medium_tier(self):
        """General stock subreddits should be medium tier."""
        assert _SUBREDDIT_TIERS["stocks"] == "medium"
        assert _SUBREDDIT_TIERS["stockmarket"] == "medium"

    def test_options_is_high_tier(self):
        """Options subreddit should be high tier."""
        assert _SUBREDDIT_TIERS["options"] == "high"

    def test_thetagang_is_high_tier(self):
        """Theta gang should be high tier."""
        assert _SUBREDDIT_TIERS["thetagang"] == "high"

    def test_investing_is_high_tier(self):
        """Investing subreddits should be high tier."""
        assert _SUBREDDIT_TIERS["investing"] == "high"
        assert _SUBREDDIT_TIERS["valueinvesting"] == "high"


class TestFormatNLPSection:
    """Test NLP data formatting for prompts."""

    def test_format_nlp_section_with_none(self):
        """None NLP data should return empty string."""
        result = _format_nlp_section(None)
        assert result == ""

    def test_format_nlp_section_with_empty_dict(self):
        """Empty NLP dict is falsy in Python, so returns empty string."""
        result = _format_nlp_section({})
        # Empty dict evaluates as falsy in `if not nlp_data`
        assert result == ""

    def test_format_nlp_section_includes_sentiment(self):
        """NLP section should include sentiment polarity and intensity."""
        nlp_data = {
            "polarity": 0.75,
            "intensity": 0.85,
        }
        result = _format_nlp_section(nlp_data)

        assert "polarity" in result.lower()
        assert "0.75" in result or "+0.75" in result
        assert "0.85" in result

    def test_format_nlp_section_includes_conviction(self):
        """NLP section should include conviction score."""
        nlp_data = {
            "conviction": 0.65,
        }
        result = _format_nlp_section(nlp_data)

        assert "conviction" in result.lower()
        assert "0.65" in result

    def test_format_nlp_section_includes_sarcasm(self):
        """NLP section should include sarcasm probability."""
        nlp_data = {
            "sarcasm_probability": 0.8,
        }
        result = _format_nlp_section(nlp_data)

        assert "sarcasm" in result.lower()
        assert "0.80" in result or "0.8" in result

    def test_format_nlp_section_includes_classifications(self):
        """NLP section should include event classifications."""
        nlp_data = {
            "classifications": [
                ("product_news", 0.85),
                ("bullish", 0.7),
                ("regulatory", 0.3),
            ]
        }
        result = _format_nlp_section(nlp_data)

        assert "classification" in result.lower()
        assert "product_news" in result
        assert "0.85" in result

    def test_format_nlp_section_limits_classifications(self):
        """NLP section should limit to top 4 classifications."""
        nlp_data = {
            "classifications": [
                ("cat1", 0.9),
                ("cat2", 0.8),
                ("cat3", 0.7),
                ("cat4", 0.6),
                ("cat5", 0.5),
                ("cat6", 0.4),
            ]
        }
        result = _format_nlp_section(nlp_data)

        # Should include first 4
        assert "cat1" in result
        assert "cat4" in result
        # Should NOT include last 2
        assert "cat5" not in result
        assert "cat6" not in result

    def test_format_nlp_section_includes_temporal(self):
        """NLP section should include temporal analysis."""
        nlp_data = {
            "tense": "future",
            "actionability": 0.75,
            "urgency": 0.6,
        }
        result = _format_nlp_section(nlp_data)

        assert "tense" in result.lower()
        assert "future" in result
        assert "actionability" in result.lower()
        assert "urgency" in result.lower()

    def test_format_nlp_section_includes_thread_consensus(self):
        """NLP section should include thread consensus."""
        nlp_data = {
            "thread_consensus": 0.8,
            "thread_agreement_with_op": 0.7,
            "contrarian_detected": False,
        }
        result = _format_nlp_section(nlp_data)

        assert "thread consensus" in result.lower()
        assert "0.80" in result or "0.8" in result
        assert "agreement" in result.lower()

    def test_format_nlp_section_flags_contrarian(self):
        """NLP section should flag contrarian signals."""
        nlp_data = {
            "thread_consensus": 0.5,
            "contrarian_detected": True,
        }
        result = _format_nlp_section(nlp_data)

        assert "CONTRARIAN" in result

    def test_format_nlp_section_includes_ticker_sentiments(self):
        """NLP section should include per-ticker sentiments."""
        nlp_data = {
            "ticker_sentiments": {
                "AAPL": 0.8,
                "TSLA": -0.3,
                "NVDA": 0.5,
            }
        }
        result = _format_nlp_section(nlp_data)

        assert "ticker" in result.lower()
        assert "AAPL" in result
        assert "TSLA" in result
        assert "0.8" in result or "0.80" in result


class TestFormatEventPrompt:
    """Test event prompt formatting."""

    def test_format_event_prompt_basic(self):
        """Basic event prompt should include all main sections."""
        result = format_event_prompt(
            entities=["TSLA"],
            subreddit="wallstreetbets",
            title="TSLA to the moon!",
            body_excerpt="Full DD inside",
            score=500,
            num_comments=150,
            upvote_ratio=0.85,
            author="test_user",
            flair="DD",
            is_crosspost=False,
            trend_score=0.75,
            score_rate=2.5,
            comment_rate=1.2,
            market_data=None,
            nlp_data=None,
        )

        # Should include Reddit signal section
        assert "Reddit Signal" in result
        assert "TSLA" in result
        assert "wallstreetbets" in result
        assert "TSLA to the moon!" in result

        # Should include metrics
        assert "500" in result
        assert "150" in result
        assert "0.85" in result

        # Should include trend metrics
        assert "Trend" in result
        assert "0.75" in result

        # Should include market context section
        assert "Market Context" in result

    def test_format_event_prompt_includes_subreddit_tier(self):
        """Event prompt should include subreddit credibility tier."""
        result = format_event_prompt(
            entities=["AAPL"],
            subreddit="options",
            title="Test",
            body_excerpt="",
            score=10,
            num_comments=5,
            upvote_ratio=0.9,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=None,
        )

        # Options subreddit is high tier
        assert "high" in result.lower()

    def test_format_event_prompt_defaults_unknown_subreddit_tier(self):
        """Unknown subreddit should default to medium tier."""
        result = format_event_prompt(
            entities=["AAPL"],
            subreddit="unknown_subreddit",
            title="Test",
            body_excerpt="",
            score=10,
            num_comments=5,
            upvote_ratio=0.9,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=None,
        )

        assert "medium" in result.lower()

    def test_format_event_prompt_handles_multiple_entities(self):
        """Event prompt should list all entities."""
        result = format_event_prompt(
            entities=["AAPL", "MSFT", "GOOGL"],
            subreddit="stocks",
            title="Test",
            body_excerpt="",
            score=10,
            num_comments=5,
            upvote_ratio=0.9,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=None,
        )

        assert "AAPL" in result
        assert "MSFT" in result
        assert "GOOGL" in result

    def test_format_event_prompt_handles_no_entities(self):
        """Event prompt should handle empty entity list."""
        result = format_event_prompt(
            entities=[],
            subreddit="stocks",
            title="Test",
            body_excerpt="",
            score=10,
            num_comments=5,
            upvote_ratio=0.9,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=None,
        )

        assert "None extracted" in result

    def test_format_event_prompt_includes_market_data(self):
        """Event prompt should include market data when provided."""
        market_data = {
            "TSLA": {
                "last_close": 250.75,
                "pct_1d": 0.025,
                "market_cap": 800_000_000_000,
            }
        }

        result = format_event_prompt(
            entities=["TSLA"],
            subreddit="stocks",
            title="Test",
            body_excerpt="",
            score=10,
            num_comments=5,
            upvote_ratio=0.9,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=market_data,
        )

        assert "250.75" in result or "250" in result
        assert "2.5%" in result or "2.50%" in result or "+2.5%" in result

    def test_format_event_prompt_includes_options_data(self):
        """Event prompt should include IV and put/call data."""
        market_data = {
            "NVDA": {
                "last_close": 500.0,
                "pct_1d": 0.01,
                "market_cap": 1_000_000_000_000,
                "atm_iv": 0.65,
                "pc_ratio": 1.5,
                "call_oi": 50000,
                "put_oi": 75000,
            }
        }

        result = format_event_prompt(
            entities=["NVDA"],
            subreddit="stocks",
            title="Test",
            body_excerpt="",
            score=10,
            num_comments=5,
            upvote_ratio=0.9,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=market_data,
        )

        assert "65.0%" in result or "65%" in result  # IV
        assert "1.50" in result or "1.5" in result  # P/C ratio
        assert "50,000" in result or "50000" in result  # Call OI
        assert "75,000" in result or "75000" in result  # Put OI

    def test_format_event_prompt_handles_no_market_data(self):
        """Event prompt should handle missing market data."""
        result = format_event_prompt(
            entities=["AAPL"],
            subreddit="stocks",
            title="Test",
            body_excerpt="",
            score=10,
            num_comments=5,
            upvote_ratio=0.9,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=None,
        )

        assert "No market data available" in result

    def test_format_event_prompt_includes_nlp_section(self):
        """Event prompt should include NLP analysis when provided."""
        nlp_data = {
            "polarity": 0.8,
            "intensity": 0.9,
            "conviction": 0.75,
        }

        result = format_event_prompt(
            entities=["AAPL"],
            subreddit="stocks",
            title="Test",
            body_excerpt="",
            score=10,
            num_comments=5,
            upvote_ratio=0.9,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=None,
            nlp_data=nlp_data,
        )

        assert "NLP Analysis" in result
        assert "0.8" in result or "0.80" in result

    def test_format_event_prompt_truncates_long_title(self):
        """Long titles should be truncated to 200 chars."""
        long_title = "A" * 300

        result = format_event_prompt(
            entities=["AAPL"],
            subreddit="stocks",
            title=long_title,
            body_excerpt="",
            score=10,
            num_comments=5,
            upvote_ratio=0.9,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=None,
        )

        # Title in result should be max 200 chars
        assert "A" * 200 in result
        # Should not contain full 300 chars
        assert "A" * 250 not in result

    def test_format_event_prompt_truncates_long_body(self):
        """Long body excerpts should be truncated to 500 chars."""
        long_body = "B" * 1000

        result = format_event_prompt(
            entities=["AAPL"],
            subreddit="stocks",
            title="Test",
            body_excerpt=long_body,
            score=10,
            num_comments=5,
            upvote_ratio=0.9,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=None,
        )

        # Body in result should be max 500 chars
        assert "B" * 500 in result
        # Should not contain full 1000 chars
        assert "B" * 600 not in result

    def test_format_event_prompt_handles_none_upvote_ratio(self):
        """None upvote ratio should display as N/A."""
        result = format_event_prompt(
            entities=["AAPL"],
            subreddit="stocks",
            title="Test",
            body_excerpt="",
            score=10,
            num_comments=5,
            upvote_ratio=None,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=None,
        )

        assert "N/A" in result

    def test_format_event_prompt_handles_none_flair(self):
        """None flair should display as None."""
        result = format_event_prompt(
            entities=["AAPL"],
            subreddit="stocks",
            title="Test",
            body_excerpt="",
            score=10,
            num_comments=5,
            upvote_ratio=0.9,
            author="user",
            flair=None,
            is_crosspost=False,
            trend_score=0.5,
            score_rate=0.1,
            comment_rate=0.05,
            market_data=None,
        )

        assert "None" in result


class TestEventTemplate:
    """Test EVENT_TEMPLATE structure."""

    def test_event_template_has_sections(self):
        """Event template should have clear sections."""
        assert "## Reddit Signal" in EVENT_TEMPLATE
        assert "## Trend Metrics" in EVENT_TEMPLATE
        assert "## Market Context" in EVENT_TEMPLATE

    def test_event_template_has_placeholders(self):
        """Event template should have all necessary placeholders."""
        # Check for key placeholders (some may have format specifiers)
        required_words = [
            "entities",
            "subreddit",
            "title",
            "score",
            "num_comments",
            "upvote_ratio",
            "author",
            "flair",
            "crosspost",
            "trend_score",
            "score_rate",
            "comment_rate",
            "market_context",
            "nlp_section",
        ]

        for word in required_words:
            assert word in EVENT_TEMPLATE or word.replace("_", " ") in EVENT_TEMPLATE
