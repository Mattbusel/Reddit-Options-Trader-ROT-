# Reddit Options Trader (ROT)

[![CI](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/ci.yml/badge.svg)](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/ci.yml)
[![Tests](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/tests.yml/badge.svg)](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/tests.yml)
[![Security](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/security.yml/badge.svg)](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/security.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Coverage: 75%+](https://img.shields.io/badge/coverage-75%25%2B-brightgreen)]()
[![CodeQL: 0 alerts](https://img.shields.io/badge/CodeQL-0%20alerts-brightgreen)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A full-stack financial intelligence platform that monitors Reddit and RSS feeds in real time, classifies market events using a 10-module NLP pipeline, scores credibility via a gradient-boosting model, optionally augments reasoning with an LLM, and generates structured options trade ideas -- all surfaced through a FastAPI web dashboard.

This is not a trading execution engine. ROT is the intelligence layer that surfaces what matters before price fully reacts.

**Live deployment:** [rot.up.railway.app](https://web-production-71423.up.railway.app/)

---

## Features

- **Real-time ingestion** -- Reddit (PRAW streaming) and 13+ RSS feeds including Reuters Business and SEC 8-K filings
- **9-stage signal pipeline** -- Trend Detection > NLP > Event Classification > Market Enrichment > Credibility Scoring > Feedback Suppression > LLM Reasoning > Trade Ideas
- **10-module NLP engine** -- custom tokenizer, lexicon, entity extraction, sentiment, sarcasm detection, conviction scoring, temporal reasoning, thread analysis
- **ML credibility scorer** -- GradientBoosting with 12 heuristic features, transparent score breakdown
- **LLM reasoning** -- provider-agnostic (OpenAI, Anthropic, DeepSeek), circuit breaker with stub fallback
- **Trade idea generation** -- bull call spreads, bear put spreads, straddles; ATM +/-5% strike selection; weekly/monthly expiry heuristics; max-loss calculation
- **FastAPI web dashboard** -- WebSocket signal feed, dark theme, confidence bars, full reasoning display
- **Backtesting engine** -- Monte Carlo simulation, walk-forward optimization, 12 modules
- **Strategy builder** -- rule-based, ML optimizer, genetic algorithms, regime detection, marketplace
- **Options flow intelligence** -- block/sweep/dark pool detection, IV analysis, Greek calculations
- **Social manipulation detection** -- bot detection, pump-dump patterns, coordination tracking
- **Macro event calendar** -- FOMC schedule, earnings tracking, seasonal patterns, insider activity
- **Multi-method authentication** -- JWT + API key + session cookie, 5-tier hierarchy (Free > Pro > Premium > Ultra > Enterprise), 35+ tier gates
- **Enterprise security** -- CodeQL, Bandit, pip-audit, TruffleHog, Dependabot on every push; 0 open CVEs; nonce-based CSP; CSRF middleware; rate limiting
- **6,900+ tests** -- 1.57:1 test-to-production ratio; zero external API calls; 75% coverage floor enforced in CI

---

## Quickstart (Docker)

```bash
git clone https://github.com/Mattbusel/Reddit-Options-Trader-ROT-.git
cd Reddit-Options-Trader-ROT-

# Configure environment
cp .env.example .env
# Edit .env -- see Environment Variables section below

# Build and start
docker compose up --build

# Dashboard: http://localhost:8000/dashboard
# API docs:  http://localhost:8000/docs
```

---

## Quickstart (Manual)

```bash
git clone https://github.com/Mattbusel/Reddit-Options-Trader-ROT-.git
cd Reddit-Options-Trader-ROT-

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install with dev dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env -- see Environment Variables section below

# Run the server
python -m rot.app.server

# Dashboard: http://localhost:8000/dashboard
# API docs:  http://localhost:8000/docs
```

Run the standalone pipeline loop (no web server):

```bash
python -m rot.app.loop
```

Run a single pipeline pass:

```bash
python -m rot.app.main
```

---

## Environment Variables

All variables are optional unless marked **required**.

| Variable | Default | Description |
|---|---|---|
| `ROT_REDDIT_CLIENT_ID` | `""` | **Required for Reddit.** Reddit API client ID |
| `ROT_REDDIT_CLIENT_SECRET` | `""` | **Required for Reddit.** Reddit API client secret |
| `ROT_REDDIT_USER_AGENT` | `rot:v1 (by u_rotbot)` | Reddit API user-agent string |
| `ROT_REDDIT_SUBREDDITS` | `wallstreetbets,stocks,options` | Comma-separated subreddit list |
| `ROT_REDDIT_LISTING` | `hot` | Feed type: `hot`, `new`, `rising`, `top` |
| `ROT_REDDIT_LIMIT_PER_SUB` | `50` | Posts to fetch per subreddit per poll |
| `ROT_REDDIT_POLL_INTERVAL_S` | `20` | Poll interval in seconds |
| `ROT_LLM_PROVIDER` | `openai` | LLM provider: `openai`, `anthropic`, `deepseek` |
| `ROT_LLM_API_KEY` | `""` | LLM API key. Leave empty to disable LLM reasoning |
| `ROT_LLM_MODEL` | `gpt-4o-mini` | Model name to use |
| `ROT_LLM_MAX_TOKENS` | `1024` | Max response tokens |
| `ROT_LLM_TEMPERATURE` | `0.3` | Sampling temperature |
| `ROT_RSS_ENABLED` | `false` | Enable RSS feed ingestion |
| `ROT_MARKET_MIN_MARKET_CAP` | `100000000` | Minimum market cap filter ($100M) |
| `ROT_MARKET_CACHE_TTL_S` | `3600` | Market data cache TTL in seconds |
| `ROT_TREND_WINDOW_S` | `1800` | Trend detection window in seconds |
| `ROT_TREND_THRESHOLD` | `0.01` | Trend score threshold |
| `ROT_ALERT_DISCORD_WEBHOOK_URL` | `""` | Discord webhook URL for signal alerts |
| `ROT_STORAGE_ROOT` | `./data` | Path for SQLite databases and state files |
| `ROT_SECRET_KEY` | auto-generated | HMAC secret for CSRF and session signing |
| `STRIPE_SECRET_KEY` | `""` | Stripe secret key for subscription billing |
| `STRIPE_WEBHOOK_SECRET` | `""` | Stripe webhook signing secret |

---

## Architecture

### 9-Stage Pipeline

```
Stage 1: Reddit/RSS Ingestion
      |
Stage 2: Trend Detection
      |
Stage 3: NLP / Entity Extraction
      |
Stage 4: Event Building
      |
Stage 5: Market Data Enrichment
      |
Stage 6: Credibility Scoring
      |
Stage 7: Feedback Suppression
      |
Stage 8: LLM Reasoning (OpenAI / Anthropic)
      |
Stage 9: Trade Idea Generation
```

Every stage runs continuously. Memory-bounded dedup (max 2,000 entries). Circuit breaker on LLM (auto-disables after 3 failures, activates stub fallback). Full pipeline executes in seconds per pass.

Signal flow is memory-bounded (max 2,000 dedup entries). The full pipeline runs in seconds per pass.

### Module Layout

```
src/rot/
  app/           Server, pipeline runner, background loops
  ingest/        Reddit + RSS ingestion (7 modules)
  trend/         Trend detection and ranking
  nlp/           10-module NLP pipeline (500+ lexicon terms)
  extract/       Event builder (dual-path NLP/regex)
  market/        Trade builder, enrichment, validation
  credibility/   ML scorer + 12 heuristics
  reasoner/      LLM reasoning with circuit breaker
  storage/       33+ tables, 16 DB mixins, migrations
  web/           FastAPI routes, auth, middleware, Jinja2 templates
  strategy/      ML, genetic, regime detection, marketplace
  social/        Manipulation detection, propagation, network analysis
  flow/          Options flow intelligence, Greek calculations
  backtest/      Monte Carlo, walk-forward, 12 modules
  macro/         FOMC, earnings, seasonal patterns, insider activity
  alerts/        Discord, email, Twitter, webhook dispatch
  agents/        Autonomous trading agents (safety rails)
  gamification/  Badges, leaderboards, progression system
  export/        Enterprise exports, 9-step data lineage
  core/          Config, types, structured logging, sanitization
  affiliates/    Affiliate tracking
  sports/        Sports event correlation
  analysis/      Sector and correlation analysis

tests/           201 files, 92,000+ lines, 6,900+ test functions
```

### Security

| Control | Implementation |
|---|---|
| Authentication | JWT + API key + session cookie (3 independent methods) |
| Authorization | 5-tier hierarchy; 35+ gate functions; admin bypass |
| SQL injection | 100% parameterized queries; field whitelist for dynamic updates |
| XSS | Jinja2 autoescape + nh3 Rust sanitizer + nonce-based CSP |
| CSRF | Custom ASGI middleware; timing-safe HMAC comparison |
| Security headers | CSP, X-Frame-Options: DENY, X-Content-Type-Options, Referrer-Policy, Permissions-Policy |
| Rate limiting | Database-backed, multi-instance-safe; per-tier daily + burst limits |
| Security logging | 10 SIEM-ready JSON event types; global sanitizing filter; request-ID correlation |
| CI scanners | CodeQL, Bandit, pip-audit, TruffleHog, Dependabot |

---

## Running Tests

```bash
# Full suite with coverage
pytest tests/ --cov=rot --cov-report=term-missing --cov-fail-under=75

# Parallel execution (faster)
pytest tests/ -n auto -q

# Single file
pytest tests/test_nlp_engine.py -v

# With short tracebacks
pytest tests/ --tb=short
```

---

## Development

### Prerequisites

- Python 3.10, 3.11, or 3.12
- Docker (optional, for containerized deployment)

### Setup

```bash
pip install -e ".[dev]"
```

### Lint

```bash
ruff check src/ tests/
ruff format src/ tests/
```

### Type check

```bash
mypy src/rot/core/ src/rot/app/ --ignore-missing-imports
```

### Pre-commit workflow

```bash
ruff check src/ tests/ && ruff format src/ tests/ && pytest tests/ -n auto -q --tb=short
```

---

## Contributing

1. Fork the repository and create a feature branch from `master`.
2. Write tests for any new behavior. Aim to keep the test-to-production ratio above 1.5:1.
3. Ensure `ruff check`, `ruff format --check`, and `pytest` all pass locally before opening a pull request.
4. Keep pull requests focused: one logical change per PR.
5. Reference any related issues in the PR description.
6. Do not commit secrets, credentials, or generated files to version control.

---

## API Reference

See [`docs/api-reference.md`](docs/api-reference.md) for the full endpoint catalog, or visit `/docs` on a running server for the interactive Swagger UI.

---

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for release history.

---

## License

Copyright (c) 2026 Matthew Busel. All rights reserved.

Third-party dependency licenses are listed in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

---

## Disclaimer

This project is for research and educational purposes only. Nothing in this repository constitutes financial advice. ROT is a signal intelligence platform, not a trading execution engine. Past signal quality does not guarantee future performance. Use at your own risk.
