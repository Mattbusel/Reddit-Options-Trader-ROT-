# Web Layer, Auth & Tier Gating — ROT Architecture Reference

> Part of the ROT documentation suite. See [CLAUDE.md](../CLAUDE.md) for the full index.

## Quick Start for Agents

- Key file(s): `src/rot/web/routes/` (35+ route files), `src/rot/web/auth.py`, `src/rot/web/tier_gate.py`, `src/rot/web/query_cache.py`
- Key pattern: FastAPI + Jinja2 + Tailwind CSS + HTMX, tier-gated features via dict-returning gate functions, JWT + API key + session cookie auth
- Factory: `src/rot/web/server.py` creates the FastAPI app, mounts all route modules

---

## Framework Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI |
| Templates | Jinja2 |
| CSS | Tailwind CSS |
| Charts | Chart.js (self-hosted) |
| Interactivity | HTMX + HTMX-ws (self-hosted) |
| Static files | `/static/js/` (Chart.js, HTMX, HTMX-ws) |
| Compression | GZipMiddleware (minimum_size=500) |

---

## Route Inventory (50+ endpoints across 35+ route files)

### Core Dashboard

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Landing page (or redirect to dashboard if logged in) |
| GET | `/dashboard` | Main signal dashboard |
| GET | `/dashboard/signal/{signal_id}` | Signal detail view |
| GET | `/pricing` | Pricing page with tier comparison |
| GET | `/account` | Account settings |

### Authentication (`/auth/`)

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

### Signals API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/signals` | List signals (JSON, filterable, paginated) |
| GET | `/signals/new-count` | Count new signals since timestamp |
| GET | `/signals/{signal_id}` | Single signal detail |
| GET | `/tickers/trending` | Trending tickers |
| POST | `/signals/{signal_id}/reason` | Add reasoning note |
| GET | `/signals/export` | Export signals (CSV/JSON) |

### Performance & Analytics

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

### Visualization Pages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sentiment` | Sentiment heatmap |
| GET | `/correlations` | Ticker correlations (pairs, clusters, lead-lag, network) |
| GET | `/api/v1/correlations/matrix` | Correlation matrix JSON API |
| GET | `/api/v1/correlations/{ticker}` | Per-ticker correlations JSON API |
| GET | `/api/v1/correlations/clusters` | Cluster analysis JSON API |
| GET | `/api/v1/correlations/lead-lag` | Lead-lag relationships JSON API |
| GET | `/sector-rotation` | Sector rotation dashboard (rankings, flow, gauges) |
| GET | `/sector-rotation/drill-down/{sector}` | HTMX partial: ticker breakdown within sector |
| GET | `/api/v1/sectors/rankings` | Sector rankings JSON API |
| GET | `/unusual-activity` | Unusual activity dashboard (events, timeline, filters) |
| GET | `/api/v1/unusual-activity` | Unusual events JSON API |
| GET | `/api/v1/unusual-activity/summary` | Aggregate unusual activity stats |
| GET | `/api/v1/unusual-activity/timeline/{ticker}` | Per-ticker unusual event timeline |
| GET | `/signal-quality` | Signal quality dashboard (Pro+) |
| GET | `/ticker/{symbol}` | Ticker deep dive |
| GET | `/news` | News feed |

### Trading Features

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

### Data & Tracker Pages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/congress-tracker` | Congressional trading tracker |
| GET | `/sports-tracker` | Sports betting intel |
| GET | `/ceo-rap-sheet` | CEO controversies |
| GET | `/hall-of-legends` | Top performer history |
| GET | `/wall-of-shame` | Pump & dump tracker |

### Billing (Stripe, prefix: `/api/v1/billing/`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/checkout` | Create Stripe checkout session |
| POST | `/webhook` | Stripe webhook handler |
| GET | `/portal` | Stripe customer portal |
| GET | `/status` | Subscription status |

### Enterprise (`/enterprise`, `/api/v1/enterprise/`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/enterprise` | Enterprise dashboard (analytics, exports, lineage, schedules) |
| POST | `/api/v1/enterprise/data-export` | Request data export (CSV/JSON, optional lineage) |
| POST | `/api/v1/enterprise/sponsored/submit` | Submit sponsored signal |
| GET | `/api/v1/enterprise/sponsored/status` | Sponsored signal status |
| GET | `/api/v1/enterprise/usage` | Enterprise usage stats |
| GET | `/api/v1/enterprise/analytics/overview` | Analytics overview (7d signals, confidence, win rate) |
| GET | `/api/v1/enterprise/lineage/{signal_id}` | Signal lineage/provenance chain |

### Misc

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

## Route Files

| File | Routes Covered |
|------|---------------|
| `dashboard.py` | Main dashboard, auth pages, landing |
| `signals.py` | Signal CRUD API |
| `auth_routes.py` | Auth endpoints |
| `stripe_routes.py` | Billing endpoints |
| `paper_trading.py` | Paper trading |
| `performance.py` | Analytics |
| `sentiment.py` | Sentiment heatmap |
| `correlations.py` | Correlation matrix |
| `congress_tracker.py` | Congressional trading |
| `sports_tracker.py` | Sports betting intel |
| `enterprise.py` | Enterprise features |
| `export.py` | Data export |
| `news_feed.py` | News feed |
| `websocket.py` | WebSocket real-time stream |
| ... | 20+ more route files |

---

## Templates (39+)

| Template | Purpose |
|----------|---------|
| `base.html` | Base layout (Tailwind + Chart.js + HTMX) |
| `dashboard.html` | Main dashboard |
| `signal_detail.html` | Signal detail view |
| `pricing.html` | Pricing page |
| `backtest.html` | Backtest config form + saved runs |
| `backtest_result.html` | Backtest results with KPI cards, equity curve, trade log |
| `backtest_compare.html` | Strategy comparison page |
| `backtest_monte_carlo_partial.html` | HTMX partial: Monte Carlo results |
| `backtest_optimize_partial.html` | HTMX partial: optimizer results |
| `backtest_walk_forward_partial.html` | HTMX partial: walk-forward results |
| ... | 35+ more templates |

---

## Authentication & Authorization

**Module:** `src/rot/web/auth.py`

### Authentication Methods (priority order)

| Priority | Method | Mechanism | Use Case |
|----------|--------|-----------|----------|
| 1 | JWT Bearer Token | `Authorization: Bearer <token>` header | API clients |
| 2 | API Key | `X-API-Key: rot_<token>` header | Programmatic access |
| 3 | Session Cookie | `rot_session` cookie containing JWT | Web dashboard |
| 4 | Anonymous | No auth | Free tier access with gating |

### Password Security

- bcrypt hashing via `hash_password()` / `verify_password()`
- JWT signed with `ROT_AUTH_JWT_SECRET` (falls back to `ROT_WEB_SECRET_KEY`)
- JWT claims: `sub` (user_id), `email`, `tier`, `exp` (24h default)

### Key Functions

| Function | Purpose |
|----------|---------|
| `get_current_user_optional(request)` | Returns user dict or None (for optional auth routes) |
| `require_user(request)` | FastAPI dependency, raises 401 if unauthenticated |
| `require_tier(*tiers)` | Factory for tier-checking dependency, raises 403 if wrong tier |

### Auth Config

| Variable | Default | Description |
|----------|---------|-------------|
| `ROT_AUTH_JWT_SECRET` | `""` | JWT signing secret (falls back to `ROT_WEB_SECRET_KEY`) |
| `ROT_AUTH_JWT_ALGORITHM` | `"HS256"` | JWT algorithm |
| `ROT_AUTH_JWT_EXPIRE_MINUTES` | `1440` | Token expiry (24h) |

---

## Subscription Tiers & Feature Gating

**Module:** `src/rot/web/tier_gate.py`

### Tier Hierarchy

```
Free --> Pro --> Premium --> Ultra --> Enterprise
```

### Tier Capabilities

| Feature | Free | Pro | Premium | Ultra | Enterprise |
|---------|------|-----|---------|-------|-----------|
| Signal delay | 15 min | Real-time | Real-time | Real-time | Real-time |
| Signals per page | 10 | Full | Full | Full | Full |
| API access | No | 1000/day | 5000/day | 25000/day | 100000/day |
| Trade legs/reasoning | Redacted | Full | Full | Full | Full |
| Charts/filters | Basic | Basic | Advanced | Full | Full |
| Performance dashboard | No | Basic | Full | Full | Full |
| Backtest | No | Basic (30d, 200 signals) | +MC, walk-forward, risk (90d, 1000) | +optimizer, comparison, export (365d, 5000) | Full |
| Exports | No | No | No | Yes | Bulk + scheduled |
| Sponsored signals | No | No | No | No | Yes |
| Custom webhooks | No | No | No | No | Yes |
| Data licensing | No | No | No | No | Yes |

### Gate Functions (30+)

Each gate function returns a dict of boolean/numeric flags (not exceptions). This allows templates to show/hide features granularly.

| Gate Function | Controls |
|--------------|----------|
| `gate_signal()` / `gate_signal_list()` | Signal content gating (delay, redaction) |
| `gate_chart_access()` | Chart features (quadrant, overlay, etc.) |
| `gate_filter_access()` | Filter capabilities (ticker, strategy, date range) |
| `gate_performance_access()` | Analytics depth |
| `gate_email_access()` | Alert types (digest, real-time) |
| `gate_heatmap_access()` | Sentiment heatmap features |
| `gate_leaderboard_access()` | Leaderboard features |
| `gate_market_context()` | Market data depth |
| `gate_correlation_access()` | Correlation features |
| `gate_sentiment_access()` | Sentiment analysis depth |
| `gate_ticker_dive_access()` | Ticker deep dive |
| `gate_weekly_wrap_access()` | Weekly summaries |
| `gate_replay_access()` | Signal replay |
| `gate_data_licensing()` | Enterprise data export |
| `gate_sponsored_access()` | Enterprise sponsored signals |
| `gate_sector_rotation_access()` | Sector analysis |
| `gate_unusual_activity()` | Unusual options activity |
| `gate_news_feed_access()` | News feed depth |
| `gate_congress_tracker_access()` | Congressional trading |
| `gate_paper_leaderboard_access()` | Paper trading leaderboard |
| `gate_sports_betting_access()` | Sports betting intel |
| `gate_signal_quality_access()` | Signal quality analytics dashboard |
| `gate_backtest_access()` | Backtest engine features (tiered) |

### Usage Pattern

```python
access = gate_chart_access(user_tier)
if access["has_quadrant"]:
    render_quadrant_chart()
```

### Rate Limiting

**Module:** `src/rot/web/rate_limit.py`

Per-tier API rate limits enforced via `api_usage` table:

| Tier | Daily API Calls |
|------|----------------|
| Free | 0 (blocked) |
| Pro | 1,000 |
| Premium | 5,000 |
| Ultra | 25,000 |
| Enterprise | 100,000 |

---

## Query Cache

**Module:** `src/rot/web/query_cache.py`

Async in-memory TTL cache to reduce DB load from dashboard page views.

### Cached Queries

| Query | TTL | Invalidated on New Signal? |
|-------|-----|---------------------------|
| Trending tickers | 30s | Yes (prefix invalidation) |
| Leaderboard | 30s | Yes (prefix invalidation) |
| Chart data | 60s | No (TTL expiry) |
| Time series | 60s | No (TTL expiry) |
| Performance summary | 120s | No (TTL expiry) |
| Strategy breakdown | 120s | No (TTL expiry) |
| Accuracy stats | 120s | No (TTL expiry) |
| Heatmaps | 120s | No (TTL expiry) |
| Correlations | 120s | No (TTL expiry) |
| Landing page stats | 300s | No (TTL expiry) |

**NOT cached:** user-filtered signals, per-user signal count badge.

### Cache Features

| Feature | Detail |
|---------|--------|
| Thundering herd prevention | Per-key `asyncio.Lock` -- only one coroutine fetches stale data |
| Bounded size | Max 100 entries, evicts expired + oldest on overflow |
| Lock cleanup | Every 5 minutes, removes stale locks |
| Prefix invalidation | `invalidate_prefix("trending")` clears all matching keys |

---

## Stripe Integration

### Billing Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/billing/checkout` | Creates Stripe checkout session for tier upgrade |
| `POST /api/v1/billing/webhook` | Handles Stripe webhook events (subscription lifecycle) |
| `GET /api/v1/billing/portal` | Redirects to Stripe customer portal |
| `GET /api/v1/billing/status` | Returns current subscription status |

### Config

| Variable | Description |
|----------|-------------|
| `ROT_STRIPE_SECRET_KEY` | Stripe secret key |
| `ROT_STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `ROT_STRIPE_PRO_PRICE_ID` | Stripe price ID for Pro tier |
| `ROT_STRIPE_PREMIUM_PRICE_ID` | Stripe price ID for Premium tier |
| `ROT_STRIPE_ULTRA_PRICE_ID` | Stripe price ID for Ultra tier |
| `ROT_STRIPE_ENTERPRISE_PRICE_ID` | Stripe price ID for Enterprise tier |
