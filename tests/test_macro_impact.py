"""Tests for rot.macro.impact — EventImpactAnalyzer."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from rot.macro.impact import EventImpactAnalyzer
from rot.macro.types import EventImpact, HistoricalReaction


# ── Helpers ────────────────────────────────────────────────────────────


def _make_db() -> MagicMock:
    """Create a mock db with standard async methods."""
    db = MagicMock()
    db.get_event_impact_cache = AsyncMock(return_value=None)
    db.query_macro_events = AsyncMock(return_value=[])
    db.save_event_impact_cache = AsyncMock()
    return db


def _make_row(
    scheduled_at: float = 1_700_000_000.0,
    spy_move: float = 0.5,
    vix_change: float = 1.2,
    surprise_pct: float = 0.1,
    sector_moves: dict | None = None,
) -> dict:
    """Build a row dict like the DB would return."""
    return {
        "scheduled_at": scheduled_at,
        "surprise_pct": surprise_pct,
        "meta": {
            "spy_move_pct": spy_move,
            "vix_change": vix_change,
            "sector_moves": sector_moves or {},
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# 1. analyze_impact
# ═══════════════════════════════════════════════════════════════════════


class TestAnalyzeImpactNoRows:
    """analyze_impact with no historical data."""

    @pytest.mark.asyncio
    async def test_returns_zero_impact(self) -> None:
        db = _make_db()
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.analyze_impact("cpi")

        assert result.event_type == "cpi"
        assert result.avg_spy_move_pct == 0.0
        assert result.avg_vix_change == 0.0
        assert result.sample_size == 0
        assert result.historical_reactions == []

    @pytest.mark.asyncio
    async def test_does_not_save_cache_on_empty(self) -> None:
        db = _make_db()
        analyzer = EventImpactAnalyzer(db)

        await analyzer.analyze_impact("cpi")

        db.save_event_impact_cache.assert_not_called()


class TestAnalyzeImpactWithRows:
    """analyze_impact with historical data rows."""

    @pytest.mark.asyncio
    async def test_computes_averages_correctly(self) -> None:
        db = _make_db()
        db.query_macro_events.return_value = [
            _make_row(spy_move=1.0, vix_change=2.0),
            _make_row(spy_move=-0.5, vix_change=1.0),
            _make_row(spy_move=0.5, vix_change=3.0),
        ]
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.analyze_impact("nonfarm_payrolls")

        # avg_spy = (1.0 + -0.5 + 0.5) / 3 = 0.3333
        assert result.avg_spy_move_pct == round(1.0 / 3, 4)
        # avg_vix = (2.0 + 1.0 + 3.0) / 3 = 2.0
        assert result.avg_vix_change == 2.0
        assert result.sample_size == 3
        assert result.max_spy_move_pct == 1.0
        assert result.min_spy_move_pct == -0.5

    @pytest.mark.asyncio
    async def test_saves_cache_after_compute(self) -> None:
        db = _make_db()
        db.query_macro_events.return_value = [_make_row()]
        analyzer = EventImpactAnalyzer(db)

        await analyzer.analyze_impact("cpi")

        db.save_event_impact_cache.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_populates_most_affected_sectors(self) -> None:
        """FOMC maps to monetary_policy -> [Financials, Real Estate, ...]."""
        db = _make_db()
        db.query_macro_events.return_value = [_make_row()]
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.analyze_impact("fomc_decision")

        assert "Financials" in result.most_affected_sectors
        assert "Real Estate" in result.most_affected_sectors

    @pytest.mark.asyncio
    async def test_meta_as_json_string(self) -> None:
        """Row meta stored as JSON string should be parsed."""
        db = _make_db()
        db.query_macro_events.return_value = [
            {
                "scheduled_at": 1_700_000_000.0,
                "surprise_pct": 0.0,
                "meta": json.dumps({"spy_move_pct": 0.8, "vix_change": 1.5}),
            }
        ]
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.analyze_impact("cpi")

        assert result.avg_spy_move_pct == 0.8
        assert result.avg_vix_change == 1.5

    @pytest.mark.asyncio
    async def test_limits_reactions_to_50(self) -> None:
        db = _make_db()
        db.query_macro_events.return_value = [
            _make_row(scheduled_at=float(i)) for i in range(80)
        ]
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.analyze_impact("cpi")

        assert len(result.historical_reactions) <= 50
        assert result.sample_size == 80

    @pytest.mark.asyncio
    async def test_null_surprise_treated_as_zero(self) -> None:
        db = _make_db()
        db.query_macro_events.return_value = [
            {
                "scheduled_at": 1_700_000_000.0,
                "surprise_pct": None,
                "meta": {"spy_move_pct": 0.3, "vix_change": 0.5},
            }
        ]
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.analyze_impact("cpi")

        assert result.historical_reactions[0].surprise_pct == 0.0


class TestAnalyzeImpactCache:
    """Cache hit / miss behaviour."""

    @pytest.mark.asyncio
    async def test_fresh_cache_returned_without_query(self) -> None:
        db = _make_db()
        db.get_event_impact_cache.return_value = {
            "event_type": "cpi",
            "avg_spy_move": 0.5,
            "avg_vix_change": 1.0,
            "sample_size": 10,
            "computed_at": time.time(),  # fresh
            "reactions_json": "[]",
            "sector_sensitivity_json": "[]",
        }
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.analyze_impact("cpi")

        assert result.event_type == "cpi"
        assert result.avg_spy_move_pct == 0.5
        db.query_macro_events.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stale_cache_triggers_recompute(self) -> None:
        db = _make_db()
        db.get_event_impact_cache.return_value = {
            "event_type": "cpi",
            "avg_spy_move": 0.5,
            "avg_vix_change": 1.0,
            "sample_size": 10,
            "computed_at": time.time() - 100_000,  # stale (>86400)
            "reactions_json": "[]",
            "sector_sensitivity_json": "[]",
        }
        db.query_macro_events.return_value = [_make_row(spy_move=0.2, vix_change=0.3)]
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.analyze_impact("cpi")

        db.query_macro_events.assert_awaited_once()
        assert result.avg_spy_move_pct == 0.2

    @pytest.mark.asyncio
    async def test_cache_missing_computed_at_triggers_recompute(self) -> None:
        db = _make_db()
        db.get_event_impact_cache.return_value = {
            "event_type": "cpi",
            "avg_spy_move": 0.5,
        }
        db.query_macro_events.return_value = [_make_row(spy_move=0.9, vix_change=0.1)]
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.analyze_impact("cpi")

        db.query_macro_events.assert_awaited_once()
        assert result.avg_spy_move_pct == 0.9


# ═══════════════════════════════════════════════════════════════════════
# 2. predict_impact
# ═══════════════════════════════════════════════════════════════════════


class TestPredictImpactLowSample:
    """predict_impact with fewer than 5 samples."""

    @pytest.mark.asyncio
    async def test_returns_low_confidence(self) -> None:
        db = _make_db()
        db.query_macro_events.return_value = [_make_row(), _make_row()]
        analyzer = EventImpactAnalyzer(db)

        pred = await analyzer.predict_impact("cpi")

        assert pred["confidence"] == "low"
        assert pred["expected_spy_move_pct"] == 0.0
        assert pred["sample_size"] == 2
        assert "Insufficient" in pred["recommendation"]


class TestPredictImpactConfidence:
    """Confidence level determination in predict_impact."""

    @pytest.mark.asyncio
    async def test_high_confidence(self) -> None:
        """>=20 samples, low CV -> high."""
        db = _make_db()
        # 25 rows all with identical moves -> stdev=0 -> CV extremely low
        db.query_macro_events.return_value = [
            _make_row(spy_move=0.5, vix_change=1.0) for _ in range(25)
        ]
        analyzer = EventImpactAnalyzer(db)

        pred = await analyzer.predict_impact("cpi")

        assert pred["confidence"] == "high"
        assert pred["sample_size"] == 25

    @pytest.mark.asyncio
    async def test_medium_confidence(self) -> None:
        """>=10 samples, moderate CV -> medium."""
        db = _make_db()
        # 15 samples: alternating moves give moderate CV
        rows = []
        for i in range(15):
            move = 0.5 if i % 2 == 0 else 0.3
            rows.append(_make_row(spy_move=move, vix_change=1.0))
        db.query_macro_events.return_value = rows
        analyzer = EventImpactAnalyzer(db)

        pred = await analyzer.predict_impact("cpi")

        assert pred["confidence"] == "medium"

    @pytest.mark.asyncio
    async def test_low_confidence_high_variability(self) -> None:
        """Few samples with high variability -> low."""
        db = _make_db()
        db.query_macro_events.return_value = [
            _make_row(spy_move=5.0, vix_change=1.0),
            _make_row(spy_move=0.01, vix_change=1.0),
            _make_row(spy_move=3.0, vix_change=1.0),
            _make_row(spy_move=0.02, vix_change=1.0),
            _make_row(spy_move=4.0, vix_change=1.0),
            _make_row(spy_move=0.01, vix_change=1.0),
        ]
        analyzer = EventImpactAnalyzer(db)

        pred = await analyzer.predict_impact("cpi")

        assert pred["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_high_impact_recommendation(self) -> None:
        """avg_abs_move > 1.0 => straddle/strangle recommendation."""
        db = _make_db()
        db.query_macro_events.return_value = [
            _make_row(spy_move=1.5, vix_change=3.0) for _ in range(25)
        ]
        analyzer = EventImpactAnalyzer(db)

        pred = await analyzer.predict_impact("fomc_decision")

        assert "straddle" in pred["recommendation"].lower()

    @pytest.mark.asyncio
    async def test_moderate_impact_recommendation(self) -> None:
        """avg_abs_move between 0.5 and 1.0 => surprise deviation rec."""
        db = _make_db()
        db.query_macro_events.return_value = [
            _make_row(spy_move=0.7, vix_change=1.0) for _ in range(25)
        ]
        analyzer = EventImpactAnalyzer(db)

        pred = await analyzer.predict_impact("cpi")

        assert "surprise" in pred["recommendation"].lower()

    @pytest.mark.asyncio
    async def test_low_impact_recommendation(self) -> None:
        """avg_abs_move < 0.5 => low impact rec."""
        db = _make_db()
        db.query_macro_events.return_value = [
            _make_row(spy_move=0.1, vix_change=0.2) for _ in range(25)
        ]
        analyzer = EventImpactAnalyzer(db)

        pred = await analyzer.predict_impact("cpi")

        assert "low historical impact" in pred["recommendation"].lower()


# ═══════════════════════════════════════════════════════════════════════
# 3. get_sector_sensitivity
# ═══════════════════════════════════════════════════════════════════════


class TestGetSectorSensitivity:

    @pytest.mark.asyncio
    async def test_aggregates_sector_moves(self) -> None:
        db = _make_db()
        db.query_macro_events.return_value = [
            _make_row(sector_moves={"Technology": 1.0, "Financials": -0.5}),
            _make_row(sector_moves={"Technology": -2.0, "Energy": 0.3}),
        ]
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.get_sector_sensitivity("cpi")

        # Technology: mean(abs(1.0), abs(-2.0)) = 1.5
        assert result["Technology"] == 1.5
        # Financials: mean(abs(-0.5)) = 0.5
        assert result["Financials"] == 0.5
        # Energy: mean(abs(0.3)) = 0.3
        assert result["Energy"] == 0.3

    @pytest.mark.asyncio
    async def test_empty_reactions_returns_empty_dict(self) -> None:
        db = _make_db()
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.get_sector_sensitivity("cpi")

        assert result == {}


# ═══════════════════════════════════════════════════════════════════════
# 4. get_surprise_correlation
# ═══════════════════════════════════════════════════════════════════════


class TestGetSurpriseCorrelation:

    @pytest.mark.asyncio
    async def test_returns_correlation_for_sufficient_data(self) -> None:
        db = _make_db()
        # Create rows where surprise and move are perfectly correlated
        db.query_macro_events.return_value = [
            _make_row(spy_move=float(i), surprise_pct=float(i))
            for i in range(1, 8)
        ]
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.get_surprise_correlation("cpi")

        assert result == 1.0

    @pytest.mark.asyncio
    async def test_fewer_than_5_nonzero_returns_zero(self) -> None:
        db = _make_db()
        # Only 3 rows with nonzero surprise
        db.query_macro_events.return_value = [
            _make_row(spy_move=1.0, surprise_pct=1.0),
            _make_row(spy_move=2.0, surprise_pct=2.0),
            _make_row(spy_move=3.0, surprise_pct=3.0),
            _make_row(spy_move=4.0, surprise_pct=0.0),  # zero surprise excluded
        ]
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.get_surprise_correlation("cpi")

        assert result == 0.0

    @pytest.mark.asyncio
    async def test_no_data_returns_zero(self) -> None:
        db = _make_db()
        analyzer = EventImpactAnalyzer(db)

        result = await analyzer.get_surprise_correlation("cpi")

        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════
# 5. _pearson (static method)
# ═══════════════════════════════════════════════════════════════════════


class TestPearson:

    def test_perfect_positive_correlation(self) -> None:
        result = EventImpactAnalyzer._pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
        assert result == 1.0

    def test_perfect_negative_correlation(self) -> None:
        result = EventImpactAnalyzer._pearson([1, 2, 3, 4, 5], [10, 8, 6, 4, 2])
        assert result == -1.0

    def test_no_correlation(self) -> None:
        # Orthogonal signals: should be near zero
        result = EventImpactAnalyzer._pearson(
            [1, -1, 1, -1, 1, -1],
            [1, 1, -1, -1, 1, 1],
        )
        assert abs(result) < 0.5

    def test_n_less_than_2_returns_zero(self) -> None:
        assert EventImpactAnalyzer._pearson([1.0], [2.0]) == 0.0
        assert EventImpactAnalyzer._pearson([], []) == 0.0

    def test_zero_denominator_returns_zero(self) -> None:
        """All identical values -> zero std -> zero denominator."""
        result = EventImpactAnalyzer._pearson([5, 5, 5], [1, 2, 3])
        assert result == 0.0

    def test_both_constant_returns_zero(self) -> None:
        result = EventImpactAnalyzer._pearson([3, 3, 3], [7, 7, 7])
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════
# 6. _cache_to_impact (static method)
# ═══════════════════════════════════════════════════════════════════════


class TestCacheToImpact:

    def test_normal_dict(self) -> None:
        cached = {
            "event_type": "cpi",
            "avg_spy_move": 0.35,
            "avg_vix_change": 1.2,
            "sample_size": 15,
            "reactions_json": [
                {
                    "date": 1_700_000_000.0,
                    "spy_move_pct": 0.5,
                    "vix_change": 1.0,
                    "surprise_pct": 0.1,
                    "sector_moves": {"Tech": 0.3},
                }
            ],
            "sector_sensitivity_json": ["Financials", "Technology"],
        }
        result = EventImpactAnalyzer._cache_to_impact(cached)

        assert result.event_type == "cpi"
        assert result.avg_spy_move_pct == 0.35
        assert result.avg_vix_change == 1.2
        assert result.sample_size == 15
        assert len(result.historical_reactions) == 1
        assert result.historical_reactions[0].spy_move_pct == 0.5
        assert result.historical_reactions[0].sector_moves == {"Tech": 0.3}
        assert result.most_affected_sectors == ["Financials", "Technology"]

    def test_reactions_json_as_string(self) -> None:
        cached = {
            "event_type": "nfp",
            "avg_spy_move": 0.2,
            "avg_vix_change": 0.5,
            "sample_size": 3,
            "reactions_json": json.dumps([
                {"date": 1.0, "spy_move_pct": 0.1, "vix_change": 0.2},
            ]),
            "sector_sensitivity_json": json.dumps(["Energy"]),
        }
        result = EventImpactAnalyzer._cache_to_impact(cached)

        assert len(result.historical_reactions) == 1
        assert result.historical_reactions[0].spy_move_pct == 0.1
        assert result.most_affected_sectors == ["Energy"]

    def test_missing_fields_use_defaults(self) -> None:
        result = EventImpactAnalyzer._cache_to_impact({})

        assert result.event_type == ""
        assert result.avg_spy_move_pct == 0.0
        assert result.avg_vix_change == 0.0
        assert result.sample_size == 0
        assert result.historical_reactions == []
        assert result.most_affected_sectors == []

    def test_invalid_reactions_json_string(self) -> None:
        cached = {
            "event_type": "cpi",
            "reactions_json": "not valid json{{",
            "sector_sensitivity_json": "also bad",
        }
        result = EventImpactAnalyzer._cache_to_impact(cached)

        assert result.historical_reactions == []
        assert result.most_affected_sectors == []

    def test_non_dict_items_in_reactions_skipped(self) -> None:
        cached = {
            "event_type": "cpi",
            "reactions_json": [
                {"date": 1.0, "spy_move_pct": 0.5, "vix_change": 0.3},
                "not a dict",
                42,
                None,
            ],
        }
        result = EventImpactAnalyzer._cache_to_impact(cached)

        assert len(result.historical_reactions) == 1


# ═══════════════════════════════════════════════════════════════════════
# 7. Confidence logic edge cases
# ═══════════════════════════════════════════════════════════════════════


class TestConfidenceEdgeCases:

    @pytest.mark.asyncio
    async def test_exactly_5_samples_exits_low_sample_branch(self) -> None:
        db = _make_db()
        db.query_macro_events.return_value = [
            _make_row(spy_move=0.5, vix_change=1.0) for _ in range(5)
        ]
        analyzer = EventImpactAnalyzer(db)

        pred = await analyzer.predict_impact("cpi")

        # With 5 identical samples: stdev=0, CV=0 => but sample_size < 10
        # so not medium or high, falls to low
        assert pred["confidence"] == "low"
        assert "Insufficient" not in pred["recommendation"]

    @pytest.mark.asyncio
    async def test_exactly_20_samples_with_low_cv(self) -> None:
        db = _make_db()
        db.query_macro_events.return_value = [
            _make_row(spy_move=0.5, vix_change=1.0) for _ in range(20)
        ]
        analyzer = EventImpactAnalyzer(db)

        pred = await analyzer.predict_impact("cpi")

        assert pred["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_zero_abs_moves_cv_defaults_high(self) -> None:
        """When avg_abs < 0.01 the CV is set to 999.0 -> low confidence."""
        db = _make_db()
        db.query_macro_events.return_value = [
            _make_row(spy_move=0.0, vix_change=0.0) for _ in range(25)
        ]
        analyzer = EventImpactAnalyzer(db)

        pred = await analyzer.predict_impact("cpi")

        assert pred["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_prediction_includes_max_historical_move(self) -> None:
        db = _make_db()
        db.query_macro_events.return_value = [
            _make_row(spy_move=0.3, vix_change=0.5),
            _make_row(spy_move=0.8, vix_change=0.5),
            _make_row(spy_move=0.3, vix_change=0.5),
            _make_row(spy_move=0.3, vix_change=0.5),
            _make_row(spy_move=0.3, vix_change=0.5),
        ]
        analyzer = EventImpactAnalyzer(db)

        pred = await analyzer.predict_impact("cpi")

        assert pred["max_historical_move"] == 0.8
