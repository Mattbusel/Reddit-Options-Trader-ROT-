# Changelog

All notable changes to Reddit Options Trader (ROT) are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added
- `ci.yml` GitHub Actions workflow: lint (ruff), type check (mypy), test matrix
  (Python 3.10 / 3.11 / 3.12), Docker build verification.
- `mypy>=1.8` added to `[project.optional-dependencies.dev]`.
- `[tool.mypy]` and `[tool.ruff.lint]` configuration sections in `pyproject.toml`.
- `[project.urls]` metadata in `pyproject.toml`.

### Changed
- `README.md` rewritten: CI/security/coverage badges, Docker + manual quickstart,
  environment variable reference table, architecture diagram, security control table,
  contributing guide, and disclaimer.
- `pyproject.toml`: version bumped to `1.0.0`; added `readme`, `license`, `authors`,
  `keywords`, `classifiers`, and `project.urls` metadata fields.
- `tests.yml`: action versions corrected from `v6` to `v4/v5`; Python matrix expanded
  to include 3.10 and 3.11 alongside 3.12.
- `security.yml`: action versions corrected from `v6` to `v4/v5`.
- `src/rot/app/loop.py`: replaced `print()` calls with structured `logging` statements.
- `src/rot/app/main.py`: replaced `print()` calls with structured `logging` statements.

---

## [0.1.0] - 2026-02-15

### Added

**Platform foundation (built 2026-02-06 through 2026-02-15)**

- **9-stage pipeline**: Reddit/RSS ingestion → Trend detection → NLP (10 modules) → Event building → Market enrichment → Credibility scoring → Feedback suppression → LLM reasoning → Trade idea generation
- **Multi-source ingestion**: PRAW Reddit streaming (r/wallstreetbets, r/stocks, r/options), RSS (13+ feeds including Reuters, SEC 8-K), StockTwits, Twitter ingest
- **NLP engine** (10 modules): polarity, intensity, conviction, sarcasm, classification, temporal, actionability, urgency, entity, thread analysis. 500+ lexicon entries.
- **Ticker extraction**: `$TSLA`, bare `TSLA`, multi-ticker posts. Alias normalisation, aggressive noise filtering.
- **Market enrichment**: yfinance with local TTL cache. Price, market cap, volume, IV context.
- **Credibility scorer**: GradientBoosting ML + 12 heuristic factors. DD flair bonus, engagement quality, cross-post penalties.
- **LLM reasoning**: Provider-agnostic (OpenAI, Anthropic, DeepSeek). Circuit breaker: auto-disables after 3 failures, stub fallback, per-success reset.
- **Trade idea generation**: Bull call spreads, bear put spreads, straddles. ATM ±5% strike selection, weekly/monthly expiry heuristics, max-loss calculation.
- **Feedback suppression loop**: Adaptive signal suppression based on rolling win-rate by event_type and source.
- **Web dashboard**: FastAPI + Jinja2. WebSocket real-time feed, confidence bars, stance badges, signal detail pages.
- **Authentication**: JWT + API Key + Session Cookie. 5-tier hierarchy (Free → Pro → Premium → Ultra → Enterprise) + Admin. 35+ gate functions.
- **Security**: CSP nonce, nh3 Rust sanitiser, CSRF ASGI middleware, 6/6 security headers, database-backed rate limiting, brute-force protection.
- **Alerts**: Discord webhooks, email (Resend + SMTP fallback), Twitter. HMAC-SHA256 signed webhooks.
- **Database**: SQLite via aiosqlite. 33+ tables, 16 DB mixins (231 methods). WAL mode, automated migrations.
- **Backtesting engine**: Monte Carlo simulation, walk-forward optimisation, 12 modules.
- **Strategy builder**: Rule-based, ML optimiser, genetic algorithms, regime detection, marketplace.
- **Social intelligence**: Manipulation detection, bot detection, pump-dump patterns, coordination tracking, author credibility.
- **Options flow**: Block/sweep/dark pool detection, IV analysis, Greek calculations.
- **Macro events**: FOMC calendar, earnings tracking, seasonal patterns, insider activity (SEC EDGAR).
- **Gamification**: Badges, leaderboards, progression system.
- **Enterprise export**: 9-step data lineage, scheduled exports, analytics.
- **MCP server**: Model Context Protocol integration for agent-based access.
- **Paper trading**: Portfolio simulation with leaderboard.
- **Control plane**: Live config tuning, telemetry bus, anomaly detector, helix config.
- **Query cache**: Async TTL with thundering-herd prevention (per-key locks).
- **Docker**: Multi-stage build, non-root `gosu` entrypoint, volume permission handling.
- **CI/CD**: Pytest on every push with 75% coverage floor. 5 security scanners (CodeQL, Bandit, pip-audit, TruffleHog, Dependabot).

### Security

- Resolved 425 CodeQL alerts prior to initial release.
- All dependencies pinned to exact versions with CVE audit trail in `pyproject.toml`.
- `cryptography` CVE patched within hours of enabling dependency pinning.
- `python-jose` version locked to address known JOSE vulnerabilities.

### Fixed

- Serialisation bug: `Evidence` dataclass objects were silently failing to store, dropping 100% of signals.
- Ghost endpoint: duplicate health check routes where minimal route shadowed comprehensive one.
- Tier gate design assumption corrected to match actual product behaviour.

---

*Earlier development history predates this changelog. See git log for full commit history.*
