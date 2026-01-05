# Reddit Options Trader (ROT)

**Real-time Reddit trend detection → ticker-aware signal extraction → market-enriched trade ideas.**

ROT is an experimental research system that monitors high-velocity Reddit discussions, detects emerging trends, extracts tradable tickers, enriches them with market data, and generates structured trade ideas.

This is **not** a backtester or an execution bot.
It is a **signal discovery and intelligence pipeline**.

Live Pipeline loop output

![ROT storage outputs](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/blob/master/Screenshot%202026-01-04%20194537.png)
---

### JSONL artifact outputs (storage/)
![ROT storage outputs](https://raw.githubusercontent.com/Mattbusel/Reddit-Options-Trader-ROT-/master/Screenshot%202026-01-04%20171857.png)

## What It Does (Current State)

ROT runs as a continuous loop:

1. **Ingests Reddit in real time**

   * Uses **PRAW** to stream posts from subreddits like:

     * `r/wallstreetbets`
     * `r/stocks`
   * Supports `hot`, `rising`, `new`, `top`
   * Deduplicates previously seen posts

2. **Detects trending discussions**

   * Computes momentum using:

     * score velocity
     * comment velocity
   * Emits `TrendCandidate`s when rate thresholds are exceeded

3. **Ranks top signals**

   * Global top trends (all posts)
   * **Ticker-aware ranking** (only posts with valid tradable symbols)
   * Outputs live “Top Signals” and “Top Ticker Signals” every cycle

4. **Extracts and validates tickers**

   * Supports:

     * `$TSLA` style mentions
     * bare tickers (`TSLA`)
   * Filters:

     * macro words (`AI`, `IPO`, `USD`, `WSB`, etc.)
     * non-equities
     * delisted / invalid symbols
   * Alias handling (e.g. `SPXW → ^GSPC`, `TSMC → TSM`)

5. **Market enrichment**

   * Pulls live market data via **yfinance**
   * Caches results locally to avoid re-fetching
   * Adds market metadata into event objects

6. **Event → reasoning → trade ideas**

   * Converts signals into structured `Event`s
   * Runs LLM reasoning (DeepSeek integration stubbed / optional)
   * Emits example option trade ideas (directional, not executable)

7. **Writes everything to disk**

   * JSONL logs for:

     * snapshots
     * trend candidates
     * top signals
     * ticker signals
     * events
     * reasoning packets
     * trade ideas

---

## Example Output (Live)

```
🔥 Top signals:
  1. wallstreetbets | What Are Your Moves Tomorrow, January 05, 2026 [-]
  2. wallstreetbets | Investing changed my life [HYSA]
  3. wallstreetbets | Closed SPXW $6875.00C (+92%) [^GSPC]

🎯 Top ticker signals:
  1. wallstreetbets | Closed SPXW $6875.00C (+92%) [^GSPC]
  2. wallstreetbets | My Turn. Became a millionaire in 2025 [GOOGL]
  3. wallstreetbets | Drones and Space 🛩️🚀 [ASTS,RKLB,LUNR]
```

(Exact output varies by market conditions.)

---


## Project Structure

```
src/rot/
├── app/                # main loop + pipeline runner
├── ingest/             # Reddit ingestion (PRAW)
├── trend/              # trend detection & ranking
├── extract/            # entity & ticker extraction
├── market/             # symbol validation + enrichment
├── credibility/        # signal confidence scoring
├── reasoner/           # LLM reasoning layer (DeepSeek)
├── core/               # types, logging, utilities
storage/
├── *.jsonl             # emitted signals & logs
├── market_cache.json   # cached market data
```

---

## Setup

### 1. Install dependencies

```bash
pip install praw yfinance
```

### 2. Set Reddit API credentials

```bash
export ROT_REDDIT_CLIENT_ID="..."
export ROT_REDDIT_CLIENT_SECRET="..."
export ROT_REDDIT_USER_AGENT="rot:v0.1 (by u_yourname)"
```

### 3. Run once

```bash
python -m rot.app.main
```

### 4. Run continuously

```bash
python -m rot.app.loop
```

---

## What This Is *Not*

*  Not a trading bot
*  Not financial advice
*  Not a backtesting framework
*  Not optimized for latency or execution

This is **signal intelligence**, not order placement.

---

## Why This Exists

Most retail trading systems:

* React to price **after** the move
* Ignore social momentum structure
* Treat Reddit as noise

ROT treats Reddit as:

* A **high-energy signal surface**
* Where crowd conviction forms **before price fully adjusts**
* Especially relevant for **options-driven markets**

---

## Roadmap (Next Logical Steps)

* Confidence-weighted ticker ranking
* Time-decay signal persistence
* Options chain awareness (IV, OI, expiry clustering)
* Cross-subreddit correlation
* Backtesting harness (offline replay)
* Alerting (Slack / Discord / email)
* Live dashboard

---

## Disclaimer

This project is for **research and experimentation only**.
Nothing here constitutes financial advice.









