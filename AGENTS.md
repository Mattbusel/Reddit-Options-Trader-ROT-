# AGENTS.md -- Agent Speed Reference for ROT Codebase

> Read this FIRST. It will save you 10+ minutes per task.

---

## 1. SPEED INDEX -- Before You Start

```
Test all:       python -m pytest tests/ -x --tb=short
Test one file:  python -m pytest tests/test_foo.py -v
Test one func:  python -m pytest tests/test_foo.py::test_bar -v
Server:         python -m rot.app.server
Lint:           ruff check src/ tests/
Line length:    100 chars (ruff, pyproject.toml)
Python:         >=3.10 (deployed 3.12)
Async mode:     auto (pyproject.toml: asyncio_mode = "auto") -- NO @pytest.mark.asyncio needed
DB fixture:     async def db(tmp_path) -> Database: connect/yield/close (see Section 6)
Templates:      extend base.html, use {% block content %}...{% endblock %}
Static JS:      /static/js/ for Chart.js, HTMX, HTMX-WS (self-hosted, no CDN)
```

---

## 2. IMPORT MAP -- Every Module's Key Exports

### Core
```
rot.core.types       -> Post, Comment, ThreadSnapshot, TrendCandidate, Event, Evidence,
                        ReasoningPacket, TradeIdea, OptionLeg
rot.core.config      -> Settings (24 config sections: reddit, llm, market, trend, alert, web,
                        rss, stocktwits, twitter_ingest, twitter, auth, stripe, tier_limits,
                        email, sponsored, ml, feedback, backtest_server, unusual, sector,
                        export_scheduler, archive, macro, agent)
rot.core.logging     -> JsonlLogger, cleanup_market_cache
```

### Pipeline
```
rot.ingest.reddit_ingestor    -> RedditIngestor
rot.ingest.rss_ingestor       -> RSSIngestor, RSSFeedConfig
rot.ingest.multi_ingestor     -> MultiSourceIngestor
rot.ingest.stocktwits_ingestor -> StockTwitsIngestor
rot.ingest.twitter_ingestor   -> TwitterIngestor
rot.ingest.seen_store         -> SeenStore
rot.trend.trend_engine        -> TrendEngine
rot.trend.trend_store         -> TrendStore
rot.extract.event_builder     -> EventBuilder
rot.extract.enricher          -> (ticker aliases, blocklists)
rot.credibility.scorer        -> CredibilityScorer
rot.credibility.ml_scorer     -> MLCredibilityScorer
rot.credibility.features      -> extract_features (32-float vector)
rot.credibility.train         -> train_model_from_db
rot.feedback.analyzer         -> FeedbackAnalyzer
rot.feedback.suppressor       -> SignalSuppressor
rot.reasoner.reasoner         -> Reasoner
rot.reasoner.llm_client       -> LLMClient
rot.reasoner.prompts          -> system_prompt, event_prompt
rot.reasoner.parser           -> parse_llm_response
rot.reasoner.ai_summary       -> backfill_ai_summaries
rot.market.trade_builder      -> TradeBuilder
rot.market.enricher           -> MarketEnricher
rot.market.symbol_validator   -> SymbolValidator
rot.market.price_checker      -> PriceChecker
rot.market.gates              -> (trade safety gates)
rot.app.runner                -> PipelineRunner
```

### NLP
```
rot.nlp                -> NLPEngine, NLPResult, SentimentResult, ResolvedEntity
rot.nlp.types          -> Token, SentimentResult, ResolvedEntity, NLPResult, ClassifiedEvent,
                          TemporalResult, ThreadResult, OptionsEntity, PositionEntity
rot.nlp.tokenizer      -> Tokenizer
rot.nlp.lexicon        -> LEXICON (500+ terms)
rot.nlp.sentiment      -> SentimentAnalyzer
rot.nlp.entities       -> EntityResolver
rot.nlp.classifier     -> EventClassifier
rot.nlp.temporal       -> TemporalAnalyzer
rot.nlp.thread         -> ThreadAnalyzer
rot.nlp.engine         -> NLPEngine
```

### Analytics
```
rot.backtest           -> BacktestConfig, BacktestEngine, BacktestResult, TradeRecord,
                          EquityPoint, DrawdownPeriod
rot.backtest.monte_carlo -> MonteCarloResult, run_monte_carlo
rot.backtest.risk      -> RiskMetrics, compute_risk_metrics
rot.backtest.walk_forward -> WalkForwardResult, run_walk_forward
rot.backtest.optimizer -> OptimizationResult, optimize
rot.backtest.benchmark -> BenchmarkComparison, compare_to_benchmark
rot.backtest.comparator -> ComparisonResult, compare_strategies
rot.backtest.report    -> generate_csv_trades, generate_html_report
rot.unusual            -> UnusualEvent, UnusualDetector, UnusualScore
rot.unusual.types      -> UnusualEvent, UnusualScore, UnusualSummary
rot.unusual.history    -> UnusualHistory
rot.analysis           -> SectorAnalyzer, CorrelationAnalyzer
rot.analysis.sector    -> SectorAnalyzer
rot.analysis.correlations -> CorrelationAnalyzer
rot.macro              -> MacroEvent, EarningsEvent, InsiderTrade, FOMCMeeting, EventImpact,
                          HistoricalReaction, SeasonalPattern, EconomicCalendar,
                          EventImpactAnalyzer, EarningsCalendar, InsiderFeed,
                          FOMCTracker, SeasonalAnalyzer
rot.agents             -> AgentRule, AgentPerformance, AgentType, AgentStatus, AGENT_TYPES,
                          RuleEngine, AgentEngine
rot.export             -> ExportJob, ExportScheduler, LineageBuilder
```

### Web
```
rot.web.auth           -> get_current_user_optional, require_user, require_tier
rot.web.tier_gate      -> gate_signal, gate_signal_list, gate_chart_access, gate_filter_access,
                          gate_performance_access, gate_email_access, gate_heatmap_access,
                          gate_leaderboard_access, gate_market_context, gate_correlation_access,
                          gate_sentiment_access, gate_ticker_dive_access, gate_weekly_wrap_access,
                          gate_replay_access, gate_data_licensing, gate_sponsored_access,
                          gate_sector_rotation_access, gate_unusual_activity, gate_news_feed_access,
                          gate_congress_tracker_access, gate_paper_leaderboard_access,
                          gate_sports_betting_access, gate_signal_quality_access,
                          gate_backtest_access, gate_macro_access, gate_terminal_access,
                          gate_agent_access (27 functions)
rot.web.query_cache    -> QueryCache
rot.web.rate_limit     -> (rate limiting middleware)
rot.web.app            -> create_app
rot.storage.database   -> Database (100+ async methods)
```

### Alerts
```
rot.alerts.dispatcher  -> AlertDispatcher
rot.alerts.discord     -> (Discord webhook)
rot.alerts.email       -> EmailAlerter
rot.alerts.twitter     -> XPoster, format_tweet
rot.alerts.webhook     -> (custom webhooks)
```

---

## 3. ADD A NEW ROUTE -- Checklist

1. Create: `src/rot/web/routes/{name}.py`
2. Add `router = APIRouter()`
3. Register in `src/rot/web/app.py` -- import + `app.include_router()`
4. Create template: `src/rot/web/templates/{name}.html` (extends base.html)
5. If tier-gated: add `gate_{name}_access()` to `src/rot/web/tier_gate.py`
6. Add nav link to `src/rot/web/templates/base.html` (desktop + mobile)
7. Add tests: `tests/test_{name}.py`

### Route template (copy-paste):
```python
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_{name}_access

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/{name}")
async def {name}_page(request: Request):
    user = await get_current_user_optional(request)
    tier = user["tier"] if user else "free"
    access = gate_{name}_access(tier)
    db = request.app.state.db
    # your DB queries here
    templates = request.app.state.templates
    return templates.TemplateResponse("{name}.html", {
        "request": request,
        "user": user,
        "tier": tier,
        "access": access,
    })
```

### Template skeleton (copy-paste):
```html
{% extends "base.html" %}
{% block title %}Page Title - ROT{% endblock %}
{% block content %}
<div class="max-w-7xl mx-auto px-4 py-8">
    <h1 class="text-3xl font-bold text-amber-400 mb-6">Page Title</h1>
    {% if not access.has_access %}
    <div class="bg-gray-800 rounded-lg p-6 text-center">
        <p class="text-gray-400">Upgrade to Pro to access this feature.</p>
        <a href="/pricing" class="text-amber-400 hover:underline">View Plans</a>
    </div>
    {% else %}
    <!-- content here -->
    {% endif %}
</div>
{% endblock %}
```

### app.py registration (add to appropriate section):
```python
from rot.web.routes import {name}
app.include_router({name}.router, tags=["{name}"])
```

---

## 4. ADD A DB TABLE -- Checklist

1. Add `CREATE TABLE IF NOT EXISTS {name} (...)` to `_SCHEMA` in `src/rot/storage/database.py`
2. Add indexes: `CREATE INDEX IF NOT EXISTS idx_{name}_{col} ON {name}({col})`
3. For column additions to existing tables: add `ALTER TABLE ... ADD COLUMN ...` to `_MIGRATIONS`
4. Implement async CRUD methods on the `Database` class
5. Test with `db(tmp_path)` fixture pattern

### DB method template (copy-paste):
```python
async def insert_{name}(self, **kwargs) -> str:
    row_id = str(uuid.uuid4())
    await self.db.execute(
        "INSERT INTO {name} (id, ...) VALUES (?, ...)",
        (row_id, ...),
    )
    await self.db.commit()
    return row_id

async def get_{name}(self, row_id: str) -> dict | None:
    async with self.db.execute(
        "SELECT * FROM {name} WHERE id = ?", (row_id,)
    ) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None

async def query_{name}(self, limit: int = 50) -> list[dict]:
    async with self.db.execute(
        "SELECT * FROM {name} ORDER BY created_at DESC LIMIT ?", (limit,)
    ) as cursor:
        return [dict(r) for r in await cursor.fetchall()]

async def purge_old_{name}(self, keep_days: int = 90) -> int:
    import time
    cutoff = time.time() - keep_days * 86400
    cursor = await self.db.execute(
        "DELETE FROM {name} WHERE created_at < ?", (cutoff,)
    )
    await self.db.commit()
    return cursor.rowcount
```

### Migration template (for adding columns):
```python
# In _MIGRATIONS list:
"ALTER TABLE {table} ADD COLUMN {col} {type} DEFAULT {default}",
```

---

## 5. ADD A TIER GATE -- Template

```python
def gate_{name}_access(tier: str) -> dict:
    """Return {name} feature access flags based on tier."""
    _PAID = ("pro", "premium", "ultra", "enterprise")
    return {
        "has_access": tier in _PAID,
        # Premium+ features:
        "has_advanced": tier in ("premium", "ultra", "enterprise"),
        # Ultra+ features:
        "has_export": tier in ("ultra", "enterprise"),
        # Enterprise-only:
        "has_api": tier == "enterprise",
    }
```

Tier hierarchy: `free < pro < premium < ultra < enterprise`

`_PAID_TIERS = ("pro", "premium", "ultra", "enterprise")` is defined at top of tier_gate.py.

---

## 6. ADD A TEST FILE -- Template

```python
from __future__ import annotations

import pytest
from rot.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


async def test_something(db):
    # No @pytest.mark.asyncio needed (asyncio_mode = "auto")
    result = await db.some_method()
    assert result is not None
```

For non-DB tests:
```python
from rot.core.types import Event, Evidence

def test_pure_logic():
    event = Event(
        event_type="earnings_rumor",
        entities=["TSLA"],
        stance="bullish",
        time_horizon="earnings",
        evidence=[Evidence(
            post_id="abc", permalink="https://reddit.com/abc",
            subreddit="wsb", excerpt="test",
        )],
        confidence=0.5,
        meta={},
    )
    assert event.stance == "bullish"
```

Shared fixtures in `tests/conftest.py`: `sample_post`, `sample_snapshot`, `sample_candidate`,
`sample_event`, `sample_reasoning`.

---

## 7. FEATURE MATRIX -- Quick Reference

| Feature | Min Tier | Gate Function | Route File |
|---------|----------|---------------|------------|
| Dashboard | free | (none) | dashboard.py |
| Signals API | free | gate_signal / gate_signal_list | signals.py |
| Chart access | pro | gate_chart_access | dashboard.py |
| Filter access | pro | gate_filter_access | signals.py |
| Performance | pro | gate_performance_access | performance.py |
| Accuracy breakdown | pro | gate_performance_access | accuracy_breakdown.py |
| Confidence calib. | pro | gate_performance_access | confidence_calibration.py |
| Sentiment heatmap | pro | gate_heatmap_access / gate_sentiment_access | sentiment.py |
| Correlations | pro | gate_correlation_access | correlations.py |
| Sector rotation | pro | gate_sector_rotation_access | sector_rotation.py |
| Unusual activity | pro | gate_unusual_activity | unusual_activity.py |
| Signal quality | pro | gate_signal_quality_access | signal_quality.py |
| News feed | free* | gate_news_feed_access | news_feed.py |
| Congress tracker | pro | gate_congress_tracker_access | congress_tracker.py |
| Paper trading | free | (none) | paper_trading.py |
| Leaderboard | free* | gate_paper_leaderboard_access | paper_leaderboard.py |
| Sports tracker | free* | gate_sports_betting_access | sports_tracker.py |
| Backtest | pro | gate_backtest_access | backtest.py |
| Macro events | free* | gate_macro_access | macro.py |
| Terminal | premium | gate_terminal_access | terminal.py |
| Agents | ultra | gate_agent_access | agents.py |
| Data licensing | enterprise | gate_data_licensing | enterprise.py |
| Sponsored signals | enterprise | gate_sponsored_access | enterprise.py |
| Weekly wrap | free* | gate_weekly_wrap_access | weekly_wrap.py |
| Replay | pro | gate_replay_access | replay.py |
| Email alerts | free* | gate_email_access | auth_routes.py |
| Market context | pro | gate_market_context | dashboard.py |
| Ticker dive | free* | gate_ticker_dive_access | ticker_dive.py |

`*` = free tier gets limited/delayed access (acquisition funnel)

---

## 8. FILE OWNERSHIP -- Who Owns What

### Pipeline (sync thread)
```
src/rot/app/runner.py          -- PipelineRunner orchestration
src/rot/ingest/                -- all data ingestion
src/rot/trend/                 -- trend detection + ranking
src/rot/nlp/                   -- NLP analysis (10 modules)
src/rot/extract/               -- event building (NLP + legacy)
src/rot/credibility/           -- ML + heuristic scoring
src/rot/feedback/              -- suppressor (stage 6.5)
src/rot/reasoner/              -- LLM reasoning
src/rot/market/                -- trade building, enrichment, price checks
```

### Web (async FastAPI)
```
src/rot/web/app.py             -- FastAPI factory, route registration
src/rot/web/auth.py            -- JWT/API key/session auth
src/rot/web/tier_gate.py       -- 27 gate functions
src/rot/web/query_cache.py     -- dashboard query cache
src/rot/web/rate_limit.py      -- per-tier rate limiting
src/rot/web/routes/            -- 41 route files
src/rot/web/templates/         -- 39+ Jinja2 templates
src/rot/web/static/            -- self-hosted JS (Chart.js, HTMX)
```

### Storage
```
src/rot/storage/database.py    -- ALL DB operations (18+ tables, 100+ methods)
```

### Analytics engines (pure logic, no DB)
```
src/rot/backtest/              -- 12 modules, backtesting engine
src/rot/unusual/               -- 4 modules, unusual activity detection
src/rot/analysis/              -- 5 modules, sector + correlation
src/rot/macro/                 -- 7 modules, economic calendar + earnings + insider + FOMC
src/rot/agents/                -- 3 modules, autonomous trading agents
src/rot/export/                -- 4 modules, enterprise export + lineage
```

### Alerts
```
src/rot/alerts/                -- 5 modules (dispatcher, discord, email, twitter, webhook)
```

### Server + background loops
```
src/rot/app/server.py          -- uvicorn startup, ALL background loops, signal bridging
```

---

## 9. GOTCHAS -- Things That Bite Agents

1. **Route registration order matters**: Export routes MUST be registered BEFORE signals routes
   in `app.py`. The `/signals/export` path must match before the `/signals/{signal_id}` catch-all.

2. **`_SCHEMA` is safe to re-run**: Uses `CREATE TABLE IF NOT EXISTS`. No need to worry about
   double-creation.

3. **`_MIGRATIONS` is safe to re-run**: Each migration is wrapped in try/except. Adding a column
   that already exists silently succeeds.

4. **All test DB fixtures MUST follow connect/yield/close pattern**:
   ```python
   async def db(tmp_path):
       database = Database(db_path=str(tmp_path / "test.db"))
       await database.connect()
       yield database
       await database.close()
   ```

5. **Templates access via `request.app.state.templates`** -- not a global. Always pass `request`
   as first template context key.

6. **Tier hierarchy**: `free < pro < premium < ultra < enterprise`. Use
   `_PAID_TIERS = ("pro", "premium", "ultra", "enterprise")` from tier_gate.py.

7. **app.state objects** (set in app.py and server.py):
   `db`, `settings`, `signal_queue`, `query_cache`, `templates`,
   `feedback_analyzer`, `agent_engine`, `email_alerter`

8. **Frozen dataclasses**: All types in `rot.core.types` are `@dataclass(frozen=True)`.
   To modify, use `dataclasses.replace(event, confidence=0.9)`.

9. **JSON blob columns**: `market_data`, `reasoning`, `trade_idea`, `event_data` in signals table
   are TEXT columns containing JSON. Use `json.loads()` / `json.dumps()`.

10. **Win/loss logic**: Only `bullish` and `bearish` stances count as trades. Mixed/unknown are
    always neutral. See `_WIN_CASE_SQL` / `_LOSS_CASE_SQL` in database.py.

11. **Signal archive**: Signals are purged after 14 days. `archive_before_purge()` copies them to
    `signal_archive` first. Analytics queries use `_UNIFIED_CTE` to union live + archived data.

12. **No `@pytest.mark.asyncio`**: asyncio_mode is "auto" in pyproject.toml. Just write
    `async def test_xxx()` and it works.

13. **Pipeline runs in a background thread** (sync), web runs in async event loop. Signal callback
    uses `asyncio.run_coroutine_threadsafe()` to bridge sync->async.

14. **Query cache invalidation**: When adding new cached queries, invalidate them in
    `_async_signal_handler` in server.py if they change on new signals.

15. **self-hosted CDN**: Chart.js/HTMX/HTMX-WS are in `src/rot/web/static/js/`. Do NOT add
    external CDN links for these libraries.

---

## 10. BACKGROUND LOOPS IN SERVER.PY

All loops are started in `_run_server()` in `src/rot/app/server.py`.

| Loop | Startup Delay | Interval | What It Does |
|------|---------------|----------|--------------|
| Pipeline (thread) | 0s | `cfg.reddit.poll_interval_s` (20s) | Runs PipelineRunner.run_once() |
| DB cleanup (lifespan) | 0s | 3600s | api_usage purge, old signals, blob compaction, AI backfill |
| Price check | 30s | `cfg.market.price_check_interval_s` | Tracks prices for signal performance |
| Digest email | 60s | 3600s | Daily digest emails to subscribers |
| X/Twitter posting | 120s | `cfg.twitter.interval_s` (10800s) | Posts top signals to X |
| Cleanup | 30s | 1800s (30m) | Full purge, JSONL rotation, VACUUM, market cache |
| ML retrain | 60s | `cfg.ml.retrain_interval_s` (86400s) | Retrains credibility model |
| Feedback analysis | 120s | `cfg.feedback.analysis_interval_s` (21600s) | Quality analytics + suppression |
| Unusual activity | 60s | `cfg.unusual.scan_interval_s` (300s) | IV spikes, volume surges |
| Export scheduler | 120s | `cfg.export_scheduler.scheduler_interval_s` (3600s) | Enterprise exports |
| Macro data | 90s | `cfg.macro.calendar_poll_interval_s` | Calendar, earnings, insider, FOMC |

### Loop template (copy-paste for adding a new background loop):
```python
async def _my_loop(db, cfg, stop_event: threading.Event):
    """Background task that does X every Y seconds."""
    interval = cfg.my_interval_s
    log.info("My loop starting (interval=%ds)", interval)

    # Startup delay -- let DB initialize
    for _ in range(60):
        if stop_event.is_set():
            return
        await asyncio.sleep(1)

    while not stop_event.is_set():
        try:
            # --- your work here ---
            pass
        except Exception as e:
            log.error("My loop error: %s", e, exc_info=True)

        for _ in range(interval):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)
    log.info("My loop stopped")
```

Then in `_run_server()`:
```python
my_task = asyncio.create_task(_my_loop(app.state.db, cfg.my_section, stop_event))
# ... and in finally block:
my_task.cancel()
```

---

## 11. COMMON DB QUERY PATTERNS

### Insert with UUID:
```python
import uuid, time, json
row_id = str(uuid.uuid4())
await self.db.execute(
    "INSERT INTO tbl (id, created_at, data_json) VALUES (?, ?, ?)",
    (row_id, time.time(), json.dumps(data)),
)
await self.db.commit()
```

### Query with dict results:
```python
async with self.db.execute("SELECT * FROM tbl WHERE id = ?", (id,)) as cursor:
    row = await cursor.fetchone()
    return dict(row) if row else None
```

### Batch query:
```python
async with self.db.execute(
    "SELECT * FROM tbl WHERE created_at > ? ORDER BY created_at DESC LIMIT ?",
    (cutoff, limit),
) as cursor:
    return [dict(r) for r in await cursor.fetchall()]
```

### Use unified CTE for analytics (includes archived data):
```python
async with self.db.execute(f"""
    WITH unified AS ({self._UNIFIED_CTE})
    SELECT ticker, COUNT(*) as cnt FROM unified
    WHERE created_at > ? GROUP BY ticker ORDER BY cnt DESC
""", (cutoff,)) as cursor:
    return [dict(r) for r in await cursor.fetchall()]
```

---

## 12. CONFIG QUICK ADD

To add a new config section:

1. Add class in `src/rot/core/config.py`:
```python
class MyConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROT_MY_", extra="ignore")
    enabled: bool = True
    interval_s: int = 300
```

2. Add field to `Settings` class:
```python
my: MyConfig = Field(default_factory=MyConfig)
```

3. Access in code: `cfg.my.enabled`, `cfg.my.interval_s`
4. Env vars: `ROT_MY_ENABLED=true`, `ROT_MY_INTERVAL_S=300`

---

## 13. ROUTE FILES -- Complete List (41 files)

```
accuracy_breakdown.py   affiliates.py         agents.py
api_status.py           auth_routes.py        backtest.py
badges.py               brokers.py            ceo_rap_sheet.py
confidence_calibration.py congress_tracker.py  correlations.py
dashboard.py            enterprise.py         export.py
faq.py                  glossary.py           hall_of_legends.py
health.py               macro.py              news_feed.py
paper_leaderboard.py    paper_trading.py      performance.py
raid_tracker.py         replay.py             sector_rotation.py
sentiment.py            seo.py                signal_quality.py
signals.py              sports_tracker.py     stripe_routes.py
terminal.py             ticker_dive.py        tradingview.py
unusual_activity.py     websocket.py          weekly_wrap.py
widgets.py              __init__.py
```
