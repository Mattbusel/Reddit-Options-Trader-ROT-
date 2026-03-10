"""ControlMixin — SQLite persistence for the Unified Control Plane.

Stores parameter snapshots and tuning history so the PID controller's
learned state survives process restarts.

Tables:
  control_snapshots — timestamped parameter snapshots (HelixConfig history)
  control_adjustments — every PID-driven parameter change with before/after
"""

from __future__ import annotations

import json
import time
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

CONTROL_SCHEMA = """
CREATE TABLE IF NOT EXISTS control_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snap_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'manual',
    accuracy_at_snap REAL,
    param_values TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_control_snapshots_created ON control_snapshots(created_at DESC);

CREATE TABLE IF NOT EXISTS control_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    param_id TEXT NOT NULL,
    value_before REAL NOT NULL,
    value_after REAL NOT NULL,
    accuracy_before REAL,
    trigger TEXT NOT NULL DEFAULT 'pid'
);
CREATE INDEX IF NOT EXISTS idx_control_adj_created ON control_adjustments(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_control_adj_param ON control_adjustments(param_id, created_at DESC);
"""


class ControlMixin:
    """SQLite persistence for control plane snapshots and adjustment history."""

    async def ensure_control_schema(self) -> None:
        """Create control tables if they don't exist (called on startup)."""
        try:
            for stmt in CONTROL_SCHEMA.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await self.db.execute(stmt)
            await self.db.commit()
        except Exception as exc:
            log.error("ControlMixin.ensure_control_schema failed: %s", exc)

    async def save_control_snapshot(
        self,
        snap_id: int,
        values: Dict[str, float],
        trigger: str = "manual",
        accuracy_at_snap: Optional[float] = None,
    ) -> None:
        """Persist a HelixConfig snapshot to the database."""
        try:
            await self.db.execute(
                """
                INSERT INTO control_snapshots
                    (snap_id, created_at, trigger, accuracy_at_snap, param_values)
                VALUES (?, ?, ?, ?, ?)
                """,
                (snap_id, time.time(), trigger, accuracy_at_snap, json.dumps({k: v for k, v in values.items()})),
            )
            await self.db.commit()
        except Exception as exc:
            log.error("save_control_snapshot failed: %s", exc)

    async def get_latest_control_snapshot(self) -> Optional[Dict[str, Any]]:
        """Return the most recent control snapshot."""
        try:
            async with self.db.execute(
                "SELECT snap_id, created_at, trigger, accuracy_at_snap, param_values "
                "FROM control_snapshots ORDER BY created_at DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                return {
                    "snap_id": row[0],
                    "created_at": row[1],
                    "trigger": row[2],
                    "accuracy_at_snap": row[3],
                    "values": json.loads(row[4] or "{}"),
                }
        except Exception as exc:
            log.error("get_latest_control_snapshot failed: %s", exc)
            return None

    async def save_control_adjustment(
        self,
        param_id: str,
        value_before: float,
        value_after: float,
        accuracy_before: Optional[float] = None,
        trigger: str = "pid",
    ) -> None:
        """Record a single parameter adjustment."""
        try:
            await self.db.execute(
                """
                INSERT INTO control_adjustments
                    (created_at, param_id, value_before, value_after, accuracy_before, trigger)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (time.time(), param_id, value_before, value_after, accuracy_before, trigger),
            )
            await self.db.commit()
        except Exception as exc:
            log.error("save_control_adjustment failed: %s", exc)

    async def get_adjustment_history(
        self,
        param_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return recent parameter adjustments, optionally filtered by param."""
        try:
            if param_id:
                query = (
                    "SELECT created_at, param_id, value_before, value_after, "
                    "accuracy_before, trigger FROM control_adjustments "
                    "WHERE param_id = ? ORDER BY created_at DESC LIMIT ?"
                )
                params = (param_id, limit)
            else:
                query = (
                    "SELECT created_at, param_id, value_before, value_after, "
                    "accuracy_before, trigger FROM control_adjustments "
                    "ORDER BY created_at DESC LIMIT ?"
                )
                params = (limit,)
            rows = []
            async with self.db.execute(query, params) as cursor:
                async for row in cursor:
                    rows.append({
                        "created_at": row[0],
                        "param_id": row[1],
                        "value_before": row[2],
                        "value_after": row[3],
                        "accuracy_before": row[4],
                        "trigger": row[5],
                    })
            return rows
        except Exception as exc:
            log.error("get_adjustment_history failed: %s", exc)
            return []
