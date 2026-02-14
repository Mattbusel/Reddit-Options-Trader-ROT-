# Bloomberg-lite Terminal — ROT Feature Reference
> Part of the ROT documentation suite. See [CLAUDE.md](../../CLAUDE.md) for the full index.

## Quick Start for Agents
- Key files: `src/rot/web/routes/terminal.py` (to be created), `src/rot/web/templates/terminal.html` (to be created)
- DB tables: None (reads from existing `signals`, `signal_performance`, `unusual_events`)
- Routes: `GET /terminal`
- Config: None new (uses existing `ROT_WEB_*`, leverages existing WebSocket at `/api/v1/signals/live`)
- Tier gate: `gate_terminal_access()` in `src/rot/web/tier_gate.py` -- Premium+ only

---

## Overview

The Terminal is a multi-panel, information-dense dashboard inspired by Bloomberg Terminal layouts. It presents real-time market intelligence in a single viewport, combining signal feeds, market data, watchlist monitoring, news wires, and options flow into a unified interface. No new database tables are required -- the terminal reads from existing data sources and presents them in a dense, professional layout.

## Panel Layout

The terminal uses a CSS Grid layout with 7 panels arranged for maximum information density:

### 1. Ticker Bar (Top Strip)
- Horizontal scrolling bar showing live ticker prices and daily changes
- Sources data from recent signals' market_data JSON
- HTMX auto-refresh every 30 seconds
- Color-coded: green for positive, red for negative changes

### 2. Signal Feed (Left Column, Top)
- Live stream of incoming signals with ticker, stance, confidence, event type
- WebSocket-powered via existing `/api/v1/signals/live` endpoint
- Compact card format: one line per signal with color-coded stance badges
- Click-to-expand for full signal details (HTMX partial load)

### 3. Market Heatmap (Center, Top)
- Treemap visualization of sectors by signal volume
- Color-coded by aggregate stance (green = net bullish, red = net bearish)
- Leverages existing sector rotation data from `SectorAnalyzer`
- HTMX auto-refresh every 60 seconds

### 4. Watchlist (Right Column, Top)
- User's personal watchlist with live price data and alert status
- Reads from user's `settings["watchlist"]` stored in the `users` table
- Shows last signal, confidence trend, and unusual activity flags
- HTMX auto-refresh every 30 seconds

### 5. News Wire (Left Column, Bottom)
- Chronological feed of RSS-sourced signals (flair == "rss")
- Shows source, headline, ticker mentions, and lag timer
- Compact list format with timestamp and source icon
- HTMX auto-refresh every 60 seconds

### 6. Options Flow (Center, Bottom)
- Recent unusual activity events from `unusual_events` table
- Shows event type icon, ticker, composite score, and detection time
- Sorted by composite score descending
- HTMX auto-refresh every 60 seconds

### 7. Quick Stats (Right Column, Bottom)
- Key performance indicators: 24h signal count, win rate, average confidence
- Active positions count (from paper trading)
- Top performing ticker (24h)
- Suppressed signal count (feedback engine)
- HTMX auto-refresh every 120 seconds

## Template Architecture

`terminal.html` extends `base.html` but uses a minimal header to maximize viewport space. The layout uses Tailwind CSS Grid:

```
+------------------------------------------------------------------+
|                        TICKER BAR                                 |
+------------------+---------------------+-------------------------+
|                  |                     |                         |
|   SIGNAL FEED    |   MARKET HEATMAP    |      WATCHLIST          |
|   (WebSocket)    |   (HTMX 60s)       |      (HTMX 30s)        |
|                  |                     |                         |
+------------------+---------------------+-------------------------+
|                  |                     |                         |
|   NEWS WIRE      |   OPTIONS FLOW      |      QUICK STATS        |
|   (HTMX 60s)     |   (HTMX 60s)       |      (HTMX 120s)       |
|                  |                     |                         |
+------------------+---------------------+-------------------------+
```

## HTMX Auto-Refresh

Each panel (except the WebSocket-powered signal feed) uses HTMX `hx-trigger="every Ns"` for periodic refresh. Each panel has a dedicated HTMX partial endpoint:

| Panel | Endpoint | Refresh |
|-------|----------|---------|
| Ticker Bar | `GET /terminal/partial/ticker-bar` | 30s |
| Market Heatmap | `GET /terminal/partial/heatmap` | 60s |
| Watchlist | `GET /terminal/partial/watchlist` | 30s |
| News Wire | `GET /terminal/partial/news` | 60s |
| Options Flow | `GET /terminal/partial/options-flow` | 60s |
| Quick Stats | `GET /terminal/partial/stats` | 120s |

## WebSocket Integration

The signal feed panel connects to the existing WebSocket endpoint at `/api/v1/signals/live`. New signals appear immediately in the feed without polling. The WebSocket connection is managed by the existing `htmx-ws` library already bundled in the static assets.

## Tier Gating

The terminal is a Premium+ feature. `gate_terminal_access()` returns:

| Tier | Access |
|------|--------|
| Free | No access |
| Pro | No access |
| Premium | Full terminal access |
| Ultra | Full terminal access |
| Enterprise | Full terminal access |

## Data Sources (No New Tables)

All terminal panels read from existing data:
- **Signal feed**: `signals` table via WebSocket
- **Ticker bar**: `market_data` JSON from recent signals
- **Heatmap**: `SectorAnalyzer` on-demand computation (cached 120s)
- **Watchlist**: `users.settings["watchlist"]` + recent signals for those tickers
- **News wire**: `signals` table filtered by `subreddit` containing RSS source identifiers
- **Options flow**: `unusual_events` table
- **Quick stats**: `signals` table aggregations + `paper_portfolios`

## Implementation Notes

- The terminal route should be a single `GET /terminal` that renders the full grid layout with initial data.
- Each partial endpoint returns a small HTML fragment for its respective panel.
- No new database migrations are needed.
- The `gate_terminal_access()` function should be added to `tier_gate.py`.
- The route file (`terminal.py`) should be registered in `server.py` alongside other route modules.
- Chart.js is used for the heatmap treemap visualization (already available in static assets).
- Dark theme is default for the terminal layout (professional trading aesthetic).
