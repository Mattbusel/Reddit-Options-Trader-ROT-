# Testing — ROT Architecture Reference

> Part of the ROT documentation suite. See [CLAUDE.md](../CLAUDE.md) for the full index.

## Quick Start for Agents

- Key file(s): `tests/` directory, `tests/conftest.py` (shared fixtures)
- Key pattern: pytest + pytest-asyncio, ~689 tests, no external API calls (all mocked), async tests with `asyncio_mode = "auto"`
- Run: `pytest` from project root

---

## Framework

| Setting | Value |
|---------|-------|
| Test framework | pytest >= 8.0 |
| Async support | pytest-asyncio >= 0.23 |
| Coverage | pytest-cov >= 4.1 |
| Linting | ruff >= 0.2 |
| Async mode | `asyncio_mode = "auto"` (in pyproject.toml) |
| Total tests | ~689 |

---

## Test File Inventory

### Core Pipeline Tests

| File | Coverage |
|------|----------|
| `test_event_builder.py` | Event extraction, NLP vs legacy paths, entity extraction |
| `test_credibility.py` | All 12 heuristic credibility scoring factors |
| `test_ml_credibility.py` | ML feature extraction, ML scorer fallback, mock model inference |
| `test_trade_builder.py` | Trade strategy selection, liquidity gates, quality scoring |
| `test_database.py` | Schema creation, migrations, CRUD operations |
| `test_parser.py` | LLM response parsing, malformed JSON handling |
| `test_trend_engine_rss.py` | RSS trend detection, bypass logic |
| `test_rss_ingestor.py` | RSS feed parsing, dedup |
| `test_multi_ingestor.py` | Multi-source aggregation |
| `test_query_cache.py` | Dashboard query cache: TTL, invalidation, thundering herd, edge cases |
| `test_feedback.py` | Feedback analyzer (slope, MA, feature importance, suppression candidates), suppressor (category/source/low-confidence suppression, apply), tier gate tests |

### Backtesting Tests

| File | Coverage |
|------|----------|
| `test_backtest_types.py` | BacktestConfig validation, serialization, BacktestResult to_dict, TradeRecord/EquityPoint/DrawdownPeriod creation |
| `test_backtest_metrics.py` | Sharpe, Sortino, Calmar, max drawdown, drawdown periods, profit factor, win rate, VaR, CVaR, MAE/MFE, monthly returns |
| `test_backtest_engine.py` | Position sizing (fixed/Kelly/confidence), stop loss/take profit, concurrent limits, filters, stance-aware P&L |
| `test_backtest_monte_carlo.py` | Bootstrap resampling, percentile curves, reproducibility, probabilities |
| `test_backtest_risk.py` | VaR, CVaR, MAE/MFE, underwater analysis, Ulcer Index, skewness/kurtosis |
| `test_backtest_walk_forward.py` | Fold generation, IS/OOS split, stability scoring, degradation |
| `test_backtest_optimizer.py` | Grid generation, heatmap, max_combos cap, Sharpe ranking |
| `test_backtest_benchmark.py` | Alpha, beta, correlation, information ratio, benchmark curve |
| `test_backtest_comparator.py` | Correlation matrix, rankings, summary table, strategy stats |
| `test_backtest_tier_gate.py` | Free/Pro/Premium/Ultra/Enterprise tier access, feature hierarchy |
| `test_backtest_report.py` | CSV trade export, HTML report generation with risk/Monte Carlo sections |

### Analytics Tests

| File | Coverage |
|------|----------|
| `test_unusual_types.py` | UnusualEvent, UnusualScore, UnusualSummary dataclass creation and validation |
| `test_unusual_detector.py` | IV rank, volume surge, OI surge, skew shift, sweep detection, composite scoring, batch scan |
| `test_unusual_history.py` | Rolling stats, percentile computation, cold start, baseline updates |
| `test_unusual_db.py` | save/query/purge unusual events, timeline queries, summary aggregation |
| `test_sector_types.py` | SectorMomentum, RotationEvent, SectorRanking, CapitalFlow dataclass tests |
| `test_sector_analysis.py` | Momentum scoring, rotation detection, capital flow, sector ranking, edge cases |
| `test_sector_db.py` | Time series queries, drill-down, ranking, performance |
| `test_correlation_types.py` | CorrelationPair, TickerCluster, LeadLagPair, NetworkGraph dataclass tests |
| `test_correlation_analysis.py` | Co-fire correlation, clustering, lead-lag detection, network construction |
| `test_correlation_db.py` | Correlation matrix queries, ticker correlations, signal pair queries |

### Enterprise Tests

| File | Coverage |
|------|----------|
| `test_export_types.py` | ExportJob, ExportResult, SignalLineage, ScheduleConfig dataclass tests |
| `test_export_scheduler.py` | Schedule creation, pending export detection, export generation |
| `test_export_lineage.py` | Lineage chain construction, batch lineage, step ordering |
| `test_enterprise_db.py` | Export schedule CRUD, analytics queries, lineage data retrieval |

### Archive Tests

| File | Coverage |
|------|----------|
| `test_signal_archive.py` | Table creation, archive_before_purge, idempotency, purge retention, all 14 analytics queries include archived data, feedback analyzer includes archived data, initial migration |

### Shared

| File | Purpose |
|------|---------|
| `conftest.py` | Shared fixtures (temporary DB, mock objects, sample data) |

---

## Test Patterns

### Dual-Path Testing
All existing tests must pass through both NLP and legacy paths. The `EventBuilder` is tested with and without an `NLPEngine` instance.

### Database Tests
Database tests use temporary SQLite files (created via `tempfile`). Each test gets a fresh database instance.

### Async Tests
Async tests use `pytest-asyncio` with `asyncio_mode = "auto"`. No need for `@pytest.mark.asyncio` decorator -- all async test functions are detected automatically.

### No External API Calls
All external dependencies (Reddit API, yfinance, LLM providers, Stripe) are mocked in tests. No real network calls.

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=rot

# Run specific test file
pytest tests/test_database.py

# Run specific test
pytest tests/test_database.py::test_create_tables

# Run with verbose output
pytest -v

# Run only backtest tests
pytest tests/test_backtest_*.py
```
