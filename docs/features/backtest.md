<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Backtesting Engine

- **Files**: `src/rot/backtest/` (12 modules), `src/rot/web/routes/backtest.py`, 6 templates
- **DB**: `backtest_runs`, `backtest_strategies`
- **Config**: `ROT_BACKTEST_MAX_SIGNALS` (5000), `ROT_BACKTEST_MONTE_CARLO_SIMS` (1000), `ROT_BACKTEST_WALK_FORWARD_FOLDS` (5), `ROT_BACKTEST_OPTIMIZER_MAX_COMBOS` (500)

## Modules
| File | Purpose |
|------|---------|
| `config.py` | `BacktestConfig` frozen dataclass (portfolio, exits, filters, serialization) |
| `result.py` | `TradeRecord`, `EquityPoint`, `DrawdownPeriod`, `BacktestResult` with `to_dict()` |
| `metrics.py` | Sharpe, Sortino, Calmar, drawdown, profit factor, VaR, CVaR, MAE/MFE |
| `engine.py` | `BacktestEngine.run()` -- stance-aware P&L, position sizing, stop/take-profit |
| `monte_carlo.py` | Bootstrap resampling, confidence intervals, probabilities |
| `risk.py` | VaR, CVaR, MAE/MFE, Ulcer Index, skewness, kurtosis, underwater |
| `walk_forward.py` | Chronological IS/OOS folds, stability scoring |
| `optimizer.py` | Grid search, heatmap, Sharpe-based ranking |
| `benchmark.py` | Alpha, beta, correlation, info ratio vs SPY |
| `comparator.py` | Side-by-side metrics, correlation matrix, rankings |
| `report.py` | CSV export, standalone HTML report |

## Engine Flow
1. Filter signals (date, tickers, stances, event types, min confidence)
2. Position sizing: `fixed` / `kelly` / `confidence`
3. Stance-aware P&L (bullish profits on up, bearish on down -- mirrors DB logic)
4. Stop loss / take profit via `max_gain_pct` / `max_loss_pct`
5. Concurrent position limits
6. Equity curve as `EquityPoint` series

## Tier Gating (`gate_backtest_access()`)
| Tier | Features |
|------|----------|
| Free | No access |
| Pro | Basic, 30d, 200 signals |
| Premium | + MC, walk-forward, risk, benchmark, 90d, 1000 signals |
| Ultra/Enterprise | + optimizer, comparison, saved strategies, export, 365d, 5000 signals |

## Routes
`GET /backtest`, `POST /backtest/run`, `GET /backtest/result/{run_id}`, `POST /backtest/monte-carlo/{run_id}`, `POST /backtest/optimize`, `POST /backtest/walk-forward/{run_id}`, `GET /backtest/compare`, `POST /backtest/strategies/save`, `DELETE /backtest/strategies/{id}`, `GET /api/v1/backtest/export/{run_id}`

## Templates
`backtest.html` (config form), `backtest_result.html` (KPIs + equity curve + trades), `backtest_compare.html`, HTMX partials: `backtest_{monte_carlo,optimize,walk_forward}_partial.html`

## Design Notes
- Only bullish/bearish signals count as trades; mixed/unknown are neutral
- Monte Carlo: bootstrap resampling of trade returns
- Walk-forward: chronological splits only (never random), stability scored
- Signals queried via `_UNIFIED_CTE` (includes archived signals)

## Tests
253 tests across 11 files: `test_backtest_{types,metrics,engine,monte_carlo,risk,walk_forward,optimizer,benchmark,comparator,tier_gate,report}.py`
