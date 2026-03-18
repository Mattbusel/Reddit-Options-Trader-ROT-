# API Reference — ROT

All API endpoints require authentication via one of:
- **Bearer token** (JWT): `Authorization: Bearer <token>`
- **API key**: `X-API-Key: <key>` or `?api_key=<key>`

All endpoints return JSON. Errors follow `{"error": "<message>"}` format.

Interactive documentation available at `/docs` (Swagger UI) and `/redoc`.

---

## Tier Access

| Tier | Daily Limit | Notes |
|------|-------------|-------|
| Free | 0 (blocked) | Dashboard only |
| Pro | 1,000 | Most endpoints |
| Premium | 5,000 | Extended history, date filtering |
| Ultra | 25,000 | Strategy P&L, webhooks |
| Enterprise | 100,000 | Full access, export schedules |
| Admin | Unlimited | All endpoints, no rate limit |

---

## Signals

### `GET /api/v1/signals`
List trading signals with filtering, sorting, and field selection.

**Min tier:** Pro

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 50 | Max results (1–200) |
| `offset` | int | 0 | Pagination offset |
| `ticker` | str | — | Filter by ticker symbol (e.g. `AAPL`) |
| `stance` | str | — | `bullish`, `bearish`, `mixed`, `unknown` |
| `min_confidence` | float | — | Minimum confidence threshold (0–1) |
| `event_type` | str | — | `earnings`, `fda`, `merger`, `squeeze_chatter`, `macro`, etc. |
| `date_from` | float | — | Unix timestamp — Premium+ only |
| `date_to` | float | — | Unix timestamp — Premium+ only |
| `source` | str | — | Filter by subreddit or RSS feed source |
| `fields` | str | all | Comma-separated field list to reduce bandwidth |
| `sort` | str | `created_at` | `created_at`, `confidence`, `trend_score` |
| `order` | str | `desc` | `asc` or `desc` |

**Example:**
```
GET /api/v1/signals?ticker=AAPL&stance=bullish&min_confidence=0.7&fields=ticker,stance,confidence,created_at&limit=10
```

**Response fields:** `id`, `created_at`, `ticker`, `event_type`, `stance`, `time_horizon`, `confidence`, `trend_score`, `quality_score`, `strategy`, `subreddit`, `post_title`, `post_url`, `market_data`, `reasoning`, `trade_idea`, `event_data`, `sector`, `ai_summary`

---

### `GET /api/v1/signals/{signal_id}`
Get a single signal by ID.

**Min tier:** Pro

**Query parameters:** `fields` (comma-separated)

---

## Tickers

### `GET /api/v1/tickers/trending`
Trending tickers by signal volume.

**Min tier:** Pro

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `hours` | int | 24 | Lookback window (1–168) |
| `limit` | int | 20 | Max tickers (1–100) |

---

## Performance

### `GET /api/v1/performance/summary`
Aggregate performance summary (win rate, avg P&L).

**Min tier:** Pro

| Parameter | Type | Default |
|-----------|------|---------|
| `days` | int | 30 (1–365) |

---

### `GET /api/v1/performance/accuracy`
Signal accuracy stats by ticker and event type.

**Min tier:** Pro

| Parameter | Type | Description |
|-----------|------|-------------|
| `days` | int | Lookback (capped by tier) |
| `ticker` | str | Optional ticker filter |

---

### `GET /api/v1/performance/history`
Per-signal performance history.

**Min tier:** Pro

| Parameter | Type | Default |
|-----------|------|---------|
| `days` | int | 30 |
| `ticker` | str | — |
| `limit` | int | 50 |

---

### `GET /api/v1/performance/accuracy-chart`
Time-series accuracy data for charting.

**Min tier:** Premium

| Parameter | Type | Default |
|-----------|------|---------|
| `days` | int | 30 (1–365) |

---

### `GET /api/v1/performance/strategy-pnl`
Strategy-level P&L breakdown.

**Min tier:** Ultra

| Parameter | Type | Default |
|-----------|------|---------|
| `days` | int | 30 (1–365) |

---

## Leaderboard

### `GET /api/v1/leaderboard`
Ticker leaderboard by signal volume and performance.

**Min tier:** Pro

| Parameter | Type | Default |
|-----------|------|---------|
| `hours` | int | 24 (1–2160) |
| `limit` | int | 20 (1–100) |
| `sort_by` | str | `signal_count` |

---

## Correlations

### `GET /api/v1/correlations`
Co-occurring ticker pairs within a time window.

**Min tier:** Pro

| Parameter | Type | Default |
|-----------|------|---------|
| `hours` | int | 24 (1–168) |

---

### `GET /api/v1/correlations/matrix`
Top correlated ticker pairs globally.

**Min tier:** Pro

| Parameter | Type | Default |
|-----------|------|---------|
| `days` | int | 30 (capped by tier) |
| `limit` | int | 20 (1–50) |

---

### `GET /api/v1/correlations/{ticker}`
Tickers that co-fire with a specific ticker.

**Min tier:** Pro

| Parameter | Type | Default |
|-----------|------|---------|
| `days` | int | 30 (capped by tier) |
| `window_hours` | int | 4 (1–24) |

---

## News

### `GET /api/v1/news`
Real-time news feed from 15+ financial sources.

**Min tier:** Pro

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | str | `all` | `all`, `marketwatch`, `cnbc`, `reuters`, `sec_8k`, etc. |
| `hours` | int | 4 | Lookback (capped by tier) |
| `limit` | int | 50 | Max items (capped by tier) |

---

## Unusual Activity

### `GET /api/v1/unusual-activity`
Signals with unusual options activity flags (high IV rank, volume surge, dark pool).

**Min tier:** Pro

| Parameter | Type | Default |
|-----------|------|---------|
| `hours` | int | 24 (1–720, capped by tier) |
| `limit` | int | 50 (1–200) |

---

## Congress Trades

### `GET /api/v1/congress-trades`
Congressional stock trading tracker (STOCK Act disclosures).

**Min tier:** Pro

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 30 | Lookback (capped by tier) |
| `limit` | int | 20 (max 100) | |
| `ticker` | str | — | Filter by ticker — Premium+ only |

---

## Paper Trading

### `GET /api/v1/paper-leaderboard`
Paper trading leaderboard rankings.

**Min tier:** Pro

| Parameter | Type | Default |
|-----------|------|---------|
| `limit` | int | 20 (capped by tier) |

---

## TradingView

### `GET /api/v1/tradingview/signals`
Signals formatted for TradingView Pine Script integration.

**Min tier:** Ultra

---

## Health

### `GET /health`
Health check. Unauthenticated returns `{"status": "ok"}`. Admin tier returns full diagnostic (DB status, memory, uptime, backup status).

---

## Status & Self-Documentation

### `GET /api/v1/status`
Your current API usage, quota remaining, and tier limits.

**Min tier:** Pro (any authenticated user)

### `GET /api/v1/docs`
Machine-readable endpoint catalog with parameters and examples.

**Min tier:** Pro

---

## Authentication Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/register` | POST | Create account |
| `/api/auth/login` | POST | Get JWT token |
| `/api/auth/me` | GET | Current user info |
| `/api/auth/api-key` | POST | Generate API key |
| `/api/auth/api-key` | DELETE | Revoke API key |

---

## Rate Limit Headers

All API responses include rate limit headers:

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Daily request limit for your tier |
| `X-RateLimit-Remaining` | Requests remaining today |
| `X-RateLimit-Reset` | Unix timestamp when limit resets |

---

## Error Codes

| HTTP Status | Meaning |
|-------------|---------|
| 400 | Bad request / invalid parameters |
| 401 | Missing or invalid authentication |
| 403 | Tier insufficient for this endpoint |
| 404 | Resource not found |
| 429 | Rate limit exceeded |
| 500 | Internal server error |

---

*For the live interactive reference, visit `/docs` on the running server.*
