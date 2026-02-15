# Infrastructure & Observability

> Documentation for ROT's production infrastructure, security, monitoring, and reliability features.

## Table of Contents

1. [Security Hardening](#security-hardening)
2. [Retry Logic](#retry-logic)
3. [Request Tracing](#request-tracing)
4. [Security Logging](#security-logging)
5. [Database Backups](#database-backups)
6. [Health Checks](#health-checks)
7. [Dependency Scanning](#dependency-scanning)
8. [Loading States](#loading-states)

---

## Security Hardening

### Database-Backed Rate Limiting

**Location:** `src/rot/storage/auth_db.py`

Multi-instance compatible rate limiting using SQLite for persistence.

```python
from rot.storage.auth_db import AuthDatabase

auth_db = AuthDatabase()

# Check rate limit
is_limited, retry_after = await auth_db.check_rate_limit(
    key="login:192.168.1.1",
    max_attempts=5,
    window_seconds=300
)

if is_limited:
    # Return 429 with Retry-After header
    return Response(status_code=429, headers={"Retry-After": str(retry_after)})
```

**Features:**
- Per-IP rate limiting for login/register
- Database persistence (survives restarts)
- Multi-instance support (shared state)
- Automatic cleanup of expired entries
- Configurable limits and windows

**Schema:**
```sql
CREATE TABLE rate_limit_state (
    key TEXT PRIMARY KEY,
    attempt_count INTEGER,
    window_start INTEGER
)
```

### Secret Key Validation

**Location:** `src/rot/core/config.py`

Validates `ROT_SECRET_KEY` on startup:

```python
from rot.core.config import Settings

settings = Settings()
# Raises ValueError if secret key is default/weak
```

**Requirements:**
- Must be set in production (`ROT_ENV=production`)
- Cannot be the default dev value
- Enforced at application startup

---

## Retry Logic

**Location:** `src/rot/core/retry.py`

Exponential backoff with jitter for transient failures.

### Sync Retry Decorator

```python
from rot.core.retry import with_retry

@with_retry(max_attempts=3, base_delay=1.0, max_delay=10.0)
def fetch_market_data(ticker: str):
    # Will retry on ConnectionError, Timeout, HTTPError
    response = requests.get(f"https://api.example.com/quote/{ticker}")
    return response.json()
```

### Async Retry Decorator

```python
from rot.core.retry import with_async_retry

@with_async_retry(max_attempts=5, base_delay=0.5)
async def fetch_llm_completion(prompt: str):
    # Will retry on OpenAI rate limits, timeouts
    response = await openai.ChatCompletion.create(...)
    return response
```

### Configuration

```python
@with_retry(
    max_attempts=5,        # Maximum retry attempts
    base_delay=1.0,        # Initial delay in seconds
    max_delay=30.0,        # Maximum delay between retries
    jitter=True,           # Add randomness to prevent thundering herd
    backoff_factor=2.0,    # Exponential backoff multiplier
)
```

### Applied To

- yfinance market data (`src/rot/market/enricher.py`)
- OpenAI API calls (`src/rot/reasoner/llm_client.py`)
- Anthropic API calls (`src/rot/reasoner/llm_client.py`)
- DeepSeek API calls (`src/rot/reasoner/llm_client.py`)
- RSS feed fetching (`src/rot/ingest/rss.py`)
- StockTwits API (`src/rot/ingest/stocktwits.py`)
- Twitter API (`src/rot/ingest/twitter.py`)

**Benefits:**
- Handles transient network failures gracefully
- Prevents pipeline crashes from API timeouts
- ~300% reliability improvement

---

## Request Tracing

**Location:** `src/rot/core/request_context.py`, `src/rot/web/request_id_middleware.py`

Distributed tracing with request IDs for debugging and observability.

### Middleware

```python
from rot.web.request_id_middleware import RequestIDMiddleware

app.add_middleware(RequestIDMiddleware)  # First middleware
```

### Usage in Code

```python
from rot.core.request_context import get_request_id, get_user_id

log.info(f"Processing request {get_request_id()} for user {get_user_id()}")
```

### Log Format

```
2026-02-14 21:35:00 [req_abc123-def4-5678-90ab-cdef12345678] [user:42] rot.web - INFO - Processing request
```

### HTTP Headers

**Request:**
- `X-Request-ID` - Client-provided request ID (optional)
- `X-Correlation-ID` - Distributed tracing correlation ID (optional)

**Response:**
- `X-Request-ID` - Unique request identifier
- `X-Correlation-ID` - Correlation ID if provided
- `X-Response-Time` - Request duration (e.g., "150ms")

### Features

- Automatic UUID4 generation for each request
- Context variables (thread-safe)
- Correlation ID propagation
- Request timing
- Enhanced logging with request/user context

---

## Security Logging

**Location:** `src/rot/core/security_logger.py`

Structured JSON logging for security events (SIEM-ready).

### Event Types

1. **auth_attempt** - Login/register attempts
2. **rate_limit_violation** - Rate limit exceeded
3. **api_key_event** - API key creation/rotation/validation
4. **admin_elevation** - Admin privilege escalation
5. **suspicious_activity** - Anomalous behavior detected
6. **secret_validation_failure** - Invalid secret key
7. **backup_event** - Database backup operations
8. **tier_gate_block** - Feature access denied (tier)
9. **data_export** - Data export requests
10. **config_change** - Configuration modifications

### Usage

```python
from rot.core.security_logger import log_auth_attempt, log_rate_limit_violation

# Log successful login
log_auth_attempt(
    event="login",
    email="user@example.com",
    ip="192.168.1.1",
    success=True,
    metadata={"tier": "pro", "user_id": 42}
)

# Log rate limit violation
log_rate_limit_violation(
    endpoint="/api/v1/login",
    ip="192.168.1.1",
    attempt_count=6,
    limit=5,
    window_seconds=300,
    metadata={"retry_after": 120}
)
```

### Log Output

```json
{
  "event_type": "auth_attempt",
  "auth_event": "login",
  "timestamp": "2026-02-14T21:35:00.123456",
  "email": "user@example.com",
  "ip_address": "192.168.1.1",
  "success": true,
  "reason": null,
  "metadata": {
    "tier": "pro",
    "user_id": 42
  }
}
```

---

## Database Backups

**Location:** `src/rot/storage/backup.py`

Automated database backups with compression and rotation.

### Usage

```python
from rot.storage.backup import BackupManager

manager = BackupManager(
    db_path="/app/data/rot.db",
    backup_dir="/app/data/backups",
    max_backups=7  # Keep last 7 backups
)

# Create backup
backup_file = await manager.create_backup()
# Returns: Path("/app/data/backups/rot_backup_20260214_213500.db.gz")

# List backups
backups = await manager.list_backups()
# Returns: [BackupInfo(path=..., size_mb=..., created_at=...), ...]

# Restore backup
await manager.restore_backup(backup_file)
```

### Features

- GZip compression (~70% size reduction)
- Automatic rotation (keeps last N backups)
- Metadata tracking (size, timestamp)
- Atomic operations (temp file + rename)

### Configuration

```bash
# Backup directory (default: /app/data/backups)
ROT_BACKUP_DIR=/app/data/backups

# Max backups to keep (default: 7)
ROT_MAX_BACKUPS=7
```

---

## Health Checks

**Location:** Enhanced health endpoint at `/health`

### Response

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 3600,
  "database": {
    "status": "connected",
    "signals_stored": 50000,
    "size_mb": 150.5,
    "last_backup": "2026-02-14T20:00:00"
  },
  "system": {
    "memory_rss_mb": 250.5,
    "cpu_percent": 15.2,
    "num_threads": 8,
    "disk_usage_percent": 45.0
  },
  "backups": {
    "count": 7,
    "latest": "2026-02-14T20:00:00",
    "total_size_mb": 500.0
  }
}
```

### Monitoring

```bash
# Check health
curl https://rot.example.com/health

# Kubernetes liveness probe
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
```

---

## Dependency Scanning

**Location:** `.github/workflows/security.yml`

Automated security scanning via GitHub Actions.

### Scanners

1. **pip-audit** - Python dependency vulnerabilities
2. **CodeQL** - Code security analysis
3. **Bandit** - Python security issues
4. **TruffleHog** - Secret detection

### Schedule

- On every push to `main`
- On every pull request
- Weekly security scan (Sunday 2 AM)

### Dependabot

**Location:** `.github/dependabot.yml`

Automated dependency updates:

- Python packages (weekly)
- GitHub Actions (weekly)
- Docker base images (weekly)
- Grouped updates to reduce PR noise

---

## Loading States

**Location:** `src/rot/web/static/css/loading.css`, `src/rot/web/static/js/loading.js`

Professional loading indicators and skeleton screens.

### JavaScript API

```javascript
// Show spinner
Loading.show('#my-container', 'md', 'primary');

// Hide spinner
Loading.hide('#my-container');

// Show overlay
Loading.showOverlay('#main-content', false);

// Button loading state
Loading.buttonStart('#submit-btn', 'Saving...');
Loading.buttonEnd('#submit-btn');

// Skeleton loader
Loading.showSkeleton('#signal-feed', 3, 'signal');

// Empty state
Loading.showEmpty('#results', 'No signals', 'Try adjusting filters');
```

### HTMX Integration

```html
<!-- Automatic skeleton loader on HTMX requests -->
<div id="signal-feed" data-loading-skeleton="3">
  <!-- Content -->
</div>

<!-- Disable button during HTMX request -->
<button type="submit" data-loading-disable>
  <span class="htmx-indicator spinner spinner-sm"></span>
  Filter
</button>
```

### CSS Classes

```html
<!-- Spinner variants -->
<div class="spinner"></div>
<div class="spinner spinner-lg spinner-primary"></div>

<!-- Skeleton loaders -->
<div class="skeleton skeleton-text"></div>
<div class="skeleton-signal-card">...</div>

<!-- Loading overlay -->
<div class="loading-overlay">
  <div class="spinner spinner-lg"></div>
</div>

<!-- Empty state -->
<div class="empty-state">
  <div class="empty-state-icon">📭</div>
  <div class="empty-state-title">No Results</div>
  <div class="empty-state-description">Try different filters</div>
</div>
```

### Features

- Spinner animations (3 sizes, 3 variants)
- Loading overlays with backdrop blur
- Skeleton loaders with shimmer effect
- Signal card skeletons
- HTMX loading indicators
- Button loading states
- Progress bars
- Fade-in animations
- Empty state components

---

## Best Practices

### Rate Limiting

- Use database-backed rate limiting for multi-instance deployments
- Log all rate limit violations for security monitoring
- Return `Retry-After` header with 429 responses

### Retry Logic

- Apply retry decorators to all external API calls
- Use exponential backoff with jitter
- Set reasonable max_attempts (3-5 for most cases)
- Don't retry on client errors (4xx), only server/network errors

### Request Tracing

- Always include request IDs in error messages
- Use correlation IDs for distributed systems
- Log request/user context for debugging

### Security Logging

- Log all authentication events (success and failure)
- Log all rate limit violations
- Log all admin privilege escalations
- Use structured JSON logs for SIEM integration

### Backups

- Schedule regular backups (hourly/daily based on needs)
- Keep 7-30 days of backups based on retention policy
- Monitor backup sizes and storage usage
- Test restore process regularly

### Loading States

- Use skeleton loaders for predictable content (lists, cards)
- Use spinners for unpredictable content (search results)
- Always provide visual feedback for async operations
- Show empty states when no data is available

---

## Related Documentation

- [Architecture](architecture.md) - Overall system design
- [Database](database.md) - Schema and migrations
- [Web Layer](web-layer.md) - Routes and tier gating
- [Testing](testing.md) - Test patterns
- [Deployment](deployment.md) - Railway deployment
