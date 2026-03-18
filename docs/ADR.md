# Architecture Decision Records (ADR)

ROT uses Architecture Decision Records to document significant technical choices, their context, and the trade-offs considered. Each record is immutable after acceptance; superseded decisions reference their successors.

---

## ADR-001: FastAPI over Flask and Django

**Status:** Accepted
**Date:** 2025-01
**Deciders:** Initial architecture

### Context

ROT needs a Python web framework to serve 100+ API endpoints, a real-time WebSocket signal feed, server-rendered Jinja2 dashboard templates, and background async pipeline loops — all in a single process. The framework must handle async I/O natively because the pipeline, database access (aiosqlite), LLM API calls, and market data fetches are all async.

### Decision

Use **FastAPI** as the web framework.

### Rationale

- **Native async**: FastAPI is built on Starlette and supports `async def` route handlers without any compatibility shims. Flask's async support (via `asgiref`) is a bolt-on and Django's async story is incomplete for ORM usage.
- **Automatic OpenAPI generation**: FastAPI generates `/docs` (Swagger UI) and `/redoc` from Pydantic models with zero boilerplate. ROT exposes 100+ endpoints; maintaining hand-written OpenAPI specs would be a significant maintenance burden.
- **Pydantic integration**: ROT uses Pydantic v2 throughout (`core/types.py`, `core/config.py`, `web/api_models.py`). FastAPI's native Pydantic integration means request validation, response serialization, and settings management all share a single type system.
- **WebSocket support**: FastAPI (via Starlette) has first-class WebSocket support needed for the live signal feed (`/api/v1/signals/live`). Flask-SocketIO is a separate library with its own event loop; Django Channels requires separate ASGI configuration.
- **Performance**: FastAPI benchmarks consistently faster than Flask for async workloads and comparable to Django REST Framework for JSON throughput, which matters at 100K+ API calls/day for Enterprise tier users.

### Trade-offs

- **Less opinionated**: Flask and Django provide more batteries (admin panel, ORM, migrations). ROT uses aiosqlite with hand-written migrations instead of an ORM, which was a deliberate choice for performance and simplicity with SQLite.
- **Smaller ecosystem**: Some Flask/Django extensions have no FastAPI equivalent. This has not been a problem in practice — ROT's dependencies are all framework-agnostic.

### Consequences

FastAPI is used for all HTTP routing, middleware, and dependency injection. The Starlette `Request` object is passed explicitly to route handlers that need authentication context. Background tasks use FastAPI's `BackgroundTasks` or standalone `asyncio.Task` instances managed by the pipeline runner.

---

## ADR-002: GradientBoosting for Credibility Scoring over Neural Networks

**Status:** Accepted
**Date:** 2025-02
**Deciders:** Initial ML design

### Context

ROT needs a model to score the credibility of Reddit posts as financial signals. The feature set is tabular (32 engineered features including engagement metrics, text depth, author history, subreddit weight, ticker focus ratio). The model must be retrained periodically from the live database, make fast inference decisions per-signal, and provide interpretable outputs that can be logged and audited.

### Decision

Use **scikit-learn GradientBoostingClassifier** (32 input features) as the ML credibility scorer.

### Rationale

- **Tabular data advantage**: GradientBoosting (and tree ensembles generally) outperform neural networks on tabular data with engineered features, particularly when the feature space is small (32 features) and the dataset is moderate-sized (hundreds to thousands of examples). Neural networks require significantly more data and careful regularization to match gradient boosting on this problem class.
- **No GPU required**: Inference and retraining run on CPU. ROT deploys on Railway with standard instances; requiring a GPU for the credibility model would increase hosting cost by 10–20x.
- **Fast retraining**: The model retrains every 24 hours from the live signal database. GradientBoosting on a few thousand examples completes in seconds. A neural network would require more infrastructure (training loop, early stopping, checkpointing).
- **Interpretability**: scikit-learn GradientBoosting exposes `feature_importances_` which are logged alongside each signal. This supports auditing ("why was this signal scored 0.81?") and debugging poor signal quality.
- **Graceful fallback**: When insufficient training data exists (fewer than 100 resolved signals per `ROT_ML_MIN_TRAINING_SAMPLES`), the heuristic scorer takes over transparently. A neural network-based design would have a harder transition because it requires more samples before converging to a useful decision boundary.

### Trade-offs

- **Not a deep semantic model**: GradientBoosting operates on engineered features, not raw text. It cannot learn novel linguistic patterns the way a fine-tuned language model could. The LLM Reasoner layer partially compensates by handling semantic analysis.
- **Feature engineering dependency**: Adding new signal attributes requires updating the feature extractor (`credibility/features.py`) and retraining. A neural network with embedding layers could handle raw text end-to-end.

### Consequences

The credibility module is split into `scorer.py` (heuristic, always available), `ml_scorer.py` (GradientBoosting, requires trained model file), and `features.py` (feature extraction shared by both). The ML model path is auto-derived from `ROT_STORAGE_ROOT` and is created on first successful training. Both scores are always stored in signal metadata.

---

## ADR-003: Circuit Breaker Pattern for LLM Reasoning

**Status:** Accepted
**Date:** 2025-02
**Deciders:** Reliability design

### Context

LLM API calls (OpenAI, Anthropic, DeepSeek) are external network dependencies with rate limits, occasional outages, and variable latency. The ROT pipeline processes hundreds of signals per day. If the LLM API is down, the entire pipeline should not stall — signal ingestion, scoring, trade idea generation, and dashboard delivery must continue uninterrupted.

### Decision

Implement a **circuit breaker** around the LLM reasoning step. After 3 consecutive failures, the breaker opens and all subsequent signals use a deterministic stub reasoner. The breaker attempts to close (resume LLM calls) after a configurable recovery window.

### Rationale

- **Pipeline availability over LLM completeness**: ROT's primary value is signal detection and trade idea generation. LLM reasoning adds qualitative thesis and risk context, but signals remain actionable without it. Failing open (skipping LLM rather than blocking) is the correct trade-off.
- **Exponential blast radius prevention**: Without a circuit breaker, a slow LLM API would cause every signal to time out, accumulating backpressure in the async queue and potentially stalling the entire pipeline runner loop.
- **Rate limit protection**: Opening the circuit breaker on rate limit errors (HTTP 429) prevents the system from hammering the API during quota exhaustion, which would extend the blackout window.
- **Observable failure mode**: The circuit breaker state is logged as a SIEM event. Operators can see exactly when LLM reasoning was disabled, for how long, and what triggered the open transition.
- **Stub reasoner**: The fallback stub produces a structured `ReasoningPacket` using deterministic heuristics (stance, event_type, credibility score), so downstream components (trade builder, storage, alerts) receive consistently shaped data regardless of LLM availability.

### Trade-offs

- **Reduced signal quality during outages**: Signals generated while the circuit is open lack LLM-synthesized thesis and risk analysis. This is visible in the dashboard (signals show "Automated analysis" instead of an LLM-written thesis).
- **Manual recovery awareness**: The breaker auto-recovers after the recovery window, but operators are not automatically notified when LLM reasoning resumes. Monitoring the security log provides this information.

### Consequences

`reasoner/reasoner.py` maintains a failure counter and open/closed state. All LLM calls are routed through this single interface. The `llm_client.py` module handles provider-specific API calls and raises a common `LLMError` that the circuit breaker catches. The stub reasoner in `reasoner/parser.py` is used as the fallback return value.

---

## ADR-004: nh3 (Rust-based Sanitizer) for HTML Sanitization

**Status:** Accepted
**Date:** 2026-02-15
**Deciders:** Security hardening sprint

### Context

ROT renders user-influenced content in Jinja2 templates (post titles, signal reasoning text, user-provided watchlist names). Some template locations use `|safe` to bypass Jinja2's default escaping in order to render pre-formatted HTML from trusted internal sources. Any content that could be influenced by external data flowing through these paths needs an additional sanitization layer to prevent stored XSS if the upstream escaping is ever bypassed.

The existing Python HTML sanitization libraries at the time of evaluation were `bleach` (based on `html5lib`) and `markupsafe`. `bleach` was officially deprecated in 2023 and its upstream `html5lib` has a history of parser-differential vulnerabilities.

### Decision

Use **nh3** (`nh3>=0.2.14`) as the HTML sanitization library, exposed via `src/rot/core/sanitize.py`.

### Rationale

- **Rust-based implementation**: nh3 wraps the `ammonia` Rust library, which uses `html5ever` (the same HTML parser powering Firefox) for parsing. Rust's memory safety properties eliminate an entire class of vulnerabilities (buffer overflows, use-after-free) that have historically affected C-based sanitizers.
- **Active maintenance**: `bleach` was deprecated in 2023. nh3 is actively maintained with regular releases and a clean CVE history.
- **Performance**: Rust FFI overhead is negligible compared to Python's native HTML parsing. For ROT's use case (sanitizing signal reasoning text and post titles), throughput is not a concern, but the Rust implementation being faster means no regression.
- **Defense-in-depth positioning**: nh3 is not the primary XSS defense — Jinja2 autoescape is. nh3 is the second line of defense for `|safe` content only. This means it does not need to handle all edge cases; it only needs to be more reliable than doing nothing.
- **Consistent API**: `sanitize.py` exposes three functions — `sanitize_html(text)` (nh3 clean), `strip_html(text)` (removes all tags), `sanitize_for_json(text)` (strip + normalize whitespace) — providing a stable interface that could swap the underlying library without changing callers.

### Trade-offs

- **Binary wheel dependency**: nh3 ships pre-built wheels for common platforms. On uncommon architectures, it requires a Rust toolchain to build from source. ROT's Docker image uses `python:3.12-slim` which matches available wheels.
- **Allowlist-by-default**: nh3/ammonia strips all tags not explicitly allowed. The default allowlist is conservative. If ROT ever needs to render rich HTML (tables, images) from internal trusted content, the allowlist must be explicitly extended in `sanitize.py`.

### Consequences

`nh3` is in `pyproject.toml` as a defense-in-depth dependency with a minimum version pin (`nh3>=0.2.14`). `sanitize.py` is imported in all template rendering paths that use `|safe`. Security audits treat this as one of three XSS defenses (Jinja2 autoescape, nh3 sanitization, CSP header).

---

## ADR-005: SQLite over PostgreSQL for the Persistence Tier

**Status:** Accepted
**Date:** 2025-01
**Deciders:** Initial architecture

### Context

ROT needs a persistent relational database for 33+ tables covering signals, user accounts, paper trades, backtests, and analytics. The initial deployment target is Railway (a PaaS platform). The access pattern is a single-writer, multiple-reader async application (aiosqlite). Read queries are dashboard analytics and API responses; writes are continuous signal ingestion (1 write per ~20-second pipeline cycle).

### Decision

Use **SQLite** with WAL mode, accessed via **aiosqlite**, with persistent storage at `/app/data/rot.db` (Railway volume).

### Rationale

- **Zero operational overhead**: SQLite requires no separate server process, no connection pooling configuration, no network firewall rules, and no separate managed database billing. For a solo-operated platform on Railway, eliminating this operational surface is a significant advantage.
- **WAL mode for concurrency**: SQLite in WAL (Write-Ahead Log) mode supports concurrent readers with a single writer without reader blocking. ROT's access pattern — one pipeline writer and multiple simultaneous dashboard readers — is exactly what WAL mode is optimized for.
- **Sufficient throughput**: ROT writes one signal per ~20-second pipeline cycle and handles dashboard reads from a query cache (30–300 second TTL). Peak write throughput is well within SQLite's documented limits (many thousands of writes/second on SSD). The query cache means most dashboard requests never hit the database.
- **Simplified deployment**: The SQLite file lives on the Railway persistent volume (`/app/data/rot.db`). Backup is as simple as copying the file. Migration is a file copy. No `DATABASE_URL` connection strings, SSL certificates, or managed database provisioning.
- **aiosqlite for async**: The `aiosqlite` library wraps SQLite in an async interface, allowing non-blocking database access from FastAPI async route handlers and the async pipeline runner without threads blocking the event loop.

### Trade-offs

- **Single-instance constraint**: SQLite cannot be shared across multiple application instances. ROT is designed as a single-instance deployment. If horizontal scaling were required, migration to PostgreSQL would be necessary. This is acknowledged and documented.
- **No native JSON operators**: SQLite supports JSON storage but the JSON query functions (`json_extract`) are less ergonomic than PostgreSQL's `jsonb` operators. ROT stores complex nested data as JSON text blobs and retrieves full blobs, deserializing in Python — a pragmatic trade-off for simplicity.
- **Backup complexity**: Unlike PostgreSQL, SQLite has no built-in point-in-time recovery. ROT implements a `BackupManager` (`storage/backup.py`) that creates GZip-compressed copies on a schedule with rotation, accessible via the `/health` endpoint (admin only).
- **No connection pooling**: aiosqlite serializes writes through a single thread. This is not a bottleneck at current scale but would limit write-heavy workloads.

### Consequences

All database access goes through `src/rot/storage/database.py`, which owns the connection lifecycle, WAL mode pragma setup, and all 33+ table schemas. Migrations are applied idempotently in `Database.connect()` using `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ADD COLUMN` with exception swallowing (SQLite's limitation on conditional column adds). The `_UNIFIED_CTE` pattern merges live and archived signals for analytics without requiring a separate analytics database.

---

*Additional ADRs will be added as new significant technical decisions are made. See `docs/architecture.md` for the complete system architecture.*
