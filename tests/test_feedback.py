"""Tests for signal feedback engine: analyzer, suppressor, tier gating."""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rot.core.types import Event, Evidence
from rot.feedback.analyzer import FeedbackAnalyzer
from rot.feedback.suppressor import SignalSuppressor
from rot.web.tier_gate import gate_signal_quality_access


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_event(
    event_type: str = "product_news",
    stance: str = "bullish",
    confidence: float = 0.5,
    subreddit: str = "stocks",
    **meta_overrides,
) -> Event:
    """Create a test Event with sensible defaults."""
    meta = {
        "trend_score": 0.5,
        "features": {"score_rate": 0.3, "comment_rate": 0.1},
    }
    meta.update(meta_overrides)
    return Event(
        event_type=event_type,
        entities=["TSLA"],
        stance=stance,
        time_horizon="1w",
        evidence=[
            Evidence(
                post_id="x",
                permalink="https://reddit.com/r/stocks/x",
                subreddit=subreddit,
                excerpt="test signal",
            )
        ],
        confidence=confidence,
        meta=meta,
    )


def _mock_analyzer_with_results(results: dict) -> MagicMock:
    """Create a mock analyzer that returns given cached results."""
    analyzer = MagicMock(spec=FeedbackAnalyzer)
    analyzer.get_cached_results.return_value = results
    return analyzer


# ── FeedbackAnalyzer Tests ────────────────────────────────────────────────


class TestFeedbackAnalyzer:
    """Tests for FeedbackAnalyzer methods."""

    def test_get_cached_results_empty_initially(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        assert analyzer.get_cached_results() == {}

    def test_get_cached_results_after_store(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        analyzer._last_analysis = {"computed_at": 1234, "category_performance": []}
        result = analyzer.get_cached_results()
        assert result["computed_at"] == 1234

    def test_compute_slope_with_no_data(self):
        slope = FeedbackAnalyzer._compute_slope([])
        assert slope is None

    def test_compute_slope_with_insufficient_data(self):
        daily = [
            {"win_rate": 50.0},
            {"win_rate": 60.0},
        ]
        slope = FeedbackAnalyzer._compute_slope(daily)
        assert slope is None  # needs >= 3 points

    def test_compute_slope_with_flat_data(self):
        daily = [
            {"win_rate": 50.0},
            {"win_rate": 50.0},
            {"win_rate": 50.0},
            {"win_rate": 50.0},
        ]
        slope = FeedbackAnalyzer._compute_slope(daily)
        assert slope == 0.0

    def test_compute_slope_with_increasing_data(self):
        daily = [
            {"win_rate": 30.0},
            {"win_rate": 40.0},
            {"win_rate": 50.0},
            {"win_rate": 60.0},
            {"win_rate": 70.0},
        ]
        slope = FeedbackAnalyzer._compute_slope(daily)
        assert slope is not None
        assert slope > 0  # positive slope

    def test_compute_slope_with_decreasing_data(self):
        daily = [
            {"win_rate": 70.0},
            {"win_rate": 60.0},
            {"win_rate": 50.0},
            {"win_rate": 40.0},
        ]
        slope = FeedbackAnalyzer._compute_slope(daily)
        assert slope is not None
        assert slope < 0  # negative slope

    def test_compute_slope_skips_none_values(self):
        daily = [
            {"win_rate": 50.0},
            {"win_rate": None},
            {"win_rate": 50.0},
            {"win_rate": 50.0},
        ]
        slope = FeedbackAnalyzer._compute_slope(daily)
        assert slope == 0.0

    def test_compute_moving_average_empty(self):
        ma = FeedbackAnalyzer._compute_moving_average([])
        assert ma == []

    def test_compute_moving_average_single(self):
        ma = FeedbackAnalyzer._compute_moving_average([{"win_rate": 50.0}])
        assert len(ma) == 1
        assert ma[0] == 50.0

    def test_compute_moving_average_window(self):
        daily = [
            {"win_rate": 30.0},
            {"win_rate": 40.0},
            {"win_rate": 50.0},
            {"win_rate": 60.0},
            {"win_rate": 70.0},
        ]
        ma = FeedbackAnalyzer._compute_moving_average(daily, window=3)
        assert len(ma) == 5
        # First value = just 30
        assert ma[0] == 30.0
        # Second value = avg(30, 40) = 35
        assert ma[1] == 35.0
        # Third value = avg(30, 40, 50) = 40
        assert ma[2] == 40.0
        # Fourth value = avg(40, 50, 60) = 50
        assert ma[3] == 50.0

    def test_compute_moving_average_with_none(self):
        daily = [
            {"win_rate": None},
            {"win_rate": 40.0},
            {"win_rate": None},
            {"win_rate": 60.0},
        ]
        ma = FeedbackAnalyzer._compute_moving_average(daily, window=3)
        assert len(ma) == 4
        assert ma[0] is None  # no valid values in window
        assert ma[1] == 40.0  # only 40 is valid

    def test_feature_importance_no_scorer(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        result = analyzer.get_feature_importance(None)
        assert result == []

    def test_feature_importance_scorer_not_available(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        scorer = MagicMock()
        scorer.ml_available = False
        result = analyzer.get_feature_importance(scorer)
        assert result == []

    def test_feature_importance_with_mock_model(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        scorer = MagicMock()
        scorer.ml_available = True

        # Mock sklearn pipeline structure
        mock_clf = MagicMock()
        mock_clf.feature_importances_ = [0.1, 0.2, 0.05] + [0.0] * 29
        mock_pipeline = MagicMock()
        mock_pipeline.named_steps = {"clf": mock_clf}
        scorer._model = mock_pipeline

        # Patch FEATURE_NAMES at the source module (it's imported inside the method)
        with patch("rot.credibility.features.FEATURE_NAMES", ["f1", "f2", "f3"] + [f"f{i}" for i in range(4, 33)]):
            result = analyzer.get_feature_importance(scorer)

        assert len(result) > 0
        # Should be sorted by importance descending
        importances = [r["importance"] for r in result]
        assert importances == sorted(importances, reverse=True)

    def test_suppression_candidates_empty_inputs(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        result = analyzer._compute_suppression_candidates([], [], 0.20, 30)
        assert result == []

    def test_suppression_candidates_category_below_threshold(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        category_perf = [
            {
                "event_type": "squeeze_chatter",
                "stance": "bullish",
                "strategy": "debit_spread",
                "decided": 50,
                "win_rate": 15.0,  # Below 20% threshold
            }
        ]
        result = analyzer._compute_suppression_candidates(category_perf, [], 0.20, 30)
        assert len(result) == 1
        assert result[0]["level"] == "category"
        assert result[0]["event_type"] == "squeeze_chatter"

    def test_suppression_candidates_category_above_threshold(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        category_perf = [
            {
                "event_type": "earnings_rumor",
                "stance": "bullish",
                "strategy": "debit_spread",
                "decided": 50,
                "win_rate": 55.0,  # Above 20% threshold
            }
        ]
        result = analyzer._compute_suppression_candidates(category_perf, [], 0.20, 30)
        assert len(result) == 0

    def test_suppression_candidates_not_enough_signals(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        category_perf = [
            {
                "event_type": "squeeze_chatter",
                "stance": "bullish",
                "strategy": "debit_spread",
                "decided": 10,  # Below min_signals (30)
                "win_rate": 10.0,
            }
        ]
        result = analyzer._compute_suppression_candidates(category_perf, [], 0.20, 30)
        assert len(result) == 0  # Not enough signals to suppress

    def test_suppression_candidates_source_level(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        source_rel = [
            {
                "source": "wallstreetbets",
                "event_type": "squeeze_chatter",
                "decided": 40,
                "win_rate": 12.0,
            }
        ]
        result = analyzer._compute_suppression_candidates([], source_rel, 0.20, 30)
        assert len(result) == 1
        assert result[0]["level"] == "source"
        assert result[0]["source"] == "wallstreetbets"

    def test_suppression_candidates_sorted_by_win_rate(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        category_perf = [
            {"event_type": "a", "stance": "x", "strategy": "y", "decided": 50, "win_rate": 18.0},
            {"event_type": "b", "stance": "x", "strategy": "y", "decided": 50, "win_rate": 5.0},
            {"event_type": "c", "stance": "x", "strategy": "y", "decided": 50, "win_rate": 12.0},
        ]
        result = analyzer._compute_suppression_candidates(category_perf, [], 0.20, 30)
        assert len(result) == 3
        win_rates = [r["win_rate"] for r in result]
        assert win_rates == sorted(win_rates)  # ascending

    def test_suppression_candidates_none_win_rate_ignored(self):
        analyzer = FeedbackAnalyzer(db=MagicMock())
        category_perf = [
            {"event_type": "a", "stance": "x", "strategy": "y", "decided": 50, "win_rate": None},
        ]
        result = analyzer._compute_suppression_candidates(category_perf, [], 0.20, 30)
        assert len(result) == 0  # None win_rate cannot be compared


# ── SignalSuppressor Tests ────────────────────────────────────────────────


class TestSignalSuppressor:
    """Tests for the adaptive signal suppressor."""

    def test_disabled_returns_false(self):
        analyzer = _mock_analyzer_with_results({})
        suppressor = SignalSuppressor(analyzer, enabled=False)
        event = _make_event()
        suppress, reason = suppressor.should_suppress(event)
        assert suppress is False
        assert reason == ""

    def test_no_cached_analysis_returns_false(self):
        analyzer = _mock_analyzer_with_results({})
        suppressor = SignalSuppressor(analyzer, enabled=True)
        event = _make_event()
        suppress, reason = suppressor.should_suppress(event)
        assert suppress is False

    def test_no_suppression_candidates_returns_false(self):
        analyzer = _mock_analyzer_with_results({"suppression_candidates": []})
        suppressor = SignalSuppressor(analyzer, enabled=True)
        event = _make_event()
        suppress, reason = suppressor.should_suppress(event)
        assert suppress is False

    def test_category_suppression(self):
        """Event type matching a suppression candidate should be suppressed."""
        analyzer = _mock_analyzer_with_results({
            "suppression_candidates": [
                {
                    "level": "category",
                    "event_type": "squeeze_chatter",
                    "source": None,
                    "win_rate": 10.0,
                    "decided": 50,
                }
            ]
        })
        suppressor = SignalSuppressor(analyzer, enabled=True)
        event = _make_event(event_type="squeeze_chatter")
        suppress, reason = suppressor.should_suppress(event)
        assert suppress is True
        assert "category_low_win_rate" in reason
        assert "squeeze_chatter" in reason

    def test_category_not_matching_passes(self):
        """Event type NOT in suppression candidates should pass."""
        analyzer = _mock_analyzer_with_results({
            "suppression_candidates": [
                {
                    "level": "category",
                    "event_type": "squeeze_chatter",
                    "source": None,
                    "win_rate": 10.0,
                    "decided": 50,
                }
            ]
        })
        suppressor = SignalSuppressor(analyzer, enabled=True)
        event = _make_event(event_type="earnings_rumor")
        suppress, reason = suppressor.should_suppress(event)
        assert suppress is False

    def test_source_suppression(self):
        """Event from a low-win-rate source should be suppressed."""
        analyzer = _mock_analyzer_with_results({
            "suppression_candidates": [
                {
                    "level": "source",
                    "event_type": "product_news",
                    "source": "wallstreetbets",
                    "win_rate": 8.0,
                    "decided": 40,
                }
            ]
        })
        suppressor = SignalSuppressor(analyzer, enabled=True)
        event = _make_event(
            event_type="product_news",
            subreddit="wallstreetbets",
        )
        suppress, reason = suppressor.should_suppress(event)
        assert suppress is True
        assert "source_low_win_rate" in reason

    def test_source_different_subreddit_passes(self):
        """Source suppression only matches same subreddit + event_type."""
        analyzer = _mock_analyzer_with_results({
            "suppression_candidates": [
                {
                    "level": "source",
                    "event_type": "product_news",
                    "source": "wallstreetbets",
                    "win_rate": 8.0,
                    "decided": 40,
                }
            ]
        })
        suppressor = SignalSuppressor(analyzer, enabled=True)
        event = _make_event(
            event_type="product_news",
            subreddit="stocks",  # different source
        )
        suppress, reason = suppressor.should_suppress(event)
        assert suppress is False

    def test_low_confidence_poor_category(self):
        """Low confidence + event type in suppression candidates (source-level) → suppress via low_confidence check."""
        # Use a SOURCE-level candidate so the category check (lines 73-80) doesn't match,
        # but the looser low-confidence check (lines 100-108) does match by event_type.
        analyzer = _mock_analyzer_with_results({
            "suppression_candidates": [
                {
                    "level": "source",
                    "event_type": "product_news",
                    "source": "wallstreetbets",  # Different from event's "stocks" source
                    "win_rate": 18.0,
                    "decided": 50,
                }
            ]
        })
        suppressor = SignalSuppressor(analyzer, enabled=True)
        # confidence=0.25 < 0.3 threshold, and event_type matches a candidate
        event = _make_event(event_type="product_news", confidence=0.25, subreddit="stocks")
        suppress, reason = suppressor.should_suppress(event)
        assert suppress is True
        assert "low_confidence_poor_category" in reason

    def test_low_confidence_but_good_category_passes(self):
        """Low confidence but event_type NOT in candidates → pass."""
        analyzer = _mock_analyzer_with_results({
            "suppression_candidates": [
                {
                    "level": "category",
                    "event_type": "squeeze_chatter",
                    "source": None,
                    "win_rate": 10.0,
                    "decided": 50,
                }
            ]
        })
        suppressor = SignalSuppressor(analyzer, enabled=True)
        event = _make_event(event_type="earnings_rumor", confidence=0.25)
        suppress, reason = suppressor.should_suppress(event)
        assert suppress is False

    def test_apply_suppressed_event(self):
        """apply() should set meta['suppressed'] and meta['suppression_reason']."""
        analyzer = _mock_analyzer_with_results({
            "suppression_candidates": [
                {
                    "level": "category",
                    "event_type": "squeeze_chatter",
                    "source": None,
                    "win_rate": 10.0,
                    "decided": 50,
                }
            ]
        })
        suppressor = SignalSuppressor(analyzer, enabled=True)
        event = _make_event(event_type="squeeze_chatter")

        modified, was_suppressed = suppressor.apply(event)
        assert was_suppressed is True
        assert modified.meta["suppressed"] is True
        assert "suppression_reason" in modified.meta
        assert modified.meta["suppression_reason"] != ""

    def test_apply_not_suppressed_preserves_event(self):
        """apply() on non-suppressed event returns original unchanged."""
        analyzer = _mock_analyzer_with_results({"suppression_candidates": []})
        suppressor = SignalSuppressor(analyzer, enabled=True)
        event = _make_event(event_type="earnings_rumor")

        modified, was_suppressed = suppressor.apply(event)
        assert was_suppressed is False
        assert modified is event  # exact same object — not modified

    def test_apply_preserves_existing_meta(self):
        """apply() should preserve existing meta fields when adding suppression."""
        analyzer = _mock_analyzer_with_results({
            "suppression_candidates": [
                {
                    "level": "category",
                    "event_type": "squeeze_chatter",
                    "source": None,
                    "win_rate": 10.0,
                    "decided": 50,
                }
            ]
        })
        suppressor = SignalSuppressor(analyzer, enabled=True)
        event = _make_event(event_type="squeeze_chatter", some_existing_key="preserved")

        modified, was_suppressed = suppressor.apply(event)
        assert was_suppressed is True
        assert modified.meta["some_existing_key"] == "preserved"
        assert modified.meta["suppressed"] is True


# ── Tier Gate Tests ───────────────────────────────────────────────────────


class TestGateSignalQualityAccess:
    """Tests for gate_signal_quality_access tier gate function."""

    def test_free_tier_no_access(self):
        access = gate_signal_quality_access("free")
        assert access["has_access"] is False
        assert access["has_category_heatmap"] is False

    def test_pro_tier_basic_access(self):
        access = gate_signal_quality_access("pro")
        assert access["has_access"] is True
        assert access["has_category_heatmap"] is True
        assert access["has_quality_trend"] is True
        # Pro does NOT get premium features
        assert access["has_source_reliability"] is False
        assert access["has_feature_importance"] is False
        assert access["has_calibration_detail"] is False
        assert access["has_suppression_view"] is False
        assert access["quality_days"] == 30

    def test_premium_tier_advanced_access(self):
        access = gate_signal_quality_access("premium")
        assert access["has_access"] is True
        assert access["has_source_reliability"] is True
        assert access["has_feature_importance"] is True
        assert access["has_calibration_detail"] is True
        # Premium does NOT get ultra features
        assert access["has_suppression_view"] is False
        assert access["quality_days"] == 90

    def test_ultra_tier_full_access(self):
        access = gate_signal_quality_access("ultra")
        assert access["has_access"] is True
        assert access["has_suppression_view"] is True
        assert access["has_source_reliability"] is True
        assert access["has_feature_importance"] is True
        assert access["quality_days"] == 365

    def test_enterprise_tier_full_access(self):
        access = gate_signal_quality_access("enterprise")
        assert access["has_access"] is True
        assert access["has_suppression_view"] is True
        assert access["quality_days"] == 365
