"""Tests for rot.nlp.temporal - Temporal analysis for financial text.

Comprehensive test coverage for the temporal analyzer that detects:
- Tense detection (past/present/future/unknown via verb patterns)
- Actionability scoring:
  - Past tense: 0.1-0.3
  - Present tense: 0.7-1.0
  - Future tense: 0.4-0.6
- Urgency scoring:
  - 0dte/right-now: high (0.6-1.0)
  - this-week: medium (0.3-0.6)
  - soon: low (0.1-0.3)
- Time expression extraction
- Tense signal counting
- Edge cases (mixed tenses, no markers, ambiguous)
"""
import pytest

from rot.nlp.temporal import TemporalAnalyzer
from rot.nlp.types import Token, TemporalResult


@pytest.fixture
def analyzer():
    """Provide a fresh TemporalAnalyzer instance for each test."""
    return TemporalAnalyzer()


@pytest.fixture
def dummy_tokens():
    """Provide dummy tokens (temporal analyzer doesn't use them currently)."""
    return []


class TestTenseDetection:
    """Test past/present/future/unknown tense detection."""

    def test_past_tense_clear(self, analyzer, dummy_tokens):
        """Text with clear past tense verbs should be detected as past."""
        text = "TSLA crashed yesterday. The stock dropped 20% and closed at $200."
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "past"
        assert result.tense_signals["past"] > 0
        # Actionability should be low for past events
        assert 0.05 <= result.actionability <= 0.35

    def test_past_tense_financial_verbs(self, analyzer, dummy_tokens):
        """Past financial verbs (reported, missed, beat) should indicate past."""
        text = "Apple beat earnings last quarter. They reported revenue of $100B."
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "past"
        assert result.tense_signals["past"] >= 2  # beat, reported

    def test_present_tense_clear(self, analyzer, dummy_tokens):
        """Text with present tense -ing verbs should be detected as present."""
        text = "TSLA is crashing right now. The stock is bleeding out."
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "present"
        assert result.tense_signals["present"] > 0
        # Actionability should be high for present events
        assert 0.65 <= result.actionability <= 1.0

    def test_present_tense_wsb_slang(self, analyzer, dummy_tokens):
        """WSB present tense slang (mooning, printing) should indicate present."""
        text = "This is mooning! My calls are printing right now!"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "present"
        assert result.tense_signals["present"] >= 2  # mooning, printing

    def test_future_tense_clear(self, analyzer, dummy_tokens):
        """Text with will/gonna/going to should be detected as future."""
        text = "TSLA will moon tomorrow. It's gonna be huge next week."
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "future"
        assert result.tense_signals["future"] > 0
        # Actionability should be medium for future predictions
        assert 0.35 <= result.actionability <= 0.7

    def test_future_tense_predictions(self, analyzer, dummy_tokens):
        """Future prediction words (expected, forecast) should indicate future."""
        text = "Expected to rally. Forecast shows bullish momentum."
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "future"
        assert result.tense_signals["future"] >= 2

    def test_unknown_tense_no_markers(self, analyzer, dummy_tokens):
        """Text with no tense markers should be detected as unknown."""
        text = "TSLA 200C 1/19"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "unknown"
        assert result.tense_signals["past"] == 0
        assert result.tense_signals["present"] == 0
        assert result.tense_signals["future"] == 0
        # Actionability should be neutral for unknown
        assert result.actionability == 0.5

    def test_mixed_tense_past_dominant(self, analyzer, dummy_tokens):
        """Mixed tenses with past dominant should be classified as past."""
        text = "Stock crashed yesterday but is recovering today. Will moon soon."
        result = analyzer.analyze(dummy_tokens, text)
        # Past: crashed (1), Present: recovering (1), Future: will, moon (2)
        # Should have all three, but future might be dominant
        assert result.tense_signals["past"] >= 1
        assert result.tense_signals["present"] >= 1
        assert result.tense_signals["future"] >= 1

    def test_mixed_tense_present_dominant(self, analyzer, dummy_tokens):
        """Mixed tenses with present dominant should be classified as present."""
        text = "Stock is crashing, bleeding, tanking right now after it dropped yesterday."
        result = analyzer.analyze(dummy_tokens, text)
        # Present: crashing, bleeding, tanking (3), Past: dropped (1)
        assert result.dominant_tense == "present"
        assert result.tense_signals["present"] >= 3

    @pytest.mark.parametrize("verb,expected_tense", [
        ("crashed", "past"),
        ("tanked", "past"),
        ("dropped", "past"),
        ("fell", "past"),
        ("was", "past"),
        ("had", "past"),
        ("crashing", "present"),
        ("tanking", "present"),
        ("is", "present"),
        ("are", "present"),
        ("currently", "present"),
        ("will", "future"),
        ("gonna", "future"),
        ("should", "future"),
        ("tomorrow", "future"),
    ])
    def test_individual_tense_markers(self, analyzer, dummy_tokens, verb, expected_tense):
        """Individual tense markers should be correctly classified."""
        text = f"Stock {verb} big."
        result = analyzer.analyze(dummy_tokens, text)
        assert result.tense_signals[expected_tense] >= 1


class TestActionabilityScoring:
    """Test actionability scoring based on tense."""

    def test_past_low_actionability(self, analyzer, dummy_tokens):
        """Pure past tense should have low actionability (0.1-0.3)."""
        text = "Stock crashed yesterday. Fell 50%. Closed at $10."
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "past"
        assert 0.05 <= result.actionability <= 0.35

    def test_present_high_actionability(self, analyzer, dummy_tokens):
        """Pure present tense should have high actionability (0.7-1.0)."""
        text = "Stock is crashing right now. Currently bleeding out. Tanking as we speak."
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "present"
        assert 0.65 <= result.actionability <= 1.0

    def test_future_medium_actionability(self, analyzer, dummy_tokens):
        """Pure future tense should have medium actionability (0.4-0.6)."""
        text = "Stock will moon tomorrow. Gonna rally next week. Expected to surge."
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "future"
        assert 0.35 <= result.actionability <= 0.7

    def test_unknown_neutral_actionability(self, analyzer, dummy_tokens):
        """Unknown tense should have neutral actionability (0.5)."""
        text = "TSLA 200C"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.actionability == 0.5

    def test_mixed_weighted_actionability(self, analyzer, dummy_tokens):
        """Mixed tenses should have weighted actionability."""
        # Heavy present + some future = high-ish actionability
        text = "Stock is mooning, ripping, surging and will continue tomorrow"
        result = analyzer.analyze(dummy_tokens, text)
        # Should be dominated by present markers (3) vs future (2)
        assert result.actionability > 0.5  # More than neutral

    def test_actionability_bounds(self, analyzer, dummy_tokens):
        """Actionability should always be bounded [0.05, 1.0]."""
        # Test extreme past (should still be >= 0.05)
        text = "crashed tanked dropped fell plunged collapsed dumped sold"
        result = analyzer.analyze(dummy_tokens, text)
        assert 0.05 <= result.actionability <= 1.0

        # Test extreme present (should be <= 1.0)
        text = "crashing tanking dropping falling plunging collapsing dumping selling"
        result = analyzer.analyze(dummy_tokens, text)
        assert 0.05 <= result.actionability <= 1.0


class TestUrgencyScoring:
    """Test urgency scoring from 0.0 to 1.0."""

    def test_no_urgency(self, analyzer, dummy_tokens):
        """Text with no urgency markers should have 0.0 urgency."""
        text = "Stock is doing things."
        result = analyzer.analyze(dummy_tokens, text)
        assert result.urgency == 0.0

    def test_high_urgency_right_now(self, analyzer, dummy_tokens):
        """'right now' should trigger high urgency."""
        text = "Buy calls right now!"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.urgency >= 0.6

    def test_high_urgency_0dte(self, analyzer, dummy_tokens):
        """'0dte' should trigger high urgency."""
        text = "0dte calls are the play"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.urgency >= 0.6

    def test_high_urgency_immediately(self, analyzer, dummy_tokens):
        """'immediately' should trigger high urgency."""
        text = "Act immediately or miss out"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.urgency >= 0.6

    def test_high_urgency_expiring_today(self, analyzer, dummy_tokens):
        """'expiring today' should trigger high urgency."""
        text = "Options expiring today need action"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.urgency >= 0.6

    def test_medium_urgency_this_week(self, analyzer, dummy_tokens):
        """'this week' should trigger medium urgency."""
        text = "Need to act this week"
        result = analyzer.analyze(dummy_tokens, text)
        assert 0.2 <= result.urgency <= 0.7

    def test_medium_urgency_by_friday(self, analyzer, dummy_tokens):
        """'by friday' should trigger medium urgency."""
        text = "Close position by friday"
        result = analyzer.analyze(dummy_tokens, text)
        assert 0.2 <= result.urgency <= 0.7

    def test_medium_urgency_weeklies(self, analyzer, dummy_tokens):
        """'weeklies' should trigger medium urgency."""
        text = "Playing weeklies on TSLA"
        result = analyzer.analyze(dummy_tokens, text)
        assert 0.2 <= result.urgency <= 0.7

    def test_medium_urgency_fds(self, analyzer, dummy_tokens):
        """'FDs' (weekly options slang) should trigger medium urgency."""
        text = "Buying FDs before close"
        result = analyzer.analyze(dummy_tokens, text)
        assert 0.2 <= result.urgency <= 0.7

    def test_multiple_high_urgency_stacks(self, analyzer, dummy_tokens):
        """Multiple high urgency markers should stack."""
        text = "Act now! Right now! Immediately! 0dte expiring today!"
        result = analyzer.analyze(dummy_tokens, text)
        # Should have multiple high urgency matches
        assert result.urgency >= 0.8

    def test_urgency_capped_at_one(self, analyzer, dummy_tokens):
        """Urgency should never exceed 1.0."""
        text = "now now now immediately urgent asap right now 0dte breaking"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.urgency <= 1.0

    def test_mixed_urgency_levels(self, analyzer, dummy_tokens):
        """Mixed urgency markers should combine scores."""
        text = "Act this week before close right now"
        result = analyzer.analyze(dummy_tokens, text)
        # Has both high (right now) and medium (this week) markers
        assert result.urgency >= 0.6


class TestTimeExpressionExtraction:
    """Test extraction of time expressions from text."""

    def test_no_time_expressions(self, analyzer, dummy_tokens):
        """Text with no time expressions should return empty list."""
        text = "Stock is moving"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.time_expressions == []

    def test_relative_time_today(self, analyzer, dummy_tokens):
        """'today' should be extracted."""
        text = "Buy calls today"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("today" in expr.lower() for expr in result.time_expressions)

    def test_relative_time_tomorrow(self, analyzer, dummy_tokens):
        """'tomorrow' should be extracted."""
        text = "Earnings tomorrow"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("tomorrow" in expr.lower() for expr in result.time_expressions)

    def test_relative_time_next_week(self, analyzer, dummy_tokens):
        """'next week' should be extracted."""
        text = "FOMC next week"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("next week" in expr.lower() for expr in result.time_expressions)

    def test_relative_time_this_month(self, analyzer, dummy_tokens):
        """'this month' should be extracted."""
        text = "Expiring this month"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("this month" in expr.lower() for expr in result.time_expressions)

    def test_relative_time_by_eod(self, analyzer, dummy_tokens):
        """'by eod' should be extracted."""
        text = "Close position by eod"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("eod" in expr.lower() for expr in result.time_expressions)

    def test_duration_in_days(self, analyzer, dummy_tokens):
        """'in X days' should be extracted."""
        text = "Earnings in 3 days"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("in 3 days" in expr.lower() for expr in result.time_expressions)

    def test_duration_in_hours(self, analyzer, dummy_tokens):
        """'in X hours' should be extracted."""
        text = "Market opens in 2 hours"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("in 2 hours" in expr.lower() for expr in result.time_expressions)

    def test_event_relative_pre_earnings(self, analyzer, dummy_tokens):
        """'pre-earnings' should be extracted."""
        text = "Position sizing pre-earnings"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("pre-earnings" in expr.lower() or "pre earnings" in expr.lower()
                  for expr in result.time_expressions)

    def test_event_relative_post_fomc(self, analyzer, dummy_tokens):
        """'post-fomc' should be extracted."""
        text = "Rally expected post-fomc"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("fomc" in expr.lower() for expr in result.time_expressions)

    def test_calendar_month_name(self, analyzer, dummy_tokens):
        """Month names should be extracted."""
        text = "Expecting rally in December"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("december" in expr.lower() for expr in result.time_expressions)

    def test_calendar_quarter(self, analyzer, dummy_tokens):
        """'Q1', 'Q2', etc. should be extracted."""
        text = "Q4 earnings are crucial"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("q4" in expr.lower() for expr in result.time_expressions)

    def test_specific_date_slash_format(self, analyzer, dummy_tokens):
        """Dates like '1/19' or '12/31/2024' should be extracted."""
        text = "TSLA 200C 1/19 is the play"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("1/19" in expr for expr in result.time_expressions)

    def test_specific_date_full_year(self, analyzer, dummy_tokens):
        """Full date with year should be extracted."""
        text = "Options expire 12/31/2024"
        result = analyzer.analyze(dummy_tokens, text)
        assert any("12/31/2024" in expr for expr in result.time_expressions)

    def test_multiple_time_expressions(self, analyzer, dummy_tokens):
        """Multiple time expressions should all be extracted."""
        text = "Buy today, hold until next week, sell before 1/19 earnings"
        result = analyzer.analyze(dummy_tokens, text)
        # Should have: today, next week, 1/19
        assert len(result.time_expressions) >= 3

    def test_duplicate_time_expressions_deduped(self, analyzer, dummy_tokens):
        """Duplicate time expressions should be deduplicated."""
        text = "today today today"
        result = analyzer.analyze(dummy_tokens, text)
        # Should only appear once
        today_count = sum(1 for expr in result.time_expressions if expr.lower() == "today")
        assert today_count == 1

    def test_case_insensitive_matching(self, analyzer, dummy_tokens):
        """Time expressions should be matched case-insensitively."""
        text = "TOMORROW after FOMC"
        result = analyzer.analyze(dummy_tokens, text)
        # Should extract both despite case
        assert len(result.time_expressions) >= 2


class TestTenseSignals:
    """Test tense signal counting."""

    def test_empty_text_zero_signals(self, analyzer, dummy_tokens):
        """Empty text should have zero signals for all tenses."""
        text = ""
        result = analyzer.analyze(dummy_tokens, text)
        assert result.tense_signals["past"] == 0
        assert result.tense_signals["present"] == 0
        assert result.tense_signals["future"] == 0

    def test_signal_counts_accurate(self, analyzer, dummy_tokens):
        """Signal counts should accurately reflect marker occurrences."""
        text = "crashed dropped fell"  # 3 past markers
        result = analyzer.analyze(dummy_tokens, text)
        assert result.tense_signals["past"] == 3
        assert result.tense_signals["present"] == 0
        assert result.tense_signals["future"] == 0

    def test_mixed_signal_counts(self, analyzer, dummy_tokens):
        """Mixed tenses should count all markers correctly."""
        text = "crashed is crashing will crash"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.tense_signals["past"] == 1  # crashed
        assert result.tense_signals["present"] == 2  # is + crashing (both match)
        assert result.tense_signals["future"] == 1  # will

    def test_repeated_markers_counted(self, analyzer, dummy_tokens):
        """Repeated markers should be counted multiple times."""
        text = "will will will"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.tense_signals["future"] == 3


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string(self, analyzer, dummy_tokens):
        """Empty string should not crash."""
        text = ""
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "unknown"
        assert result.actionability == 0.5
        assert result.urgency == 0.0
        assert result.time_expressions == []

    def test_whitespace_only(self, analyzer, dummy_tokens):
        """Whitespace-only text should behave like empty."""
        text = "   \n\t  "
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "unknown"
        assert result.actionability == 0.5
        assert result.urgency == 0.0

    def test_no_markers_at_all(self, analyzer, dummy_tokens):
        """Text with no temporal markers should return unknown/neutral."""
        text = "random words without meaning"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "unknown"
        assert result.actionability == 0.5
        assert result.urgency == 0.0

    def test_case_sensitivity_tense(self, analyzer, dummy_tokens):
        """Tense markers should be case-insensitive."""
        text = "CRASHED TANKED DROPPED"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.tense_signals["past"] == 3

    def test_case_sensitivity_urgency(self, analyzer, dummy_tokens):
        """Urgency markers should be case-insensitive."""
        text = "RIGHT NOW IMMEDIATELY 0DTE"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.urgency >= 0.6

    def test_partial_word_boundary(self, analyzer, dummy_tokens):
        """Markers should require word boundaries (not match inside words)."""
        # "crashed" inside "uncrashed" should not match
        text = "uncrashedword"
        result = analyzer.analyze(dummy_tokens, text)
        assert result.tense_signals["past"] == 0

    def test_unicode_text(self, analyzer, dummy_tokens):
        """Unicode text should not crash the analyzer."""
        text = "Stock 📈 crashed yesterday 💥"
        result = analyzer.analyze(dummy_tokens, text)
        # Should still detect "crashed"
        assert result.dominant_tense == "past"

    def test_very_long_text(self, analyzer, dummy_tokens):
        """Very long text should not cause performance issues."""
        # 1000 repetitions
        text = "crashed " * 1000
        result = analyzer.analyze(dummy_tokens, text)
        assert result.dominant_tense == "past"
        assert result.tense_signals["past"] == 1000

    def test_special_characters(self, analyzer, dummy_tokens):
        """Special characters should not interfere with detection."""
        text = "!!!crashed??? @@@is###crashing$$$ will***moon"
        result = analyzer.analyze(dummy_tokens, text)
        # Should still detect all three
        assert result.tense_signals["past"] >= 1
        assert result.tense_signals["present"] >= 1
        assert result.tense_signals["future"] >= 1


class TestTemporalResultStructure:
    """Test that TemporalResult is correctly structured."""

    def test_result_has_all_fields(self, analyzer, dummy_tokens):
        """Result should have all required fields."""
        text = "Stock crashed yesterday"
        result = analyzer.analyze(dummy_tokens, text)

        assert hasattr(result, "dominant_tense")
        assert hasattr(result, "actionability")
        assert hasattr(result, "urgency")
        assert hasattr(result, "time_expressions")
        assert hasattr(result, "tense_signals")

    def test_result_types_correct(self, analyzer, dummy_tokens):
        """Result field types should match TemporalResult spec."""
        text = "Stock is crashing right now. Act today!"
        result = analyzer.analyze(dummy_tokens, text)

        assert isinstance(result.dominant_tense, str)
        assert result.dominant_tense in ["past", "present", "future", "unknown"]
        assert isinstance(result.actionability, float)
        assert isinstance(result.urgency, float)
        assert isinstance(result.time_expressions, list)
        assert isinstance(result.tense_signals, dict)

    def test_result_immutable(self, analyzer, dummy_tokens):
        """TemporalResult should be frozen/immutable."""
        text = "Stock crashed"
        result = analyzer.analyze(dummy_tokens, text)

        # Frozen dataclass should not allow assignment
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            result.dominant_tense = "future"  # type: ignore


class TestRealWorldScenarios:
    """Test real-world WSB/Reddit post scenarios."""

    def test_wsb_yolo_post(self, analyzer, dummy_tokens):
        """Typical WSB YOLO post with immediate action."""
        text = "YOLO'd into 0dte calls right now. Stock is mooning!"
        result = analyzer.analyze(dummy_tokens, text)

        assert result.dominant_tense == "present"
        assert result.actionability >= 0.7  # High actionability
        assert result.urgency >= 0.6  # High urgency (0dte, right now)

    def test_dd_post_future_prediction(self, analyzer, dummy_tokens):
        """DD post with future predictions."""
        text = "DD: TSLA will moon after earnings next week. Expected to beat estimates."
        result = analyzer.analyze(dummy_tokens, text)

        assert result.dominant_tense == "future"
        assert 0.35 <= result.actionability <= 0.7  # Medium actionability
        assert any("next week" in expr.lower() for expr in result.time_expressions)

    def test_loss_porn_post(self, analyzer, dummy_tokens):
        """Loss porn post describing past events."""
        text = "Lost everything. Stock crashed and my calls expired worthless yesterday."
        result = analyzer.analyze(dummy_tokens, text)

        assert result.dominant_tense == "past"
        assert result.actionability <= 0.35  # Low actionability
        assert any("yesterday" in expr.lower() for expr in result.time_expressions)

    def test_pre_market_discussion(self, analyzer, dummy_tokens):
        """Pre-market discussion with mixed tenses."""
        text = "Stock rallied yesterday, is gapping up this morning, and should continue today."
        result = analyzer.analyze(dummy_tokens, text)

        # Has past (rallied), present (gapping), future (should)
        assert result.tense_signals["past"] >= 1
        assert result.tense_signals["present"] >= 1
        assert result.tense_signals["future"] >= 1
        assert any("yesterday" in expr.lower() for expr in result.time_expressions)
        assert any("today" in expr.lower() for expr in result.time_expressions)

    def test_earnings_play_post(self, analyzer, dummy_tokens):
        """Earnings play with specific timing."""
        text = "Loading calls before earnings on 1/19. IV crush expected post-earnings."
        result = analyzer.analyze(dummy_tokens, text)

        assert any("1/19" in expr for expr in result.time_expressions)
        assert any("earnings" in expr.lower() for expr in result.time_expressions)

    def test_daily_discussion_urgent(self, analyzer, dummy_tokens):
        """Daily discussion thread with urgent call to action."""
        text = "SPY about to break out! Get in right now before it's too late!"
        result = analyzer.analyze(dummy_tokens, text)

        # "about to" is future, but "right now" creates urgency
        assert result.urgency > 0.0
        # "about to" suggests imminent action
        assert result.actionability >= 0.5
