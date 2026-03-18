# ROT Deployment Guide

## Overview

ROT deploys as a single Docker container on Railway with a persistent volume for SQLite storage.
The application runs as a non-root user (`rot`, UID 1000) via a `gosu`-based entrypoint.

- **Platform**: Railway (primary), any Docker host
- **Image**: Multi-stage build — builder (python:3.12-slim + gcc) + runtime (python:3.12-slim)
- **Persistent volume**: `/app/data` (SQLite database + backups + ML model)
- **Port**: 8000 (configurable via `PORT` env var)
- **Entry points**:
  - `python -m rot.app.server` — full stack: web server + pipeline (default)
  - `python -m rot.app.main` — one-shot pipeline run, no web server
  - `python -m rot.app.loop` — pipeline only, no web server

---

## Docker Deployment

### Dockerfile Overview

The Dockerfile uses a two-stage build:

1. **Builder stage** (`python:3.12-slim`): installs gcc, creates a virtualenv at `/opt/venv`, installs all Python dependencies.
2. **Runtime stage** (`python:3.12-slim`): copies only the virtualenv (no build tools), installs `gosu`, creates non-root user `rot` (UID 1000), sets up `/app/data` with correct ownership.

The `entrypoint.sh` script runs as root to fix volume ownership (in case the mounted volume is owned by root), then uses `gosu rot` to drop privileges before exec-ing the application command.

### Build and Run

    # Build the image
    docker build -t rot:latest .

    # Run with environment variables
    docker run -d \
      --name rot \
      -p 8000:8000 \
      -v rot_data:/app/data \
      -e ROT_WEB_SECRET_KEY=your-strong-32-char-secret-key \
      -e ROT_REDDIT_CLIENT_ID=your_reddit_client_id \
      -e ROT_REDDIT_CLIENT_SECRET=your_reddit_client_secret \
      -e ROT_LLM_API_KEY=your_openai_or_anthropic_key \
      rot:latest

### docker-compose (Local Development)

    docker-compose up --build

The `docker-compose.yml` defines three profiles:
- Default: runs the `rot` service with synthetic data enabled
- `test`: runs pytest in an isolated container (`docker-compose run --rm test`)
- `seed`: seeds 30 days of synthetic resolved outcome data

The healthcheck polls `GET /health` every 10 seconds with a 5-second timeout, 3 retries.

### Railway Deployment

1. Connect the GitHub repository to a Railway project.
2. Railway auto-detects the Dockerfile and builds on push to main.
3. Add a persistent volume mounted at `/app/data`.
4. Set all required environment variables in the Railway Variables panel.
5. Railway injects `PORT` automatically; the app reads it via `ROT_WEB_PORT` or falls back to `PORT`.

Live deployment: https://web-production-71423.up.railway.app/

---

## Environment Variables Reference

All variables use the `ROT_` prefix. Nested config sections use `ROT_<SECTION>_<KEY>`.

### Core Web

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| ROT_WEB_SECRET_KEY | change-me-in-production | **YES** | Session signing key. Must be 32+ chars in production. |
| ROT_WEB_HOST | 0.0.0.0 | No | Bind address. Use 127.0.0.1 if behind a reverse proxy on localhost. |
| ROT_WEB_PORT | 8000 | No | HTTP port. Railway overrides with PORT env var. |
| ROT_WEB_CORS_ORIGINS | http://localhost:8000 | No | Comma-separated allowed CORS origins. |
| ROT_STORAGE_ROOT | storage | No | Directory for SQLite DB and backups. Set /app/data in Docker. |
| ROT_DB_PATH | (auto) | No | Explicit SQLite path. Defaults to {ROT_STORAGE_ROOT}/rot.db. |
| ROT_ENV | (unset) | No | Set to "production" to enforce strong secret key validation. |

### Authentication

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| ROT_AUTH_JWT_SECRET | (empty) | No | JWT signing secret. Falls back to ROT_WEB_SECRET_KEY if empty. |
| ROT_AUTH_JWT_ALGORITHM | HS256 | No | JWT signing algorithm. |
| ROT_AUTH_JWT_EXPIRE_MINUTES | 1440 | No | JWT token lifetime in minutes (default 24 hours). |
| ROT_AUTH_ADMIN_EMAILS | (empty) | No | JSON array or comma-separated emails for admin tier. Example: admin@example.com |

### Reddit Ingestion

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| ROT_REDDIT_CLIENT_ID | (empty) | **YES** | Reddit API client ID (from https://www.reddit.com/prefs/apps). |
| ROT_REDDIT_CLIENT_SECRET | (empty) | **YES** | Reddit API client secret. |
| ROT_REDDIT_USER_AGENT | rot:v0.1 (by u_rotbot) | No | User-agent string for Reddit API requests. |
| ROT_REDDIT_SUBREDDITS | ["wallstreetbets","stocks","options"] | No | JSON array of subreddits to monitor. |
| ROT_REDDIT_LISTING | hot | No | Listing type: hot, new, rising, top. |
| ROT_REDDIT_LIMIT_PER_SUB | 50 | No | Max posts per subreddit per poll. |
| ROT_REDDIT_POLL_INTERVAL_S | 20 | No | Seconds between Reddit polls. |

### LLM Reasoning

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| ROT_LLM_PROVIDER | openai | No | LLM provider: openai, anthropic, or deepseek. |
| ROT_LLM_API_KEY | (empty) | No | API key for the configured LLM provider. LLM is disabled if empty. |
| ROT_LLM_MODEL | gpt-4o-mini | No | Model name. Provider-specific. |
| ROT_LLM_MAX_TOKENS | 1024 | No | Max tokens per LLM response. |
| ROT_LLM_TEMPERATURE | 0.3 | No | Sampling temperature (0.0-1.0). |
| ROT_LLM_BASE_URL | (empty) | No | Optional custom API base URL (for DeepSeek or local proxies). |

### Market Data

| Variable | Default | Description |
|----------|---------|-------------|
| ROT_MARKET_CACHE_TTL_S | 3600 | Price data cache TTL in seconds (1 hour). |
| ROT_MARKET_SYMBOL_CACHE_TTL_S | 604800 | Symbol validation cache TTL (7 days). |
| ROT_MARKET_MIN_MARKET_CAP | 100000000 | Minimum market cap ($100M) to generate trade ideas. |
| ROT_MARKET_PRICE_CHECK_INTERVAL_S | 300 | Interval for post-signal price tracking (5 minutes). |
| ROT_MARKET_ENABLE_OPTIONS_CHAIN | true | Whether to fetch options chain data via yfinance. |

### Alerts

| Variable | Default | Description |
|----------|---------|-------------|
| ROT_ALERT_DISCORD_WEBHOOK_URL | (empty) | Discord webhook URL. Discord alerts disabled if empty. |
| ROT_ALERT_MIN_CONFIDENCE | 0.6 | Minimum confidence score to trigger an alert. |
| ROT_EMAIL_RESEND_API_KEY | (empty) | Resend HTTP API key. Preferred for cloud deployments. |
| ROT_EMAIL_SMTP_HOST | (empty) | SMTP server hostname (fallback to Resend). |
| ROT_EMAIL_SMTP_PORT | 587 | SMTP port (587=STARTTLS, 465=SSL). |
| ROT_EMAIL_SMTP_USER | (empty) | SMTP authentication username. |
| ROT_EMAIL_SMTP_PASSWORD | (empty) | SMTP authentication password. |
| ROT_EMAIL_ENABLED | false | Master switch for email alerts. |
| ROT_TWITTER_API_KEY | (empty) | Twitter/X OAuth 1.0a consumer key (for posting alerts). |
| ROT_TWITTER_API_SECRET | (empty) | Twitter/X OAuth 1.0a consumer secret. |
| ROT_TWITTER_ACCESS_TOKEN | (empty) | Twitter/X user access token. |
| ROT_TWITTER_ACCESS_SECRET | (empty) | Twitter/X user access token secret. |
| ROT_TWITTER_ENABLED | false | Master switch for Twitter/X alert posting. |

### Stripe Billing

| Variable | Default | Description |
|----------|---------|-------------|
| ROT_STRIPE_SECRET_KEY | (empty) | Stripe secret key. Billing disabled if empty. |
| ROT_STRIPE_WEBHOOK_SECRET | (empty) | Stripe webhook signing secret for endpoint verification. |
| ROT_STRIPE_PRO_PRICE_ID | (empty) | Stripe Price ID for the Pro plan. |
| ROT_STRIPE_PREMIUM_PRICE_ID | (empty) | Stripe Price ID for the Premium plan. |
| ROT_STRIPE_ULTRA_PRICE_ID | (empty) | Stripe Price ID for the Ultra plan. |
| ROT_STRIPE_ENTERPRISE_PRICE_ID | (empty) | Stripe Price ID for the Enterprise plan. |

### Tier Limits

| Variable | Default | Description |
|----------|---------|-------------|
| ROT_TIER_FREE_SIGNAL_DELAY_S | 900 | Signal delay for free-tier users (15 minutes). |
| ROT_TIER_FREE_PAGE_LIMIT | 10 | Max signals per page for free-tier users. |
| ROT_TIER_FREE_API_LIMIT_DAY | 0 | Daily API calls for free tier (0 = blocked). |
| ROT_TIER_PRO_API_LIMIT_DAY | 1000 | Daily API calls for Pro tier. |
| ROT_TIER_PREMIUM_API_LIMIT_DAY | 5000 | Daily API calls for Premium tier. |
| ROT_TIER_ULTRA_API_LIMIT_DAY | 25000 | Daily API calls for Ultra tier. |
| ROT_TIER_ENTERPRISE_API_LIMIT_DAY | 100000 | Daily API calls for Enterprise tier. |

### RSS Feeds

| Variable | Default | Description |
|----------|---------|-------------|
| ROT_RSS_ENABLED | false | Master switch for RSS ingestion. |
| ROT_RSS_POLL_INTERVAL_S | 300 | Global RSS polling interval (5 minutes). |
| ROT_RSS_MAX_AGE_S | 3600 | Freshness gate — items older than 1 hour bypass trend scoring. |
| ROT_RSS_MAX_ENTRIES_PER_FEED | 50 | Cap on entries processed per feed per poll. |

### Optional Integrations

| Variable | Default | Description |
|----------|---------|-------------|
| ROT_STOCKTWITS_ENABLED | false | Enable StockTwits ingestion. |
| ROT_TWITTER_INGEST_ENABLED | false | Enable Twitter/X reading (requires bearer token). |
| ROT_TWITTER_INGEST_BEARER_TOKEN | (empty) | Twitter API v2 bearer token for reading tweets. |
| ROT_MACRO_ENABLED | true | Enable macro events calendar engine. |
| ROT_ML_ENABLED | true | Enable ML credibility scoring (falls back to heuristic). |
| ROT_FEEDBACK_ENABLED | true | Enable adaptive signal suppression feedback loop. |
| ROT_AGENT_ENABLED | false | Enable autonomous trading agents. |
| ROT_SOCIAL_TRACKING_ENABLED | true | Enable author accuracy tracking. |

### Macro Events (SEC EDGAR)

| Variable | Default | Description |
|----------|---------|-------------|
| ROT_MACRO_SEC_EDGAR_USER_AGENT | (empty) | Required by SEC: "CompanyName admin@email.com" format. |
| ROT_MACRO_INSIDER_MIN_VALUE | 50000 | Minimum dollar value for notable insider trades. |

---

## Health Check Endpoint

### Public Health Check

`GET /health` — returns `{"status": "ok"}` with HTTP 200. Used by Docker healthcheck and Railway health probes.

### Admin Health Check

`GET /health` with `Authorization: Bearer <admin-jwt>` — returns full diagnostic payload:

```
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "database": {
    "status": "connected",
    "signals_stored": 12345,
    "size_mb": 48.2
  },
  "system": {
    "memory_rss_mb": 312.4,
    "memory_percent": 3.1,
    "cpu_percent": 0.8,
    "num_threads": 24,
    "python_version": "3.12.0",
    "platform": "Linux",
    "disk_usage_percent": 42.1,
    "disk_free_gb": 18.4
  },
  "backups": {
    "count": 7,
    "total_size_mb": 336.0,
    "latest_backup": {
      "filename": "rot_backup_20260318_030000.db.gz",
      "age_hours": 6.2,
      "size_mb": 48.0
    }
  },
  "environment": {
    "deployment": "railway",
    "railway_env": "production"
  }
}
```

Docker healthcheck configuration in docker-compose.yml:

    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3

---

## Production Checklist

### Security

- [ ] Set `ROT_WEB_SECRET_KEY` to a cryptographically random 32+ character string. Generate with: `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] Set `ROT_AUTH_JWT_SECRET` independently of the web secret key.
- [ ] Set `ROT_AUTH_ADMIN_EMAILS` to the email address(es) of your admin accounts.
- [ ] Terminate TLS at the reverse proxy or Railway level — never serve HTTP directly in production.
- [ ] Set `ROT_STRIPE_WEBHOOK_SECRET` if accepting payments (prevents webhook spoofing).
- [ ] Rotate `ROT_WEB_SECRET_KEY` periodically (quarterly or on suspected compromise) — this invalidates all active sessions.
- [ ] Never commit `.env` files to version control. Use Railway Variables or a secrets manager.

### Database

- [ ] Mount `/app/data` as a persistent volume. Without this, all data is lost on container restart.
- [ ] Verify the admin health check shows `database.status: "connected"` after first boot.
- [ ] The backup system automatically creates GZip-compressed copies in `/app/data/backups/`. Verify the `backups.count` field increments in the admin health check.
- [ ] Set up an external backup job (e.g., Railway volume snapshots or rclone to S3) to protect against volume loss.
- [ ] Monitor `database.size_mb` in the health check — SQLite WAL files can grow; run `VACUUM` if needed.

### Application

- [ ] Set `ROT_REDDIT_CLIENT_ID` and `ROT_REDDIT_CLIENT_SECRET` (required for signal ingestion).
- [ ] Set `ROT_LLM_API_KEY` if you want LLM reasoning (optional — the circuit breaker stub will be used otherwise).
- [ ] Verify the pipeline is running by checking that new signals appear in the dashboard within a few minutes of deployment.
- [ ] Set `ROT_ALERT_DISCORD_WEBHOOK_URL` if you want Discord alert delivery.
- [ ] Set `ROT_EMAIL_RESEND_API_KEY` (recommended) or SMTP settings if you want email alerts.
- [ ] Set `ROT_MACRO_SEC_EDGAR_USER_AGENT` in the format "CompanyName admin@email.com" if you want insider trading data (required by SEC).

### Monitoring

- [ ] Set up an uptime monitor on `GET /health` (e.g., UptimeRobot, Better Uptime).
- [ ] Review Railway deployment logs after each deploy to confirm no startup errors.
- [ ] Check the admin health check endpoint periodically for memory growth or disk pressure.

---

## Background Loops

| Loop | Interval | Purpose |
|------|----------|---------|
| Pipeline | 20s | Main Reddit/RSS ingestion and 9-stage processing |
| Price checker | 5min | Post-signal price tracking for win/loss attribution |
| Cleanup | 30min | Archive and purge signals older than 14 days |
| Unusual activity scanner | 5min | IV spike / volume surge / options sweep detection |
| Flow intelligence scanner | 5min | Block trade / dark pool detection |
| Manipulation scanner | 30min | Bot detection and pump-dump pattern analysis |
| Author resolution | 1h | Resolve author accuracy from historical signals |
| Export scheduler | 1h | Process pending scheduled enterprise exports |
| Feedback analyzer | 6h | Category win-rate analysis and suppression update |
| Macro calendar | 1h | FOMC, earnings, insider trade polling |
| Strategy health | 6h | Strategy marketplace health checks |
| ML retrain | 24h | Retrain GradientBoosting credibility model |

---

## Integrations

| Service | Key Config Variables | Module |
|---------|---------------------|--------|
| Reddit (PRAW) | ROT_REDDIT_CLIENT_ID, ROT_REDDIT_CLIENT_SECRET | ingest/reddit_ingestor.py |
| RSS (13+ feeds) | ROT_RSS_ENABLED, ROT_RSS_POLL_INTERVAL_S | ingest/rss_ingestor.py |
| yfinance | ROT_MARKET_CACHE_TTL_S, ROT_MARKET_MIN_MARKET_CAP | market/enricher.py |
| OpenAI | ROT_LLM_PROVIDER=openai, ROT_LLM_API_KEY, ROT_LLM_MODEL | reasoner/llm_client.py |
| Anthropic | ROT_LLM_PROVIDER=anthropic, ROT_LLM_API_KEY | reasoner/llm_client.py |
| DeepSeek | ROT_LLM_PROVIDER=deepseek, ROT_LLM_API_KEY, ROT_LLM_BASE_URL | reasoner/llm_client.py |
| Stripe | ROT_STRIPE_SECRET_KEY, ROT_STRIPE_WEBHOOK_SECRET, price IDs | web/routes/stripe_routes.py |
| Discord | ROT_ALERT_DISCORD_WEBHOOK_URL | alerts/discord.py |
| Email (Resend) | ROT_EMAIL_RESEND_API_KEY, ROT_EMAIL_ENABLED=true | alerts/email.py |
| Email (SMTP) | ROT_EMAIL_SMTP_HOST/PORT/USER/PASSWORD, ROT_EMAIL_ENABLED=true | alerts/email.py |
| Twitter/X (alerts) | ROT_TWITTER_API_KEY/SECRET/ACCESS_TOKEN/ACCESS_SECRET | alerts/twitter.py |
| Twitter/X (ingest) | ROT_TWITTER_INGEST_BEARER_TOKEN, ROT_TWITTER_INGEST_ENABLED=true | ingest/twitter_ingestor.py |
| StockTwits | ROT_STOCKTWITS_ENABLED=true (no API key needed) | ingest/stocktwits_ingestor.py |
| SEC EDGAR | ROT_MACRO_SEC_EDGAR_USER_AGENT | macro/insider.py |

RSS feed sources (all enabled by default when ROT_RSS_ENABLED=true): MarketWatch Top Stories, MarketWatch Realtime Headlines, Investing.com Stocks, Yahoo Finance (SPY/QQQ/AAPL/TSLA/NVDA), CNBC Markets, Seeking Alpha, DoD Contracts (30-min), DoD Releases (30-min), DoD News (30-min), FDA Press Releases (30-min), FDA Drugs (30-min), FDA Recalls (30-min), Federal Reserve Press Releases.
