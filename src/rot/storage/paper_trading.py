"""
Paper trading portfolios & trades mixin.

Assumes self.db (aiosqlite Connection) exists.
"""
import time
import uuid
from typing import Any, Dict, List, Optional


class PaperTradingMixin:
    """Paper trading portfolios & trades. Assumes self.db (aiosqlite Connection) exists."""

    async def init_paper_portfolio(self, user_id: str) -> None:
        """Initialize a paper portfolio for a user."""
        await self.db.execute(
            "INSERT OR IGNORE INTO paper_portfolios (user_id) VALUES (?)",
            (user_id,),
        )
        await self.db.commit()

    async def get_paper_portfolio(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get paper portfolio for a user."""
        async with self.db.execute(
            "SELECT * FROM paper_portfolios WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def create_paper_trade(
        self, user_id: str, signal_id: str, ticker: str, stance: str,
        entry_price: float, quantity: float, dollars: float,
    ) -> Dict[str, Any]:
        """Create a paper trade and deduct from balance."""
        trade_id = str(uuid.uuid4())[:12]
        now = time.time()

        # Deduct from balance
        portfolio = await self.get_paper_portfolio(user_id)
        new_balance = portfolio["balance"] - dollars

        await self.db.execute("""
            INSERT INTO paper_trades
            (id, user_id, signal_id, ticker, stance, entry_price, quantity, paper_balance_after, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
        """, (trade_id, user_id, signal_id, ticker, stance, entry_price, quantity, new_balance, now))

        await self.db.execute(
            "UPDATE paper_portfolios SET balance = ?, last_trade_at = ? WHERE user_id = ?",
            (new_balance, now, user_id),
        )
        await self.db.commit()

        return {
            "id": trade_id, "ticker": ticker, "stance": stance,
            "entry_price": entry_price, "quantity": quantity,
            "balance_after": new_balance,
        }

    async def get_paper_trade(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Get a single paper trade."""
        async with self.db.execute(
            "SELECT * FROM paper_trades WHERE id = ?", (trade_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def close_paper_trade(self, trade_id: str, exit_price: float) -> Dict[str, Any]:
        """Close a paper trade and update portfolio stats."""
        trade = await self.get_paper_trade(trade_id)
        if not trade:
            return {}

        now = time.time()
        entry = trade["entry_price"]
        qty = trade["quantity"]
        stance = trade["stance"]

        # Calculate P&L (stance-aware: bearish = profit on price drop)
        if stance == "bearish":
            pnl_pct = ((entry - exit_price) / entry) * 100
        else:
            pnl_pct = ((exit_price - entry) / entry) * 100

        cost = entry * qty
        pnl_dollars = cost * (pnl_pct / 100)

        # Update trade
        await self.db.execute("""
            UPDATE paper_trades
            SET closed_at = ?, exit_price = ?, pnl_dollars = ?, pnl_pct = ?, status = 'closed'
            WHERE id = ?
        """, (now, exit_price, pnl_dollars, pnl_pct, trade_id))

        # Update portfolio
        portfolio = await self.get_paper_portfolio(trade["user_id"])
        new_balance = portfolio["balance"] + cost + pnl_dollars
        new_total = portfolio["total_trades"] + 1
        new_winning = portfolio["winning_trades"] + (1 if pnl_dollars > 0 else 0)
        new_pnl = portfolio["total_pnl"] + pnl_dollars

        await self.db.execute("""
            UPDATE paper_portfolios
            SET balance = ?, total_trades = ?, winning_trades = ?, total_pnl = ?
            WHERE user_id = ?
        """, (new_balance, new_total, new_winning, new_pnl, trade["user_id"]))

        await self.db.commit()

        return {
            "id": trade_id, "ticker": trade["ticker"],
            "entry_price": entry, "exit_price": exit_price,
            "pnl_dollars": round(pnl_dollars, 2), "pnl_pct": round(pnl_pct, 2),
            "new_balance": round(new_balance, 2),
        }

    async def get_paper_trades(
        self, user_id: str, status: Optional[str] = None, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get paper trades for a user."""
        if status:
            query = "SELECT * FROM paper_trades WHERE user_id = ? AND status = ? ORDER BY created_at DESC LIMIT ?"
            params = (user_id, status, limit)
        else:
            query = "SELECT * FROM paper_trades WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
            params = (user_id, limit)
        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_paper_trading_leaderboard(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Public leaderboard: top paper traders by total P&L."""
        query = """
            SELECT
                pp.user_id,
                COALESCE(SUBSTR(u.email, 1, INSTR(u.email, '@') - 1), 'anon') as username,
                pp.balance,
                pp.initial_balance,
                pp.total_pnl,
                pp.total_trades,
                pp.winning_trades,
                CASE WHEN pp.total_trades > 0
                     THEN ROUND(pp.winning_trades * 100.0 / pp.total_trades, 1)
                     ELSE 0 END as win_rate,
                ROUND(pp.total_pnl / pp.initial_balance * 100, 1) as return_pct,
                pp.last_trade_at
            FROM paper_portfolios pp
            JOIN users u ON pp.user_id = u.id
            WHERE pp.total_trades >= 3
            ORDER BY pp.total_pnl DESC
            LIMIT ?
        """
        async with self.db.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
