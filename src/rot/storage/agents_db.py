"""
Trading agents + agent trades mixin.

Assumes self.db (aiosqlite Connection) exists.

This mixin handles all autonomous trading agent operations:
- Agent CRUD (create, get, update, delete)
- Agent query methods (by user, active agents)
- Agent trade recording and tracking
- Performance computation
- Exposure and deduplication checks
"""

import json
import time
import uuid
from typing import Any, Dict, List, Optional


class AgentsMixin:
    """Trading agents + agent trades. Assumes self.db (aiosqlite Connection) exists."""

    # ── Agent CRUD ──

    async def create_agent(
        self,
        user_id: str,
        name: str,
        agent_type: str,
        min_confidence: float = 0.4,
        max_daily_trades: int = 5,
        max_position_dollars: float = 2000.0,
        max_portfolio_exposure_pct: float = 50.0,
        stop_loss_pct: float = 10.0,
        rules_json: str = "[]",
        config_json: str = "{}",
    ) -> str:
        """Create a new trading agent. Returns agent ID."""
        agent_id = str(uuid.uuid4())
        now = time.time()
        await self.db.execute(
            """INSERT INTO trading_agents
               (id, user_id, name, agent_type, status, rules_json, config_json,
                min_confidence, max_daily_trades, max_position_dollars,
                max_portfolio_exposure_pct, stop_loss_pct, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, user_id, name, agent_type, rules_json, config_json,
             min_confidence, max_daily_trades, max_position_dollars,
             max_portfolio_exposure_pct, stop_loss_pct, now, now),
        )
        await self.db.commit()
        return agent_id

    async def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get a single trading agent by ID."""
        async with self.db.execute(
            "SELECT * FROM trading_agents WHERE id = ?", (agent_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_agents_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all trading agents for a user."""
        async with self.db.execute(
            "SELECT * FROM trading_agents WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_active_agents(self) -> List[Dict[str, Any]]:
        """Get all active trading agents (across all users)."""
        async with self.db.execute(
            "SELECT * FROM trading_agents WHERE status = 'active'"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def update_agent(
        self, agent_id: str, **kwargs
    ) -> bool:
        """Update agent fields. Only updates provided kwargs."""
        if not kwargs:
            return False
        # Validate column names to prevent SQL injection
        allowed_columns = {
            "user_id", "name", "agent_type", "status", "rules_json", "config_json",
            "min_confidence", "max_daily_trades", "max_position_dollars",
            "max_portfolio_exposure_pct", "stop_loss_pct", "updated_at"
        }
        if not all(k in allowed_columns for k in kwargs):
            invalid = set(kwargs.keys()) - allowed_columns
            raise ValueError(f"Invalid column names for update: {invalid}")
        kwargs["updated_at"] = time.time()
        set_clauses = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [agent_id]
        cursor = await self.db.execute(
            f"UPDATE trading_agents SET {set_clauses} WHERE id = ?",
            values,
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def update_agent_status(self, agent_id: str, status: str) -> bool:
        """Update agent status (active/paused/stopped)."""
        return await self.update_agent(agent_id, status=status)

    async def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent and its trades."""
        await self.db.execute(
            "DELETE FROM agent_trades WHERE agent_id = ?", (agent_id,)
        )
        cursor = await self.db.execute(
            "DELETE FROM trading_agents WHERE id = ?", (agent_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def count_user_agents(self, user_id: str) -> int:
        """Count agents for a user."""
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM trading_agents WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row["cnt"] if row else 0

    # ── Agent Trades ──

    async def insert_agent_trade(
        self,
        agent_id: str,
        user_id: str,
        signal_id: Optional[str],
        ticker: str,
        stance: str,
        entry_price: float,
        quantity: float,
        dollars: float,
        paper_trade_id: Optional[str] = None,
    ) -> str:
        """Record a trade executed by an agent."""
        trade_id = str(uuid.uuid4())
        now = time.time()
        await self.db.execute(
            """INSERT INTO agent_trades
               (id, agent_id, user_id, signal_id, ticker, stance, entry_price,
                quantity, dollars, created_at, status, paper_trade_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (trade_id, agent_id, user_id, signal_id, ticker, stance,
             entry_price, quantity, dollars, now, paper_trade_id),
        )
        await self.db.commit()
        return trade_id

    async def close_agent_trade(
        self, trade_id: str, exit_price: float, pnl_dollars: float, pnl_pct: float,
    ) -> bool:
        """Close an open agent trade with exit price and P&L."""
        now = time.time()
        cursor = await self.db.execute(
            """UPDATE agent_trades
               SET status = 'closed', closed_at = ?, exit_price = ?,
                   pnl_dollars = ?, pnl_pct = ?
               WHERE id = ? AND status = 'open'""",
            (now, exit_price, pnl_dollars, pnl_pct, trade_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_agent_trades(
        self, agent_id: str, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get trades for an agent."""
        async with self.db.execute(
            """SELECT * FROM agent_trades
               WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?""",
            (agent_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_agent_trades_today(self, agent_id: str) -> int:
        """Count trades executed by this agent today."""
        today_start = time.time() - 86400
        async with self.db.execute(
            """SELECT COUNT(*) as cnt FROM agent_trades
               WHERE agent_id = ? AND created_at > ?""",
            (agent_id, today_start),
        ) as cursor:
            row = await cursor.fetchone()
            return row["cnt"] if row else 0

    async def get_open_agent_trades(self, agent_id: str) -> List[Dict[str, Any]]:
        """Get all open trades for an agent."""
        async with self.db.execute(
            "SELECT * FROM agent_trades WHERE agent_id = ? AND status = 'open'",
            (agent_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ── Agent Performance & Analytics ──

    async def get_agent_performance(self, agent_id: str) -> Dict[str, Any]:
        """Compute performance metrics for an agent."""
        async with self.db.execute(
            """SELECT
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as winning_trades,
                   SUM(COALESCE(pnl_dollars, 0)) as total_pnl,
                   AVG(COALESCE(pnl_dollars, 0)) as avg_trade_pnl
               FROM agent_trades WHERE agent_id = ?""",
            (agent_id,),
        ) as cursor:
            row = await cursor.fetchone()
            d = dict(row) if row else {}

        total = d.get("total_trades", 0) or 0
        wins = d.get("winning_trades", 0) or 0
        trades_today = await self.get_agent_trades_today(agent_id)

        return {
            "total_trades": total,
            "winning_trades": wins,
            "win_rate": wins / total if total > 0 else 0.0,
            "total_pnl": d.get("total_pnl", 0) or 0.0,
            "avg_trade_pnl": d.get("avg_trade_pnl", 0) or 0.0,
            "trades_today": trades_today,
        }

    async def get_agent_total_exposure(self, agent_id: str) -> float:
        """Get total dollar exposure for open trades of an agent."""
        async with self.db.execute(
            """SELECT SUM(dollars) as total_exposure
               FROM agent_trades WHERE agent_id = ? AND status = 'open'""",
            (agent_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return (row["total_exposure"] or 0.0) if row else 0.0

    async def check_agent_signal_dedup(self, agent_id: str, signal_id: str) -> bool:
        """Check if this agent already traded this signal."""
        async with self.db.execute(
            "SELECT 1 FROM agent_trades WHERE agent_id = ? AND signal_id = ?",
            (agent_id, signal_id),
        ) as cursor:
            return await cursor.fetchone() is not None
