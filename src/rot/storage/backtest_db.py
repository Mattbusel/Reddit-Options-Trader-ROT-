"""
Backtesting database mixin.

Provides database methods for backtest runs, saved strategies, and backtest signal queries.
"""

import time
import uuid
from typing import Dict, List, Optional, Any


class BacktestMixin:
    """
    Database methods for backtesting features.

    Tables:
    - backtest_runs: Saved backtest results with config, metrics, monte carlo, risk
    - backtest_strategies: Named/saved strategy configurations
    """

    async def get_backtest_signals(
        self,
        days: int = 90,
        ticker: Optional[str] = None,
        stance: Optional[str] = None,
        strategy: Optional[str] = None,
        event_type: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        """Get signals for backtesting with performance data joined.

        Args:
            days: Lookback period in days
            ticker: Filter by ticker
            stance: Filter by stance
            strategy: Filter by strategy
            event_type: Filter by event type
            min_confidence: Minimum confidence threshold
            limit: Maximum number of signals

        Returns:
            List of signal dicts with performance data
        """
        cutoff = time.time() - (days * 86400)

        query = """
            SELECT s.*, sp.price_at_signal, sp.price_1h, sp.price_4h, sp.price_1d,
                   sp.max_gain_pct, sp.max_loss_pct
            FROM signals s
            JOIN signal_performance sp ON sp.signal_id = s.id
            WHERE s.created_at > ? AND sp.price_at_signal > 0
        """
        params = [cutoff]

        if ticker:
            query += " AND s.ticker = ?"
            params.append(ticker.upper())
        if stance:
            query += " AND s.stance = ?"
            params.append(stance)
        if strategy:
            query += " AND s.strategy = ?"
            params.append(strategy)
        if event_type:
            query += " AND s.event_type = ?"
            params.append(event_type)
        if min_confidence > 0:
            query += " AND s.confidence >= ?"
            params.append(min_confidence)

        query += " ORDER BY s.created_at ASC LIMIT ?"
        params.append(limit)

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def save_backtest_run(
        self,
        user_id: str,
        name: str,
        config_json: str,
        result_json: str,
        monte_carlo_json: str = "{}",
        risk_json: str = "{}",
    ) -> str:
        """Save a backtest run with results.

        Args:
            user_id: User who ran the backtest
            name: Backtest run name
            config_json: JSON config
            result_json: JSON results
            monte_carlo_json: Monte Carlo results (optional)
            risk_json: Risk metrics (optional)

        Returns:
            Backtest run ID
        """
        run_id = str(uuid.uuid4())
        now = time.time()

        await self.db.execute(
            """INSERT INTO backtest_runs
               (id, user_id, name, config_json, result_json,
                monte_carlo_json, risk_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, user_id, name, config_json, result_json,
             monte_carlo_json, risk_json, now),
        )
        await self.db.commit()
        return run_id

    async def get_user_backtests(
        self, user_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get saved backtest runs for a user (summary only).

        Args:
            user_id: User ID
            limit: Max number of runs to return

        Returns:
            List of backtest run summaries
        """
        async with self.db.execute(
            """SELECT id, name, config_json, created_at
               FROM backtest_runs
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_backtest_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get a single backtest run with full data.

        Args:
            run_id: Backtest run ID

        Returns:
            Backtest run dict with all fields or None
        """
        async with self.db.execute(
            "SELECT * FROM backtest_runs WHERE id = ?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def delete_backtest_run(self, run_id: str, user_id: str) -> bool:
        """Delete a backtest run.

        Args:
            run_id: Backtest run ID
            user_id: User ID (for authorization)

        Returns:
            True if deleted, False if not found
        """
        cursor = await self.db.execute(
            "DELETE FROM backtest_runs WHERE id = ? AND user_id = ?",
            (run_id, user_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def save_backtest_strategy(
        self,
        user_id: str,
        name: str,
        description: str,
        config_json: str,
    ) -> str:
        """Save a named backtest strategy.

        Args:
            user_id: User ID
            name: Strategy name
            description: Strategy description
            config_json: JSON configuration

        Returns:
            Strategy ID
        """
        strat_id = str(uuid.uuid4())
        now = time.time()

        await self.db.execute(
            """INSERT INTO backtest_strategies
               (id, user_id, name, description, config_json,
                last_run_at, created_at, is_active)
               VALUES (?, ?, ?, ?, ?, 0, ?, 1)""",
            (strat_id, user_id, name, description, config_json, now),
        )
        await self.db.commit()
        return strat_id

    async def get_user_backtest_strategies(
        self, user_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get saved backtest strategies for a user.

        Args:
            user_id: User ID
            limit: Max number to return

        Returns:
            List of strategy dicts
        """
        async with self.db.execute(
            """SELECT id, name, description, config_json, last_run_at, created_at, is_active
               FROM backtest_strategies
               WHERE user_id = ? AND is_active = 1
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_backtest_strategy(self, strategy_id: str, user_id: str) -> bool:
        """Soft-delete a strategy (set is_active=0).

        Args:
            strategy_id: Strategy ID
            user_id: User ID (for authorization)

        Returns:
            True if updated, False if not found
        """
        cursor = await self.db.execute(
            "UPDATE backtest_strategies SET is_active = 0 WHERE id = ? AND user_id = ?",
            (strategy_id, user_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0
