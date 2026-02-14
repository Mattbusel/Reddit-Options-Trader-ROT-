<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Sector Rotation Analysis

- **Files**: `src/rot/analysis/{sector,sector_types,__init__}.py`
- **DB**: None (computed on-demand from `signals` + `signal_performance`)
- **Routes**: `GET /sector-rotation`, `GET /sector-rotation/drill-down/{sector}` (HTMX), `GET /api/v1/sectors/rankings`
- **Config**: `ROT_SECTOR_MIN_SIGNALS` (2), `ROT_SECTOR_MOMENTUM_WINDOW_DAYS` (30)
- **Tier**: `gate_sector_rotation_access()`

## Types
- **SectorMomentum**: sector, signal_count, avg_confidence, win_rate, momentum_score, trend direction
- **RotationEvent**: from_sector, to_sector, strength, detected_at
- **SectorRanking**: ranked sectors by composite momentum
- **CapitalFlow**: sector, net flow (inferred from bullish/bearish signal balance weighted by confidence)

## Analysis
1. **Momentum Scoring**: Rolling 30d window -- signal volume trend, confidence trajectory, win rate, composite score
2. **Rotation Detection**: Simultaneous momentum increase in one sector + decrease in another
3. **Capital Flow**: Net bullish/bearish sentiment per sector
4. **Rankings**: Composite score, excludes sectors with < `MIN_SIGNALS` signals

## On-Demand Pattern
Computed on page visit, cached 120s via query cache. Uses unified CTE (live + archived). HTMX drill-down for per-ticker breakdown within sector.

## Sector Groups
~12 groups defined in `nlp/entities.py`, used for entity resolution and rotation analysis. Stored in `signals.sector`.

## Tests
`test_sector_{types,analysis,db}.py`
