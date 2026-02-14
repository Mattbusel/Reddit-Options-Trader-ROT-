# Database Schema — ROT Architecture Reference

> Part of the ROT documentation suite. See [CLAUDE.md](../CLAUDE.md) for the full index.

## Quick Start for Agents

- Key file(s): `src/rot/storage/database.py`
- Key pattern: SQLite with WAL mode, async via aiosqlite, 18+ tables, JSON blob columns for complex data, `_UNIFIED_CTE` for archive-inclusive queries
- All tables created/migrated in `Database.connect()` method

---

## Overview

SQLite with WAL mode, managed by `src/rot/storage/database.py`. All tables use async access via aiosqlite. Complex nested data is stored as JSON text columns.

**Connection config:**

| Setting | Value |
|---------|-------|
| Engine | aiosqlite |
| Mode | WAL (Write-Ahead Logging) |
| Path | `ROT_DB_PATH` or `{ROT_STORAGE_ROOT}/rot.db` |
| Migrations | Run on `connect()`, idempotent |

---

## Core Tables

### `signals` -- Core signal storage

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| run_id | TEXT | Pipeline run identifier |
| created_at | REAL | Unix timestamp |
| ticker | TEXT | Primary ticker symbol |
| event_type | TEXT | One of 6 EventTypes |
| stance | TEXT | bullish/bearish/mixed/unknown |
| time_horizon | TEXT | intraday/1w/earnings/longer/unknown |
| confidence | REAL | 0.0-1.0 after credibility scoring |
| trend_score | REAL | Raw trend detection score |
| quality_score | REAL | Trade quality score 0.0-1.0 |
| strategy | TEXT | Options strategy name |
| subreddit | TEXT | Source subreddit |
| post_title | TEXT | Reddit post title |
| post_url | TEXT | Reddit post URL |
| market_data | TEXT (JSON) | Price, cap, IV, options chain data |
| reasoning | TEXT (JSON) | Full ReasoningPacket |
| trade_idea | TEXT (JSON) | Full TradeIdea |
| event_data | TEXT (JSON) | Full Event including NLP metadata |
| sector | TEXT | Market sector |
| sponsored | INTEGER | 0/1 flag for sponsored signals |
| sponsored_by | TEXT | Sponsor company name |

**Indexes:**
- `ticker`
- `created_at DESC`
- `confidence DESC`
- `stance`
- `(post_url, ticker, created_at)` -- unique constraint for dedup
- `event_type`
- `strategy`
- `(created_at DESC, ticker)`

### `signal_performance` -- Price tracking

| Column | Type | Description |
|--------|------|-------------|
| signal_id | TEXT FK-->signals | Linked signal |
| ticker | TEXT | Ticker symbol |
| price_at_signal | REAL | Price when signal generated |
| price_1h | REAL | Price 1 hour later |
| price_4h | REAL | Price 4 hours later |
| price_1d | REAL | Price 1 day later |
| price_1w | REAL | Price 1 week later |
| max_gain_pct | REAL | Peak gain % since signal |
| max_loss_pct | REAL | Peak loss % since signal |
| checked_at | REAL | Last price check timestamp |

### `signal_archive` -- Long-term archive

Denormalized flat table preserving per-signal data from `signals JOIN signal_performance` before 14-day purge. Used for backtesting and analytics beyond the live data window.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | Original signal UUID |
| created_at | REAL | Original signal timestamp |
| ticker | TEXT | Ticker symbol |
| event_type | TEXT | Event type |
| stance | TEXT | Signal stance |
| strategy | TEXT | Options strategy |
| confidence | REAL | Confidence score |
| subreddit | TEXT | Source subreddit |
| quality_score | REAL | Trade quality score |
| sector | TEXT | Market sector |
| post_title | TEXT | Post title |
| price_at_signal | REAL | Entry price |
| price_1h | REAL | Price at +1h |
| price_4h | REAL | Price at +4h |
| price_1d | REAL | Price at +1d |
| max_gain_pct | REAL | Peak gain % |
| max_loss_pct | REAL | Peak loss % |
| archived_at | REAL | When archived |

**Retention:** 365 days (configurable via `ROT_ARCHIVE_KEEP_DAYS`).

---

## User & Auth Tables

### `users` -- User accounts

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| email | TEXT UNIQUE | User email |
| password_hash | TEXT | bcrypt hash |
| api_key_hash | TEXT UNIQUE | SHA-256 hash of API key |
| tier | TEXT | free/pro/premium/ultra/enterprise |
| settings | TEXT (JSON) | User preferences (watchlist, filter presets, LLM settings) |

### `subscriptions` -- Stripe subscriptions

| Column | Type | Description |
|--------|------|-------------|
| user_id | TEXT FK-->users | Linked user |
| stripe_customer_id | TEXT | Stripe customer ID |
| stripe_subscription_id | TEXT | Stripe subscription ID |
| tier | TEXT | Subscription tier |
| status | TEXT | active/canceled/past_due |
| current_period_end | REAL | Unix timestamp |

---

## Trading Tables

### `paper_portfolios` -- Paper trading balances

| Column | Type | Description |
|--------|------|-------------|
| user_id | TEXT PK FK-->users | One portfolio per user |
| balance | REAL | Current balance (default $10,000) |
| total_trades | INTEGER | Total trade count |
| winning_trades | INTEGER | Winning trade count |
| total_pnl | REAL | Cumulative P&L |

### `paper_trades` -- Paper trading history

| Column | Type | Description |
|--------|------|-------------|
| user_id | TEXT FK-->users | Owner |
| signal_id | TEXT | Linked signal |
| ticker | TEXT | Symbol |
| entry_price | REAL | Trade entry price |
| exit_price | REAL | Trade exit price |
| pnl_dollars | REAL | Profit/loss in dollars |
| pnl_pct | REAL | Profit/loss percentage |
| status | TEXT | open/closed |

---

## Analytics & Feature Tables

| Table | Columns (key) | Purpose |
|-------|---------------|---------|
| `backtest_runs` | id, user_id, name, config_json, result_json, monte_carlo_json, risk_json, created_at | Saved backtest runs |
| `backtest_strategies` | id, user_id, name, description, config_json, last_result_json, last_run_at, created_at, is_active | Saved named backtest strategies |
| `unusual_events` | id, ticker, event_type, score, details_json, signal_id, detected_at | Unusual activity events. Types: iv_spike, volume_surge, oi_surge, skew_shift, sweep |
| `win_rate_snapshots` | (periodic aggregation) | Periodic win rate aggregation |
| `congress_trades` | (trade data) | Congressional trading tracker data |

---

## Integration & Alert Tables

| Table | Purpose |
|-------|---------|
| `api_usage` | Per-user API call tracking for rate limiting |
| `email_alert_settings` | Per-user email alert preferences (digest, realtime, filters) |
| `x_posts` | Twitter/X posting history |
| `referral_clicks` / `referral_conversions` | Affiliate tracking |
| `sponsored_signals` | Enterprise sponsored signal submissions |
| `data_exports` | Enterprise data export request tracking |
| `export_schedules` | Scheduled enterprise exports (id, user_id, format, frequency, filters_json, last_run_at, next_run_at, created_at) |

---

## SQL Helper Patterns

### Win/Loss SQL Macros

Only **bullish** and **bearish** signals count as trades. Mixed and unknown stances are always neutral.

```
_WIN_CASE_SQL:
  CASE WHEN stance='bullish' AND max_gain_pct >= 5.0 THEN 1
       WHEN stance='bearish' AND max_loss_pct >= 5.0 THEN 1
       ELSE 0 END

_LOSS_CASE_SQL:
  CASE WHEN stance='bullish' AND max_loss_pct >= 5.0 THEN 1
       WHEN stance='bearish' AND max_gain_pct >= 5.0 THEN 1
       ELSE 0 END

_NEUTRAL_CASE_SQL:
  (not win AND not loss, or stance not in bullish/bearish)
```

### Unified CTE (`_UNIFIED_CTE`)

Enables all analytics queries to seamlessly include both live signals and archived data:

```sql
WITH unified AS (
    SELECT s.id, s.created_at, s.ticker, s.event_type, s.stance,
           s.strategy, s.confidence, s.subreddit, s.quality_score,
           s.sector, s.post_title,
           sp.price_at_signal, sp.price_1h, sp.price_4h, sp.price_1d,
           sp.max_gain_pct, sp.max_loss_pct
    FROM signals s
    JOIN signal_performance sp ON s.id = sp.signal_id
    UNION ALL
    SELECT id, created_at, ticker, event_type, stance,
           strategy, confidence, subreddit, quality_score,
           sector, post_title,
           price_at_signal, price_1h, price_4h, price_1d,
           max_gain_pct, max_loss_pct
    FROM signal_archive
)
```

Archive-compatible SQL macros (`_A_WIN_SQL`, `_A_LOSS_SQL`, `_A_NEUTRAL_SQL`) use unqualified column names for use inside the CTE.

### Queries Using Unified CTE

The following 14 query methods use the unified CTE to include archived data:

| Method | Purpose |
|--------|---------|
| `get_signals_for_backtest()` | Backtest signal retrieval |
| `get_accuracy_stats()` | Win/loss accuracy |
| `get_confidence_calibration()` | Confidence bucket calibration |
| `get_strategy_pnl()` | Strategy P&L breakdown |
| `get_event_type_accuracy()` | Per-event-type accuracy |
| `get_confidence_accuracy()` | Confidence vs outcome correlation |
| `get_ticker_performance()` | Per-ticker performance |
| `get_signals_csv_export()` | CSV export |
| `get_performance_summary()` | Summary dashboard stats |
| `get_accuracy_by_subreddit()` | Subreddit accuracy |
| Feedback: `_category_performance()` | Category win rates |
| Feedback: `_source_reliability()` | Source-level reliability |
| Feedback: `_quality_trend()` | Quality over time |
| Feedback: `_confidence_calibration()` | Calibration analysis |

---

## Migration System

Migrations run in `Database.connect()` and are idempotent (use `IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN` with try/except). Key migration behaviors:

- **Table creation**: All 18+ tables created with `CREATE TABLE IF NOT EXISTS`
- **Column additions**: New columns added via `ALTER TABLE` wrapped in try/except (sqlite has no `IF NOT EXISTS` for columns)
- **Index creation**: `CREATE INDEX IF NOT EXISTS`
- **Archive seeding**: One-time migration seeds `signal_archive` with existing resolved signals on first connect after the feature was added
- **Win rate snapshots**: Cleared on deploy when win/loss logic changes (migration re-runs)

---

## Data Lifecycle

| Phase | Retention | Mechanism |
|-------|-----------|-----------|
| Live signals + performance | 14 days | `run_full_cleanup()` purges older |
| Signal archive | 365 days | `archive_before_purge()` copies before deletion, `purge_old_archives()` trims |
| Unusual events | 90 days | Background purge in scanner loop |
| No overlap risk | -- | Archived signals are >14 days old, live signals are <14 days old |
