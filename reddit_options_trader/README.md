
# Reddit Options Trader (ROT)

A modular research pipeline that turns **trending Reddit discussions** into
**structured market events** and **options trade ideas**.

This project is focused on **infrastructure**, not “print money” claims.

---

## What this is

ROT ingests Reddit threads, detects early momentum, extracts market-relevant
events, runs structured reasoning (LLM-assisted), and outputs **auditable,
defined-risk options ideas**.

Every stage produces receipts.

---

## High-level flow

```

Reddit → Snapshots → Trend Detection → Events
→ Credibility Scoring → Reasoning (LLM)
→ Market Gates → Trade Ideas

```

Key design choice:  
**Reddit is treated as an event discovery surface, not a truth source.**

---

## Core concepts

- **ThreadSnapshot**  
  Point-in-time capture of a Reddit post (and optional comments).

- **TrendCandidate**  
  A post or entity showing *acceleration* (rate of change), not raw popularity.

- **Event**  
  Structured representation of a potential market catalyst:
  - entities (tickers / companies)
  - stance (bullish / bearish / unknown)
  - time horizon
  - evidence + confidence

- **ReasoningPacket**  
  Schema-locked LLM output:
  - thesis
  - catalyst window
  - invalidations
  - suggested option structures

- **TradeIdea**  
  A paper-trade object with:
  - defined risk
  - no execution by default
  - explicit “do not trade” reasons when gated out

---

## Project structure

```

src/rot/
core/          Shared types, config, logging
ingest/        Reddit API ingestion
trend/         Momentum detection (rate-based)
extract/       Entity + event construction
credibility/   Confidence & manipulation filters
reasoner/      LLM integration (DeepSeek)
market/        Market data gates + trade construction
app/           Pipeline runner
storage/
snapshots.jsonl
events.jsonl
reasoning.jsonl
trade_ideas.jsonl

````

All outputs are logged as **JSONL** for replay, debugging, and backtesting.

---

## Current status

- X Full pipeline structure in place
- X Typed data contracts between modules
- X JSONL audit trail
- X Reddit API ingestion (official)
- X Market data integration
- X Live / paper trading (optional)

By default, the system **does not place trades**.

---

## Design principles

- Modular, swappable components
- No hidden state
- No look-ahead leakage
- Defined-risk bias for options
- Skepticism-first (manipulation-aware)

---

## Non-goals

- Guaranteed profitability
- Directional prediction from sentiment alone
- Black-box decision making
- High-frequency execution

---

## Getting started

```bash
# create virtual env
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# install deps (once defined)
pip install -e .
````

Then wire the Reddit ingestor and run:

```python
PipelineRunner.run_once()
```

---

## Disclaimer

This project is for **research and experimentation**.
Nothing here constitutes financial advice.


