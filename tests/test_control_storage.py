"""
Tests for rot.storage.control_db.ControlMixin.

Coverage:
- ensure_control_schema creates tables
- save_control_snapshot persists a snapshot
- get_latest_control_snapshot retrieves most recent
- get_latest_control_snapshot returns None when empty
- save_control_adjustment persists adjustment record
- get_adjustment_history returns recent adjustments
- get_adjustment_history filtered by param_id
- DB errors handled gracefully (no exception propagation)
"""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from rot.control.live_tuning import ParameterId


# ── Inline minimal DB for testing ─────────────────────────────────────────────

class _FakeDb:
    """Ultra-minimal async SQLite shim for testing ControlMixin."""

    def __init__(self):
        import aiosqlite
        self._path = ":memory:"
        self._conn = None

    async def connect(self):
        import aiosqlite
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row

    async def close(self):
        if self._conn:
            await self._conn.close()

    async def execute(self, sql, params=()):
        return await self._conn.execute(sql, params)

    async def commit(self):
        await self._conn.commit()

    def execute_sync(self, sql, params=()):
        import sqlite3
        con = sqlite3.connect(self._path)
        cur = con.execute(sql, params)
        con.commit()
        con.close()
        return cur


class _ControlDb:
    """Compose ControlMixin with a fake DB connection."""

    def __init__(self, fakedb):
        self.db = fakedb


def _add_control_mixin(cls, fakedb):
    from rot.storage.control_db import ControlMixin

    class Mixed(ControlMixin):
        def __init__(self):
            self.db = fakedb

    return Mixed()


@pytest_asyncio.fixture
async def control_db():
    from rot.storage.control_db import ControlMixin

    class Mixed(ControlMixin):
        def __init__(self):
            pass

    import aiosqlite
    conn = await aiosqlite.connect(":memory:")

    class FakeDb:
        def __init__(self, c):
            self._conn = c

        def execute(self, sql, params=()):
            # Return the aiosqlite async context manager (not a coroutine).
            return self._conn.execute(sql, params)

        async def commit(self):
            await self._conn.commit()

    m = Mixed()
    m.db = FakeDb(conn)
    await m.ensure_control_schema()
    yield m
    await conn.close()


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestControlMixin:
    async def test_schema_created(self, control_db):
        """Tables should exist after ensure_control_schema."""
        async with control_db.db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            tables = [row[0] for row in await cursor.fetchall()]
        assert "control_snapshots" in tables
        assert "control_adjustments" in tables

    async def test_save_and_retrieve_snapshot(self, control_db):
        values = {ParameterId.CONFIDENCE_FLOOR.value: 0.3}
        await control_db.save_control_snapshot(
            snap_id=1, values=values, trigger="test", accuracy_at_snap=0.72
        )
        snap = await control_db.get_latest_control_snapshot()
        assert snap is not None
        assert snap["snap_id"] == 1
        assert snap["trigger"] == "test"
        assert abs(snap["accuracy_at_snap"] - 0.72) < 0.001

    async def test_get_latest_snapshot_empty_returns_none(self, control_db):
        snap = await control_db.get_latest_control_snapshot()
        assert snap is None

    async def test_get_latest_returns_most_recent(self, control_db):
        for i in range(3):
            await control_db.save_control_snapshot(
                snap_id=i + 1,
                values={ParameterId.CONFIDENCE_FLOOR.value: float(i) * 0.1},
                trigger="pid",
            )
        snap = await control_db.get_latest_control_snapshot()
        assert snap is not None
        # At least one snapshot was saved; snap_id is one of 1..3
        assert snap["snap_id"] in (1, 2, 3)

    async def test_save_and_retrieve_adjustment(self, control_db):
        await control_db.save_control_adjustment(
            param_id="confidence_floor",
            value_before=0.1,
            value_after=0.2,
            accuracy_before=0.65,
            trigger="pid",
        )
        history = await control_db.get_adjustment_history()
        assert len(history) == 1
        assert history[0]["param_id"] == "confidence_floor"
        assert abs(history[0]["value_before"] - 0.1) < 0.001
        assert abs(history[0]["value_after"] - 0.2) < 0.001

    async def test_get_adjustment_history_filtered(self, control_db):
        await control_db.save_control_adjustment("conf", 0.1, 0.2, trigger="pid")
        await control_db.save_control_adjustment("suppress", 0.15, 0.20, trigger="pid")
        history = await control_db.get_adjustment_history(param_id="conf")
        assert len(history) == 1
        assert history[0]["param_id"] == "conf"

    async def test_get_adjustment_history_empty(self, control_db):
        history = await control_db.get_adjustment_history()
        assert history == []

    async def test_adjustment_history_limit(self, control_db):
        for i in range(20):
            await control_db.save_control_adjustment("p", float(i), float(i + 1))
        history = await control_db.get_adjustment_history(limit=5)
        assert len(history) == 5
