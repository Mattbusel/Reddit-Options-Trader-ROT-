<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Options Flow Intelligence

**Module**: `src/rot/flow/` (7 files)
**Tier**: Pro+ (gated by `gate_flow_access()`)

## Modules

| File | Purpose |
|------|---------|
| `types.py` | FlowEvent, FlowScore, FlowPattern, FlowSignalConvergence, GreeksSnapshot, FlowSummary |
| `greeks.py` | Black-Scholes pricing, delta/gamma/theta/vega/rho, IV bisection, portfolio Greeks |
| `detector.py` | Block trade, sweep, dark pool, accumulation/distribution detection, composite scoring |
| `patterns.py` | Repeat buyer, accumulation sequence, hedging, rolling, cross-ticker recognition |
| `history.py` | Rolling per-ticker baselines, LRU eviction at 500 tickers |
| `convergence.py` | Cross-reference flow events with social signals for multi-source corroboration |

## Detection Types

- **block_trade** — Premium >= `ROT_FLOW_BLOCK_PREMIUM_THRESHOLD` ($100k default)
- **sweep** — Volume >= `ROT_FLOW_SWEEP_VOLUME_THRESHOLD` (1000 default)
- **dark_pool** — Premium >= `ROT_FLOW_DARK_POOL_THRESHOLD` ($50k default)
- **accumulation** — Repeated same-direction within `ACCUMULATION_WINDOW_S` (1h)
- **distribution** — Opposite of accumulation

## Pattern Types

repeat_buyer, accumulation_sequence, hedging, rolling, cross_ticker. Min events: `PATTERN_MIN_EVENTS` (3).

## Convergence

`ConvergenceDetector` matches flow events with social signals within `CONVERGENCE_WINDOW_S` (30min). High convergence amplifies signal confidence.

## DB Tables

- `flow_events` — id, ticker, flow_type, direction, premium, volume, oi_change, score, details_json, signal_id, detected_at. IDX: ticker, detected_at DESC, flow_type
- `flow_patterns` — id, pattern_type, tickers_json, confidence, timeframe, events_json, details_json, detected_at
- `flow_convergences` — id, signal_id, flow_event_ids_json, convergence_score, convergence_type, details_json, detected_at
- `flow_baselines` — ticker PK, net_premium, avg_premium, flow_count, last_direction, observations_json, last_updated

## Routes

- `GET /flow` — Dashboard (events, patterns, convergences, Greeks)
- `GET /api/v1/flow/events` — Flow events JSON
- `GET /api/v1/flow/summary` — Summary stats
- `GET /api/v1/flow/timeline/{ticker}` — Per-ticker timeline
- `GET /api/v1/flow/convergences` — Convergences JSON
- `GET /api/v1/flow/patterns` — Patterns JSON
- `GET /api/v1/flow/greeks/{ticker}` — Greeks snapshot

## Tier Gating

Pro: 24h history. Premium: 7d + patterns/convergences. Ultra: 30d + Greeks + export.

## Background Loop

`_flow_scan_loop()` every 5min in server.py. Fetches recent signals → `FlowDetector.scan_batch()` → saves events/patterns/convergences → purges old data (90 days).

## Config (`ROT_FLOW_*`)

SCAN_INTERVAL_S=300, BLOCK_PREMIUM_THRESHOLD=100000, SWEEP_VOLUME_THRESHOLD=1000, DARK_POOL_THRESHOLD=50000, ACCUMULATION_WINDOW_S=3600, PATTERN_MIN_EVENTS=3, CONVERGENCE_WINDOW_S=1800, PURGE_KEEP_DAYS=90
