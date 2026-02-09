Reddit Options Trader (ROT)

Real-time Reddit signal intelligence → ticker-aware event detection → market-enriched options trade ideas.

ROT is a full-stack, real-time signal discovery system that monitors high-velocity Reddit discussions, detects emerging market events, extracts and validates tradable tickers, enriches them with market data, applies credibility scoring, and generates structured options trade ideas.

This is not a trading bot or execution system.
ROT is an intelligence layer designed to surface what matters before price fully reacts.
Live Pipeline loop output

![ROT storage outputs](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/blob/main/Screenshot%202026-02-09%20012734.png)
---

### JSONL artifact outputs (storage/)
![ROT storage outputs](https://raw.githubusercontent.com/Mattbusel/Reddit-Options-Trader-ROT-/master/Screenshot%202026-01-04%20171857.png)

What ROT Is

A real-time social signal engine for markets

A research and discovery tool for options-driven traders

A backend + dashboard product, not a notebook experiment

ROT runs continuously, stores signals in a database, broadcasts them live, and exposes them via:

Web dashboard

REST API

WebSockets

Discord alerts

Core Capabilities (Current State)
1. Real-Time Reddit Ingestion

Streams posts using PRAW from:

r/wallstreetbets

r/stocks

Supports hot, new, rising, top

Deduplicates posts with TTL-based persistence

Handles restarts without losing context

2. Trend Detection Engine

Detects emerging momentum, not raw mentions.

Signals are driven by:

Score velocity

Comment velocity

Engagement acceleration

Emits TrendCandidates when thresholds are exceeded.

3. Ticker Extraction & Validation

Robust entity extraction with aggressive filtering.

Supports:

$TSLA style mentions

Bare tickers (TSLA)

Multi-ticker posts

Filters:

Macro noise (AI, IPO, USD, WSB, etc.)

Non-equities and slang

Invalid or delisted symbols

Includes alias normalization:

SPXW → ^GSPC

TSMC → TSM

4. Market Enrichment

Pulls live market data via yfinance

Caches results locally to minimize API calls

Enriches events with:

Price

Market cap

Volume

Metadata used downstream

5. Event Classification & Scoring

Each signal is converted into a structured Event with:

Event type detection:

Earnings

Squeeze

Regulatory

Product

Macro

Sentiment detection:

Bullish / Bearish / Mixed

Time horizon inference:

Intraday (0DTE)

Weekly

Earnings window

Confidence scoring based on:

Flair (DD bonus)

Engagement quality

Crosspost penalties

Ticker focus

Text depth

Transparency included via scoring breakdown metadata.

6. LLM Reasoning Layer (Optional)

Provider-agnostic LLM interface

Supports OpenAI, Anthropic, DeepSeek

Converts events into ReasoningPackets

Fully optional with safe fallback when disabled

LLMs are used for:

Thesis articulation

Risk identification

Context synthesis

7. Trade Idea Generation

ROT generates example options strategies, not executable orders.

Supported strategies:

Bull call spreads

Bear put spreads

Straddles

Features:

Strike selection (ATM ± 5%)

Expiry heuristics (weekly vs monthly)

Max loss calculation

Quality scoring

Pre-trade gating:

Market data availability

Market cap thresholds

8. Persistent Storage Layer

Async SQLite database (aiosqlite)

Tables:

signals

signal_performance

users

Supports:

Filtering by ticker, stance, confidence, event type

Trending ticker aggregation

Performance summaries

Legacy JSONL artifacts are still emitted for inspection.

9. Web Dashboard (FastAPI + Jinja)

A live, production-style dashboard:

Real-time signal feed (WebSocket)

Confidence bars & stance badges

Trending tickers (24h)

Signal detail pages:

Full reasoning

Trade structure

Market context

Dark theme with Tailwind CSS

Health & API visibility

10. Alerts & Distribution

Discord webhook integration

High-confidence, tradeable signals only

Rich embeds with:

Ticker

Stance

Confidence

Strategy

Legs

Risks

Catalyst window

Example Live Output
🔥 Top signals:
1. wallstreetbets | What Are Your Moves Tomorrow, February 09, 2026
2. stocks | Silver has crashed yet again [SLV]
3. wallstreetbets | Inside Elon Musk’s $1.25T AI & Space Megamerger

🎯 Top ticker signals:
1. SLV
2. AGI
3. GDRX


(Exact output varies by market conditions.)

Project Structure
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


This starts:

Reddit ingestion pipeline

Database persistence

Web dashboard

WebSocket live feed

Discord alerts

4. View Dashboard
http://localhost:8000/dashboard

5. Run Tests
pytest tests/ -v


53 tests currently passing.

What This Is Not

❌ Not a trading bot

❌ Not an execution engine

❌ Not financial advice

❌ Not a backtester (yet)

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

Roadmap

Signal performance tracking & win-rate attribution

Time-decay persistence & signal aging

Options chain awareness (IV, OI clustering)

Cross-subreddit correlation

Offline backtesting & replay

X (Twitter) bot integration

Hosted SaaS deployment

Disclaimer

This project is for research and experimentation only.
Nothing in this repository constitutes financial advice.





