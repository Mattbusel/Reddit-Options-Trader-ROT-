<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Enterprise Features

- **Files**: `src/rot/export/{types,scheduler,lineage,__init__}.py`, `src/rot/web/routes/enterprise.py`
- **DB**: `export_schedules`, `data_exports`, `sponsored_signals`
- **Config**: `ROT_EXPORT_SCHEDULER_INTERVAL_S` (3600), `ROT_EXPORT_MAX_ROWS_PER_EXPORT` (1000000)
- **Tier**: Enterprise-only via `gate_data_licensing()`, `gate_sponsored_access()`

## Features

### Export Scheduler
Recurring data exports: daily/weekly/on-demand, CSV/JSON, filterable (ticker, event_type, stance, date, confidence). Background asyncio task checks `export_schedules` hourly. Uses unified CTE for archived signals.

### Signal Lineage (9-Step Provenance)
`LineageBuilder` reconstructs from existing signal JSON blobs (no extra storage):
1. Source (Reddit/RSS/StockTwits/Twitter) -> 2. Ingestion -> 3. Trend -> 4. NLP -> 5. Event -> 6. Market -> 7. Credibility -> 8. LLM -> 9. Trade

### Sponsored Signals
Enterprise customers submit via API; flagged with `sponsored=1` + `sponsored_by` in `signals` table.

### Analytics Overview
`GET /api/v1/enterprise/analytics/overview`: 7d summary (total signals, avg confidence, win rate, event type distribution, source breakdown).

## Routes
| Method | Path | Description |
|--------|------|-------------|
| GET | `/enterprise` | Dashboard (analytics, exports, lineage, schedules) |
| POST | `/api/v1/enterprise/data-export` | Request export (CSV/JSON, optional lineage) |
| POST | `/api/v1/enterprise/sponsored/submit` | Submit sponsored signal |
| GET | `/api/v1/enterprise/sponsored/status` | Sponsored status |
| GET | `/api/v1/enterprise/usage` | Usage stats |
| GET | `/api/v1/enterprise/analytics/overview` | 7d analytics |
| GET | `/api/v1/enterprise/lineage/{signal_id}` | Signal provenance |

## DB
- **`export_schedules`**: id, user_id, format, frequency, filters_json, last_run_at, next_run_at, created_at
- **`data_exports`**: export request tracking
- **`sponsored_signals`**: sponsored signal submissions

## Tests
`test_export_{types,scheduler,lineage}.py`, `test_enterprise_db.py`
