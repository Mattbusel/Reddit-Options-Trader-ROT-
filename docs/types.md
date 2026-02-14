# Data Types & Models — ROT Architecture Reference

> Part of the ROT documentation suite. See [CLAUDE.md](../CLAUDE.md) for the full index.

## Quick Start for Agents

- Key file(s): `src/rot/core/types.py` (pipeline types), `src/rot/nlp/types.py` (NLP types)
- Key pattern: Frozen dataclasses throughout. All types are immutable. Complex data stored as JSON blobs in SQLite.
- Additional type files: `src/rot/backtest/config.py`, `src/rot/backtest/result.py`, `src/rot/unusual/types.py`, `src/rot/analysis/sector_types.py`, `src/rot/analysis/correlation_types.py`, `src/rot/export/types.py`

---

## Core Pipeline Types (`src/rot/core/types.py`)

### Post -- Reddit post snapshot

| Field | Type | Description |
|-------|------|-------------|
| id | str | Post ID |
| created_utc | float | Unix timestamp |
| subreddit | str | Source subreddit |
| title | str | Post title |
| selftext | str | Post body text |
| url | str | Post URL |
| score | int | Upvote score |
| num_comments | int | Comment count |
| upvote_ratio | float | Upvote ratio (0-1) |
| author | str | Author username |
| permalink | str | Reddit permalink |
| flair | str | Post flair |
| is_crosspost | bool | Whether post is a crosspost |

### Comment -- Reddit comment

| Field | Type | Description |
|-------|------|-------------|
| id | str | Comment ID |
| created_utc | float | Unix timestamp |
| author | str | Author username |
| body | str | Comment text |
| score | int | Upvote score |

### ThreadSnapshot -- Post + comments at a point in time

| Field | Type | Description |
|-------|------|-------------|
| snapshot_ts | float | Snapshot timestamp |
| post | Post | The post |
| top_comments | List[Comment] | Top comments |

### TrendCandidate -- Trending post with trend metrics

| Field | Type | Description |
|-------|------|-------------|
| key | str | Unique key |
| window_s | int | Window size in seconds |
| features | Dict[str, float] | Trend feature values |
| trend_score | float | Computed trend score |
| reason | str | Why this is trending |
| snapshot | ThreadSnapshot | Source snapshot |

### Event -- Classified market event

| Field | Type | Description |
|-------|------|-------------|
| event_type | str | One of 6 EventTypes (see below) |
| entities | List[str] | Ticker symbols |
| stance | str | bullish / bearish / mixed / unknown |
| time_horizon | str | intraday / 1w / earnings / longer / unknown |
| evidence | str | Supporting text |
| confidence | float | 0.0-1.0 after credibility scoring |
| meta | Dict | NLP data, market data, post metadata |

**EventType values:** `earnings_rumor`, `product_news`, `regulatory`, `squeeze_chatter`, `macro`, `other`

**Stance values:** `bullish`, `bearish`, `mixed`, `unknown`

**Horizon values:** `intraday`, `1w`, `earnings`, `longer`, `unknown`

### ReasoningPacket -- LLM analysis output

| Field | Type | Description |
|-------|------|-------------|
| thesis | str | Trade thesis |
| catalyst_window | str | Expected catalyst timeframe |
| market_expectation | str | Market expectation description |
| invalidations | List[str] | What would invalidate the thesis |
| recommended_structures | List[str] | Suggested option structures |
| risk_notes | List[str] | Risk factors |
| raw | Dict | Raw LLM response |

### TradeIdea -- Complete trade recommendation

| Field | Type | Description |
|-------|------|-------------|
| underlying | str | Ticker symbol |
| strategy | str | One of 7 strategy types (see below) |
| legs | List[OptionLeg] | Option legs |
| max_loss | float | Maximum loss |
| thesis | str | Trade thesis |
| time_stop | str | Time-based exit |
| quality_score | float | 0.0-1.0 quality rating |
| do_not_trade_reasons | List[str] | Reasons to avoid |
| meta | Dict | Additional metadata |

**Strategy values:** `debit_spread`, `credit_spread`, `iron_condor`, `calendar`, `straddle`, `strangle`, `none`

### OptionLeg -- Single options leg

| Field | Type | Description |
|-------|------|-------------|
| side | str | buy / sell |
| kind | str | call / put |
| strike | float | Strike price |
| expiry | str | Expiration date |
| qty | int | Quantity |

---

## NLP Types (`src/rot/nlp/types.py`)

### NLPResult -- Master NLP output

| Field | Type | Description |
|-------|------|-------------|
| sentiment | SentimentResult | Sentiment analysis |
| entities | List[ResolvedEntity] | Resolved ticker entities |
| options_entities | List[OptionsEntity] | Options contract entities |
| positions | List[PositionEntity] | Position entities |
| classifications | List[ClassifiedEvent] | Event classifications |
| temporal | TemporalResult | Temporal analysis |
| thread | ThreadResult | Thread consensus |
| ticker_symbols | List[str] | Extracted tickers |
| primary_stance | str | Overall stance |
| primary_event_type | str | Top event classification |
| token_count | int | Number of tokens |
| processing_time_ms | float | Processing duration |

### SentimentResult -- Sentiment analysis

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| polarity | float | -1 to +1 | Sentiment direction |
| intensity | float | 0-1 | Signal strength |
| conviction | float | 0-1 | Author certainty |
| sarcasm_probability | float | 0-1 | Sarcasm likelihood |
| raw_signals | List[SentimentSignal] | -- | Individual signal components |
| bullish_count | int | -- | Number of bullish signals |
| bearish_count | int | -- | Number of bearish signals |
| negated_count | int | -- | Number of negated signals |

### ResolvedEntity -- Ticker/financial entity

| Field | Type | Description |
|-------|------|-------------|
| symbol | str | Ticker symbol |
| raw_text | str | Original text that matched |
| resolution_method | str | cashtag / bare_ticker / implicit / sector / alias |
| confidence | float | 0-1, resolution confidence |
| span | Tuple[int,int] | Character span in source |
| sentiment_toward | str/None | bullish / bearish / None |

### ClassifiedEvent -- Event category with confidence

| Field | Type | Description |
|-------|------|-------------|
| category | str | One of 14 category types |
| confidence | float | 0-1, classification confidence |
| evidence_spans | List[str] | Supporting text spans |
| matched_terms | List[str] | Terms that triggered this classification |

### TemporalResult -- Time analysis

| Field | Type | Description |
|-------|------|-------------|
| dominant_tense | str | past / present / future / unknown |
| actionability | float | 0-1, how actionable the signal is |
| urgency | float | 0-1, urgency score |
| time_expressions | List[str] | Extracted time phrases |
| tense_signals | List | Individual tense signal components |

### ThreadResult -- Comment consensus

| Field | Type | Description |
|-------|------|-------------|
| consensus_polarity | float | -1 to +1, overall comment sentiment |
| consensus_score | float | 0-1, how much comments agree |
| agreement_with_op | float | 0-1, comment alignment with OP |
| contrarian_detected | bool | Top comment disagrees with OP |
| top_comment_aligns | bool/None | Whether top comment aligns with OP |
| comment_count_analyzed | int | Number of comments analyzed |
| comment_analyses | List[CommentAnalysis] | Per-comment analysis results |

---

## Backtest Types (`src/rot/backtest/`)

### BacktestConfig (`config.py`)

Portfolio settings, exit rules, signal filters. Frozen dataclass with serialization (`to_dict()` / `from_dict()`).

### BacktestResult (`result.py`)

Contains: total_trades, win_rate, total_return, sharpe_ratio, max_drawdown, equity_curve, trade_log, monthly_returns.

### TradeRecord (`result.py`)

Individual trade: ticker, entry/exit price, pnl_pct, stance, confidence, entry/exit time.

### EquityPoint (`result.py`)

Equity curve point: timestamp, equity value.

### DrawdownPeriod (`result.py`)

Drawdown: start/end time, depth, recovery time.

---

## Analytics Types

### Unusual Activity (`src/rot/unusual/types.py`)

| Type | Fields |
|------|--------|
| UnusualEvent | ticker, event_type (iv_spike/volume_surge/oi_surge/skew_shift/sweep), score, details, signal_id, detected_at |
| UnusualScore | iv_rank, volume_zscore, oi_change_pct, skew_zscore, composite (0-100) |
| UnusualSummary | total_events, by_type counts, top tickers |

### Sector Rotation (`src/rot/analysis/sector_types.py`)

| Type | Fields |
|------|--------|
| SectorMomentum | sector, momentum_score, signal_count, avg_confidence, win_rate |
| RotationEvent | from_sector, to_sector, strength, detected_at |
| SectorRanking | sector, rank, score, trend (improving/declining/stable) |
| CapitalFlow | sector, inflow_signals, outflow_signals, net_flow |

### Correlation (`src/rot/analysis/correlation_types.py`)

| Type | Fields |
|------|--------|
| CorrelationPair | ticker_a, ticker_b, correlation, co_fire_count, window |
| TickerCluster | cluster_id, tickers, avg_correlation |
| LeadLagPair | leader, follower, lag_hours, correlation |
| NetworkGraph | nodes (tickers), edges (correlations), clusters |

### Enterprise Export (`src/rot/export/types.py`)

| Type | Fields |
|------|--------|
| ExportJob | id, user_id, format, filters, created_at, status |
| ExportResult | job_id, file_path, row_count, file_size |
| SignalLineage | signal_id, steps (ordered provenance chain) |
| LineageStep | stage, timestamp, details |
| ScheduleConfig | frequency (daily/weekly), format, filters |
