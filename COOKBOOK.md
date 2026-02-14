# COOKBOOK.md — ROT Agent Recipe Book

Copy-paste patterns for common codebase tasks. All paths are relative to project root.

---

## Recipe 1: Add a New Dashboard Page

Add a tier-gated HTML page with route, template, gate, nav link, and test.

**Files touched:**
- `src/rot/web/routes/my_page.py` (new)
- `src/rot/web/templates/my_page.html` (new)
- `src/rot/web/tier_gate.py` (edit)
- `src/rot/web/app.py` (edit)
- `src/rot/web/templates/base.html` (edit)
- `tests/test_my_page.py` (new)

### Route: `src/rot/web/routes/my_page.py`

```python
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from rot.web.auth import get_current_user_optional
from rot.web.tier_gate import gate_my_page_access

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/my-page", response_class=HTMLResponse)
async def my_page(request: Request):
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    access = gate_my_page_access(tier)

    db = request.app.state.db
    # Query your data here
    items = []

    # Build context — always include request, user, tier
    ctx = {
        "request": request,
        "user": user,
        "tier": tier,
        "access": access,
        "items": items,
    }
    templates = request.app.state.templates
    return templates.TemplateResponse("my_page.html", ctx)
```

### Template: `src/rot/web/templates/my_page.html`

```html
{% extends "base.html" %}
{% block title %}My Page - ROT{% endblock %}
{% block content %}
<div class="max-w-7xl mx-auto px-4 py-8">
    <h1 class="text-2xl font-bold text-white mb-6">My Page</h1>

    {% if not access.has_access %}
    <div class="bg-gray-800 rounded-lg p-8 text-center">
        <p class="text-gray-400">Upgrade to Pro to access this feature.</p>
        <a href="/pricing" class="mt-4 inline-block px-6 py-2 bg-blue-600 text-white rounded hover:bg-blue-500">Upgrade</a>
    </div>
    {% else %}
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        {% for item in items %}
        <div class="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <p class="text-white">{{ item }}</p>
        </div>
        {% endfor %}
    </div>
    {% endif %}
</div>
{% endblock %}
```

### Gate: add to `src/rot/web/tier_gate.py`

```python
def gate_my_page_access(tier: str) -> dict:
    """Return my page feature access flags based on tier."""
    return {
        "has_access": tier in _PAID_TIERS,  # Pro+
        "has_detail": tier in ("premium", "ultra", "enterprise"),
        "has_export": tier in ("ultra", "enterprise"),
        "max_items": 10 if tier == "pro" else 50 if tier == "premium" else 200,
    }
```

### Register route in `src/rot/web/app.py`

```python
# In the imports section at the bottom of create_app():
from rot.web.routes import my_page
app.include_router(my_page.router, tags=["my-page"])
```

### Nav link in `src/rot/web/templates/base.html`

```html
<!-- Add inside the appropriate dropdown menu section -->
<a href="/my-page" class="block px-4 py-2 text-sm text-gray-400 hover:text-white hover:bg-gray-800 transition">My Page {% if user.tier not in ('pro', 'premium', 'ultra', 'enterprise') %}<span class="text-xs text-blue-400">Pro</span>{% endif %}</a>
```

---

## Recipe 2: Add a New API Endpoint

JSON endpoint with auth, rate limiting, tier check.

**Files touched:**
- `src/rot/web/routes/signals.py` (or new route file)

```python
from rot.web.auth import get_current_user_optional, require_user
from rot.web.rate_limit import check_rate_limit, require_api_auth, rate_limit_headers
from rot.web.tier_gate import gate_my_page_access


@router.get("/my-data")
async def get_my_data(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    ticker: Optional[str] = None,
):
    # 1. Auth (required for API)
    user = await get_current_user_optional(request)
    await require_api_auth(request, user)

    # 2. Rate limit check
    tier = user.get("tier", "free")
    await check_rate_limit(request, user)

    # 3. Tier gate
    access = gate_my_page_access(tier)
    if not access["has_access"]:
        raise HTTPException(403, "Upgrade to Pro for API access")

    # 4. Query
    db = request.app.state.db
    results = await db.get_my_data(limit=limit, ticker=ticker)

    # 5. Return with rate limit headers
    headers = rate_limit_headers(user)
    return JSONResponse(
        content={"data": results, "count": len(results)},
        headers=headers,
    )
```

---

## Recipe 3: Add a New Background Loop

Background async task in `src/rot/app/server.py`.

**Files touched:**
- `src/rot/app/server.py`

### Define the loop function (add before `_run_server`)

```python
async def _my_feature_loop(
    db,
    cfg,  # your config section
    stop_event: threading.Event,
):
    """Background task that does X every N seconds."""
    interval = cfg.my_interval_s
    log.info("My feature loop starting (interval=%ds)", interval)

    # Startup delay — let DB and pipeline initialize first
    for _ in range(60):
        if stop_event.is_set():
            return
        await asyncio.sleep(1)

    while not stop_event.is_set():
        try:
            # Your logic here
            result = await db.do_something()
            if result:
                log.info("My feature: processed %d items", result)
        except Exception as e:
            log.error("My feature error: %s", e, exc_info=True)

        # Interruptible sleep (checks stop_event every second)
        for _ in range(interval):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)
    log.info("My feature loop stopped")
```

### Start the task in `_run_server` (add after existing task starts)

```python
    my_feature_task = asyncio.create_task(
        _my_feature_loop(
            db=app.state.db,
            cfg=cfg.my_feature,
            stop_event=stop_event,
        )
    )
    log.info("My feature loop: ACTIVE (interval=%ds)", cfg.my_feature.my_interval_s)
```

### Cancel in the `finally` block

```python
    finally:
        # ... existing cancels ...
        my_feature_task.cancel()
```

---

## Recipe 4: Add a New Database Table

Schema DDL, indexes, CRUD methods, migration.

**Files touched:**
- `src/rot/storage/database.py`

### Add DDL to `_SCHEMA` string

```sql
CREATE TABLE IF NOT EXISTS my_items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    ticker TEXT NOT NULL DEFAULT '',
    value REAL NOT NULL DEFAULT 0.0,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_my_items_user ON my_items(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_my_items_ticker ON my_items(ticker);
```

### Add migration entry to `_MIGRATIONS` list (for new columns on existing tables)

```python
_MIGRATIONS = [
    # ... existing entries ...
    ("signals", "my_new_column", "TEXT NOT NULL DEFAULT ''"),
]
```

### Add CRUD methods to `Database` class

```python
    async def insert_my_item(self, user_id: str, ticker: str, value: float,
                              details: dict | None = None) -> str:
        item_id = str(uuid.uuid4())
        await self.db.execute(
            """INSERT INTO my_items (id, user_id, ticker, value, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (item_id, user_id, ticker, value, json.dumps(details or {}), time.time()),
        )
        await self.db.commit()
        return item_id

    async def get_my_items(self, user_id: str, limit: int = 50) -> list[dict]:
        async with self.db.execute(
            """SELECT * FROM my_items WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]

    async def get_my_item(self, item_id: str) -> dict | None:
        async with self.db.execute(
            "SELECT * FROM my_items WHERE id = ?", (item_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_my_item(self, item_id: str, value: float) -> bool:
        cursor = await self.db.execute(
            "UPDATE my_items SET value = ? WHERE id = ?",
            (value, item_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def delete_my_item(self, item_id: str) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM my_items WHERE id = ?", (item_id,),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def purge_old_my_items(self, keep_days: int = 90) -> int:
        cutoff = time.time() - keep_days * 86400
        cursor = await self.db.execute(
            "DELETE FROM my_items WHERE created_at < ?", (cutoff,),
        )
        await self.db.commit()
        return cursor.rowcount
```

---

## Recipe 5: Add HTMX Partial

Route returning HTML fragment, loaded into parent page via HTMX.

**Files touched:**
- `src/rot/web/routes/my_page.py` (edit)
- `src/rot/web/templates/my_page_partial.html` (new)
- `src/rot/web/templates/my_page.html` (edit)

### HTMX partial route

```python
@router.get("/my-page/detail/{item_id}", response_class=HTMLResponse)
async def my_page_detail(request: Request, item_id: str):
    user = await get_current_user_optional(request)
    tier = (user or {}).get("tier", "free")
    db = request.app.state.db
    item = await db.get_my_item(item_id)
    if not item:
        return HTMLResponse("<p class='text-red-400'>Not found</p>", status_code=404)
    ctx = {"request": request, "item": item, "tier": tier}
    templates = request.app.state.templates
    return templates.TemplateResponse("my_page_partial.html", ctx)
```

### Partial template: `src/rot/web/templates/my_page_partial.html`

```html
<!-- No {% extends %} — this is a fragment -->
<div class="bg-gray-800 rounded-lg p-4 border border-gray-700">
    <h3 class="text-lg font-semibold text-white">{{ item.ticker }}</h3>
    <p class="text-gray-400 mt-2">Value: {{ item.value }}</p>
</div>
```

### Trigger from parent template

```html
<!-- In my_page.html: button that loads partial into #detail-container -->
<button hx-get="/my-page/detail/{{ item.id }}"
        hx-target="#detail-container"
        hx-swap="innerHTML"
        class="px-3 py-1 bg-blue-600 text-white rounded text-sm hover:bg-blue-500">
    View Detail
</button>

<div id="detail-container" class="mt-4"></div>
```

---

## Recipe 6: Add a New Config Section

Pydantic Settings class with env vars.

**Files touched:**
- `src/rot/core/config.py`

### Define config class (add before `Settings`)

```python
class MyFeatureConfig(BaseSettings):
    """Config for my new feature."""

    model_config = SettingsConfigDict(env_prefix="ROT_MY_FEATURE_")

    enabled: bool = False
    my_interval_s: int = 300        # env: ROT_MY_FEATURE_MY_INTERVAL_S
    my_threshold: float = 0.5       # env: ROT_MY_FEATURE_MY_THRESHOLD
    max_items: int = 100            # env: ROT_MY_FEATURE_MAX_ITEMS
```

### Add to `Settings` class

```python
class Settings(BaseSettings):
    # ... existing fields ...
    my_feature: MyFeatureConfig = Field(default_factory=MyFeatureConfig)
```

### Access in code

```python
cfg = Settings()
if cfg.my_feature.enabled:
    do_thing(threshold=cfg.my_feature.my_threshold)
```

---

## Recipe 7: Add WebSocket Integration

Broadcast custom events via existing WebSocket infrastructure.

**Files touched:**
- `src/rot/web/routes/websocket.py` (existing — use `broadcast_signal`)
- Your code that generates events

### Broadcast from async context (e.g., route handler)

```python
from rot.web.routes.websocket import broadcast_signal

# In an async function:
await broadcast_signal({
    "type": "my_event",
    "ticker": "TSLA",
    "data": {"score": 85.0, "message": "IV spike detected"},
})
```

### Broadcast from sync context (e.g., pipeline thread)

```python
# In server.py on_signal callback or similar sync code:
import asyncio

def on_my_event(event_data: dict):
    asyncio.run_coroutine_threadsafe(
        broadcast_signal(event_data),
        loop,  # the running event loop captured in _run_server
    )
```

### Client-side listener (in template)

```html
<div hx-ext="ws" ws-connect="/api/v1/signals/live?token={{ jwt_token }}">
    <div id="live-feed" ws-swap="afterbegin"></div>
</div>
```

---

## Recipe 8: Add a Tier Gate Function

Full 5-tier gate with route import and template usage.

**Files touched:**
- `src/rot/web/tier_gate.py`
- Route file (import)
- Template file (use)

### Gate function in `tier_gate.py`

```python
def gate_my_feature_access(tier: str) -> dict:
    """Return my feature access flags based on tier."""
    return {
        "has_access": tier in _PAID_TIERS,                          # Pro+
        "has_advanced": tier in ("premium", "ultra", "enterprise"), # Premium+
        "has_export": tier in ("ultra", "enterprise"),              # Ultra+
        "has_api": tier == "enterprise",                            # Enterprise only
        "max_items": (
            0 if tier == "free"
            else 25 if tier == "pro"
            else 100 if tier == "premium"
            else 500                                                # ultra/enterprise
        ),
        "max_days": (
            0 if tier == "free"
            else 7 if tier == "pro"
            else 30 if tier == "premium"
            else 365                                                # ultra/enterprise
        ),
    }
```

### Import in route

```python
from rot.web.tier_gate import gate_my_feature_access

access = gate_my_feature_access(tier)
```

### Use in template

```html
{% if access.has_access %}
    <div>Feature content here</div>
    {% if access.has_advanced %}
        <div>Premium-only section</div>
    {% endif %}
    {% if not access.has_export %}
        <p class="text-xs text-gray-500">Upgrade to Ultra for export</p>
    {% endif %}
{% else %}
    <div class="text-center p-8">
        <p class="text-gray-400 mb-4">This feature requires a Pro subscription.</p>
        <a href="/pricing" class="px-4 py-2 bg-blue-600 text-white rounded">Upgrade</a>
    </div>
{% endif %}
```

---

## Recipe 9: Write Tests for DB Operations

Async pytest pattern with temp DB fixture.

**Files touched:**
- `tests/test_my_feature_db.py` (new)

```python
from __future__ import annotations

import time
import pytest
from rot.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_insert_my_item(db):
    item_id = await db.insert_my_item(
        user_id="user1", ticker="TSLA", value=42.0,
        details={"note": "test"},
    )
    assert item_id
    item = await db.get_my_item(item_id)
    assert item is not None
    assert item["ticker"] == "TSLA"
    assert item["value"] == 42.0


@pytest.mark.asyncio
async def test_list_my_items(db):
    for i in range(5):
        await db.insert_my_item(
            user_id="user1", ticker="TSLA", value=float(i),
        )
    items = await db.get_my_items("user1", limit=3)
    assert len(items) == 3
    # Most recent first (ORDER BY created_at DESC)
    assert items[0]["value"] >= items[-1]["value"]


@pytest.mark.asyncio
async def test_update_my_item(db):
    item_id = await db.insert_my_item("user1", "AAPL", 10.0)
    updated = await db.update_my_item(item_id, 99.0)
    assert updated is True
    item = await db.get_my_item(item_id)
    assert item["value"] == 99.0


@pytest.mark.asyncio
async def test_delete_my_item(db):
    item_id = await db.insert_my_item("user1", "SPY", 5.0)
    deleted = await db.delete_my_item(item_id)
    assert deleted is True
    assert await db.get_my_item(item_id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false(db):
    assert await db.delete_my_item("nonexistent-id") is False


@pytest.mark.asyncio
async def test_purge_old_items(db):
    # Insert item with old timestamp (patch time.time in insert or insert raw)
    await db.db.execute(
        """INSERT INTO my_items (id, user_id, ticker, value, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("old1", "user1", "TSLA", 1.0, "{}", time.time() - 200 * 86400),
    )
    await db.db.execute(
        """INSERT INTO my_items (id, user_id, ticker, value, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("new1", "user1", "TSLA", 2.0, "{}", time.time()),
    )
    await db.db.commit()

    purged = await db.purge_old_my_items(keep_days=90)
    assert purged == 1
    assert await db.get_my_item("old1") is None
    assert await db.get_my_item("new1") is not None
```

### pyproject.toml config (already set, for reference)

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## Recipe 10: Add Signal Callback Hook

Hook into `_async_signal_handler` for real-time processing when a new signal arrives.

**Files touched:**
- `src/rot/app/server.py`

### Option A: Add logic inside `_async_signal_handler`

```python
async def _async_signal_handler(
    signal_data: Dict[str, Any],
    app,
    dispatcher: AlertDispatcher | None,
    price_checker: PriceChecker | None = None,
):
    # ... existing store, price check, broadcast, cache invalidation ...

    # YOUR HOOK: process signal after storage
    try:
        my_engine = getattr(app.state, "my_engine", None)
        if my_engine and signal_id:
            result = await my_engine.process(signal_data, signal_id)
            if result:
                log.info("My engine: processed signal %s -> %s", signal_id, result)
    except Exception as e:
        log.error("My engine error: %s", e)

    # ... existing alert dispatch ...
```

### Option B: Initialize your engine in `_run_server`

```python
    # In _run_server, before the pipeline starts:
    from rot.my_module.engine import MyEngine
    my_engine = MyEngine(db=app.state.db)
    app.state.my_engine = my_engine
    log.info("My engine: ACTIVE")
```

### Option C: Register a standalone callback (when you need multiple hooks)

```python
# In server.py, modify the on_signal closure in _run_server:
def on_signal(signal_data: Dict[str, Any]):
    try:
        asyncio.run_coroutine_threadsafe(
            _async_signal_handler(signal_data, app, dispatcher, price_checker),
            loop,
        )
    except Exception as e:
        log.error("Signal handler error: %s", e)
```

The `_async_signal_handler` is the single entry point. It runs on the main event loop
via `run_coroutine_threadsafe` because the pipeline runs in a background thread.
All hooks must be async-safe. Add your logic after `signal_id` is confirmed non-None
(i.e., the signal was stored, not a duplicate).
