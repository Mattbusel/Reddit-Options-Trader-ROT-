# HOT PATHS — 5 most common agent tasks as decision trees
# Follow arrows. Each step = one tool call. File:line refs are approximate.

## 1. ADD NEW PAGE (route + template + gate)
```
1. Write route file: src/rot/web/routes/{name}.py
   - router = APIRouter()
   - @router.get("/{path}")
   - async def page(request: Request): ...
   - get_current_user_optional(request) for auth
   - gate_{name}_access(user_tier) for gating
   - return templates.TemplateResponse("{name}.html", ctx)

2. Write template: src/rot/web/templates/{name}.html
   - {% extends "base.html" %}
   - {% block title %}{Title}{% endblock %}
   - {% block content %}...{% endblock %}

3. Register in app.py:
   - src/rot/web/app.py:~165 — add import + include_router
   - IMPORTANT: if path has /{param}, register AFTER static paths

4. Add tier gate (if gated):
   - src/rot/web/tier_gate.py — add gate_{name}_access()
   - Return dict of bool/int flags
   - grep tier.map for pattern

5. Add nav link:
   - src/rot/web/templates/base.html — add to nav menu

6. Write test:
   - tests/test_{name}.py — use M:ROUTE_AUTH from test.gen

7. Update docs:
   - .claude/route.tbl — add endpoint line
   - .claude/tier.map — add gate line (if gated)
   - .claude/rot.idx — add to TESTS section
   - CLAUDE.md#6 — add to route inventory
   - CLAUDE.md#8 — add gate (if gated)
```

## 2. ADD DB TABLE
```
1. Add CREATE TABLE in database.py:
   - src/rot/storage/database.py:connect() — add to _SCHEMA
   - Pattern: CREATE TABLE IF NOT EXISTS {name} (...)
   - Add indexes after CREATE

2. Add CRUD methods in database.py:
   - async def save_{name}(self, ...) -> None
   - async def get_{name}(self, id) -> Optional[dict]
   - async def get_{name}s(self, **filters) -> List[dict]
   - Use dict(row) pattern for results

3. Add migration (if modifying existing table):
   - database.py:connect() — add ALTER TABLE in try/except
   - MUST be idempotent (IF NOT EXISTS, try/except)

4. Write test:
   - tests/test_{name}_db.py — use M:DB_CRUD from test.gen
   - ALWAYS use tmp_path fixture for test DB

5. Update docs:
   - .claude/rot.idx#TABLES — add table schema
   - .claude/sql.h — add indexes
   - CLAUDE.md#5 — add to schema section
```

## 3. ADD TIER GATE
```
1. Add gate function in tier_gate.py:
   - src/rot/web/tier_gate.py
   - def gate_{name}_access(tier: str) -> dict:
   - Pattern: TIER_ORDER[tier] >= TIER_ORDER["pro"]
   - Return dict with has_access + granular flags

2. Use in route:
   - access = gate_{name}_access(user.get("tier","free"))
   - Pass to template: {"access": access}

3. Use in template:
   - {% if access.has_access %} content {% else %} upgrade CTA {% endif %}
   - Upgrade CTA: <a href="/pricing">Upgrade to {tier}+</a>

4. Write test:
   - Use M:GATE_TIER from test.gen
   - Test ALL 5 tiers: free/pro/premium/ultra/enterprise
   - Verify hierarchy: each tier >= previous tier's access

5. Update docs:
   - .claude/tier.map — add line
   - CLAUDE.md#8 — add to gate list
```

## 4. ADD BACKGROUND LOOP
```
1. Write async function in server.py:
   - src/rot/app/server.py
   - Pattern:
     async def _loop_{name}(app, stop_event):
         await asyncio.sleep(10)  # initial delay
         while not stop_event.is_set():
             try:
                 # work here
             except Exception as e:
                 log.error("{name} error: %s", e)
             await asyncio.sleep(interval)

2. Register in _run_server():
   - tasks.append(asyncio.create_task(_loop_{name}(app, stop)))
   - Add to finally: task.cancel()

3. Add config (if interval is configurable):
   - src/rot/core/config.py — add field to relevant Config class
   - Update .claude/rot.idx#CONFIG

4. Write test:
   - Test the work function in isolation, not the loop itself
   - Mock DB, verify expected calls

5. Update docs:
   - AGENTS.md#10 — add to background loops table
   - CLAUDE.md#3 — mention in module reference
```

## 5. DEBUG FAILING TEST
```
1. Read error message:
   - grep test name in output
   - Identify: ImportError? AssertionError? AttributeError?

2. ImportError:
   - Check src/rot/{module}/__init__.py for missing re-export
   - Check circular imports (move import inside function)
   - Check if new dep missing from pyproject.toml

3. AssertionError:
   - Read test to understand expected behavior
   - Read source code being tested
   - Common: SQL changed but test uses old schema → update test

4. AttributeError on frozen dataclass:
   - Can't mutate frozen dataclass → use dataclasses.replace()
   - Can't add field → update dataclass + all constructors

5. "table has no column named X":
   - Migration not idempotent → wrap in try/except
   - Test DB doesn't have migration → call db.connect() in fixture

6. Test passes locally but fails in CI:
   - Async issue → ensure asyncio_mode = "auto"
   - File path issue → use tmp_path, not hardcoded paths
   - Import order → check conftest.py fixtures
```
