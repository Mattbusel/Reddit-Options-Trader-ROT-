"""HelixConfig — snapshot and rollback system for pipeline parameters.

Ported from tokio-prompt-orchestrator/src/self_tune/snapshot.rs.

Every time TuningController applies a parameter adjustment, it calls
``HelixConfig.snapshot()`` first.  If signal accuracy degrades within the
rollback window, ``HelixConfig.rollback()`` restores the last known-good state.

Analogous to git: every PID-driven adjustment creates a commit; rollback
is a ``git reset --hard HEAD~1``.

Storage is in-memory with a configurable cap on history depth.  Persistence
(SQLite) is handled by ControlMixin in rot/storage/control_db.py.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from rot.control.live_tuning import LiveTuning, ParameterId

log = logging.getLogger(__name__)

_DEFAULT_HISTORY_CAP = 100


@dataclass
class ConfigSnapshot:
    """A timestamped snapshot of all parameter values.

    Attributes:
        snap_id: Auto-incrementing integer identifier.
        ts: Unix timestamp when snapshot was taken.
        values: Parameter values at the time of snapshot.
        trigger: Why this snapshot was taken (e.g. ``"pid_adjustment"``).
        accuracy_at_snap: Signal accuracy metric at time of snapshot, if known.
    """

    snap_id: int
    ts: float
    values: Dict[ParameterId, float]
    trigger: str = "manual"
    accuracy_at_snap: Optional[float] = None


class HelixConfig:
    """Snapshot and rollback system for LiveTuning parameters.

    Usage::

        helix = HelixConfig(live_tuning)
        helix.snapshot(trigger="pid_adjustment")  # before every PID write
        # ... PID applies new values to LiveTuning ...
        # Later, if accuracy degrades:
        helix.rollback()
    """

    def __init__(
        self,
        live_tuning: LiveTuning,
        history_cap: int = _DEFAULT_HISTORY_CAP,
    ) -> None:
        self._lt = live_tuning
        self._history_cap = history_cap
        self._history: Deque[ConfigSnapshot] = deque(maxlen=history_cap)
        self._counter = 0
        self._rollback_count = 0

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(
        self,
        trigger: str = "manual",
        accuracy_at_snap: Optional[float] = None,
    ) -> ConfigSnapshot:
        """Save current LiveTuning state as a new snapshot."""
        self._counter += 1
        snap = ConfigSnapshot(
            snap_id=self._counter,
            ts=time.time(),
            values=self._lt.snapshot(),
            trigger=trigger,
            accuracy_at_snap=accuracy_at_snap,
        )
        self._history.append(snap)
        log.debug(
            "HelixConfig: snapshot #%d trigger=%s accuracy=%s",
            snap.snap_id, trigger, accuracy_at_snap,
        )
        return snap

    # ── Rollback ──────────────────────────────────────────────────────────────

    def rollback(self, steps: int = 1) -> Optional[ConfigSnapshot]:
        """Restore LiveTuning to ``steps`` snapshots ago.

        Returns the snapshot that was restored, or None if history is empty.
        """
        if len(self._history) < 2:
            log.warning("HelixConfig: rollback requested but history is empty or has only 1 entry")
            return None
        # Pop the current (post-adjustment) snapshot, then go back `steps`
        target_idx = max(0, len(self._history) - 1 - steps)
        target = list(self._history)[target_idx]
        self._lt.restore(target.values)
        self._rollback_count += 1
        log.info(
            "HelixConfig: rolled back to snapshot #%d (trigger=%s, %d rollbacks total)",
            target.snap_id, target.trigger, self._rollback_count,
        )
        return target

    def rollback_to_best(
        self, window_s: float = 3600.0
    ) -> Optional[ConfigSnapshot]:
        """Rollback to the snapshot with the highest accuracy within the window.

        If no snapshot has recorded accuracy, falls back to the oldest snapshot
        in the window.
        """
        cutoff = time.time() - window_s
        candidates = [s for s in self._history if s.ts >= cutoff]
        if not candidates:
            return self.rollback()
        # Prefer highest accuracy, fall back to oldest if none have accuracy
        with_accuracy = [s for s in candidates if s.accuracy_at_snap is not None]
        if with_accuracy:
            best = max(with_accuracy, key=lambda s: s.accuracy_at_snap)  # type: ignore[arg-type]
        else:
            best = candidates[0]
        self._lt.restore(best.values)
        self._rollback_count += 1
        log.info(
            "HelixConfig: rolled back to best snapshot #%d accuracy=%s",
            best.snap_id, best.accuracy_at_snap,
        )
        return best

    # ── Inspection ────────────────────────────────────────────────────────────

    def history(self) -> List[ConfigSnapshot]:
        """Return all snapshots oldest-first."""
        return list(self._history)

    def latest(self) -> Optional[ConfigSnapshot]:
        """Return the most recent snapshot."""
        if not self._history:
            return None
        return self._history[-1]

    def diff(self, snap_a: ConfigSnapshot, snap_b: ConfigSnapshot) -> Dict[ParameterId, tuple[float, float]]:
        """Return params that changed between two snapshots.

        Returns {param_id → (value_in_a, value_in_b)} for every param
        whose value differs between snap_a and snap_b.
        """
        changed: Dict[ParameterId, tuple[float, float]] = {}
        all_keys = set(snap_a.values) | set(snap_b.values)
        for pid in all_keys:
            va = snap_a.values.get(pid, 0.0)
            vb = snap_b.values.get(pid, 0.0)
            if abs(va - vb) > 1e-9:
                changed[pid] = (va, vb)
        return changed

    @property
    def rollback_count(self) -> int:
        """Number of configuration rollbacks performed since startup."""
        return self._rollback_count

    @property
    def snapshot_count(self) -> int:
        """Total number of configuration snapshots taken since startup."""
        return self._counter
