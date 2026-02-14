# Deployment & External Integrations — ROT Architecture Reference

> Part of the ROT documentation suite. See [CLAUDE.md](../CLAUDE.md) for the full index.

## Quick Start for Agents

- Key file(s): `Dockerfile`, `Procfile`, `pyproject.toml`, `src/rot/app/server.py`
- Key pattern: Railway deployment with Docker, persistent volume for SQLite, multi-stage build
- Entry point: `python -m rot.app.server` (Procfile: `web: python -m rot.app.server`)

---

## Deployment (Railway)

### Docker Setup

- **Build**: Multi-stage (builder + slim runtime)
- **Base image**: Python 3.12-slim
- **Persistent Volume**: `/app/data` for SQLite database
- **Health check**: `GET /health`

### Environment Variables (Production)

| Variable | Value |
|----------|-------|
| `PYTHONUNBUFFERED` | `1` |
| `PYTHONDONTWRITEBYTECODE` | `1` |
| `ROT_STORAGE_ROOT` | `/app/data` |
| `ROT_WEB_HOST` | `0.0.0.0` |
| `PORT` | Set by Railway |

### Entry Points

| Command | Purpose |
|---------|---------|
| `python -m rot.app.server` | Web server + background pipeline loop (production) |
| `python -m rot.app.main` | One-shot pipeline run |
| `python -m rot.app.loop` | Continuous polling loop (no web server) |

---

## Dependencies

### Runtime (pyproject.toml)

```
praw, yfinance, feedparser>=6.0, pydantic>=2.0, pydantic-settings>=2.0,
openai>=1.0, anthropic>=0.20, fastapi>=0.109, uvicorn[standard]>=0.27,
aiosqlite>=0.19, python-jose[cryptography]>=3.3, bcrypt>=4.0,
httpx>=0.26, jinja2>=3.1, python-multipart>=0.0.6, stripe>=7.0,
scikit-learn>=1.3, numpy>=1.24
```

### Dev Dependencies

```
pytest>=8.0, pytest-asyncio>=0.23, pytest-cov>=4.1, ruff>=0.2
```

---

## External Integrations

### Reddit (PRAW)

| Detail | Value |
|--------|-------|
| Protocol | OAuth2 via PRAW |
| Required config | `ROT_REDDIT_CLIENT_ID`, `ROT_REDDIT_CLIENT_SECRET` |
| Data fetched | Posts (hot/new/rising) + optional top comments |
| Module | `src/rot/ingest/reddit_ingestor.py` |

### yfinance

| Detail | Value |
|--------|-------|
| Data | Last close, 1d change, market cap, ATM IV, put/call OI ratio |
| Caching | Market data: 1h TTL (500 entries max). Symbol validation: 7d TTL (1000 entries max) |
| Options chain | Disabled by default (`ROT_MARKET_ENABLE_OPTIONS_CHAIN=False`) |
| Module | `src/rot/market/enricher.py`, `src/rot/market/symbol_validator.py` |

### OpenAI / Anthropic / DeepSeek

| Detail | Value |
|--------|-------|
| Client | Provider-agnostic `LLMClient` |
| Config | `ROT_LLM_PROVIDER`, `ROT_LLM_API_KEY`, `ROT_LLM_MODEL` |
| Circuit breaker | Disables after 3 consecutive failures |
| Module | `src/rot/reasoner/llm_client.py` |

### Stripe

| Detail | Value |
|--------|-------|
| Purpose | Subscription billing for 4 paid tiers |
| Flow | Checkout session --> hosted payment --> webhook --> tier update |
| Customer portal | Self-service management |
| Config | `ROT_STRIPE_SECRET_KEY`, `ROT_STRIPE_WEBHOOK_SECRET`, price IDs |
| Module | `src/rot/web/routes/stripe_routes.py` |

### Discord

| Detail | Value |
|--------|-------|
| Method | Webhook-based signal alerts |
| Format | Formatted embeds with signal data |
| Filter | Configurable min confidence threshold |
| Module | `src/rot/alerts/discord.py` |

### Resend / SMTP

| Detail | Value |
|--------|-------|
| Primary | Resend HTTP API (`ROT_EMAIL_RESEND_API_KEY`) |
| Fallback | SMTP (`ROT_EMAIL_SMTP_*`) |
| Alert types | Daily digest + real-time |
| Per-user filters | Tickers, stances, event types |
| Module | `src/rot/alerts/email.py` |

### Twitter/X

| Detail | Value |
|--------|-------|
| Ingestion | Twitter API v2 recent search (cashtags + accounts) |
| Posting | OAuth 1.0a auto-posting of top signals |
| Ingest config | `ROT_TWITTER_INGEST_*` |
| Post config | `ROT_TWITTER_*` |
| Modules | `src/rot/ingest/twitter_ingestor.py`, `src/rot/alerts/twitter.py` |

### StockTwits

| Detail | Value |
|--------|-------|
| Protocol | HTTP API (public endpoints, no key required) |
| Data | Symbol streams + trending |
| Config | `ROT_STOCKTWITS_*` |
| Module | `src/rot/ingest/stocktwits_ingestor.py` |

### RSS Feeds (13+ default feeds)

| Feed Category | Sources |
|--------------|---------|
| Financial news | MarketWatch, Investing.com, Yahoo Finance, CNBC, SeekingAlpha |
| FDA | Press releases, drug approvals, safety alerts, recalls, oncology |
| Government | Federal Reserve (press releases), DoD (contracts, releases, news) |
| Regulatory | SEC (8-K filings) |
| Pharma | BioPharma Dive, Drugs.com (approvals, trials) |

Config: `ROT_RSS_*`. Module: `src/rot/ingest/rss_ingestor.py`.

---

## Background Loops (Production)

The `server.py` FastAPI factory starts these background `asyncio` tasks:

| Loop | Interval | Purpose |
|------|----------|---------|
| Pipeline | `ROT_REDDIT_POLL_INTERVAL_S` (20s) | Main ingestion + processing pipeline |
| Price checker | Periodic | Tracks signal performance prices |
| Cleanup | 30 min | Purges old signals, archives before delete |
| Unusual activity scanner | 5 min | Detects unusual options activity |
| Export scheduler | 1 hour | Runs pending scheduled exports |
| Feedback analyzer | 6 hours | Recomputes category performance |
| ML retrain | 24 hours | Retrains credibility model |
