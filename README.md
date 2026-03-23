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

### Options Greeks Calculator

`src/rot/flow/greeks.py` provides two complementary Greeks APIs:

**`GreeksEngine`** (pure-Python, zero extra dependencies) — original implementation used internally throughout the pipeline.

**`BlackScholesGreeks` / `OptionGreeks` / `GreeksCalculator` / `SpreadGreeks`** — higher-level API that uses `scipy.stats.norm` for N(d1)/N(d2) when scipy is installed, with a pure-Python fallback.

```python
from rot.flow.greeks import BlackScholesGreeks, GreeksCalculator, SpreadGreeks

# Single option
bsg = BlackScholesGreeks(risk_free_rate=0.05)
og = bsg.all_greeks(S=150, K=155, T=0.25, sigma=0.30, option_type="call")

# Strike/DTE-based calculator
calc = GreeksCalculator(strike=155, dte_days=30, spot=150, volatility=0.28)
og = calc.compute("call")

# Spread aggregation
spread = SpreadGreeks(spot=150)
bull_spread = spread.bull_call_spread(long_strike=150, short_strike=160, dte_days=30, volatility=0.25)
straddle = spread.straddle(strike=150, dte_days=30, volatility=0.30)
```

Supported spread types: `bull_call_spread`, `bear_put_spread`, `straddle`, and arbitrary multi-leg via `aggregate(legs)`.

---

### User Reputation System

`src/rot/credibility/user_reputation.py` builds a per-user reputation score from Reddit metadata and integrates with the credibility pipeline.

**Scoring components:**

| Component | Weight | Notes |
|---|---|---|
| Karma (log-normalised) | 30% | `log1p(karma) / log1p(1_000_000)` |
| Account age | 20% | < 30 days = 0.10 → >= 730 days = 1.0 |
| Historical accuracy | 35% | Win-rate of past option calls (defaults to 0.5) |
| Manipulation flag | 15% | Zeroed when flagged by `ManipulationDetector` |

```python
from rot.credibility.user_reputation import UserReputationScorer

scorer = UserReputationScorer()
rep = scorer.score("wsb_user", karma=45_000, account_age_days=730, accuracy_ratio=0.62)
adjusted_confidence = scorer.apply_to_confidence(raw_confidence, "wsb_user")
```

The `ReputationStore` provides an in-process persistence layer with `upsert` / `get` / `all` operations suitable for wiring into the existing SQLite storage layer.

---

### Multi-Timeframe Signal Aggregation

`src/rot/strategy/timeframe_aggregator.py` collects signals from six timeframes and produces an alignment-aware composite score.

**Timeframe weight schema:**

| Timeframe | Weight |
|---|---|
| 1m | 0.05 |
| 5m | 0.10 |
| 15m | 0.15 |
| 1h | 0.25 |
| 4h | 0.20 |
| 1d | 0.25 |

**Alignment multipliers:** `FULL_ALIGN` (+20%), `PARTIAL_ALIGN` (+5%), `DIVERGENT` (-20%).

```python
from rot.strategy.timeframe_aggregator import TimeframeAggregator, TimeframeSignal

agg = TimeframeAggregator()
agg.add(TimeframeSignal(ticker="AAPL", timeframe="1h", signal="bullish", confidence=0.75, timestamp=...))
agg.add(TimeframeSignal(ticker="AAPL", timeframe="4h", signal="bullish", confidence=0.80, timestamp=...))
result = agg.composite_score("AAPL")
# result.alignment → TimeframeAlignment.FULL_ALIGN / PARTIAL_ALIGN / DIVERGENT
# result.score → alignment-adjusted composite confidence
```

---

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

### Security scanning (local)

```bash
# Static application security testing
bandit -r src/ --configfile pyproject.toml

# Dependency vulnerability audit
pip-audit --desc
```

### Pre-commit workflow

```bash
ruff check src/ tests/ && \
ruff format src/ tests/ && \
mypy src/rot/core/ src/rot/app/ --ignore-missing-imports && \
bandit -r src/ --configfile pyproject.toml -q && \
pytest tests/ -n auto -q --tb=short
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

## Running in Production (Docker)

### Docker Compose (recommended)

```bash
# Clone and configure
git clone https://github.com/Mattbusel/Reddit-Options-Trader-ROT-.git
cd Reddit-Options-Trader-ROT-
cp .env.example .env
# Edit .env with your credentials (see Environment Variables section)

# Start all services
docker compose up --build -d

# View logs
docker compose logs -f rot

# Stop
docker compose down
```

### Standalone Docker

```bash
docker build -t rot:latest .

docker run -d \
  --name rot \
  --restart unless-stopped \
  -p 8000:8000 \
  -v $(pwd)/data:/app/storage \
  --env-file .env \
  rot:latest
```

### Health Check

```bash
curl http://localhost:8000/api/health
# Expected: {"status":"ok","version":"1.0.0",...}
```

### Production Checklist

- Set `ROT_WEB_SECRET_KEY` to a randomly generated 32+ character string.
- Set Reddit API credentials (`ROT_REDDIT_CLIENT_ID`, `ROT_REDDIT_CLIENT_SECRET`, `ROT_REDDIT_USER_AGENT`).
- Set `ROT_LLM_API_KEY` for LLM reasoning (optional — system runs in stub mode without it).
- Mount a persistent volume at the path specified by `ROT_STORAGE_ROOT` (default: `./data`).
- Place the application behind a reverse proxy (nginx, Caddy, or Railway's built-in proxy) — never expose uvicorn directly to the internet.
- Set `ROT_ENV=production` or deploy to Railway (auto-detected) to enforce secret-key validation at startup.

---

## API Endpoints

The full interactive API reference is available at `/docs` (Swagger UI) or `/redoc` on a running server.

Key endpoint groups:

| Group | Path prefix | Description |
|---|---|---|
| Health | `/api/health` | Service health, version, uptime |
| Signals | `/api/signals` | Live and historical trade signal feed |
| Dashboard | `/dashboard` | Web UI — real-time signal stream |
| Backtesting | `/backtest` | Run and compare backtests |
| Strategy | `/strategy` | Strategy builder, ML optimizer, marketplace |
| Options Flow | `/flow` | Block/sweep/dark-pool detection |
| Macro | `/macro` | FOMC, earnings, insider activity calendar |
| Social | `/social` | Manipulation detection, author credibility |
| Auth | `/auth` | Register, login, JWT refresh, API keys |
| Billing | `/billing` | Stripe subscription management |
| Admin | `/admin` | Platform administration (admin tier only) |
| MCP | `/mcp` | Model Context Protocol server endpoint |

All API endpoints require authentication. Free-tier users have read-only access to delayed signals. Pro and above receive real-time access. See `docs/api-reference.md` for full schema documentation.

---

## API Reference

See [`docs/api-reference.md`](docs/api-reference.md) for the full endpoint catalog, or visit `/docs` on a running server for the interactive Swagger UI.

---

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for release history.

---

## License

MIT License. Copyright (c) 2026 Matthew Busel.

Third-party dependency licenses are listed in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

---

## Risk Disclaimer

**IMPORTANT — READ BEFORE USE**

ROT is a **research and educational tool only**. It is a signal intelligence platform, not a trading execution engine.

- **Nothing in this repository constitutes financial advice, investment advice, or a recommendation to buy or sell any security or derivative.**
- Options trading carries **significant financial risk**. You can lose 100% of the premium paid on options positions. Spreads and other multi-leg strategies carry their own unique risks.
- Signal quality scores, confidence levels, and trade ideas generated by this system are **experimental** and have not been independently validated for real-money trading.
- **Past signal quality does not guarantee future accuracy or profitability.** Reddit sentiment is noisy and frequently manipulated (pump-and-dump schemes, coordinated short squeezes, bot activity).
- LLM-generated reasoning is probabilistic and can be confidently wrong.
- The system does not have access to real-time options pricing, broker execution, or live market data for strike/expiry selection. All trade structures are illustrative.
- **Never risk capital you cannot afford to lose.**
- The authors and contributors accept no liability for financial losses arising from use of this software.

Use at your own risk.
