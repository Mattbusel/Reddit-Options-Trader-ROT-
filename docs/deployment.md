<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Deployment & Integrations

- **Files**: `Dockerfile`, `Procfile`, `pyproject.toml`, `src/rot/app/server.py`
- **Platform**: Railway, Docker multi-stage (builder + slim), persistent volume `/app/data`
- **Entry**: `python -m rot.app.server` | `python -m rot.app.main` (one-shot) | `python -m rot.app.loop` (no web)

## Production Env
`PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`, `ROT_STORAGE_ROOT=/app/data`, `ROT_WEB_HOST=0.0.0.0`, `PORT` from Railway

## Dependencies

**Security-critical (exact pin)**: fastapi==0.128.5, starlette==0.52.1, pydantic==2.12.5, pydantic-settings==2.12.0, aiosqlite==0.22.1, python-jose[cryptography]==3.5.0, cryptography==46.0.5, bcrypt==5.0.0, uvicorn[standard]==0.40.0, jinja2==3.1.6, httpx==0.28.1

**Application (loose)**: praw, yfinance, feedparser>=6.0, openai>=1.0, anthropic>=0.20, python-multipart>=0.0.6, stripe>=7.0, scikit-learn>=1.3, numpy>=1.24

**Defense-in-depth**: nh3>=0.2.14 (Rust-based HTML sanitizer)

**Dev**: pytest>=8.0, pytest-asyncio>=0.23, pytest-cov>=4.1, ruff>=0.2

> **Pinning policy**: Security-critical packages use exact `==` versions. Do not update without reviewing changelogs and running `pytest -x`. Dependabot monitors for CVEs. See `SECURITY.md` §8.

## Integrations

| Service | Config | Module |
|---------|--------|--------|
| Reddit (PRAW) | `ROT_REDDIT_CLIENT_ID/SECRET` | `ingest/reddit_ingestor.py` |
| yfinance | `ROT_MARKET_*` (1h cache, 7d symbol cache) | `market/enricher.py`, `market/symbol_validator.py` |
| LLM (OpenAI/Anthropic/DeepSeek) | `ROT_LLM_PROVIDER/API_KEY/MODEL` | `reasoner/llm_client.py` |
| Stripe | `ROT_STRIPE_SECRET_KEY/WEBHOOK_SECRET` + price IDs | `web/routes/stripe_routes.py` |
| Discord | Webhook URL | `alerts/discord.py` |
| Email (Resend/SMTP) | `ROT_EMAIL_RESEND_API_KEY` or `ROT_EMAIL_SMTP_*` | `alerts/email.py` |
| Twitter/X | `ROT_TWITTER_INGEST_*` (in), `ROT_TWITTER_*` (out) | `ingest/twitter_ingestor.py`, `alerts/twitter.py` |
| StockTwits | `ROT_STOCKTWITS_*` (no key needed) | `ingest/stocktwits_ingestor.py` |
| RSS (13+ feeds) | `ROT_RSS_*` | `ingest/rss_ingestor.py` |

RSS sources: MarketWatch, Investing.com, Yahoo Finance, CNBC, SeekingAlpha, FDA (5 feeds), Fed, SEC 8-K, DoD, BioPharma Dive, Drugs.com

## Background Loops
| Loop | Interval | Purpose |
|------|----------|---------|
| Pipeline | 20s | Main ingestion + processing |
| Price checker | periodic | Signal performance tracking |
| Cleanup | 30min | Purge old signals, archive |
| Unusual scanner | 5min | Unusual options activity |
| Export scheduler | 1h | Pending scheduled exports |
| Feedback analyzer | 6h | Category performance |
| ML retrain | 24h | Credibility model |
