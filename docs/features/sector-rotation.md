# Sector Rotation Analysis — ROT Feature Reference
> Part of the ROT documentation suite. See [CLAUDE.md](../../CLAUDE.md) for the full index.

## Quick Start for Agents
- Key files: `src/rot/analysis/sector.py`, `src/rot/analysis/sector_types.py`, `src/rot/analysis/__init__.py`
- DB tables: None (computed on-demand from `signals` + `signal_performance`)
- Routes: `GET /sector-rotation`, `GET /sector-rotation/drill-down/{sector}`, `GET /api/v1/sectors/rankings`
- Config: `ROT_SECTOR_MIN_SIGNALS`, `ROT_SECTOR_MOMENTUM_WINDOW_DAYS`

---

## Module Layout

| File | Purpose |
|------|---------|
| `__init__.py` | Exports SectorAnalyzer, CorrelationAnalyzer |
| `sector.py` | Sector rotation intelligence: momentum scoring, rotation detection, capital flow, rankings |
| `sector_types.py` | Frozen dataclasses: SectorMomentum, RotationEvent, SectorRanking, CapitalFlow |

## Data Types

**SectorMomentum**: sector name, signal count, avg confidence, win rate, momentum score, trend direction (improving/declining/stable)

**RotationEvent**: from_sector, to_sector, strength, detected_at -- represents capital rotation between sectors

**SectorRanking**: ranked list of sectors by composite momentum score

**CapitalFlow**: sector, net flow direction, magnitude -- inferred from signal volume and stance distribution

## Analysis Components

### Momentum Scoring
Computes a momentum score per sector using a rolling window (default 30 days, configurable via `ROT_SECTOR_MOMENTUM_WINDOW_DAYS`). Factors include:
- Signal volume trend (increasing/decreasing)
- Average confidence trajectory
- Win rate over the window
- Composite weighted score

### Rotation Detection
Identifies capital rotation events by detecting simultaneous momentum increases in one sector paired with decreases in another. Produces `RotationEvent` objects with a strength metric.

### Capital Flow
Infers net capital flow direction per sector from the balance of bullish vs bearish signals, weighted by confidence. Positive flow indicates net bullish sentiment, negative indicates net bearish.

### Sector Rankings
Aggregates momentum, win rate, and signal volume into a ranked list of sectors. Sectors with fewer than `ROT_SECTOR_MIN_SIGNALS` (default 2) signals are excluded from rankings.

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sector-rotation` | Full dashboard: rankings table, flow gauges, rotation arrows |
| GET | `/sector-rotation/drill-down/{sector}` | HTMX partial: ticker breakdown within a sector |
| GET | `/api/v1/sectors/rankings` | JSON API: sector ranking data |

## HTMX Drill-Down

The sector rotation dashboard uses HTMX for interactive drill-down. Clicking a sector row triggers an HTMX request to `/sector-rotation/drill-down/{sector}`, which returns a partial HTML fragment showing the individual tickers within that sector, their signal counts, win rates, and momentum scores.

## On-Demand Analysis Pattern

Sector rotation analysis is computed on-demand when the user visits the page, not via a background loop. Results are cached via the dashboard query cache (`src/rot/web/query_cache.py`) with a 120-second TTL to avoid re-running expensive aggregations on every page load. This differs from the unusual activity scanner which runs on a fixed interval.

## Tier Gating

Access is controlled by `gate_sector_rotation_access()` in `src/rot/web/tier_gate.py`.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ROT_SECTOR_MIN_SIGNALS` | `2` | Minimum signals per sector to include in analysis |
| `ROT_SECTOR_MOMENTUM_WINDOW_DAYS` | `30` | Rolling window for momentum scoring |

## Sector Groups

The NLP engine (`src/rot/nlp/entities.py`) defines approximately 12 sector groups used for sector expansion during entity resolution. These same groupings are used by the sector rotation analysis to categorize signals. The `sector` field on the `signals` table stores the resolved sector.

## Tests

3 test files:
- `test_sector_types.py` -- SectorMomentum, RotationEvent, SectorRanking, CapitalFlow dataclass tests
- `test_sector_analysis.py` -- Momentum scoring, rotation detection, capital flow, sector ranking, edge cases
- `test_sector_db.py` -- Time series queries, drill-down, ranking, performance

## Design Notes

- Sectors with too few signals are excluded to avoid noisy rankings.
- The on-demand pattern was chosen because sector analysis is requested infrequently (page visits) compared to signal processing, making a background loop wasteful.
- The HTMX drill-down avoids full page reloads, keeping the dashboard responsive.
- Signal data comes from the unified CTE (live + archived signals) when available, enabling long-term sector trend analysis beyond the 14-day live retention window.
