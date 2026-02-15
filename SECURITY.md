# SECURITY.md — ROT Security Policy

> **BINDING POLICY**: This document defines the security standards for ALL code produced in this
> repository — by humans, Claude, or any AI agent. Every line of code (LOC) must meet these standards.
> Non-compliance blocks merges via CI (CodeQL, Bandit, pip-audit, TruffleHog).

**Baseline**: 0 open CodeQL alerts as of 2026-02-14 (425 closed), 0 Dependabot alerts as of 2026-02-15. This baseline MUST be maintained.

---

## 1. Static Analysis (CI-Enforced)

All PRs and pushes to `main`/`master` are scanned by GitHub Actions (`.github/workflows/security.yml`):

| Tool | What It Checks | Failure Policy |
|------|----------------|----------------|
| **CodeQL** (Python) | Unused imports/vars, info exposure, injection, weak crypto, logic defects | **Block merge** |
| **Bandit** | Python-specific security issues (B-series rules) | **Block merge** |
| **pip-audit** | Known CVEs in dependencies | **Warn** (review required) |
| **TruffleHog** | Secrets in code/history | **Block merge** |
| **Dependabot** | Outdated dependencies with known vulnerabilities | **Auto-PR** |

### CodeQL Configuration

File: `.github/codeql/codeql-config.yml`

Excluded queries (with documented justification):
- `py/log-injection` — Mitigated by global `SanitizingLogFilter`
- `py/clear-text-logging-sensitive-data` — Mitigated by global `SanitizingLogFilter`
- `py/weak-cryptographic-algorithm` — SHA-1 required by OAuth 1.0a (RFC 5849, Twitter API)
- `py/weak-sensitive-data-hashing` — HMAC-SHA1 (OAuth protocol) + SHA-256 for high-entropy API tokens
- `py/import-own-module` — Standard `__init__.py` re-export pattern

**Adding new exclusions requires**: (1) documented runtime mitigation, (2) code comment at the usage site, (3) approval in PR review.

---

## 2. Authentication & Authorization

### Auth Stack
- **JWT tokens** (access + refresh) for web sessions
- **API keys** (SHA-256 hashed in DB) for programmatic access
- **Session cookies** (httponly, secure, samesite=lax) for browser persistence
- **Admin tier** via `ROT_AUTH_ADMIN_EMAILS` environment variable (never in code)

### Rules
1. **Never hardcode secrets.** All credentials via `ROT_*` environment variables.
2. **Strong secret keys.** `ROT_AUTH_SECRET_KEY` must be cryptographically random, minimum 32 bytes. Validated at startup.
3. **Rate limiting** is database-backed (multi-instance safe), per-tier, with progressive penalties.
4. **Tier gates** return dicts, never raise exceptions directly. Auth failure = 401/403 HTTP response.
5. **Admin tier** is hidden from UI. Elevation only via email allowlist.

---

## 3. Cryptography Standards

| Use Case | Algorithm | Justification |
|----------|-----------|---------------|
| Password hashing | bcrypt (cost 12+) | Industry standard for low-entropy secrets |
| API key storage | SHA-256 | Acceptable for high-entropy random tokens (32+ bytes) |
| OAuth 1.0a signatures | HMAC-SHA1 | Protocol-mandated (RFC 5849), not a choice |
| JWT signing | HS256 (HMAC-SHA256) | Standard for symmetric JWT |
| Database backup | GZip | Compression, not encryption (backups are local) |

### Rules
6. **Never use MD5 or plain SHA-1 for passwords or secrets.**
7. **SHA-1 usage must have a code comment** citing the protocol requirement (e.g., `# OAuth 1.0a (RFC 5849) requires HMAC-SHA1`).
8. **New crypto algorithms** require review — default to what's already in use.

---

## 4. Input Validation & Injection Prevention

### SQL Injection
9. **Always use parameterized queries** (`?` placeholders with aiosqlite). Never interpolate user data into SQL strings.
10. **No f-strings in SQL.** Table/column names may use f-strings only if they come from hardcoded constants (never user input).

### XSS Prevention
11. **Jinja2 autoescaping is ON** (`autoescape=True`). Never use `| safe` filter on user-supplied content. All 16 `|safe` instances audited safe (2026-02-15): hardcoded static content or `tojson`.
12. **Content-Security-Policy** enforced via `SecurityHeadersMiddleware` (`src/rot/web/security_headers.py`). CSP uses `'unsafe-inline'` for `script-src` due to 102 inline `<script>` tags — nonce-based CSP is a future phase. Acceptable because autoescape is ON and all `|safe` usages are audited safe.
12a. **Defense-in-depth sanitizer** (`src/rot/core/sanitize.py`): `sanitize_html()` (nh3/Rust-based), `strip_html()`, `sanitize_for_json()`. Use for any new content rendered with `|safe`.
12b. **Security headers on all responses** (via `SecurityHeadersMiddleware`): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-XSS-Protection: 0` (OWASP), `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(self)`.

### Log Injection
13. **`SanitizingLogFilter`** is attached globally at startup. It strips newlines, control chars, and ANSI sequences from log messages.
14. **Never log raw user input** without the filter chain active. When in doubt, explicitly sanitize.

### Path Traversal
15. **Validate file paths** against a whitelist or base directory. Never construct file paths from user input without normalization and validation.

---

## 5. Error Handling & Information Exposure

16. **Never return stack traces to users.** Catch exceptions at route boundaries; return generic JSON/HTML errors. Log the full trace server-side.
17. **No internal paths in responses.** Error messages must not reveal file paths, module names, or database schemas.
18. **No version disclosure.** Do not expose Python version, framework version, or dependency versions in HTTP headers or error responses.

### Exception Handling Standards
19. **No bare `except: pass`.** Every exception handler must either:
    - Log the error (`log.error("...", exc_info=True)`)
    - Re-raise with context (`raise NewError("context") from e`)
    - Return a meaningful error response
20. **Catch specific exceptions.** `except ValueError` not `except Exception`, unless the broad catch is intentional and documented with a comment.
21. **Circuit breaker pattern** (used in `reasoner/`): After N consecutive failures, disable the failing subsystem and use fallback. Do not retry indefinitely.

---

## 6. Data Protection

22. **Secrets in environment only.** `ROT_AUTH_SECRET_KEY`, API keys, OAuth tokens — all via env vars, never in code or config files.
23. **`.env` in `.gitignore`.** Verified. Never commit `.env` files.
24. **Database backups** use GZip compression with rotation (configurable retention). Stored in the persistent volume, not in the repo.
25. **Signal archive** purges raw signals after 14 days. `archive_before_purge()` preserves analytics data without PII.
26. **Request IDs** (UUID4) are attached to every request for tracing but contain no user data.

---

## 7. Code Quality Standards (Zero-Alert Baseline)

These rules prevent the categories of issues found in the 425 CodeQL alerts:

### Imports (40% of historical alerts)
27. **Only import what you use.** After every edit, verify all imported names appear in the file.
28. **Cascading cleanup.** Removing code that used an import? Check if the import is now orphaned.
29. **`from __future__ import annotations`** does NOT make typing imports "free" — CodeQL still flags unused ones.
30. **Circular imports**: Use `if TYPE_CHECKING:` guard for type-only imports.

### Variables (30% of historical alerts)
31. **Every assignment must be read.** Dead assignments are code quality violations.
32. **Side-effect calls**: Use bare `await foo()` not `_result = await foo()` when the result is unused.
33. **Cascading cleanup.** Removing code that read a variable? Check if the assignment is now dead.
34. **No redundant initializations** before if/elif/else blocks that cover all branches.

### Logic (5% of historical alerts)
35. **No self-comparisons** (`x == x`, `x != x`). Use `math.isnan()` for NaN detection.
36. **No redundant boolean conditions.** Review all if/elif chains for duplicate conditions.
37. **Float equality**: Use `math.isclose(a, b)` not `a == b`.

---

## 8. Dependency Security

38. **Dependabot** is configured (`.github/dependabot.yml`) for weekly scans.
39. **pip-audit** runs in CI on every push.
40. **Security-critical packages pinned to exact versions** (`==`) in `pyproject.toml`: fastapi, starlette, pydantic, pydantic-settings, aiosqlite, python-jose, cryptography, bcrypt, uvicorn, jinja2, httpx. Do not update without reviewing changelogs and running full test suite. Application packages (praw, yfinance, etc.) use loose constraints.
41. **Review dependency additions.** New dependencies must be justified and checked for known vulnerabilities before adding.
41a. **nh3** (Rust-based HTML sanitizer) added as defense-in-depth. Replaces deprecated `bleach`.

---

## 9. Deployment Security

42. **Railway deployment** uses Docker with a non-root user.
43. **Persistent volume** at `/app/data` for database and backups. Not world-readable.
44. **Health endpoint** (`/health`) exposes only: status, uptime, database connectivity. No version info, no internal state.
45. **HTTPS enforced** via Railway's edge proxy. No HTTP in production.

---

## 10. Stripe & Payment Security

46a. **Webhook signature verification** via `stripe.Webhook.construct_event()` on raw `request.body()`. Rejects missing/invalid signatures with 400.
46b. **Empty webhook secret guard** — returns 500 with `log.error()` if `ROT_STRIPE_WEBHOOK_SECRET` is not configured, instead of cryptic crash.
46c. **Failed verification logging** includes client IP (`get_client_ip(request)`) for security monitoring/SIEM correlation.
46d. **No card data** ever touches ROT servers. All payment processing via Stripe Checkout (redirect flow). CSP allows `frame-src https://js.stripe.com` and `connect-src https://api.stripe.com` only.

---

## 11. Incident Response

47. **Security logging** (10 event types) is SIEM-ready JSON. Events: auth failures, rate limit hits, suspicious patterns, admin actions.
48. **Request ID correlation** across the entire pipeline (UUID4) for tracing incidents.
49. **Database backup** before any destructive operation (automatic in maintenance loops).

---

## 12. Agent & AI Policy

> These rules apply to ALL AI agents (Claude, sub-agents, GitHub Copilot, etc.) producing code for this repo.

50. **Agents MUST read `CLAUDE.md` and `AGENTS.md`** before writing any code.
51. **Agents MUST follow the pre-commit checklist** in CLAUDE.md section "Code Quality Guardrails".
52. **Agents MUST NOT add CodeQL exclusions** without human approval and documented justification.
53. **Agents MUST NOT introduce new dependencies** without human approval.
54. **Agents MUST NOT modify auth, tier gating, or rate limiting** without explicit human instruction.
55. **Agents MUST NOT commit `.env` files, secrets, or credentials** under any circumstances.
56. **Agents MUST run `pytest -x`** (or verify tests pass) before claiming a task is complete.
57. **Agents MUST verify 0 new CodeQL alerts** are introduced by their changes.

---

## 13. Compliance Checklist

For any PR, the author (human or agent) must verify:

```
[ ] No new CodeQL alerts introduced
[ ] No secrets in code (checked by TruffleHog)
[ ] No known CVEs in dependencies (checked by pip-audit)
[ ] All imports are used
[ ] All variables are read
[ ] No bare except: pass blocks
[ ] No stack traces in user-facing responses
[ ] SQL uses parameterized queries only
[ ] Tests pass (pytest -x)
[ ] No .env or credential files committed
```

---

## Reporting Security Issues

If you discover a security vulnerability, please report it privately via GitHub Security Advisories
or contact the maintainer directly. Do NOT open a public issue for security vulnerabilities.

---

*Last updated: 2026-02-15 | Baseline: 425 alerts fixed, 0 open, 0 Dependabot alerts | Enforced by: CodeQL + Bandit + pip-audit + TruffleHog + Dependabot*
