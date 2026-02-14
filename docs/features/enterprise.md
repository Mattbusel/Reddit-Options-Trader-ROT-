# Enterprise Features — ROT Feature Reference
> Part of the ROT documentation suite. See [CLAUDE.md](../../CLAUDE.md) for the full index.

## Quick Start for Agents
- Key files: `src/rot/export/` (4 modules: `types.py`, `scheduler.py`, `lineage.py`, `__init__.py`), `src/rot/web/routes/enterprise.py`
- DB tables: `export_schedules`, `data_exports`, `sponsored_signals`
- Routes: `GET /enterprise`, `POST /api/v1/enterprise/data-export`, `POST /api/v1/enterprise/sponsored/submit`, `GET /api/v1/enterprise/sponsored/status`, `GET /api/v1/enterprise/usage`, `GET /api/v1/enterprise/analytics/overview`, `GET /api/v1/enterprise/lineage/{signal_id}`
- Config: `ROT_EXPORT_SCHEDULER_INTERVAL_S`, `ROT_EXPORT_MAX_ROWS_PER_EXPORT`

---

## Module Layout

| File | Purpose |
|------|---------|
| `__init__.py` | Exports ExportJob, ExportScheduler, LineageBuilder |
| `types.py` | Frozen dataclasses: ExportJob, ExportResult, SignalLineage, ScheduleConfig, LineageStep |
| `scheduler.py` | ExportScheduler: scheduled recurring exports, background job runner, CSV/JSON generation |
| `lineage.py` | LineageBuilder: full signal provenance chain (9-step lineage) |

## Feature Areas

### 1. Export Scheduler

Supports scheduled recurring data exports for enterprise customers:
- **Frequencies**: daily, weekly, on-demand
- **Formats**: CSV, JSON
- **Filters**: by ticker, event type, stance, date range, confidence threshold
- **Background runner**: checks `export_schedules` table every hour (configurable) for pending exports

The scheduler runs as a background `asyncio` task in `server.py`, following the same pattern as the unusual activity scanner: initial delay, while-not-stopped loop, try/except with logging, asyncio.sleep.

### 2. Signal Lineage (9-Step Provenance Chain)

`LineageBuilder` traces the complete provenance of any signal through the pipeline:

| Step | Stage | Data |
|------|-------|------|
| 1 | Source | Reddit post/RSS entry/StockTwits/Twitter origin |
| 2 | Ingestion | Timestamp, source type, dedup status |
| 3 | Trend | Trend score, velocity metrics, window |
| 4 | NLP | Sentiment, entities, classifications, temporal |
| 5 | Event | Event type, stance, horizon, confidence |
| 6 | Market | Price, market cap, IV, options chain data |
| 7 | Credibility | ML score, heuristic score, adjustment factors |
| 8 | LLM | Reasoning thesis, catalyst window, risk notes |
| 9 | Trade | Strategy, legs, quality score, do-not-trade reasons |

Lineage is constructed by reading the signal's `event_data`, `market_data`, `reasoning`, and `trade_idea` JSON blobs and assembling the chain of `LineageStep` objects.

### 3. Sponsored Signals

Enterprise customers can submit sponsored signals that appear in the dashboard alongside organic signals:
- Submission via `POST /api/v1/enterprise/sponsored/submit`
- Status tracking via `GET /api/v1/enterprise/sponsored/status`
- Sponsored signals are flagged with `sponsored=1` and `sponsored_by` in the `signals` table
- Dashboard template shows a visual indicator for sponsored content

### 4. Analytics Overview API

`GET /api/v1/enterprise/analytics/overview` returns a 7-day analytics summary:
- Total signals generated
- Average confidence score
- Win rate across all stances
- Event type distribution
- Source breakdown

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/enterprise` | Dashboard: analytics charts, export history, lineage lookup, schedule management |
| POST | `/api/v1/enterprise/data-export` | Request data export (CSV/JSON, optional lineage inclusion) |
| POST | `/api/v1/enterprise/sponsored/submit` | Submit a sponsored signal |
| GET | `/api/v1/enterprise/sponsored/status` | Check sponsored signal status |
| GET | `/api/v1/enterprise/usage` | Enterprise usage statistics |
| GET | `/api/v1/enterprise/analytics/overview` | 7-day analytics overview |
| GET | `/api/v1/enterprise/lineage/{signal_id}` | Full signal lineage/provenance chain |

## DB Tables

**`export_schedules`**: id, user_id, format, frequency, filters_json, last_run_at, next_run_at, created_at

**`data_exports`**: Enterprise data export request tracking

**`sponsored_signals`**: Enterprise sponsored signal submissions

## Tier Gating

Enterprise features are exclusively gated to the Enterprise tier:
- `gate_data_licensing()` -- controls data export access
- `gate_sponsored_access()` -- controls sponsored signal submission
- Enterprise tier: 100,000 API calls/day, custom webhooks, bulk export

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ROT_EXPORT_SCHEDULER_INTERVAL_S` | `3600` | Seconds between scheduler checks (1 hour) |
| `ROT_EXPORT_MAX_ROWS_PER_EXPORT` | `1000000` | Maximum rows per export file |

## Tests

4 test files:
- `test_export_types.py` -- ExportJob, ExportResult, SignalLineage, ScheduleConfig dataclass tests
- `test_export_scheduler.py` -- Schedule creation, pending export detection, export generation
- `test_export_lineage.py` -- Lineage chain construction, batch lineage, step ordering
- `test_enterprise_db.py` -- Export schedule CRUD, analytics queries, lineage data retrieval

## Design Notes

- Lineage is read-only and reconstructed from existing signal metadata. No additional data is stored for lineage purposes.
- The export scheduler is decoupled from the main pipeline loop to avoid blocking signal processing.
- Custom webhooks (`src/rot/alerts/webhook.py`) are Enterprise-only and allow customers to receive signal data at their own HTTP endpoints.
- Export files use the unified CTE to include archived signals, enabling historical data exports beyond the 14-day live retention.
