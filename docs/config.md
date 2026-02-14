<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Configuration Reference

> Part of ROT docs. See [CLAUDE.md](../CLAUDE.md) for full index.

**Source:** `src/rot/core/config.py` (Pydantic Settings, 21+ sections)
**Required:** `ROT_REDDIT_CLIENT_ID`, `ROT_REDDIT_CLIENT_SECRET`, `ROT_LLM_API_KEY`

Format: `VAR = default — description`

## Global
- `ROT_STORAGE_ROOT` = `"storage"` — root dir for all file storage
- `ROT_DB_PATH` = `""` — SQLite path (auto-derived from storage_root if empty)

## Reddit (`ROT_REDDIT_*`)
- `CLIENT_ID` = `""` — Reddit API client ID
- `CLIENT_SECRET` = `""` — Reddit API client secret
- `USER_AGENT` = `"rot:v0.1 (by u_rotbot)"`
- `SUBREDDITS` = `["wallstreetbets","stocks","options"]`
- `LISTING` = `"hot"` — hot/new/rising
- `LIMIT_PER_SUB` = `50` — posts per sub per poll
- `INCLUDE_COMMENTS` = `False`
- `TOP_COMMENTS` = `10`
- `POLL_INTERVAL_S` = `20`

## LLM (`ROT_LLM_*`)
- `PROVIDER` = `"openai"` — openai/anthropic/deepseek
- `API_KEY` = `""`
- `MODEL` = `"gpt-4o-mini"`
- `BASE_URL` = `None` — custom API base URL
- `MAX_TOKENS` = `1024`
- `TEMPERATURE` = `0.3`

## Market (`ROT_MARKET_*`)
- `CACHE_TTL_S` = `3600`
- `SYMBOL_CACHE_TTL_S` = `604800` — 7 days
- `MIN_MARKET_CAP` = `1e8` — $100M
- `ENABLE_OPTIONS_CHAIN` = `False` — disabled to save memory/network
- `OPTIONS_CACHE_TTL_S` = `1800` — 30 min

## Trend (`ROT_TREND_*`)
- `WINDOW_S` = `1800` — 30 min sliding window
- `THRESHOLD` = `0.01` — min trend score
- `COMMENT_WEIGHT` = `2.0` — comment velocity weight vs score
- `TOP_N` = `10`

## RSS (`ROT_RSS_*`)
- `ENABLED` = `False`
- `POLL_INTERVAL_S` = `300`
- `MAX_AGE_S` = `3600`
- `SYNTHETIC_TREND_SCORE` = `0.5`
- `MAX_ENTRIES_PER_FEED` = `50`

## StockTwits (`ROT_STOCKTWITS_*`)
- `ENABLED` = `False`
- `SYMBOLS` = `["TSLA","AAPL","NVDA","SPY","QQQ","AMD","AMZN","MSFT"]`
- `TRENDING_ENABLED` = `True`

## Twitter Ingest (`ROT_TWITTER_INGEST_*`)
- `ENABLED` = `False`
- `BEARER_TOKEN` = `""` — API v2 bearer token
- `CASHTAGS` = `["TSLA","AAPL","NVDA","SPY","QQQ"]`
- `ACCOUNTS` = `["unusual_whales","zerohedge","DeItaone"]`

## Twitter Poster (`ROT_TWITTER_*`)
- `API_KEY` / `API_SECRET` = `""` — consumer credentials
- `ACCESS_TOKEN` / `ACCESS_SECRET` = `""` — user credentials
- `ENABLED` = `False`
- `INTERVAL_S` = `10800` — min seconds between posts
- `MIN_CONFIDENCE` = `0.5`

## Email (`ROT_EMAIL_*`)
- `RESEND_API_KEY` = `""` — Resend HTTP API (recommended)
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` = `""` — SMTP fallback
- `FROM_ADDRESS` = `"ROT Alerts <alerts@rot.app>"`

## Auth (`ROT_AUTH_*`)
- `JWT_SECRET` = `""` — falls back to web.secret_key
- `JWT_ALGORITHM` = `"HS256"`
- `JWT_EXPIRE_MINUTES` = `1440` — 24h
- `ADMIN_EMAILS` = `[]` — JSON list of emails auto-elevated to admin tier

## Stripe (`ROT_STRIPE_*`)
- `SECRET_KEY` = `""`
- `WEBHOOK_SECRET` = `""`
- `PRO_PRICE_ID` / `PREMIUM_PRICE_ID` / `ULTRA_PRICE_ID` / `ENTERPRISE_PRICE_ID` = `""` — Stripe price IDs per tier

## Tier Limits (`ROT_TIER_*`)
- `FREE_SIGNAL_DELAY_S` = `900` — 15 min delay
- `FREE_PAGE_LIMIT` = `10`
- `FREE_API_LIMIT_DAY` = `0` — blocked
- `PRO_API_LIMIT_DAY` = `1000`
- `PREMIUM_API_LIMIT_DAY` = `5000`
- `ULTRA_API_LIMIT_DAY` = `25000`
- `ENTERPRISE_API_LIMIT_DAY` = `100000`

## Web (`ROT_WEB_*`)
- `HOST` = `"0.0.0.0"`
- `PORT` = `8000`
- `SECRET_KEY` = `"change-me-in-production"` — session/JWT fallback

## ML Credibility (`ROT_ML_*`)
- `ENABLED` = `True` — falls back to heuristic when no model
- `MODEL_PATH` = `""` — auto-derived from storage_root if empty
- `MIN_TRAINING_SAMPLES` = `100` — min resolved signals to train
- `RETRAIN_INTERVAL_S` = `86400` — 24h
- `MIN_CLASS_SAMPLES` = `30` — min per class (win/loss)

## Feedback (`ROT_FEEDBACK_*`)
- `ENABLED` = `True` — background analysis loop
- `ANALYSIS_INTERVAL_S` = `21600` — 6h
- `SUPPRESS_ENABLED` = `True` — Stage 6.5 adaptive suppression
- `SUPPRESS_THRESHOLD` = `0.20` — suppress categories below 20% win rate
- `SUPPRESS_SOURCE_THRESHOLD` = `0.15` — suppress (event_type, source) below 15%
- `MIN_SIGNALS_FOR_SUPPRESSION` = `30`
- `QUALITY_TREND_WINDOW_DAYS` = `30`

## Backtest (`ROT_BACKTEST_*`)
- `MAX_SIGNALS` = `5000`
- `MONTE_CARLO_SIMS` = `1000`
- `WALK_FORWARD_FOLDS` = `5`
- `OPTIMIZER_MAX_COMBOS` = `500`

## Unusual Activity (`ROT_UNUSUAL_*`)
- `SCAN_INTERVAL_S` = `300` — 5 min
- `IV_RANK_THRESHOLD` = `80.0` — flag if > 80th percentile
- `VOLUME_SURGE_MULTIPLIER` = `2.0` — flag if > 2x 20-day avg
- `OI_SURGE_PCT` = `20.0` — flag if OI increases > 20%
- `SKEW_STD_THRESHOLD` = `2.0` — flag if P/C ratio > 2 std devs
- `COMPOSITE_MIN_SCORE` = `40.0` — min score (0-100) to store
- `HISTORY_WINDOW_DAYS` = `20` — rolling baseline window
- `PURGE_KEEP_DAYS` = `90`

## Sector Rotation (`ROT_SECTOR_*`)
- `MIN_SIGNALS` = `2` — min signals per sector
- `MOMENTUM_WINDOW_DAYS` = `30`

## Export (`ROT_EXPORT_*`)
- `SCHEDULER_INTERVAL_S` = `3600` — 1h
- `MAX_ROWS_PER_EXPORT` = `1000000`

## Archive (`ROT_ARCHIVE_*`)
- `KEEP_DAYS` = `365` — archived signal retention

## Macro Events (`ROT_MACRO_*`)
- `ENABLED` = `True`
- `CALENDAR_POLL_INTERVAL_S` = `3600` — 1h
- `EARNINGS_POLL_INTERVAL_S` = `14400` — 4h
- `INSIDER_POLL_INTERVAL_S` = `7200` — 2h
- `FOMC_POLL_INTERVAL_S` = `86400` — daily
- `IMPACT_CACHE_TTL_S` = `86400` — 1 day
- `SEC_EDGAR_USER_AGENT` = `""` — required: "Company admin@email.com"
- `EARNINGS_LOOKBACK_QUARTERS` = `12`
- `INSIDER_MIN_VALUE` = `50000` — min $ for notable insider trades
- `SEASONAL_LOOKBACK_YEARS` = `10`
- `PURGE_KEEP_DAYS` = `365`

## Agents (`ROT_AGENT_*`)
- `ENABLED` = `False` — master switch
- `EVAL_INTERVAL_S` = `60` — fallback polling (primary is signal callback)
- `MAX_AGENTS_PER_USER` = `5`
- `MAX_DAILY_TRADES` = `20` — global cap across all agents

## Options Flow (`ROT_FLOW_*`)
- `SCAN_INTERVAL_S` = `300` — 5 min
- `BLOCK_PREMIUM_THRESHOLD` = `100000` — min $ for block trade
- `SWEEP_VOLUME_THRESHOLD` = `1000`
- `DARK_POOL_THRESHOLD` = `50000`
- `ACCUMULATION_WINDOW_S` = `3600` — 1h detection window
- `PATTERN_MIN_EVENTS` = `3` — min events to form pattern
- `CONVERGENCE_WINDOW_S` = `1800` — flow-social convergence window
- `PURGE_KEEP_DAYS` = `90`

## Social Intelligence (`ROT_SOCIAL_*`)
- `TRACKING_ENABLED` = `True`
- `MANIPULATION_SCAN_INTERVAL_S` = `1800` — 30 min
- `AUTHOR_RESOLUTION_INTERVAL_S` = `3600` — 1h
- `MIN_PREDICTIONS_FOR_SCORE` = `10`
- `BOT_DETECTION_THRESHOLD` = `0.8`
- `PUMP_DUMP_WINDOW_S` = `7200` — 2h
- `PROPAGATION_MAX_LAG_S` = `86400` — 24h max cross-platform lag
- `PURGE_KEEP_DAYS` = `180`

## Strategy Builder (`ROT_STRATEGY_*`)
- `DISCOVERY_MAX_RULES` = `5` — max rules per discovered strategy
- `DISCOVERY_MAX_CANDIDATES` = `1000`
- `ML_MIN_SIGNALS` = `200` — min signals for ML optimizer
- `GENETIC_GENERATIONS` = `50`
- `GENETIC_POPULATION_SIZE` = `100`
- `AUTO_TRADE_ENABLED` = `True` — auto paper trade active strategies
- `MARKETPLACE_ENABLED` = `True`
- `REGIME_WINDOW_DAYS` = `30`
- `HEALTH_CHECK_INTERVAL_S` = `21600` — 6h
- `REGIME_DETECTION_INTERVAL_S` = `3600` — 1h
