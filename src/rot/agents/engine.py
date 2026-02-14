"""Agent execution engine — evaluates signals against active agents and executes paper trades."""

from __future__ import annotations

import logging
import math
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from rot.agents.types import AgentRule, AgentPerformance
from rot.agents.rules import RuleEngine

log = logging.getLogger(__name__)


class AgentEngine:
    """Background engine that evaluates signals against active agents and executes paper trades."""

    def __init__(self, db):
        self.db = db
        self._rule_engine = RuleEngine()

    async def evaluate_signal(self, signal_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Evaluate a signal against all active agents. Returns list of trades executed."""
        executed_trades: List[Dict[str, Any]] = []

        # Build a flat signal dict for rule matching
        signal = self._flatten_signal(signal_data)

        # Only trade directional signals
        if not RuleEngine.check_stance_tradeable(signal):
            return executed_trades

        # Get all active agents
        agents = await self.db.get_active_agents()
        if not agents:
            return executed_trades

        for agent in agents:
            try:
                trade = await self._evaluate_agent(agent, signal)
                if trade:
                    executed_trades.append(trade)
            except Exception as e:
                log.error("Agent %s evaluation error: %s", agent.get("id", "?"), e)

        return executed_trades

    async def _evaluate_agent(
        self, agent: Dict[str, Any], signal: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Evaluate a single agent against a signal. Returns trade dict if executed."""
        agent_id = agent["id"]

        # 1. Check confidence gate
        min_conf = agent.get("min_confidence", 0.4)
        if not RuleEngine.check_confidence_gate(signal, min_conf):
            return None

        # 2. Parse and evaluate rules
        import json
        rules_raw = agent.get("rules_json", "[]")
        if isinstance(rules_raw, str):
            rules_raw = json.loads(rules_raw)
        rules = [AgentRule.from_dict(r) for r in rules_raw]

        agent_type = agent.get("agent_type", "signal_follower")

        # For custom_rule agents, use OR logic from config; others use AND
        config = agent.get("config_json", {})
        if isinstance(config, str):
            config = json.loads(config)
        logic = config.get("rule_logic", "and")

        if agent_type == "custom_rule":
            matched = RuleEngine.evaluate_custom(rules, signal, logic)
        else:
            matched = RuleEngine.evaluate_all(rules, signal)

        if not matched:
            return None

        # 3. Check safety rails
        safe, reason = await self.check_safety_rails(agent)
        if not safe:
            log.info("Agent %s safety rail triggered: %s", agent_id, reason)
            return None

        # 4. Check dedup (don't trade same signal twice)
        signal_id = signal.get("id", "")
        if signal_id:
            existing = await self.db.get_agent_trade_by_signal(agent_id, signal_id)
            if existing:
                return None

        # 5. Apply agent-type logic (e.g., contrarian flips stance)
        effective_signal = RuleEngine.apply_agent_type_logic(agent_type, signal)

        # 6. Execute paper trade
        trade = await self.execute_trade(agent, effective_signal)
        return trade

    async def execute_trade(
        self, agent: Dict[str, Any], signal: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Execute a paper trade for an agent."""
        agent_id = agent["id"]
        user_id = agent["user_id"]
        ticker = signal.get("ticker", "UNKNOWN")
        stance = signal.get("stance", "unknown")
        signal_id = signal.get("id", "")

        # Determine position size from agent config
        max_dollars = agent.get("max_position_dollars", 2000.0)

        # Get entry price from signal market data
        price = self._get_price_from_signal(signal)
        if not price or price <= 0:
            return None

        # Calculate quantity (dollars / price)
        quantity = max_dollars / price

        # Create agent trade record
        trade_id = str(uuid.uuid4())
        now = time.time()

        trade_data = {
            "id": trade_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "signal_id": signal_id,
            "ticker": ticker,
            "stance": stance,
            "entry_price": price,
            "quantity": round(quantity, 4),
            "dollars": round(max_dollars, 2),
            "created_at": now,
            "status": "open",
        }

        await self.db.create_agent_trade(trade_data)

        log.info(
            "Agent %s executed trade: %s %s @ $%.2f ($%.0f)",
            agent_id[:8], stance, ticker, price, max_dollars,
        )

        return trade_data

    async def check_safety_rails(
        self, agent: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """Check if agent should be allowed to trade. Returns (is_safe, reason)."""
        agent_id = agent["id"]

        # 1. Daily trade cap
        max_daily = agent.get("max_daily_trades", 5)
        today_count = await self.db.get_agent_daily_trade_count(agent_id)
        if today_count >= max_daily:
            return False, f"daily trade limit reached ({today_count}/{max_daily})"

        # 2. Max portfolio exposure
        max_exposure_pct = agent.get("max_portfolio_exposure_pct", 50.0)
        user_id = agent["user_id"]
        portfolio = await self.db.get_paper_portfolio(user_id)
        if portfolio:
            balance = portfolio.get("balance", 10000)
            open_trades = await self.db.get_agent_trades(agent_id, status="open")
            open_dollars = sum(t.get("dollars", 0) for t in open_trades)
            exposure_pct = (open_dollars / balance * 100) if balance > 0 else 100
            if exposure_pct >= max_exposure_pct:
                return False, f"exposure limit reached ({exposure_pct:.1f}%/{max_exposure_pct}%)"

        # 3. Stop loss check (daily P&L)
        stop_loss_pct = agent.get("stop_loss_pct", 10.0)
        daily_pnl = await self.db.get_agent_daily_pnl(agent_id)
        if portfolio:
            balance = portfolio.get("balance", 10000)
            if balance > 0 and daily_pnl < 0:
                loss_pct = abs(daily_pnl) / balance * 100
                if loss_pct >= stop_loss_pct:
                    # Auto-pause the agent
                    await self.db.update_agent_status(agent_id, "paused")
                    return False, f"stop loss triggered ({loss_pct:.1f}%/{stop_loss_pct}%)"

        return True, ""

    async def get_agent_performance(self, agent_id: str) -> AgentPerformance:
        """Compute aggregate performance metrics for an agent."""
        stats = await self.db.get_agent_performance_stats(agent_id)
        total = stats.get("total_trades", 0)
        wins = stats.get("winning_trades", 0)
        pnl = stats.get("total_pnl", 0.0)

        # Compute win rate
        win_rate = wins / total if total > 0 else 0.0
        avg_pnl = pnl / total if total > 0 else 0.0

        # Compute simple Sharpe approximation from trade returns
        returns = stats.get("returns", [])
        sharpe = self._compute_sharpe(returns)
        max_dd = self._compute_max_drawdown(returns)

        today_count = await self.db.get_agent_daily_trade_count(agent_id)

        return AgentPerformance(
            agent_id=agent_id,
            total_trades=total,
            winning_trades=wins,
            total_pnl=pnl,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd,
            avg_trade_pnl=avg_pnl,
            win_rate=win_rate,
            trades_today=today_count,
        )

    def _flatten_signal(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten a pipeline signal_data dict into a flat dict for rule matching."""
        flat: Dict[str, Any] = {}

        # Direct fields
        event = signal_data.get("event")
        if hasattr(event, "entities"):
            flat["ticker"] = event.entities[0] if event.entities else "UNKNOWN"
            flat["event_type"] = event.event_type
            flat["stance"] = event.stance
            flat["confidence"] = event.confidence
            flat["time_horizon"] = event.time_horizon
            flat["sector"] = event.meta.get("sector", "")
        elif isinstance(event, dict):
            flat["ticker"] = (event.get("entities") or ["UNKNOWN"])[0]
            flat["event_type"] = event.get("event_type", "other")
            flat["stance"] = event.get("stance", "unknown")
            flat["confidence"] = event.get("confidence", 0)
            flat["time_horizon"] = event.get("time_horizon", "unknown")
            flat["sector"] = event.get("meta", {}).get("sector", "")

        trade = signal_data.get("trade_idea")
        if hasattr(trade, "strategy"):
            flat["strategy"] = trade.strategy
            flat["quality_score"] = trade.quality_score
        elif isinstance(trade, dict):
            flat["strategy"] = trade.get("strategy", "none")
            flat["quality_score"] = trade.get("quality_score", 0)

        # Signal ID
        flat["id"] = signal_data.get("id", signal_data.get("signal_id", ""))

        # Subreddit from evidence
        if hasattr(event, "evidence") and event.evidence:
            flat["subreddit"] = event.evidence[0].subreddit
        elif isinstance(event, dict):
            evidence = event.get("evidence", [])
            if evidence:
                flat["subreddit"] = evidence[0].get("subreddit", "") if isinstance(evidence[0], dict) else ""

        # Market data
        md = signal_data.get("market_data", {})
        if isinstance(md, dict):
            flat["price"] = md.get("last_close", 0)
            flat["market_cap"] = md.get("market_cap", 0)

        return flat

    def _get_price_from_signal(self, signal: Dict[str, Any]) -> float:
        """Extract price from a flattened signal dict."""
        price = signal.get("price", 0)
        try:
            return float(price) if price else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _compute_sharpe(returns: List[float], risk_free: float = 0.0) -> float:
        """Compute annualized Sharpe ratio from a list of per-trade returns."""
        if len(returns) < 2:
            return 0.0
        mean_r = sum(returns) / len(returns) - risk_free
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1))
        if std_r == 0:
            return 0.0
        # Annualize assuming ~252 trading days, ~2 trades/day
        return (mean_r / std_r) * math.sqrt(252)

    @staticmethod
    def _compute_max_drawdown(returns: List[float]) -> float:
        """Compute max drawdown percentage from cumulative returns."""
        if not returns:
            return 0.0
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in returns:
            cumulative += r
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        return max_dd
