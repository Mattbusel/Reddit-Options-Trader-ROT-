"""
Comprehensive tests for rot.control.helix_config.

Modules tested:
- HelixConfig
- ConfigSnapshot

Coverage:
- snapshot() saves current LiveTuning state
- snapshot() increments counter
- snapshot() records trigger and accuracy
- rollback() restores previous state
- rollback() returns target snapshot
- rollback() with empty history returns None
- rollback() with single entry returns None
- rollback_to_best() finds highest accuracy snapshot
- rollback_to_best() falls back to oldest when no accuracy
- history() returns all snapshots oldest-first
- latest() returns most recent
- diff() identifies changed params
- diff() returns empty when no changes
- history cap limits memory usage
- rollback_count increments correctly
"""
from __future__ import annotations

import math
import time

import pytest

from rot.control.helix_config import HelixConfig, ConfigSnapshot
from rot.control.live_tuning import LiveTuning, ParameterId


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def lt():
    return LiveTuning()


@pytest.fixture
def helix(lt):
    return HelixConfig(lt, history_cap=20)


# ── ConfigSnapshot ────────────────────────────────────────────────────────────

class TestConfigSnapshot:
    def test_construction(self, lt):
        values = lt.snapshot()
        snap = ConfigSnapshot(snap_id=1, ts=time.time(), values=values, trigger="test")
        assert snap.snap_id == 1
        assert snap.trigger == "test"
        assert snap.accuracy_at_snap is None

    def test_with_accuracy(self, lt):
        snap = ConfigSnapshot(snap_id=2, ts=time.time(), values=lt.snapshot(),
                               accuracy_at_snap=0.72)
        assert snap.accuracy_at_snap == 0.72


# ── HelixConfig.snapshot() ────────────────────────────────────────────────────

class TestHelixSnapshot:
    def test_snapshot_increments_counter(self, helix):
        assert helix.snapshot_count == 0
        helix.snapshot()
        assert helix.snapshot_count == 1
        helix.snapshot()
        assert helix.snapshot_count == 2

    def test_snapshot_returns_config_snapshot(self, helix):
        snap = helix.snapshot()
        assert isinstance(snap, ConfigSnapshot)
        assert snap.snap_id == 1

    def test_snapshot_captures_current_values(self, lt, helix):
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.3)
        snap = helix.snapshot()
        assert math.isclose(snap.values[ParameterId.CONFIDENCE_FLOOR], 0.3, abs_tol=0.01)

    def test_snapshot_trigger_recorded(self, helix):
        snap = helix.snapshot(trigger="pid_adjustment")
        assert snap.trigger == "pid_adjustment"

    def test_snapshot_accuracy_recorded(self, helix):
        snap = helix.snapshot(accuracy_at_snap=0.65)
        assert snap.accuracy_at_snap == 0.65

    def test_snapshot_added_to_history(self, helix):
        helix.snapshot()
        helix.snapshot()
        assert len(helix.history()) == 2

    def test_history_cap_respected(self, lt):
        helix = HelixConfig(lt, history_cap=5)
        for _ in range(10):
            helix.snapshot()
        assert len(helix.history()) == 5


# ── HelixConfig.rollback() ────────────────────────────────────────────────────

class TestHelixRollback:
    def test_rollback_empty_history_returns_none(self, helix):
        result = helix.rollback()
        assert result is None

    def test_rollback_single_entry_returns_none(self, helix):
        helix.snapshot()
        result = helix.rollback()
        assert result is None

    def test_rollback_restores_previous_state(self, lt, helix):
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.1)
        helix.snapshot(trigger="baseline")   # snap #1
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.5)
        helix.snapshot(trigger="pid_adjustment")  # snap #2 (current)

        result = helix.rollback()
        assert result is not None
        # LiveTuning should be restored to the baseline
        assert math.isclose(lt.get(ParameterId.CONFIDENCE_FLOOR), 0.1, abs_tol=0.01)

    def test_rollback_returns_target_snapshot(self, lt, helix):
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.2)
        helix.snapshot(trigger="v1")
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.4)
        helix.snapshot(trigger="v2")
        result = helix.rollback()
        assert result is not None
        assert result.trigger == "v1"

    def test_rollback_increments_rollback_count(self, lt, helix):
        helix.snapshot()
        helix.snapshot()
        assert helix.rollback_count == 0
        helix.rollback()
        assert helix.rollback_count == 1

    def test_multiple_rollbacks(self, lt, helix):
        for i in range(5):
            lt.set(ParameterId.CONFIDENCE_FLOOR, float(i) * 0.1)
            helix.snapshot()
        helix.rollback()
        helix.rollback()
        assert helix.rollback_count == 2


# ── HelixConfig.rollback_to_best() ───────────────────────────────────────────

class TestHelixRollbackToBest:
    def test_rollback_to_best_accuracy(self, lt, helix):
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.1)
        helix.snapshot(accuracy_at_snap=0.5)
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.3)
        helix.snapshot(accuracy_at_snap=0.8)  # best
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.5)
        helix.snapshot(accuracy_at_snap=0.6)

        result = helix.rollback_to_best(window_s=86400)
        assert result is not None
        assert result.accuracy_at_snap == 0.8
        assert math.isclose(lt.get(ParameterId.CONFIDENCE_FLOOR), 0.3, abs_tol=0.01)

    def test_rollback_to_best_no_accuracy_uses_oldest(self, lt, helix):
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.1)
        helix.snapshot()  # oldest, no accuracy
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.9)
        helix.snapshot()

        result = helix.rollback_to_best(window_s=86400)
        assert result is not None
        # Should use oldest when no accuracy data
        assert math.isclose(lt.get(ParameterId.CONFIDENCE_FLOOR), 0.1, abs_tol=0.01)

    def test_rollback_to_best_empty_history(self, helix):
        result = helix.rollback_to_best()
        assert result is None


# ── HelixConfig.history() and latest() ───────────────────────────────────────

class TestHelixHistory:
    def test_history_empty_initially(self, helix):
        assert helix.history() == []

    def test_history_ordered_oldest_first(self, lt, helix):
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.1)
        s1 = helix.snapshot()
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.2)
        s2 = helix.snapshot()
        history = helix.history()
        assert history[0].snap_id == s1.snap_id
        assert history[1].snap_id == s2.snap_id

    def test_latest_returns_most_recent(self, helix):
        helix.snapshot()
        s2 = helix.snapshot()
        assert helix.latest().snap_id == s2.snap_id

    def test_latest_empty_history_returns_none(self, helix):
        assert helix.latest() is None


# ── HelixConfig.diff() ────────────────────────────────────────────────────────

class TestHelixDiff:
    def test_diff_identical_snapshots_empty(self, lt, helix):
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.2)
        snap = helix.snapshot()
        diff = helix.diff(snap, snap)
        assert diff == {}

    def test_diff_detects_changed_param(self, lt, helix):
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.1)
        snap_a = helix.snapshot()
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.5)
        snap_b = helix.snapshot()
        diff = helix.diff(snap_a, snap_b)
        assert ParameterId.CONFIDENCE_FLOOR in diff
        va, vb = diff[ParameterId.CONFIDENCE_FLOOR]
        assert math.isclose(va, 0.1, abs_tol=0.01)
        assert math.isclose(vb, 0.5, abs_tol=0.01)

    def test_diff_multiple_changes(self, lt, helix):
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.1)
        lt.set(ParameterId.SUPPRESS_THRESHOLD, 0.15)
        snap_a = helix.snapshot()
        lt.set(ParameterId.CONFIDENCE_FLOOR, 0.5)
        lt.set(ParameterId.SUPPRESS_THRESHOLD, 0.30)
        snap_b = helix.snapshot()
        diff = helix.diff(snap_a, snap_b)
        assert ParameterId.CONFIDENCE_FLOOR in diff
        assert ParameterId.SUPPRESS_THRESHOLD in diff
