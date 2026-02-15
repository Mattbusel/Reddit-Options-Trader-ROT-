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
├── core/           config.py (Settings), types.py (Post,Event,TradeIdea...), logging.py, sanitize.py (nh3 XSS)
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
    ├── security_headers.py  CSP + X-Frame-Options + 4 more headers on all responses
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
| 2026-02-14 | **CodeQL zero-alert baseline**: Fixed all 425 code scanning alerts (0 open). Added code quality guardrails, SECURITY.md policy. See `SECURITY.md` for full policy. |
| 2026-02-15 | **Final security hardening**: Pinned 11 security-critical deps to exact versions, added `SecurityHeadersMiddleware` (CSP + 5 headers), `sanitize.py` (nh3 HTML sanitizer), hardened Stripe webhook (empty-secret guard + IP logging). Bumped cryptography 46.0.4→46.0.5 (CVE-2026-26007). 0 Dependabot alerts. 39 new tests. |

---

## Code Quality Guardrails

> **MANDATORY**: Every line of code produced by Claude or any agent MUST comply with these rules.
> These guardrails were derived from analysis of 425 CodeQL alerts fixed during the Feb 2026 hardening.
> See `SECURITY.md` for the full security policy.

### Root Cause Analysis (why we had 425 alerts)

| Category | % of Alerts | Root Cause | Prevention |
|----------|-------------|------------|------------|
| Unused imports | 40% | Refactoring removed usage but left import lines | Clean imports on every edit |
| Unused variables | 30% | Copy-paste, cascading dead code after edits | Verify every assigned variable is read |
| Empty except blocks | 7% | Silencing errors during rapid prototyping | Always log or re-raise |
| Comparison warnings | 5% | `x == x` identity checks, redundant conditions | Review boolean logic |
| Cyclic imports | 5% | `__init__.py` re-exports creating import cycles | Use `TYPE_CHECKING` guard |
| Info exposure | 2% | Stack traces / secrets in error responses | Sanitize all user-facing errors |
| Weak hashing | 1.5% | SHA1 in OAuth, SHA256 for API keys | Document protocol requirements |
| NaN comparisons | 0.5% | `x != x` to detect NaN | Use `math.isnan()` |

### Import Rules

1. **Only import what you use.** After ANY edit, verify every imported name appears in the file body.
2. **Remove the name, not the line.** If `from typing import Any, Dict, List` and only `Any` is unused, edit to `from typing import Dict, List`. Do NOT delete the whole line.
3. **`from __future__ import annotations`** makes all type annotations strings at runtime. CodeQL still tracks whether a typing name is used in annotations. Only import typing names that actually appear somewhere.
4. **After removing code that used an import**, check if the import is now orphaned. Cascading dead imports are the #1 source of alerts.
5. **Use `TYPE_CHECKING` for circular imports**: `if TYPE_CHECKING: from rot.foo import Bar` keeps the import out of runtime.

### Variable Rules

6. **Every assigned variable must be read.** If you assign `x = foo()` but never reference `x`, either use it or call `foo()` as a bare expression.
7. **Side-effect-only calls**: For auth guards and similar, use bare `await require_tier("pro")(request)` NOT `_user = await require_tier("pro")(request)`. The `_` prefix does NOT satisfy CodeQL.
8. **After removing code that read a variable**, check if the assignment is now dead. Cascading dead variables are the #2 source of alerts.
9. **No redundant initializations**: If every branch of an if/elif/else assigns a variable, do not initialize it before the block.

### Exception Handling Rules

10. **Never use bare `except: pass`**. Always either `log.error(...)` or re-raise with context.
11. **Catch specific exceptions**: `except ValueError` not `except Exception` unless you genuinely handle all exceptions.
12. **Swallowed exceptions must be logged**: At minimum `log.debug("...", exc_info=True)`.

### Security Rules

13. **Never expose stack traces to users.** Return generic error messages; log the full trace server-side.
14. **Hash passwords with bcrypt only.** SHA-256 is acceptable for high-entropy API tokens. SHA-1 only for protocol-mandated OAuth 1.0a (document with a code comment).
15. **Sanitize all log output.** Use `SanitizingLogFilter` (already global). Never log raw user input without it.
16. **Validate at system boundaries.** Validate user input, external API responses, and config values. Trust internal code.

### Comparison and Logic Rules

17. **Never compare a value to itself** (`x == x`, `x != x`). Use `math.isnan(x)` for NaN checks.
18. **No redundant boolean conditions.** If both branches of `if x > 0` and `elif x > 0` are identical, consolidate.
19. **Floating point**: Use `math.isclose()` for float equality, `math.isnan()` for NaN detection.

### Pre-Commit Checklist (mental, before every commit)

- [ ] All imports are used (grep each imported name in the file)
- [ ] All assigned variables are read downstream
- [ ] No bare `except: pass` blocks
- [ ] No secrets or stack traces in user-facing responses
- [ ] No `x == x` or `x != x` comparisons
- [ ] Tests pass (`pytest -x`)
