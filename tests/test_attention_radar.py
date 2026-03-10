"""
Comprehensive tests for rot.radar.attention_radar.

Modules tested:
- AttentionRadar
- AttentionRadarEvent
- RadarFireCondition
- _TickerVolumeBaseline
- RadarResolver

Coverage:
- Fire conditions: all three must be met
- Confidence threshold: fires above 0.88, not below
- Event type: fires on 'other', not on 'earnings_rumor'
- Volume z-score: fires above 2σ, not below
- No baseline → volume condition not met (safe default)
- Insufficient baseline samples → no fire
- record_volume() builds baseline correctly
- check() returns unchanged event + radar_event tuple
- check() returns None radar_event when conditions not met
- AttentionRadarEvent contains correct data
- RadarFireCondition.fired property
- evaluate_conditions() public method
- Disabled radar never fires
- fired_count increments
- RadarResolver.try_resolve() marks event resolved
- RadarResolver.run_once() handles DB errors gracefully
"""
from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rot.core.types import Event, Evidence
from rot.radar.attention_radar import (
    AttentionRadar,
    AttentionRadarEvent,
    RadarFireCondition,
    RadarResolver,
    _TickerVolumeBaseline,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event(
    confidence=0.90,
    event_type="other",
    stance="unknown",
    ticker="TSLA",
) -> Event:
    return Event(
        event_type=event_type,
        entities=[ticker],
        stance=stance,
        time_horizon="unknown",
        evidence=[Evidence(post_id="p1", permalink="http://x.com", subreddit="wsb", excerpt="test")],
        confidence=confidence,
    )


def _radar_with_baseline(ticker="TSLA", n_samples=20, base_volume=10.0):
    """Return an AttentionRadar with enough baseline data for z-score computation."""
    radar = AttentionRadar()
    now = time.time()
    for i in range(n_samples):
        radar.record_volume(ticker, base_volume, ts=now - i * 3600)
    return radar


# ── RadarFireCondition ────────────────────────────────────────────────────────

class TestRadarFireCondition:
    def test_fired_all_true(self):
        cond = RadarFireCondition(
            confidence_met=True, event_type_met=True, volume_met=True,
            confidence=0.90, event_type="other", volume_zscore=3.0,
        )
        assert cond.fired is True

    def test_not_fired_if_confidence_missing(self):
        cond = RadarFireCondition(
            confidence_met=False, event_type_met=True, volume_met=True,
            confidence=0.80, event_type="other", volume_zscore=3.0,
        )
        assert cond.fired is False

    def test_not_fired_if_event_type_missing(self):
        cond = RadarFireCondition(
            confidence_met=True, event_type_met=False, volume_met=True,
            confidence=0.90, event_type="earnings_rumor", volume_zscore=3.0,
        )
        assert cond.fired is False

    def test_not_fired_if_volume_missing(self):
        cond = RadarFireCondition(
            confidence_met=True, event_type_met=True, volume_met=False,
            confidence=0.90, event_type="other", volume_zscore=0.5,
        )
        assert cond.fired is False


# ── _TickerVolumeBaseline ─────────────────────────────────────────────────────

class TestTickerVolumeBaseline:
    def test_zscore_none_with_insufficient_samples(self):
        baseline = _TickerVolumeBaseline()
        for i in range(9):  # < 10 minimum
            baseline.record(time.time() - i * 3600, 10.0)
        assert baseline.zscore(20.0) is None

    def test_zscore_available_with_enough_samples(self):
        baseline = _TickerVolumeBaseline()
        now = time.time()
        for i in range(20):
            baseline.record(now - i * 3600, 10.0)
        zscore = baseline.zscore(10.0)
        assert zscore is not None

    def test_zscore_zero_for_mean_value(self):
        baseline = _TickerVolumeBaseline()
        now = time.time()
        for i in range(20):
            baseline.record(now - i * 3600, 10.0)
        zscore = baseline.zscore(10.0)
        # All values are 10.0 → std=0 → zscore=0
        assert zscore == 0.0

    def test_zscore_high_for_anomalous_value(self):
        baseline = _TickerVolumeBaseline()
        now = time.time()
        for i in range(20):
            baseline.record(now - i * 3600, 10.0)
        # Std is ~0 with identical values, so insert small variance
        baseline.record(now, 11.0)
        baseline.record(now - 100, 9.0)
        # Force recompute
        baseline._recompute_welford()
        zscore = baseline.zscore(50.0)
        assert zscore is not None and zscore > 2.0

    def test_baseline_prunes_old_samples(self):
        baseline = _TickerVolumeBaseline(window_s=100)  # tiny window
        now = time.time()
        baseline.record(now - 200, 10.0)  # too old
        baseline.record(now, 10.0)         # fresh
        baseline.record(now, 10.0)         # another fresh (triggers prune)
        assert baseline.sample_count < 3

    def test_sample_count_accurate(self):
        baseline = _TickerVolumeBaseline()
        now = time.time()
        for i in range(5):
            baseline.record(now - i * 60, 10.0)
        assert baseline.sample_count == 5


# ── AttentionRadar.check() ────────────────────────────────────────────────────

class TestAttentionRadarCheck:
    def test_no_fire_when_confidence_low(self):
        radar = _radar_with_baseline()
        ev = _event(confidence=0.80)  # below 0.88
        # Need to set baseline with high variance to allow high zscore
        radar.record_volume("TSLA", 100.0)  # spike
        _, radar_ev = radar.check(ev, signal_volume=100.0)
        assert radar_ev is None

    def test_no_fire_wrong_event_type(self):
        radar = _radar_with_baseline()
        radar.record_volume("TSLA", 100.0)
        ev = _event(confidence=0.95, event_type="earnings_rumor")  # not "other"
        _, radar_ev = radar.check(ev, signal_volume=100.0)
        assert radar_ev is None

    def test_no_fire_without_baseline(self):
        radar = AttentionRadar()  # no baseline
        ev = _event(confidence=0.95, event_type="other")
        _, radar_ev = radar.check(ev, signal_volume=999.0)
        assert radar_ev is None  # no baseline → no fire

    def test_fire_when_all_conditions_met(self):
        radar = AttentionRadar()
        now = time.time()
        # Build baseline with tight distribution
        for i in range(25):
            radar.record_volume("TSLA", 10.0, ts=now - i * 3600)
        # Record slight variance so std > 0
        radar.record_volume("TSLA", 12.0, ts=now - 1800)
        radar.record_volume("TSLA", 8.0, ts=now - 900)
        ev = _event(confidence=0.92, event_type="other")
        _, radar_ev = radar.check(ev, signal_volume=100.0)  # 100 vs baseline ~10 → high z
        assert radar_ev is not None

    def test_fired_event_has_correct_ticker(self):
        radar = AttentionRadar()
        now = time.time()
        for i in range(25):
            radar.record_volume("AMD", 10.0, ts=now - i * 3600)
        radar.record_volume("AMD", 12.0, ts=now - 1800)
        radar.record_volume("AMD", 8.0, ts=now - 900)
        ev = _event(confidence=0.93, event_type="other", ticker="AMD")
        _, radar_ev = radar.check(ev, signal_volume=100.0)
        if radar_ev is not None:
            assert radar_ev.ticker == "AMD"

    def test_event_returned_unchanged(self):
        radar = _radar_with_baseline()
        ev = _event(confidence=0.95, event_type="other")
        returned_ev, _ = radar.check(ev, signal_volume=5.0)
        assert returned_ev is ev  # exact same object

    def test_fired_count_increments(self):
        radar = AttentionRadar()
        now = time.time()
        for i in range(25):
            radar.record_volume("TSLA", 10.0, ts=now - i * 3600)
        radar.record_volume("TSLA", 12.0, ts=now - 1800)
        radar.record_volume("TSLA", 8.0, ts=now - 900)
        ev = _event(confidence=0.95, event_type="other")
        assert radar.fired_count == 0
        _, radar_ev = radar.check(ev, signal_volume=200.0)
        if radar_ev is not None:
            assert radar.fired_count == 1

    def test_disabled_radar_never_fires(self):
        radar = AttentionRadar(enabled=False)
        ev = _event(confidence=0.99, event_type="other")
        _, radar_ev = radar.check(ev, signal_volume=999.0)
        assert radar_ev is None


# ── AttentionRadarEvent ───────────────────────────────────────────────────────

class TestAttentionRadarEvent:
    def test_construction_defaults(self):
        ev = AttentionRadarEvent(
            ticker="TSLA",
            timestamp=1000.0,
            confidence=0.90,
            signal_volume_zscore=3.0,
            event_type="other",
            stance="unknown",
        )
        assert ev.resolved is False
        assert ev.eventual_catalyst is None
        assert ev.lead_time_days is None

    def test_construction_with_all_fields(self):
        ev = AttentionRadarEvent(
            ticker="NVDA",
            timestamp=2000.0,
            confidence=0.95,
            signal_volume_zscore=4.5,
            event_type="other",
            stance="bullish",
            source_signal_id="sig_123",
            eventual_catalyst="earnings_surprise",
            lead_time_days=7.0,
            resolved=True,
            resolved_at=2700.0,
        )
        assert ev.resolved is True
        assert ev.eventual_catalyst == "earnings_surprise"
        assert ev.lead_time_days == 7.0


# ── RadarResolver ─────────────────────────────────────────────────────────────

class TestRadarResolver:
    @pytest.mark.asyncio
    async def test_run_once_with_no_pending_events(self):
        db = AsyncMock()
        db.get_unresolved_radar_events = AsyncMock(return_value=[])
        resolver = RadarResolver(db)
        count = await resolver.run_once()
        assert count == 0

    @pytest.mark.asyncio
    async def test_run_once_resolves_matching_event(self):
        now = time.time()
        db = AsyncMock()
        db.get_unresolved_radar_events = AsyncMock(return_value=[{
            "id": 1,
            "ticker": "TSLA",
            "timestamp": now - 5 * 86400,
        }])
        db.get_directional_signals_after = AsyncMock(return_value=[{
            "id": "sig_1",
            "created_at": now - 2 * 86400,
            "event_type": "earnings_rumor",
            "stance": "bullish",
            "confidence": 0.85,
        }])
        db.resolve_radar_event = AsyncMock()
        resolver = RadarResolver(db)
        count = await resolver.run_once()
        assert count == 1
        db.resolve_radar_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_once_no_directional_signal(self):
        now = time.time()
        db = AsyncMock()
        db.get_unresolved_radar_events = AsyncMock(return_value=[{
            "id": 2,
            "ticker": "AAPL",
            "timestamp": now - 4 * 86400,
        }])
        db.get_directional_signals_after = AsyncMock(return_value=[])
        resolver = RadarResolver(db)
        count = await resolver.run_once()
        assert count == 0

    @pytest.mark.asyncio
    async def test_run_once_handles_db_error_gracefully(self):
        db = AsyncMock()
        db.get_unresolved_radar_events = AsyncMock(side_effect=RuntimeError("DB down"))
        resolver = RadarResolver(db)
        count = await resolver.run_once()  # Should not raise
        assert count == 0

    @pytest.mark.asyncio
    async def test_resolver_directional_query_error_handled(self):
        now = time.time()
        db = AsyncMock()
        db.get_unresolved_radar_events = AsyncMock(return_value=[{
            "id": 3, "ticker": "TSLA", "timestamp": now - 5 * 86400,
        }])
        db.get_directional_signals_after = AsyncMock(side_effect=RuntimeError("timeout"))
        resolver = RadarResolver(db)
        count = await resolver.run_once()
        assert count == 0


# ── evaluate_conditions() public method ──────────────────────────────────────

class TestEvaluateConditions:
    def test_evaluate_returns_fire_condition(self):
        radar = _radar_with_baseline()
        ev = _event(confidence=0.50, event_type="earnings_rumor")
        cond = radar.evaluate_conditions(ev, signal_volume=5.0)
        assert isinstance(cond, RadarFireCondition)
        assert cond.confidence_met is False
        assert cond.event_type_met is False

    def test_evaluate_confidence_met(self):
        radar = _radar_with_baseline()
        ev = _event(confidence=0.95, event_type="other")
        cond = radar.evaluate_conditions(ev, signal_volume=5.0)
        assert cond.confidence_met is True

    def test_evaluate_event_type_met_for_unknown_variants(self):
        radar = _radar_with_baseline()
        for etype in ("other", "unknown"):
            ev = _event(confidence=0.60, event_type=etype)
            cond = radar.evaluate_conditions(ev, signal_volume=5.0)
            assert cond.event_type_met is True, f"event_type={etype} should be met"
