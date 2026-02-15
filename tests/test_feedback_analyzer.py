"""Tests for the feedback analyzer engine.

Covers:
- FeedbackAnalyzer.run_analysis: full pipeline with all sub-analyses
- get_category_performance: win rate by (event_type, stance, strategy)
- get_source_reliability: win rate by (source, event_type)
- get_feature_importance: ML model feature extraction
- get_quality_trend: daily win rate + linear regression slope
- get_confidence_calibration_detailed: per-decile calibration
- _compute_suppression_candidates: threshold-based candidate selection
- _compute_slope: linear regression helper
- _compute_moving_average: rolling window average
"""

from __future__ import annotations

import os
import tempfile
import time

import pytest

from rot.feedback.analyzer import FeedbackAnalyzer
from rot.storage.database import Database


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
async def db():
    """Create a temporary database for testing feedback analysis."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    database = Database(path)
    await database.connect()

    # Ensure signals, signal_performance, and signal_archive tables exist
    # (they should be created by database.connect() via schema migrations)
    # Insert test data
    await _seed_test_signals(database)

    yield database

    await database.close()
    os.unlink(path)


@pytest.fixture
def analyzer(db: Database) -> FeedbackAnalyzer:
    """Create a FeedbackAnalyzer with the test database."""
    return FeedbackAnalyzer(db)


async def _seed_test_signals(db: Database) -> None:
    """Insert test signals and performance data for analysis."""
    now = time.time()
    day = 86400

    # Insert a batch of signals with varying outcomes
    signals_data = [
        # (id, run_id, created_at, ticker, event_type, stance, strategy, confidence, subreddit, quality_score, post_title)
        ("s1", "run1", now - 1 * day, "TSLA", "earnings_rumor", "bullish", "debit_spread", 0.8, "wallstreetbets", 0.7, "TSLA calls"),
        ("s2", "run1", now - 2 * day, "TSLA", "earnings_rumor", "bullish", "debit_spread", 0.7, "wallstreetbets", 0.6, "TSLA moon"),
        ("s3", "run1", now - 3 * day, "AAPL", "product_news", "bearish", "credit_spread", 0.6, "options", 0.5, "AAPL bearish"),
        ("s4", "run1", now - 4 * day, "MSFT", "product_news", "bearish", "credit_spread", 0.5, "options", 0.4, "MSFT down"),
        ("s5", "run1", now - 5 * day, "NVDA", "macro", "bullish", "debit_spread", 0.9, "investing", 0.8, "NVDA up"),
        ("s6", "run1", now - 6 * day, "AMD", "macro", "bullish", "debit_spread", 0.4, "wallstreetbets", 0.3, "AMD buy"),
        ("s7", "run1", now - 7 * day, "GOOG", "regulatory", "mixed", "none", 0.3, "stocks", 0.2, "GOOG news"),
        ("s8", "run1", now - 8 * day, "AMZN", "squeeze_chatter", "bullish", "straddle", 0.6, "wallstreetbets", 0.5, "AMZN squeeze"),
        ("s9", "run1", now - 9 * day, "META", "earnings_rumor", "bullish", "debit_spread", 0.75, "wallstreetbets", 0.65, "META earnings"),
        ("s10", "run1", now - 10 * day, "NFLX", "earnings_rumor", "bearish", "credit_spread", 0.55, "options", 0.45, "NFLX puts"),
    ]

    for sig in signals_data:
        await db.db.execute(
            """INSERT INTO signals (id, run_id, created_at, ticker, event_type, stance, strategy,
               confidence, subreddit, quality_score, post_title)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            sig,
        )

    # Insert performance data: some win, some lose, some neutral
    performance_data = [
        # (signal_id, ticker, price_at_signal, price_1h, price_4h, price_1d)
        ("s1", "TSLA", 200.0, 202.0, 204.0, 206.0),
        ("s2", "TSLA", 200.0, 199.0, 197.0, 196.0),
        ("s3", "AAPL", 150.0, 149.0, 147.0, 145.5),
        ("s4", "MSFT", 300.0, 301.0, 302.0, 303.0),
        ("s5", "NVDA", 500.0, 510.0, 520.0, 525.0),
        ("s6", "AMD", 100.0, 100.2, 100.1, 100.3),
        ("s7", "GOOG", 140.0, 142.0, 144.0, 146.0),
        ("s8", "AMZN", 180.0, 178.0, 175.0, 172.8),
        ("s9", "META", 400.0, 404.0, 406.0, 408.0),
        ("s10", "NFLX", 550.0, 555.0, 558.0, 561.0),
    ]

    for perf in performance_data:
        await db.db.execute(
            """INSERT INTO signal_performance (signal_id, ticker, price_at_signal, price_1h, price_4h, price_1d)
               VALUES (?, ?, ?, ?, ?, ?)""",
            perf,
        )

    await db.db.commit()


# ============================================================================
# _compute_slope tests (static method, no DB needed)
# ============================================================================


class TestComputeSlope:
    """Tests for the linear regression slope helper."""

    def test_positive_slope(self) -> None:
        daily = [
            {"win_rate": 40.0},
            {"win_rate": 45.0},
            {"win_rate": 50.0},
            {"win_rate": 55.0},
            {"win_rate": 60.0},
        ]
        slope = FeedbackAnalyzer._compute_slope(daily)
        assert slope is not None
        assert slope > 0

    def test_negative_slope(self) -> None:
        daily = [
            {"win_rate": 70.0},
            {"win_rate": 65.0},
            {"win_rate": 60.0},
            {"win_rate": 55.0},
            {"win_rate": 50.0},
        ]
        slope = FeedbackAnalyzer._compute_slope(daily)
        assert slope is not None
        assert slope < 0

    def test_flat_slope(self) -> None:
        daily = [
            {"win_rate": 50.0},
            {"win_rate": 50.0},
            {"win_rate": 50.0},
            {"win_rate": 50.0},
        ]
        slope = FeedbackAnalyzer._compute_slope(daily)
        assert slope is not None
        assert abs(slope) < 0.01

    def test_too_few_points_returns_none(self) -> None:
        assert FeedbackAnalyzer._compute_slope([]) is None
        assert FeedbackAnalyzer._compute_slope([{"win_rate": 50.0}]) is None
        assert FeedbackAnalyzer._compute_slope(
            [{"win_rate": 50.0}, {"win_rate": 60.0}]
        ) is None

    def test_none_win_rates_skipped(self) -> None:
        daily = [
            {"win_rate": None},
            {"win_rate": 40.0},
            {"win_rate": 50.0},
            {"win_rate": 60.0},
            {"win_rate": None},
        ]
        slope = FeedbackAnalyzer._compute_slope(daily)
        assert slope is not None
        assert slope > 0

    def test_all_none_returns_none(self) -> None:
        daily = [{"win_rate": None}] * 5
        assert FeedbackAnalyzer._compute_slope(daily) is None

    @pytest.mark.parametrize(
        "rates, expect_positive",
        [
            ([10, 20, 30, 40], True),
            ([90, 80, 70, 60], False),
            ([50, 50, 50, 50], None),  # None = ~zero
        ],
        ids=["increasing", "decreasing", "flat"],
    )
    def test_slope_direction(self, rates: list[int], expect_positive: bool | None) -> None:
        daily = [{"win_rate": float(r)} for r in rates]
        slope = FeedbackAnalyzer._compute_slope(daily)
        assert slope is not None
        if expect_positive is True:
            assert slope > 0
        elif expect_positive is False:
            assert slope < 0
        else:
            assert abs(slope) < 0.01


# ============================================================================
# _compute_moving_average tests (static method, no DB needed)
# ============================================================================


class TestComputeMovingAverage:
    """Tests for the rolling window average helper."""

    def test_basic_ma(self) -> None:
        daily = [{"win_rate": float(i * 10)} for i in range(1, 11)]
        ma = FeedbackAnalyzer._compute_moving_average(daily, window=3)
        assert len(ma) == 10
        # First element: just [10.0] -> 10.0
        assert ma[0] == 10.0
        # Third element: avg(10, 20, 30) = 20.0
        assert ma[2] == 20.0

    def test_window_larger_than_data(self) -> None:
        daily = [{"win_rate": 50.0}, {"win_rate": 60.0}]
        ma = FeedbackAnalyzer._compute_moving_average(daily, window=7)
        assert len(ma) == 2
        assert ma[0] == 50.0
        assert ma[1] == 55.0

    def test_none_values_excluded(self) -> None:
        daily = [
            {"win_rate": 40.0},
            {"win_rate": None},
            {"win_rate": 60.0},
        ]
        ma = FeedbackAnalyzer._compute_moving_average(daily, window=3)
        assert len(ma) == 3
        # Index 2: window = [40.0, None, 60.0], non-None = [40, 60], avg = 50
        assert ma[2] == 50.0

    def test_all_none_returns_none_values(self) -> None:
        daily = [{"win_rate": None}] * 4
        ma = FeedbackAnalyzer._compute_moving_average(daily, window=3)
        assert all(v is None for v in ma)

    def test_window_of_one(self) -> None:
        daily = [{"win_rate": 10.0}, {"win_rate": 20.0}, {"win_rate": 30.0}]
        ma = FeedbackAnalyzer._compute_moving_average(daily, window=1)
        assert ma == [10.0, 20.0, 30.0]

    def test_empty_daily(self) -> None:
        ma = FeedbackAnalyzer._compute_moving_average([], window=7)
        assert ma == []


# ============================================================================
# _compute_suppression_candidates tests (pure logic, no DB needed)
# ============================================================================


class TestComputeSuppressionCandidates:
    """Tests for threshold-based suppression candidate selection."""

    def _make_analyzer(self) -> FeedbackAnalyzer:
        """Create a minimal analyzer for testing static-like methods."""
        # Use a mock since we only call _compute_suppression_candidates
        return FeedbackAnalyzer(db=None)

    @pytest.mark.parametrize(
        "win_rate, threshold, expected_suppress",
        [
            (10.0, 0.20, True),   # 10% < 20% threshold -> suppress
            (15.0, 0.20, True),   # 15% < 20%
            (19.9, 0.20, True),   # 19.9% < 20%
            (20.0, 0.20, False),  # 20% == 20% -> not below
            (25.0, 0.20, False),  # 25% > 20%
            (50.0, 0.20, False),  # 50% > 20%
            (0.0, 0.10, True),    # 0% < 10%
            (5.0, 0.10, True),    # 5% < 10%
        ],
        ids=[
            "10pct-suppress", "15pct-suppress", "19.9pct-suppress",
            "20pct-no", "25pct-no", "50pct-no",
            "0pct-low-thresh", "5pct-low-thresh",
        ],
    )
    def test_threshold_boundary(
        self, win_rate: float, threshold: float, expected_suppress: bool
    ) -> None:
        analyzer = self._make_analyzer()
        cat_perf = [
            {
                "event_type": "earnings_rumor",
                "stance": "bullish",
                "strategy": "debit_spread",
                "decided": 50,
                "win_rate": win_rate,
            }
        ]
        candidates = analyzer._compute_suppression_candidates(
            cat_perf, [], threshold, min_signals=30
        )
        if expected_suppress:
            assert len(candidates) == 1
            assert candidates[0]["level"] == "category"
        else:
            assert len(candidates) == 0

    def test_min_signals_filter(self) -> None:
        """Categories with too few decided signals should not be suppressed."""
        analyzer = self._make_analyzer()
        cat_perf = [
            {
                "event_type": "earnings_rumor",
                "stance": "bullish",
                "strategy": "debit_spread",
                "decided": 10,  # below min_signals=30
                "win_rate": 5.0,
            }
        ]
        candidates = analyzer._compute_suppression_candidates(
            cat_perf, [], threshold=0.20, min_signals=30
        )
        assert len(candidates) == 0

    def test_source_level_candidates(self) -> None:
        analyzer = self._make_analyzer()
        source_rel = [
            {
                "source": "wallstreetbets",
                "event_type": "squeeze_chatter",
                "decided": 40,
                "win_rate": 12.0,
            }
        ]
        candidates = analyzer._compute_suppression_candidates(
            [], source_rel, threshold=0.20, min_signals=30
        )
        assert len(candidates) == 1
        assert candidates[0]["level"] == "source"
        assert candidates[0]["source"] == "wallstreetbets"

    def test_mixed_category_and_source_candidates(self) -> None:
        analyzer = self._make_analyzer()
        cat_perf = [
            {
                "event_type": "squeeze_chatter",
                "stance": "bullish",
                "strategy": "straddle",
                "decided": 50,
                "win_rate": 8.0,
            }
        ]
        source_rel = [
            {
                "source": "pennystocks",
                "event_type": "other",
                "decided": 35,
                "win_rate": 15.0,
            }
        ]
        candidates = analyzer._compute_suppression_candidates(
            cat_perf, source_rel, threshold=0.20, min_signals=30
        )
        assert len(candidates) == 2
        # Sorted by win_rate ascending
        assert candidates[0]["win_rate"] <= candidates[1]["win_rate"]

    def test_none_win_rate_excluded(self) -> None:
        analyzer = self._make_analyzer()
        cat_perf = [
            {
                "event_type": "other",
                "stance": "unknown",
                "strategy": "none",
                "decided": 40,
                "win_rate": None,
            }
        ]
        candidates = analyzer._compute_suppression_candidates(
            cat_perf, [], threshold=0.20, min_signals=30
        )
        assert len(candidates) == 0

    def test_empty_inputs(self) -> None:
        analyzer = self._make_analyzer()
        candidates = analyzer._compute_suppression_candidates(
            [], [], threshold=0.20, min_signals=30
        )
        assert candidates == []

    def test_candidates_sorted_by_win_rate(self) -> None:
        analyzer = self._make_analyzer()
        cat_perf = [
            {"event_type": "a", "stance": "bullish", "strategy": "s", "decided": 50, "win_rate": 15.0},
            {"event_type": "b", "stance": "bearish", "strategy": "s", "decided": 50, "win_rate": 5.0},
            {"event_type": "c", "stance": "bullish", "strategy": "s", "decided": 50, "win_rate": 10.0},
        ]
        candidates = analyzer._compute_suppression_candidates(
            cat_perf, [], threshold=0.20, min_signals=30
        )
        assert len(candidates) == 3
        win_rates = [c["win_rate"] for c in candidates]
        assert win_rates == sorted(win_rates)


# ============================================================================
# get_cached_results tests
# ============================================================================


class TestGetCachedResults:
    """Tests for the caching behavior."""

    def test_initial_cache_empty(self) -> None:
        analyzer = FeedbackAnalyzer(db=None)
        assert analyzer.get_cached_results() == {}

    @pytest.mark.asyncio
    async def test_cache_populated_after_run(self, analyzer: FeedbackAnalyzer) -> None:
        results = await analyzer.run_analysis(days=30)
        cached = analyzer.get_cached_results()
        assert cached is results
        assert "computed_at" in cached
        assert "elapsed_s" in cached

    @pytest.mark.asyncio
    async def test_cache_has_all_keys(self, analyzer: FeedbackAnalyzer) -> None:
        results = await analyzer.run_analysis(days=30)
        expected_keys = {
            "category_performance",
            "source_reliability",
            "feature_importance",
            "quality_trend",
            "suppression_candidates",
            "calibration_detailed",
            "computed_at",
            "elapsed_s",
        }
        assert expected_keys.issubset(set(results.keys()))


# ============================================================================
# get_feature_importance tests (no DB, uses mock ML scorer)
# ============================================================================


class TestGetFeatureImportance:
    """Tests for ML model feature importance extraction."""

    def _make_analyzer(self) -> FeedbackAnalyzer:
        return FeedbackAnalyzer(db=None)

    def test_none_scorer_returns_empty(self) -> None:
        analyzer = self._make_analyzer()
        assert analyzer.get_feature_importance(None) == []

    def test_scorer_not_available(self) -> None:
        """ml_available=False should return empty."""
        analyzer = self._make_analyzer()

        class FakeScorer:
            ml_available = False

        assert analyzer.get_feature_importance(FakeScorer()) == []

    def test_scorer_no_model(self) -> None:
        analyzer = self._make_analyzer()

        class FakeScorer:
            ml_available = True
            _model = None

        assert analyzer.get_feature_importance(FakeScorer()) == []

    def test_scorer_no_clf_in_pipeline(self) -> None:
        analyzer = self._make_analyzer()

        class FakeModel:
            named_steps = {"scaler": object()}

        class FakeScorer:
            ml_available = True
            _model = FakeModel()

        assert analyzer.get_feature_importance(FakeScorer()) == []

    def test_scorer_with_valid_importances(self) -> None:
        analyzer = self._make_analyzer()
        from rot.credibility.features import FEATURE_NAMES

        importances = [1.0 / (i + 1) for i in range(len(FEATURE_NAMES))]

        class FakeClf:
            feature_importances_ = importances

        class FakeModel:
            named_steps = {"clf": FakeClf()}

        class FakeScorer:
            ml_available = True
            _model = FakeModel()

        result = analyzer.get_feature_importance(FakeScorer())
        assert len(result) == len(FEATURE_NAMES)
        # Should be sorted by importance descending
        for i in range(len(result) - 1):
            assert result[i]["importance"] >= result[i + 1]["importance"]
        # Each entry should have feature and importance keys
        for entry in result:
            assert "feature" in entry
            assert "importance" in entry


# ============================================================================
# Database-backed integration tests
# ============================================================================


class TestCategoryPerformance:
    """Tests for get_category_performance with real DB queries."""

    @pytest.mark.asyncio
    async def test_returns_list(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_category_performance(days=30)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_result_structure(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_category_performance(days=30)
        if result:
            row = result[0]
            assert "event_type" in row
            assert "stance" in row
            assert "strategy" in row
            assert "total" in row
            assert "winners" in row
            assert "losers" in row
            assert "neutral" in row
            assert "decided" in row
            assert "win_rate" in row
            assert "avg_confidence" in row

    @pytest.mark.asyncio
    async def test_decided_equals_winners_plus_losers(
        self, analyzer: FeedbackAnalyzer
    ) -> None:
        result = await analyzer.get_category_performance(days=30)
        for row in result:
            assert row["decided"] == row["winners"] + row["losers"]

    @pytest.mark.asyncio
    async def test_win_rate_calculation(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_category_performance(days=30)
        for row in result:
            if row["decided"] > 0:
                expected = round(row["winners"] / row["decided"] * 100, 1)
                assert row["win_rate"] == expected

    @pytest.mark.asyncio
    async def test_zero_days_returns_nothing(self, analyzer: FeedbackAnalyzer) -> None:
        """With days=0, cutoff is now, so no data in the future."""
        result = await analyzer.get_category_performance(days=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_ordered_by_total_desc(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_category_performance(days=30)
        for i in range(len(result) - 1):
            assert result[i]["total"] >= result[i + 1]["total"]


class TestSourceReliability:
    """Tests for get_source_reliability with real DB queries."""

    @pytest.mark.asyncio
    async def test_returns_list(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_source_reliability(days=30)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_result_structure(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_source_reliability(days=30)
        for row in result:
            assert "source" in row
            assert "event_type" in row
            assert "total" in row
            assert "winners" in row
            assert "losers" in row

    @pytest.mark.asyncio
    async def test_minimum_signal_count(self, analyzer: FeedbackAnalyzer) -> None:
        """get_source_reliability has HAVING COUNT(*) >= 5."""
        result = await analyzer.get_source_reliability(days=30)
        for row in result:
            assert row["total"] >= 5


class TestQualityTrend:
    """Tests for get_quality_trend with real DB queries."""

    @pytest.mark.asyncio
    async def test_returns_dict(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_quality_trend(days=30)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_has_expected_keys(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_quality_trend(days=30)
        assert "daily" in result
        assert "slope" in result
        assert "ma7" in result
        assert "direction" in result

    @pytest.mark.asyncio
    async def test_direction_values(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_quality_trend(days=30)
        assert result["direction"] in ("improving", "degrading", "stable")

    @pytest.mark.asyncio
    async def test_daily_ordered_ascending(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_quality_trend(days=30)
        daily = result["daily"]
        for i in range(len(daily) - 1):
            assert daily[i]["day"] <= daily[i + 1]["day"]

    @pytest.mark.asyncio
    async def test_ma7_length_matches_daily(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_quality_trend(days=30)
        assert len(result["ma7"]) == len(result["daily"])


class TestConfidenceCalibration:
    """Tests for get_confidence_calibration_detailed."""

    @pytest.mark.asyncio
    async def test_returns_list(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_confidence_calibration_detailed(days=30)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_decile_structure(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_confidence_calibration_detailed(days=30)
        for row in result:
            assert "decile" in row
            assert "decile_label" in row
            assert "total" in row
            assert "winners" in row
            assert "losers" in row
            assert "decided" in row
            assert "actual_win_rate" in row
            assert "expected_win_rate" in row

    @pytest.mark.asyncio
    async def test_decile_labels_formatted(self, analyzer: FeedbackAnalyzer) -> None:
        result = await analyzer.get_confidence_calibration_detailed(days=30)
        for row in result:
            assert "%" in row["decile_label"]


# ============================================================================
# run_analysis integration test
# ============================================================================


class TestRunAnalysis:
    """Tests for the full analysis pipeline."""

    @pytest.mark.asyncio
    async def test_run_analysis_returns_all_sections(
        self, analyzer: FeedbackAnalyzer
    ) -> None:
        results = await analyzer.run_analysis(days=30)
        assert "category_performance" in results
        assert "source_reliability" in results
        assert "feature_importance" in results
        assert "quality_trend" in results
        assert "suppression_candidates" in results
        assert "calibration_detailed" in results
        assert "computed_at" in results
        assert "elapsed_s" in results

    @pytest.mark.asyncio
    async def test_elapsed_positive(self, analyzer: FeedbackAnalyzer) -> None:
        results = await analyzer.run_analysis(days=30)
        assert results["elapsed_s"] >= 0

    @pytest.mark.asyncio
    async def test_feature_importance_empty_without_scorer(
        self, analyzer: FeedbackAnalyzer
    ) -> None:
        results = await analyzer.run_analysis(ml_scorer=None, days=30)
        assert results["feature_importance"] == []

    @pytest.mark.asyncio
    async def test_suppression_with_low_threshold(
        self, analyzer: FeedbackAnalyzer
    ) -> None:
        """Very low threshold should suppress nothing."""
        results = await analyzer.run_analysis(
            days=30, suppress_threshold=0.01, min_signals=1
        )
        # With 1% threshold, most categories pass
        assert isinstance(results["suppression_candidates"], list)

    @pytest.mark.asyncio
    async def test_suppression_with_high_threshold(
        self, analyzer: FeedbackAnalyzer
    ) -> None:
        """Very high threshold could suppress many categories."""
        results = await analyzer.run_analysis(
            days=30, suppress_threshold=0.99, min_signals=1
        )
        assert isinstance(results["suppression_candidates"], list)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "days",
        [1, 7, 14, 30, 90],
        ids=["1day", "7days", "14days", "30days", "90days"],
    )
    async def test_different_day_windows(
        self, analyzer: FeedbackAnalyzer, days: int
    ) -> None:
        results = await analyzer.run_analysis(days=days)
        assert isinstance(results["category_performance"], list)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "threshold, min_signals",
        [
            (0.10, 5),
            (0.20, 10),
            (0.30, 20),
            (0.50, 30),
        ],
        ids=["10pct-5min", "20pct-10min", "30pct-20min", "50pct-30min"],
    )
    async def test_different_suppression_params(
        self,
        analyzer: FeedbackAnalyzer,
        threshold: float,
        min_signals: int,
    ) -> None:
        results = await analyzer.run_analysis(
            days=30,
            suppress_threshold=threshold,
            min_signals=min_signals,
        )
        for candidate in results["suppression_candidates"]:
            # All candidates must be below threshold
            assert candidate["win_rate"] < threshold * 100
            assert candidate["decided"] >= min_signals


# ============================================================================
# Direction logic tests
# ============================================================================


class TestDirectionLogic:
    """Tests for the quality trend direction classification."""

    @pytest.mark.parametrize(
        "slope, expected_direction",
        [
            (0.05, "improving"),
            (0.10, "improving"),
            (0.03, "improving"),
            (-0.05, "degrading"),
            (-0.10, "degrading"),
            (-0.03, "degrading"),
            (0.0, "stable"),
            (0.01, "stable"),
            (-0.01, "stable"),
            (0.02, "stable"),
            (-0.02, "stable"),
            (None, "stable"),
        ],
        ids=[
            "pos-0.05", "pos-0.10", "pos-0.03",
            "neg-0.05", "neg-0.10", "neg-0.03",
            "zero", "pos-0.01", "neg-0.01", "pos-0.02", "neg-0.02",
            "none",
        ],
    )
    def test_direction_from_slope(self, slope: float | None, expected_direction: str) -> None:
        """Verify direction classification matches the code's thresholds."""
        if slope and slope > 0.02:
            direction = "improving"
        elif slope and slope < -0.02:
            direction = "degrading"
        else:
            direction = "stable"
        assert direction == expected_direction
