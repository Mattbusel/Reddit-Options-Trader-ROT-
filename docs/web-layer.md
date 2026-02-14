<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Web Layer — ROT Reference

> See [CLAUDE.md](../CLAUDE.md) for full index.

**Key files:** `src/rot/web/routes/` (35+ files), `auth.py`, `tier_gate.py`, `query_cache.py`, `rate_limit.py`
**Stack:** FastAPI + Jinja2 + Tailwind CSS + Chart.js + HTMX (all self-hosted in `/static/js/`) + GZipMiddleware(min=500)
**Factory:** `src/rot/web/server.py` creates app, mounts routes, starts background pipeline

---

## Routes (50+ endpoints)

### Core
- `GET /` — Landing (redirects to dashboard if logged in)
- `GET /dashboard` — Main signal dashboard
- `GET /dashboard/signal/{signal_id}` — Signal detail
- `GET /pricing` — Tier comparison
- `GET /account` — Account settings

### Auth (`/auth/`)
- `POST register|login|logout` — Registration, JWT login, logout
- `GET /auth/me` — Current user
- `POST /auth/api-key` — Generate API key
- `PUT /auth/llm-settings` — User LLM settings
- `POST/DELETE/GET /auth/watchlist` — Watchlist CRUD
- `POST/DELETE/GET /auth/filter-presets` — Filter presets CRUD
- `GET/PUT /auth/email-alerts` — Email alert prefs

### Signals
- `GET /signals` — List (JSON, filterable, paginated)
- `GET /signals/new-count` — Count since timestamp
- `GET /signals/{signal_id}` — Detail
- `GET /signals/export` — CSV/JSON export
- `GET /tickers/trending` — Trending tickers
- `POST /signals/{signal_id}/reason` — Add note

### Performance & Analytics
- `GET /performance` — Dashboard page
- `GET /performance/summary|accuracy|history|strategy-pnl|export` — JSON endpoints
- `GET /accuracy-breakdown` — Detailed accuracy page
- `GET /confidence-calibration` — Calibration chart
- `GET /weekly-wrap` — Weekly wrap

### Visualization
- `GET /sentiment` — Sentiment heatmap
- `GET /correlations` — Correlations page (pairs, clusters, lead-lag, network)
- `GET /api/v1/correlations/matrix|{ticker}|clusters|lead-lag` — Correlation JSON APIs
- `GET /sector-rotation` — Sector rotation dashboard
- `GET /sector-rotation/drill-down/{sector}` — HTMX ticker breakdown
- `GET /api/v1/sectors/rankings` — Rankings JSON
- `GET /unusual-activity` — Unusual activity dashboard
- `GET /api/v1/unusual-activity` — Events JSON
- `GET /api/v1/unusual-activity/summary` — Stats JSON
- `GET /api/v1/unusual-activity/timeline/{ticker}` — Timeline JSON
- `GET /signal-quality` — Quality dashboard (Pro+)
- `GET /ticker/{symbol}` — Ticker deep dive
- `GET /news` — News feed

### Trading
- `GET /paper-trading` — Paper trading page
- `POST /api/v1/paper-trading/trade` — Execute trade
- `POST /api/v1/paper-trading/close/{trade_id}` — Close trade
- `GET /leaderboard` — Paper trading leaderboard
- `GET /backtest` — Backtest dashboard (Pro+)
- `POST /backtest/run` — Run simulation (HTMX)
- `GET /backtest/result/{run_id}` — View result
- `POST /backtest/monte-carlo/{run_id}` — Monte Carlo (HTMX)
- `POST /backtest/optimize` — Parameter optimization (HTMX)
- `POST /backtest/walk-forward/{run_id}` — Walk-forward (HTMX)
- `GET /backtest/compare` — Strategy comparison
- `POST /backtest/strategies/save` — Save strategy
- `DELETE /backtest/strategies/{id}` — Delete strategy
- `GET /api/v1/backtest/export/{run_id}` — Export (JSON/CSV)
- `GET /replay|brokers|tradingview` — Replay, brokers, TradingView pages

### Data & Trackers
- `GET /congress-tracker|sports-tracker|ceo-rap-sheet|hall-of-legends|wall-of-shame`

### Billing (`/api/v1/billing/`)
- `POST /checkout` — Stripe checkout session
- `POST /webhook` — Stripe webhook handler
- `GET /portal` — Customer portal
- `GET /status` — Subscription status

### Enterprise
- `GET /enterprise` — Dashboard (analytics, exports, lineage)
- `POST /api/v1/enterprise/data-export` — Export (CSV/JSON + lineage)
- `POST /api/v1/enterprise/sponsored/submit` — Submit sponsored signal
- `GET /api/v1/enterprise/sponsored/status|usage` — Status, usage
- `GET /api/v1/enterprise/analytics/overview` — 7d analytics
- `GET /api/v1/enterprise/lineage/{signal_id}` — Provenance chain

### Misc
- `GET /health|/api/v1/status|/api/v1/docs` — Health, status, docs
- `GET /faq|glossary|badges|widgets|affiliates` — Content pages
- `GET /robots.txt|sitemap.xml|llms.txt` — SEO + LLM docs
- `WS /api/v1/signals/live` — WebSocket signal stream

---

## Route Files

`dashboard.py` (main+auth+landing), `signals.py`, `auth_routes.py`, `stripe_routes.py`, `paper_trading.py`, `performance.py`, `sentiment.py`, `correlations.py`, `congress_tracker.py`, `sports_tracker.py`, `enterprise.py`, `export.py`, `news_feed.py`, `websocket.py`, `macro.py`, `flow.py`, `social.py`, `strategy.py`, + 20 more

## Templates (39+)

`base.html` (Tailwind+Chart.js+HTMX layout), `dashboard.html`, `signal_detail.html`, `pricing.html`, `backtest.html` + `backtest_result.html` + `backtest_compare.html`, `backtest_monte_carlo_partial.html` + `backtest_optimize_partial.html` + `backtest_walk_forward_partial.html` (HTMX partials), + 35 more

---

## Authentication

**Module:** `src/rot/web/auth.py`

**Methods (priority order):**
1. JWT Bearer — `Authorization: Bearer <token>` (API clients)
2. API Key — `X-API-Key: rot_<token>` (programmatic, SHA-256 stored)
3. Session Cookie — `rot_session` with JWT (web dashboard)
4. Anonymous — free tier with gating

**Password:** bcrypt hash. JWT signed with `ROT_AUTH_JWT_SECRET` (fallback: `ROT_WEB_SECRET_KEY`). Claims: `sub`, `email`, `tier`, `exp` (24h).

**Key functions:**
- `get_current_user_optional(request)` — user dict or None
- `require_user(request)` — 401 if unauthed
- `require_tier(*tiers)` — 403 if wrong tier

**Config:** `ROT_AUTH_JWT_SECRET` (default `""`), `ROT_AUTH_JWT_ALGORITHM` (`"HS256"`), `ROT_AUTH_JWT_EXPIRE_MINUTES` (`1440`)

---

## Tier Gating

**Module:** `src/rot/web/tier_gate.py` — `Free > Pro > Premium > Ultra > Enterprise` (+ hidden `admin` bypasses all)

**Capabilities:**

| Feature | Free | Pro | Premium | Ultra | Enterprise |
|---------|------|-----|---------|-------|-----------|
| Signal delay | 15min | Real-time | RT | RT | RT |
| Page limit | 10 | Full | Full | Full | Full |
| API/day | 0 | 1K | 5K | 25K | 100K |
| Trade legs | Redacted | Full | Full | Full | Full |
| Charts | Basic | Basic | Advanced | Full | Full |
| Perf dashboard | No | Basic | Full | Full | Full |
| Backtest | No | Basic 30d/200 | +MC,WF,risk 90d/1K | +opt,compare 365d/5K | Full |
| Exports | No | No | No | Yes | Bulk+scheduled |
| Sponsored/webhooks | No | No | No | No | Yes |

**30+ gate functions** return dicts of bool/numeric flags (not exceptions). See `tier_gate.py` for full list: `gate_signal()`, `gate_chart_access()`, `gate_filter_access()`, `gate_performance_access()`, `gate_backtest_access()`, `gate_macro_access()`, `gate_terminal_access()`, `gate_agent_access()`, `gate_flow_access()`, `gate_social_access()`, `gate_strategy_access()`, etc.

```python
access = gate_chart_access(user_tier)
if access["has_quadrant"]:
    render_quadrant_chart()
```

**Rate limiting** (`rate_limit.py`): enforced via `api_usage` table, per-tier daily caps (Free=0, Pro=1K, Premium=5K, Ultra=25K, Enterprise=100K, Admin=999999).

---

## Query Cache

**Module:** `src/rot/web/query_cache.py` — async in-memory TTL cache for dashboard queries.

**Cached (10):** trending (30s), leaderboard (30s), charts (60s), time series (60s), perf summary (120s), strategy breakdown (120s), accuracy (120s), heatmaps (120s), correlations (120s), landing stats (300s)
**Not cached:** user-filtered signals, per-user badge count

**On new signal:** trending + leaderboard invalidated via prefix. Others expire naturally.

**Features:** per-key `asyncio.Lock` (thundering herd), max 100 entries (evicts expired+oldest), lock cleanup every 5min, `invalidate_prefix()` for bulk clear.

---

## Stripe Config

`ROT_STRIPE_SECRET_KEY`, `ROT_STRIPE_WEBHOOK_SECRET`, `ROT_STRIPE_{PRO|PREMIUM|ULTRA|ENTERPRISE}_PRICE_ID`
