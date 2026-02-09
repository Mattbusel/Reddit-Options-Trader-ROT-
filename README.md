Reddit Options Trader (ROT)

Real-time Reddit signal intelligence → ticker-aware event detection → market-enriched options trade ideas.

ROT is a full-stack, real-time signal discovery system that monitors high-velocity Reddit discussions, detects emerging market events, extracts and validates tradable tickers, enriches them with market data, applies credibility scoring, and generates structured options trade ideas.

This is not a trading bot or execution system.
ROT is an intelligence layer designed to surface what matters before price fully reacts.
Live Pipeline loop output

![ROT storage outputs](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/blob/main/Screenshot%202026-02-09%20061235.png)
---

### JSONL artifact outputs (storage/)
![ROT storage outputs](https://raw.githubusercontent.com/Mattbusel/Reddit-Options-Trader-ROT-/master/Screenshot%202026-01-04%20171857.png)


##  What ROT Is

- A **real-time social signal engine** for markets  
- A **research and discovery tool** for options-driven traders  
- A **backend + dashboard product**, not a notebook experiment  

ROT runs continuously, stores signals in a database, broadcasts them live, and exposes them via:

- Web dashboard  
- REST API  
- WebSockets  
- Discord alerts  

---

##  Core Capabilities

### 1. Real-Time Reddit Ingestion

- Streams posts using **PRAW**
- Supported subreddits:
  - `r/wallstreetbets`
  - `r/stocks`
- Supports:
  - `hot`
  - `new`
  - `rising`
  - `top`
- Deduplicates previously seen posts
- Persists state across restarts

---

### 2. Trend Detection Engine

Detects **momentum**, not raw mentions.

Signals are driven by:
- Score velocity
- Comment velocity
- Engagement acceleration

Emits **TrendCandidates** once thresholds are exceeded.

---

### 3. Ticker Extraction & Validation

Robust entity extraction with aggressive filtering.

Supports:
- `$TSLA` style mentions
- Bare tickers (`TSLA`)
- Multi-ticker posts

Filters:
- Macro noise (`AI`, `IPO`, `USD`, `WSB`, etc.)
- Non-equities and slang
- Delisted / invalid symbols

Alias normalization:
- `SPXW → ^GSPC`
- `TSMC → TSM`

---

### 4. Market Enrichment

- Pulls live market data via **yfinance**
- Local caching to avoid repeated fetches
- Enriches events with:
  - Price
  - Market cap
  - Volume
  - Context metadata

---

### 5. Event Classification & Credibility Scoring

Each signal is converted into a structured **Event** with:

- **Event types**
  - Earnings
  - Squeeze
  - Regulatory
  - Product
  - Macro
- **Sentiment detection**
  - Bullish / Bearish / Mixed
- **Time horizon inference**
  - Intraday (0DTE)
  - Weekly
  - Earnings window
- **Confidence scoring** based on:
  - DD flair bonus
  - Engagement quality
  - Crosspost penalties
  - Ticker focus
  - Text depth

Each score includes a transparent breakdown.

---

### 6. LLM Reasoning Layer (Optional)

- Provider-agnostic LLM interface
- Supports:
  - OpenAI
  - Anthropic
  - DeepSeek
- Fully optional with safe fallback mode

Used for:
- Thesis synthesis
- Risk identification
- Context expansion

---

### 7. Trade Idea Generation

ROT produces **example options strategies** (not executable orders).

Supported strategies:
- Bull call spreads
- Bear put spreads
- Straddles

Features:
- Strike selection (ATM ± 5%)
- Expiry heuristics (weekly vs monthly)
- Max loss calculation
- Quality scoring
- Pre-trade gates:
  - Market data availability
  - Market cap minimums

---

### 8. Persistent Storage Layer

- Async SQLite database via **aiosqlite**
- Tables:
  - `signals`
  - `signal_performance`
  - `users`
- Supports:
  - Filtering by ticker, stance, confidence, event type
  - Trending ticker aggregation
  - Performance summaries

Legacy `.jsonl` artifacts are still emitted for inspection.

---

### 9. Web Dashboard (FastAPI + Jinja)

Live production-style dashboard:

- Real-time signal feed (WebSockets)
- Confidence bars & stance badges
- Trending tickers (24h)
- Signal detail pages:
  - Full reasoning
  - Trade structure
  - Market context
- Dark theme with Tailwind CSS
- Health & API visibility

---

### 10. Alerts & Distribution

- Discord webhook integration
- High-confidence signals only
- Rich embeds including:
  - Ticker
  - Stance
  - Confidence
  - Strategy
  - Option legs
  - Risks
  - Catalyst window

---

## 📊 Example Live Output

```text
🔥 Top signals:
1. wallstreetbets | What Are Your Moves Tomorrow, February 09, 2026
2. stocks | Silver has crashed yet again [SLV]
3. wallstreetbets | Inside Elon Musk’s $1.25T AI & Space Megamerger

🎯 Top ticker signals:
1. SLV
2. AGI
3. GDRX

src/rot/
├── app/                # unified server & pipeline runner
├── ingest/             # Reddit ingestion
├── trend/              # trend detection
├── extract/            # ticker extraction
├── market/             # validation & enrichment
├── credibility/        # scoring logic
├── reasoner/           # LLM reasoning layer
├── alerts/             # Discord dispatch
├── storage/            # database + persistence
├── web/                # FastAPI app, routes, templates
├── core/               # config, types, utilities
storage/
├── *.jsonl             # emitted artifacts
├── market_cache.json

 Setup & Running
1. Environment
cp .env.example .env


Fill in:

Reddit API credentials

Optional LLM API key

2. Install
pip install -e ".[dev]"

3. Run the Full Product
python -m rot.app.server


Starts:

Reddit ingestion pipeline

SQLite persistence

Web dashboard

WebSocket live feed

Discord alerts

4. View Dashboard
http://localhost:8000/dashboard

5. Run Tests
pytest tests/ -v


(53 tests currently passing)

 What This Is Not

Not a trading bot

Not an execution engine

Not financial advice

Not a backtesting framework (yet)

ROT is signal intelligence, not order placement.

 Why This Exists

Most retail trading tools:

React after price moves

Ignore social momentum structure

Treat Reddit as noise

ROT treats Reddit as:

A high-energy signal surface

Where conviction forms before price fully adjusts

Especially relevant for options-driven markets

🛣 Roadmap

Signal performance attribution

Time-decay signal aging

Options chain awareness (IV, OI clustering)

Cross-subreddit correlation

Offline backtesting & replay

X (Twitter) bot integration

Hosted SaaS deployment

 Disclaimer

This project is for research and experimentation only.
Nothing in this repository constitutes financial advice.

















