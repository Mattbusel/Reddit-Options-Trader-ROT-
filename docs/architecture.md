<!-- Full architecture reference. Generated 2026-03-17. -->
# ROT System Architecture

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        INGESTION LAYER                                          │
│                                                                                 │
│   ┌──────────────┐   ┌──────────────┐   ┌─────────────┐   ┌─────────────────┐  │
│   │    Reddit     │   │   RSS Feeds  │   │  StockTwits │   │    Twitter/X    │  │
│   │  (PRAW)      │   │  (13+ feeds) │   │  (optional) │   │   (optional)    │  │
│   └──────┬───────┘   └──────┬───────┘   └──────┬──────┘   └────────┬────────┘  │
│          └──────────────────┴──────────────────┴───────────────────┘           │
│                                      │                                          │
│                              ┌───────▼───────┐                                 │
│                              │  Deduplicator  │  (seen_store, max 2,000 IDs)    │
│                              └───────┬───────┘                                 │
└──────────────────────────────────────┼──────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          TREND DETECTION                                         │
│                                                                                  │
│   TrendEngine: score velocity + comment velocity + engagement acceleration       │
│   → emits TrendCandidate when thresholds exceeded                                │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          NLP PIPELINE  (10 modules)                              │
│                                                                                  │
│  Tokenizer → Lexicon(500+) → Sentiment → EntityExtractor → TickerExtractor      │
│      → EventClassifier(14 categories) → SarcasmDetector → TemporalParser        │
│          → ThreadAnalyzer → NLPEngine (orchestrator) → NLPResult                │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         EVENT BUILDER                                            │
│                                                                                  │
│  Dual-path: NLP engine (primary) + regex fallback                                │
│  Outputs structured Event objects with tickers, event_type, sentiment            │
│  Alias normalization (SPXW→^GSPC), blocklist filtering, multi-ticker support    │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                       MARKET ENRICHMENT                                          │
│                                                                                  │
│  yfinance: price, market cap, volume, IV, options chain (cached, 1h TTL)        │
│  symbol_validator: gate on $100M min market cap, blocklists, delisted check     │
│  price_checker: async batch polling every 5 min for signal performance tracking │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                      CREDIBILITY SCORER                                          │
│                                                                                  │
│  ML scorer: GradientBoosting (32 features), trained on resolved signals         │
│  Heuristic scorer: 12 factors — DD flair, engagement quality, cross-post        │
│  penalty, ticker focus, text depth, author history, subreddit weight            │
│  Output: credibility score 0.0–1.0; both scores in meta["ml_credibility"]      │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   ADAPTIVE SUPPRESSION (Stage 6.5)                               │
│                                                                                  │
│  FeedbackEngine: analyzes win/loss by event_type and (event_type, source) pairs │
│  Suppresses categories with win_rate < 20%; source combos with win_rate < 15%   │
│  Requires minimum 30 resolved signals before suppression activates              │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         LLM REASONER                                             │
│                                                                                  │
│  Provider-agnostic: OpenAI / Anthropic / DeepSeek (ROT_LLM_PROVIDER)           │
│  Circuit breaker: disables after 3 consecutive failures → stub reasoning        │
│  Outputs ReasoningPacket: thesis, risks, context, conviction score              │
│  Informational sources (FDA/DoD/pharma) skip LLM reasoning entirely            │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          TRADE IDEA BUILDER                                      │
│                                                                                  │
│  6 strategies: bull call spread, bear put spread, straddle, strangle,           │
│  long call, long put — selected by stance + IV context                          │
│  Strike selection: ATM ±5%, weekly/monthly expiry heuristics                   │
│  Gates: min $100M market cap, data availability, IV availability                │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                      STORAGE + WEB API                                           │
│                                                                                  │
│  SQLite (WAL mode) via aiosqlite, 33+ tables                                    │
│  FastAPI: 100+ endpoints, JWT/API-key/session-cookie auth, 5-tier gating        │
│  WebSocket /api/v1/signals/live for real-time signal feed                       │
│  OpenAPI Swagger UI at /docs, ReDoc at /redoc                                   │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            ALERTS                                                │
│                                                                                  │
│  Dispatcher: Discord webhooks, email (Resend / SMTP), Twitter/X                 │
│  Fires only on high-confidence signals (configurable threshold, default 0.6)    │
│  Rich embeds: ticker, stance, confidence, strategy, option legs, catalyst       │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Layer Descriptions

### Ingestion Layer

The ingestion layer pulls raw content from Reddit (via PRAW), 13+ RSS feeds (MarketWatch, CNBC, Yahoo Finance, SEC, FDA, DoD, Federal Reserve, SeekingAlpha), StockTwits, and optionally Twitter/X. Posts pass through an in-memory deduplicator (seen_store, capped at 2,000 IDs) to prevent duplicate processing across polling cycles. Each source adapter normalizes its output to a common `Post` dataclass before emitting to the pipeline.

### Trend Detection

The trend engine ranks incoming posts by momentum rather than raw mention count. It calculates score velocity, comment velocity, and engagement acceleration over a configurable rolling window (default 30 minutes). When a post crosses the trend threshold, the engine emits a `TrendCandidate` object that carries the original post plus a numeric trend_score used downstream for confidence weighting. RSS and institutional feeds bypass trend scoring with a fixed synthetic trend_score.

### NLP Pipeline (10 modules)

The custom NLP engine processes each post through ten sequential modules: tokenizer, lexicon lookup (500+ financial terms), sentiment analysis, named entity extraction, ticker extraction and validation, event classification into 14 categories, sarcasm detection, temporal phrase parsing, thread context analysis, and a top-level orchestrator that assembles an `NLPResult`. Ticker extraction applies aggressive filtering — blocklists for macro noise (SPY, QQQ), non-equities, slang, and delisted symbols — followed by alias normalization. The full NLP path is preferred; a regex fallback handles edge cases when the NLP engine is unavailable.

### Event Builder

The event builder transforms raw NLP output into structured `Event` objects with a canonical schema: ticker(s), event_type (earnings_rumor / product_news / regulatory / squeeze_chatter / macro / other), sentiment (bullish / bearish / mixed / unknown), and time_horizon (intraday / 1w / earnings / longer / unknown). Dual-path design: NLP primary path, regex legacy fallback. The enricher sub-module applies blocklists and alias normalization so that every Event exits with validated, normalized tickers.

### Market Enrichment

The market enrichment layer fetches live price, market cap, trading volume, implied volatility, and options chain data via yfinance, with local caching (1-hour TTL for prices, 7-day TTL for symbol validation). The symbol validator gates each ticker against a $100M minimum market cap threshold and cross-references against a blocklist of invalid or delisted symbols. The price checker runs a background batch loop every 5 minutes to track post-signal price moves (1h, 4h, 1d, 1w deltas) needed for win/loss attribution.

### Credibility Scorer

The credibility scorer combines a GradientBoosting ML model (32 input features trained on resolved signals from the database) with a deterministic heuristic scorer covering 12 factors including DD flair detection, engagement quality, cross-posting penalties, ticker focus ratio, text depth, and author history. When the ML model is unavailable (e.g., insufficient training data), the heuristic scorer is used as fallback. Both scores are stored alongside every signal in `meta["ml_credibility"]` for auditability.

### Adaptive Suppression

The feedback engine runs every 6 hours in the background, analyzing historical win/loss outcomes to identify systematically underperforming signal categories. Categories with a win rate below 20% are suppressed; specific (event_type, source) combinations with a win rate below 15% are suppressed at the source level. Suppression does not activate until at least 30 resolved signals are available per category, preventing premature filtering on limited samples. Suppression state is stored in the database and applied at Stage 6.5 in the pipeline.

### LLM Reasoner

The reasoning layer sends enriched event context to a configurable LLM provider (OpenAI, Anthropic, or DeepSeek) for thesis synthesis, risk enumeration, and conviction scoring. A circuit breaker pattern auto-disables the LLM after 3 consecutive failures and substitutes a deterministic stub reasoner so the pipeline continues without interruption. Informational-only sources (FDA, DoD, pharma regulatory feeds) skip LLM reasoning entirely and proceed directly to storage as research signals rather than trade candidates.

### Trade Idea Builder

The trade builder converts a reasoned `Event` into a structured `TradeIdea` with explicit option legs, strike prices, expiry dates, max loss estimates, and a quality score. Six strategies are supported: bull call spread, bear put spread, straddle, strangle, long call, and long put — selected based on stance and IV context. Strike selection uses ATM ±5% heuristics with weekly expiry for short-horizon signals and monthly expiry for longer horizons. Minimum market cap and data availability gates prevent trade idea generation for illiquid or data-poor symbols.

### Web API

The FastAPI application exposes 100+ endpoints covering signals, authentication, analytics, backtesting, paper trading, enterprise exports, and administration. All responses carry a request ID and correlation ID for distributed tracing. Authentication supports JWT bearer tokens, API key headers (`X-API-Key`), and session cookies. A five-tier subscription hierarchy (Free → Pro → Premium → Ultra → Enterprise) gates feature access via 35+ declarative gate functions. A WebSocket endpoint streams live signals to connected dashboard clients in real time.

### Alerts

The alert dispatcher evaluates completed signals against a configurable minimum confidence threshold (default 0.6) and fires notifications to Discord (rich embeds), email (via Resend API or SMTP), and Twitter/X. Alert content includes the ticker, directional stance, confidence score, options strategy, individual option legs, identified catalyst, and suggested time window. Each alert channel has independent enable/disable control via environment variables.

---

## Data Flow: Raw Reddit Post to Structured Trade Idea

The following traces a single Reddit post from ingestion to a stored trade idea.

1. **Ingestion** — PRAW streams a post from r/wallstreetbets: "NVDA is about to moon — earnings beat incoming." The `RedditIngestor` constructs a `Post` dataclass with id, title, body, score, comment_count, subreddit, url, and created_at timestamp.

2. **Deduplication** — The `SeenStore` checks the post's URL+ticker composite key against the in-memory set. If unseen, the post proceeds; otherwise it is dropped.

3. **Trend Detection** — `TrendEngine` computes score velocity for NVDA-mentioning posts in the last 30 minutes. The post's engagement exceeds the threshold (default 0.01), so a `TrendCandidate` is emitted with trend_score=0.72.

4. **NLP Analysis** — The 10-module pipeline tokenizes the title, finds `NVDA` via ticker extraction, scores sentiment as bullish (lexicon hit on "moon"), classifies event_type as earnings_rumor, infers time_horizon=earnings from "earnings beat incoming," and returns an `NLPResult`.

5. **Event Building** — `EventBuilder` assembles an `Event`: ticker=NVDA, event_type=earnings_rumor, stance=bullish, time_horizon=earnings, source=reddit/wallstreetbets. Alias normalization confirms NVDA is the canonical symbol.

6. **Market Enrichment** — `MarketEnricher` fetches NVDA price ($875.40), market cap ($2.15T), 30-day IV rank (72nd percentile), and the near-term options chain. Market cap gate passes ($2.15T >> $100M floor).

7. **Credibility Scoring** — The heuristic scorer awards points for bullish stance, high engagement (1,200 upvotes, 340 comments), recognized subreddit, and adequate text depth. The GradientBoosting model evaluates 32 features. Final credibility score: 0.81.

8. **Adaptive Suppression** — The feedback engine checks whether earnings_rumor/reddit has been suppressed. Win rate is 38%, above the 20% threshold, so the signal passes.

9. **LLM Reasoning** — The reasoner sends event context to the configured LLM. The model returns: thesis ("IV rank elevated ahead of earnings; options pricing suggests 6% implied move"), risks ("guidance miss would collapse IV rapidly"), conviction=high. Circuit breaker remains closed (no recent failures).

10. **Trade Idea Generation** — With bullish stance and elevated IV, `TradeBuilder` selects a bull call spread: buy NVDA $880C expiry Friday, sell NVDA $900C expiry Friday. Max loss = premium paid, quality_score = 0.79.

11. **Storage** — The complete signal (Event + market_data + ReasoningPacket + TradeIdea) is written to the `signals` table. A `signal_performance` row is initialized with price_at_signal=$875.40.

12. **Delivery** — The WebSocket dispatcher pushes the new signal to all connected dashboard clients. The alert dispatcher checks confidence (0.81 > 0.60 threshold) and fires a Discord embed with ticker, stance, strategy, and option legs.

13. **Performance Tracking** — The price checker polls NVDA at t+1h, t+4h, t+1d, t+1w, updating `signal_performance`. After resolution, NVDA +7.2% → win (>5% threshold for bullish). The ML model retrains on this resolved signal in the next 24-hour cycle.

---

## Database Schema Summary

The database is a single SQLite file in WAL mode, accessed via aiosqlite. All tables are created idempotently on connection. Path defaults to `{ROT_STORAGE_ROOT}/rot.db`.

### Core Signal Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `signals` | Live signal storage (14-day retention) | id, ticker, event_type, stance, confidence, quality_score, strategy, market_data (JSON), reasoning (JSON), trade_idea (JSON), event_data (JSON) |
| `signal_performance` | Price tracking for win/loss attribution | signal_id, price_at_signal, price_1h, price_4h, price_1d, price_1w, max_gain_pct, max_loss_pct |
| `signal_archive` | Long-term flat archive (365-day retention) | Denormalized copy of signals JOIN signal_performance, archived before 14-day purge |

### User and Auth Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `users` | User accounts | id, email, password_hash (bcrypt), api_key_hash (SHA-256), tier, settings (JSON) |
| `subscriptions` | Stripe subscription state | user_id, stripe_customer_id, stripe_subscription_id, tier, status, current_period_end |
| `api_usage` | Per-user API rate limiting | user_id, date, call_count |

### Trading Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `paper_portfolios` | Per-user paper trading balance | user_id, balance, total_trades, winning_trades, total_pnl |
| `paper_trades` | Individual paper trade records | user_id, signal_id, ticker, entry_price, exit_price, pnl_dollars, pnl_pct, status |
| `backtest_runs` | Saved backtest results | id, user_id, name, config_json, result_json, monte_carlo_json, risk_json |
| `backtest_strategies` | Named backtest strategies | id, user_id, name, config_json, last_result_json, is_active |

### Analytics and Feature Tables

| Table | Purpose |
|-------|---------|
| `unusual_events` | Unusual options activity (IV spikes, volume surges, sweeps) |
| `win_rate_snapshots` | Periodic win-rate aggregation snapshots |
| `congress_trades` | Congressional trading tracker data |
| `email_alert_settings` | Per-user alert preferences |
| `x_posts` | Twitter/X posting history |
| `referral_clicks` / `referral_conversions` | Affiliate tracking |
| `sponsored_signals` | Enterprise sponsored analysis submissions |
| `data_exports` | Enterprise export requests |
| `export_schedules` | Scheduled recurring exports |

### Unified CTE Pattern

Analytics queries use a `_UNIFIED_CTE` that unions live `signals JOIN signal_performance` with `signal_archive`, providing seamless access to both recent and historical data through a single query surface. Win/loss is computed as: bullish + max_gain_pct >= 5% = win; bullish + max_loss_pct >= 5% = loss. Mixed/unknown stance = neutral (not counted as trades).

---

## Security Architecture Summary

### Authentication (3 methods, priority order)

1. **JWT Bearer Token** — `Authorization: Bearer <token>` header. Tokens signed with HS256 using `ROT_AUTH_JWT_SECRET`. Claims: sub, email, tier, exp (24-hour expiry). Used by API clients and programmatic access.
2. **API Key Header** — `X-API-Key: rot_<token>` header. Keys stored as SHA-256 hashes in `users.api_key_hash`. Generated on demand via `POST /auth/api-key`. Requires Pro tier or above.
3. **Session Cookie** — `rot_session` cookie containing a JWT. Used by the web dashboard for browser sessions.
4. **Anonymous** — Free tier with time-delayed signals and page-count limits.

### Authorization (5-tier hierarchy)

```
Free → Pro → Premium → Ultra → Enterprise → Admin (hidden, ROT_AUTH_ADMIN_EMAILS)
```

Gate functions in `tier_gate.py` return dicts of feature flags rather than raising exceptions, allowing partial access to be rendered gracefully. Admin tier bypasses all gates.

### Injection Prevention

All database queries use parameterized statements. Dynamic `UPDATE` queries use a field whitelist to prevent column-name injection. JSON blob storage for nested data avoids SQL expression injection entirely.

### XSS Prevention (3-layer)

1. Jinja2 autoescape enabled globally on all templates.
2. `nh3` (Rust-based HTML sanitizer) applied to any content marked `|safe` in templates.
3. Content Security Policy header restricts script sources and blocks inline execution where feasible.

### CSRF Protection

Custom ASGI middleware performs timing-safe HMAC comparison on state tokens for all state-mutating requests.

### Security Headers (6 headers on all responses)

| Header | Value |
|--------|-------|
| Content-Security-Policy | default-src 'self'; restricts scripts, styles, images, WebSocket |
| X-Content-Type-Options | nosniff |
| X-Frame-Options | DENY |
| Referrer-Policy | strict-origin-when-cross-origin |
| X-XSS-Protection | 0 (legacy filter disabled per OWASP guidance) |
| Permissions-Policy | camera=(), microphone=(), geolocation=(), payment=(self) |

### Rate Limiting

Database-backed per-user rate limiting (multi-instance safe via `api_usage` table). Daily limits by tier: Free=0 (API blocked), Pro=1,000, Premium=5,000, Ultra=25,000, Enterprise=100,000, Admin=unlimited. Brute-force protection on authentication endpoints.

### Security Logging

Ten SIEM-ready JSON event types logged via `security_logger.py`: auth success/failure, privilege escalation attempt, rate limit breach, suspicious payload, admin action, tier gate violation, API key generation, password change, Stripe webhook failure. All log output passes through a `SanitizingLogFilter`. Request IDs (UUID4) correlate log lines across the pipeline.
