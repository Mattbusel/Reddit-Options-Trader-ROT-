# Configuration Reference — ROT Architecture Reference

> Part of the ROT documentation suite. See [CLAUDE.md](../CLAUDE.md) for the full index.

## Quick Start for Agents

- Key file(s): `src/rot/core/config.py`
- Key pattern: All configuration via `ROT_*` environment variables, managed by Pydantic Settings. 18+ config sections.
- Minimal required: `ROT_REDDIT_CLIENT_ID`, `ROT_REDDIT_CLIENT_SECRET`, `ROT_LLM_API_KEY`

---

## Global Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ROT_STORAGE_ROOT` | `"storage"` | Root directory for all file storage |
| `ROT_DB_PATH` | `""` | SQLite DB path (auto-derived from storage_root if empty) |

---

## Reddit (`ROT_REDDIT_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `CLIENT_ID` | `""` | Reddit API client ID |
| `CLIENT_SECRET` | `""` | Reddit API client secret |
| `USER_AGENT` | `"rot:v0.1 (by u_rotbot)"` | PRAW user agent |
| `SUBREDDITS` | `["wallstreetbets","stocks","options"]` | Subreddits to monitor |
| `LISTING` | `"hot"` | Listing type (hot/new/rising) |
| `LIMIT_PER_SUB` | `50` | Posts per subreddit per poll |
| `INCLUDE_COMMENTS` | `False` | Fetch top comments |
| `TOP_COMMENTS` | `10` | Number of comments to fetch |
| `POLL_INTERVAL_S` | `20` | Seconds between polls (loop mode) |

---

## LLM (`ROT_LLM_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `PROVIDER` | `"openai"` | LLM provider: openai, anthropic, deepseek |
| `API_KEY` | `""` | Provider API key |
| `MODEL` | `"gpt-4o-mini"` | Model name |
| `BASE_URL` | `None` | Custom API base URL |
| `MAX_TOKENS` | `1024` | Max response tokens |
| `TEMPERATURE` | `0.3` | Sampling temperature |

---

## Market (`ROT_MARKET_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_TTL_S` | `3600` | Market data cache TTL |
| `SYMBOL_CACHE_TTL_S` | `604800` | Symbol validation cache (7 days) |
| `MIN_MARKET_CAP` | `1e8` | Minimum market cap ($100M) |
| `ENABLE_OPTIONS_CHAIN` | `False` | Fetch options chain data (disabled by default to save memory/network) |
| `OPTIONS_CACHE_TTL_S` | `1800` | Options data cache (30 min) |

---

## Trend (`ROT_TREND_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `WINDOW_S` | `1800` | Sliding window (30 min) |
| `THRESHOLD` | `0.01` | Minimum trend score |
| `COMMENT_WEIGHT` | `2.0` | Comment velocity weight vs score |
| `TOP_N` | `10` | Top N candidates per cycle |

---

## RSS (`ROT_RSS_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLED` | `False` | Enable RSS ingestion |
| `POLL_INTERVAL_S` | `300` | Default feed poll interval |
| `MAX_AGE_S` | `3600` | Max entry age |
| `SYNTHETIC_TREND_SCORE` | `0.5` | Default trend score for RSS |
| `MAX_ENTRIES_PER_FEED` | `50` | Max entries per feed |

---

## StockTwits (`ROT_STOCKTWITS_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLED` | `False` | Enable StockTwits |
| `SYMBOLS` | `["TSLA","AAPL","NVDA","SPY","QQQ","AMD","AMZN","MSFT"]` | Symbols to track |
| `TRENDING_ENABLED` | `True` | Include trending symbols |

---

## Twitter Ingest (`ROT_TWITTER_INGEST_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLED` | `False` | Enable Twitter ingestion |
| `BEARER_TOKEN` | `""` | Twitter API v2 bearer token |
| `CASHTAGS` | `["TSLA","AAPL","NVDA","SPY","QQQ"]` | Cashtags to track |
| `ACCOUNTS` | `["unusual_whales","zerohedge","DeItaone"]` | Accounts to follow |

---

## Twitter Poster (`ROT_TWITTER_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` / `API_SECRET` | `""` | Consumer credentials |
| `ACCESS_TOKEN` / `ACCESS_SECRET` | `""` | User credentials |
| `ENABLED` | `False` | Enable auto-posting |
| `INTERVAL_S` | `10800` | Min seconds between posts |
| `MIN_CONFIDENCE` | `0.5` | Min confidence to post |

---

## Email (`ROT_EMAIL_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `RESEND_API_KEY` | `""` | Resend HTTP API key (recommended) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | `""` | SMTP fallback |
| `FROM_ADDRESS` | `"ROT Alerts <alerts@rot.app>"` | Sender address |

---

## Auth (`ROT_AUTH_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | `""` | JWT signing secret (falls back to web.secret_key) |
| `JWT_ALGORITHM` | `"HS256"` | JWT algorithm |
| `JWT_EXPIRE_MINUTES` | `1440` | Token expiry (24h) |

---

## Stripe (`ROT_STRIPE_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `""` | Stripe secret key |
| `WEBHOOK_SECRET` | `""` | Stripe webhook signing secret |
| `PRO_PRICE_ID` | `""` | Stripe price ID for Pro tier |
| `PREMIUM_PRICE_ID` | `""` | Stripe price ID for Premium tier |
| `ULTRA_PRICE_ID` | `""` | Stripe price ID for Ultra tier |
| `ENTERPRISE_PRICE_ID` | `""` | Stripe price ID for Enterprise tier |

---

## Tier Limits (`ROT_TIER_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `FREE_SIGNAL_DELAY_S` | `900` | Free tier signal delay (15 min) |
| `FREE_PAGE_LIMIT` | `10` | Free tier max signals per page |
| `FREE_API_LIMIT_DAY` | `0` | Free tier API calls/day (blocked) |
| `PRO_API_LIMIT_DAY` | `1000` | Pro tier API calls/day |
| `PREMIUM_API_LIMIT_DAY` | `5000` | Premium tier |
| `ULTRA_API_LIMIT_DAY` | `25000` | Ultra tier |
| `ENTERPRISE_API_LIMIT_DAY` | `100000` | Enterprise tier |

---

## Web (`ROT_WEB_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `"0.0.0.0"` | Server bind host |
| `PORT` | `8000` | Server port |
| `SECRET_KEY` | `"change-me-in-production"` | Session/JWT fallback secret |

---

## ML Credibility (`ROT_ML_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLED` | `True` | Enable ML credibility scoring (falls back to heuristic when no model) |
| `MODEL_PATH` | `""` | Path to trained model pickle (auto-derived from storage_root if empty) |
| `MIN_TRAINING_SAMPLES` | `100` | Minimum resolved signals to start training |
| `RETRAIN_INTERVAL_S` | `86400` | Seconds between retrain attempts (24h) |
| `MIN_CLASS_SAMPLES` | `30` | Minimum samples per class (win/loss) to train |

---

## Feedback Engine (`ROT_FEEDBACK_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLED` | `True` | Enable feedback analysis background loop |
| `ANALYSIS_INTERVAL_S` | `21600` | Seconds between analysis cycles (6h) |
| `SUPPRESS_ENABLED` | `True` | Enable adaptive signal suppression (Stage 6.5) |
| `SUPPRESS_THRESHOLD` | `0.20` | Suppress categories with win rate below 20% |
| `SUPPRESS_SOURCE_THRESHOLD` | `0.15` | Suppress (event_type, source) combos below 15% |
| `MIN_SIGNALS_FOR_SUPPRESSION` | `30` | Minimum decided signals before suppression kicks in |
| `QUALITY_TREND_WINDOW_DAYS` | `30` | Days of history for quality trend analysis |

---

## Backtest Server (`ROT_BACKTEST_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_SIGNALS` | `5000` | Max signals per backtest query |
| `MONTE_CARLO_SIMS` | `1000` | Number of Monte Carlo simulations |
| `WALK_FORWARD_FOLDS` | `5` | Number of walk-forward folds |
| `OPTIMIZER_MAX_COMBOS` | `500` | Max parameter combinations for optimizer |

---

## Unusual Activity (`ROT_UNUSUAL_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `SCAN_INTERVAL_S` | `300` | Seconds between background scans (5 min) |
| `IV_RANK_THRESHOLD` | `80.0` | Flag if IV rank > 80th percentile |
| `VOLUME_SURGE_MULTIPLIER` | `2.0` | Flag if volume > 2x 20-day average |
| `OI_SURGE_PCT` | `20.0` | Flag if OI increases > 20% |
| `SKEW_STD_THRESHOLD` | `2.0` | Flag if P/C ratio > 2 std devs from mean |
| `COMPOSITE_MIN_SCORE` | `40.0` | Minimum composite score (0-100) to store event |
| `HISTORY_WINDOW_DAYS` | `20` | Rolling window for baseline computation |
| `PURGE_KEEP_DAYS` | `90` | Days to keep unusual events before purging |

---

## Sector Rotation (`ROT_SECTOR_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `MIN_SIGNALS` | `2` | Minimum signals per sector to include in analysis |
| `MOMENTUM_WINDOW_DAYS` | `30` | Rolling window for momentum scoring |

---

## Export Scheduler (`ROT_EXPORT_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `SCHEDULER_INTERVAL_S` | `3600` | Seconds between scheduler checks (1 hour) |
| `MAX_ROWS_PER_EXPORT` | `1000000` | Maximum rows per export file |

---

## Archive (`ROT_ARCHIVE_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `KEEP_DAYS` | `365` | How long to keep archived signals (1 year) |
