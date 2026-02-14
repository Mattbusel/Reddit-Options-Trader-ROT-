<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Architecture & Pipeline — ROT

> See [CLAUDE.md](../CLAUDE.md) for full index.

## Quick Start

| Key | Value |
|-----|-------|
| Pipeline orchestrator | `src/rot/app/runner.py` |
| FastAPI factory | `src/rot/app/server.py` |
| Pattern | 9-stage pipeline, dual-path NLP/legacy, provider-agnostic LLM, multi-level dedup |
| Entry points | `server` (web+pipeline), `main` (one-shot), `loop` (continuous) — all via `python -m rot.app.<name>` |

## Pipeline: 9 Stages

```
Ingestion -> Trend -> NLP/Entity -> Event Build -> Market Enrich -> Credibility -> Suppression -> LLM -> Trade Build -> Store+Deliver
```

### 1. Ingestion (`src/rot/ingest/`)

| Component | Source |
|-----------|--------|
| `RedditIngestor` | PRAW subreddit polls -> `ThreadSnapshot` |
| `RSSIngestor` | 13+ feeds (MarketWatch, FDA, DoD, Fed, SeekingAlpha, etc.) |
| `StockTwitsIngestor` | Symbol streams + trending |
| `TwitterIngestor` | Cashtags + accounts via API v2 |
| `MultiSourceIngestor` | Aggregates all above |
| `SeenStore` | JSON dedup, 5000 entry cap |

### 2. Trend Detection (`src/rot/trend/`)

`TrendEngine.detect(snapshots)` -> `List[TrendCandidate]`. Sliding window (1800s default), score+comment velocity. RSS/StockTwits/Twitter bypass threshold. `TrendStore` persists state as JSON. Produces top-N overall + top-N per-ticker.

### 3. Entity Extraction (`src/rot/nlp/engine.py` or `event_builder.py`)

- **NLP**: tokenize -> resolve entities (cashtags, bare tickers, implicit refs, sector expansion)
- **Legacy**: regex `$TICKER` + bare uppercase + blocklist

### 4. Event Building (`src/rot/extract/event_builder.py`)

`EventBuilder(nlp_engine=...)` — dual-path NLP/legacy. Produces `Event` with type, stance, horizon, confidence, entities, evidence, meta (carries NLP data, post metadata, trend features).

### 5. Market Enrichment (`src/rot/market/`)

| Component | Purpose |
|-----------|---------|
| `SymbolValidator` | yfinance validation, 1000-entry cache |
| `MarketEnricher` | Last close, 1d change, market cap, ATM IV, put/call OI ratio |
| `PriceChecker` | Periodic price tracking for performance measurement |

Options chain: only when `enable_options_chain=True` (off by default).

### 6. Credibility Scoring (`src/rot/credibility/`)

**ML path (default):** `MLCredibilityScorer` — GradientBoostingClassifier, P(win) from 32 features, live retrain every 24h, hot-reload.
**Heuristic fallback:** `CredibilityScorer` — 12 factors (always runs for A/B comparison in `meta["ml_credibility"]`).
**Training:** `train.py` — queries win/loss outcomes, 5-fold CV, needs 100+ signals (30+ per class).
**Result:** `event.confidence` = ML P(win) [0.05, 0.95] or heuristic-adjusted [0.05, 1.0].

#### Heuristic Factors

| # | Factor | Adj | Condition |
|---|--------|-----|-----------|
| 0 | institutional_rss | +.15 | FDA/DoD/Fed/SEC RSS |
| 0b | news_rss | +.05 | Other RSS |
| 1 | dd_flair | +.15 | DD flair + body>=200 |
| 1b | dd_flair_shallow | +.05 | DD flair + short body |
| 1c | quality_flair | +.05 | Discussion/TA/Fundamentals |
| 2 | too_many_tickers | -.15 | 5+ entities |
| 2b | focused_ticker | +.05 | Exactly 1 entity |
| 3 | crosspost_penalty | -.10 | Is crosspost |
| 4 | high_score | +.05 | Score > 100 |
| 4b | controversial | -.05 | Upvote ratio < 0.6 |
| 5 | high_discussion | +.05 | Comments > score*0.5 |
| 6 | has_body_analysis | +.05 | Body > 100 chars |
| 7 | subreddit_boost | +.05 | options/thetagang/investing/valueinvesting |
| 7b | subreddit_penalty | -.05/-.10 | wsb/shortsqueeze/pennystocks |
| 8a | author_high_karma | +.10 | Karma >= 50K |
| 8b | author_good_karma | +.05 | Karma >= 10K |
| 8c | author_low_karma | -.10 | Karma < 100 |
| 8d | author_established | +.05 | Age >= 365d |
| 8e | author_new_account | -.10 | Age < 30d |
| 9 | nlp_sarcasm_penalty | 0 to -.15 | Sarcasm prob > 0.5 |
| 10a | nlp_high_conviction | +.05 | Conviction > 0.7 |
| 10b | nlp_low_conviction | -.05 | Conviction < 0.3 |
| 11a | nlp_strong_consensus | +.10 | Consensus > 0.7 |
| 11b | nlp_moderate_consensus | +.05 | Consensus > 0.5 |
| 11c | nlp_contrarian_flag | -.05 | Contrarian detected |
| 12 | nlp_low_actionability | -.10 | Actionability < 0.3 |

### 6.5 Adaptive Suppression (`src/rot/feedback/suppressor.py`)

`SignalSuppressor.apply(event)` -> `(Event, was_suppressed)`. Reads precomputed `FeedbackAnalyzer._last_analysis` (GIL-safe).

| Rule | Threshold |
|------|-----------|
| Category suppression | event_type win_rate < 20%, 30+ signals |
| Source suppression | (event_type, subreddit) win_rate < 15%, 30+ signals |
| Low-confidence + poor category | confidence < 0.3 AND event_type in suppression candidates |

Suppressed: stub ReasoningPacket + no-trade, skip LLM/trade build, stored with `meta["suppressed"]=True`. Disabled until first `FeedbackAnalyzer.run_analysis()` completes.

### 7. LLM Reasoning (`src/rot/reasoner/`)

`Reasoner.reason(event)` -> `ReasoningPacket`. Circuit breaker after 3 failures -> stub fallback. Informational-only sources (FDA/DoD/pharma) skip LLM -> stub with confidence=0.

**Confidence calibration:**

| Range | Level |
|-------|-------|
| .10-.25 | Speculative |
| .25-.40 | Some reasoning, unverified |
| .40-.55 | Solid thesis + real data |
| .55-.70 | Strong + market confirmation |
| .70-.85 | Multi-source corroboration |
| .85-1.0 | Officially confirmed |

Caps: squeeze_chatter max .65, all others max .85 unless confirmed. WSB/shortsqueeze/pennystocks: -.05/-.10. RSS: +.05/+.10. Market contradiction: -.10/-.20.

### 8. Trade Building (`src/rot/market/trade_builder.py`)

`TradeBuilder.build(packet, event)` -> `List[TradeIdea]`. IV-aware: high IV (>50%) -> credit spreads/iron condors; low IV -> debit spreads/straddles. Gates: min volume, min OI, max bid-ask spread, min market cap ($100M). Quality score 0-1.

### 9. Storage & Delivery (`src/rot/storage/database.py`, `src/rot/alerts/`)

Signal -> SQLite `signals` table (metadata as JSON blobs). `on_signal` callback: WebSocket, Discord webhook, email (digest+realtime), Twitter/X, custom webhooks (Enterprise). JSONL audit trail.

## Module Map

| Module | Files | Purpose |
|--------|-------|---------|
| `core/` | config, types, logging | Settings, dataclasses, JSONL |
| `ingest/` | reddit, rss, stocktwits, twitter, multi, seen_store | Multi-source ingestion |
| `trend/` | engine, store, ranker, ticker_ranker | Sliding window trend detection |
| `nlp/` | 10 modules ([detail](nlp-engine.md)) | Custom financial NLP |
| `extract/` | event_builder, enricher | Dual-path event extraction |
| `credibility/` | scorer, ml_scorer, features, train | ML+heuristic scoring |
| `feedback/` | analyzer, suppressor | Feedback analysis + suppression |
| `reasoner/` | reasoner, llm_client, prompts, parser, ai_summary | LLM + circuit breaker |
| `market/` | trade_builder, enricher, symbol_validator, price_checker, gates | Market data + trades |
| `backtest/` | 12 modules | Backtesting engine |
| `unusual/` | 4 modules | Unusual activity detection |
| `analysis/` | 5 modules | Sector rotation + correlations |
| `export/` | 4 modules | Enterprise pipeline + lineage |
| `macro/` | 7 modules | Economic calendar + events |
| `agents/` | 4 modules | Autonomous trading agents |
| `flow/` | 7 modules | Options flow intelligence |
| `social/` | 7 modules | Social intel network |
| `strategy/` | 9 modules | Strategy builder + ML optimizer |
| `storage/` | database | aiosqlite, 33+ tables, migrations |
| `alerts/` | dispatcher, discord, email, twitter, webhook | Multi-channel delivery |
| `app/` | main, loop, runner, server | Entry points + orchestration |
| `web/` | auth, query_cache, tier_gate, rate_limit, routes/, templates/ | Web layer ([detail](web-layer.md)) |

## Design Patterns

### Dual-Path NLP/Legacy
```python
# EventBuilder falls back to legacy regex if nlp_engine is None or fails
EventBuilder(nlp_engine=NLPEngine())  # NLP path
EventBuilder()                        # legacy regex path
```

### Provider-Agnostic LLM
`LLMClient(provider=, api_key=, model=)` — supports openai/anthropic/deepseek. Switch via `ROT_LLM_PROVIDER` + `ROT_LLM_API_KEY`.

### Circuit Breaker
3 consecutive LLM failures -> auto-switch to stub reasoning. Prevents cascading failures.

### Informational-Only Sources
FDA/DoD/pharma RSS: skip LLM+trade building, still stored for news feed/dashboard.

### Multi-Level Dedup

| Level | Mechanism | Scope |
|-------|-----------|-------|
| 1 | SeenStore | Post-level, JSON file, 5000 cap |
| 2 | Runner | (post_url, ticker) in-memory, clears at 2K |
| 3 | DB index | (post_url, ticker, created_at) unique |

### ML/Heuristic Dual-Path
ML scorer always runs heuristic internally. Falls back when no model. Both in `meta["ml_credibility"]` for A/B. Hot-reloads after retrain.

### Tier Gating
Gate functions return dicts of bool/numeric flags (not exceptions): `gate_chart_access(tier)["has_quadrant"]`.

### JSON Blob Storage
Complex nested data stored as JSON text columns in SQLite — avoids schema complexity, queryable via JSON functions.

### Precomputed Feedback
Background loop every 6h caches analysis in memory. Dashboard reads instantly. Suppressor reads same cache (GIL-safe, no locks).

### Background Loops (`server.py`)

| Loop | Interval | Purpose |
|------|----------|---------|
| Unusual Activity | 5min | `UnusualDetector.scan_batch()`, save+purge |
| Export Scheduler | 1h | Run pending scheduled exports |
| Feedback Analyzer | 6h | Category performance, suppression candidates |
| ML Retrain | 24h | Retrain credibility model |
| Macro Data | 1h | Calendar seed, earnings/insider ingest, purge |
| Flow Scanner | 5min | `FlowDetector.scan_batch()`, patterns, convergences |
| Author Resolution | 1h | Resolve predictions, update profiles |
| Manipulation Scanner | 30min | Coordinated posting, bot, pump-dump detection |
| Strategy Health | 6h | Health scores, deactivate underperformers |
| Regime Detection | 1h | Market regime classification |

Pattern: initial delay -> `while not stop_event.is_set()` -> try/except+log -> `asyncio.sleep()`.

### On-Demand Analysis
Sector rotation + correlations computed on page visit, cached via query cache (TTL 120s).

### Signal Archive
14-day purge via `run_full_cleanup()`. `archive_before_purge()` copies resolved signals to `signal_archive` (flat table). `_UNIFIED_CTE` unions live+archive for all analytics. 365-day archive retention (`ROT_ARCHIVE_KEEP_DAYS`).

### Dashboard Query Cache (`src/rot/web/query_cache.py`)

| Query | TTL |
|-------|-----|
| Trending tickers, Leaderboard | 30s |
| Chart data, Time series | 60s |
| Perf summary, Strategy breakdown, Accuracy, Heatmaps, Correlations | 120s |
| Landing page stats | 300s |

NOT cached: user-filtered signals, per-user signal count. Features: per-key TTL, thundering-herd prevention (asyncio.Lock), prefix invalidation on new signals, max 100 entries + LRU eviction, lock cleanup every 5min.

### Lag Timer (RSS)
`post_created_utc` vs `created_at` delta shown on RSS signal cards (flair=="rss").

### Win/Loss Logic
Only bullish/bearish count as trades. Mixed/unknown always neutral. Applies in DB SQL (`_WIN_CASE_SQL`/`_LOSS_CASE_SQL`) and backtest engine (`_compute_pnl_pct`).
