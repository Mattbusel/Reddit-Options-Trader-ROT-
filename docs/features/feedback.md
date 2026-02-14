# Feedback Engine — ROT Feature Reference
> Part of the ROT documentation suite. See [CLAUDE.md](../../CLAUDE.md) for the full index.

## Quick Start for Agents
- Key files: `src/rot/feedback/analyzer.py`, `src/rot/feedback/suppressor.py`, `src/rot/feedback/__init__.py`
- DB tables: None dedicated (reads from `signals`, `signal_performance`, `signal_archive`)
- Routes: `GET /signal-quality` (Pro+ gated)
- Config: `ROT_FEEDBACK_ENABLED`, `ROT_FEEDBACK_ANALYSIS_INTERVAL_S`, `ROT_FEEDBACK_SUPPRESS_ENABLED`, `ROT_FEEDBACK_SUPPRESS_THRESHOLD`, `ROT_FEEDBACK_SUPPRESS_SOURCE_THRESHOLD`, `ROT_FEEDBACK_MIN_SIGNALS_FOR_SUPPRESSION`, `ROT_FEEDBACK_QUALITY_TREND_WINDOW_DAYS`

---

## Module Layout

| File | Purpose |
|------|---------|
| `__init__.py` | Exports FeedbackAnalyzer, SignalSuppressor |
| `analyzer.py` | Analysis engine: category performance, source reliability, feature importance, quality trends, suppression candidates, calibration |
| `suppressor.py` | Adaptive signal suppressor: Stage 6.5 in the pipeline |

## FeedbackAnalyzer

The analyzer runs expensive DB queries in a background loop every 6 hours (configurable), caching results in `_last_analysis` for instant access by the dashboard and suppressor.

### Analysis Components

**Category Performance**: Win rate, signal count, and trend direction per event type (earnings_rumor, product_news, regulatory, squeeze_chatter, macro, other). Identifies which categories are consistently profitable or consistently losing.

**Source Reliability**: Win rate broken down by (event_type, subreddit) pairs. Identifies which source/category combinations are reliable vs unreliable. Used by the suppressor for source-level suppression.

**Feature Importance**: Analyzes which signal features (confidence, trend score, post score, author karma, NLP metrics) correlate most strongly with win/loss outcomes. Provides ranked feature importance.

**Quality Trends**: Computes rolling quality metrics over a configurable window (default 30 days): slope of win rate, moving average of confidence, trend direction (improving/declining/stable).

**Suppression Candidates**: Identifies event types and source combinations that should be suppressed based on historically low win rates and sufficient sample sizes.

**Confidence Calibration**: Compares predicted confidence levels against actual win rates to identify systematic over- or under-confidence.

### Precomputed Cache Pattern

The analyzer stores results in `_last_analysis` (a plain dict). The Signal Quality dashboard reads this cache instantly (no DB query on page load). The suppressor reads the same cache from the sync pipeline thread. This is safe because Python's GIL guarantees atomic dict reads, so no locks are needed.

## SignalSuppressor (Pipeline Stage 6.5)

Sits between credibility scoring (Stage 6) and LLM reasoning (Stage 7). Its purpose is to skip expensive LLM API calls for signals in historically losing categories.

### Suppression Rules

| Rule | Condition | Threshold |
|------|-----------|-----------|
| Category-level | Event type win rate below threshold | < 20% with 30+ decided signals |
| Source-level | (Event type, subreddit) win rate below threshold | < 15% with 30+ decided signals |
| Low-confidence + poor category | Confidence < 0.3 AND event type is a suppression candidate | Compound check |

### Suppression Behavior

When a signal is suppressed:
1. A stub `ReasoningPacket` is generated (no LLM call)
2. A no-trade `TradeIdea` stub is used (no trade building)
3. The signal is still stored in the DB with `meta["suppressed"]=True` for audit
4. LLM and trade building stages are completely skipped

### Graceful First Deployment

On first deployment (or when `_last_analysis` is None), the suppressor never suppresses any signals. It only activates after the first `FeedbackAnalyzer.run_analysis()` completes, ensuring no behavior change until the system has enough data.

## Signal Quality Dashboard

Route: `GET /signal-quality` (Pro+ tier gated via `gate_signal_quality_access()`)

Displays the precomputed analysis results:
- Category performance table with win rates and trends
- Source reliability breakdown
- Feature importance rankings
- Quality trend charts over time
- Suppression candidates list
- Confidence calibration curve

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ROT_FEEDBACK_ENABLED` | `True` | Enable feedback analysis background loop |
| `ROT_FEEDBACK_ANALYSIS_INTERVAL_S` | `21600` | Seconds between analysis cycles (6h) |
| `ROT_FEEDBACK_SUPPRESS_ENABLED` | `True` | Enable adaptive signal suppression |
| `ROT_FEEDBACK_SUPPRESS_THRESHOLD` | `0.20` | Suppress categories with win rate below 20% |
| `ROT_FEEDBACK_SUPPRESS_SOURCE_THRESHOLD` | `0.15` | Suppress source combos below 15% |
| `ROT_FEEDBACK_MIN_SIGNALS_FOR_SUPPRESSION` | `30` | Min decided signals before suppression activates |
| `ROT_FEEDBACK_QUALITY_TREND_WINDOW_DAYS` | `30` | Days of history for quality trend analysis |

## Tests

`test_feedback.py` covers:
- FeedbackAnalyzer: slope computation, moving average, feature importance, suppression candidates
- SignalSuppressor: category-level suppression, source-level suppression, low-confidence + poor category, `apply()` method
- Tier gate tests for signal quality dashboard access

## Design Notes

- The feedback engine uses the unified CTE to include archived signals, enabling analysis over longer time periods than the 14-day live retention window.
- Suppression saves LLM API costs by avoiding reasoning on historically losing signal categories. This is the primary cost optimization.
- The 30-signal minimum for suppression prevents premature suppression from small sample sizes.
- Both thresholds (20% category, 15% source) are intentionally aggressive: a category needs to be substantially losing before suppression kicks in.
- The `apply()` method returns a tuple `(Event, was_suppressed)` so the pipeline can track suppression counts.
