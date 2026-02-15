"""
Comprehensive tests for SignalSuppressor module.

Modules tested:
- rot.feedback.suppressor

Coverage:
- SignalSuppressor initialization
- should_suppress with category-level suppression
- should_suppress with source-level suppression
- should_suppress with low-confidence + poor category
- apply method (returns tuple, annotates meta)
- Disabled suppressor (always returns False)
- No analyzer results (no suppression)
- Event type matching
- Source matching (subreddit)
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from rot.core.types import Event, Evidence
from rot.feedback.suppressor import SignalSuppressor


@pytest.fixture
def mock_analyzer():
    """Mock analyzer with configurable cached results."""
    analyzer = Mock()
    analyzer.get_cached_results = Mock(return_value={})
    return analyzer


class TestSignalSuppressorInit:
    def test_suppressor_creation(self, mock_analyzer):
        """SignalSuppressor can be created with default params."""
        suppressor = SignalSuppressor(mock_analyzer)

        assert suppressor.analyzer == mock_analyzer
        assert suppressor.threshold == 0.20
        assert suppressor.source_threshold == 0.15
        assert suppressor.min_signals == 30
        assert suppressor.enabled is True

    def test_suppressor_custom_params(self, mock_analyzer):
        """SignalSuppressor can be created with custom params."""
        suppressor = SignalSuppressor(
            mock_analyzer,
            threshold=0.30,
            source_threshold=0.25,
            min_signals=50,
            enabled=False,
        )

        assert suppressor.threshold == 0.30
        assert suppressor.source_threshold == 0.25
        assert suppressor.min_signals == 50
        assert suppressor.enabled is False


class TestShouldSuppress:
    def test_disabled_suppressor_never_suppresses(self, mock_analyzer):
        """Disabled suppressor always returns False."""
        evidence = Evidence(post_id="p1", permalink="p", subreddit="test", excerpt="e")
        event = Event(
            event_type="earnings_rumor",
            entities=["AAPL"],
            stance="bullish",
            time_horizon="1w",
            evidence=[evidence],
            confidence=0.8,
        )

        suppressor = SignalSuppressor(mock_analyzer, enabled=False)
        should_suppress, reason = suppressor.should_suppress(event)

        assert should_suppress is False
        assert reason == ""

    def test_no_analyzer_results_no_suppression(self, mock_analyzer):
        """No analyzer results means no suppression."""
        mock_analyzer.get_cached_results.return_value = {}
        evidence = Evidence(post_id="p1", permalink="p", subreddit="test", excerpt="e")
        event = Event(
            event_type="earnings_rumor",
            entities=["AAPL"],
            stance="bullish",
            time_horizon="1w",
            evidence=[evidence],
            confidence=0.8,
        )

        suppressor = SignalSuppressor(mock_analyzer)
        should_suppress, reason = suppressor.should_suppress(event)

        assert should_suppress is False
        assert reason == ""

    def test_category_level_suppression(self, mock_analyzer):
        """Category with low win rate is suppressed."""
        mock_analyzer.get_cached_results.return_value = {
            "suppression_candidates": [
                {
                    "level": "category",
                    "event_type": "earnings_rumor",
                    "win_rate": 15.0,
                    "decided": 50,
                }
            ]
        }
        evidence = Evidence(post_id="p1", permalink="p", subreddit="test", excerpt="e")
        event = Event(
            event_type="earnings_rumor",
            entities=["AAPL"],
            stance="bullish",
            time_horizon="1w",
            evidence=[evidence],
            confidence=0.8,
        )

        suppressor = SignalSuppressor(mock_analyzer)
        should_suppress, reason = suppressor.should_suppress(event)

        assert should_suppress is True
        assert "category_low_win_rate" in reason
        assert "earnings_rumor" in reason

    def test_source_level_suppression(self, mock_analyzer):
        """Source with low win rate is suppressed."""
        mock_analyzer.get_cached_results.return_value = {
            "suppression_candidates": [
                {
                    "level": "source",
                    "event_type": "earnings_rumor",
                    "source": "wallstreetbets",
                    "win_rate": 10.0,
                    "decided": 40,
                }
            ]
        }
        evidence = Evidence(post_id="p1", permalink="p", subreddit="wallstreetbets", excerpt="e")
        event = Event(
            event_type="earnings_rumor",
            entities=["AAPL"],
            stance="bullish",
            time_horizon="1w",
            evidence=[evidence],
            confidence=0.8,
            meta={"subreddit": "wallstreetbets"},
        )

        suppressor = SignalSuppressor(mock_analyzer)
        should_suppress, reason = suppressor.should_suppress(event)

        assert should_suppress is True
        assert "source_low_win_rate" in reason
        assert "wallstreetbets" in reason

    def test_category_level_suppression_regardless_of_confidence(self, mock_analyzer):
        """Category with low win rate is suppressed even with low confidence."""
        mock_analyzer.get_cached_results.return_value = {
            "suppression_candidates": [
                {
                    "level": "category",
                    "event_type": "regulatory",
                    "win_rate": 18.0,
                    "decided": 35,
                }
            ]
        }
        evidence = Evidence(post_id="p1", permalink="p", subreddit="test", excerpt="e")
        event = Event(
            event_type="regulatory",
            entities=["AAPL"],
            stance="bearish",
            time_horizon="1w",
            evidence=[evidence],
            confidence=0.25,
        )

        suppressor = SignalSuppressor(mock_analyzer)
        should_suppress, reason = suppressor.should_suppress(event)

        assert should_suppress is True
        # Category rule triggers first, before low-confidence rule
        assert "category_low_win_rate" in reason

    def test_low_confidence_triggers_when_no_category_match(self, mock_analyzer):
        """Low confidence rule triggers when confidence < 0.3 and category in candidates."""
        mock_analyzer.get_cached_results.return_value = {
            "suppression_candidates": [
                {
                    "level": "source",  # Source-level, not category-level
                    "event_type": "regulatory",
                    "source": "different_source",
                    "win_rate": 18.0,
                    "decided": 35,
                }
            ]
        }
        evidence = Evidence(post_id="p1", permalink="p", subreddit="test", excerpt="e")
        event = Event(
            event_type="regulatory",
            entities=["AAPL"],
            stance="bearish",
            time_horizon="1w",
            evidence=[evidence],
            confidence=0.25,
        )

        suppressor = SignalSuppressor(mock_analyzer)
        should_suppress, reason = suppressor.should_suppress(event)

        assert should_suppress is True
        # Low-confidence rule triggers because event_type matches any candidate
        assert "low_confidence_poor_category" in reason


class TestApplyMethod:
    def test_apply_not_suppressed(self, mock_analyzer):
        """apply returns original event if not suppressed."""
        mock_analyzer.get_cached_results.return_value = {}
        evidence = Evidence(post_id="p1", permalink="p", subreddit="test", excerpt="e")
        event = Event(
            event_type="earnings_rumor",
            entities=["AAPL"],
            stance="bullish",
            time_horizon="1w",
            evidence=[evidence],
            confidence=0.8,
        )

        suppressor = SignalSuppressor(mock_analyzer)
        result_event, was_suppressed = suppressor.apply(event)

        assert was_suppressed is False
        assert result_event == event
        assert result_event.meta.get("suppressed") is None

    def test_apply_suppressed_annotates_meta(self, mock_analyzer):
        """apply annotates meta if suppressed."""
        mock_analyzer.get_cached_results.return_value = {
            "suppression_candidates": [
                {
                    "level": "category",
                    "event_type": "earnings_rumor",
                    "win_rate": 12.0,
                    "decided": 50,
                }
            ]
        }
        evidence = Evidence(post_id="p1", permalink="p", subreddit="test", excerpt="e")
        event = Event(
            event_type="earnings_rumor",
            entities=["AAPL"],
            stance="bullish",
            time_horizon="1w",
            evidence=[evidence],
            confidence=0.8,
        )

        suppressor = SignalSuppressor(mock_analyzer)
        result_event, was_suppressed = suppressor.apply(event)

        assert was_suppressed is True
        assert result_event.meta["suppressed"] is True
        assert "suppression_reason" in result_event.meta
        assert "category_low_win_rate" in result_event.meta["suppression_reason"]

    def test_apply_preserves_existing_meta(self, mock_analyzer):
        """apply preserves existing meta fields."""
        mock_analyzer.get_cached_results.return_value = {
            "suppression_candidates": [
                {
                    "level": "category",
                    "event_type": "earnings_rumor",
                    "win_rate": 12.0,
                    "decided": 50,
                }
            ]
        }
        evidence = Evidence(post_id="p1", permalink="p", subreddit="test", excerpt="e")
        event = Event(
            event_type="earnings_rumor",
            entities=["AAPL"],
            stance="bullish",
            time_horizon="1w",
            evidence=[evidence],
            confidence=0.8,
            meta={"existing_field": "value"},
        )

        suppressor = SignalSuppressor(mock_analyzer)
        result_event, was_suppressed = suppressor.apply(event)

        assert was_suppressed is True
        assert result_event.meta["existing_field"] == "value"
        assert result_event.meta["suppressed"] is True
