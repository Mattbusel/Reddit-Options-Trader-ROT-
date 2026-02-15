# CLAUDE.md — ROT (Reddit Options Trader)

> **UPDATE RULE**: Any agent modifying features, modules, routes, tables, or config MUST update
> this doc AND the relevant `docs/*.md` file before the task is complete.

## Quick Reference

| Key | Value |
|-----|-------|
| **Stack** | Python 3.12, FastAPI, Jinja2, Tailwind CSS, Chart.js, HTMX, aiosqlite, PRAW |
| **Entry** | `python -m rot.app.server` (web+pipeline), `python -m rot.app.main` (one-shot) |
| **Layout** | `src/rot/` (setuptools src-layout), `tests/` (~2048+ pytest tests) |
| **Config** | `ROT_*` env vars via Pydantic Settings (`src/rot/core/config.py`) |
| **DB** | SQLite + aiosqlite (WAL mode), 33+ tables (`src/rot/storage/database.py`) |
| **Deploy** | Railway (Docker, `/app/data` persistent volume) |

## Detailed Docs (read on-demand, NOT auto-loaded)

| Doc | Contents |
|-----|----------|
| `docs/architecture.md` | Pipeline stages, design patterns, key decisions |
| `docs/database.md` | Full schema (33+ tables), SQL helpers, migrations |
| `docs/web-layer.md` | All 100+ routes, auth, tier gating (35+ gates) |
| `docs/nlp-engine.md` | Custom 10-module NLP pipeline, lexicon, sarcasm rules |
| `docs/config.md` | All `ROT_*` env vars with defaults |
| `docs/testing.md` | Test patterns, file inventory |
| `docs/deployment.md` | Docker, Railway, dependencies |
| `docs/types.md` | All dataclass definitions |
| `docs/features/backtest.md` | Backtesting engine (12 modules) |
| `docs/features/unusual-activity.md` | Unusual options activity detection |
| `docs/features/sector-rotation.md` | Sector analysis & rotation |
| `docs/features/correlations.md` | Correlation engine |
| `docs/features/enterprise.md` | Enterprise data pipeline & exports |
| `docs/features/feedback.md` | Feedback engine & signal suppressor |
| `docs/features/credibility.md` | ML + heuristic credibility scoring |
| `docs/features/terminal.md` | Bloomberg-lite terminal |
| `docs/features/agents.md` | Autonomous trading agents |
| `docs/features/flow-intelligence.md` | Options flow intelligence (Greeks, detection, convergence) |
| `docs/features/social-intelligence.md` | Social intelligence (author tracking, manipulation, propagation) |
| `docs/features/strategy-builder.md` | Strategy builder (rules, ML, genetic, marketplace) |
| `docs/agent-map.compact` | Token-efficient symbol→import map |

## Pipeline Flow (9 stages)

```
Ingestion → Trend Detection → NLP Analysis → Event Building
→ Market Enrichment → Credibility Scoring → Adaptive Suppression
→ LLM Reasoning → Trade Building → Storage + Delivery
```

Orchestrated by `PipelineRunner` in `src/rot/app/runner.py`.

## Module Map

```
src/rot/
├── core/           config.py (Settings), types.py (Post,Event,TradeIdea...), logging.py
├── ingest/         reddit, rss (13+ feeds), stocktwits, twitter, multi_ingestor, seen_store
├── trend/          trend_engine, trend_store, ranker, ticker_ranker
├── nlp/            10-module custom NLP: tokenizer, lexicon(500+), sentiment, entities,
│                   classifier(14 categories), temporal, thread, engine → NLPResult
├── extract/        event_builder (dual-path NLP/legacy), enricher (blocklists, aliases)
├── credibility/    scorer (12 heuristic factors), ml_scorer (GradientBoosting, 32 features),
│                   features.py, train.py (live retrain from DB)
├── feedback/       analyzer (category perf, suppression candidates), suppressor (Stage 6.5)
├── reasoner/       reasoner (LLM+circuit breaker), llm_client (OpenAI/Anthropic/DeepSeek),
│                   prompts, parser, ai_summary
├── market/         trade_builder (IV-aware, 6 strategies), enricher (yfinance), symbol_validator,
│                   price_checker, gates
├── backtest/       12 modules: config, result, metrics, engine, monte_carlo, risk,
│                   walk_forward, optimizer, benchmark, comparator, report
├── unusual/        types, detector (IV/volume/OI/skew/sweep), history (rolling baselines)
├── analysis/       sector.py (rotation, momentum, flow), correlations.py (co-fire, clustering,
│                   lead-lag, network)
├── macro/          7 modules: calendar (13 event types), earnings, insider (SEC EDGAR),
│                   fomc (hawk/dove), seasonal, impact
├── export/         scheduler (recurring exports), lineage (9-step provenance)
├── agents/         types, rules (9 operators, AND/OR), engine (safety rails, paper trading)
├── flow/           7 modules: greeks (Black-Scholes), detector (block/sweep/dark pool),
│                   patterns, history, convergence (flow-social cross-ref)
├── social/         7 modules: tracker (author accuracy), manipulation (bot/pump-dump),
│                   propagation, network (clustering), confidence (pipeline plugin)
├── strategy/       9 modules: rules (7 operators), discovery, ml_optimizer (52 features),
│                   regime (bull/bear/sideways/volatile/crisis), genetic, auto_trader, marketplace
├── storage/        database.py — aiosqlite, 33+ tables, migrations, signal_archive, unified CTE
├── alerts/         dispatcher, discord, email (Resend+SMTP), twitter, webhook
├── app/            main.py, loop.py, runner.py (PipelineRunner), server.py (FastAPI factory)
└── web/
    ├── auth.py         JWT + API key + session cookie, admin tier elevation
    ├── query_cache.py  Async TTL cache (thundering-herd, prefix invalidation)
    ├── tier_gate.py    5 tiers (Free→Pro→Premium→Ultra→Enterprise) + admin, 35+ gates
    ├── rate_limit.py   Per-tier API rate limiting
    ├── routes/         40+ route files, 100+ endpoints (see docs/web-layer.md)
    └── templates/      46+ Jinja2 HTML templates
```

## Key Patterns

- **Dual-path NLP/Legacy**: EventBuilder uses NLP engine if available, falls back to regex
- **ML/Heuristic credibility**: ML scorer (GradientBoosting) with heuristic fallback, both scores in `meta["ml_credibility"]`
- **Circuit breaker**: Reasoner disables LLM after 3 consecutive failures → stub reasoning
- **Tier gating**: Gate functions return dicts of flags, not exceptions. Admin tier bypasses all.
- **JSON blob storage**: Complex nested data stored as JSON text in SQLite columns
- **Signal archive**: `signal_archive` table + `_UNIFIED_CTE` enables analytics across live+archived data
- **Background loops**: Unusual (5m), Flow (5m), Manipulation (30m), Author resolution (1h), Export (1h), Regime (1h), Strategy health (6h), Feedback (6h), Macro (1h)
- **Query cache**: 10 dashboard queries cached with TTL (30s-300s), thundering-herd prevention
- **Win/loss**: Only bullish/bearish signals count as trades. Mixed/unknown = neutral.
- **Informational sources**: FDA/DoD/pharma feeds skip LLM reasoning + trade building

## Tier Hierarchy

```
Free → Pro → Premium → Ultra → Enterprise → Admin (hidden master, ROT_AUTH_ADMIN_EMAILS)
```

Free: 15min delay, 10 signals, no API. Pro: real-time, basic features, 1000 API/day.
Premium: advanced analytics, 5000 API/day. Ultra: full access, 25000 API/day.
Enterprise: data licensing, webhooks, 100000 API/day. Admin: everything, unlimited.

## Testing

```bash
pytest                          # all tests
pytest tests/test_database.py   # specific file
pytest -x                       # stop on first failure
```

Pattern: pytest-asyncio (auto mode), temp SQLite files, no external API calls (mocked).

## Change Log

| Date | Change |
|------|--------|
| 2025 | Initial creation, dashboard query cache |
| 2026-02 | ML credibility, feedback engine, backtesting (12 modules), unusual activity, sector rotation, correlations, enterprise export, signal archive, macro events (7 modules), terminal, agents, admin tier, flow intelligence (7 modules), social intelligence (7 modules), strategy builder (9 modules). Memory/network optimization. Simplified win/loss counting. Doc restructuring (17 split docs). ~2048 tests. |
| 2026-02 | **Token optimization**: Slimmed CLAUDE.md from ~24.7k to ~3k tokens. Detailed content moved to `docs/` (read on-demand). Added MEMORY.md for cross-session learnings. |
| 2026-02-14 | **Nightly hardening (82% complete)**: WS1 (security): Strong secret key validation, fixed auth rate limiting for multi-instance (database-backed), database backup system (GZip, rotation), enhanced health check endpoint. WS2 (tech debt): Removed database_old.py, fixed reasoning type bug in analytics. WS3 (retry logic): Comprehensive retry module with exponential backoff applied to yfinance, LLM APIs, RSS/StockTwits/Twitter fetches. WS4 (automation): GitHub Actions security workflow (pip-audit, CodeQL, Bandit, TruffleHog), Dependabot config. WS5 (performance): SQLite pragma optimizations (16MB cache, 128MB mmap, 4 threads), GZip compression level tuning. WS7 (integration tests): 4 test suites (1,400+ lines) covering auth rate limiting, retry resilience, backup system, health endpoint. WS8 (logging): Structured JSON security logging (10 event types, SIEM-ready) + request ID tracking across pipeline (UUID4, correlation IDs, distributed tracing, response timing). WS9 (API docs): Enhanced OpenAPI schema with Pydantic models, response examples, tier documentation, auto-generated Swagger UI at /docs. WS10 (frontend): Professional loading states, skeleton loaders, HTMX integration, shimmer animations. **Total: 9/11 work streams, 5,200+ lines added, 19 files created, 3 critical bugs fixed**. |
