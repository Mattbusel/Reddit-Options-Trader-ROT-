<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Database Schema — ROT

> See [CLAUDE.md](../CLAUDE.md) for full index.

**Key file:** `src/rot/storage/database.py` | SQLite WAL mode, aiosqlite, 18+ tables, JSON blob columns, `_UNIFIED_CTE` for archive-inclusive queries. All tables created/migrated in `Database.connect()`. Path: `ROT_DB_PATH` or `{ROT_STORAGE_ROOT}/rot.db`.

---

## `signals` (Core signal storage)

- `id TEXT PK` — UUID
- `run_id TEXT` — pipeline run ID
- `created_at REAL` — unix ts
- `ticker TEXT` [IDX]
- `event_type TEXT` [IDX] — earnings_rumor/product_news/regulatory/squeeze_chatter/macro/other
- `stance TEXT` [IDX] — bullish/bearish/mixed/unknown
- `time_horizon TEXT` — intraday/1w/earnings/longer/unknown
- `confidence REAL` [IDX DESC] — 0.0-1.0
- `trend_score REAL`
- `quality_score REAL` — 0.0-1.0
- `strategy TEXT` [IDX]
- `subreddit TEXT`
- `post_title TEXT`
- `post_url TEXT`
- `market_data JSON` — price, cap, IV, options chain
- `reasoning JSON` — ReasoningPacket
- `trade_idea JSON` — TradeIdea
- `event_data JSON` — Event + NLP metadata
- `sector TEXT`
- `sponsored INTEGER` — 0/1
- `sponsored_by TEXT`

**Indexes:** `ticker`, `created_at DESC`, `confidence DESC`, `stance`, `(post_url, ticker, created_at)` UNIQUE, `event_type`, `strategy`, `(created_at DESC, ticker)`

## `signal_performance` (Price tracking)

- `signal_id TEXT` [FK->signals]
- `ticker TEXT`
- `price_at_signal REAL`
- `price_1h REAL`, `price_4h REAL`, `price_1d REAL`, `price_1w REAL`
- `max_gain_pct REAL`, `max_loss_pct REAL`
- `checked_at REAL`

## `signal_archive` (Long-term, denormalized)

Flat copy of `signals JOIN signal_performance` preserved before 14-day purge. Retention: 365 days (`ROT_ARCHIVE_KEEP_DAYS`).

- `id TEXT PK`, `created_at REAL`, `ticker TEXT`, `event_type TEXT`, `stance TEXT`, `strategy TEXT`, `confidence REAL`, `subreddit TEXT`, `quality_score REAL`, `sector TEXT`, `post_title TEXT`
- `price_at_signal REAL`, `price_1h REAL`, `price_4h REAL`, `price_1d REAL`, `max_gain_pct REAL`, `max_loss_pct REAL`
- `archived_at REAL`

---

## User & Auth

**`users`:** `id TEXT PK`, `email TEXT UNIQUE`, `password_hash TEXT` (bcrypt), `api_key_hash TEXT UNIQUE` (SHA-256), `tier TEXT` (free/pro/premium/ultra/enterprise), `settings JSON` (watchlist, filter presets, LLM settings)

**`subscriptions`:** `user_id TEXT FK->users`, `stripe_customer_id TEXT`, `stripe_subscription_id TEXT`, `tier TEXT`, `status TEXT` (active/canceled/past_due), `current_period_end REAL`

---

## Trading

**`paper_portfolios`:** `user_id TEXT PK FK->users`, `balance REAL` (default $10k), `total_trades INT`, `winning_trades INT`, `total_pnl REAL`

**`paper_trades`:** `user_id TEXT FK->users`, `signal_id TEXT`, `ticker TEXT`, `entry_price REAL`, `exit_price REAL`, `pnl_dollars REAL`, `pnl_pct REAL`, `status TEXT` (open/closed)

---

## Analytics & Feature Tables

| Table | Key Columns | Notes |
|-------|-------------|-------|
| `backtest_runs` | id, user_id, name, config_json, result_json, monte_carlo_json, risk_json, created_at | Saved runs |
| `backtest_strategies` | id, user_id, name, description, config_json, last_result_json, last_run_at, created_at, is_active | Named strategies |
| `unusual_events` | id, ticker, event_type, score, details_json, signal_id, detected_at | Types: iv_spike/volume_surge/oi_surge/skew_shift/sweep |
| `win_rate_snapshots` | periodic aggregation | Cleared on win/loss logic change |
| `congress_trades` | trade data | Congressional tracker |

---

## Integration & Alert Tables

| Table | Purpose |
|-------|---------|
| `api_usage` | Per-user API rate limiting |
| `email_alert_settings` | Per-user alert prefs (digest, realtime, filters) |
| `x_posts` | Twitter/X posting history |
| `referral_clicks` / `referral_conversions` | Affiliate tracking |
| `sponsored_signals` | Enterprise sponsored submissions |
| `data_exports` | Enterprise export requests |
| `export_schedules` | Scheduled exports (id, user_id, format, frequency, filters_json, last_run_at, next_run_at, created_at) |

---

## SQL Helper Patterns

### Win/Loss Macros

Only **bullish** and **bearish** stances count as trades. Mixed/unknown = neutral.

```
_WIN_CASE_SQL:  stance='bullish' AND max_gain_pct>=5.0 OR stance='bearish' AND max_loss_pct>=5.0
_LOSS_CASE_SQL: stance='bullish' AND max_loss_pct>=5.0 OR stance='bearish' AND max_gain_pct>=5.0
_NEUTRAL_CASE_SQL: not win AND not loss, or stance not in (bullish, bearish)
```

### Unified CTE (`_UNIFIED_CTE`)

Unions live `signals JOIN signal_performance` with `signal_archive` for seamless analytics:

```sql
WITH unified AS (
    SELECT s.id, s.created_at, s.ticker, s.event_type, s.stance, s.strategy,
           s.confidence, s.subreddit, s.quality_score, s.sector, s.post_title,
           sp.price_at_signal, sp.price_1h, sp.price_4h, sp.price_1d,
           sp.max_gain_pct, sp.max_loss_pct
    FROM signals s JOIN signal_performance sp ON s.id = sp.signal_id
    UNION ALL
    SELECT id, created_at, ticker, event_type, stance, strategy, confidence,
           subreddit, quality_score, sector, post_title, price_at_signal,
           price_1h, price_4h, price_1d, max_gain_pct, max_loss_pct
    FROM signal_archive
)
```

Archive macros (`_A_WIN_SQL`, `_A_LOSS_SQL`, `_A_NEUTRAL_SQL`) use unqualified column names for CTE context.

### 14 Methods Using Unified CTE

`get_signals_for_backtest`, `get_accuracy_stats`, `get_confidence_calibration`, `get_strategy_pnl`, `get_event_type_accuracy`, `get_confidence_accuracy`, `get_ticker_performance`, `get_signals_csv_export`, `get_performance_summary`, `get_accuracy_by_subreddit`, Feedback: `_category_performance`, `_source_reliability`, `_quality_trend`, `_confidence_calibration`

---

## Migrations

Run in `Database.connect()`, idempotent. Tables: `CREATE TABLE IF NOT EXISTS`. Columns: `ALTER TABLE ADD COLUMN` in try/except (SQLite lacks `IF NOT EXISTS` for columns). Indexes: `CREATE INDEX IF NOT EXISTS`. One-time archive seeding on first connect. Win rate snapshots cleared on logic change.

---

## Data Lifecycle

| Phase | Retention | Mechanism |
|-------|-----------|-----------|
| Live signals + performance | 14 days | `run_full_cleanup()` |
| Signal archive | 365 days | `archive_before_purge()` then `purge_old_archives()` |
| Unusual events | 90 days | Background purge in scanner loop |

No overlap: archived >14d old, live <14d old.
