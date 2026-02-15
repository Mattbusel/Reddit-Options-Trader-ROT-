# Reddit Options Trader (ROT)

**A 165K-line financial intelligence platform that turns Reddit into structured options trade ideas. Built solo in 9 days.**


[![Security: 0 alerts](https://img.shields.io/badge/security%20alerts-0-brightgreen)]()
[![Tests: 6,916](https://img.shields.io/badge/tests-6%2C916-blue)]()
[![Test Ratio: 1.57:1](https://img.shields.io/badge/test%3Aproduction-1.57%3A1-blue)]()


---

## What Is This

ROT is a full-stack signal intelligence platform. It monitors Reddit in real time, detects emerging market events, extracts and validates tickers, enriches them with market data, scores credibility, reasons about conviction, and generates structured options trade ideas — complete with strike selection, expiry heuristics, and risk parameters.

This is not a trading bot. ROT is the intelligence layer that surfaces what matters before price fully reacts.

**Live deployment:** [rot.up.railway.app](https://rot.up.railway.app)

---

## The Numbers

```
CODEBASE
──────────────────────────────────────
Production Code:     58,869 lines  │  230 files
Test Code:           92,182 lines  │  201 files
Templates:           14,318 lines  │   64 files
Total Python:       151,116 lines  │  431 files
Grand Total:       ~165,000+ lines │  564 files

TESTING
──────────────────────────────────────
Test Functions:       6,916  (5,063 sync + 1,853 async)
Test-to-Prod Ratio:  1.57:1
External API Calls:  0  (fully mocked)
CI:                  Pytest on every push, 75% coverage floor

SECURITY
──────────────────────────────────────
CodeQL Alerts:         0  (425 fixed)
Dependabot Alerts:     0
Open CVEs:             0
TODO/FIXME Comments:   0
Bare except: pass:     0
Hardcoded Secrets:     0
Security Scanners:     5  (CodeQL, Bandit, pip-audit, TruffleHog, Dependabot)

INFRASTRUCTURE
──────────────────────────────────────
Database Tables:      33+
API Endpoints:       100+
Tier Gates:           35+
NLP Modules:          10
Background Loops:      8
Pipeline Stages:       9
```

---

## Why This Exists

In January 2026, Intercontinental Exchange — the $98.8B company that owns the NYSE — launched "Reddit Signals and Sentiment," selling structured Reddit market data to institutional investors.

ROT does the same thing for everyone else. ICE sells raw data feeds to hedge funds at institutional prices. ROT is the complete platform — ingestion, analysis, trade ideas, dashboard, alerts — at retail scale.

---

## Architecture

### 9-Stage Pipeline

```
Reddit/RSS → Trend Detection → NLP (10 modules) → Event Building → Market Enrichment
    → Credibility Scoring → Feedback Suppression → LLM Reasoning → Trade Ideas
```

Every stage runs continuously. Memory-bounded dedup (max 2,000). Circuit breaker on LLM (auto-disables after 3 failures, stub fallback). Full pipeline executes in seconds.

### Security (Grade: A)

Independently audited at **A (93-95/100)** across two separate assessments.

- **Authentication:** JWT + API Key + Session Cookie (3 methods)
- **Authorization:** 5-tier hierarchy (Free → Pro → Premium → Ultra → Enterprise) + Admin. 35+ gate functions.
- **SQL Injection:** 100% parameterized queries. Field whitelist for dynamic updates.
- **XSS Prevention:** 3-layer defense — Jinja2 autoescape + nh3 Rust sanitizer + nonce-based CSP
- **CSRF:** Custom ASGI middleware with timing-safe HMAC comparison
- **Security Headers:** 6/6 — CSP, X-Frame-Options: DENY, nosniff, Referrer-Policy, Permissions-Policy, X-XSS-Protection
- **Rate Limiting:** Database-backed, multi-instance safe. Per-tier daily + burst limits. Brute-force protection.
- **Security Logging:** 10 SIEM-ready JSON event types. Global sanitizing filter. Request ID correlation.
- **CI/CD:** 5 automated scanners on every push — CodeQL, Bandit, pip-audit, TruffleHog, Dependabot

### Test Suite

1.57:1 test-to-production ratio — more test code than production code.

6,916 tests across 201 files. Zero external API calls (everything mocked). Runs in CI on every push with coverage enforcement.

**What the tests have found:**
- A ghost endpoint — two health check routes existed, the minimal one shadowed the comprehensive one
- A tier gate design assumption that didn't match actual product behavior
- A CVE in `cryptography` caught and patched within hours of enabling dependency pinning
- A known pytest `caplog` fixture isolation issue triggered by extreme test density (23 tests for a single security logger module)
- A serialization bug where `Evidence` dataclass objects were silently failing to store, dropping 100% of signals

### Key Design Patterns

| Pattern | Implementation |
|---------|---------------|
| **Pipeline Orchestration** | 9-stage DAG with dedup and filtering |
| **Circuit Breaker** | LLM disabled after 3 failures, stub fallback, auto-recovery |
| **Mixin Composition** | 16 DB mixins (231 methods) vs monolithic file |
| **Dual-Path NLP** | Custom 10-module engine with regex fallback |
| **Query Cache** | Async TTL with thundering-herd prevention (per-key locks) |
| **Tier Gating** | Returns dicts of flags, not exceptions. Admin bypasses all. |
| **Non-root Docker** | gosu-based entrypoint with volume permission handling |

---

## Core Capabilities

### Real-Time Ingestion
- **Reddit:** PRAW streaming from r/wallstreetbets, r/stocks (hot, new, rising, top)
- **RSS:** 13+ feeds including Reuters Business, SEC 8-K filings
- Deduplication, freshness gating, persistence across restarts

### Trend Detection
Momentum-based, not mention-based. Score velocity, comment velocity, engagement acceleration. Emits `TrendCandidate` objects when thresholds are exceeded.

### Ticker Extraction & Validation
- `$TSLA`, bare `TSLA`, multi-ticker posts
- Aggressive filtering: macro noise, non-equities, slang, delisted symbols
- Alias normalization (`SPXW` → `^GSPC`, `TSMC` → `TSM`)

### Market Enrichment
Live data via yfinance with local caching. Price, market cap, volume, IV context.

### Event Classification
Event types (earnings, squeeze, regulatory, product, macro), sentiment detection (bullish/bearish/mixed), time horizon inference (intraday through earnings window).

### Credibility Scoring
ML scorer (GradientBoosting) + 12 heuristic factors. DD flair bonus, engagement quality, cross-post penalties, ticker focus, text depth. Transparent score breakdown.

### LLM Reasoning (Optional)
Provider-agnostic — OpenAI, Anthropic, DeepSeek. Thesis synthesis, risk identification, context expansion. Circuit breaker with safe fallback.

### Trade Idea Generation
Bull call spreads, bear put spreads, straddles. ATM ± 5% strike selection, weekly/monthly expiry heuristics, max loss calculation, quality scoring. Market cap and data availability gates.

### Web Dashboard
FastAPI + Jinja2. Real-time signal feed (WebSockets), confidence bars, stance badges, trending tickers, signal detail pages with full reasoning and trade structure. Dark theme.

### Alerts
Discord webhooks, email, Twitter. High-confidence signals only. Rich embeds with ticker, stance, confidence, strategy, option legs, risks, catalyst window.

### Additional Systems
- **Backtesting Engine:** Monte Carlo simulation, walk-forward optimization, 12 modules
- **Strategy Builder:** Rule-based, ML optimizer, genetic algorithms, regime detection, marketplace
- **Social Intelligence:** Manipulation detection, bot detection, pump-dump patterns, coordination tracking
- **Options Flow:** Block/sweep/dark pool detection, IV analysis, Greek calculations
- **Macro Events:** FOMC calendar, earnings tracking, seasonal patterns, insider activity
- **Gamification:** Badges, leaderboards, progression system
- **Enterprise Export:** 9-step data lineage, scheduled exports, analytics

---

## Project Structure

```
src/rot/
├── app/          # Server, pipeline runner, background loops
├── ingest/       # Reddit + RSS ingestion (7 modules)
├── trend/        # Trend detection and ranking
├── nlp/          # 10-module NLP pipeline (500+ lexicon)
├── extract/      # Event builder (dual-path NLP/regex)
├── market/       # Trade builder, enrichment, validation
├── credibility/  # ML scorer + 12 heuristics
├── reasoner/     # LLM reasoning with circuit breaker
├── storage/      # 33+ tables, 16 DB mixins, migrations
├── web/          # FastAPI routes, auth, middleware, templates
├── strategy/     # ML, genetic, regime, marketplace
├── social/       # Manipulation, propagation, network analysis
├── flow/         # Options flow intelligence, Greeks
├── backtest/     # Monte Carlo, walk-forward, 12 modules
├── macro/        # FOMC, earnings, seasonal, insider
├── alerts/       # Discord, email, Twitter, webhook dispatch
├── agents/       # Autonomous trading agents (safety rails)
├── gamification/ # Badges, leaderboards, progression
├── export/       # Enterprise exports, 9-step lineage
├── core/         # Config, types, logging, sanitization
└── ...           # + affiliates, sports, integrations, analysis

tests/            # 201 files, 92,182 lines, 6,916 test functions
templates/        # 64 Jinja2 templates
docs/             # 17 documentation files
```

---

## Setup

```bash
# 1. Clone
git clone https://github.com/Mattbusel/Reddit-Options-Trader-ROT-.git
cd Reddit-Options-Trader-ROT-

# 2. Configure
cp .env.example .env
# Fill in: Reddit API credentials, optional LLM API key

# 3. Install
pip install -e ".[dev]"

# 4. Run
python -m rot.app.server
# Dashboard: http://localhost:8000/dashboard
# API docs:  http://localhost:8000/docs

# 5. Test
pytest tests/ -v
```

---

## Audit Results

Two independent AI-assisted audits, both scoring **A overall**:

| Dimension | Score |
|-----------|-------|
| Security | A to A+ (93-98/100) |
| Architecture | A (95/100) |
| Code Quality | A (94/100) |
| Test Suite | A (92-95/100) |
| Dependencies | A to A+ |
| Documentation | A- to A |
| **Overall** | **A (93-95/100)** |

Zero open recommendations. All P0, P1, P2, and P3 items from both audits have been closed.

Full audit reports available in [`docs/`](docs/).

---

## Disclaimer

This project is for research and experimentation only. Nothing in this repository constitutes financial advice. ROT is a signal intelligence platform, not an execution engine.

---






