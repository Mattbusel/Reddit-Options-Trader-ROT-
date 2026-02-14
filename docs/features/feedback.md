<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Feedback Engine

- **Files**: `src/rot/feedback/{analyzer,suppressor,__init__}.py`
- **DB**: reads `signals`, `signal_performance`, `signal_archive` (no dedicated tables)
- **Routes**: `GET /signal-quality` (Pro+ via `gate_signal_quality_access()`)
- **Config**: `ROT_FEEDBACK_ENABLED` (True), `ROT_FEEDBACK_ANALYSIS_INTERVAL_S` (21600), `ROT_FEEDBACK_SUPPRESS_ENABLED` (True), `ROT_FEEDBACK_SUPPRESS_THRESHOLD` (0.20), `ROT_FEEDBACK_SUPPRESS_SOURCE_THRESHOLD` (0.15), `ROT_FEEDBACK_MIN_SIGNALS_FOR_SUPPRESSION` (30), `ROT_FEEDBACK_QUALITY_TREND_WINDOW_DAYS` (30)

## FeedbackAnalyzer
Background loop every 6h, caches results in `_last_analysis` dict (GIL-safe reads, no locks). Uses unified CTE for archived data.

**Analysis components**: category performance (win rate per event type), source reliability (win rate per event_type+subreddit), feature importance (which features correlate with wins), quality trends (rolling slope/MA over 30d), suppression candidates, confidence calibration.

## SignalSuppressor (Pipeline Stage 6.5)
Between credibility (6) and LLM reasoning (7). Skips expensive LLM calls for losing categories.

### Suppression Rules
| Rule | Condition |
|------|-----------|
| Category-level | Event type win_rate < 20% with 30+ signals |
| Source-level | (event_type, subreddit) win_rate < 15% with 30+ signals |
| Low-confidence + poor category | confidence < 0.3 AND event type is suppression candidate |

### When suppressed
Stub ReasoningPacket (no LLM), no-trade TradeIdea, signal still stored with `meta["suppressed"]=True`. On first deployment (`_last_analysis` is None), never suppresses.

## Signal Quality Dashboard
Displays: category performance table, source reliability, feature importance, quality trend charts, suppression candidates, confidence calibration curve.

## Tests
`test_feedback.py` -- analyzer (slope, MA, feature importance, candidates), suppressor (category/source/low-confidence, apply), tier gates
