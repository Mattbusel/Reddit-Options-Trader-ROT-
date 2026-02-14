# Autonomous Trading Agents — ROT Feature Reference
> Part of the ROT documentation suite. See [CLAUDE.md](../../CLAUDE.md) for the full index.

## Quick Start for Agents
- Key files: `src/rot/agents/` (to be created: `types.py`, `engine.py`, `rules.py`, `safety.py`, `__init__.py`), `src/rot/web/routes/agents.py` (to be created), `src/rot/web/templates/agents.html` (to be created)
- DB tables: `trading_agents`, `agent_trades` (to be created)
- Routes: `GET /agents`, `POST /api/v1/agents/create`, `GET /api/v1/agents/{agent_id}`, `PUT /api/v1/agents/{agent_id}`, `DELETE /api/v1/agents/{agent_id}`, `POST /api/v1/agents/{agent_id}/start`, `POST /api/v1/agents/{agent_id}/stop`, `GET /api/v1/agents/{agent_id}/trades`
- Config: `ROT_AGENTS_ENABLED`, `ROT_AGENTS_MAX_PER_USER`, `ROT_AGENTS_EVAL_INTERVAL_S`, `ROT_AGENTS_MAX_DAILY_TRADES`, `ROT_AGENTS_MAX_POSITION_PCT`
- Tier gate: `gate_agents_access()` -- Ultra+ only

---

## Overview

Autonomous Trading Agents are user-configured bots that automatically evaluate incoming signals and execute paper trades based on predefined rules. Each agent has a type, a rule set, safety rails, and an independent paper trading balance drawn from the user's paper portfolio. Agents operate on paper trades only -- no real money execution.

## Agent Types

| Type | Strategy | Description |
|------|----------|-------------|
| `signal_follower` | Follow high-confidence signals | Trades in the direction of the signal stance when confidence exceeds threshold |
| `contrarian` | Fade low-confidence signals | Takes the opposite stance when confidence is below a threshold (fade the crowd) |
| `momentum_rider` | Follow trending tickers | Trades tickers with sustained signal momentum (multiple signals in same direction) |
| `custom_rule` | User-defined rules | Fully configurable rule set using the rules engine |

## Rules Engine (`rules.py`)

The rules engine evaluates incoming signals against an agent's rule set. Rules are composed of conditions and actions:

### Conditions

| Condition | Parameters | Description |
|-----------|-----------|-------------|
| `min_confidence` | threshold (0.0-1.0) | Signal confidence must exceed threshold |
| `max_confidence` | threshold (0.0-1.0) | Signal confidence must be below threshold |
| `stance_filter` | stances (list) | Signal stance must be in the list |
| `event_type_filter` | types (list) | Event type must be in the list |
| `ticker_filter` | tickers (list) | Ticker must be in the list (or empty for all) |
| `subreddit_filter` | subreddits (list) | Source subreddit must be in the list |
| `min_quality_score` | threshold (0.0-1.0) | Trade quality score must exceed threshold |
| `min_trend_score` | threshold (float) | Trend score must exceed threshold |
| `not_suppressed` | boolean | Signal must not be suppressed by feedback engine |
| `sector_filter` | sectors (list) | Signal sector must be in the list |
| `momentum_count` | count, window_hours | Requires N signals for same ticker in same direction within window |

### Actions

| Action | Description |
|--------|-------------|
| `execute_trade` | Execute a paper trade in the signal's stance direction |
| `execute_contrarian` | Execute a paper trade opposite to the signal's stance |
| `skip` | Log the evaluation but take no action |

## Safety Rails (`safety.py`)

Every agent is subject to mandatory safety rails that cannot be overridden by user configuration:

| Rail | Default | Description |
|------|---------|-------------|
| Max daily trades | 10 (configurable via `ROT_AGENTS_MAX_DAILY_TRADES`) | Prevents runaway trading |
| Max position size | 20% of balance (configurable via `ROT_AGENTS_MAX_POSITION_PCT`) | Prevents over-concentration |
| Max concurrent positions | 5 | Limits simultaneous open trades |
| Cooldown period | 60 seconds between trades | Prevents rapid-fire execution |
| Loss circuit breaker | Pause after 3 consecutive losses | Prevents drawdown spiraling |
| Daily loss limit | 10% of starting daily balance | Hard stop on daily losses |
| Duplicate prevention | No duplicate ticker+stance within 1 hour | Prevents position stacking |

## Background Signal Evaluation

Agents evaluate signals via a background loop in `server.py`:
- **Trigger**: each time a new signal arrives (via the `on_signal` callback)
- **Process**: for each active agent belonging to any user, evaluate the signal against the agent's rule set
- **Execution**: if rules match and safety rails pass, execute a paper trade via the existing paper trading system
- **Logging**: all evaluations (match or skip) are logged to `agent_trades` with the evaluation result

## DB Schema

### `trading_agents`

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| user_id | TEXT FK->users | Owner |
| name | TEXT | User-given agent name |
| agent_type | TEXT | signal_follower / contrarian / momentum_rider / custom_rule |
| rules_json | TEXT | JSON-encoded rule set |
| status | TEXT | active / paused / stopped |
| created_at | REAL | Unix timestamp |
| last_eval_at | REAL | Last signal evaluation timestamp |
| total_trades | INTEGER | Cumulative trade count |
| winning_trades | INTEGER | Cumulative winning trade count |
| total_pnl | REAL | Cumulative P&L |

### `agent_trades`

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| agent_id | TEXT FK->trading_agents | Owning agent |
| signal_id | TEXT | Evaluated signal |
| ticker | TEXT | Symbol |
| action | TEXT | execute_trade / execute_contrarian / skip |
| stance | TEXT | bullish / bearish |
| entry_price | REAL | Trade entry price |
| exit_price | REAL | Trade exit price (null if open) |
| pnl_dollars | REAL | Profit/loss |
| pnl_pct | REAL | Profit/loss percentage |
| status | TEXT | open / closed / skipped |
| eval_result_json | TEXT | Full evaluation details (which rules matched, safety checks) |
| created_at | REAL | Unix timestamp |

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/agents` | Agent management dashboard |
| POST | `/api/v1/agents/create` | Create a new agent with rules |
| GET | `/api/v1/agents/{agent_id}` | Get agent details and stats |
| PUT | `/api/v1/agents/{agent_id}` | Update agent rules or status |
| DELETE | `/api/v1/agents/{agent_id}` | Delete an agent |
| POST | `/api/v1/agents/{agent_id}/start` | Activate a paused agent |
| POST | `/api/v1/agents/{agent_id}/stop` | Pause an active agent |
| GET | `/api/v1/agents/{agent_id}/trades` | List agent's trade history |

## Tier Gating

Agents are an Ultra+ feature. `gate_agents_access()` returns:

| Tier | Access |
|------|--------|
| Free | No access |
| Pro | No access |
| Premium | No access |
| Ultra | Up to 3 agents, all types |
| Enterprise | Up to 10 agents, all types, priority evaluation |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ROT_AGENTS_ENABLED` | `False` | Enable agent system |
| `ROT_AGENTS_MAX_PER_USER` | `3` | Max agents per user (Ultra), 10 (Enterprise) |
| `ROT_AGENTS_EVAL_INTERVAL_S` | `0` | Not interval-based; agents evaluate on each signal arrival |
| `ROT_AGENTS_MAX_DAILY_TRADES` | `10` | Max trades per agent per day |
| `ROT_AGENTS_MAX_POSITION_PCT` | `20.0` | Max position size as % of balance |

## Implementation Notes

- Agents use the existing paper trading system (`paper_portfolios`, `paper_trades`) for execution. Agent trades are also recorded in `agent_trades` for agent-specific analytics.
- The agent evaluation hook is added to the `on_signal` callback in `server.py`, alongside WebSocket broadcast and alert dispatch.
- Agent rules are stored as JSON in `rules_json` for flexibility. The rules engine validates the JSON structure on agent creation.
- The loss circuit breaker resets daily at midnight UTC.
- The `momentum_rider` type requires a minimum number of directional signals (configurable) before it will trade, making it slower but potentially more reliable.
- The dashboard template (`agents.html`) shows agent status, recent evaluations, trade history, and performance metrics per agent.
