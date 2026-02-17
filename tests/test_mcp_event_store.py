"""Tests for MCP event stores (InMemoryEventStore and SqliteEventStore).

Covers:
- Event storage and retrieval
- Replay-after semantics (anchor event, subsequent events, cross-stream isolation)
- Pruning by age and count (InMemory)
- Cleanup by age (SQLite)
- Edge cases: unknown event_id, None messages, concurrent streams
- Lifecycle: connect/close, error without connect
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from unittest.mock import AsyncMock

import pytest

from rot.web.mcp_event_store import InMemoryEventStore, SqliteEventStore

# ── Helpers ──────────────────────────────────────────────────────────


def _make_jsonrpc_message(method: str = "test", msg_id: int = 1):
    """Create a minimal JSONRPCMessage for testing."""
    from mcp.types import JSONRPCMessage

    return JSONRPCMessage.model_validate(
        {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": {}}
    )


class _CollectCallback:
    """EventCallback that collects replayed events into a list."""

    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)


# ═══════════════════════════════════════════════════════════════════════
# InMemoryEventStore
# ═══════════════════════════════════════════════════════════════════════


class TestInMemoryEventStoreBasics:
    """Basic store and replay operations."""

    @pytest.mark.asyncio
    async def test_store_returns_unique_event_id(self):
        store = InMemoryEventStore()
        eid1 = await store.store_event("stream-a", _make_jsonrpc_message())
        eid2 = await store.store_event("stream-a", _make_jsonrpc_message())
        assert isinstance(eid1, str)
        assert len(eid1) == 32  # uuid4 hex
        assert eid1 != eid2

    @pytest.mark.asyncio
    async def test_store_none_message(self):
        """None messages (priming events) are stored but not replayed."""
        store = InMemoryEventStore()
        eid = await store.store_event("stream-a", None)
        assert isinstance(eid, str)

    @pytest.mark.asyncio
    async def test_replay_returns_stream_id(self):
        store = InMemoryEventStore()
        eid1 = await store.store_event("stream-x", _make_jsonrpc_message())
        await store.store_event("stream-x", _make_jsonrpc_message())
        cb = _CollectCallback()
        stream_id = await store.replay_events_after(eid1, cb)
        assert stream_id == "stream-x"

    @pytest.mark.asyncio
    async def test_replay_sends_events_after_anchor(self):
        store = InMemoryEventStore()
        eid1 = await store.store_event("s1", _make_jsonrpc_message("m1", 1))
        eid2 = await store.store_event("s1", _make_jsonrpc_message("m2", 2))
        eid3 = await store.store_event("s1", _make_jsonrpc_message("m3", 3))

        cb = _CollectCallback()
        await store.replay_events_after(eid1, cb)
        # Should replay eid2 and eid3, not eid1
        assert len(cb.events) == 2
        assert cb.events[0].event_id == eid2
        assert cb.events[1].event_id == eid3

    @pytest.mark.asyncio
    async def test_replay_skips_none_messages(self):
        """None (priming) events are stored but not sent during replay."""
        store = InMemoryEventStore()
        eid1 = await store.store_event("s1", _make_jsonrpc_message("m1", 1))
        await store.store_event("s1", None)  # priming event
        eid3 = await store.store_event("s1", _make_jsonrpc_message("m3", 3))

        cb = _CollectCallback()
        await store.replay_events_after(eid1, cb)
        # Only the real message (eid3) should be replayed
        assert len(cb.events) == 1
        assert cb.events[0].event_id == eid3

    @pytest.mark.asyncio
    async def test_replay_unknown_event_id_returns_none(self):
        store = InMemoryEventStore()
        await store.store_event("s1", _make_jsonrpc_message())
        cb = _CollectCallback()
        result = await store.replay_events_after("nonexistent-id", cb)
        assert result is None
        assert len(cb.events) == 0

    @pytest.mark.asyncio
    async def test_replay_last_event_sends_nothing(self):
        """Replaying from the last event sends nothing (no events after it)."""
        store = InMemoryEventStore()
        await store.store_event("s1", _make_jsonrpc_message("m1", 1))
        eid2 = await store.store_event("s1", _make_jsonrpc_message("m2", 2))
        cb = _CollectCallback()
        stream_id = await store.replay_events_after(eid2, cb)
        assert stream_id == "s1"
        assert len(cb.events) == 0


class TestInMemoryEventStoreMultiStream:
    """Cross-stream isolation."""

    @pytest.mark.asyncio
    async def test_streams_are_isolated(self):
        store = InMemoryEventStore()
        eid_a = await store.store_event("stream-a", _make_jsonrpc_message("a1", 1))
        await store.store_event("stream-b", _make_jsonrpc_message("b1", 2))
        await store.store_event("stream-a", _make_jsonrpc_message("a2", 3))

        cb = _CollectCallback()
        stream_id = await store.replay_events_after(eid_a, cb)
        assert stream_id == "stream-a"
        # Only stream-a events after anchor
        assert len(cb.events) == 1

    @pytest.mark.asyncio
    async def test_many_streams(self):
        store = InMemoryEventStore()
        eids = {}
        for i in range(10):
            sid = f"stream-{i}"
            eids[sid] = await store.store_event(sid, _make_jsonrpc_message(f"m{i}", i))
            await store.store_event(sid, _make_jsonrpc_message(f"m{i}b", i + 100))

        for sid, anchor in eids.items():
            cb = _CollectCallback()
            result = await store.replay_events_after(anchor, cb)
            assert result == sid
            assert len(cb.events) == 1


class TestInMemoryEventStorePruning:
    """Age-based and count-based pruning."""

    @pytest.mark.asyncio
    async def test_prune_by_count(self):
        store = InMemoryEventStore(max_events_per_stream=3, max_event_age_seconds=9999)
        eids = []
        for i in range(5):
            eid = await store.store_event("s1", _make_jsonrpc_message(f"m{i}", i))
            eids.append(eid)

        # After storing 5 events with max=3, oldest 2 should be pruned
        assert len(store._streams["s1"]) == 3
        # Oldest event_ids should be gone from reverse index
        assert eids[0] not in store._event_to_stream
        assert eids[1] not in store._event_to_stream
        # Newest should remain
        assert eids[4] in store._event_to_stream

    @pytest.mark.asyncio
    async def test_prune_by_age(self):
        store = InMemoryEventStore(max_events_per_stream=999, max_event_age_seconds=0.1)
        eid1 = await store.store_event("s1", _make_jsonrpc_message("old", 1))

        # Wait for the event to age out
        await asyncio.sleep(0.15)

        # Storing a new event triggers pruning
        await store.store_event("s1", _make_jsonrpc_message("new", 2))

        # Old event should be pruned
        assert eid1 not in store._event_to_stream
        assert len(store._streams["s1"]) == 1

    @pytest.mark.asyncio
    async def test_pruning_preserves_other_streams(self):
        store = InMemoryEventStore(max_events_per_stream=2, max_event_age_seconds=9999)
        eid_a = await store.store_event("stream-a", _make_jsonrpc_message("a1", 1))
        await store.store_event("stream-a", _make_jsonrpc_message("a2", 2))
        await store.store_event("stream-a", _make_jsonrpc_message("a3", 3))

        eid_b = await store.store_event("stream-b", _make_jsonrpc_message("b1", 4))

        # stream-a should be pruned to 2, stream-b untouched
        assert len(store._streams["stream-a"]) == 2
        assert len(store._streams["stream-b"]) == 1
        assert eid_a not in store._event_to_stream
        assert eid_b in store._event_to_stream

    @pytest.mark.asyncio
    async def test_empty_stream_after_all_pruned(self):
        store = InMemoryEventStore(max_events_per_stream=999, max_event_age_seconds=0.05)
        await store.store_event("s1", _make_jsonrpc_message("m1", 1))
        await asyncio.sleep(0.1)
        # Trigger prune — new event on same stream
        await store.store_event("s1", _make_jsonrpc_message("m2", 2))
        # Only the newest should survive
        assert len(store._streams["s1"]) == 1


# ═══════════════════════════════════════════════════════════════════════
# SqliteEventStore
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
async def sqlite_store(tmp_path):
    """Create a connected SqliteEventStore in a temp directory."""
    db_path = str(tmp_path / "test_mcp_events.db")
    store = SqliteEventStore(db_path, max_events=1000, max_age_seconds=3600)
    await store.connect()
    yield store
    await store.close()


class TestSqliteEventStoreLifecycle:
    """Connection and lifecycle management."""

    @pytest.mark.asyncio
    async def test_connect_creates_database(self, tmp_path):
        db_path = str(tmp_path / "new_mcp.db")
        assert not os.path.exists(db_path)
        store = SqliteEventStore(db_path)
        await store.connect()
        assert os.path.exists(db_path)
        await store.close()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, tmp_path):
        db_path = str(tmp_path / "close_test.db")
        store = SqliteEventStore(db_path)
        await store.connect()
        await store.close()
        await store.close()  # second close should not raise

    @pytest.mark.asyncio
    async def test_store_without_connect_raises(self):
        store = SqliteEventStore("unused.db")
        with pytest.raises(RuntimeError, match="not connected"):
            await store.store_event("s1", _make_jsonrpc_message())

    @pytest.mark.asyncio
    async def test_replay_without_connect_raises(self):
        store = SqliteEventStore("unused.db")
        cb = _CollectCallback()
        with pytest.raises(RuntimeError, match="not connected"):
            await store.replay_events_after("some-id", cb)

    @pytest.mark.asyncio
    async def test_connect_twice_succeeds(self, tmp_path):
        """Re-connecting to the same DB file is safe (idempotent schema)."""
        db_path = str(tmp_path / "reconnect.db")
        store = SqliteEventStore(db_path)
        await store.connect()
        await store.close()
        await store.connect()
        eid = await store.store_event("s1", _make_jsonrpc_message())
        assert isinstance(eid, str)
        await store.close()


class TestSqliteEventStoreBasics:
    """Basic store and replay operations with SQLite."""

    @pytest.mark.asyncio
    async def test_store_returns_unique_event_id(self, sqlite_store):
        eid1 = await sqlite_store.store_event("s1", _make_jsonrpc_message())
        eid2 = await sqlite_store.store_event("s1", _make_jsonrpc_message())
        assert isinstance(eid1, str)
        assert len(eid1) == 32
        assert eid1 != eid2

    @pytest.mark.asyncio
    async def test_store_none_message(self, sqlite_store):
        eid = await sqlite_store.store_event("s1", None)
        assert isinstance(eid, str)

    @pytest.mark.asyncio
    async def test_store_and_replay_roundtrip(self, sqlite_store):
        eid1 = await sqlite_store.store_event("s1", _make_jsonrpc_message("m1", 1))
        eid2 = await sqlite_store.store_event("s1", _make_jsonrpc_message("m2", 2))
        eid3 = await sqlite_store.store_event("s1", _make_jsonrpc_message("m3", 3))

        cb = _CollectCallback()
        stream_id = await sqlite_store.replay_events_after(eid1, cb)
        assert stream_id == "s1"
        assert len(cb.events) == 2
        assert cb.events[0].event_id == eid2
        assert cb.events[1].event_id == eid3

    @pytest.mark.asyncio
    async def test_replay_skips_none_messages(self, sqlite_store):
        eid1 = await sqlite_store.store_event("s1", _make_jsonrpc_message("m1", 1))
        await sqlite_store.store_event("s1", None)  # priming
        eid3 = await sqlite_store.store_event("s1", _make_jsonrpc_message("m3", 3))

        cb = _CollectCallback()
        await sqlite_store.replay_events_after(eid1, cb)
        assert len(cb.events) == 1
        assert cb.events[0].event_id == eid3

    @pytest.mark.asyncio
    async def test_replay_unknown_event_id_returns_none(self, sqlite_store):
        await sqlite_store.store_event("s1", _make_jsonrpc_message())
        cb = _CollectCallback()
        result = await sqlite_store.replay_events_after("nonexistent", cb)
        assert result is None
        assert len(cb.events) == 0

    @pytest.mark.asyncio
    async def test_replay_last_event_sends_nothing(self, sqlite_store):
        await sqlite_store.store_event("s1", _make_jsonrpc_message("m1", 1))
        eid2 = await sqlite_store.store_event("s1", _make_jsonrpc_message("m2", 2))
        cb = _CollectCallback()
        stream_id = await sqlite_store.replay_events_after(eid2, cb)
        assert stream_id == "s1"
        assert len(cb.events) == 0


class TestSqliteEventStoreMultiStream:
    """Cross-stream isolation in SQLite."""

    @pytest.mark.asyncio
    async def test_streams_are_isolated(self, sqlite_store):
        eid_a = await sqlite_store.store_event("sa", _make_jsonrpc_message("a1", 1))
        await sqlite_store.store_event("sb", _make_jsonrpc_message("b1", 2))
        await sqlite_store.store_event("sa", _make_jsonrpc_message("a2", 3))

        cb = _CollectCallback()
        stream_id = await sqlite_store.replay_events_after(eid_a, cb)
        assert stream_id == "sa"
        assert len(cb.events) == 1

    @pytest.mark.asyncio
    async def test_many_concurrent_streams(self, sqlite_store):
        eids = {}
        for i in range(10):
            sid = f"stream-{i}"
            eids[sid] = await sqlite_store.store_event(
                sid, _make_jsonrpc_message(f"m{i}", i)
            )
            await sqlite_store.store_event(
                sid, _make_jsonrpc_message(f"m{i}b", i + 100)
            )

        for sid, anchor in eids.items():
            cb = _CollectCallback()
            result = await sqlite_store.replay_events_after(anchor, cb)
            assert result == sid
            assert len(cb.events) == 1


class TestSqliteEventStoreCleanup:
    """Age-based cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_events(self, tmp_path):
        db_path = str(tmp_path / "cleanup_test.db")
        store = SqliteEventStore(db_path, max_age_seconds=0.1)
        await store.connect()

        await store.store_event("s1", _make_jsonrpc_message("old", 1))
        await asyncio.sleep(0.15)

        deleted = await store.cleanup()
        assert deleted >= 1

        # Verify the table is now empty
        cursor = await store._db.execute("SELECT COUNT(*) FROM mcp_events")
        row = await cursor.fetchone()
        assert row[0] == 0

        await store.close()

    @pytest.mark.asyncio
    async def test_cleanup_preserves_recent_events(self, tmp_path):
        db_path = str(tmp_path / "cleanup_recent.db")
        store = SqliteEventStore(db_path, max_age_seconds=3600)
        await store.connect()

        await store.store_event("s1", _make_jsonrpc_message("recent", 1))

        deleted = await store.cleanup()
        assert deleted == 0

        cursor = await store._db.execute("SELECT COUNT(*) FROM mcp_events")
        row = await cursor.fetchone()
        assert row[0] == 1

        await store.close()

    @pytest.mark.asyncio
    async def test_cleanup_without_connect_returns_zero(self):
        store = SqliteEventStore("unused.db")
        result = await store.cleanup()
        assert result == 0

    @pytest.mark.asyncio
    async def test_cleanup_mixed_old_and_new(self, tmp_path):
        db_path = str(tmp_path / "cleanup_mixed.db")
        store = SqliteEventStore(db_path, max_age_seconds=0.1)
        await store.connect()

        # Store an old event
        await store.store_event("s1", _make_jsonrpc_message("old", 1))
        await asyncio.sleep(0.15)

        # Store a new event
        await store.store_event("s1", _make_jsonrpc_message("new", 2))

        deleted = await store.cleanup()
        assert deleted == 1

        cursor = await store._db.execute("SELECT COUNT(*) FROM mcp_events")
        row = await cursor.fetchone()
        assert row[0] == 1  # only the new one survives

        await store.close()


class TestSqliteEventStorePersistence:
    """Data survives close + reconnect."""

    @pytest.mark.asyncio
    async def test_data_persists_across_reconnect(self, tmp_path):
        db_path = str(tmp_path / "persist.db")

        # Session 1: store events
        store1 = SqliteEventStore(db_path)
        await store1.connect()
        eid1 = await store1.store_event("s1", _make_jsonrpc_message("m1", 1))
        eid2 = await store1.store_event("s1", _make_jsonrpc_message("m2", 2))
        await store1.close()

        # Session 2: replay events
        store2 = SqliteEventStore(db_path)
        await store2.connect()
        cb = _CollectCallback()
        stream_id = await store2.replay_events_after(eid1, cb)
        assert stream_id == "s1"
        assert len(cb.events) == 1
        assert cb.events[0].event_id == eid2
        await store2.close()

    @pytest.mark.asyncio
    async def test_event_ordering_preserved(self, sqlite_store):
        """Events are replayed in insertion order."""
        eids = []
        for i in range(20):
            eid = await sqlite_store.store_event(
                "s1", _make_jsonrpc_message(f"m{i}", i)
            )
            eids.append(eid)

        cb = _CollectCallback()
        await sqlite_store.replay_events_after(eids[0], cb)
        assert len(cb.events) == 19
        for i, event in enumerate(cb.events):
            assert event.event_id == eids[i + 1]
