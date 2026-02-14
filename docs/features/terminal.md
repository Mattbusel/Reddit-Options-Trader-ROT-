<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Bloomberg-lite Terminal

- **Files**: `src/rot/web/routes/terminal.py`, `src/rot/web/templates/terminal.html`
- **DB**: None (reads existing `signals`, `signal_performance`, `unusual_events`)
- **Routes**: `GET /terminal`, HTMX partials: `/api/v1/terminal/{ticker-bar,quick-stats,watchlist}`
- **Tier**: Premium+ via `gate_terminal_access()`

## 7-Panel Grid Layout
```
+------------------------------------------------------------------+
|                        TICKER BAR (30s)                           |
+------------------+---------------------+-------------------------+
| SIGNAL FEED      | MARKET HEATMAP      | WATCHLIST               |
| (WebSocket)      | (HTMX 60s)         | (HTMX 30s)             |
+------------------+---------------------+-------------------------+
| NEWS WIRE        | OPTIONS FLOW        | QUICK STATS             |
| (HTMX 60s)      | (HTMX 60s)         | (HTMX 120s)            |
+------------------+---------------------+-------------------------+
```

### Panels
1. **Ticker Bar**: Scrolling prices from recent signals' market_data, green/red coded
2. **Signal Feed**: WebSocket via `/api/v1/signals/live`, compact one-line cards
3. **Market Heatmap**: Treemap by sector signal volume, stance-colored, from `SectorAnalyzer`
4. **Watchlist**: User's `settings["watchlist"]`, last signal + unusual flags
5. **News Wire**: RSS-sourced signals (flair=="rss"), chronological with lag timer
6. **Options Flow**: Recent `unusual_events` sorted by composite score
7. **Quick Stats**: 24h signal count, win rate, avg confidence, active positions, top ticker

## Data Sources
All from existing tables -- no new DB tables or migrations needed.

## Tier Gating
| Tier | Access |
|------|--------|
| Free/Pro | No access |
| Premium | Full access, 60s refresh, 25 signals |
| Ultra+ | Full access, 30s refresh, 50 signals, options flow, watchlist alerts |

## Design
Extends `base.html` with minimal header. Tailwind CSS Grid. Dark theme default. Chart.js for heatmap. `htmx-ws` for signal feed WebSocket.
