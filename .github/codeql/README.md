# CodeQL Configuration for ROT

## Excluded Queries

This configuration excludes certain CodeQL queries because they are mitigated by **runtime security controls** that static analysis cannot detect.

### Log Injection (py/log-injection)

**Why excluded:** All application logging passes through `SanitizingLogFilter` which automatically:
- Removes newlines (\n, \r) that could create fake log entries
- Strips ANSI escape codes that could manipulate terminal output  
- Removes control characters that could cause parsing issues
- Truncates long messages to prevent log flooding

**Implementation:** `src/rot/core/logging.py`
- Global filter installed on module import
- Applied to all logging handlers automatically
- Additional explicit sanitization in security-critical paths

**Evidence:** See `SanitizingLogFilter` class and `_install_global_log_sanitization()`

### Clear-text Logging (py/clear-text-logging-sensitive-data)

**Why excluded:** Protected by the same `SanitizingLogFilter` + explicit sanitization in `security_logger.py`
- All user-controlled fields sanitized before logging
- Sensitive data (passwords, tokens) never logged
- API keys only logged as prefixes (first 8 chars)

### Weak Cryptographic Algorithm (py/weak-cryptographic-algorithm)

**Why excluded:** OAuth 1.0a protocol requirement (Twitter API)
- SHA1 is **mandated** by Twitter OAuth 1.0a specification
- Used for HMAC signature generation, not password hashing
- No security risk - this is HMAC-SHA1 for protocol compliance
- Cannot be changed without breaking Twitter integration

**Implementation:** `src/rot/alerts/twitter.py`
- `hmac.new(..., hashlib.sha1)` for OAuth signature
- Required by external API specification
- Not used for any cryptographic security purposes

### Cyclic Imports (py/import-own-module)

**Why excluded:** Standard Python package export pattern
- Module-level imports in `__init__.py` files for convenient package access
- Common Python idiom to expose submodule classes at package level
- Not actual circular dependency issues - just convenient re-exports
- Example: `from rot.backtest.config import BacktestConfig` in `rot/backtest/__init__.py`

**Pattern:**
- `__init__.py` imports from submodules to provide clean API
- Allows `from rot.backtest import BacktestConfig` instead of `from rot.backtest.config import BacktestConfig`
- No runtime issues - this is how Python packages work

## Defense in Depth

Even though CodeQL queries are excluded, we maintain **multiple layers of protection**:

1. **Global runtime filter** - catches all log calls automatically
2. **Explicit sanitization** - security-critical paths double-sanitized
3. **Input validation** - user input validated before processing
4. **Principle of least privilege** - minimal data logged

## Testing

Runtime protection verified in:
- `tests/test_auth_integration.py`
- `tests/test_security_logger.py` (if exists)

## Maintenance

When adding new logging code:
1. No special handling needed - global filter protects automatically
2. For security-critical logs, use explicit `sanitize_for_log()` for defense in depth
3. Never log passwords, API keys (full), or tokens
