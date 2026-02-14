/* ROT SQL PATTERN LIBRARY — C-header style, grep-friendly
 * Usage: grep "WIN_CASE\|UNIFIED_CTE\|Q_PERF" .claude/sql.h
 * T=TEXT R=REAL I=INT $=JSON(TEXT) AI=AUTOINCREMENT
 */

/* ── STANCE-AWARE WIN/LOSS MACROS (database.py) ── */
/* {price_col} = sp.price_1h, sp.price_4h, sp.price_1d, sp.price_1w */

#define WIN_CASE(price_col) \
  CASE WHEN s.stance='bullish' AND ({price_col}-sp.price_at_signal)/sp.price_at_signal > 0.01 THEN 1 \
       WHEN s.stance='bearish' AND (sp.price_at_signal-{price_col})/sp.price_at_signal > 0.01 THEN 1 \
       ELSE 0 END

#define LOSS_CASE(price_col) \
  CASE WHEN s.stance='bullish' AND (sp.price_at_signal-{price_col})/sp.price_at_signal > 0.02 THEN 1 \
       WHEN s.stance='bearish' AND ({price_col}-sp.price_at_signal)/sp.price_at_signal > 0.02 THEN 1 \
       ELSE 0 END

#define NEUTRAL_CASE \
  CASE WHEN COALESCE(s.stance,'unknown') IN ('unknown','mixed') THEN 1 ELSE 0 END

/* ── ARCHIVE-COMPAT MACROS (unqualified columns for signal_archive) ── */
#define A_WIN(price_col) \
  CASE WHEN stance='bullish' AND ({price_col}-price_at_signal)/price_at_signal > 0.01 THEN 1 \
       WHEN stance='bearish' AND (price_at_signal-{price_col})/price_at_signal > 0.01 THEN 1 \
       ELSE 0 END

#define A_LOSS(price_col) \
  CASE WHEN stance='bullish' AND (price_at_signal-{price_col})/price_at_signal > 0.02 THEN 1 \
       WHEN stance='bearish' AND ({price_col}-price_at_signal)/price_at_signal > 0.02 THEN 1 \
       ELSE 0 END

#define A_NEUTRAL \
  CASE WHEN stance IN ('unknown','mixed') THEN 1 ELSE 0 END

/* ── UNIFIED CTE (live signals + archive union) ── */
#define UNIFIED_CTE \
  WITH _unified AS ( \
    SELECT s.id, s.created_at, s.ticker, s.event_type, s.stance, s.strategy, \
           s.confidence, s.subreddit, s.quality_score, s.sector, s.post_title, \
           sp.price_at_signal, sp.price_1h, sp.price_4h, sp.price_1d, \
           sp.max_gain_pct, sp.max_loss_pct \
    FROM signals s JOIN signal_performance sp ON s.id = sp.signal_id \
    WHERE sp.price_1d IS NOT NULL AND s.stance IN ('bullish','bearish') \
    UNION ALL \
    SELECT id, created_at, ticker, event_type, stance, strategy, \
           confidence, subreddit, quality_score, sector, post_title, \
           price_at_signal, price_1h, price_4h, price_1d, \
           max_gain_pct, max_loss_pct \
    FROM signal_archive \
    WHERE price_1d IS NOT NULL AND stance IN ('bullish','bearish') \
  )
/* NOTE: archive has unqualified cols, live has s./sp. prefixed */
/* NOTE: stance IN ('bullish','bearish') = tradeable only */

/* ── COMMON QUERY PATTERNS ── */
#define Q_PERF_SUMMARY \
  SELECT COUNT(*) total, SUM(WIN_CASE(sp.price_1d)) wins, SUM(LOSS_CASE(sp.price_1d)) losses \
  FROM _unified WHERE created_at > ? /* uses UNIFIED_CTE */

#define Q_ACCURACY_BY_CONF \
  SELECT ROUND(confidence,1) bucket, COUNT(*) n, \
    SUM(A_WIN(price_1d)) wins, SUM(A_LOSS(price_1d)) losses \
  FROM _unified GROUP BY bucket /* confidence calibration */

#define Q_STRATEGY_PNL \
  SELECT strategy, COUNT(*) n, SUM(A_WIN(price_1d)) w, SUM(A_LOSS(price_1d)) l, \
    AVG(CASE WHEN stance='bullish' THEN (price_1d-price_at_signal)/price_at_signal*100 \
             WHEN stance='bearish' THEN (price_at_signal-price_1d)/price_at_signal*100 END) avg_pnl \
  FROM _unified GROUP BY strategy

#define Q_BACKTEST \
  SELECT * FROM _unified WHERE created_at BETWEEN ? AND ? ORDER BY created_at
  /* backtest engine uses this to fetch signal history */

#define Q_TICKER_PERF \
  SELECT ticker, COUNT(*) n, SUM(A_WIN(price_1d)) w, SUM(A_LOSS(price_1d)) l \
  FROM _unified GROUP BY ticker ORDER BY n DESC

/* ── INDEX REFERENCE ── */
/* signals: ticker, created_at DESC, confidence DESC, stance, (post_url,ticker,created_at), event_type, strategy, (created_at DESC,ticker), sector, sarcasm_score, conviction, nlp_polarity */
/* signal_performance: signal_id, ticker, checked_at */
/* signal_archive: created_at DESC, ticker, event_type, stance, strategy, subreddit */
/* users: api_key_hash, email */
/* unusual_events: ticker, event_type, detected_at DESC, score DESC, signal_id */
/* backtest_runs: (user_id, created_at DESC) */
/* backtest_strategies: (user_id, is_active, created_at DESC) */
/* congress_trades: ticker, filed_at DESC, politician */
/* macro_events: scheduled_at, (event_type,scheduled_at), category, importance */
/* earnings_events: (ticker,report_date), report_date */
/* insider_trades: (ticker,filing_date DESC), (source,filing_date DESC), value DESC, trade_type */
/* trading_agents: user_id, status */
/* agent_trades: agent_id, user_id, status, created_at DESC */
