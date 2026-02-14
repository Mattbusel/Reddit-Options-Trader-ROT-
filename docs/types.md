<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Data Types

- **Files**: `src/rot/core/types.py`, `src/rot/nlp/types.py`, `src/rot/backtest/{config,result}.py`, `src/rot/unusual/types.py`, `src/rot/analysis/{sector,correlation}_types.py`, `src/rot/export/types.py`
- **Pattern**: Frozen dataclasses, immutable. Complex data stored as JSON blobs in SQLite.

## Core Pipeline (`core/types.py`)

**Post**: id, created_utc, subreddit, title, selftext, url, score, num_comments, upvote_ratio, author, permalink, flair, is_crosspost

**Comment**: id, created_utc, author, body, score

**ThreadSnapshot**: snapshot_ts, post (Post), top_comments (List[Comment])

**TrendCandidate**: key, window_s, features (Dict[str,float]), trend_score, reason, snapshot (ThreadSnapshot)

**Event**: event_type, entities (List[str]), stance, time_horizon, evidence, confidence (0-1), meta (Dict)
- EventType: `earnings_rumor|product_news|regulatory|squeeze_chatter|macro|other`
- Stance: `bullish|bearish|mixed|unknown`
- Horizon: `intraday|1w|earnings|longer|unknown`

**ReasoningPacket**: thesis, catalyst_window, market_expectation, invalidations (List[str]), recommended_structures (List[str]), risk_notes (List[str]), raw (Dict)

**TradeIdea**: underlying, strategy, legs (List[OptionLeg]), max_loss, thesis, time_stop, quality_score (0-1), do_not_trade_reasons (List[str]), meta (Dict)
- Strategy: `debit_spread|credit_spread|iron_condor|calendar|straddle|strangle|none`

**OptionLeg**: side (buy/sell), kind (call/put), strike, expiry, qty

## NLP Types (`nlp/types.py`)

**NLPResult**: sentiment, entities, options_entities, positions, classifications, temporal, thread, ticker_symbols, primary_stance, primary_event_type, token_count, processing_time_ms

**SentimentResult**: polarity (-1..+1), intensity (0-1), conviction (0-1), sarcasm_probability (0-1), raw_signals, bullish_count, bearish_count, negated_count

**ResolvedEntity**: symbol, raw_text, resolution_method (cashtag/bare_ticker/implicit/sector/alias), confidence (0-1), span, sentiment_toward

**ClassifiedEvent**: category (14 types), confidence (0-1), evidence_spans, matched_terms

**TemporalResult**: dominant_tense (past/present/future/unknown), actionability (0-1), urgency (0-1), time_expressions, tense_signals

**ThreadResult**: consensus_polarity (-1..+1), consensus_score (0-1), agreement_with_op (0-1), contrarian_detected, top_comment_aligns, comment_count_analyzed, comment_analyses

## Backtest Types (`backtest/`)
- **BacktestConfig** (config.py): portfolio settings, exit rules, signal filters. `to_dict()`/`from_dict()`
- **BacktestResult** (result.py): total_trades, win_rate, total_return, sharpe_ratio, max_drawdown, equity_curve, trade_log, monthly_returns
- **TradeRecord**: ticker, entry/exit price, pnl_pct, stance, confidence, entry/exit time
- **EquityPoint**: timestamp, equity value
- **DrawdownPeriod**: start/end time, depth, recovery time

## Analytics Types
| Module | Type | Key Fields |
|--------|------|------------|
| `unusual/types.py` | UnusualEvent | ticker, event_type (iv_spike/volume_surge/oi_surge/skew_shift/sweep), score, details, signal_id, detected_at |
| | UnusualScore | iv_rank, volume_zscore, oi_change_pct, skew_zscore, composite (0-100) |
| | UnusualSummary | total_events, by_type counts, top tickers |
| `analysis/sector_types.py` | SectorMomentum | sector, momentum_score, signal_count, avg_confidence, win_rate |
| | RotationEvent | from_sector, to_sector, strength, detected_at |
| | SectorRanking | sector, rank, score, trend |
| | CapitalFlow | sector, inflow_signals, outflow_signals, net_flow |
| `analysis/correlation_types.py` | CorrelationPair | ticker_a, ticker_b, correlation, co_fire_count, window |
| | TickerCluster | cluster_id, tickers, avg_correlation |
| | LeadLagPair | leader, follower, lag_hours, correlation |
| | NetworkGraph | nodes, edges, clusters |
| `export/types.py` | ExportJob | id, user_id, format, filters, created_at, status |
| | ExportResult | job_id, file_path, row_count, file_size |
| | SignalLineage | signal_id, steps (ordered provenance) |
| | LineageStep | stage, timestamp, details |
| | ScheduleConfig | frequency (daily/weekly), format, filters |
