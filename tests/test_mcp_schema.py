"""Tests for the mcp_events database schema.

Verifies the mcp_events table is created by the main schema, has the
correct columns and indexes, and supports basic CRUD operations used
by the SqliteEventStore.
"""
from __future__ import annotations

import time

import aiosqlite
import pytest

from rot.storage.schema import SCHEMA_SQL


@pytest.fixture
async def db(tmp_path):
    """Create a fresh database with the full ROT schema applied."""
    db_path = str(tmp_path / "test_schema.db")
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA_SQL)
    await conn.commit()
    yield conn
    await conn.close()


# ═══════════════════════════════════════════════════════════════════════
# Table Existence
# ═══════════════════════════════════════════════════════════════════════


class TestMcpEventsTableExists:
    """Verify the mcp_events table is created by SCHEMA_SQL."""

    @pytest.mark.asyncio
    async def test_table_exists(self, db):
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mcp_events'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["name"] == "mcp_events"

    @pytest.mark.asyncio
    async def test_table_has_expected_columns(self, db):
        cursor = await db.execute("PRAGMA table_info(mcp_events)")
        columns = {row["name"] for row in await cursor.fetchall()}
        expected = {"id", "event_id", "stream_id", "message_json", "created_at"}
        assert expected == columns

    @pytest.mark.asyncio
    async def test_id_is_autoincrement_primary_key(self, db):
        cursor = await db.execute("PRAGMA table_info(mcp_events)")
        rows = await cursor.fetchall()
        id_col = next(r for r in rows if r["name"] == "id")
        assert id_col["pk"] == 1
        assert id_col["type"] == "INTEGER"

    @pytest.mark.asyncio
    async def test_event_id_is_unique(self, db):
        """event_id column has a UNIQUE constraint."""
        now = time.time()
        await db.execute(
            "INSERT INTO mcp_events (event_id, stream_id, created_at) VALUES (?, ?, ?)",
            ("evt-1", "s1", now),
        )
        await db.commit()
        with pytest.raises(Exception):  # IntegrityError
            await db.execute(
                "INSERT INTO mcp_events (event_id, stream_id, created_at) VALUES (?, ?, ?)",
                ("evt-1", "s2", now),
            )

    @pytest.mark.asyncio
    async def test_message_json_is_nullable(self, db):
        """message_json allows NULL (for priming events)."""
        now = time.time()
        await db.execute(
            "INSERT INTO mcp_events (event_id, stream_id, message_json, created_at) "
            "VALUES (?, ?, NULL, ?)",
            ("evt-null", "s1", now),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT message_json FROM mcp_events WHERE event_id = ?", ("evt-null",)
        )
        row = await cursor.fetchone()
        assert row["message_json"] is None


# ═══════════════════════════════════════════════════════════════════════
# Indexes
# ═══════════════════════════════════════════════════════════════════════


class TestMcpEventsIndexes:
    """Verify indexes are created for efficient queries."""

    @pytest.mark.asyncio
    async def test_stream_id_index_exists(self, db):
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_mcp_events_stream'"
        )
        row = await cursor.fetchone()
        assert row is not None

    @pytest.mark.asyncio
    async def test_event_id_index_exists(self, db):
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_mcp_events_event_id'"
        )
        row = await cursor.fetchone()
        assert row is not None

    @pytest.mark.asyncio
    async def test_created_at_index_exists(self, db):
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_mcp_events_created'"
        )
        row = await cursor.fetchone()
        assert row is not None


# ═══════════════════════════════════════════════════════════════════════
# CRUD Operations
# ═══════════════════════════════════════════════════════════════════════


class TestMcpEventsCrud:
    """Basic CRUD operations matching SqliteEventStore usage patterns."""

    @pytest.mark.asyncio
    async def test_insert_and_select_by_event_id(self, db):
        now = time.time()
        await db.execute(
            "INSERT INTO mcp_events (event_id, stream_id, message_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("evt-abc", "stream-1", '{"jsonrpc":"2.0"}', now),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT id, stream_id, message_json FROM mcp_events WHERE event_id = ?",
            ("evt-abc",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["stream_id"] == "stream-1"
        assert row["message_json"] == '{"jsonrpc":"2.0"}'

    @pytest.mark.asyncio
    async def test_select_by_stream_id_ordered(self, db):
        """Events for a stream are returned in insertion order (by id)."""
        now = time.time()
        for i in range(5):
            await db.execute(
                "INSERT INTO mcp_events (event_id, stream_id, message_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (f"evt-{i}", "stream-1", f'{{"id":{i}}}', now + i),
            )
        await db.commit()

        cursor = await db.execute(
            "SELECT event_id FROM mcp_events WHERE stream_id = ? ORDER BY id",
            ("stream-1",),
        )
        rows = await cursor.fetchall()
        assert [r["event_id"] for r in rows] == [f"evt-{i}" for i in range(5)]

    @pytest.mark.asyncio
    async def test_delete_by_created_at(self, db):
        """Old events can be deleted by created_at (cleanup pattern)."""
        old_time = time.time() - 7200
        new_time = time.time()

        await db.execute(
            "INSERT INTO mcp_events (event_id, stream_id, created_at) VALUES (?, ?, ?)",
            ("old-evt", "s1", old_time),
        )
        await db.execute(
            "INSERT INTO mcp_events (event_id, stream_id, created_at) VALUES (?, ?, ?)",
            ("new-evt", "s1", new_time),
        )
        await db.commit()

        cutoff = time.time() - 3600
        cursor = await db.execute(
            "DELETE FROM mcp_events WHERE created_at < ?", (cutoff,)
        )
        assert cursor.rowcount == 1
        await db.commit()

        cursor = await db.execute("SELECT event_id FROM mcp_events")
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["event_id"] == "new-evt"

    @pytest.mark.asyncio
    async def test_replay_query_pattern(self, db):
        """Verify the exact query pattern used by SqliteEventStore.replay_events_after."""
        now = time.time()
        for i in range(5):
            await db.execute(
                "INSERT INTO mcp_events (event_id, stream_id, message_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (f"evt-{i}", "s1", f'{{"seq":{i}}}', now + i),
            )
        await db.commit()

        # Find anchor (evt-1)
        cursor = await db.execute(
            "SELECT id, stream_id FROM mcp_events WHERE event_id = ?",
            ("evt-1",),
        )
        anchor = await cursor.fetchone()
        assert anchor is not None

        # Replay events after anchor
        cursor = await db.execute(
            "SELECT event_id, message_json FROM mcp_events "
            "WHERE stream_id = ? AND id > ? ORDER BY id",
            (anchor["stream_id"], anchor["id"]),
        )
        rows = await cursor.fetchall()
        assert len(rows) == 3  # evt-2, evt-3, evt-4
        assert [r["event_id"] for r in rows] == ["evt-2", "evt-3", "evt-4"]

    @pytest.mark.asyncio
    async def test_cross_stream_isolation_in_replay(self, db):
        """Replay query only returns events from the same stream."""
        now = time.time()
        await db.execute(
            "INSERT INTO mcp_events (event_id, stream_id, created_at) VALUES (?, ?, ?)",
            ("a1", "stream-a", now),
        )
        await db.execute(
            "INSERT INTO mcp_events (event_id, stream_id, created_at) VALUES (?, ?, ?)",
            ("b1", "stream-b", now + 1),
        )
        await db.execute(
            "INSERT INTO mcp_events (event_id, stream_id, created_at) VALUES (?, ?, ?)",
            ("a2", "stream-a", now + 2),
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT id, stream_id FROM mcp_events WHERE event_id = ?", ("a1",)
        )
        anchor = await cursor.fetchone()

        cursor = await db.execute(
            "SELECT event_id FROM mcp_events WHERE stream_id = ? AND id > ? ORDER BY id",
            (anchor["stream_id"], anchor["id"]),
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["event_id"] == "a2"
