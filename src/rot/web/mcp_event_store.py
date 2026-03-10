"""MCP event stores for session resumability.

Provides EventStore implementations that enable MCP Streamable HTTP
transport to resume sessions after disconnection:

- InMemoryEventStore: Fast, in-process storage (no restart survival)
- SqliteEventStore:   Persistent storage surviving container restarts

The EventStore interface comes from the MCP SDK and requires two methods:
    store_event(stream_id, message) -> event_id
    replay_events_after(last_event_id, callback) -> stream_id | None
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from uuid import uuid4

import aiosqlite
from mcp.server.streamable_http import (
    EventCallback,
    EventMessage,
    EventStore,
)
from mcp.types import JSONRPCMessage

log = logging.getLogger(__name__)

# Type aliases matching the MCP SDK
EventId = str
StreamId = str

# InMemoryEventStore defaults
_MAX_EVENTS_PER_STREAM = 500
_MAX_EVENT_AGE_SECONDS = 3600  # 1 hour

# SqliteEventStore defaults
_SQLITE_MAX_EVENTS = 10_000
_SQLITE_MAX_AGE_SECONDS = 7200  # 2 hours


class InMemoryEventStore(EventStore):
    """In-memory event store for MCP session resumability.

    Stores events in dicts keyed by stream_id.  Each event gets a
    UUID-based event_id.  Events are pruned by count and age to
    prevent unbounded memory growth.

    Does NOT survive process restarts.  Use SqliteEventStore for
    persistence across deploys.
    """

    def __init__(
        self,
        max_events_per_stream: int = _MAX_EVENTS_PER_STREAM,
        max_event_age_seconds: float = _MAX_EVENT_AGE_SECONDS,
    ) -> None:
        self._max_events = max_events_per_stream
        self._max_age = max_event_age_seconds
        # stream_id -> ordered list of (event_id, timestamp, message_json | None)
        self._streams: dict[str, list[tuple[str, float, str | None]]] = defaultdict(list)
        # event_id -> stream_id  (reverse lookup for replay)
        self._event_to_stream: dict[str, str] = {}

    async def store_event(
        self,
        stream_id: str,
        message: JSONRPCMessage | None,
    ) -> str:
        """Store an event and return a unique event_id."""
        event_id = uuid4().hex
        now = time.time()
        message_json = (
            message.model_dump_json(by_alias=True, exclude_none=True)
            if message is not None
            else None
        )

        self._streams[stream_id].append((event_id, now, message_json))
        self._event_to_stream[event_id] = stream_id

        self._prune_stream(stream_id, now)
        return event_id

    async def replay_events_after(
        self,
        last_event_id: str,
        send_callback: EventCallback,
    ) -> str | None:
        """Replay events that occurred after *last_event_id*."""
        stream_id = self._event_to_stream.get(last_event_id)
        if stream_id is None:
            log.warning("Cannot replay: event_id %s not found", last_event_id)
            return None

        events = self._streams.get(stream_id, [])
        found = False
        for event_id, _ts, message_json in events:
            if found and message_json is not None:
                msg = JSONRPCMessage.model_validate_json(message_json)
                await send_callback(EventMessage(message=msg, event_id=event_id))
            if event_id == last_event_id:
                found = True

        return stream_id

    def _prune_stream(self, stream_id: str, now: float) -> None:
        """Remove old or excess events from a single stream."""
        events = self._streams[stream_id]

        # Age-based pruning
        cutoff = now - self._max_age
        pruned = [(eid, ts, m) for eid, ts, m in events if ts > cutoff]

        # Count-based pruning (keep newest)
        if len(pruned) > self._max_events:
            removed = pruned[: len(pruned) - self._max_events]
            pruned = pruned[len(pruned) - self._max_events :]
            for eid, _, _ in removed:
                self._event_to_stream.pop(eid, None)

        # Also clean reverse index for age-pruned entries
        for eid, ts, _ in events:
            if ts <= cutoff:
                self._event_to_stream.pop(eid, None)

        self._streams[stream_id] = pruned


class SqliteEventStore(EventStore):
    """SQLite-backed event store for cross-restart MCP session persistence.

    Events are stored in a dedicated ``mcp_events.db`` database (separate
    from the main ``rot.db``) to avoid WAL contention.  The auto-increment
    ``id`` column provides a total ordering for replay.

    Call ``connect()`` before use and ``close()`` on shutdown.
    """

    def __init__(
        self,
        db_path: str,
        max_events: int = _SQLITE_MAX_EVENTS,
        max_age_seconds: float = _SQLITE_MAX_AGE_SECONDS,
    ) -> None:
        self._db_path = db_path
        self._max_events = max_events
        self._max_age = max_age_seconds
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database and ensure the schema exists."""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA busy_timeout=3000")
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS mcp_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                stream_id TEXT NOT NULL,
                message_json TEXT,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mcp_events_stream
                ON mcp_events(stream_id, id);
            CREATE INDEX IF NOT EXISTS idx_mcp_events_event_id
                ON mcp_events(event_id);
            CREATE INDEX IF NOT EXISTS idx_mcp_events_created
                ON mcp_events(created_at);
            """
        )
        await self._db.commit()
        log.info("SqliteEventStore connected: %s", self._db_path)

    async def store_event(
        self,
        stream_id: str,
        message: JSONRPCMessage | None,
    ) -> str:
        """Persist an event and return its unique event_id."""
        if not self._db:
            raise RuntimeError("SqliteEventStore not connected — call connect() first")

        event_id = uuid4().hex
        now = time.time()
        message_json = (
            message.model_dump_json(by_alias=True, exclude_none=True)
            if message is not None
            else None
        )

        await self._db.execute(
            "INSERT INTO mcp_events (event_id, stream_id, message_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (event_id, stream_id, message_json, now),
        )
        await self._db.commit()
        return event_id

    async def replay_events_after(
        self,
        last_event_id: str,
        send_callback: EventCallback,
    ) -> str | None:
        """Replay events after *last_event_id* from the same stream."""
        if not self._db:
            raise RuntimeError("SqliteEventStore not connected — call connect() first")

        # Find the anchor row
        cursor = await self._db.execute(
            "SELECT id, stream_id FROM mcp_events WHERE event_id = ?",
            (last_event_id,),
        )
        row = await cursor.fetchone()
        if not row:
            log.warning("Cannot replay: event_id %s not in DB", last_event_id)
            return None

        anchor_id = row["id"]
        stream_id = row["stream_id"]

        # Replay subsequent events in insertion order
        cursor = await self._db.execute(
            "SELECT event_id, message_json FROM mcp_events "
            "WHERE stream_id = ? AND id > ? ORDER BY id",
            (stream_id, anchor_id),
        )
        rows = await cursor.fetchall()
        for r in rows:
            if r["message_json"] is not None:
                msg = JSONRPCMessage.model_validate_json(r["message_json"])
                await send_callback(EventMessage(message=msg, event_id=r["event_id"]))

        return stream_id

    async def cleanup(self) -> int:
        """Remove events older than *max_age_seconds*.  Returns deleted count."""
        if not self._db:
            return 0
        cutoff = time.time() - self._max_age
        cursor = await self._db.execute(
            "DELETE FROM mcp_events WHERE created_at < ?", (cutoff,)
        )
        deleted = cursor.rowcount
        if deleted:
            await self._db.commit()
        return deleted

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
