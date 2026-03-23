"""Q-learning agent for option strategy selection."""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class State:
    iv_rank: float
    days_to_expiry: int
    market_regime: str
    portfolio_delta: float

    def discretize(self) -> tuple:
        """Return a hashable tuple representing the discretized state."""
        iv_bucket = int(self.iv_rank * 10)  # 0..10
        dte_bucket = self.days_to_expiry // 10  # 0,1,2,...
        delta_bucket = int((self.portfolio_delta + 1.0) * 5)  # 0..10
        return (iv_bucket, dte_bucket, self.market_regime, delta_bucket)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

class Action(str, Enum):
    BUY_CALL = "BUY_CALL"
    BUY_PUT = "BUY_PUT"
    SELL_CALL = "SELL_CALL"
    SELL_PUT = "SELL_PUT"
    SELL_IRON_CONDOR = "SELL_IRON_CONDOR"
    DO_NOTHING = "DO_NOTHING"


ALL_ACTIONS: List[str] = [a.value for a in Action]


# ---------------------------------------------------------------------------
# Reward
# ---------------------------------------------------------------------------

def compute_reward(pnl: float, delta_exposure: float) -> float:
    """PnL minus a penalty proportional to absolute delta exposure."""
    return pnl - 0.1 * abs(delta_exposure)


# ---------------------------------------------------------------------------
# Q-Learning Trader
# ---------------------------------------------------------------------------

class QLearningTrader:
    """Epsilon-greedy Q-learning agent for option strategy selection."""

    def __init__(
        self,
        alpha: float = 0.1,
        gamma: float = 0.95,
        epsilon: float = 0.3,
        epsilon_decay: float = 0.995,
        min_epsilon: float = 0.05,
    ) -> None:
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.min_epsilon = min_epsilon
        # q_table[state][action] -> Q-value
        self.q_table: Dict[tuple, Dict[str, float]] = defaultdict(
            lambda: {a: 0.0 for a in ALL_ACTIONS}
        )

    def discretize_state(
        self,
        iv_rank: float,
        dte: int,
        regime: str,
        delta: float,
    ) -> tuple:
        state = State(iv_rank=iv_rank, days_to_expiry=dte, market_regime=regime, portfolio_delta=delta)
        return state.discretize()

    def choose_action(self, state: tuple) -> str:
        """Epsilon-greedy action selection."""
        if random.random() < self.epsilon:
            return random.choice(ALL_ACTIONS)
        q_values = self.q_table[state]
        return max(q_values, key=q_values.__getitem__)

    def update(
        self,
        state: tuple,
        action: str,
        reward: float,
        next_state: tuple,
        done: bool,
    ) -> None:
        """Standard Q-update rule."""
        current_q = self.q_table[state][action]
        if done:
            target = reward
        else:
            best_next_q = max(self.q_table[next_state].values())
            target = reward + self.gamma * best_next_q
        self.q_table[state][action] = current_q + self.alpha * (target - current_q)

    def decay_epsilon(self) -> None:
        """Multiply epsilon by decay factor, clamp to min_epsilon."""
        self.epsilon = max(self.min_epsilon, self.epsilon * self.epsilon_decay)

    def train_episode(self, env_data: List[dict]) -> float:
        """
        Train on one episode of environment data.

        Each item in `env_data` should be a dict with keys:
            iv_rank, dte, regime, delta, pnl, next_iv_rank, next_dte,
            next_regime, next_delta, done
        Returns the total reward accumulated in this episode.
        """
        total_reward = 0.0
        for step in env_data:
            state = self.discretize_state(
                step["iv_rank"], step["dte"], step["regime"], step["delta"]
            )
            action = self.choose_action(state)
            reward = compute_reward(step.get("pnl", 0.0), step.get("delta", 0.0))
            next_state = self.discretize_state(
                step.get("next_iv_rank", step["iv_rank"]),
                step.get("next_dte", step["dte"]),
                step.get("next_regime", step["regime"]),
                step.get("next_delta", step["delta"]),
            )
            done = step.get("done", False)
            self.update(state, action, reward, next_state, done)
            total_reward += reward
        self.decay_epsilon()
        return total_reward

    def get_policy(self) -> Dict[tuple, str]:
        """Return best action for each known state."""
        return {
            state: max(actions, key=actions.__getitem__)
            for state, actions in self.q_table.items()
        }

    def save(self, path: str) -> None:
        """Serialize q_table to JSON."""
        serializable = {
            str(state): actions for state, actions in self.q_table.items()
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)

    def load(self, path: str) -> None:
        """Deserialize q_table from JSON."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.q_table = defaultdict(lambda: {a: 0.0 for a in ALL_ACTIONS})
        for key, actions in data.items():
            # Convert string key back to tuple
            state = tuple(eval(key))  # noqa: S307
            self.q_table[state] = actions


# ---------------------------------------------------------------------------
# Unit tests (inline, run with pytest)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import unittest

    class TestQLearningTrader(unittest.TestCase):
        def test_action_coverage(self):
            """With epsilon=1.0, all actions should eventually be selected."""
            trader = QLearningTrader(epsilon=1.0)
            state = trader.discretize_state(0.5, 30, "neutral", 0.0)
            seen = set()
            for _ in range(500):
                seen.add(trader.choose_action(state))
            self.assertEqual(seen, set(ALL_ACTIONS))

        def test_q_update_changes_value(self):
            trader = QLearningTrader(alpha=0.5, epsilon=0.0)
            state = (5, 3, "bull", 5)
            action = Action.BUY_CALL.value
            # Initial Q-value should be 0
            self.assertAlmostEqual(trader.q_table[state][action], 0.0)
            trader.update(state, action, reward=1.0, next_state=state, done=True)
            # After update Q should increase
            self.assertGreater(trader.q_table[state][action], 0.0)

        def test_reward_penalizes_delta(self):
            r1 = compute_reward(pnl=100.0, delta_exposure=0.0)
            r2 = compute_reward(pnl=100.0, delta_exposure=10.0)
            self.assertGreater(r1, r2)

    unittest.main(argv=[""], exit=False, verbosity=2)
