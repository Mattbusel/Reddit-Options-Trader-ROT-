"""Tests for rot.macro.fomc — FOMCTracker: scoring, classification, diffs, queries."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from rot.macro.fomc import FOMCTracker
from rot.macro.types import FOMCMeeting


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def tracker(mock_db):
    return FOMCTracker(db=mock_db)


# ── score_hawkish_dovish ────────────────────────────────────────────


class TestScoreHawkishDovish:
    def test_empty_text_returns_zeros(self, tracker):
        hawk, dove = tracker.score_hawkish_dovish("")
        assert hawk == 0.0
        assert dove == 0.0

    def test_hawkish_text(self, tracker):
        text = (
            "Inflation remains elevated and persistent. The committee sees "
            "upside risks and further tightening may be necessary. "
            "Rate hike is appropriate given overheating economy. "
            "Sufficiently restrictive stance needed."
        )
        hawk, dove = tracker.score_hawkish_dovish(text)
        assert hawk > 0.3
        assert hawk > dove

    def test_dovish_text(self, tracker):
        text = (
            "The economy is slowing and there are downside risks. "
            "Easing is warranted given weakening labor market. "
            "A rate cut may be appropriate. The committee remains patient. "
            "Disinflation progress supports accommodative stance."
        )
        hawk, dove = tracker.score_hawkish_dovish(text)
        assert dove > 0.3
        assert dove > hawk

    def test_mixed_text_both_nonzero(self, tracker):
        text = (
            "Inflation remains elevated but the economy shows signs of slowing. "
            "The committee is data dependent and will remain patient."
        )
        hawk, dove = tracker.score_hawkish_dovish(text)
        assert hawk > 0.0
        assert dove > 0.0

    def test_strongly_hawkish_near_max(self, tracker):
        text = (
            "Inflation inflation overheating tighten tightening restrictive "
            "rate hike rate increase above target elevated persistent "
            "upside risks further tightening higher for longer "
            "quantitative tightening reduce balance sheet"
        )
        hawk, dove = tracker.score_hawkish_dovish(text)
        assert hawk > 0.5
        assert dove == 0.0 or dove < hawk

    def test_strongly_dovish_near_max(self, tracker):
        text = (
            "Accommodate accommodative easing rate cut rate reduction "
            "downside risks slowdown slowing weakening unemployment "
            "below target patient gradual supportive stimulus "
            "flexible data dependent balanced risks pause skip "
            "disinflation progress maximum employment"
        )
        hawk, dove = tracker.score_hawkish_dovish(text)
        assert dove > 0.5
        assert hawk == 0.0 or hawk < dove

    def test_neutral_text(self, tracker):
        text = "The weather today is sunny and warm with light winds."
        hawk, dove = tracker.score_hawkish_dovish(text)
        assert hawk == 0.0
        assert dove == 0.0

    def test_returns_tuple_of_floats(self, tracker):
        hawk, dove = tracker.score_hawkish_dovish("inflation easing")
        assert isinstance(hawk, float)
        assert isinstance(dove, float)

    def test_scores_bounded_at_one(self, tracker):
        # Even with repetition, should cap at 1.0
        text = " ".join(["inflation rate hike tightening"] * 50)
        hawk, dove = tracker.score_hawkish_dovish(text)
        assert hawk <= 1.0
        assert dove <= 1.0

    def test_scores_bounded_at_zero(self, tracker):
        hawk, dove = tracker.score_hawkish_dovish("nothing relevant here")
        assert hawk >= 0.0
        assert dove >= 0.0


# ── classify_decision ───────────────────────────────────────────────


class TestClassifyDecision:
    def test_hold(self, tracker):
        assert tracker.classify_decision(5.25, 5.25) == "hold"

    def test_raise_25(self, tracker):
        assert tracker.classify_decision(5.25, 5.50) == "raise_25"

    def test_raise_50(self, tracker):
        assert tracker.classify_decision(5.25, 5.75) == "raise_50"

    def test_raise_75(self, tracker):
        assert tracker.classify_decision(5.25, 6.00) == "raise_75"

    def test_cut_25(self, tracker):
        assert tracker.classify_decision(5.50, 5.25) == "cut_25"

    def test_cut_50(self, tracker):
        assert tracker.classify_decision(5.50, 5.00) == "cut_50"

    def test_cut_75(self, tracker):
        assert tracker.classify_decision(5.50, 4.75) == "cut_75"

    def test_hold_exact_zero(self, tracker):
        assert tracker.classify_decision(0.0, 0.0) == "hold"


# ── generate_statement_diff ─────────────────────────────────────────


class TestGenerateStatementDiff:
    def test_returns_html(self, tracker):
        old = "The economy is growing steadily."
        new = "The economy is growing at a moderate pace."
        html = tracker.generate_statement_diff(old, new)
        assert len(html) > 0
        assert "<" in html  # Should contain HTML tags

    def test_empty_old_returns_empty(self, tracker):
        html = tracker.generate_statement_diff("", "Some new text")
        assert html == ""

    def test_empty_new_returns_empty(self, tracker):
        html = tracker.generate_statement_diff("Some old text", "")
        assert html == ""

    def test_both_empty_returns_empty(self, tracker):
        html = tracker.generate_statement_diff("", "")
        assert html == ""

    def test_identical_text_returns_html(self, tracker):
        text = "The Committee decided to maintain the target range."
        html = tracker.generate_statement_diff(text, text)
        # Even identical text should produce valid HTML table
        assert isinstance(html, str)


# ── estimate_rate_probabilities ─────────────────────────────────────


class TestEstimateRateProbabilities:
    def test_hold_scenario(self, tracker):
        probs = tracker.estimate_rate_probabilities(5.25, 5.25)
        assert "hold" in probs
        assert probs["hold"] == 0.80
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_raise_scenario_small(self, tracker):
        # Market implies small raise (20 bps above current)
        probs = tracker.estimate_rate_probabilities(5.25, 5.45)
        assert "raise_25" in probs
        assert probs["raise_25"] == 0.60
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_raise_scenario_large(self, tracker):
        # Market implies large raise (50 bps above current)
        probs = tracker.estimate_rate_probabilities(5.25, 5.75)
        assert "raise_50" in probs
        assert probs["raise_50"] == 0.60
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_cut_scenario_small(self, tracker):
        probs = tracker.estimate_rate_probabilities(5.25, 5.05)
        assert "cut_25" in probs
        assert probs["cut_25"] == 0.60
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_cut_scenario_large(self, tracker):
        probs = tracker.estimate_rate_probabilities(5.25, 4.80)
        assert "cut_50" in probs
        assert probs["cut_50"] == 0.60
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_near_hold(self, tracker):
        # Very small diff (3 bps) should be treated as hold
        probs = tracker.estimate_rate_probabilities(5.25, 5.28)
        assert "hold" in probs
        assert probs["hold"] == 0.80


# ── _row_to_meeting ─────────────────────────────────────────────────


class TestRowToMeeting:
    def test_basic_conversion(self):
        row = {
            "id": "fomc-test",
            "meeting_date": 1700000000.0,
            "rate_decision": "hold",
            "rate_before": 5.25,
            "rate_after": 5.25,
            "statement_text": "The Committee decided...",
            "statement_diff": "<html></html>",
            "hawkish_score": 0.6,
            "dovish_score": 0.3,
            "dot_plot_median": 5.50,
            "meta": '{"votes": "12-0"}',
        }
        meeting = FOMCTracker._row_to_meeting(row)
        assert isinstance(meeting, FOMCMeeting)
        assert meeting.id == "fomc-test"
        assert meeting.rate_decision == "hold"
        assert meeting.hawkish_score == 0.6
        assert meeting.meta == {"votes": "12-0"}

    def test_handles_invalid_json_meta(self):
        row = {
            "id": "fomc-bad",
            "meeting_date": 1700000000.0,
            "meta": "not-json",
        }
        meeting = FOMCTracker._row_to_meeting(row)
        assert meeting.meta == {}

    def test_handles_missing_optional_fields(self):
        row = {
            "id": "fomc-minimal",
            "meeting_date": 1700000000.0,
        }
        meeting = FOMCTracker._row_to_meeting(row)
        assert meeting.rate_decision == ""
        assert meeting.rate_before == 0.0
        assert meeting.rate_after == 0.0
        assert meeting.statement_text == ""
        assert meeting.hawkish_score == 0.0
        assert meeting.dot_plot_median is None


# ── Query methods (mocked DB) ──────────────────────────────────────


class TestFOMCQueries:
    @pytest.mark.asyncio
    async def test_get_next_meeting(self, tracker, mock_db):
        row = {
            "id": "fomc-next",
            "meeting_date": time.time() + 86400 * 30,
            "rate_decision": "",
            "meta": "{}",
        }
        mock_db.get_next_fomc_meeting = AsyncMock(return_value=row)
        result = await tracker.get_next_meeting()
        assert result is not None
        assert result.id == "fomc-next"

    @pytest.mark.asyncio
    async def test_get_next_meeting_none(self, tracker, mock_db):
        mock_db.get_next_fomc_meeting = AsyncMock(return_value=None)
        result = await tracker.get_next_meeting()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_history(self, tracker, mock_db):
        rows = [
            {"id": f"fomc-{i}", "meeting_date": 1700000000.0 - i * 86400 * 45, "meta": "{}"}
            for i in range(3)
        ]
        mock_db.query_fomc_meetings = AsyncMock(return_value=rows)
        results = await tracker.get_history(limit=20)
        assert len(results) == 3
        mock_db.query_fomc_meetings.assert_called_once_with(limit=20, order="desc")

    @pytest.mark.asyncio
    async def test_get_meeting(self, tracker, mock_db):
        row = {"id": "fomc-specific", "meeting_date": 1700000000.0, "meta": "{}"}
        mock_db.get_fomc_meeting = AsyncMock(return_value=row)
        result = await tracker.get_meeting("fomc-specific")
        assert result is not None
        assert result.id == "fomc-specific"

    @pytest.mark.asyncio
    async def test_get_meeting_not_found(self, tracker, mock_db):
        mock_db.get_fomc_meeting = AsyncMock(return_value=None)
        result = await tracker.get_meeting("nonexistent")
        assert result is None
