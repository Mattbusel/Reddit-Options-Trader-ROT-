"""
Signal Lineage Tracker - full audit trail for every signal from source to trade idea.
Stores the complete provenance chain: raw post -> NLP pipeline -> credibility -> LLM -> trade.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class LineageNodeType(Enum):
    SOURCE = "source"              # Reddit post / RSS item
    NLP_OUTPUT = "nlp_output"      # After NLP pipeline
    CREDIBILITY = "credibility"    # After credibility scoring
    LLM_REASONING = "llm_reasoning"  # After LLM
    TRADE_IDEA = "trade_idea"      # Final trade idea


@dataclass
class LineageNode:
    node_id: str
    signal_id: str               # groups nodes for same signal
    node_type: LineageNodeType
    timestamp: str               # ISO8601
    data: Dict[str, Any]         # stage-specific data
    parent_ids: List[str]        # provenance chain
    metadata: Dict[str, Any] = field(default_factory=dict)


class SignalLineageStore:
    """SQLite-backed lineage store for audit and replay.

    All writes are wrapped in explicit transactions so that partial pipeline
    failures leave no orphan rows.  The store is safe for multi-thread access
    within a single process (``check_same_thread=False`` + ``WAL`` journal).
    """

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS lineage_nodes (
        node_id     TEXT PRIMARY KEY,
        signal_id   TEXT NOT NULL,
        node_type   TEXT NOT NULL,
        timestamp   TEXT NOT NULL,
        data        TEXT NOT NULL,
        parent_ids  TEXT NOT NULL,
        metadata    TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_signal_id   ON lineage_nodes (signal_id);
    CREATE INDEX IF NOT EXISTS idx_node_type   ON lineage_nodes (node_type);
    CREATE INDEX IF NOT EXISTS idx_timestamp   ON lineage_nodes (timestamp);
    CREATE TABLE IF NOT EXISTS trade_signal_map (
        trade_id   TEXT NOT NULL,
        signal_id  TEXT NOT NULL,
        PRIMARY KEY (trade_id, signal_id)
    );
    """

    def __init__(self, db_path: str = "signal_lineage.db") -> None:
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,  # autocommit; we manage transactions manually
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        with conn:
            for stmt in self.CREATE_TABLE_SQL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)

    @staticmethod
    def _node_from_row(row: sqlite3.Row) -> LineageNode:
        return LineageNode(
            node_id=row["node_id"],
            signal_id=row["signal_id"],
            node_type=LineageNodeType(row["node_type"]),
            timestamp=row["timestamp"],
            data=json.loads(row["data"]),
            parent_ids=json.loads(row["parent_ids"]),
            metadata=json.loads(row["metadata"]),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_node(self, node: LineageNode) -> None:
        """Persist a single lineage node.  Idempotent on node_id."""
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO lineage_nodes
                    (node_id, signal_id, node_type, timestamp, data, parent_ids, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.node_id,
                    node.signal_id,
                    node.node_type.value,
                    node.timestamp,
                    json.dumps(node.data),
                    json.dumps(node.parent_ids),
                    json.dumps(node.metadata),
                ),
            )
            # If this is a trade idea node, maintain the reverse-lookup map so
            # callers can resolve a trade_id -> signal_id without a full scan.
            if node.node_type == LineageNodeType.TRADE_IDEA:
                trade_id = node.data.get("trade_id")
                if trade_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO trade_signal_map (trade_id, signal_id) VALUES (?, ?)",
                        (trade_id, node.signal_id),
                    )

    def get_lineage(self, signal_id: str) -> List[LineageNode]:
        """Return all nodes for *signal_id* ordered by timestamp ascending."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM lineage_nodes WHERE signal_id = ? ORDER BY timestamp ASC",
            (signal_id,),
        ).fetchall()
        return [self._node_from_row(r) for r in rows]

    def get_trade_provenance(self, trade_id: str) -> Dict[str, Any]:
        """Return a dict with signal_id and the full ordered lineage for *trade_id*.

        Returns an empty dict when *trade_id* is not known.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT signal_id FROM trade_signal_map WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
        if row is None:
            return {}
        signal_id: str = row["signal_id"]
        nodes = self.get_lineage(signal_id)
        return {
            "trade_id": trade_id,
            "signal_id": signal_id,
            "stages": [asdict(n) | {"node_type": n.node_type.value} for n in nodes],
        }

    def export_lineage_json(self, signal_id: str) -> str:
        """Serialise the full lineage for *signal_id* as a JSON string."""
        nodes = self.get_lineage(signal_id)
        payload = [
            {
                "node_id": n.node_id,
                "signal_id": n.signal_id,
                "node_type": n.node_type.value,
                "timestamp": n.timestamp,
                "data": n.data,
                "parent_ids": n.parent_ids,
                "metadata": n.metadata,
            }
            for n in nodes
        ]
        return json.dumps({"signal_id": signal_id, "lineage": payload}, indent=2)

    def query_by_source(self, source_url: str) -> List[str]:
        """Return all signal_ids whose SOURCE node contains *source_url*."""
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT DISTINCT signal_id
            FROM lineage_nodes
            WHERE node_type = ?
              AND json_extract(data, '$.url') = ?
            """,
            (LineageNodeType.SOURCE.value, source_url),
        ).fetchall()
        return [r["signal_id"] for r in rows]

    def replay_signals(self, since: datetime, until: datetime) -> List[LineageNode]:
        """Return all SOURCE nodes whose timestamps fall within [since, until].

        Callers can use the returned nodes as replay seeds, then call
        ``get_lineage(node.signal_id)`` to reconstruct the full chain.
        """
        since_str = since.isoformat()
        until_str = until.isoformat()
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT * FROM lineage_nodes
            WHERE node_type = ?
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            (LineageNodeType.SOURCE.value, since_str, until_str),
        ).fetchall()
        return [self._node_from_row(r) for r in rows]

    def close(self) -> None:
        """Close the underlying database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class LineageTracker:
    """Middleware wrapper that records lineage at each pipeline stage.

    Each ``track_*`` method creates a :class:`LineageNode`, persists it via the
    :class:`SignalLineageStore`, and returns the new ``node_id`` so the caller
    can thread it through as a parent reference for the next stage.

    Usage example::

        store   = SignalLineageStore("lineage.db")
        tracker = LineageTracker(store)

        signal_id  = str(uuid.uuid4())
        src_id     = tracker.track_source(signal_id, raw_post)
        nlp_id     = tracker.track_nlp(signal_id, nlp_output, src_id)
        cred_id    = tracker.track_credibility(signal_id, 0.82, features, nlp_id)
        llm_id     = tracker.track_llm(signal_id, reasoning_text, cred_id)
        trade_node = tracker.track_trade(signal_id, trade_idea, llm_id)
    """

    def __init__(self, store: SignalLineageStore) -> None:
        self.store = store

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _now() -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    def _record(
        self,
        signal_id: str,
        node_type: LineageNodeType,
        data: Dict[str, Any],
        parent_ids: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        node_id = self._new_id()
        node = LineageNode(
            node_id=node_id,
            signal_id=signal_id,
            node_type=node_type,
            timestamp=self._now(),
            data=data,
            parent_ids=parent_ids,
            metadata=metadata or {},
        )
        self.store.record_node(node)
        return node_id

    # ------------------------------------------------------------------
    # Stage trackers
    # ------------------------------------------------------------------

    def track_source(self, signal_id: str, raw_post: Dict[str, Any]) -> str:
        """Record a raw Reddit/RSS post as the source node.

        Args:
            signal_id: Unique identifier for this signal chain.
            raw_post:  Dict representation of the raw post (Post dataclass, dict, etc.).

        Returns:
            node_id for the newly created SOURCE node.
        """
        # Normalise — accept dataclass instances or plain dicts
        data: Dict[str, Any] = raw_post if isinstance(raw_post, dict) else vars(raw_post)
        return self._record(
            signal_id=signal_id,
            node_type=LineageNodeType.SOURCE,
            data=data,
            parent_ids=[],
            metadata={"ingested_at": self._now()},
        )

    def track_nlp(
        self,
        signal_id: str,
        nlp_output: Dict[str, Any],
        parent_id: str,
    ) -> str:
        """Record the NLP pipeline output node.

        Args:
            signal_id:  Unique identifier for this signal chain.
            nlp_output: Dict with NLP results (entities, sentiment, etc.).
            parent_id:  node_id of the preceding SOURCE node.

        Returns:
            node_id for the newly created NLP_OUTPUT node.
        """
        return self._record(
            signal_id=signal_id,
            node_type=LineageNodeType.NLP_OUTPUT,
            data=nlp_output if isinstance(nlp_output, dict) else vars(nlp_output),
            parent_ids=[parent_id],
        )

    def track_credibility(
        self,
        signal_id: str,
        score: float,
        features: Dict[str, Any],
        parent_id: str,
    ) -> str:
        """Record the credibility scoring node.

        Args:
            signal_id: Unique identifier for this signal chain.
            score:     Final credibility score in [0.0, 1.0].
            features:  Dict of per-factor feature values used to derive the score.
            parent_id: node_id of the preceding NLP_OUTPUT node.

        Returns:
            node_id for the newly created CREDIBILITY node.
        """
        return self._record(
            signal_id=signal_id,
            node_type=LineageNodeType.CREDIBILITY,
            data={"score": score, "features": features},
            parent_ids=[parent_id],
        )

    def track_llm(
        self,
        signal_id: str,
        reasoning: str,
        parent_id: str,
    ) -> str:
        """Record the LLM reasoning node.

        Args:
            signal_id: Unique identifier for this signal chain.
            reasoning: Full LLM reasoning text or structured JSON string.
            parent_id: node_id of the preceding CREDIBILITY node.

        Returns:
            node_id for the newly created LLM_REASONING node.
        """
        return self._record(
            signal_id=signal_id,
            node_type=LineageNodeType.LLM_REASONING,
            data={"reasoning": reasoning},
            parent_ids=[parent_id],
        )

    def track_trade(
        self,
        signal_id: str,
        trade_idea: Dict[str, Any],
        parent_id: str,
    ) -> str:
        """Record the final trade idea node.

        Args:
            signal_id:  Unique identifier for this signal chain.
            trade_idea: Dict representation of the generated TradeIdea.
            parent_id:  node_id of the preceding LLM_REASONING node.

        Returns:
            node_id for the newly created TRADE_IDEA node.
        """
        data = trade_idea if isinstance(trade_idea, dict) else vars(trade_idea)
        return self._record(
            signal_id=signal_id,
            node_type=LineageNodeType.TRADE_IDEA,
            data=data,
            parent_ids=[parent_id],
        )


__all__ = [
    "LineageNodeType",
    "LineageNode",
    "SignalLineageStore",
    "LineageTracker",
]
