# Architecture & Pipeline — ROT Architecture Reference

> Part of the ROT documentation suite. See [CLAUDE.md](../CLAUDE.md) for the full index.

## Quick Start for Agents

- Key file(s): `src/rot/app/runner.py` (pipeline orchestrator), `src/rot/app/server.py` (FastAPI factory)
- Key pattern: 9-stage pipeline, dual-path NLP/legacy, provider-agnostic LLM, multi-level dedup
- Entry points: `python -m rot.app.server` (web+pipeline), `python -m rot.app.main` (one-shot), `python -m rot.app.loop` (continuous)

---

## Architecture Overview

ROT is a vertically integrated pipeline that turns social media chatter into structured, scored, tradeable options signal intelligence. The data flows through 9 stages:

```
[Ingestion] --> [Trend Detection] --> [NLP Analysis] --> [Event Extraction]
    --> [Credibility Scoring] --> [Adaptive Suppression] --> [LLM Reasoning] --> [Trade Building] --> [Storage + Delivery]
```

### Key Architectural Decisions

| Decision | Implementation |
|----------|---------------|
| Zero external NLP dependencies | Custom 10-module NLP engine in `src/rot/nlp/`, pure Python |
| Provider-agnostic LLM | Supports OpenAI, Anthropic, DeepSeek via `LLMClient` |
| Multi-source ingestion | Reddit (PRAW), RSS (feedparser), StockTwits (HTTP), Twitter/X (API v2) |
| Dual-path event extraction | NLP engine path + legacy regex fallback |
| Tier-gated SaaS model | 5 tiers (Free, Pro, Premium, Ultra, Enterprise) via Stripe |
| SQLite persistence | Single-file DB with WAL mode, async via aiosqlite, 18+ tables |
| Real-time delivery | WebSocket push, Discord webhooks, email (Resend/SMTP), Twitter posting |

---

## Pipeline Flow

The pipeline is orchestrated by `PipelineRunner` (`src/rot/app/runner.py`). Each `run_once()` cycle executes the stages below.

### Stage 1: Ingestion

**Module:** `src/rot/ingest/`

| Component | Purpose |
|-----------|---------|
| `RedditIngestor` | Polls subreddits via PRAW, returns `ThreadSnapshot` (post + top comments) |
| `RSSIngestor` | Polls 13+ RSS feeds (MarketWatch, FDA, DoD, Fed, SeekingAlpha, etc.) |
| `StockTwitsIngestor` | Polls symbol streams + trending |
| `TwitterIngestor` | Polls cashtags + accounts via Twitter API v2 |
| `MultiSourceIngestor` | Aggregates all sources into unified snapshot list |
| `SeenStore` | JSON file dedup to skip already-processed posts (5000 entry cap) |

### Stage 2: Trend Detection

**Module:** `src/rot/trend/`

- `TrendEngine.detect(snapshots)` --> `List[TrendCandidate]`
- Sliding window (default 1800s), scores based on score velocity + comment velocity
- RSS/StockTwits/Twitter sources can bypass trend threshold (high-signal by nature)
- `TrendStore` persists trend state as JSON
- Produces both "top N overall" and "top N per-ticker" candidate lists

### Stage 3: Entity Extraction

**Module:** `src/rot/nlp/engine.py` (or legacy path in `event_builder.py`)

- NLP path: tokenize --> resolve entities (cashtags, bare tickers, implicit references, sector expansion)
- Legacy path: regex `$TICKER` + bare uppercase matching with blocklist
- Returns list of ticker symbols per candidate

### Stage 4: Event Building

**Module:** `src/rot/extract/event_builder.py`

- `EventBuilder(nlp_engine=NLPEngine())` -- dual-path: NLP or legacy
- NLP path: uses full NLP analysis (sentiment, classification, temporal, thread consensus)
- Produces `Event` dataclass with type, stance, horizon, confidence, entities, evidence, meta
- Meta dict carries all NLP data, post metadata, trend features for downstream use

### Stage 5: Market Enrichment

**Module:** `src/rot/market/`

| Component | Purpose |
|-----------|---------|
| `SymbolValidator` | Validates tickers via yfinance (cached, 1000-entry cap) |
| `MarketEnricher` | Enriches events with: last close, 1d change, market cap, ATM IV, put/call OI ratio |
| `PriceChecker` | Periodic price tracking for signal performance measurement |

- Options chain data fetched when `enable_options_chain=True` (disabled by default)

### Stage 6: Credibility Scoring

**Module:** `src/rot/credibility/`

- **ML path (default):** `MLCredibilityScorer` wraps a trained scikit-learn `GradientBoostingClassifier` predicting P(win) from 32 signal features. Model trains live from historical win/loss data in a background loop (every 24h). Hot-reloads after retrain.
- **Heuristic fallback:** `CredibilityScorer` with 12 hand-tuned factors. Always runs internally for comparison metadata. Used when ML model not yet trained or inference fails.
- **Feature extraction:** `features.py` produces a 32-float vector from Event metadata.
- **Training:** `train.py` queries signal_performance for resolved win/loss outcomes, trains with 5-fold CV. Requires 100+ decided signals and 30+ in each class.
- Both scores stored in `meta["ml_credibility"]` for A/B monitoring.
- Result: event.confidence = P(win) from ML [0.05, 0.95], or heuristic adjustment clamped [0.05, 1.0]

#### Heuristic Credibility Factors (12 factors)

| # | Factor | Adjustment | Condition |
|---|--------|-----------|-----------|
| 0 | `institutional_rss` | +0.15 | RSS from FDA/DoD/Fed/SEC feeds |
| 0b | `news_rss` | +0.05 | Any other RSS source |
| 1 | `dd_flair` | +0.15 | DD flair + body >= 200 chars |
| 1b | `dd_flair_shallow` | +0.05 | DD flair + short body |
| 1c | `quality_flair` | +0.05 | Discussion/TA/Fundamentals flair |
| 2 | `too_many_tickers` | -0.15 | 5+ entities (watchlist noise) |
| 2b | `focused_ticker` | +0.05 | Exactly 1 entity |
| 3 | `crosspost_penalty` | -0.10 | Post is a crosspost |
| 4 | `high_score` | +0.05 | Post score > 100 |
| 4b | `controversial` | -0.05 | Upvote ratio < 0.6 |
| 5 | `high_discussion` | +0.05 | Comments > score x 0.5 |
| 6 | `has_body_analysis` | +0.05 | Body > 100 chars |
| 7 | `subreddit_boost` | +0.05 | options/thetagang/investing/valueinvesting |
| 7b | `subreddit_penalty` | -0.05 to -0.10 | wsb/shortsqueeze/pennystocks |
| 8a | `author_high_karma` | +0.10 | Karma >= 50,000 |
| 8b | `author_good_karma` | +0.05 | Karma >= 10,000 |
| 8c | `author_low_karma` | -0.10 | Karma < 100 |
| 8d | `author_established` | +0.05 | Account age >= 365 days |
| 8e | `author_new_account` | -0.10 | Account age < 30 days |
| 9 | `nlp_sarcasm_penalty` | -0.00 to -0.15 | Sarcasm probability > 0.5 |
| 10a | `nlp_high_conviction` | +0.05 | NLP conviction > 0.7 |
| 10b | `nlp_low_conviction` | -0.05 | NLP conviction < 0.3 |
| 11a | `nlp_strong_consensus` | +0.10 | Thread consensus > 0.7 |
| 11b | `nlp_moderate_consensus` | +0.05 | Thread consensus > 0.5 |
| 11c | `nlp_contrarian_flag` | -0.05 | Contrarian detected in thread |
| 12 | `nlp_low_actionability` | -0.10 | Temporal actionability < 0.3 |

### Stage 6.5: Adaptive Signal Suppression

**Module:** `src/rot/feedback/suppressor.py`

- `SignalSuppressor.apply(event)` --> `(Event, was_suppressed)`
- Reads precomputed analysis from `FeedbackAnalyzer._last_analysis` (thread-safe GIL read)
- **Category-level suppression**: if event_type win_rate < 20% with 30+ decided signals
- **Source-level suppression**: if (event_type, subreddit) win_rate < 15% with 30+ decided signals
- **Low-confidence + poor category**: if confidence < 0.3 AND event_type appears in any suppression candidate
- Suppressed signals: emit with stub ReasoningPacket + no-trade TradeIdea, skip LLM + trade building
- Suppressed signals still stored with `meta["suppressed"]=True` for audit trail
- Disabled by default until first `FeedbackAnalyzer.run_analysis()` completes

### Stage 7: LLM Reasoning

**Module:** `src/rot/reasoner/`

- `Reasoner.reason(event)` --> `ReasoningPacket`
- If LLM available: sends system prompt + event prompt to LLM, parses structured JSON response
- If LLM unavailable: returns stub reasoning (template-based fallback)
- Circuit breaker: disables LLM after 3 consecutive failures
- **Informational-only sources** (FDA, DoD, pharma feeds) skip LLM reasoning --> stub with confidence=0

#### LLM Confidence Calibration Rules

| Range | Meaning |
|-------|---------|
| 0.10-0.25 | Speculative, no data |
| 0.25-0.40 | Some reasoning, unverified |
| 0.40-0.55 | Solid thesis with real data |
| 0.55-0.70 | Strong thesis + market confirmation |
| 0.70-0.85 | Multi-source corroboration |
| 0.85-1.00 | Officially confirmed events |

Hard caps: squeeze_chatter never > 0.65, nothing > 0.85 unless officially confirmed. Subreddit discounts: WSB/shortsqueeze/pennystocks -0.05 to -0.10. RSS boost: +0.05 to +0.10. Market contradiction: -0.10 to -0.20.

### Stage 8: Trade Building

**Module:** `src/rot/market/trade_builder.py`

- `TradeBuilder.build(packet, event)` --> `List[TradeIdea]`
- IV-aware strategy selection:
  - High IV (>50%): credit spreads, iron condors (sell premium)
  - Low IV: debit spreads, straddles (buy premium)
- Liquidity gates: min volume, min OI, max bid-ask spread
- Market cap gate: default $100M minimum
- Quality scoring: 0.0-1.0 based on confidence, thesis quality, risk notes

### Stage 9: Storage & Delivery

**Module:** `src/rot/storage/database.py`, `src/rot/alerts/`

- Signal saved to SQLite `signals` table with all metadata as JSON blobs
- `on_signal` callback fires for real-time delivery:
  - WebSocket broadcast to connected dashboard clients
  - Discord webhook (if configured)
  - Email alerts (digest + real-time, filtered by user preferences)
  - Twitter/X posting (if configured)
  - Custom webhooks (Enterprise tier)
- JSONL logging for audit trail

---

## Module Reference

### Core Modules

| Module | Key Files | Purpose |
|--------|-----------|---------|
| `src/rot/core/` | `config.py`, `types.py`, `logging.py` | Pydantic Settings, frozen dataclasses, JSONL logging |
| `src/rot/ingest/` | `reddit_ingestor.py`, `rss_ingestor.py`, `stocktwits_ingestor.py`, `twitter_ingestor.py`, `multi_ingestor.py`, `seen_store.py` | Multi-source data ingestion |
| `src/rot/trend/` | `trend_engine.py`, `trend_store.py`, `ranker.py`, `ticker_ranker.py` | Sliding window trend detection |
| `src/rot/nlp/` | 10 modules (see [nlp-engine.md](nlp-engine.md)) | Custom financial NLP engine |
| `src/rot/extract/` | `event_builder.py`, `enricher.py` | Dual-path event extraction |
| `src/rot/credibility/` | `scorer.py`, `ml_scorer.py`, `features.py`, `train.py` | ML + heuristic credibility scoring |
| `src/rot/feedback/` | `analyzer.py`, `suppressor.py` | Feedback analysis + adaptive suppression |
| `src/rot/reasoner/` | `reasoner.py`, `llm_client.py`, `prompts.py`, `parser.py`, `ai_summary.py` | LLM reasoning with circuit breaker |
| `src/rot/market/` | `trade_builder.py`, `enricher.py`, `symbol_validator.py`, `price_checker.py`, `gates.py` | Market data + trade building |
| `src/rot/backtest/` | 12 modules | Strategy backtesting engine |
| `src/rot/unusual/` | 4 modules | Unusual options activity detection |
| `src/rot/analysis/` | 5 modules | Sector rotation + correlation analysis |
| `src/rot/export/` | 4 modules | Enterprise data pipeline + lineage |
| `src/rot/storage/` | `database.py` | Async SQLite, 18+ tables, migrations |
| `src/rot/alerts/` | `dispatcher.py`, `discord.py`, `email.py`, `twitter.py`, `webhook.py` | Multi-channel alert delivery |
| `src/rot/app/` | `main.py`, `loop.py`, `runner.py`, `server.py` | Entry points + pipeline orchestration |
| `src/rot/web/` | `auth.py`, `query_cache.py`, `tier_gate.py`, `rate_limit.py`, `routes/`, `templates/` | Web layer (see [web-layer.md](web-layer.md)) |

---

## Key Design Patterns

### Dual-Path NLP/Legacy

```python
class EventBuilder:
    def __init__(self, nlp_engine=None):
        self._nlp = nlp_engine

    def from_candidate(self, c):
        if self._nlp:
            return self._from_candidate_nlp(c)  # NLP path
        return self._from_candidate_legacy(c)    # regex fallback
```

The NLP engine is optional. If not provided (or if it fails), EventBuilder falls back to legacy regex-based extraction. This ensures the pipeline never breaks due to NLP issues.

### Provider-Agnostic LLM

```python
class LLMClient:
    def __init__(self, provider="openai", api_key="", model="gpt-4o-mini", ...):
        # Supports: openai, anthropic, deepseek
        # Each provider has its own SDK client
```

Switching LLM providers requires only changing `ROT_LLM_PROVIDER` and `ROT_LLM_API_KEY`.

### Circuit Breaker (Reasoner)

After 3 consecutive LLM failures, the Reasoner automatically switches to stub reasoning (no API calls). Prevents cascading failures from taking down the pipeline.

### Informational-Only Sources

FDA, DoD, and pharma RSS feeds are classified as informational-only. They skip LLM reasoning and trade building (no trades generated), but are still stored as signals for the news feed and dashboard.

### Dedup at Multiple Levels

| Level | Mechanism | Scope |
|-------|-----------|-------|
| 1 | SeenStore | Post-level dedup at ingestion (JSON file, 5000 entry cap) |
| 2 | Runner dedup | (post_url, ticker) pair dedup at emission (in-memory, clears at 2K entries) |
| 3 | DB unique index | (post_url, ticker, created_at) prevents duplicate signals in storage |

### ML/Heuristic Dual-Path Credibility Scoring

```python
class MLCredibilityScorer:
    def score(self, event):
        heuristic_result = self._heuristic.score(event)  # always runs
        if not self.ml_available:
            return heuristic_result
        return self._score_ml(event, heuristic_result)  # P(win) from model
```

The ML scorer trains live from historical outcomes. If no model exists, it falls back to the heuristic. Both scores stored in `meta["ml_credibility"]` for A/B comparison. Hot-reloads after retrain without server restart.

### Tier Gating as Dict Returns

Gate functions return dicts of boolean/numeric flags rather than raising exceptions:

```python
access = gate_chart_access(user_tier)
if access["has_quadrant"]:
    render_quadrant_chart()
```

### JSON Blob Storage

Complex nested data (market data, reasoning, trade ideas, event metadata including NLP) is stored as JSON text columns in SQLite. Avoids schema complexity while keeping data queryable via JSON functions.

### Precomputed Feedback Analysis

The feedback engine runs expensive DB queries in a background loop every 6h, caching results in memory. The Signal Quality dashboard reads cached results instantly. The suppressor reads the same cache from the sync pipeline thread (GIL-safe dict read, no locks needed).

### Background Scan Loops

`server.py` runs background `asyncio` tasks alongside the main pipeline loop:

| Loop | Interval | Purpose |
|------|----------|---------|
| Unusual Activity Scanner | 5 min | Fetches recent signals, runs `UnusualDetector.scan_batch()`, saves events, purges old |
| Export Scheduler | 1 hour | Checks `export_schedules` for pending exports and runs them |
| Feedback Analyzer | 6 hours | Recomputes category performance, suppression candidates |
| ML Retrain | 24 hours | Retrains credibility model from win/loss outcomes |

All loops follow the pattern: initial delay --> `while not stop_event.is_set()` --> try/except with logging --> `asyncio.sleep()`.

### On-Demand Analysis (Sector + Correlation)

Sector rotation and correlation analysis are computed on-demand when the user visits the page, not via background loops. Results are cached via the dashboard query cache (TTL 120s).

### Signal Archive (Long-Term Data Retention)

Signals and performance data are purged after 14 days by `run_full_cleanup()`. To preserve data for backtesting and analytics, `archive_before_purge()` copies resolved signals into the flat `signal_archive` table before deletion. A `_UNIFIED_CTE` unions live data with archive for seamless querying across all analytics. Archives retained for 365 days (configurable via `ROT_ARCHIVE_KEEP_DAYS`).

### Dashboard Query Cache

The dashboard loads 12+ database queries per page view. An async in-memory TTL cache (`src/rot/web/query_cache.py`) handles this:

| Cached Query | TTL |
|-------------|-----|
| Trending tickers | 30s |
| Leaderboard | 30s |
| Chart data | 60s |
| Time series | 60s |
| Performance summary | 120s |
| Strategy breakdown | 120s |
| Accuracy stats | 120s |
| Heatmaps | 120s |
| Correlations | 120s |
| Landing page stats | 300s |

**NOT cached**: user-filtered signals, per-user signal count badge.

Features: per-key TTL, thundering-herd prevention (per-key `asyncio.Lock`), prefix invalidation on new signals, max 100 entries with LRU eviction, periodic lock cleanup every 5 minutes.

### Lag Timer (RSS Signal Provenance)

Event meta stores `post_created_utc` (RSS article publish time) and `snapshot_ts` (ingestion time). The dashboard template computes `created_at - post_created_utc` to show detection latency. Only displayed on RSS-sourced signals (flair == "rss").

### Win/Loss Logic

Only **bullish** and **bearish** signals count as trades for win/loss evaluation. Mixed and unknown stances are always neutral. This applies both in the DB (`_WIN_CASE_SQL`, `_LOSS_CASE_SQL`) and the backtest engine (`_compute_pnl_pct`).
