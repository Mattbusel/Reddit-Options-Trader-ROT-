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

## What ROT Is

- A **real-time market signal engine**
- A **research & discovery tool** for options-driven traders
- A **backend + live dashboard product**, not a notebook experiment

ROT runs continuously, persists data, broadcasts live updates, and exposes signals via:

- Web dashboard  
- REST API  
- WebSockets  
- Discord alerts  


## Core Capabilities

### 1. Real-Time Ingestion (Reddit + RSS)

**Reddit**
- Streams posts using PRAW
- Supported subreddits:
  - `r/wallstreetbets`
  - `r/stocks`
- Feeds supported:
  - `hot`, `new`, `rising`, `top`
- Deduplicates previously seen posts
- Persists state across restarts

**RSS / News**
- Native RSS & Atom feed ingestion
- Default feeds include:
  - Reuters Business
  - Reuters Company News
  - SEC 8-K filings
- Deterministic IDs, freshness gating, and deduplication
- RSS events bypass engagement heuristics and are promoted directly as catalysts

---

### 2. Trend Detection Engine

Detects **momentum**, not raw mentions.

Signals are driven by:
- Score velocity
- Comment velocity
- Engagement acceleration

Emits `TrendCandidate` objects once thresholds are exceeded.

---

### 3. Ticker Extraction & Validation

Robust entity extraction with aggressive filtering.

**Supports**
- `$TSLA` style mentions
- Bare tickers (`TSLA`)
- Multi-ticker posts

**Filters**
- Macro noise (`AI`, `IPO`, `USD`, `WSB`, etc.)
- Non-equities and slang
- Delisted / invalid symbols

**Alias normalization**
- `SPXW` → `^GSPC`
- `TSMC` → `TSM`

---

### 4. Market Enrichment

- Live market data via `yfinance`
- Local caching to avoid repeated fetches
- Enriches events with:
  - Price
  - Market cap
  - Volume
  - Context metadata

---

### 5. Event Classification & Credibility Scoring

Each signal becomes a structured **Event** with:

**Event Types**
- Earnings
- Squeeze
- Regulatory
- Product
- Macro

**Sentiment Detection**
- Bullish
- Bearish
- Mixed

**Time Horizon Inference**
- Intraday (0DTE)
- Weekly
- Earnings window

**Credibility Scoring**
- DD flair bonus
- Engagement quality
- Cross-post penalties
- Ticker focus
- Text depth

Each score includes a **transparent breakdown**.

---

### 6. LLM Reasoning Layer (Optional)

- Provider-agnostic interface
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

ROT produces **example options strategies**  
*(not executable orders)*.

**Supported strategies**
- Bull call spreads
- Bear put spreads
- Straddles

**Features**
- Strike selection (ATM ± 5%)
- Expiry heuristics (weekly vs monthly)
- Max loss calculation
- Quality scoring

**Pre-trade gates**
- Market data availability
- Market cap minimums

---

### 8. Persistent Storage Layer

- Async SQLite database via `aiosqlite`
- Tables:
  - `signals`
  - `signal_performance`
  - `users`

Supports:
- Filtering by ticker, stance, confidence, event type
- Trending ticker aggregation
- Performance summaries

Legacy `.jsonl` artifacts are still emitted for inspection.

---

### 9. Web Dashboard (FastAPI + Jinja)

Live production-style dashboard featuring:

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

## Example Live Output

🔥 Top signals:

wallstreetbets | What Are Your Moves Tomorrow, February 09, 2026

stocks | Silver has crashed yet again [SLV]

wallstreetbets | Inside Elon Musk’s $1.25T AI & Space Megamerger

🎯 Top ticker signals:

SLV

AGI

GDRX


---

## Project Structure

src/rot/
├── app/ # unified server & pipeline runner
├── ingest/ # Reddit + RSS ingestion
├── trend/ # trend detection
├── extract/ # ticker extraction
├── market/ # validation & enrichment
├── credibility/ # scoring logic
├── reasoner/ # LLM reasoning layer
├── alerts/ # Discord dispatch
├── storage/ # database + persistence
├── web/ # FastAPI app, routes, templates
├── core/ # config, types, utilities

storage/
├── *.jsonl # emitted artifacts
├── market_cache.json


---

## Setup & Running

### 1. Environment

```bash
cp .env.example .env
Fill in:

Reddit API credentials

Optional LLM API key

Optional RSS configuration

2. Install
pip install -e ".[dev]"
3. Run the Full Product
python -m rot.app.server
Starts:

Reddit + RSS ingestion pipeline

SQLite persistence

Web dashboard

WebSocket live feed

Discord alerts

4. View Dashboard
http://localhost:8000/dashboard
5. Run Tests
pytest tests/ -v
83 tests currently passing

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

Treat Reddit and news as noise

ROT treats them as:

A high-energy signal surface

Where conviction forms before price fully adjusts

Especially relevant for options-driven markets

Roadmap
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
