<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Autonomous Trading Agents

- **Files**: `src/rot/agents/{types,rules,engine,__init__}.py`, `src/rot/web/routes/agents.py`, `src/rot/web/templates/agents.html`
- **DB**: `trading_agents`, `agent_trades`
- **Config**: `ROT_AGENT_ENABLED`, `ROT_AGENT_MAX_AGENTS_PER_USER` (5), `ROT_AGENT_EVAL_INTERVAL_S` (60), `ROT_AGENT_MAX_DAILY_TRADES` (20)
- **Tier**: Ultra+ via `gate_agent_access()`

## Agent Types
| Type | Behavior |
|------|----------|
| `signal_follower` | Trades in signal direction when confidence > threshold |
| `contrarian` | Flips stance (fades the crowd) |
| `momentum_rider` | Trades tickers with sustained directional momentum |
| `custom_rule` | Enterprise-only, fully user-defined rules |

## Rules Engine (`rules.py`)
9 operators: eq, neq, gt, gte, lt, lte, in, not_in, contains. Supports AND/OR/custom boolean logic. AgentRule dataclass with `to_dict()`/`from_dict()`.

## Safety Rails
| Rail | Default |
|------|---------|
| Max daily trades | 10 per agent |
| Max position size | 20% of balance |
| Max concurrent positions | 5 |
| Cooldown | 60s between trades |
| Loss circuit breaker | Pause after 3 consecutive losses |
| Daily loss limit | 10% of starting daily balance |
| Duplicate prevention | No same ticker+stance within 1h |

## Signal Evaluation
Triggered via `on_signal` callback in `server.py`. For each active agent: evaluate rules -> check safety rails -> execute paper trade via existing paper trading system. All evals logged to `agent_trades`.

## DB Schema
**`trading_agents`**: id, user_id, name, agent_type, status (active/paused/stopped), rules_json, config_json, min_confidence, max_daily_trades, max_position_dollars, max_portfolio_exposure_pct, stop_loss_pct, created_at, updated_at

**`agent_trades`**: id, agent_id, user_id, signal_id, ticker, stance, entry_price, quantity, dollars, created_at, closed_at, exit_price, pnl_dollars, pnl_pct, status (open/closed), paper_trade_id

## Routes
| Method | Path | Description |
|--------|------|-------------|
| GET | `/agents` | Dashboard |
| GET | `/agents/{id}` | Agent detail |
| POST | `/api/v1/agents/create` | Create |
| PUT | `/api/v1/agents/{id}` | Update |
| POST | `/api/v1/agents/{id}/pause` | Pause |
| POST | `/api/v1/agents/{id}/resume` | Resume |
| DELETE | `/api/v1/agents/{id}` | Delete |
| GET | `/api/v1/agents/{id}/trades` | Trade history |
| GET | `/api/v1/agents/{id}/performance` | Performance JSON |

## Tier Gating
| Tier | Access |
|------|--------|
| Free/Pro/Premium | No access |
| Ultra | 3 agents, signal_follower/contrarian/momentum_rider |
| Enterprise | 10 agents, + custom_rule, performance export, API |

## Tests
`test_agent_{types,engine,db,tier_gate}.py`
