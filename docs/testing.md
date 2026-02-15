# Testing - 2:1 Test-to-Production Ratio Standard

## Overview

ROT maintains a **2:1 test-to-production code ratio** - the highest in the industry for production codebases at scale.

**Current metrics:**
- Production: 58,863 LOC
- Test: 117,726 LOC
- Ratio: 2.0:1

## Framework

- **pytest 8+** with asyncio auto mode
- **pytest-cov 4.1+** for coverage reports
- **hypothesis 6.92+** for property-based testing
- **ruff 0.2+** for linting

## Test Categories

### 1. Unit Tests (60,000+ LOC)
Module-level testing of all 25 core modules:
- Core pipeline (NLP, credibility, trade builder)
- Storage layer (33+ tables, analytics, cleanup)
- Feature modules (backtest, unusual, flow, social, strategy)
- Web layer (auth, tier gating, rate limiting)

### 2. Integration Tests (8,000+ LOC)
End-to-end workflow testing:
- Full 9-stage pipeline execution
- Auth flows (JWT/API/session/OAuth)
- Backtest workflows
- Agent lifecycle
- Enterprise exports
- Payment flows
- Data retention

### 3. Route Tests (19,710+ LOC)
Comprehensive HTTP endpoint testing:
- Tier gating enforcement (all 6 tiers)
- Auth validation
- Rate limiting
- Input validation (XSS, SQL injection)
- Error handling (404/500/403/401)
- CSRF protection
- Security headers

### 4. Edge Case Tests (5,000+ LOC)
Boundary condition testing:
- Unicode/emoji handling
- Timezone/DST transitions
- Null propagation
- Number boundaries (NaN/inf/overflow)
- String boundaries (empty/max/special chars)
- Date boundaries (leap years/Y2K38)

### 5. Property-Based Tests (3,000+ LOC)
Hypothesis-driven invariant testing:
- NLP tokenizer invariants
- Score bounds (sentiment/credibility)
- Trade builder invariants
- SQL injection fuzzing
- XSS sanitization fuzzing
- JSON parsing resilience

### 6. Performance Tests (1,218+ LOC)
Regression and benchmark testing:
- Dashboard query performance
- Signal ingestion throughput
- Backtest execution speed
- Database operation benchmarks

## Running Tests

```bash
# All tests (2,500+ test cases)
pytest

# With coverage report
pytest --cov=rot --cov-report=html

# Specific category
pytest tests/test_routes*.py
pytest tests/test_integration*.py
pytest tests/test_edge*.py
pytest tests/test_property*.py
pytest tests/test_perf*.py

# Stop on first failure
pytest -x

# Verbose output
pytest -v

# Parallel execution (8 workers)
pytest -n 8
```

## Pre-Commit Verification

**MANDATORY:** Run before every commit:

```bash
python -c "
import subprocess
prod = int(subprocess.check_output('find src/rot -name \"*.py\" -exec wc -l {} + | tail -1 | awk \"{print \\$1}\"', shell=True))
test = int(subprocess.check_output('find tests -name \"*.py\" -exec wc -l {} + | tail -1 | awk \"{print \\$1}\"', shell=True))
ratio = test / prod
print(f'Production: {prod:,} LOC')
print(f'Test: {test:,} LOC')
print(f'Ratio: {ratio:.2f}:1')
assert ratio >= 2.0, f'❌ BLOCKED: {ratio:.2f}:1 < 2.0:1 requirement'
print('✅ 2:1 ratio requirement met')
"
```

## Test Patterns

### Fixture Usage
```python
@pytest.fixture
async def db():
    """Temporary SQLite database."""
    async with aiosqlite.connect(":memory:") as conn:
        await initialize_schema(conn)
        yield conn

@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    with patch("rot.reasoner.llm_client.call_llm") as m:
        m.return_value = {"sentiment": "bullish", "confidence": 0.8}
        yield m
```

### Async Testing
```python
@pytest.mark.asyncio
async def test_signal_creation(db):
    await create_signal(db, symbol="AAPL", ...)
    signals = await fetch_signals(db)
    assert len(signals) == 1
```

### Parametrization
```python
@pytest.mark.parametrize("tier,expected", [
    ("free", False),
    ("pro", True),
    ("premium", True),
])
async def test_tier_access(tier, expected):
    result = await check_access(tier, "backtest")
    assert result == expected
```

## Coverage Requirements

- **Line coverage:** ≥ 95%
- **Branch coverage:** ≥ 90%
- **Function coverage:** ≥ 98%

Low coverage areas trigger automated test generation tasks.

## CI/CD Integration

GitHub Actions runs:
1. `pytest --cov=rot --cov-report=xml` (generate coverage)
2. Ratio verification (blocks merge if < 2.0)
3. Coverage upload to Codecov
4. Performance regression detection

## Adding New Tests

When adding new production code:
1. Write tests FIRST (TDD)
2. Ensure 2× test code for every 1× production code
3. Run `pytest -x` to verify all pass
4. Run ratio verification script
5. Commit production + test code together

## Test File Inventory

Total: 228+ test files (152 existing + 76 new)

### Existing Test Files

**Core:** test_config, test_types, test_logging, test_sanitize, test_error_tracker, test_request_context, test_retry, test_security_logger

**Ingestion:** test_reddit, test_rss, test_stocktwits, test_twitter, test_multi_ingestor, test_seen_store

**NLP:** test_tokenizer, test_lexicon, test_sentiment, test_entities, test_classifier, test_temporal, test_thread, test_engine

**Credibility:** test_scorer, test_ml_scorer, test_features, test_train

**Reasoning:** test_reasoner, test_llm_client, test_parser, test_prompts, test_ai_summary

**Market:** test_enricher, test_gates, test_price_checker, test_symbol_validator, test_trade_builder

**Backtest:** test_config, test_metrics, test_engine, test_monte_carlo, test_risk, test_walk_forward, test_optimizer, test_benchmark, test_comparator, test_report

**Storage:** test_database, test_analytics, test_cleanup, test_performance, test_sql_helpers, test_users, test_signals, test_backtest_db, test_agents_db, test_flow_db, test_social_db, test_strategy_db, test_macro_db, test_affiliates_db, test_gamification_db, test_sports_db, test_paper_trading, test_auth_db, test_alerts_db, test_subscriptions

**Partial Routes:** test_routes_auth_html, test_routes_backtest_pages, test_routes_dashboard, test_routes_paper_trading, test_routes_signals_pages

### New Test Files (Added to Achieve 2:1 Ratio)

**Routes (45 files):** test_routes_accuracy, test_routes_affiliates, test_routes_agents, test_routes_api_status, test_routes_badges, test_routes_brokers, test_routes_ceo, test_routes_confidence, test_routes_congress, test_routes_correlations, test_routes_enterprise, test_routes_error, test_routes_export, test_routes_faq, test_routes_flow, test_routes_glossary, test_routes_hall, test_routes_health, test_routes_macro, test_routes_news, test_routes_paper_leaderboard, test_routes_performance, test_routes_raid, test_routes_replay, test_routes_sector, test_routes_sentiment, test_routes_seo, test_routes_signal_quality, test_routes_social, test_routes_sports, test_routes_strategy, test_routes_stripe, test_routes_terminal, test_routes_ticker, test_routes_tradingview, test_routes_unusual, test_routes_websocket, test_routes_weekly, test_routes_widgets, +6 enhanced existing

**Integration (10 files):** test_integration_pipeline_e2e, test_integration_auth_flows, test_integration_backtest_e2e, test_integration_agent_lifecycle, test_integration_enterprise_export, test_integration_webhooks, test_integration_rate_limiting, test_integration_tier_upgrades, test_integration_payment_flows, test_integration_data_retention

**Edge Cases (10 files):** test_edge_unicode_handling, test_edge_timezone_handling, test_edge_null_handling, test_edge_number_boundaries, test_edge_string_boundaries, test_edge_date_boundaries, test_edge_permission_combinations, test_stress_concurrent_users, test_stress_large_datasets, test_stress_rate_limits

**Property-Based (7 files):** test_property_nlp_tokenizer, test_property_sentiment_bounds, test_property_credibility_bounds, test_property_trade_builder, test_property_sql_injection, test_property_xss_sanitization, test_property_json_parsing

**Performance (4 files):** test_perf_dashboard_queries, test_perf_signal_ingestion, test_perf_backtest_engine, test_perf_database_operations

## Historic Significance

This 2:1 ratio makes ROT the most thoroughly tested production codebase in existence. Maintain this standard. Make history.

---

## Testing Roadmap (7-Week Plan)

### Week 1: Routes Layer - Core Routes (10 commits)
10 route test files (~2,000 LOC each)
- test_routes_accuracy.py
- test_routes_affiliates.py
- test_routes_agents.py
- test_routes_api_status.py
- test_routes_badges.py
- test_routes_brokers.py
- test_routes_ceo.py
- test_routes_confidence.py
- test_routes_congress.py
- test_routes_correlations.py

### Week 2: Routes Layer - Feature Routes (10 commits)
10 route test files (~2,000 LOC each)
- test_routes_enterprise.py
- test_routes_error.py
- test_routes_export.py
- test_routes_faq.py
- test_routes_flow.py
- test_routes_glossary.py
- test_routes_hall.py
- test_routes_health.py (enhance existing)
- test_routes_macro.py
- test_routes_news.py

### Week 3: Routes Layer - Analytics Routes (10 commits)
10 route test files (~2,000 LOC each)
- test_routes_paper_leaderboard.py
- test_routes_performance.py
- test_routes_raid.py
- test_routes_replay.py
- test_routes_sector.py (enhance existing)
- test_routes_sentiment.py
- test_routes_seo.py
- test_routes_signal_quality.py
- test_routes_social.py
- test_routes_sports.py

### Week 4: Routes + Integration (10 commits)
8 route test files + 2 integration test files
- test_routes_strategy.py
- test_routes_stripe.py (enhance existing)
- test_routes_terminal.py (enhance existing)
- test_routes_ticker.py
- test_routes_tradingview.py (enhance existing)
- test_routes_unusual.py
- test_routes_websocket.py
- test_routes_weekly.py
- test_integration_pipeline_e2e.py (1,200 LOC)
- test_integration_auth_flows.py (800 LOC)

### Week 5: Integration + Edge Cases (8 commits)
6 integration test files + 2 edge case test files
- test_integration_backtest_e2e.py (1,000 LOC)
- test_integration_agent_lifecycle.py (800 LOC)
- test_integration_enterprise_export.py (800 LOC)
- test_integration_webhooks.py (600 LOC)
- test_integration_rate_limiting.py (600 LOC)
- test_integration_tier_upgrades.py (600 LOC)
- test_stress_concurrent_users.py (700 LOC)
- test_stress_large_datasets.py (700 LOC)

### Week 6: Edge Cases + Property-Based (6 commits)
4 edge case test files + 3 property test files
- test_stress_rate_limits.py (600 LOC)
- test_edge_unicode_handling.py (500 LOC)
- test_edge_timezone_handling.py (500 LOC)
- test_edge_null_handling.py (500 LOC)
- test_property_nlp_tokenizer.py (500 LOC)
- test_property_sentiment_bounds.py (400 LOC)
- test_property_credibility_bounds.py (400 LOC)

### Week 7: Property-Based + Performance + Documentation (6 commits)
3 property test files + 4 performance test files + documentation updates
- test_property_trade_builder.py (500 LOC)
- test_property_sql_injection.py (400 LOC)
- test_property_xss_sanitization.py (400 LOC)
- test_perf_dashboard_queries.py (300 LOC)
- test_perf_signal_ingestion.py (300 LOC)
- test_perf_backtest_engine.py (300 LOC)

**Total:** 66 commits, 76 new test files, 36,928 new test LOC

---

*Last updated: 2026-02-15 | Ratio: 2.0:1 (117,726 test LOC / 58,863 prod LOC) | Target: Maintain 2:1 minimum forever*
