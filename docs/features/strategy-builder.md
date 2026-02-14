<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Strategy Builder & ML Optimizer

**Module**: `src/rot/strategy/` (9 files)
**Tier**: Pro+ (gated by `gate_strategy_access()`)

## Modules

| File | Purpose |
|------|---------|
| `types.py` | StrategyRule, Strategy, StrategyResult, DiscoveryResult, MarketRegime, RegimeStrategy, MarketplaceEntry |
| `rules.py` | RuleEngine: 7 operators (gt/lt/gte/lte/eq/neq/in), nested field access, compiled rules |
| `discovery.py` | StrategyDiscoverer: exhaustive/random search, backtest each candidate, walk-forward validate |
| `ml_optimizer.py` | MLStrategyOptimizer: 52-feature vector, GradientBoosting, feature importance → auto-generate rules |
| `regime.py` | RegimeDetector: market regime classification (bull/bear/sideways/volatile/crisis), per-strategy regime matrix |
| `genetic.py` | GeneticOptimizer: population → fitness → selection → crossover → mutation → evolve |
| `auto_trader.py` | AutoPaperTrader: evaluate signals vs active strategies, auto paper trade, health monitoring |
| `marketplace.py` | Marketplace: publish, subscribe, rate strategies, performance tracking |

## Rule Engine

Rules are `StrategyRule` dataclasses with field path, operator, value. Nested field access (e.g., `meta.nlp.conviction`) resolved at compile time. Operators: gt, lt, gte, lte, eq, neq, in.

## Strategy Sources

manual, discovered, ml_optimized, genetic, marketplace

## Market Regimes

RegimeDetector classifies: bull, bear, sideways, volatile, crisis. Each strategy has a regime performance matrix. Auto-adjust/deactivate based on regime changes.

## Genetic Algorithm

Population of rule sets → fitness (backtest Sharpe) → tournament selection → crossover (combine parents) → mutation (random rule changes) → new generation. `GENETIC_GENERATIONS=50`, `GENETIC_POPULATION_SIZE=100`.

## DB Tables

- `strategies` — id, user_id, name, description, rules_json, config_json, performance_json, health_score, is_active, source, created_at, updated_at
- `strategy_trades` — id, strategy_id, signal_id, ticker, stance, entry_price, exit_price, pnl_pct, created_at, resolved_at
- `strategy_portfolios` — strategy_id, user_id, balance, total_trades, winning_trades, total_pnl
- `strategy_marketplace` — id, strategy_id, author_id, name, description, performance_json, subscriber_count, rating, created_at
- `market_regimes` — id, regime_type, start_ts, end_ts, indicators_json, confidence, detected_at
- `strategy_discoveries` — id, user_id, search_config_json, result_json, strategies_found, elapsed_s, created_at

## Routes

- `GET /strategies` — Builder dashboard
- `GET /strategies/{id}` — Strategy detail
- `GET /marketplace` — Strategy marketplace
- `GET /strategies/regimes` — Market regime dashboard
- `POST /api/v1/strategies/create` — Create manual strategy
- `POST /api/v1/strategies/{id}/activate` — Activate/deactivate
- `DELETE /api/v1/strategies/{id}` — Delete strategy
- `POST /api/v1/strategies/discover` — Run discovery
- `POST /api/v1/strategies/ml-optimize` — Run ML optimization
- `POST /api/v1/strategies/evolve` — Run genetic evolution
- `GET /api/v1/strategies/regimes` — Regimes JSON
- `GET /api/v1/marketplace` — Marketplace listings JSON
- `POST /api/v1/marketplace/publish` — Publish strategy

## Tier Gating

Pro: 3 manual strategies. Premium: discovery + ML optimize + regimes, max 10. Ultra/Enterprise: genetic + marketplace + unlimited (999).

## Background Loops

- `_strategy_health_loop()` every 6h — evaluate health scores, deactivate underperformers
- `_regime_detection_loop()` every 1h — classify current market regime, update matrix

## Config (`ROT_STRATEGY_*`)

DISCOVERY_MAX_RULES=5, DISCOVERY_MAX_CANDIDATES=1000, ML_MIN_SIGNALS=200, GENETIC_GENERATIONS=50, GENETIC_POPULATION_SIZE=100, AUTO_TRADE_ENABLED=True, MARKETPLACE_ENABLED=True, REGIME_WINDOW_DAYS=30, HEALTH_CHECK_INTERVAL_S=21600, REGIME_DETECTION_INTERVAL_S=3600
