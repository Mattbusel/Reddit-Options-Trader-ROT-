# Backtesting Engine — ROT Feature Reference
> Part of the ROT documentation suite. See [CLAUDE.md](../../CLAUDE.md) for the full index.

## Quick Start for Agents
- Key files: `src/rot/backtest/` (12 modules), `src/rot/web/routes/backtest.py`, 6 templates
- DB tables: `backtest_runs`, `backtest_strategies`
- Routes: `GET /backtest`, `POST /backtest/run`, `GET /backtest/result/{run_id}`, `POST /backtest/monte-carlo/{run_id}`, `POST /backtest/optimize`, `POST /backtest/walk-forward/{run_id}`, `GET /backtest/compare`, `POST /backtest/strategies/save`, `DELETE /backtest/strategies/{id}`, `GET /api/v1/backtest/export/{run_id}`
- Config: `ROT_BACKTEST_MAX_SIGNALS`, `ROT_BACKTEST_MONTE_CARLO_SIMS`, `ROT_BACKTEST_WALK_FORWARD_FOLDS`, `ROT_BACKTEST_OPTIMIZER_MAX_COMBOS`

---

## Module Layout (12 Files)

| File | Purpose |
|------|---------|
| `__init__.py` | Re-exports BacktestConfig, BacktestEngine, BacktestResult, TradeRecord, EquityPoint, DrawdownPeriod |
| `config.py` | Frozen dataclass `BacktestConfig` with portfolio settings, exit rules, signal filters, serialization |
| `result.py` | Frozen dataclasses: `TradeRecord`, `EquityPoint`, `DrawdownPeriod`, `BacktestResult` with `to_dict()` |
| `metrics.py` | Pure stateless metric functions: Sharpe, Sortino, Calmar, drawdown, profit factor, VaR, CVaR, MAE/MFE |
| `engine.py` | Core `BacktestEngine.run(signals, config) -> BacktestResult`. Stance-aware P&L, position sizing, stop/take-profit |
| `monte_carlo.py` | `MonteCarloResult` + `run_monte_carlo()` -- bootstrap resampling for confidence intervals and probabilities |
| `risk.py` | `RiskMetrics` + `compute_risk_metrics()` -- VaR, CVaR, MAE/MFE, Ulcer Index, skewness, kurtosis, underwater analysis |
| `walk_forward.py` | `WalkForwardResult` + `run_walk_forward()` -- chronological IS/OOS folds with stability scoring |
| `optimizer.py` | `OptimizationResult` + `optimize()` -- grid search over params, heatmap generation, Sharpe-based ranking |
| `benchmark.py` | `BenchmarkComparison` + `compare_to_benchmark()` -- alpha, beta, correlation, information ratio vs SPY |
| `comparator.py` | `ComparisonResult` + `compare_strategies()` -- side-by-side metrics, correlation matrix, rankings |
| `report.py` | `generate_csv_trades()` + `generate_html_report()` -- CSV export and standalone HTML report generation |

## Core Engine

`BacktestEngine.run(signals, config)` performs a full portfolio simulation:

1. **Signal filtering** -- by date range, tickers, stances, event types, min confidence
2. **Position sizing** -- three modes: `fixed` (flat dollar amount), `kelly` (Kelly criterion from confidence), `confidence` (scale position by confidence)
3. **Stance-aware P&L** -- bullish signals profit on price increase, bearish on decrease. Mirrors the live DB win/loss SQL logic exactly
4. **Stop loss / take profit** -- configurable percentage thresholds checked against `max_gain_pct` and `max_loss_pct`
5. **Concurrent position limits** -- caps simultaneous open trades
6. **Equity curve** -- tracks portfolio value over time as `EquityPoint` series

## Metrics

All metric functions in `metrics.py` are pure and stateless. Key metrics:
- **Sharpe ratio** -- risk-adjusted returns (annualized)
- **Sortino ratio** -- downside-only volatility variant
- **Calmar ratio** -- return / max drawdown
- **Max drawdown** -- peak-to-trough percentage loss
- **Profit factor** -- gross profit / gross loss
- **VaR / CVaR** -- Value at Risk and Conditional VaR at configurable percentiles
- **MAE/MFE** -- Maximum Adverse/Favorable Excursion per trade

## Tier Gating

Access is controlled by `gate_backtest_access()` in `src/rot/web/tier_gate.py`:

| Tier | Features |
|------|----------|
| Free | No access |
| Pro | Basic backtest, 30-day lookback, 200 max signals |
| Premium | + Monte Carlo, walk-forward, risk analytics, benchmark comparison, 90-day, 1000 signals |
| Ultra | + Optimizer, strategy comparison, saved strategies, export, 365-day, 5000 signals |
| Enterprise | Same as Ultra |

## Templates (6 Files)

| Template | Purpose |
|----------|---------|
| `backtest.html` | Config form + saved runs list |
| `backtest_result.html` | Results with KPI cards, equity curve chart, trade log table |
| `backtest_compare.html` | Strategy comparison page |
| `backtest_monte_carlo_partial.html` | HTMX partial: Monte Carlo fan chart + probability table |
| `backtest_optimize_partial.html` | HTMX partial: optimizer heatmap + best params |
| `backtest_walk_forward_partial.html` | HTMX partial: walk-forward fold results + stability score |

## DB Tables

**`backtest_runs`**: id, user_id, name, config_json, result_json, monte_carlo_json, risk_json, created_at

**`backtest_strategies`**: id, user_id, name, description, config_json, last_result_json, last_run_at, created_at, is_active

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ROT_BACKTEST_MAX_SIGNALS` | `5000` | Max signals per backtest query |
| `ROT_BACKTEST_MONTE_CARLO_SIMS` | `1000` | Number of Monte Carlo simulations |
| `ROT_BACKTEST_WALK_FORWARD_FOLDS` | `5` | Number of walk-forward folds |
| `ROT_BACKTEST_OPTIMIZER_MAX_COMBOS` | `500` | Max parameter combinations for optimizer |

## Tests

253 tests across 11 test files: `test_backtest_types.py`, `test_backtest_metrics.py`, `test_backtest_engine.py`, `test_backtest_monte_carlo.py`, `test_backtest_risk.py`, `test_backtest_walk_forward.py`, `test_backtest_optimizer.py`, `test_backtest_benchmark.py`, `test_backtest_comparator.py`, `test_backtest_tier_gate.py`, `test_backtest_report.py`.

## Design Notes

- The backtest engine mirrors the live database P&L logic: only bullish and bearish signals count as trades. Mixed and unknown stances are always neutral.
- Monte Carlo uses bootstrap resampling of trade returns to generate fan charts and probability estimates.
- Walk-forward splits data chronologically (never random) into in-sample training and out-of-sample validation folds with a stability score.
- The optimizer performs grid search over configurable parameter ranges and ranks results by Sharpe ratio.
- Signals are queried using the `_UNIFIED_CTE` pattern, seamlessly including archived signals beyond the 14-day live retention window.
