<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Testing

- **Framework**: pytest 8+, pytest-asyncio 0.23+, pytest-cov 4.1+, ruff 0.2+
- **Async mode**: `asyncio_mode = "auto"` (pyproject.toml)
- **Run**: `pytest` from root
- **Patterns**: temp SQLite per test, all external APIs mocked, dual-path NLP/legacy testing

## Test Files

### Core Pipeline
| File | Coverage |
|------|----------|
| `test_event_builder.py` | Event extraction, NLP vs legacy, entities |
| `test_credibility.py` | 12 heuristic factors |
| `test_ml_credibility.py` | ML features, fallback, mock inference |
| `test_trade_builder.py` | Strategy selection, liquidity gates, quality |
| `test_database.py` | Schema, migrations, CRUD |
| `test_parser.py` | LLM response parsing, malformed JSON |
| `test_trend_engine_rss.py` | RSS trend detection, bypass |
| `test_rss_ingestor.py` | Feed parsing, dedup |
| `test_multi_ingestor.py` | Multi-source aggregation |
| `test_query_cache.py` | TTL, invalidation, thundering herd |
| `test_feedback.py` | Analyzer, suppressor, tier gates |

### Backtesting (11 files)
`test_backtest_{types,metrics,engine,monte_carlo,risk,walk_forward,optimizer,benchmark,comparator,tier_gate,report}.py`

### Analytics (10 files)
`test_unusual_{types,detector,history,db}.py`, `test_sector_{types,analysis,db}.py`, `test_correlation_{types,analysis,db}.py`

### Enterprise (4 files)
`test_export_{types,scheduler,lineage}.py`, `test_enterprise_db.py`

### Archive
`test_signal_archive.py` -- retention, unified CTE, 14 query integration

### Fixtures
`conftest.py` -- temp DB, mocks, sample data

## Commands
```bash
pytest                              # all tests
pytest --cov=rot                    # with coverage
pytest tests/test_database.py       # specific file
pytest tests/test_backtest_*.py     # pattern match
pytest -v                           # verbose
```
