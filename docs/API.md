# ROT API Reference

Live interactive docs: Swagger UI at `GET /docs`, ReDoc at `GET /redoc`.
All responses include `X-Request-ID` header and `request_id` field for distributed tracing.

---

## Authentication

Three methods, evaluated in priority order:

**1. JWT Bearer Token** - Header: `Authorization: Bearer <jwt_token>`
Obtained via POST /auth/login. Expires 24 hours (ROT_AUTH_JWT_EXPIRE_MINUTES). Signed HS256 using ROT_AUTH_JWT_SECRET. Claims: sub, email, tier, exp.

**2. API Key Header** - Header: `X-API-Key: rot_<token>`
Generated via POST /auth/api-key. Requires Pro tier or above. Stored as SHA-256 hash; plaintext shown once at creation. Revoke by generating a new key.

**3. Session Cookie** - Cookie name `rot_session` (contains JWT). Set automatically after browser POST /auth/login.

**4. Anonymous (Free Tier)** - Signals delayed 15 min, 10/page limit, trade legs redacted. /api/v1/ endpoints require authentication.

---

## Rate Limiting

Per-user via `api_usage` database table (multi-instance safe). Limits reset at UTC midnight.

| Tier | Daily API Limit |
|------|----------------|
| Free | 0 (blocked entirely) |
| Pro | 1,000 |
| Premium | 5,000 |
| Ultra | 25,000 |
| Enterprise | 100,000 |
| Admin | Unlimited |

HTTP 429 response on limit exceeded: `error_code: RATE_LIMIT_EXCEEDED` with detail fields tier, daily_limit, daily_used, reset_in_hours.

---

## Response Envelope

Success: `{"success": true, "data": {...}, "error": null, "request_id": "req_abc123"}`
Error:   `{"success": false, "data": null, "error": "Message", "error_code": "CODE", "request_id": "req_abc123"}`

---

## Endpoint Reference

### Authentication

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | /auth/register | Create account | No |
| POST | /auth/login | Login; returns JWT + sets session cookie | No |
| POST | /auth/logout | Clear session cookie | No |
| GET | /auth/me | Current user info | Yes |
| POST | /auth/api-key | Generate API key (invalidates previous) | Yes (Pro+) |
| PUT | /auth/llm-settings | Update personal LLM provider settings | Yes |
| POST/DELETE/GET | /auth/watchlist | Watchlist CRUD | Yes |
| POST/DELETE/GET | /auth/filter-presets | Filter preset CRUD | Yes |
| GET/PUT | /auth/email-alerts | Email alert preferences | Yes |

### Signals

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | /signals | List signals (filterable, paginated) | Optional |
| GET | /signals/{signal_id} | Signal detail | Optional |
| GET | /signals/new-count | Count of signals since timestamp | Optional |
| GET | /signals/export | Export as CSV or JSON | Yes (Ultra+) |
| GET | /tickers/trending | Trending tickers with momentum scores | Optional |
| POST | /signals/{signal_id}/reason | Attach user note to signal | Yes |
| WS | /api/v1/signals/live | Real-time signal stream (WebSocket) | Optional |

Query params: `ticker`, `stance` (bullish/bearish/mixed/unknown), `event_type` (earnings_rumor/product_news/regulatory/squeeze_chatter/macro/other), `min_confidence` (0.0-1.0), `strategy`, `subreddit`, `page`, `page_size` (max 200).

### Performance and Analytics

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | /performance/summary | Win rate, PnL, signal count summary | Yes (Pro+) |
| GET | /performance/accuracy | Accuracy breakdown by event type | Yes (Pro+) |
| GET | /performance/history | Historical performance time series | Yes (Pro+) |
| GET | /performance/strategy-pnl | PnL breakdown by options strategy | Yes (Pro+) |
| GET | /performance/export | Export performance data as CSV | Yes (Ultra+) |
| GET | /confidence-calibration | Confidence score calibration data | Yes (Premium+) |
| GET | /api/v1/correlations/matrix | Ticker correlation matrix | Yes (Premium+) |
| GET | /api/v1/correlations/{ticker} | Correlations for a specific ticker | Yes (Premium+) |
| GET | /api/v1/correlations/clusters | Ticker clustering groups | Yes (Premium+) |
| GET | /api/v1/correlations/lead-lag | Lead-lag relationships | Yes (Premium+) |
| GET | /api/v1/sectors/rankings | Sector momentum rankings | Yes (Premium+) |
| GET | /api/v1/unusual-activity | Unusual options activity events | Yes (Pro+) |
| GET | /api/v1/unusual-activity/summary | Unusual activity statistics | Yes (Pro+) |
| GET | /api/v1/unusual-activity/timeline/{ticker} | Activity timeline for ticker | Yes (Pro+) |

### Paper Trading

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | /paper-trading | Paper trading dashboard | Yes |
| POST | /api/v1/paper-trading/trade | Execute a paper trade | Yes |
| POST | /api/v1/paper-trading/close/{trade_id} | Close an open paper trade | Yes |
| GET | /leaderboard | Paper trading leaderboard | Optional |

### Backtesting

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | /backtest | Backtest dashboard | Yes (Pro+) |
| POST | /backtest/run | Run a backtest simulation | Yes (Pro+) |
| GET | /backtest/result/{run_id} | View backtest result | Yes (Pro+) |
| POST | /backtest/monte-carlo/{run_id} | Monte Carlo simulation on result | Yes (Premium+) |
| POST | /backtest/optimize | Parameter grid search optimization | Yes (Premium+) |
| POST | /backtest/walk-forward/{run_id} | Walk-forward validation | Yes (Premium+) |
| GET | /backtest/compare | Compare multiple strategies | Yes (Ultra+) |
| POST | /backtest/strategies/save | Save a named strategy | Yes (Pro+) |
| DELETE | /backtest/strategies/{id} | Delete a named strategy | Yes (Pro+) |
| GET | /api/v1/backtest/export/{run_id} | Export backtest result (JSON/CSV) | Yes (Pro+) |

### Billing

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | /api/v1/billing/checkout | Create Stripe checkout session | Yes |
| POST | /api/v1/billing/webhook | Stripe webhook (HMAC-signed by Stripe) | No |
| GET | /api/v1/billing/portal | Stripe customer portal redirect | Yes |
| GET | /api/v1/billing/status | Current subscription status | Yes |

### Enterprise

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | /enterprise | Enterprise dashboard | Yes (Enterprise) |
| POST | /api/v1/enterprise/data-export | Bulk data export with 9-step lineage | Yes (Enterprise) |
| POST | /api/v1/enterprise/sponsored/submit | Submit a sponsored signal analysis | Yes (Enterprise) |
| GET | /api/v1/enterprise/sponsored/status | Sponsored signal status | Yes (Enterprise) |
| GET | /api/v1/enterprise/sponsored/usage | Sponsored signal usage stats | Yes (Enterprise) |
| GET | /api/v1/enterprise/analytics/overview | 7-day analytics overview | Yes (Enterprise) |
| GET | /api/v1/enterprise/lineage/{signal_id} | 9-step signal provenance chain | Yes (Enterprise) |

### System

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | /health | Health check (public: minimal; admin: full diagnostics) | No |
| GET | /api/v1/status | API status and version | No |
| GET | /docs | Swagger UI interactive documentation | No |
| GET | /redoc | ReDoc API reference | No |

---

## curl Examples

### Login

    curl -X POST https://rot.up.railway.app/auth/login \
      -H "Content-Type: application/json" \
      -d "{\"email\": \"user@example.com\", \"password\": \"your-password\"}"

Response: `{"access_token": "eyJ...", "token_type": "bearer", "tier": "pro"}`

### Get Signals (Trade Ideas)

Using API key:

    curl -H "X-API-Key: rot_your_api_key_here" \
      "https://rot.up.railway.app/signals?min_confidence=0.7&stance=bullish&page_size=10"

Using JWT:

    curl -H "Authorization: Bearer eyJhbGc..." \
      "https://rot.up.railway.app/signals?min_confidence=0.7&stance=bullish"

Response data.items per signal: id, ticker, stance, confidence, event_type, strategy, quality_score, trade_idea (legs array with type/option_type/strike/expiry), post_title, subreddit, created_at.

### Submit Sponsored Analysis Prompt (Enterprise)

    curl -X POST \
      -H "Authorization: Bearer eyJhbGc..." \
      -H "Content-Type: application/json" \
      -d "{\"ticker\": \"AAPL\", \"context\": \"Strong iPhone demand signals\", \"stance_hint\": \"bullish\"}" \
      "https://rot.up.railway.app/api/v1/enterprise/sponsored/submit"

### Get Trending Tickers

    curl "https://rot.up.railway.app/tickers/trending"

Response data: array of {ticker, mention_count, bullish_pct, avg_confidence}.

### Health Check

    curl https://rot.up.railway.app/health
    # Public returns: {"status": "ok"}

    curl -H "Authorization: Bearer <admin-jwt>" https://rot.up.railway.app/health
    # Admin returns full diagnostics

Admin response fields: status, version, uptime_seconds; database (connected/signal_count/size_mb); system (memory_rss_mb/cpu_percent/num_threads/disk_usage_percent/disk_free_gb); backups (count/latest.filename/latest.age_hours/total_size_mb); environment (deployment/railway_env).

### WebSocket: Live Signal Stream

    const ws = new WebSocket("wss://rot.up.railway.app/api/v1/signals/live");
    ws.onmessage = (e) => console.log(JSON.parse(e.data));

---

## Error Codes

| HTTP | error_code | Meaning |
|------|------------|---------|
| 400 | BAD_REQUEST | Malformed request or invalid parameters |
| 401 | UNAUTHORIZED | Missing or invalid credentials |
| 403 | FORBIDDEN | Authenticated but insufficient tier |
| 404 | NOT_FOUND | Resource does not exist |
| 422 | VALIDATION_ERROR | Pydantic validation failure |
| 429 | RATE_LIMIT_EXCEEDED | Daily quota exhausted |
| 500 | INTERNAL_ERROR | Server error (logged server-side; not exposed to client) |

---

## Request Tracing Headers

Every response includes:

| Header | Description |
|--------|-------------|
| X-Request-ID | Unique UUID4 for this request |
| X-Correlation-ID | Echoed from request X-Correlation-ID header |
| X-Response-Time | Server processing time, e.g. 47ms |

Pass X-Request-ID and X-Correlation-ID from your client to correlate requests with server logs.
