<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Unusual Activity Detection

- **Files**: `src/rot/unusual/{types,detector,history,__init__}.py`
- **DB**: `unusual_events`
- **Routes**: `GET /unusual-activity`, `GET /api/v1/unusual-activity`, `GET /api/v1/unusual-activity/summary`, `GET /api/v1/unusual-activity/timeline/{ticker}`
- **Tier**: `gate_unusual_activity()`

## Config
| Variable | Default | Description |
|----------|---------|-------------|
| `ROT_UNUSUAL_SCAN_INTERVAL_S` | 300 | Background scan interval |
| `ROT_UNUSUAL_IV_RANK_THRESHOLD` | 80.0 | IV rank percentile |
| `ROT_UNUSUAL_VOLUME_SURGE_MULTIPLIER` | 2.0 | Volume vs 20d avg |
| `ROT_UNUSUAL_OI_SURGE_PCT` | 20.0 | OI increase % |
| `ROT_UNUSUAL_SKEW_STD_THRESHOLD` | 2.0 | P/C ratio std devs |
| `ROT_UNUSUAL_COMPOSITE_MIN_SCORE` | 40.0 | Min score to store |
| `ROT_UNUSUAL_HISTORY_WINDOW_DAYS` | 20 | Baseline window |
| `ROT_UNUSUAL_PURGE_KEEP_DAYS` | 90 | Retention |

## Event Types
| Type | Detection | Threshold |
|------|-----------|-----------|
| `iv_spike` | IV percentile rank vs history | > 80th percentile |
| `volume_surge` | Z-score vs 20d avg | > 2x average |
| `oi_surge` | OI % change | > 20% |
| `skew_shift` | P/C ratio vs rolling mean | > 2 std devs |
| `sweep` | Heuristic sweep detection | -- |

Composite score (0-100) combines all signals. Events below `COMPOSITE_MIN_SCORE` discarded.

## Rolling Baselines (`history.py`)
Per-ticker in-memory stats: IV rank, volume z-score, OI change, skew mean/std. LRU eviction at 500 tickers. Cold start uses conservative defaults.

## Background Loop
Every 5min in `server.py`: fetch recent signals -> `UnusualDetector.scan_batch()` -> save to `unusual_events` -> purge old (90d).

## DB: `unusual_events`
id (TEXT PK), ticker, event_type, score (REAL 0-100), details_json, signal_id, detected_at (REAL)

## Tests
`test_unusual_{types,detector,history,db}.py`
