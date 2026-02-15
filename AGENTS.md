# AGENTS.md -- Agent Speed Reference for ROT Codebase

> Read this FIRST. It will save you 10+ minutes per task.

## LOOKUP FILES (grep these, don't scan CLAUDE.md)

| Need | File | Example |
|------|------|---------|
| SQL patterns | `.claude/sql.h` | `grep "WIN_CASE" .claude/sql.h` |
| Routes | `.claude/route.tbl` | `grep "backtest" .claude/route.tbl` |
| Tier gates | `.claude/tier.map` | `grep "gate_backtest" .claude/tier.map` |
| Codebase index | `.claude/rot.idx` | `grep "^signals\|" .claude/rot.idx` |
| Test templates | `.claude/test.gen` | Copy macro, substitute params |
| Update rules | `.claude/diff.rules` | Check before committing |
| Step-by-step | `.claude/hotpath.md` | 5 common tasks as decision trees |
| Import map | `docs/agent-map.compact` | Module exports in compact format |
| Code recipes | `COOKBOOK.md` | 10 copy-paste recipes |
| Code templates | `docs/agent-patterns.toml` | TOML code gen templates |

---

## 1. SPEED INDEX

```
Test all:       python -m pytest tests/ -x --tb=short
Test one file:  python -m pytest tests/test_foo.py -v
Test one func:  python -m pytest tests/test_foo.py::test_bar -v
Server:         python -m rot.app.server
Lint:           ruff check src/ tests/
Line length:    100 chars (ruff, pyproject.toml)
Python:         >=3.10 (deployed 3.12)
Async mode:     auto (pyproject.toml: asyncio_mode = "auto") -- NO @pytest.mark.asyncio needed
DB fixture:     async def db(tmp_path) -> Database: connect/yield/close
Templates:      extend base.html, use {% block content %}...{% endblock %}
Static JS:      /static/js/ for Chart.js, HTMX, HTMX-WS (self-hosted, no CDN)
```

---

## 2. FILE OWNERSHIP -- Who Owns What

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
src/rot/web/tier_gate.py       -- 30 gate functions
src/rot/web/query_cache.py     -- dashboard query cache
src/rot/web/rate_limit.py      -- per-tier rate limiting
src/rot/web/routes/            -- 41 route files
src/rot/web/templates/         -- 39+ Jinja2 templates
src/rot/web/static/            -- self-hosted JS (Chart.js, HTMX)
```

### Storage
```
src/rot/storage/database.py    -- ALL DB operations (27+ tables, 100+ methods)
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

## 3. GOTCHAS -- Things That Bite Agents

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
    always neutral. See `_WIN_CASE_SQL` / `_LOSS_CASE_SQL` in database.py or `sql.h`.

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

## 4. BACKGROUND LOOPS IN SERVER.PY

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
| Agent evaluation | 60s | `cfg.agent.eval_interval_s` (60s) | Evaluates agent rules against signals |

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

## 5. COMMON DB QUERY PATTERNS

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

## 6. ROUTE FILES -- Complete List (41 files)

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

---

## 7. CODE QUALITY GUARDRAILS (MANDATORY)

> **ZERO TOLERANCE**: This codebase maintains a **0 open CodeQL alert** baseline.
> Every agent MUST follow these rules. Violations will be caught by CI and block merges.
> For full security policy, see `SECURITY.md`.

### Before Writing ANY Code

1. **Read before edit.** Always read the target file first. Understand existing imports, variables, and patterns.
2. **Minimal changes only.** Touch only what the task requires. Do not "clean up" surrounding code unless that IS the task.

### Import Discipline

3. **Only import what you use.** After editing a file, verify every imported name is referenced in the file body (not just type comments).
4. **Cascading check:** If you remove code that used an import, check if the import is now orphaned. Remove it.
5. **Typing imports with `from __future__ import annotations`:** CodeQL still tracks usage. Only import typing names that appear in annotations or runtime code.
6. **Circular imports:** Use `if TYPE_CHECKING:` guard. Never create runtime circular imports.

### Variable Discipline

7. **Every assignment must be read.** If you write `x = foo()` and never use `x`, either use it or write `foo()` as a bare expression.
8. **Auth guards are side-effect calls.** Write `await require_tier("pro")(request)` NOT `_user = await require_tier("pro")(request)`. The `_` prefix does NOT suppress CodeQL alerts.
9. **Cascading check:** If you remove code that read a variable, check if the assignment is now dead. Remove it.
10. **No dead initializations.** If every if/elif/else branch assigns a variable, do not initialize before the block.

### Exception Handling

11. **Never `except: pass`.** Always log (`log.error(...)`) or re-raise. Minimum: `log.debug("...", exc_info=True)`.
12. **Catch specific exceptions.** `except ValueError` not `except Exception` unless handling all exceptions is intentional and documented.

### Security (Critical)

13. **No secrets in responses.** Never expose stack traces, credentials, or internal paths to users.
14. **No secrets in logs.** `SanitizingLogFilter` is global but don't rely on it as the only defense.
15. **Password hashing:** bcrypt only. SHA-256 for high-entropy tokens only. SHA-1 only for OAuth 1.0a (must have code comment explaining why).
16. **Input validation at boundaries.** Validate user input, API responses, config values. Trust internal calls.
17. **SQL injection prevention.** Always use parameterized queries (`?` placeholders). Never f-string SQL with user data.

### Logic and Comparison

18. **No self-comparisons.** Never write `x == x` or `x != x`. Use `math.isnan()` for NaN checks.
19. **No redundant conditions.** If both branches have the same condition, consolidate.
20. **Float equality:** Use `math.isclose()` for comparisons, `math.isnan()` for NaN detection.

### Agent Pre-Commit Checklist

Before committing, mentally verify:
```
[ ] Every imported name is used in the file
[ ] Every assigned variable is read downstream
[ ] No bare except: pass blocks exist
[ ] No secrets or stack traces in user-facing output
[ ] No self-comparisons (x == x, x != x)
[ ] Tests pass: python -m pytest tests/ -x --tb=short
```

### Common Agent Mistakes (from 425 fixed alerts)

| Mistake | Frequency | Fix |
|---------|-----------|-----|
| Imported `Optional` but used `X \| None` syntax | Very common | Remove `Optional` from import |
| Copied function + imports, used subset | Very common | Remove unused imports after paste |
| `_user = await auth(...)` never read | Common | Bare `await auth(...)` |
| `except Exception: pass` | Common | `log.error(...)` or re-raise |
| Initialized var before if/else that covers all branches | Moderate | Remove initialization |
| `x != x` for NaN check | Rare | `math.isnan(x)` |
