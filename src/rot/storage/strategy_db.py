"""
Strategy builder methods (strategies, marketplace, regimes, discovery).

Assumes self.db (aiosqlite Connection) exists.
"""
import json
import time
from typing import Any, Dict, List, Optional


class StrategyMixin:
    """Mixin providing strategy builder database operations.

    Reads/writes to: strategies, strategy_trades, strategy_portfolios,
                     strategy_marketplace, market_regimes, strategy_discoveries tables.
    Requires self.db to be an open aiosqlite.Connection.
    """

    # ── Strategy CRUD ──

    async def get_strategy(self, strategy_id: str) -> Optional[dict]:
        """Get a strategy by ID."""
        async with self.db.execute(
            "SELECT * FROM strategies WHERE id = ?", (strategy_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return self._strategy_row_to_dict(row)

    async def get_user_strategies(
        self, user_id: str, active_only: bool = False
    ) -> list[dict]:
        """Get all strategies for a user."""
        sql = "SELECT * FROM strategies WHERE user_id = ?"
        params: list = [user_id]
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY updated_at DESC"
        async with self.db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [self._strategy_row_to_dict(r) for r in rows]

    async def delete_strategy(self, strategy_id: str, user_id: str) -> bool:
        """Delete a strategy (must be owned by user). Returns True if deleted."""
        async with self.db.execute(
            "SELECT id FROM strategies WHERE id = ? AND user_id = ?",
            (strategy_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return False
        await self.db.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
        await self.db.execute(
            "DELETE FROM strategy_trades WHERE strategy_id = ?", (strategy_id,)
        )
        await self.db.execute(
            "DELETE FROM strategy_portfolios WHERE strategy_id = ?", (strategy_id,)
        )
        await self.db.commit()
        return True

    async def update_strategy_health(
        self, strategy_id: str, health_score: float, is_active: bool
    ) -> None:
        """Update a strategy's health score and active status."""
        await self.db.execute(
            "UPDATE strategies SET health_score = ?, is_active = ?, updated_at = ? WHERE id = ?",
            (health_score, 1 if is_active else 0, time.time(), strategy_id),
        )
        await self.db.commit()

    async def update_strategy_performance(
        self, strategy_id: str, performance: dict
    ) -> None:
        """Update a strategy's cached performance stats."""
        await self.db.execute(
            "UPDATE strategies SET performance_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(performance), time.time(), strategy_id),
        )
        await self.db.commit()

    # ── Strategy Trades ──

    async def save_strategy_trade(self, trade: dict) -> None:
        """Save a strategy trade."""
        await self.db.execute(
            """INSERT OR REPLACE INTO strategy_trades
               (id, strategy_id, signal_id, ticker, stance, entry_price,
                exit_price, pnl_pct, created_at, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade["id"],
                trade["strategy_id"],
                trade.get("signal_id", ""),
                trade["ticker"],
                trade["stance"],
                trade["entry_price"],
                trade.get("exit_price"),
                trade.get("pnl_pct"),
                trade.get("created_at", time.time()),
                trade.get("resolved_at"),
            ),
        )
        await self.db.commit()

    async def get_strategy_trades(
        self,
        strategy_id: str,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get trades for a strategy. status: 'open' (no exit_price), 'closed', or None (all)."""
        sql = "SELECT * FROM strategy_trades WHERE strategy_id = ?"
        params: list = [strategy_id]
        if status == "open":
            sql += " AND exit_price IS NULL"
        elif status == "closed":
            sql += " AND exit_price IS NOT NULL"
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        async with self.db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def resolve_strategy_trade(
        self, trade_id: str, exit_price: float, pnl_pct: float
    ) -> None:
        """Close a strategy trade with exit price and P&L."""
        await self.db.execute(
            "UPDATE strategy_trades SET exit_price = ?, pnl_pct = ?, resolved_at = ? WHERE id = ?",
            (exit_price, pnl_pct, time.time(), trade_id),
        )
        await self.db.commit()

    # ── Strategy Portfolios ──

    async def get_strategy_portfolio(
        self, strategy_id: str, user_id: str
    ) -> Optional[dict]:
        """Get portfolio for a strategy-user pair."""
        async with self.db.execute(
            "SELECT * FROM strategy_portfolios WHERE strategy_id = ? AND user_id = ?",
            (strategy_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def save_strategy_portfolio(self, portfolio: dict) -> None:
        """Save or update a strategy portfolio."""
        await self.db.execute(
            """INSERT OR REPLACE INTO strategy_portfolios
               (strategy_id, user_id, balance, total_trades, winning_trades, total_pnl)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                portfolio["strategy_id"],
                portfolio["user_id"],
                portfolio.get("balance", 10000.0),
                portfolio.get("total_trades", 0),
                portfolio.get("winning_trades", 0),
                portfolio.get("total_pnl", 0.0),
            ),
        )
        await self.db.commit()

    # ── Marketplace ──

    async def save_marketplace_entry(self, entry: dict) -> None:
        """Save or update a marketplace entry."""
        await self.db.execute(
            """INSERT OR REPLACE INTO strategy_marketplace
               (id, strategy_id, author_id, name, description,
                performance_json, subscriber_count, rating, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry["id"],
                entry["strategy_id"],
                entry["author_id"],
                entry["name"],
                entry.get("description", ""),
                json.dumps(entry.get("performance", {})),
                entry.get("subscriber_count", 0),
                entry.get("rating", 0.0),
                entry.get("created_at", time.time()),
            ),
        )
        await self.db.commit()

    async def get_marketplace_entries(
        self, sort_by: str = "rating", limit: int = 20, offset: int = 0
    ) -> list[dict]:
        """Get marketplace entries sorted by specified metric."""
        order_map = {
            "rating": "rating DESC",
            "subscribers": "subscriber_count DESC",
            "newest": "created_at DESC",
        }
        order = order_map.get(sort_by, "rating DESC")
        sql = f"SELECT * FROM strategy_marketplace ORDER BY {order} LIMIT ? OFFSET ?"  # nosec B608 - SQL uses constants only, values parameterized
        async with self.db.execute(sql, (limit, offset)) as cur:
            rows = await cur.fetchall()
            return [self._marketplace_row_to_dict(r) for r in rows]

    async def get_marketplace_entry(self, entry_id: str) -> Optional[dict]:
        """Get a single marketplace entry."""
        async with self.db.execute(
            "SELECT * FROM strategy_marketplace WHERE id = ?", (entry_id,)
        ) as cur:
            row = await cur.fetchone()
            return self._marketplace_row_to_dict(row) if row else None

    async def delete_marketplace_entry(
        self, entry_id: str, author_id: str
    ) -> bool:
        """Delete marketplace entry (must be author). Returns True if deleted."""
        async with self.db.execute(
            "SELECT id FROM strategy_marketplace WHERE id = ? AND author_id = ?",
            (entry_id, author_id),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return False
        await self.db.execute(
            "DELETE FROM strategy_marketplace WHERE id = ?", (entry_id,)
        )
        await self.db.commit()
        return True

    # ── Market Regimes ──

    async def save_market_regime(self, regime: dict) -> None:
        """Save a detected market regime."""
        await self.db.execute(
            """INSERT OR REPLACE INTO market_regimes
               (id, regime_type, start_ts, end_ts, indicators_json, confidence, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                regime["id"],
                regime["regime_type"],
                regime["start_ts"],
                regime.get("end_ts"),
                json.dumps(regime.get("indicators", {})),
                regime.get("confidence", 0.5),
                regime.get("detected_at", time.time()),
            ),
        )
        await self.db.commit()

    async def get_market_regimes(
        self, days: int = 90, regime_type: Optional[str] = None
    ) -> list[dict]:
        """Get market regimes within the last N days."""
        cutoff = time.time() - (days * 86400)
        sql = "SELECT * FROM market_regimes WHERE start_ts >= ?"
        params: list = [cutoff]
        if regime_type:
            sql += " AND regime_type = ?"
            params.append(regime_type)
        sql += " ORDER BY start_ts DESC"
        async with self.db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["indicators"] = json.loads(d.pop("indicators_json", "{}"))
                result.append(d)
            return result

    # ── Strategy Discovery ──

    async def save_discovery_result(self, discovery: dict) -> None:
        """Save a strategy discovery run result."""
        await self.db.execute(
            """INSERT INTO strategy_discoveries
               (id, user_id, search_config_json, result_json, strategies_found, elapsed_s, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                discovery["id"],
                discovery["user_id"],
                json.dumps(discovery.get("search_config", {})),
                json.dumps(discovery.get("best_strategies", [])),
                discovery.get("strategies_found", 0),
                discovery.get("elapsed_s", 0.0),
                discovery.get("created_at", time.time()),
            ),
        )
        await self.db.commit()

    async def get_discovery_results(
        self, user_id: str, limit: int = 10
    ) -> list[dict]:
        """Get discovery run results for a user."""
        async with self.db.execute(
            "SELECT * FROM strategy_discoveries WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["search_config"] = json.loads(d.pop("search_config_json", "{}"))
                d["best_strategies"] = json.loads(d.pop("result_json", "[]"))
                result.append(d)
            return result

    # ── Data Cleanup ──

    async def purge_old_strategy_data(self, keep_days: int = 90) -> int:
        """Delete old strategy trades and discovery data. Returns total deleted."""
        cutoff = time.time() - (keep_days * 86400)
        total = 0
        # Purge old resolved trades
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM strategy_trades WHERE resolved_at IS NOT NULL AND resolved_at < ?",
            (cutoff,),
        ) as cur:
            row = await cur.fetchone()
            count = row["cnt"] if row else 0
        if count > 0:
            await self.db.execute(
                "DELETE FROM strategy_trades WHERE resolved_at IS NOT NULL AND resolved_at < ?",
                (cutoff,),
            )
            total += count
        # Purge old discovery runs
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM strategy_discoveries WHERE created_at < ?",
            (cutoff,),
        ) as cur:
            row = await cur.fetchone()
            count = row["cnt"] if row else 0
        if count > 0:
            await self.db.execute(
                "DELETE FROM strategy_discoveries WHERE created_at < ?",
                (cutoff,),
            )
            total += count
        if total > 0:
            await self.db.commit()
        return total

    # ── Helper Methods ──

    def _strategy_row_to_dict(self, row) -> dict:
        """Convert a strategy row to dict with JSON parsing."""
        d = dict(row)
        d["rules"] = json.loads(d.pop("rules_json", "[]"))
        d["config"] = json.loads(d.pop("config_json", "{}"))
        d["performance"] = json.loads(d.pop("performance_json", "{}"))
        d["is_active"] = bool(d.get("is_active"))
        return d

    def _marketplace_row_to_dict(self, row) -> dict:
        """Convert a marketplace row to dict with JSON parsing."""
        d = dict(row)
        d["performance"] = json.loads(d.pop("performance_json", "{}"))
        return d
