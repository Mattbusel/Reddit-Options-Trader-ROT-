# Unusual Activity Detection — ROT Feature Reference
> Part of the ROT documentation suite. See [CLAUDE.md](../../CLAUDE.md) for the full index.

## Quick Start for Agents
- Key files: `src/rot/unusual/` (4 modules: `types.py`, `detector.py`, `history.py`, `__init__.py`)
- DB tables: `unusual_events`
- Routes: `GET /unusual-activity`, `GET /api/v1/unusual-activity`, `GET /api/v1/unusual-activity/summary`, `GET /api/v1/unusual-activity/timeline/{ticker}`
- Config: `ROT_UNUSUAL_SCAN_INTERVAL_S`, `ROT_UNUSUAL_IV_RANK_THRESHOLD`, `ROT_UNUSUAL_VOLUME_SURGE_MULTIPLIER`, `ROT_UNUSUAL_OI_SURGE_PCT`, `ROT_UNUSUAL_SKEW_STD_THRESHOLD`, `ROT_UNUSUAL_COMPOSITE_MIN_SCORE`, `ROT_UNUSUAL_HISTORY_WINDOW_DAYS`, `ROT_UNUSUAL_PURGE_KEEP_DAYS`

---

## Module Layout

| File | Purpose |
|------|---------|
| `__init__.py` | Exports UnusualEvent, UnusualDetector, UnusualScore |
| `types.py` | Frozen dataclasses: UnusualEvent, UnusualScore, UnusualSummary |
| `detector.py` | Core detection engine with 5 event types, composite scoring (0-100) |
| `history.py` | Rolling per-ticker baselines for anomaly detection |

## Event Types

The detector identifies 5 types of unusual options activity:

| Type | Detection Method | Default Threshold |
|------|-----------------|-------------------|
| `iv_spike` | IV percentile rank against rolling history | IV rank > 80th percentile |
| `volume_surge` | Z-score against 20-day average volume | Volume > 2x 20-day average |
| `oi_surge` | Percentage change in open interest | OI increase > 20% |
| `skew_shift` | Put/call ratio deviation from rolling mean | P/C ratio > 2 std devs from mean |
| `sweep` | Approximation of sweep order detection | Heuristic-based |

## Composite Scoring

Each detected event receives a composite score from 0 to 100. The score combines individual signal strengths (IV rank magnitude, volume z-score, OI change percentage, skew deviation) into a single actionability metric. Events below the minimum composite score (default 40.0) are discarded and not stored.

## Rolling Baselines (`history.py`)

`UnusualHistory` maintains per-ticker rolling statistics:
- IV rank history for percentile computation
- Volume z-score against 20-day moving average
- OI change percentage tracking
- Skew (put/call ratio) mean and standard deviation

Baselines are kept in-memory with LRU eviction at 500 tickers max to bound memory usage. Periodic DB flush persists state.

## Background Scan Loop

The unusual activity scanner runs as a background `asyncio` task in `server.py`:
- **Interval**: every 5 minutes (configurable via `ROT_UNUSUAL_SCAN_INTERVAL_S`)
- **Process**: fetches recent signals from DB, runs `UnusualDetector.scan_batch()`, saves detected events to the `unusual_events` table
- **Purging**: old events are purged after 90 days (configurable via `ROT_UNUSUAL_PURGE_KEEP_DAYS`)
- **Pattern**: initial delay, `while not stop_event.is_set()`, try/except with logging, `asyncio.sleep()`

## DB Schema: `unusual_events`

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| ticker | TEXT | Ticker symbol |
| event_type | TEXT | One of: iv_spike, volume_surge, oi_surge, skew_shift, sweep |
| score | REAL | Composite score (0-100) |
| details_json | TEXT | Full detection details as JSON |
| signal_id | TEXT | Linked signal (if applicable) |
| detected_at | REAL | Unix timestamp of detection |

## Routes & API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/unusual-activity` | Dashboard page with events, timeline, filters |
| GET | `/api/v1/unusual-activity` | JSON API: list unusual events (filterable) |
| GET | `/api/v1/unusual-activity/summary` | Aggregate stats (event counts, top tickers) |
| GET | `/api/v1/unusual-activity/timeline/{ticker}` | Per-ticker event timeline |

## Tier Gating

Access is controlled by `gate_unusual_activity()` in `src/rot/web/tier_gate.py`. The dashboard and API endpoints are gated by subscription tier.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ROT_UNUSUAL_SCAN_INTERVAL_S` | `300` | Seconds between background scans |
| `ROT_UNUSUAL_IV_RANK_THRESHOLD` | `80.0` | Flag if IV rank > this percentile |
| `ROT_UNUSUAL_VOLUME_SURGE_MULTIPLIER` | `2.0` | Flag if volume > Nx 20-day average |
| `ROT_UNUSUAL_OI_SURGE_PCT` | `20.0` | Flag if OI increases > this % |
| `ROT_UNUSUAL_SKEW_STD_THRESHOLD` | `2.0` | Flag if P/C ratio > N std devs from mean |
| `ROT_UNUSUAL_COMPOSITE_MIN_SCORE` | `40.0` | Minimum composite score to store event |
| `ROT_UNUSUAL_HISTORY_WINDOW_DAYS` | `20` | Rolling window for baseline computation |
| `ROT_UNUSUAL_PURGE_KEEP_DAYS` | `90` | Days to keep unusual events before purging |

## Tests

4 test files covering the full feature:
- `test_unusual_types.py` -- UnusualEvent, UnusualScore, UnusualSummary dataclass tests
- `test_unusual_detector.py` -- IV rank, volume surge, OI surge, skew shift, sweep detection, composite scoring, batch scan
- `test_unusual_history.py` -- Rolling stats, percentile computation, cold start, baseline updates
- `test_unusual_db.py` -- save/query/purge unusual events, timeline queries, summary aggregation

## Design Notes

- Cold start: when no history exists for a ticker, the detector uses conservative defaults and accumulates baseline data over subsequent scans.
- The `scan_batch()` method processes multiple signals at once for efficiency.
- Memory is bounded by the 500-ticker LRU cap in UnusualHistory.
- The dashboard template includes filters by event type, ticker, and date range, plus a timeline visualization for per-ticker event history.
