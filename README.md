# Reddit Options Trader (ROT)

[![CI](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/ci.yml/badge.svg)](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/ci.yml)
[![Tests](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/tests.yml/badge.svg)](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/tests.yml)
[![Security](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/security.yml/badge.svg)](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/actions/workflows/security.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Coverage: 75%+](https://img.shields.io/badge/coverage-75%25%2B-brightgreen)]()
[![CodeQL: 0 alerts](https://img.shields.io/badge/CodeQL-0%20alerts-brightgreen)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> **IMPORTANT DISCLAIMER -- READ BEFORE PROCEEDING**
>
> ROT is a **research and educational tool only**. It is a signal intelligence platform, **not** a trading execution engine. Nothing in this repository constitutes financial advice, investment advice, or a recommendation to buy or sell any security or derivative. Options trading carries significant financial risk -- you can lose 100% of the premium paid. Signal scores and trade ideas are experimental and have not been independently validated. **Never risk capital you cannot afford to lose.** The authors accept no liability for financial losses arising from use of this software.

---

## Round 4 Features

### Options Position Tracker (`src/rot/portfolio/positions.py`)

Provides an in-memory ledger for multi-leg options positions with mark-to-market updates, portfolio Greeks aggregation, and expiry-risk detection.

| Class / Type | Role |
|---|---|
| `OptionLeg` | One contract leg: `contract`, `side` (Long/Short), `strike`, `expiry`, `premium`, `quantity`, Greeks |
| `OptionsPosition` | Full position: `symbol`, `strategy`, `legs`, `entry_cost`, `current_value`, `theta_decay` |
| `PositionTracker` | Ledger: `add_position`, `close_position`, `mark_to_market`, `positions_at_risk`, `portfolio_greeks` |
| `PortfolioGreeks` | Aggregated `total_delta`, `total_gamma`, `total_theta`, `total_vega` |
| `render_positions_page` | Renders `GET /portfolio/positions` as a dark-themed HTML page with position cards |

Delta-adjusted PnL: `realized_pnl + unrealized_pnl + theta_decay_collected`.

### Discord Webhook Notifier (`src/rot/notifications/discord.py`)

Extends the existing `DiscordNotifier` with alert levels, three new send methods, and a token-bucket rate limiter (max 5 msg/5 s).

| Feature | Detail |
|---|---|
| `AlertLevel` | `INFO` (blue), `WARNING` (yellow), `CRITICAL` (red) — colour-coded embeds |
| `send_signal_alert(signal, ticker, confidence)` | Rich embed with signal name, ticker, confidence, and severity |
| `send_position_alert(position, alert_type)` | Expiry warnings, loss alerts with position Greeks and PnL |
| `send_daily_summary(portfolio_greeks, daily_pnl)` | End-of-day recap with full Greek snapshot |
| Rate limiting | Token bucket: 5 messages per 5 seconds; excess messages dropped gracefully |
| Graceful no-op | Raises `ValueError` at construction if no webhook URL is configured |

```python
import asyncio
from rot.notifications.discord import DiscordNotifier, AlertLevel

notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/...")
asyncio.run(notifier.send_signal_alert(
    signal="bull_call_spread",
    ticker="AAPL",
    confidence=0.82,
    level=AlertLevel.INFO,
))
```

---

## What is ROT?

ROT is a full-stack financial intelligence platform that watches Reddit discussions and institutional RSS feeds in real time, passes every post through a 9-stage ML/NLP pipeline, scores its credibility with a gradient-boosting model, optionally augments reasoning with an LLM, and surfaces the result as a structured options trade idea -- complete with strike selection, expiry heuristics, max-loss calculation, and a full provenance audit trail. The web dashboard streams signals live via WebSocket, while the broker integration layer lets you route approved ideas directly to an Alpaca paper-trading account with one configuration change. ROT tells you what the crowd is reacting to before price fully reacts; what you do with that information is entirely your responsibility.

**Live deployment:** [rot.up.railway.app](https://web-production-71423.up.railway.app/)

---

## 5-Minute Quickstart

### Option A -- Docker (recommended)

```bash
git clone https://github.com/Mattbusel/Reddit-Options-Trader-ROT-.git
cd Reddit-Options-Trader-ROT-

# 1. Copy the environment template
cp .env.example .env

# 2. Open .env and set at minimum:
#    ROT_REDDIT_CLIENT_ID, ROT_REDDIT_CLIENT_SECRET
#    (everything else has sensible defaults -- LLM key is optional)

# 3. Build and start
docker compose up --build

# Dashboard:   http://localhost:8000/dashboard
# API docs:    http://localhost:8000/docs
# Health:      http://localhost:8000/api/health
```

You will see signals appearing on the dashboard within seconds once the Reddit
poller starts. No LLM key is required; the system runs in stub-reasoning mode
and still generates trade ideas.

### Option B -- Manual (virtualenv)

```bash
git clone https://github.com/Mattbusel/Reddit-Options-Trader-ROT-.git
cd Reddit-Options-Trader-ROT-

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"

cp .env.example .env
# Edit .env -- see Configuration Guide below

# Start the full web server
python -m rot.app.server

# Or run a standalone pipeline loop (no web server)
python -m rot.app.loop

# Or run a single pipeline pass and print results
python -m rot.app.main
```

---

## Round 3 Features

### IV Rank Calculator (`src/rot/analytics/iv_rank.py`)

`IVRankCalculator` fetches the live options chain via yfinance and inverts ATM option prices to implied volatility using Newton-Raphson Black-Scholes-Merton inversion. It then computes IV rank and IV percentile from a rolling 252-day IV history derived from realized volatility.

| Class / Type | Role |
|---|---|
| `IVRankCalculator` | Orchestrates fetch, inversion, and rank computation |
| `IVData` | Output: symbol, current_iv, iv_52w_high/low, iv_rank, iv_percentile, iv_mean_30d, classification |
| `IVRegime` | `IV_CRUSH_ZONE` (rank>80), `NORMAL` (20-80), `IV_EXPANSION_ZONE` (rank<20) |

```python
from rot.analytics.iv_rank import IVRankCalculator

calc = IVRankCalculator(risk_free_rate=0.05)
data = calc.analyze("AAPL")

print(data.iv_rank)          # e.g. 63.4
print(data.iv_percentile)    # e.g. 58.7
print(data.classification)   # IVRegime.NORMAL

# Batch mode
results = calc.analyze_batch(["AAPL", "TSLA", "SPY"])
```

IV rank formula: `iv_rank = (current_iv - iv_52w_low) / (iv_52w_high - iv_52w_low) * 100`

The Newton-Raphson BSM inversion converges in fewer than 10 iterations for typical market prices. ATM calls within 4 strikes of spot are used; the median IV is returned. Falls back to yfinance's own `impliedVolatility` field if inversion fails.

---

### Strategy Screener (`src/rot/screener.py`)

`StrategyScreener` scans a watchlist for five options strategies, scores each candidate by a weighted combination of IV rank (40 %), volume (20 %), open interest (20 %), and edge estimate (20 %), and returns results sorted by score descending.

| Class / Type | Role |
|---|---|
| `StrategyScreener` | Main scanner: `scan(watchlist, criteria)`, `scan_top(watchlist, criteria, top_n)` |
| `ScreenCriteria` | Filter: min/max IV rank, min volume, min OI, min/max DTE |
| `ScreenResult` | Output: symbol, strategy, score (0–100), details dict |
| `Strategy` | `CoveredCall`, `CashSecuredPut`, `IronCondor`, `BullPutSpread`, `BearCallSpread` |

```python
from rot.screener import StrategyScreener, ScreenCriteria

screener = StrategyScreener()
criteria = ScreenCriteria(
    min_iv_rank=40.0,       # only sell premium when IV rank >= 40
    max_iv_rank=90.0,
    min_volume=100,
    min_open_interest=500,
    min_days_to_expiry=14,
    max_days_to_expiry=60,
)

results = screener.scan(["AAPL", "TSLA", "SPY", "QQQ"], criteria)
for r in results[:5]:
    print(f"{r.symbol:6} {r.strategy.value:20} score={r.score:.1f}  "
          f"iv_rank={r.details['iv_rank']}")
```

`IronCondor` scoring penalises IV rank below 50 because the strategy needs rich premium on both wings. `BullPutSpread` and `BearCallSpread` apply a floor boost so they surface in moderate-IV environments too.

---

## Architecture

### 9-Stage Signal Pipeline

```
+------------------------------------------------------------------+
|                      ROT SIGNAL PIPELINE                         |
+------------------------------------------------------------------+
|                                                                  |
|  Stage 1: INGESTION                                              |
|  Reddit PRAW streaming + 13 RSS feeds (SEC 8-K, Reuters, FDA)   |
|     |                                                            |
|     v                                                            |
|  Stage 2: TREND DETECTION                                        |
|  Velocity scoring, dedup, memory-bounded ring buffer (2k items)  |
|     |                                                            |
|     v                                                            |
|  Stage 3: NLP ENGINE (10 modules)                                |
|  Tokeniser -> Lexicon -> Entity -> Sentiment -> Sarcasm ->       |
|  Conviction -> Temporal -> Thread Analysis -> ...                |
|     |                                                            |
|     v                                                            |
|  Stage 4: EVENT BUILDER                                          |
|  Dual-path NLP/regex event classification, ticker extraction      |
|     |                                                            |
|     v                                                            |
|  Stage 5: MARKET ENRICHMENT                                      |
|  Market-cap filter, options liquidity gate, price fetch          |
|     |                                                            |
|     v                                                            |
|  Stage 6: CREDIBILITY SCORING                                    |
|  GradientBoosting ML scorer + 12 heuristic factors -> [0, 1]    |
|     |                                                            |
|     v                                                            |
|  Stage 7: FEEDBACK SUPPRESSION                                   |
|  Dedup, cooldown, pump-dump / manipulation filter                |
|     |                                                            |
|     v                                                            |
|  Stage 8: LLM REASONING                                          |
|  OpenAI / Anthropic / DeepSeek -- circuit breaker + stub mode   |
|     |                                                            |
|     v                                                            |
|  Stage 9: TRADE IDEA GENERATION                                  |
|  Bull call spreads / bear put spreads / straddles                |
|  ATM +/- 5% strikes, weekly/monthly expiry heuristics           |
|                                                                  |
+------------------------------------------------------------------+
          |                   |                    |
    [Dashboard]         [API /signals]       [Lineage DB]
    WebSocket           REST + auth          Full audit trail
```

### Module Layout

```
src/rot/
  app/           Server, pipeline runner, background loops
  ingest/        Reddit + RSS ingestion (7 modules)
  trend/         Trend detection and ranking
  nlp/           10-module NLP pipeline (500+ lexicon terms)
  extract/       Event builder (dual-path NLP/regex)
  market/        Trade builder, enrichment, validation, microstructure, vol surface
  credibility/   ML scorer + 12 heuristics
  reasoner/      LLM reasoning with circuit breaker
  storage/       33+ tables, 16 DB mixins, migrations
  web/           FastAPI routes, auth, middleware, Jinja2 templates
  strategy/      ML, genetic, regime detection, marketplace, position sizing
  social/        Manipulation detection, propagation, network analysis
  flow/          Options flow intelligence, Greek calculations
  backtest/      Monte Carlo, walk-forward, strategy backtester, 13 modules
  macro/         FOMC, earnings, seasonal patterns, insider activity
  alerts/        Discord, email, Twitter, webhook dispatch
  agents/        Autonomous trading agents (safety rails)
  gamification/  Badges, leaderboards, progression system
  export/        Enterprise exports, 9-step data lineage
  lineage/       Signal provenance audit trail (SQLite-backed)
  brokers/       Broker integration: Alpaca paper trading + mock
  risk/          Portfolio-level Greeks and concentration limits
  core/          Config, types, structured logging, sanitization
  affiliates/    Affiliate tracking
  sports/        Sports event correlation
  analysis/      Sector and correlation analysis

tests/           205 files, 95,000+ lines, 7,060+ test functions
```

---

## Signal Quality Explained

Every signal carries a **credibility score** in the range [0.0, 1.0]. The score
is the output of a GradientBoosting classifier trained on 12 heuristic features.
It is NOT a prediction of whether a trade will be profitable. It measures how
trustworthy the underlying Reddit/RSS signal is as a genuine market-moving event.

| Score range | Interpretation |
|---|---|
| 0.80 -- 1.00 | Institutional source (SEC 8-K, FDA press release) or high-quality DD post with strong engagement and single-ticker focus |
| 0.60 -- 0.79 | Credible discussion thread with reasonable engagement; may still be speculative |
| 0.40 -- 0.59 | Moderate quality; noise is present; treat with caution |
| 0.00 -- 0.39 | Low credibility: cross-post, penny stock subreddit, low engagement, or manipulation signals detected |

**Factor breakdown** (applied additively to base confidence):

| Factor | Effect |
|---|---|
| Institutional RSS source (SEC 8-K, FDA, Fed) | +0.15 |
| DD flair on Reddit post | +0.10 |
| Subreddit quality (r/options, r/investing) | +0.05 |
| Subreddit quality (r/wallstreetbets) | -0.05 |
| High engagement score (>500 upvotes) | up to +0.10 |
| Comment depth (>50 comments) | up to +0.05 |
| Cross-post penalty | -0.05 |
| Upvote ratio >0.90 | +0.05 |
| Single-ticker focus | +0.05 |
| New account (<30 days old) | -0.10 |
| Pump-dump language detected | -0.15 |
| Award presence | +0.03 |

The ML scorer supplements these heuristics with learned feature interactions and
is retrained periodically on labelled signal outcomes.

---

## Round 2 Feature Additions

### Market Microstructure Analysis (`rot.market.microstructure`)

Five components that quantify execution quality and market structure:

| Class | Description |
|---|---|
| `BidAskSpreadAnalyzer` | Estimates effective spread (Roll 1984 / Glosten-Milgrom) from trade data or options chain |
| `OrderImbalanceDetector` | Computes net buy/sell imbalance ratio; flags when threshold is breached |
| `PriceDiscoveryMetric` | Cross-correlates Reddit sentiment vs returns across ±N lags to detect lead/lag |
| `MarketImpactEstimator` | OLS regression of price changes on signed order flow (Kyle 1985 lambda) |
| `LiquidityScore` | Composite 0-1 score from weighted spread + OI depth + daily turnover |

### Volatility Surface Modelling (`rot.market.vol_surface`)

Full IV surface pipeline for options strategy selection:

| Class | Description |
|---|---|
| `VolatilitySmile` | Fits smile (IV vs strike) for a single expiry; extracts skew and wing spread |
| `ImpliedVolatilitySurface` | Builds full strike × expiry IV matrix from raw options chain data |
| `IVRank` | IV rank: `(current - 52w_low) / (52w_high - 52w_low)` in [0, 1] |
| `IVPercentile` | Fraction of historical days with IV below current (uses full distribution) |
| `TermStructure` | ATM IV by expiry; classifies contango vs backwardation with linear slope |
| `VolatilityRegime` | High / normal / low regime with `sell_premium` / `buy_premium` / `neutral` bias |

### Position Sizing Engine (`rot.strategy.position_sizing`)

Multiple sizing methods composable into a single recommendation:

| Class | Description |
|---|---|
| `KellyCriterion` | Full Kelly: `f* = (p*b - q) / b` with configurable max-fraction cap |
| `FractionalKelly` | Half-Kelly, quarter-Kelly, or any fraction of the full Kelly bet |
| `VolatilityScaledSizing` | Target-volatility sizing: position scales inversely to realized vol |
| `MaxLossSizing` | Sizes so the worst-case loss stays within a portfolio-risk-pct budget |
| `PositionSizingEngine` | Blends all methods via `min` / `mean` / `weighted`; applies confidence scaling |

### Strategy Backtester (`rot.backtest.strategy_backtest`)

High-level backtesting layer on top of the core `BacktestEngine`:

| Class | Description |
|---|---|
| `SignalHistoryLoader` | Loads signals from in-memory list or SQLite DB with chainable `filter()` |
| `BacktestMetrics` | Sharpe, Sortino, Calmar, max drawdown, win rate, avg P&L, best/worst trade |
| `WalkForwardTester` | Configurable N-fold IS/OOS testing; returns stability score |
| `MonteCarloSimulator` | Bootstraps signal order (500+ runs); computes p-value and ruin probability |
| `StrategyBacktester` | Orchestrator: loads → backtests → walk-forward → Monte Carlo → HTML report |

The HTML report includes an inline SVG equity curve, walk-forward fold table, Monte Carlo percentile grid, and a full trade log.

---

## Configuration Guide

All environment variables are optional unless marked **required**.

### Reddit ingestion

| Variable | Default | Description |
|---|---|---|
| `ROT_REDDIT_CLIENT_ID` | `""` | **Required for Reddit.** Reddit API client ID |
| `ROT_REDDIT_CLIENT_SECRET` | `""` | **Required for Reddit.** Reddit API client secret |
| `ROT_REDDIT_USER_AGENT` | `rot:v1 (by u_rotbot)` | Reddit API user-agent |
| `ROT_REDDIT_SUBREDDITS` | `wallstreetbets,stocks,options` | Comma-separated subreddit list |
| `ROT_REDDIT_LISTING` | `hot` | Feed type: `hot`, `new`, `rising`, `top` |
| `ROT_REDDIT_LIMIT_PER_SUB` | `50` | Posts per subreddit per poll |
| `ROT_REDDIT_POLL_INTERVAL_S` | `20` | Poll interval in seconds |

### LLM reasoning

| Variable | Default | Description |
|---|---|---|
| `ROT_LLM_PROVIDER` | `openai` | Provider: `openai`, `anthropic`, `deepseek` |
| `ROT_LLM_API_KEY` | `""` | LLM API key. Leave empty to run stub mode |
| `ROT_LLM_MODEL` | `gpt-4o-mini` | Model name |
| `ROT_LLM_MAX_TOKENS` | `1024` | Max response tokens |
| `ROT_LLM_TEMPERATURE` | `0.3` | Sampling temperature |

### RSS, market data, and pipeline

| Variable | Default | Description |
|---|---|---|
| `ROT_RSS_ENABLED` | `false` | Enable RSS feed ingestion |
| `ROT_MARKET_MIN_MARKET_CAP` | `100000000` | Minimum market cap filter ($100M) |
| `ROT_MARKET_CACHE_TTL_S` | `3600` | Market data cache TTL in seconds |
| `ROT_TREND_WINDOW_S` | `1800` | Trend detection window in seconds |
| `ROT_TREND_THRESHOLD` | `0.01` | Trend score threshold |

### Infrastructure

| Variable | Default | Description |
|---|---|---|
| `ROT_ALERT_DISCORD_WEBHOOK_URL` | `""` | Discord webhook URL for alerts |
| `ROT_STORAGE_ROOT` | `./data` | Path for SQLite databases and state files |
| `ROT_SECRET_KEY` | auto-generated | HMAC secret for CSRF and session signing |

### Broker integration

| Variable | Default | Description |
|---|---|---|
| `ALPACA_API_KEY` | `""` | Alpaca API key ID |
| `ALPACA_SECRET_KEY` | `""` | Alpaca API secret key |
| `ALPACA_PAPER` | `true` | Set to `false` to use live endpoint (dangerous!) |

### Billing

| Variable | Default | Description |
|---|---|---|
| `STRIPE_SECRET_KEY` | `""` | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | `""` | Stripe webhook signing secret |

---

## Options Chain Integration

ROT enriches every trade idea with live options chain data from Yahoo Finance
(no API key required).  Two modules handle this:

### `rot.options.chain` -- Core chain fetcher and enricher

```python
from rot.options.chain import OptionsChainFetcher, TradeIdeaEnricher

# Fetch the best-liquidity chain for a ticker
fetcher = OptionsChainFetcher(min_open_interest=100)
chain = fetcher.fetch("NVDA", direction="bullish", dte_min=7, dte_max=60)

if chain:
    print(f"Expiry: {chain.expiry}")
    print(f"Underlying: ${chain.underlying_price:.2f}")
    best_call = chain.best_call(delta_target=0.40)
    if best_call:
        print(f"Best call: ${best_call.strike} @ ${best_call.ask:.2f} bid/ask "
              f"IV={best_call.iv:.1%} OI={best_call.open_interest}")
```

### Enriching a trade idea dict

```python
enricher = TradeIdeaEnricher(fetcher)
result = enricher.enrich_dict({
    "underlying": "NVDA",
    "strategy": "debit_spread",
    "stance": "bullish",
})
enriched = result["enriched"]
print(f"Long strike:  ${enriched['long_strike']}")
print(f"Short strike: ${enriched['short_strike']}")
print(f"Cost (debit): ${enriched['cost_estimate_usd']:.2f} per contract")
print(f"Max loss:     ${enriched['max_loss_usd']:.2f}")
print(f"Max profit:   ${enriched['max_profit_usd']:.2f}")
print(f"IV rank:      {enriched['iv_rank']:.1f}")
```

### Example enriched output

```json
{
  "underlying": "NVDA",
  "strategy": "debit_spread",
  "stance": "bullish",
  "enriched": {
    "selected_expiry": "2026-04-17",
    "underlying_price": 875.50,
    "long_strike": 875.0,
    "short_strike": 920.0,
    "long_premium": 18.40,
    "short_premium": 7.20,
    "cost_estimate_usd": 1120.00,
    "max_loss_usd": 1120.00,
    "max_profit_usd": 3380.00,
    "long_iv": 0.4231,
    "long_delta": 0.412,
    "iv_rank": 68.4,
    "chain_fetched_at": "2026-03-22T10:30:00+00:00",
    "enrichment_status": "ok"
  }
}
```

### `rot.options.live_chain` -- Single-contract best-fit finder

```python
from rot.options.live_chain import LiveOptionsChain

chain = LiveOptionsChain("AAPL")
analysis = chain.best_contract(
    direction="bearish",
    dte_min=14,
    dte_max=45,
    delta_target=0.35,
    min_open_interest=200,
)
print(analysis.to_dict())
```

---

## Signal Quality Dashboard

The Signal Quality Dashboard at `/signal-quality` (Pro+ tier) shows:

- **Category Performance Heatmap** -- win rate by event type and stance
- **Source Reliability** -- per-source win rate and average confidence
- **ML Feature Importance** -- top 10 features driving the credibility score
- **Quality Trend** -- rolling accuracy over time
- **Suppression Candidates** -- sources consistently producing false signals
- **Confidence Calibration** -- predicted confidence vs actual accuracy curves

### Signal Quality API

**Endpoint:** `GET /api/v1/signals/quality`

**Tier gate:** Pro and above.

```bash
curl -H "Authorization: Bearer YOUR_JWT" \
     https://rot.up.railway.app/api/v1/signals/quality
```

**Response (SignalQualityReport):**

```json
{
  "total_signals": 412,
  "decided_signals": 318,
  "accuracy_pct": 61.3,
  "avg_return_if_followed": 2.14,
  "top_tickers": [
    {"ticker": "NVDA", "win_rate": 0.78, "count": 23},
    {"ticker": "MSFT", "win_rate": 0.71, "count": 17}
  ],
  "worst_tickers": [
    {"ticker": "TSLA", "win_rate": 0.31, "count": 16},
    {"ticker": "GME",  "win_rate": 0.28, "count": 11}
  ],
  "by_strategy": {
    "debit_spread": {"win_rate": 0.60, "count": 89},
    "straddle":     {"win_rate": 0.52, "count": 44}
  },
  "by_stance": {
    "bullish": {"win_rate": 0.63, "count": 210},
    "bearish": {"win_rate": 0.58, "count": 108}
  },
  "source_reliability": [
    {"source": "sec_8k", "win_rate": 0.81, "count": 32, "avg_confidence": 0.87}
  ],
  "computed_at": "2026-03-22T10:30:00+00:00"
}
```

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `min_sample` | integer | `3` | Minimum decided signals for a ticker to appear in rankings |

---

## API Reference

The full interactive API reference is at `/docs` (Swagger UI) or `/redoc` on a
running server. Key endpoint groups:

| Group | Path prefix | Description |
|---|---|---|
| Health | `/api/v1/health` | Service health, version, uptime |
| Signals | `/api/v1/signals` | Live and historical trade signal feed |
| Signal Quality | `/api/v1/signals/quality` | Accuracy statistics and per-ticker performance (Pro+) |
| Dashboard | `/dashboard` | Web UI -- real-time signal stream |
| Backtesting | `/backtest` | Run and compare backtests |
| Strategy | `/strategy` | Strategy builder, ML optimizer, marketplace |
| Options Flow | `/flow` | Block/sweep/dark-pool detection |
| Macro | `/macro` | FOMC, earnings, insider activity calendar |
| Social | `/social` | Manipulation detection, author credibility |
| Auth | `/auth` | Register, login, JWT refresh, API keys |
| Billing | `/billing` | Stripe subscription management |
| Admin | `/admin` | Platform administration (admin tier only) |
| MCP | `/mcp` | Model Context Protocol server endpoint |

All endpoints require authentication. Free-tier users have read-only access to
delayed signals. Pro and above receive real-time access.

### Example signal response

```json
{
  "signal_id": "550e8400-e29b-41d4-a716-446655440000",
  "ticker": "NVDA",
  "credibility_score": 0.82,
  "stance": "bullish",
  "trade_idea": {
    "strategy": "bull_call_spread",
    "legs": [
      {"action": "buy_to_open", "strike": 900, "expiry": "2026-04-17", "option_type": "call"},
      {"action": "sell_to_open", "strike": 950, "expiry": "2026-04-17", "option_type": "call"}
    ],
    "max_loss": 450,
    "max_gain": 550
  },
  "reasoning": "NVDA reported strong data-center revenue guidance ...",
  "source_url": "https://reddit.com/r/stocks/comments/...",
  "timestamp": "2026-03-22T14:31:05Z"
}
```

---

## Signal Lineage

Every signal processed by ROT generates a full provenance chain stored in a
local SQLite database (`signal_lineage.db` by default). This lets you trace
any trade idea back to the exact Reddit post that triggered it, replay
historical signals, and audit the pipeline for bias or errors.

### Using the lineage tracker

```python
import uuid
from rot.lineage import SignalLineageStore, LineageTracker

store   = SignalLineageStore("signal_lineage.db")
tracker = LineageTracker(store)

# Assign a unique ID to this signal's chain
signal_id = str(uuid.uuid4())

# Record each pipeline stage in sequence
src_id  = tracker.track_source(signal_id, raw_post_dict)
nlp_id  = tracker.track_nlp(signal_id, nlp_output_dict, parent_id=src_id)
cred_id = tracker.track_credibility(signal_id, score=0.82, features=feat, parent_id=nlp_id)
llm_id  = tracker.track_llm(signal_id, reasoning="LLM text...", parent_id=cred_id)
_       = tracker.track_trade(signal_id, trade_idea_dict, parent_id=llm_id)
```

### Querying lineage

```python
# Full ordered chain for a signal
nodes = store.get_lineage(signal_id)

# Resolve a trade back to its source post
provenance = store.get_trade_provenance(trade_id="trade-uuid-here")

# Export complete chain as JSON
json_str = store.export_lineage_json(signal_id)

# Find all signals from a specific URL
signal_ids = store.query_by_source("https://reddit.com/r/stocks/comments/...")

# Replay all signals from a time window
from datetime import datetime, timezone
nodes = store.replay_signals(
    since=datetime(2026, 3, 1, tzinfo=timezone.utc),
    until=datetime(2026, 3, 22, tzinfo=timezone.utc),
)
```

### Lineage node types

| Stage | NodeType | Data captured |
|---|---|---|
| Reddit/RSS ingestion | `source` | Full raw post dict, URL, subreddit, score |
| NLP pipeline output | `nlp_output` | Entities, sentiment, sarcasm score, conviction |
| Credibility scoring | `credibility` | Final score + per-factor feature dict |
| LLM reasoning | `llm_reasoning` | Full reasoning text or structured JSON |
| Trade idea | `trade_idea` | Strategy, legs, strikes, max-loss, max-gain |

---

## Broker Integration

ROT includes a broker abstraction layer at `src/rot/brokers/` that lets you
route approved trade ideas to a real (paper) brokerage with minimal configuration.

### Alpaca paper trading

```python
from rot.brokers import AlpacaBroker, OptionOrder
from decimal import Decimal
import asyncio

broker = AlpacaBroker(
    api_key="YOUR_ALPACA_KEY",
    secret_key="YOUR_ALPACA_SECRET",
    paper=True,   # Always start with paper=True
)

order = OptionOrder(
    symbol="AAPL",
    option_type="call",
    strike=Decimal("195"),
    expiry="2026-04-17",
    quantity=1,
    action="buy_to_open",
    order_type="limit",
    limit_price=Decimal("3.50"),
)

async def place():
    account = await broker.get_account()
    print(f"Buying power: ${account.buying_power}")
    result = await broker.submit_order(order)
    print(f"Order {result.order_id}: {result.status}")

asyncio.run(place())
```

### Mock broker (for testing)

```python
from rot.brokers import MockBroker
from decimal import Decimal

broker = MockBroker(
    initial_buying_power=Decimal("50000"),
    slippage_pct=0.01,   # 1% adverse slippage on fills
    fill_rate=0.95,       # 95% of orders fill immediately
    random_seed=42,       # Deterministic for tests
)
```

### Implementing a new broker

Subclass `BrokerClient` from `rot.brokers.base` and implement all five abstract
methods: `get_account`, `submit_order`, `cancel_order`, `get_option_chain`,
`get_positions`. All methods must be `async`.

---

## Portfolio Risk Monitor

The `PortfolioRiskMonitor` in `src/rot/risk/portfolio_risk.py` tracks aggregate
Greeks exposure and sector concentration across all open signal-derived positions.

```python
from rot.risk import PortfolioRiskMonitor

monitor = PortfolioRiskMonitor(
    max_total_delta=100.0,   # max absolute portfolio delta
    max_sector_pct=0.30,     # max 30% of cost in any one sector
)

approved, reason = monitor.can_add_position(
    symbol="NVDA", delta=15.0, cost=750.0, sector="Technology"
)
if approved:
    monitor.add_position("trade-001", "NVDA", 15.0, 750.0, "Technology")

print(monitor.total_delta())           # -> 15.0
print(monitor.sector_concentration())  # -> {"Technology": 1.0}
print(monitor.generate_report())       # -> full risk dict
```

---

## Running Tests

```bash
# Full suite with coverage
pytest tests/ --cov=rot --cov-report=term-missing --cov-fail-under=75

# Parallel execution (faster)
pytest tests/ -n auto -q

# Single file
pytest tests/test_nlp_engine.py -v
```

---

## Development

### Prerequisites

- Python 3.10, 3.11, or 3.12
- Docker (optional)

### Setup

```bash
pip install -e ".[dev]"
```

### Lint and type check

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/rot/core/ src/rot/app/ --ignore-missing-imports
```

### Security scanning

```bash
bandit -r src/ --configfile pyproject.toml
pip-audit --desc
```

### Pre-commit workflow

```bash
ruff check src/ tests/ && \
ruff format src/ tests/ && \
mypy src/rot/core/ src/rot/app/ --ignore-missing-imports && \
bandit -r src/ --configfile pyproject.toml -q && \
pytest tests/ -n auto -q --tb=short
```

---

## Deployment Guide

### Docker Compose (self-hosted)

```bash
git clone https://github.com/Mattbusel/Reddit-Options-Trader-ROT-.git
cd Reddit-Options-Trader-ROT-
cp .env.example .env
docker compose up --build -d
docker compose logs -f rot
```

`docker-compose.yml` runs a single `rot` service that binds to port 8000.
SQLite state is stored in a named volume (`rot_data`) for persistence across
restarts.  To scale horizontally, point `ROT_STORAGE_ROOT` at a shared NFS
mount or S3-compatible object store (not included in the base config).

**Production checklist:**

- Set `ROT_SECRET_KEY` to a randomly generated 32+ character string.
- Set Reddit API credentials.
- Mount a persistent volume at `ROT_STORAGE_ROOT` (default: `./data`).
- Place the app behind a reverse proxy (nginx, Caddy, Railway).
- Set `ROT_ENV=production` to enforce secret-key validation at startup.
- Broker integration defaults to paper trading (`ALPACA_PAPER=true`). Do not change this unless you have fully validated the system.

### Railway (one-click cloud deployment)

ROT ships a `railway.toml` and `Procfile` for zero-config Railway deployment:

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway link          # link to your project or create a new one
railway up            # build and deploy from the current directory
```

Railway environment variables to set in the dashboard:

| Variable | Description |
|---|---|
| `ROT_REDDIT_CLIENT_ID` | Reddit API client ID |
| `ROT_REDDIT_CLIENT_SECRET` | Reddit API client secret |
| `ROT_LLM_API_KEY` | Optional LLM key (leave empty for stub mode) |
| `ROT_SECRET_KEY` | 32+ char random secret |
| `RAILWAY_VOLUME_MOUNT_PATH` | Set to `/data` and attach a Railway Volume |

The live public deployment runs at:
**[rot.up.railway.app](https://web-production-71423.up.railway.app/)**

---

## Security

| Control | Implementation |
|---|---|
| Authentication | JWT + API key + session cookie (3 independent methods) |
| Authorization | 5-tier hierarchy; 35+ gate functions; admin bypass |
| SQL injection | 100% parameterised queries; field whitelist for dynamic updates |
| XSS | Jinja2 autoescape + nh3 Rust sanitizer + nonce-based CSP |
| CSRF | Custom ASGI middleware; timing-safe HMAC comparison |
| Security headers | CSP, X-Frame-Options: DENY, X-Content-Type-Options, Referrer-Policy |
| Rate limiting | Database-backed, multi-instance-safe; per-tier daily + burst limits |
| Security logging | 10 SIEM-ready JSON event types; global sanitising filter |
| CI scanners | CodeQL, Bandit, pip-audit, TruffleHog, Dependabot |

---

## Contributing

1. Fork the repository and create a feature branch from `main`.
2. Write tests for any new behaviour. Aim to keep the test-to-production ratio above 1.5:1.
3. Ensure `ruff check`, `ruff format --check`, and `pytest` all pass locally.
4. Keep pull requests focused: one logical change per PR.
5. Reference related issues in the PR description.
6. Do not commit secrets, credentials, or generated files.
7. New broker integrations must subclass `BrokerClient` and ship with a `MockBroker`-based test suite.
8. New pipeline stages must integrate with `LineageTracker` to maintain the full audit trail.

---

## Round 2 Features

### Options Greeks Dashboard (`GET /options/greeks`)

A live, dark-themed web page showing Black-Scholes Greeks (Delta, Gamma, Theta, Vega)
for the top tracked tickers, updated every 30 seconds via AJAX.

- **Delta**: green (bullish / positive), red (bearish / negative)
- **Gamma**: yellow warning badge when `|gamma| > 0.05` (elevated pin risk)
- **Theta / Vega**: always displayed for premium decay and volatility exposure awareness
- **Greeks Summary card** per ticker: spot price, IV estimate, DTE
- JSON API also available at `GET /api/v1/options/greeks`

```bash
# Navigate to:
http://localhost:8000/options/greeks

# JSON API:
curl "http://localhost:8000/api/v1/options/greeks?tickers=SPY,AAPL,NVDA&dte=7"
```

Source: `src/rot/web/routes/greeks_dashboard.py`

---

### Automated Trade Journal (`GET /journal`)

End-to-end trade idea tracking from signal generation to outcome resolution,
backed by a SQLite table.

```
Signal generated → JournalEntry inserted → expiry date passes → price fetched
→ outcome computed (win/loss/neutral) → JournalReport updated
```

**Endpoints**:
- `GET /journal` — HTML page with dark theme showing all entries and statistics
- `GET /api/journal/report` — JSON `JournalReport` with win rate, avg PnL, best/worst trade, accuracy by strategy

**`JournalEntry` fields**:

| Field | Type | Description |
|---|---|---|
| `signal_id` | str | FK to signals table |
| `ticker` | str | Underlying symbol |
| `strategy_type` | str | `"long_call"`, `"bull_put_spread"`, etc. |
| `entry_date` | str | ISO-8601 date |
| `expiry_date` | str | ISO-8601 option expiry |
| `predicted_direction` | str | `"bullish"` / `"bearish"` / `"neutral"` |
| `confidence_score` | float | Model confidence in [0, 1] |
| `actual_outcome` | str | `"win"` / `"loss"` / `"neutral"` / `null` |
| `pnl_estimate` | float | Fraction-of-premium PnL estimate |

**Auto-resolution**: `TradeJournal.auto_resolve_expired()` runs nightly, fetches
the current price via `yfinance`, and computes the outcome heuristically.

```python
from rot.journal import TradeJournal, JournalEntry

journal = TradeJournal(db)
await journal.init_schema()

entry_id = await journal.insert(JournalEntry(
    signal_id="sig_001",
    ticker="AAPL",
    strategy_type="long_call",
    entry_date="2026-03-10",
    expiry_date="2026-03-21",
    predicted_direction="bullish",
    confidence_score=0.78,
))

report = await journal.get_report()
print(f"Win rate: {report.win_rate:.1%}  Avg PnL: {report.avg_pnl:+.1%}")
```

Source: `src/rot/journal.py`

---

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for release history.

---

## License

MIT License. Copyright (c) 2026 Matthew Busel.

Third-party dependency licenses are listed in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

---

## Risk Disclaimer

**IMPORTANT -- READ BEFORE USE**

ROT is a **research and educational tool only**. It is a signal intelligence platform, not a trading execution engine.

- **Nothing in this repository constitutes financial advice, investment advice, or a recommendation to buy or sell any security or derivative.**
- Options trading carries **significant financial risk**. You can lose 100% of the premium paid on options positions.
- Signal quality scores, confidence levels, and trade ideas generated by this system are **experimental** and have not been independently validated for real-money trading.
- **Past signal quality does not guarantee future accuracy or profitability.** Reddit sentiment is noisy and frequently manipulated.
- LLM-generated reasoning is probabilistic and can be confidently wrong.
- The broker integration module defaults to **paper trading**. If you enable live execution, you assume full responsibility for any financial outcome.
- **Never risk capital you cannot afford to lose.**
- The authors and contributors accept no liability for financial losses arising from use of this software.

Use at your own risk.
