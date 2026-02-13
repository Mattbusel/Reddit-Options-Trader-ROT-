# CLAUDE.md — ROT (Reddit Options Trader) Architecture Reference

> **MANDATORY UPDATE RULE**: Any Claude agent, LLM, or developer that adds, removes, or modifies
> ANY feature, module, route, database table, config variable, or pipeline stage MUST update this
> document before considering the task complete. This is a hard requirement, not a suggestion.
> Future agents: if your changes are not reflected here, your work is incomplete.

## Quick Reference

| Attribute | Value |
|-----------|-------|
| **Name** | ROT — Reddit Options Trader |
| **Purpose** | Real-time AI-powered options trading signal intelligence from Reddit + RSS + StockTwits + Twitter |
| **Stack** | Python 3.12, FastAPI, Jinja2, Tailwind CSS, Chart.js, HTMX, aiosqlite, PRAW |
| **Entry Points** | `python -m rot.app.server` (web+pipeline), `python -m rot.app.main` (one-shot), `python -m rot.app.loop` (continuous) |
| **Deployment** | Railway (Docker, persistent volume for SQLite) |
| **Package Layout** | `src/rot/` — all source under setuptools src-layout |
| **Tests** | `tests/` — pytest with pytest-asyncio, ~423+ tests |
| **Config** | All via `ROT_*` environment variables (Pydantic Settings) |
| **DB** | SQLite with aiosqlite (WAL mode), 15+ tables |
| **Python Version** | >=3.10 (deployed on 3.12) |

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Pipeline Flow — The Core Engine](#2-pipeline-flow)
3. [Module Reference](#3-module-reference)
4. [Custom NLP Engine](#4-custom-nlp-engine)
5. [Database Schema](#5-database-schema)
6. [Web Layer & Routes](#6-web-layer--routes)
7. [Authentication & Authorization](#7-authentication--authorization)
8. [Subscription Tiers & Feature Gating](#8-subscription-tiers--feature-gating)
9. [Configuration Reference](#9-configuration-reference)
10. [External Integrations](#10-external-integrations)
11. [Data Types & Models](#11-data-types--models)
12. [Deployment](#12-deployment)
13. [Testing](#13-testing)
14. [Key Design Patterns](#14-key-design-patterns)
15. [File Tree](#15-file-tree)

---

## 1. Architecture Overview

ROT is a vertically integrated pipeline that turns social media chatter into structured, scored, tradeable options signal intelligence. The data flows through 8 stages:

```
[Ingestion] → [Trend Detection] → [NLP Analysis] → [Event Extraction]
    → [Credibility Scoring] → [Adaptive Suppression] → [LLM Reasoning] → [Trade Building] → [Storage + Delivery]
```

**Key architectural decisions:**
- **Zero external NLP dependencies** — custom 10-module NLP engine in `src/rot/nlp/`, pure Python
- **Provider-agnostic LLM** — supports OpenAI, Anthropic, DeepSeek via `LLMClient`
- **Multi-source ingestion** — Reddit (PRAW), RSS (feedparser), StockTwits (HTTP), Twitter/X (API v2)
- **Dual-path event extraction** — NLP engine path + legacy regex fallback
- **Tier-gated SaaS model** — 5 tiers (Free, Pro, Premium, Ultra, Enterprise) via Stripe
- **SQLite persistence** — single-file DB with WAL mode, async via aiosqlite, 15+ tables
- **Real-time delivery** — WebSocket push, Discord webhooks, email (Resend/SMTP), Twitter posting

---

## 2. Pipeline Flow

The pipeline is orchestrated by `PipelineRunner` (`src/rot/app/runner.py`). Each `run_once()` cycle:

### Stage 1: Ingestion
**Module:** `src/rot/ingest/`
- `RedditIngestor` — polls subreddits via PRAW, returns `ThreadSnapshot` (post + top comments)
- `RSSIngestor` — polls 13+ RSS feeds (MarketWatch, FDA, DoD, Fed, SeekingAlpha, etc.)
- `StockTwitsIngestor` — polls symbol streams + trending
- `TwitterIngestor` — polls cashtags + accounts via Twitter API v2
- `MultiSourceIngestor` — aggregates all sources into unified snapshot list
- `SeenStore` — JSON file dedup to skip already-processed posts

### Stage 2: Trend Detection
**Module:** `src/rot/trend/`
- `TrendEngine.detect(snapshots)` → `List[TrendCandidate]`
- Sliding window (default 1800s), scores based on score velocity + comment velocity
- RSS/StockTwits/Twitter sources can bypass trend threshold (high-signal by nature)
- `TrendStore` — persists trend state as JSON
- Produces both "top N overall" and "top N per-ticker" candidate lists

### Stage 3: Entity Extraction
**Module:** `src/rot/nlp/engine.py` (or legacy path in `event_builder.py`)
- NLP path: tokenize → resolve entities (cashtags, bare tickers, implicit references, sector expansion)
- Legacy path: regex `$TICKER` + bare uppercase matching with blocklist
- Returns list of ticker symbols per candidate

### Stage 4: Event Building
**Module:** `src/rot/extract/event_builder.py`
- `EventBuilder(nlp_engine=NLPEngine())` — dual-path: NLP or legacy
- NLP path: uses full NLP analysis (sentiment, classification, temporal, thread consensus)
- Produces `Event` dataclass with type, stance, horizon, confidence, entities, evidence, meta
- Meta dict carries all NLP data, post metadata, trend features for downstream use

### Stage 5: Market Enrichment
**Module:** `src/rot/market/`
- `SymbolValidator` — validates tickers via yfinance (cached)
- `MarketEnricher` — enriches events with: last close, 1d change, market cap, ATM IV, put/call OI ratio, call/put open interest
- `PriceChecker` — periodic price tracking for signal performance measurement
- Options chain data fetched when `enable_options_chain=True`

### Stage 6: Credibility Scoring
**Module:** `src/rot/credibility/`
- **ML path (default):** `MLCredibilityScorer` wraps a trained scikit-learn `GradientBoostingClassifier` that predicts P(win) from 32 signal features. Model trains live from historical win/loss data in a background loop (every 24h). Hot-reloads after each retrain.
- **Heuristic fallback:** `CredibilityScorer` with 12 hand-tuned factors (always runs internally for comparison metadata). Used when ML model not yet trained or inference fails.
- **Feature extraction:** `features.py` produces a 32-float vector from Event metadata (post metadata, trend, NLP, market, author, categoricals).
- **Training:** `train.py` queries signal_performance for resolved win/loss outcomes, extracts features, trains with 5-fold cross-validation, saves pickle. Requires 100+ decided signals and 30+ in each class.
- Both scores stored in `meta["ml_credibility"]` for A/B monitoring.
- Result: event.confidence = P(win) from ML [0.05, 0.95], or heuristic adjustment clamped [0.05, 1.0]

### Stage 6.5: Adaptive Signal Suppression
**Module:** `src/rot/feedback/suppressor.py`
- `SignalSuppressor.apply(event)` → `(Event, was_suppressed)`
- Reads precomputed analysis from `FeedbackAnalyzer._last_analysis` (thread-safe GIL read)
- **Category-level suppression**: if event_type win_rate < 20% (configurable) with 30+ decided signals
- **Source-level suppression**: if (event_type, subreddit) win_rate < 15% with 30+ decided signals
- **Low-confidence + poor category**: if confidence < 0.3 AND event_type appears in any suppression candidate
- Suppressed signals: emit with stub ReasoningPacket + no-trade TradeIdea, skip LLM + trade building
- Suppressed signals still stored with `meta["suppressed"]=True` for audit trail
- Disabled by default until first `FeedbackAnalyzer.run_analysis()` completes (graceful first-deployment)
- Saves LLM API costs by skipping reasoning on historically losing signal categories

### Stage 7: LLM Reasoning
**Module:** `src/rot/reasoner/`
- `Reasoner.reason(event)` → `ReasoningPacket`
- If LLM available: sends system prompt + event prompt to LLM, parses structured JSON response
- If LLM unavailable: returns stub reasoning (template-based fallback)
- Prompt includes: Reddit signal data, trend metrics, NLP analysis section, market context
- Circuit breaker: disables LLM after 3 consecutive failures
- **Informational-only sources** (FDA, DoD, pharma feeds) skip LLM reasoning → stub with confidence=0

### Stage 8: Trade Building
**Module:** `src/rot/market/trade_builder.py`
- `TradeBuilder.build(packet, event)` → `List[TradeIdea]`
- IV-aware strategy selection:
  - High IV (>50%): credit spreads, iron condors (sell premium)
  - Low IV: debit spreads, straddles (buy premium)
- Liquidity gates: min volume, min OI, max bid-ask spread
- Market cap gate: default $100M minimum
- Quality scoring: 0.0-1.0 based on confidence, thesis quality, risk notes
- Output: TradeIdea with legs, max loss, quality score, or no-trade stub

### Stage 9: Storage & Delivery
**Module:** `src/rot/storage/database.py`, `src/rot/alerts/`
- Signal saved to SQLite `signals` table with all metadata as JSON blobs
- `on_signal` callback fires for real-time delivery:
  - WebSocket broadcast to connected dashboard clients
  - Discord webhook (if configured)
  - Email alerts (digest + real-time, filtered by user preferences)
  - Twitter/X posting (if configured)
  - Custom webhooks (Enterprise tier)
- JSONL logging for audit trail (`src/rot/core/logging.py`)

---

## 3. Module Reference

### `src/rot/core/`
| File | Purpose |
|------|---------|
| `config.py` | Pydantic Settings — all `ROT_*` env vars, 15 config sections |
| `types.py` | Frozen dataclasses: Post, Comment, ThreadSnapshot, TrendCandidate, Event, ReasoningPacket, OptionLeg, TradeIdea |
| `logging.py` | JsonlLogger — structured logging to JSONL files |

### `src/rot/ingest/`
| File | Purpose |
|------|---------|
| `reddit_ingestor.py` | PRAW-based Reddit polling (hot/new/rising), comment ingestion |
| `rss_ingestor.py` | feedparser-based RSS polling, 13+ feed configs, per-feed poll intervals |
| `stocktwits_ingestor.py` | StockTwits HTTP API, symbol streams + trending |
| `twitter_ingestor.py` | Twitter API v2 (recent search), cashtag + account tracking |
| `multi_ingestor.py` | Aggregates multiple ingestors into unified interface |
| `seen_store.py` | JSON file-based dedup (seen post IDs) |

### `src/rot/trend/`
| File | Purpose |
|------|---------|
| `trend_engine.py` | Sliding window trend detection, score/comment velocity |
| `trend_store.py` | JSON-persisted trend state across runs |
| `ranker.py` | Top-N ranking by trend score |
| `ticker_ranker.py` | Top-N ranking grouped by ticker |

### `src/rot/nlp/` (Custom NLP Engine — 10 modules)
| File | Purpose | Lines |
|------|---------|-------|
| `__init__.py` | Re-exports NLPEngine, NLPResult, SentimentResult, ResolvedEntity | ~28 |
| `types.py` | All NLP dataclasses (Token, SentimentResult, ResolvedEntity, NLPResult, etc.) | ~150 |
| `tokenizer.py` | Financial-aware tokenizer (cashtags, emojis, ALL-CAPS, repeated chars, options contracts) | ~300 |
| `lexicon.py` | 500+ term sentiment dictionary (polarity, intensity, conviction per term) | ~400 |
| `sentiment.py` | Sentiment analysis + 8-rule sarcasm detection + conviction scoring | ~350 |
| `entities.py` | Context-aware entity resolution (cashtags, bare tickers, implicit refs, sector expansion) | ~400 |
| `classifier.py` | Multi-label event classification (14 categories, TF-IDF-like scoring) | ~250 |
| `temporal.py` | Tense detection, actionability scoring, urgency scoring, time expression extraction | ~200 |
| `thread.py` | Comment consensus analysis (polarity std dev, OP agreement, contrarian detection) | ~200 |
| `engine.py` | Orchestrator: `analyze(title, body, comments) → NLPResult` | ~250 |

### `src/rot/extract/`
| File | Purpose |
|------|---------|
| `event_builder.py` | Dual-path event extraction (NLP engine or legacy regex). Produces `Event` from `TrendCandidate` |
| `enricher.py` | Ticker alias maps, blocklists, cashtag/bare-ticker heuristics |

### `src/rot/credibility/`
| File | Purpose |
|------|---------|
| `scorer.py` | 12-factor heuristic credibility scoring. Adjusts event confidence based on post quality + NLP signals |
| `ml_scorer.py` | ML-based credibility scorer (GradientBoosting). Predicts P(win) from 32 features. Falls back to heuristic |
| `features.py` | 32-feature extraction for ML scoring. Shared by inference (Event) and training (DB row) paths |
| `train.py` | Training script for ML model. Queries DB for win/loss outcomes, trains GradientBoosting, saves pickle |

### `src/rot/feedback/`
| File | Purpose |
|------|---------|
| `analyzer.py` | Signal feedback analysis engine: category performance, source reliability, feature importance, quality trends, suppression candidates, calibration. Precomputed cache refreshed by background loop every 6h |
| `suppressor.py` | Adaptive signal suppressor: skips LLM reasoning for categories/sources with historically low win rates. Stage 6.5 in pipeline |

### `src/rot/reasoner/`
| File | Purpose |
|------|---------|
| `reasoner.py` | LLM reasoning orchestrator with circuit breaker + stub fallback |
| `llm_client.py` | Provider-agnostic LLM client (OpenAI, Anthropic, DeepSeek) |
| `prompts.py` | System prompt + event prompt template (includes NLP section) |
| `parser.py` | Parses LLM JSON response into ReasoningPacket |
| `ai_summary.py` | AI-powered signal summaries for dashboard |

### `src/rot/market/`
| File | Purpose |
|------|---------|
| `trade_builder.py` | IV-aware trade strategy builder (6 strategies, liquidity gates) |
| `enricher.py` | Market data enrichment via yfinance (price, cap, options chain) |
| `symbol_validator.py` | Ticker validation with caching |
| `price_checker.py` | Periodic price tracking for performance measurement |
| `gates.py` | Trade safety gates (market cap, liquidity thresholds) |

### `src/rot/backtest/` (Backtesting Engine — 10 modules)
| File | Purpose |
|------|---------|
| `__init__.py` | Re-exports BacktestConfig, BacktestEngine, BacktestResult, TradeRecord, EquityPoint, DrawdownPeriod |
| `config.py` | Frozen dataclass `BacktestConfig` — portfolio settings, exit rules, signal filters, serialization |
| `result.py` | Frozen dataclasses: `TradeRecord`, `EquityPoint`, `DrawdownPeriod`, `BacktestResult` with `to_dict()` |
| `metrics.py` | Pure stateless metric functions: Sharpe, Sortino, Calmar, drawdown, profit factor, VaR, CVaR, MAE/MFE |
| `engine.py` | Core `BacktestEngine.run(signals, config) → BacktestResult`. Stance-aware P&L, position sizing, stop/take-profit |
| `monte_carlo.py` | `MonteCarloResult` + `run_monte_carlo()` — bootstrap resampling for confidence intervals and probabilities |
| `risk.py` | `RiskMetrics` + `compute_risk_metrics()` — VaR, CVaR, MAE/MFE, Ulcer Index, skewness, kurtosis, underwater analysis |
| `walk_forward.py` | `WalkForwardResult` + `run_walk_forward()` — chronological IS/OOS folds with stability scoring |
| `optimizer.py` | `OptimizationResult` + `optimize()` — grid search over params, heatmap generation, Sharpe-based ranking |
| `benchmark.py` | `BenchmarkComparison` + `compare_to_benchmark()` — alpha, beta, correlation, information ratio vs SPY |
| `comparator.py` | `ComparisonResult` + `compare_strategies()` — side-by-side metrics, correlation matrix, rankings |
| `report.py` | `generate_csv_trades()` + `generate_html_report()` — CSV export and standalone HTML report generation |

### `src/rot/storage/`
| File | Purpose |
|------|---------|
| `database.py` | Async SQLite (aiosqlite), WAL mode, 17+ tables, migration system |

### `src/rot/alerts/`
| File | Purpose |
|------|---------|
| `dispatcher.py` | Multi-channel alert routing |
| `discord.py` | Discord webhook alerts |
| `email.py` | Email alerts (Resend API + SMTP fallback) |
| `twitter.py` | Twitter/X auto-posting via OAuth 1.0a |
| `webhook.py` | Custom webhook alerts (Enterprise) |

### `src/rot/app/`
| File | Purpose |
|------|---------|
| `main.py` | One-shot pipeline entry point |
| `loop.py` | Continuous polling loop entry point |
| `runner.py` | `PipelineRunner` — orchestrates the 8-stage pipeline |
| `server.py` | FastAPI factory — creates app, mounts routes, starts background pipeline loop |

### `src/rot/web/`
| File | Purpose |
|------|---------|
| `routes/` | 35+ route files (see Section 6) |
| `templates/` | 39+ Jinja2 HTML templates |
| `auth.py` | JWT + API key + session cookie authentication |
| `query_cache.py` | Async in-memory TTL cache for dashboard queries (per-key TTL, thundering-herd prevention, prefix invalidation) |
| `tier_gate.py` | 5-tier feature gating (30+ gate functions) |
| `rate_limit.py` | Per-tier API rate limiting |

---

## 4. Custom NLP Engine

The NLP engine (`src/rot/nlp/`) is ROT's differentiator — a zero-dependency, financial-domain NLP pipeline built from scratch. No external NLP libraries (no spaCy, no NLTK, no transformers).

### Entry Point
```python
from rot.nlp import NLPEngine

engine = NLPEngine()
result = engine.analyze(title="$TSLA to the moon!", body="Buying calls...", comments=[...])

result.primary_stance          # "bullish"
result.ticker_symbols          # ["TSLA"]
result.sentiment.polarity      # 0.85
result.sentiment.conviction    # 0.7
result.sentiment.sarcasm_probability  # 0.0
result.classifications         # [ClassifiedEvent(category="squeeze_chatter", confidence=0.6)]
result.temporal.actionability  # 0.9
result.thread.consensus_score  # 0.75
```

### Pipeline (executed in `engine.py`)
1. **Tokenize** — financial-aware tokenizer handles: `$TICKER` cashtags, 50+ emoji mappings, ALL-CAPS detection, repeated character normalization, options contract parsing (`TSLA 200C 1/19`), markdown stripping
2. **Sentiment** — lexicon-matching (500+ terms) → negation window (3-word lookahead) → intensifier/diminisher pass → emoji pass → ALL-CAPS boost → sarcasm detection → conviction scoring → aggregation
3. **Entity Resolution** — cashtag extraction → bare ticker filtering (imports blocklists from `enricher.py` and `event_builder.py`) → implicit resolution (~50 CEO/company maps) → sector expansion (~12 sector groups) → options entity extraction → position extraction → per-ticker sentiment
4. **Classification** — multi-label weighted keyword scoring across 14 categories: `earnings_rumor`, `product_news`, `regulatory`, `squeeze_chatter`, `macro`, `other`, `insider_activity`, `technical_breakout`, `options_flow`, `dividend_play`, `buyback`, `ipo`, `spac`, `crypto_correlation`
5. **Temporal** — verb pattern tense detection (past/present/future), actionability scoring (past=0.1-0.3, present=0.7-1.0, future=0.4-0.6), time expression extraction, urgency scoring
6. **Thread Consensus** — analyzes `ThreadSnapshot.top_comments`: polarity std dev for consensus, OP sentiment agreement, contrarian detection, quality weighting by score x log(length)

### Sarcasm Detection (8 Rules)
1. ALL-CAPS positive + negative context → +0.35
2. Clown emoji after statement → +0.40
3. Known sarcastic phrases ("what could go wrong", "cant go tits up") → +0.50
4. Emoji contradiction (rocket + bearish words) → +0.30
5. Quoted positive words in negative context → +0.25
6. Excessive rockets with no substance → +0.15
7. "This is fine" pattern + negative context → +0.35
8. Rhetorical question + positive → +0.45

### Lexicon Categories
The 500+ term lexicon (`lexicon.py`) is organized by:
- **Category**: action, outcome, descriptor, emoji, slang, modifier
- **Domain**: general, options, technical, wsb_slang, macro
- Each term has: `polarity` (-1.0 to +1.0), `intensity` (0.0 to 1.0), `conviction` (0.0 to 1.0)

---

## 5. Database Schema

SQLite with WAL mode, managed by `src/rot/storage/database.py`. All tables use async access via aiosqlite.

### `signals` — Core signal storage
| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| run_id | TEXT | Pipeline run identifier |
| created_at | REAL | Unix timestamp |
| ticker | TEXT | Primary ticker symbol |
| event_type | TEXT | One of 6 EventTypes |
| stance | TEXT | bullish/bearish/mixed/unknown |
| time_horizon | TEXT | intraday/1w/earnings/longer/unknown |
| confidence | REAL | 0.0-1.0 after credibility scoring |
| trend_score | REAL | Raw trend detection score |
| quality_score | REAL | Trade quality score 0.0-1.0 |
| strategy | TEXT | Options strategy name |
| subreddit | TEXT | Source subreddit |
| post_title | TEXT | Reddit post title |
| post_url | TEXT | Reddit post URL |
| market_data | TEXT (JSON) | Price, cap, IV, options chain data |
| reasoning | TEXT (JSON) | Full ReasoningPacket |
| trade_idea | TEXT (JSON) | Full TradeIdea |
| event_data | TEXT (JSON) | Full Event including NLP metadata |
| sector | TEXT | Market sector |
| sponsored | INTEGER | 0/1 flag for sponsored signals |
| sponsored_by | TEXT | Sponsor company name |

**Indexes:** ticker, created_at DESC, confidence DESC, stance, (post_url, ticker, created_at), event_type, strategy, (created_at DESC, ticker)

### `signal_performance` — Price tracking
| Column | Type | Description |
|--------|------|-------------|
| signal_id | TEXT FK→signals | Linked signal |
| ticker | TEXT | Ticker symbol |
| price_at_signal | REAL | Price when signal generated |
| price_1h / price_4h / price_1d / price_1w | REAL | Tracked prices at intervals |
| max_gain_pct / max_loss_pct | REAL | Peak gain/loss since signal |
| checked_at | REAL | Last price check timestamp |

### `users` — User accounts
| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| email | TEXT UNIQUE | User email |
| password_hash | TEXT | bcrypt hash |
| api_key_hash | TEXT UNIQUE | SHA-256 hash of API key |
| tier | TEXT | free/pro/premium/ultra/enterprise |
| settings | TEXT (JSON) | User preferences (watchlist, filter presets, LLM settings) |

### `subscriptions` — Stripe subscriptions
| Column | Type | Description |
|--------|------|-------------|
| user_id | TEXT FK→users | Linked user |
| stripe_customer_id | TEXT | Stripe customer ID |
| stripe_subscription_id | TEXT | Stripe subscription ID |
| tier | TEXT | Subscription tier |
| status | TEXT | active/canceled/past_due |
| current_period_end | REAL | Unix timestamp |

### `paper_portfolios` — Paper trading balances
| Column | Type | Description |
|--------|------|-------------|
| user_id | TEXT PK FK→users | One portfolio per user |
| balance | REAL | Current balance (default $10,000) |
| total_trades / winning_trades | INTEGER | Trade counts |
| total_pnl | REAL | Cumulative P&L |

### `paper_trades` — Paper trading history
| Column | Type | Description |
|--------|------|-------------|
| user_id | TEXT FK→users | Owner |
| signal_id | TEXT | Linked signal |
| ticker | TEXT | Symbol |
| entry_price / exit_price | REAL | Trade prices |
| pnl_dollars / pnl_pct | REAL | Profit/loss |
| status | TEXT | open/closed |

### Other Tables
| Table | Purpose |
|-------|---------|
| `api_usage` | Per-user API call tracking for rate limiting |
| `email_alert_settings` | Per-user email alert preferences (digest, realtime, filters) |
| `x_posts` | Twitter/X posting history |
| `referral_clicks` / `referral_conversions` | Affiliate tracking |
| `sponsored_signals` | Enterprise sponsored signal submissions |
| `data_exports` | Enterprise data export request tracking |
| `win_rate_snapshots` | Periodic win rate aggregation |
| `congress_trades` | Congressional trading tracker data |
| `backtest_runs` | Saved backtest runs (id, user_id, name, config_json, result_json, monte_carlo_json, risk_json, created_at) |
| `backtest_strategies` | Saved named backtest strategies (id, user_id, name, description, config_json, last_result_json, last_run_at, created_at, is_active) |

---

## 6. Web Layer & Routes

**Framework:** FastAPI + Jinja2 templates + Tailwind CSS + Chart.js + HTMX

**Factory:** `src/rot/web/server.py` creates the FastAPI app, mounts all route modules, serves static files, starts background pipeline loop.

### Route Inventory (50+ endpoints across 35+ route files)

#### Core Dashboard
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Landing page (or redirect to dashboard if logged in) |
| GET | `/dashboard` | Main signal dashboard |
| GET | `/dashboard/signal/{signal_id}` | Signal detail view |
| GET | `/pricing` | Pricing page with tier comparison |
| GET | `/account` | Account settings |

#### Authentication (`/auth/`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | User registration |
| POST | `/auth/login` | Login (returns JWT) |
| POST | `/auth/logout` | Logout |
| GET | `/auth/me` | Current user info |
| POST | `/auth/api-key` | Generate API key |
| PUT | `/auth/llm-settings` | Update user LLM settings |
| POST/DELETE/GET | `/auth/watchlist` | Watchlist CRUD |
| POST/DELETE/GET | `/auth/filter-presets` | Filter presets CRUD |
| GET/PUT | `/auth/email-alerts` | Email alert settings |

#### Signals API
| Method | Path | Description |
|--------|------|-------------|
| GET | `/signals` | List signals (JSON, filterable, paginated) |
| GET | `/signals/new-count` | Count new signals since timestamp |
| GET | `/signals/{signal_id}` | Single signal detail |
| GET | `/tickers/trending` | Trending tickers |
| POST | `/signals/{signal_id}/reason` | Add reasoning note |
| GET | `/signals/export` | Export signals (CSV/JSON) |

#### Performance & Analytics
| Method | Path | Description |
|--------|------|-------------|
| GET | `/performance` | Performance dashboard page |
| GET | `/performance/summary` | Performance summary JSON |
| GET | `/performance/accuracy` | Accuracy metrics |
| GET | `/performance/history` | Historical performance |
| GET | `/performance/strategy-pnl` | Strategy P&L breakdown |
| GET | `/performance/export` | Export performance data |
| GET | `/accuracy-breakdown` | Detailed accuracy page |
| GET | `/confidence-calibration` | Confidence calibration chart |
| GET | `/weekly-wrap` | Weekly performance wrap |

#### Visualization Pages
| Method | Path | Description |
|--------|------|-------------|
| GET | `/sentiment` | Sentiment heatmap |
| GET | `/correlations` | Ticker correlations matrix |
| GET | `/sector-rotation` | Sector rotation analysis |
| GET | `/unusual-activity` | Unusual options activity |
| GET | `/signal-quality` | Signal quality dashboard (Pro+) |
| GET | `/ticker/{symbol}` | Ticker deep dive |
| GET | `/news` | News feed |

#### Trading Features
| Method | Path | Description |
|--------|------|-------------|
| GET | `/paper-trading` | Paper trading page |
| POST | `/api/v1/paper-trading/trade` | Execute paper trade |
| POST | `/api/v1/paper-trading/close/{trade_id}` | Close paper trade |
| GET | `/leaderboard` | Paper trading leaderboard |
| GET | `/backtest` | Backtesting dashboard (Pro+) |
| POST | `/backtest/run` | Run backtest simulation (HTMX) |
| GET | `/backtest/result/{run_id}` | View saved backtest result |
| POST | `/backtest/monte-carlo/{run_id}` | Run Monte Carlo simulation (HTMX) |
| POST | `/backtest/optimize` | Run parameter optimization (HTMX) |
| POST | `/backtest/walk-forward/{run_id}` | Run walk-forward analysis (HTMX) |
| GET | `/backtest/compare` | Strategy comparison page |
| POST | `/backtest/strategies/save` | Save named strategy config |
| DELETE | `/backtest/strategies/{id}` | Delete saved strategy |
| GET | `/api/v1/backtest/export/{run_id}` | Export results (JSON/CSV) |
| GET | `/replay` | Signal replay |
| GET | `/brokers` | Broker integrations page |
| GET | `/tradingview` | TradingView integration |

#### Data & Tracker Pages
| Method | Path | Description |
|--------|------|-------------|
| GET | `/congress-tracker` | Congressional trading tracker |
| GET | `/sports-tracker` | Sports betting intel |
| GET | `/ceo-rap-sheet` | CEO controversies |
| GET | `/hall-of-legends` | Top performer history |
| GET | `/wall-of-shame` | Pump & dump tracker |

#### Billing (Stripe, prefix: `/api/v1/billing/`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/checkout` | Create Stripe checkout session |
| POST | `/webhook` | Stripe webhook handler |
| GET | `/portal` | Stripe customer portal |
| GET | `/status` | Subscription status |

#### Enterprise (`/api/v1/enterprise/`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/data-export` | Request data export |
| POST | `/sponsored/submit` | Submit sponsored signal |
| GET | `/sponsored/status` | Sponsored signal status |
| GET | `/usage` | Enterprise usage stats |

#### Misc
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/v1/status` | API status |
| GET | `/api/v1/docs` | API documentation |
| GET | `/faq` | FAQ page |
| GET | `/glossary` | Trading glossary |
| GET | `/badges` | User badges |
| GET | `/widgets` | Embeddable widgets |
| GET | `/affiliates` | Affiliate program |
| GET | `/robots.txt` | SEO |
| GET | `/sitemap.xml` | SEO |
| GET | `/llms.txt` | LLM-readable API docs |
| WS | `/api/v1/signals/live` | WebSocket real-time signal stream |

---

## 7. Authentication & Authorization

**Module:** `src/rot/web/auth.py`

### Authentication Methods (priority order)
1. **JWT Bearer Token** — `Authorization: Bearer <token>` header. Used by API clients. Created via `/auth/login`.
2. **API Key** — `X-API-Key: rot_<token>` header. Generated via `/auth/api-key`. Stored as SHA-256 hash.
3. **Session Cookie** — `rot_session` cookie containing JWT. Used by web dashboard.
4. **Anonymous** — No auth = free tier access with gating applied.

### Password Security
- bcrypt hashing via `hash_password()` / `verify_password()`
- JWT signed with `ROT_AUTH_JWT_SECRET` (falls back to `ROT_WEB_SECRET_KEY`)
- JWT claims: `sub` (user_id), `email`, `tier`, `exp` (24h default)

### Key Functions
- `get_current_user_optional(request)` — returns user dict or None (for optional auth routes)
- `require_user(request)` — FastAPI dependency, raises 401 if unauthenticated
- `require_tier(*tiers)` — factory for tier-checking dependency, raises 403 if wrong tier

---

## 8. Subscription Tiers & Feature Gating

**Module:** `src/rot/web/tier_gate.py`

### Tier Hierarchy
```
Free → Pro → Premium → Ultra → Enterprise
```

### Gating Behavior
- **Free tier**: 15-minute signal delay, 10-signal page limit, no API access, heavily redacted trade legs and reasoning
- **Pro**: Full signals, real-time access, basic charts/filters, 1000 API calls/day
- **Premium**: Extended history, advanced analytics, performance dashboard, 5000 API calls/day
- **Ultra**: Full feature access, custom time ranges, exports, 25000 API calls/day
- **Enterprise**: Data licensing, sponsored signals, webhooks, bulk export, 100000 API calls/day

### Gate Functions (30+)
Each returns a dict of boolean/numeric flags:
- `gate_signal()` / `gate_signal_list()` — signal content gating
- `gate_chart_access()` — chart features
- `gate_filter_access()` — filter capabilities
- `gate_performance_access()` — analytics depth
- `gate_email_access()` — alert types
- `gate_heatmap_access()` — sentiment heatmap
- `gate_leaderboard_access()` — leaderboard features
- `gate_market_context()` — market data depth
- `gate_correlation_access()` — correlation features
- `gate_sentiment_access()` — sentiment analysis depth
- `gate_ticker_dive_access()` — ticker deep dive
- `gate_weekly_wrap_access()` — weekly summaries
- `gate_replay_access()` — signal replay
- `gate_data_licensing()` — Enterprise data export
- `gate_sponsored_access()` — Enterprise sponsored signals
- `gate_sector_rotation_access()` — sector analysis
- `gate_unusual_activity()` — unusual options activity
- `gate_news_feed_access()` — news feed depth
- `gate_congress_tracker_access()` — congressional trading
- `gate_paper_leaderboard_access()` — paper trading leaderboard
- `gate_sports_betting_access()` — sports betting intel
- `gate_signal_quality_access()` — signal quality analytics dashboard
- `gate_backtest_access()` — backtest engine features: Pro (basic, 30d, 200 signals), Premium (+MC, walk-forward, risk, benchmark, 90d, 1000 signals), Ultra (+optimizer, comparison, saved strategies, export, 365d, 5000 signals)

---

## 9. Configuration Reference

All configuration via environment variables with `ROT_` prefix. Managed by Pydantic Settings in `src/rot/core/config.py`.

### Reddit (`ROT_REDDIT_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `CLIENT_ID` | `""` | Reddit API client ID |
| `CLIENT_SECRET` | `""` | Reddit API client secret |
| `USER_AGENT` | `"rot:v0.1 (by u_rotbot)"` | PRAW user agent |
| `SUBREDDITS` | `["wallstreetbets","stocks","options"]` | Subreddits to monitor |
| `LISTING` | `"hot"` | Listing type (hot/new/rising) |
| `LIMIT_PER_SUB` | `50` | Posts per subreddit per poll |
| `INCLUDE_COMMENTS` | `False` | Fetch top comments |
| `TOP_COMMENTS` | `10` | Number of comments to fetch |
| `POLL_INTERVAL_S` | `20` | Seconds between polls (loop mode) |

### LLM (`ROT_LLM_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `PROVIDER` | `"openai"` | LLM provider: openai, anthropic, deepseek |
| `API_KEY` | `""` | Provider API key |
| `MODEL` | `"gpt-4o-mini"` | Model name |
| `BASE_URL` | `None` | Custom API base URL |
| `MAX_TOKENS` | `1024` | Max response tokens |
| `TEMPERATURE` | `0.3` | Sampling temperature |

### Market (`ROT_MARKET_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_TTL_S` | `3600` | Market data cache TTL |
| `SYMBOL_CACHE_TTL_S` | `604800` | Symbol validation cache (7 days) |
| `MIN_MARKET_CAP` | `1e8` | Minimum market cap ($100M) |
| `ENABLE_OPTIONS_CHAIN` | `True` | Fetch options chain data |
| `OPTIONS_CACHE_TTL_S` | `1800` | Options data cache (30 min) |

### Trend (`ROT_TREND_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `WINDOW_S` | `1800` | Sliding window (30 min) |
| `THRESHOLD` | `0.01` | Minimum trend score |
| `COMMENT_WEIGHT` | `2.0` | Comment velocity weight vs score |
| `TOP_N` | `10` | Top N candidates per cycle |

### RSS (`ROT_RSS_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLED` | `False` | Enable RSS ingestion |
| `POLL_INTERVAL_S` | `300` | Default feed poll interval |
| `MAX_AGE_S` | `3600` | Max entry age |
| `SYNTHETIC_TREND_SCORE` | `0.5` | Default trend score for RSS |
| `MAX_ENTRIES_PER_FEED` | `50` | Max entries per feed |

### StockTwits (`ROT_STOCKTWITS_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLED` | `False` | Enable StockTwits |
| `SYMBOLS` | `["TSLA","AAPL","NVDA","SPY","QQQ","AMD","AMZN","MSFT"]` | Symbols to track |
| `TRENDING_ENABLED` | `True` | Include trending symbols |

### Twitter Ingest (`ROT_TWITTER_INGEST_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLED` | `False` | Enable Twitter ingestion |
| `BEARER_TOKEN` | `""` | Twitter API v2 bearer token |
| `CASHTAGS` | `["TSLA","AAPL","NVDA","SPY","QQQ"]` | Cashtags to track |
| `ACCOUNTS` | `["unusual_whales","zerohedge","DeItaone"]` | Accounts to follow |

### Twitter Poster (`ROT_TWITTER_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` / `API_SECRET` | `""` | Consumer credentials |
| `ACCESS_TOKEN` / `ACCESS_SECRET` | `""` | User credentials |
| `ENABLED` | `False` | Enable auto-posting |
| `INTERVAL_S` | `10800` | Min seconds between posts |
| `MIN_CONFIDENCE` | `0.5` | Min confidence to post |

### Email (`ROT_EMAIL_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `RESEND_API_KEY` | `""` | Resend HTTP API key (recommended) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | `""` | SMTP fallback |
| `FROM_ADDRESS` | `"ROT Alerts <alerts@rot.app>"` | Sender address |

### Auth (`ROT_AUTH_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | `""` | JWT signing secret (falls back to web.secret_key) |
| `JWT_ALGORITHM` | `"HS256"` | JWT algorithm |
| `JWT_EXPIRE_MINUTES` | `1440` | Token expiry (24h) |

### Stripe (`ROT_STRIPE_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `""` | Stripe secret key |
| `WEBHOOK_SECRET` | `""` | Stripe webhook signing secret |
| `PRO_PRICE_ID` / `PREMIUM_PRICE_ID` / `ULTRA_PRICE_ID` / `ENTERPRISE_PRICE_ID` | `""` | Stripe price IDs |

### Tier Limits (`ROT_TIER_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `FREE_SIGNAL_DELAY_S` | `900` | Free tier signal delay (15 min) |
| `FREE_PAGE_LIMIT` | `10` | Free tier max signals per page |
| `FREE_API_LIMIT_DAY` | `0` | Free tier API calls/day (blocked) |
| `PRO_API_LIMIT_DAY` | `1000` | Pro tier API calls/day |
| `PREMIUM_API_LIMIT_DAY` | `5000` | Premium tier |
| `ULTRA_API_LIMIT_DAY` | `25000` | Ultra tier |
| `ENTERPRISE_API_LIMIT_DAY` | `100000` | Enterprise tier |

### Web (`ROT_WEB_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `"0.0.0.0"` | Server bind host |
| `PORT` | `8000` | Server port |
| `SECRET_KEY` | `"change-me-in-production"` | Session/JWT fallback secret |

### ML Credibility (`ROT_ML_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLED` | `True` | Enable ML credibility scoring (falls back to heuristic when no model) |
| `MODEL_PATH` | `""` | Path to trained model pickle (auto-derived from storage_root if empty) |
| `MIN_TRAINING_SAMPLES` | `100` | Minimum resolved signals to start training |
| `RETRAIN_INTERVAL_S` | `86400` | Seconds between retrain attempts (24h) |
| `MIN_CLASS_SAMPLES` | `30` | Minimum samples per class (win/loss) to train |

### Feedback Engine (`ROT_FEEDBACK_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLED` | `True` | Enable feedback analysis background loop |
| `ANALYSIS_INTERVAL_S` | `21600` | Seconds between analysis cycles (6h) |
| `SUPPRESS_ENABLED` | `True` | Enable adaptive signal suppression (Stage 6.5) |
| `SUPPRESS_THRESHOLD` | `0.20` | Suppress categories with win rate below 20% |
| `SUPPRESS_SOURCE_THRESHOLD` | `0.15` | Suppress (event_type, source) combos below 15% |
| `MIN_SIGNALS_FOR_SUPPRESSION` | `30` | Minimum decided signals before suppression kicks in |
| `QUALITY_TREND_WINDOW_DAYS` | `30` | Days of history for quality trend analysis |

### Backtest Server (`ROT_BACKTEST_*`)
| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_SIGNALS` | `5000` | Max signals per backtest query |
| `MONTE_CARLO_SIMS` | `1000` | Number of Monte Carlo simulations |
| `WALK_FORWARD_FOLDS` | `5` | Number of walk-forward folds |
| `OPTIMIZER_MAX_COMBOS` | `500` | Max parameter combinations for optimizer |

### Global
| Variable | Default | Description |
|----------|---------|-------------|
| `ROT_STORAGE_ROOT` | `"storage"` | Root directory for all file storage |
| `ROT_DB_PATH` | `""` | SQLite DB path (auto-derived from storage_root if empty) |

---

## 10. External Integrations

### Reddit (PRAW)
- Polls subreddits via Reddit API (OAuth2)
- Requires `ROT_REDDIT_CLIENT_ID` and `ROT_REDDIT_CLIENT_SECRET`
- Fetches posts + optional top comments

### yfinance
- Market data enrichment: last close, 1d change, market cap
- Options chain data: ATM IV, put/call OI ratio
- Symbol validation (is this a real ticker?)
- Cached to reduce API calls

### OpenAI / Anthropic / DeepSeek
- LLM reasoning via `LLMClient` (provider-agnostic)
- System prompt + event prompt → structured JSON response
- Circuit breaker disables after 3 consecutive failures

### Stripe
- Subscription billing for 4 paid tiers
- Checkout session creation → hosted payment page
- Webhook handler for subscription lifecycle events
- Customer portal for self-service management

### Discord
- Webhook-based signal alerts
- Formatted embeds with signal data
- Configurable min confidence threshold

### Resend / SMTP
- Email alerts (daily digest + real-time)
- Resend HTTP API (primary) or SMTP (fallback)
- Per-user filter preferences (tickers, stances, event types)

### Twitter/X
- **Ingestion**: Twitter API v2 recent search (cashtags + accounts)
- **Posting**: OAuth 1.0a auto-posting of top signals

### StockTwits
- HTTP API polling for symbol streams + trending
- No API key required (public endpoints)

### RSS Feeds (Default 13+)
- MarketWatch, Investing.com, Yahoo Finance, CNBC, SeekingAlpha
- FDA (press releases, drug approvals, safety alerts, recalls, oncology)
- Federal Reserve (press releases)
- SEC (8-K filings)
- DoD (contracts, releases, news)
- BioPharma Dive, Drugs.com (approvals, trials)

---

## 11. Data Types & Models

### Core Pipeline Types (`src/rot/core/types.py`)

**Post** — Reddit post snapshot
```
id, created_utc, subreddit, title, selftext, url, score, num_comments,
upvote_ratio, author, permalink, flair, is_crosspost
```

**Comment** — Reddit comment
```
id, created_utc, author, body, score
```

**ThreadSnapshot** — Post + comments at a point in time
```
snapshot_ts, post, top_comments
```

**TrendCandidate** — Trending post with trend metrics
```
key, window_s, features (dict of float), trend_score, reason, snapshot
```

**Event** — Classified market event
```
event_type (6 types), entities (tickers), stance, time_horizon, evidence,
confidence (0-1), meta (dict with NLP data, market data, post metadata)
```
- EventType: `earnings_rumor | product_news | regulatory | squeeze_chatter | macro | other`
- Stance: `bullish | bearish | mixed | unknown`
- Horizon: `intraday | 1w | earnings | longer | unknown`

**ReasoningPacket** — LLM analysis output
```
thesis, catalyst_window, market_expectation, invalidations,
recommended_structures, risk_notes, raw (dict)
```

**TradeIdea** — Complete trade recommendation
```
underlying, strategy (6 types), legs (OptionLeg list), max_loss,
thesis, time_stop, quality_score, do_not_trade_reasons, meta
```
- Strategy: `debit_spread | credit_spread | iron_condor | calendar | straddle | strangle | none`

**OptionLeg** — Single options leg
```
side (buy/sell), kind (call/put), strike, expiry, qty
```

### NLP Types (`src/rot/nlp/types.py`)

**NLPResult** — Master NLP output
```
sentiment (SentimentResult), entities (ResolvedEntity list),
options_entities (OptionsEntity list), positions (PositionEntity list),
classifications (ClassifiedEvent list), temporal (TemporalResult),
thread (ThreadResult), ticker_symbols, primary_stance, primary_event_type,
token_count, processing_time_ms
```

**SentimentResult** — Sentiment analysis
```
polarity (-1 to +1), intensity (0-1), conviction (0-1),
sarcasm_probability (0-1), raw_signals (SentimentSignal list),
bullish_count, bearish_count, negated_count
```

**ResolvedEntity** — Ticker/financial entity
```
symbol, raw_text, resolution_method (cashtag/bare_ticker/implicit/sector/alias),
confidence (0-1), span, sentiment_toward (bullish/bearish/None)
```

**ClassifiedEvent** — Event category with confidence
```
category (14 types), confidence (0-1), evidence_spans, matched_terms
```

**TemporalResult** — Time analysis
```
dominant_tense (past/present/future/unknown), actionability (0-1),
urgency (0-1), time_expressions, tense_signals
```

**ThreadResult** — Comment consensus
```
consensus_polarity (-1 to +1), consensus_score (0-1),
agreement_with_op (0-1), contrarian_detected (bool),
top_comment_aligns (bool/None), comment_count_analyzed,
comment_analyses (CommentAnalysis list)
```

---

## 12. Deployment

### Railway (Production)
- **Docker**: Multi-stage build (builder + slim runtime)
- **Persistent Volume**: `/app/data` for SQLite database
- **Entry**: `python -m rot.app.server` (Procfile: `web: python -m rot.app.server`)
- **Health**: `GET /health` endpoint for Railway health checks

### Environment
- Python 3.12-slim base image
- `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`
- `ROT_STORAGE_ROOT=/app/data`, `ROT_WEB_HOST=0.0.0.0`
- Port from `$PORT` env var (Railway sets this)

### Dependencies (pyproject.toml)
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

## 13. Testing

**Framework:** pytest + pytest-asyncio
**Location:** `tests/`
**Run:** `pytest` from project root

### Test Files
| File | Tests |
|------|-------|
| `test_event_builder.py` | Event extraction, NLP vs legacy paths, entity extraction |
| `test_credibility.py` | All 12 heuristic credibility scoring factors |
| `test_ml_credibility.py` | ML feature extraction, ML scorer fallback, mock model inference |
| `test_trade_builder.py` | Trade strategy selection, liquidity gates, quality scoring |
| `test_database.py` | Schema creation, migrations, CRUD operations |
| `test_parser.py` | LLM response parsing, malformed JSON handling |
| `test_trend_engine_rss.py` | RSS trend detection, bypass logic |
| `test_rss_ingestor.py` | RSS feed parsing, dedup |
| `test_multi_ingestor.py` | Multi-source aggregation |
| `test_query_cache.py` | Dashboard query cache: TTL, invalidation, thundering herd, edge cases |
| `test_feedback.py` | Feedback analyzer (slope, MA, feature importance, suppression candidates), suppressor (category/source/low-confidence suppression, apply), tier gate tests |
| `test_backtest_types.py` | BacktestConfig validation, serialization, BacktestResult to_dict, TradeRecord/EquityPoint/DrawdownPeriod creation |
| `test_backtest_metrics.py` | Sharpe, Sortino, Calmar, max drawdown, drawdown periods, profit factor, win rate, VaR, CVaR, MAE/MFE, monthly returns |
| `test_backtest_engine.py` | Position sizing (fixed/Kelly/confidence), stop loss/take profit, concurrent limits, filters, stance-aware P&L |
| `test_backtest_monte_carlo.py` | Bootstrap resampling, percentile curves, reproducibility, probabilities |
| `test_backtest_risk.py` | VaR, CVaR, MAE/MFE, underwater analysis, Ulcer Index, skewness/kurtosis |
| `test_backtest_walk_forward.py` | Fold generation, IS/OOS split, stability scoring, degradation |
| `test_backtest_optimizer.py` | Grid generation, heatmap, max_combos cap, Sharpe ranking |
| `test_backtest_benchmark.py` | Alpha, beta, correlation, information ratio, benchmark curve |
| `test_backtest_comparator.py` | Correlation matrix, rankings, summary table, strategy stats |
| `test_backtest_tier_gate.py` | Free/Pro/Premium/Ultra/Enterprise tier access, feature hierarchy |
| `test_backtest_report.py` | CSV trade export, HTML report generation with risk/Monte Carlo sections |
| `conftest.py` | Shared fixtures |

### Test Patterns
- All existing tests must pass through both NLP and legacy paths
- Database tests use temporary SQLite files
- Async tests use `pytest-asyncio` with `asyncio_mode = "auto"`
- No external API calls in tests (mocked)

---

## 14. Key Design Patterns

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
After 3 consecutive LLM failures, the Reasoner automatically switches to stub reasoning (no API calls). This prevents cascading failures from taking down the pipeline.

### Informational-Only Sources
FDA, DoD, and pharma RSS feeds are classified as informational-only. They skip LLM reasoning and trade building (no trades generated), but are still stored as signals for the news feed and dashboard.

### Dedup at Multiple Levels
1. **SeenStore** — post-level dedup at ingestion (JSON file)
2. **Runner dedup** — (post_url, ticker) pair dedup at emission (in-memory, clears at 10k entries)
3. **DB unique index** — (post_url, ticker, created_at) prevents duplicate signals in storage

### ML/Heuristic Dual-Path Credibility Scoring
```python
class MLCredibilityScorer:
    def score(self, event):
        heuristic_result = self._heuristic.score(event)  # always runs
        if not self.ml_available:
            return heuristic_result
        return self._score_ml(event, heuristic_result)  # P(win) from model
```
The ML scorer trains live from historical win/loss outcomes in a background loop. If no model exists (insufficient data, first deployment), it falls back to the 12-factor heuristic. Both scores are stored in `meta["ml_credibility"]` for A/B comparison. The model hot-reloads after each retrain without server restart.

### Credibility as Confidence Adjustment (Heuristic Fallback)
The heuristic credibility scoring directly adjusts `event.confidence` by adding/subtracting factors. This means downstream consumers (Reasoner, TradeBuilder) always work with a single, pre-adjusted confidence value.

### Tier Gating as Dict Returns
Gate functions return dicts of boolean/numeric flags rather than raising exceptions. This allows templates to show/hide features granularly:
```python
access = gate_chart_access(user_tier)
if access["has_quadrant"]:
    render_quadrant_chart()
```

### JSON Blob Storage
Complex nested data (market data, reasoning, trade ideas, event metadata including NLP) is stored as JSON text columns in SQLite. This avoids schema complexity while keeping data queryable via JSON functions.

### Precomputed Feedback Analysis
The feedback engine (`src/rot/feedback/`) runs expensive DB queries in a background loop every 6h, caching results in memory. The Signal Quality dashboard reads cached results instantly (no DB query on page load). The suppressor reads the same cache from the sync pipeline thread (GIL-safe dict read, no locks needed). First deployment: no analysis cached = suppressor never suppresses = identical behavior to before.

### Dashboard Query Cache
The dashboard loads 12+ database queries per page view. To avoid hammering the DB on every request, an async in-memory TTL cache (`src/rot/web/query_cache.py`) is used:
- **Cached (10 queries)**: trending tickers (30s), performance summary (120s), strategy breakdown (120s), chart data (60s), time series (60s), accuracy stats (120s), leaderboard (30s), heatmaps (120s), correlations (120s), landing page stats (300s)
- **NOT cached (2 queries)**: user-filtered signals, per-user signal count badge
- **Invalidation**: When a new signal arrives, fast-changing caches (trending, leaderboard) are invalidated via prefix matching. Slow-changing caches (accuracy, heatmaps) expire naturally via TTL.
- **Thundering herd prevention**: Per-key `asyncio.Lock` ensures only one coroutine fetches when multiple requests arrive for the same stale key.

---

## 15. File Tree

```
rot/
├── CLAUDE.md                          ← YOU ARE HERE
├── Dockerfile                         # Multi-stage Docker build
├── Procfile                           # Railway: web: python -m rot.app.server
├── pyproject.toml                     # Package config, dependencies, tool config
├── src/
│   └── rot/
│       ├── __init__.py
│       ├── core/
│       │   ├── config.py              # Pydantic Settings (15 config sections)
│       │   ├── types.py               # Frozen dataclasses (10 types)
│       │   └── logging.py             # JSONL structured logging
│       ├── ingest/
│       │   ├── reddit_ingestor.py     # PRAW Reddit polling
│       │   ├── rss_ingestor.py        # feedparser RSS polling (13+ feeds)
│       │   ├── stocktwits_ingestor.py # StockTwits HTTP API
│       │   ├── twitter_ingestor.py    # Twitter API v2
│       │   ├── multi_ingestor.py      # Multi-source aggregator
│       │   └── seen_store.py          # JSON dedup store
│       ├── trend/
│       │   ├── trend_engine.py        # Sliding window trend detection
│       │   ├── trend_store.py         # JSON trend state persistence
│       │   ├── ranker.py              # Top-N ranking
│       │   └── ticker_ranker.py       # Per-ticker Top-N ranking
│       ├── nlp/                       # ★ CUSTOM NLP ENGINE (10 modules)
│       │   ├── __init__.py            # Re-exports NLPEngine, NLPResult
│       │   ├── types.py               # All NLP dataclasses
│       │   ├── tokenizer.py           # Financial-aware tokenizer
│       │   ├── lexicon.py             # 500+ term sentiment dictionary
│       │   ├── sentiment.py           # Sentiment + sarcasm detection
│       │   ├── entities.py            # Entity resolution (tickers, CEOs, sectors)
│       │   ├── classifier.py          # 14-category event classification
│       │   ├── temporal.py            # Tense, actionability, urgency
│       │   ├── thread.py              # Comment consensus analysis
│       │   └── engine.py              # Orchestrator: analyze() → NLPResult
│       ├── extract/
│       │   ├── event_builder.py       # Dual-path event extraction (NLP/legacy)
│       │   └── enricher.py            # Ticker aliases, blocklists
│       ├── credibility/
│       │   ├── scorer.py              # 12-factor heuristic credibility scoring
│       │   ├── ml_scorer.py           # ML-based scorer (GradientBoosting) with heuristic fallback
│       │   ├── features.py            # 32-feature extraction for ML (inference + training)
│       │   └── train.py               # Live training from DB win/loss outcomes
│       ├── feedback/
│       │   ├── __init__.py            # Exports FeedbackAnalyzer, SignalSuppressor
│       │   ├── analyzer.py            # Category performance, source reliability, feature importance, quality trends, suppression candidates
│       │   └── suppressor.py          # Adaptive signal suppression (Stage 6.5)
│       ├── reasoner/
│       │   ├── reasoner.py            # LLM orchestrator + circuit breaker
│       │   ├── llm_client.py          # Provider-agnostic LLM client
│       │   ├── prompts.py             # System prompt + event template
│       │   ├── parser.py              # LLM JSON response parser
│       │   └── ai_summary.py          # AI signal summaries
│       ├── market/
│       │   ├── trade_builder.py       # IV-aware strategy builder
│       │   ├── enricher.py            # yfinance market data
│       │   ├── symbol_validator.py    # Ticker validation
│       │   ├── price_checker.py       # Performance price tracking
│       │   └── gates.py               # Trade safety gates
│       ├── backtest/                   # ★ BACKTESTING ENGINE (12 modules)
│       │   ├── __init__.py            # Exports BacktestConfig, BacktestEngine, BacktestResult
│       │   ├── config.py              # BacktestConfig frozen dataclass
│       │   ├── result.py              # TradeRecord, EquityPoint, DrawdownPeriod, BacktestResult
│       │   ├── metrics.py             # Pure metric functions (Sharpe, VaR, drawdown, etc.)
│       │   ├── engine.py              # Core engine: stance-aware P&L, position sizing
│       │   ├── monte_carlo.py         # Bootstrap Monte Carlo simulation
│       │   ├── risk.py                # Comprehensive risk analytics
│       │   ├── walk_forward.py        # Walk-forward IS/OOS validation
│       │   ├── optimizer.py           # Parameter grid search optimization
│       │   ├── benchmark.py           # SPY benchmark comparison
│       │   ├── comparator.py          # Strategy comparison
│       │   └── report.py              # CSV/HTML report generation
│       ├── storage/
│       │   └── database.py            # aiosqlite, 17+ tables, migrations
│       ├── alerts/
│       │   ├── dispatcher.py          # Multi-channel alert router
│       │   ├── discord.py             # Discord webhooks
│       │   ├── email.py               # Resend + SMTP email
│       │   ├── twitter.py             # Twitter/X auto-posting
│       │   └── webhook.py             # Custom webhooks
│       ├── app/
│       │   ├── main.py                # One-shot entry point
│       │   ├── loop.py                # Continuous loop entry point
│       │   ├── runner.py              # PipelineRunner (8-stage orchestrator)
│       │   └── server.py              # FastAPI factory + background loop
│       └── web/
│           ├── auth.py                # JWT + API key + session auth
│           ├── query_cache.py         # Async TTL cache for dashboard queries
│           ├── tier_gate.py           # 5-tier feature gating (30+ gates)
│           ├── rate_limit.py          # Per-tier rate limiting
│           ├── routes/                # 35+ route files (50+ endpoints)
│           │   ├── dashboard.py       # Main dashboard + auth pages
│           │   ├── signals.py         # Signal CRUD API
│           │   ├── auth_routes.py     # Auth endpoints
│           │   ├── stripe_routes.py   # Billing endpoints
│           │   ├── paper_trading.py   # Paper trading
│           │   ├── performance.py     # Analytics
│           │   ├── sentiment.py       # Sentiment heatmap
│           │   ├── correlations.py    # Correlation matrix
│           │   ├── congress_tracker.py # Congressional trading
│           │   ├── sports_tracker.py  # Sports betting intel
│           │   ├── enterprise.py      # Enterprise features
│           │   ├── export.py          # Data export
│           │   ├── news_feed.py       # News feed
│           │   ├── websocket.py       # WebSocket real-time stream
│           │   └── ... (20+ more)
│           └── templates/             # 39+ Jinja2 HTML templates
│               ├── base.html          # Base layout (Tailwind + Chart.js + HTMX)
│               ├── dashboard.html     # Main dashboard
│               ├── signal_detail.html # Signal detail view
│               ├── pricing.html       # Pricing page
│               ├── backtest.html      # Backtest config form + saved runs
│               ├── backtest_result.html  # Backtest results with KPI cards, equity curve, trade log
│               ├── backtest_compare.html # Strategy comparison page
│               ├── backtest_monte_carlo_partial.html  # HTMX partial: Monte Carlo results
│               ├── backtest_optimize_partial.html     # HTMX partial: optimizer results
│               ├── backtest_walk_forward_partial.html  # HTMX partial: walk-forward results
│               └── ... (35+ more)
└── tests/
    ├── conftest.py                    # Shared fixtures
    ├── test_event_builder.py
    ├── test_credibility.py
    ├── test_trade_builder.py
    ├── test_database.py
    ├── test_parser.py
    ├── test_trend_engine_rss.py
    ├── test_rss_ingestor.py
    ├── test_multi_ingestor.py
    ├── test_query_cache.py
    ├── test_feedback.py
    ├── test_backtest_types.py         # Config, result, dataclass tests
    ├── test_backtest_metrics.py       # Metric function tests
    ├── test_backtest_engine.py        # Engine simulation tests
    ├── test_backtest_monte_carlo.py   # Monte Carlo tests
    ├── test_backtest_risk.py          # Risk analytics tests
    ├── test_backtest_walk_forward.py  # Walk-forward tests
    ├── test_backtest_optimizer.py     # Optimizer tests
    ├── test_backtest_benchmark.py     # Benchmark comparison tests
    ├── test_backtest_comparator.py    # Strategy comparator tests
    ├── test_backtest_tier_gate.py     # Tier gating tests
    └── test_backtest_report.py        # Report generation tests
```

---

## Credibility Scoring Factors (Detailed)

For reference, the 12 factors in `CredibilityScorer.score()`:

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

---

## LLM Reasoning Prompt Structure

The LLM receives two parts via `src/rot/reasoner/prompts.py`:

### System Prompt
Instructs the LLM to output structured JSON with fields: `event_type`, `stance`, `time_horizon`, `confidence` (calibrated 0.0-1.0), `thesis`, `catalyst_window`, `market_expectation`, `invalidations`, `recommended_structures`, `risk_notes`.

Key calibration rules:
- 0.10-0.25: Speculative, no data
- 0.25-0.40: Some reasoning, unverified
- 0.40-0.55: Solid thesis with real data
- 0.55-0.70: Strong thesis + market confirmation
- 0.70-0.85: Multi-source corroboration
- 0.85-1.00: Officially confirmed events
- Hard cap: squeeze_chatter never > 0.65
- Hard cap: nothing > 0.85 unless officially confirmed
- Subreddit discounts: WSB/shortsqueeze/pennystocks: -0.05 to -0.10
- RSS boost: +0.05 to +0.10 vs equivalent Reddit post
- Market contradiction: -0.10 to -0.20

### Event Prompt (template)
Contains: ticker(s), subreddit + credibility tier, post title/body, engagement metrics, author info, trend metrics (score/velocity), NLP analysis section (polarity, conviction, sarcasm, classifications, tense, thread consensus, per-ticker sentiment), market context (price, change, cap, IV, put/call ratio).

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2025 | Initial CLAUDE.md creation — comprehensive architecture documentation | Claude Agent |
| 2025 | Dashboard query cache engine — `query_cache.py`: async TTL cache with per-key TTL, thundering-herd prevention, prefix invalidation. Caches 10 of 12 dashboard queries (trending, accuracy, leaderboard, charts, heatmaps, correlations). Signal-triggered invalidation for fast-changing data. | Claude Agent |
| 2026-02 | Add ML credibility scorer — GradientBoosting replaces heuristic, live retrain loop, 32-feature extraction, heuristic fallback | Claude Agent |
| 2026-02 | Signal feedback engine — `src/rot/feedback/`: FeedbackAnalyzer (category performance, source reliability, ML feature importance, quality trends, suppression candidates, confidence calibration), SignalSuppressor (Stage 6.5 adaptive suppression saving LLM costs), Signal Quality dashboard (`/signal-quality`, Pro+ gated), FeedbackConfig, 39 new tests (161 total) | Claude Agent |
| 2026-02 | Strategy Backtesting Engine — `src/rot/backtest/`: 12 modules (config, result, metrics, engine, monte_carlo, risk, walk_forward, optimizer, benchmark, comparator, report). Full portfolio simulation with stance-aware P&L (mirrors DB logic), 3 position sizing modes (fixed/Kelly/confidence-weighted), stop loss/take profit, Monte Carlo bootstrap (fan chart + probabilities), walk-forward IS/OOS validation with stability scoring, parameter grid search optimization with heatmap, risk analytics (VaR, CVaR, MAE/MFE, Ulcer Index, skewness/kurtosis), SPY benchmark comparison (alpha, beta, info ratio), strategy comparison. 10 HTMX-powered routes, 6 templates, 2 DB tables (backtest_runs, backtest_strategies), `gate_backtest_access()` tier gate (Pro+ tiered features), `BacktestServerConfig`, CSV/HTML report export. Backtest nav expanded from Ultra-only to Pro+. 253 new tests (423 total). | Claude Agent |

> **REMINDER**: If you've made changes to this codebase, update this document NOW.
> Add your changes to the Change Log and update any affected sections.
