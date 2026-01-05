# Reddit Options Trader (ROT)

A real-time Reddit signal ingestion and analysis pipeline that detects **emerging market sentiment**, extracts **trade-relevant entities**, and generates **structured options trade ideas**.

ROT is designed as a **research-grade pipeline**, not a trading bot. Every stage emits auditable artifacts to disk so signals can be inspected, replayed, and refined.

## Screenshots

### Live pipeline loop output
![ROT loop output](https://raw.githubusercontent.com/Mattbusel/Reddit-Options-Trader-ROT-/master/Screenshot%202026-01-04%20171813.png)

### JSONL artifact outputs (storage/)
![ROT storage outputs](https://raw.githubusercontent.com/Mattbusel/Reddit-Options-Trader-ROT-/master/Screenshot%202026-01-04%20171857.png)


---

## What This Does (Today)

ROT continuously:

1. **Ingests live Reddit data** via PRAW

   * Supports `hot`, `rising`, `new`, `top`
   * Configurable subreddits and post limits
   * Optional top-comment ingestion
2. **Deduplicates posts** across runs

   * Tracks seen post IDs to prevent reprocessing noise
3. **Detects trending threads**

   * Uses rate-of-change on score and comment velocity
   * Emits trend candidates when deltas cross thresholds
4. **Extracts market-relevant events**

   * Identifies ticker symbols (e.g. TSLA, NVDA)
   * Builds evidence chains tied to source posts
5. **Scores credibility**

   * Lightweight confidence scoring per event
6. **Reasons over events (LLM-ready)**

   * Structured reasoning packets (DeepSeek-ready)
7. **Generates trade ideas**

   * Produces normalized “trade idea” artifacts
8. **Persists everything**

   * JSONL logs for full pipeline observability

This runs **continuously** and safely. No execution, no brokerage APIs.

---

## Architecture Overview

```
Reddit (PRAW)
   ↓
Ingestor (dedupe + snapshots)
   ↓
Trend Engine (delta-based)
   ↓
Event Builder (entities + evidence)
   ↓
Credibility Scorer
   ↓
LLM Reasoner (optional)
   ↓
Trade Builder
   ↓
JSONL Artifacts (storage/)
```

Each stage is modular and independently replaceable.

---

## Live Output Artifacts

All pipeline outputs are written to `storage/` as append-only JSONL files:

* `snapshots.jsonl`
  Raw Reddit post snapshots
* `trend_candidates.jsonl`
  Posts exhibiting abnormal engagement velocity
* `events.jsonl`
  Extracted market-relevant events (tickers, stance, evidence)
* `reasoning.jsonl`
  LLM-ready reasoning packets
* `trade_ideas.jsonl`
  Structured trade idea outputs
* `seen_posts.json`
  Persistent deduplication state

This makes ROT **fully replayable and debuggable**.

---

## Requirements

* Python 3.10+
* Reddit API credentials
* PRAW

Install dependencies:

```bash
pip install -e .
```

---

## Reddit API Setup

Create a Reddit “script” app and set environment variables:

```bash
export ROT_REDDIT_CLIENT_ID="your_client_id"
export ROT_REDDIT_CLIENT_SECRET="your_client_secret"
export ROT_REDDIT_USER_AGENT="rot:v0.0.1 (by u_yourusername)"
```


---

## Running the Pipeline

### One-shot run

```bash
python -m rot.app.main
```

### Continuous loop (recommended)

```bash
python -m rot.app.loop
```

Example live output:

```
✅ run_1767564489 | snapshots=68 candidates=32 events=24 ideas=24
```

Stop safely with `Ctrl+C`.

---

## Deduplication Behavior

ROT maintains a persistent `seen_posts.json` file that:

* Prevents reprocessing identical Reddit posts
* Allows trend detection only when **metrics change**
* Keeps signal quality high during tight polling loops

You can reset state by deleting:

```bash
rm storage/seen_posts.json
```

---

## Design Philosophy

* **Research-first**: every decision is inspectable
* **No black boxes**: JSONL > dashboards
* **Signal over scale**: velocity beats volume
* **Composable**: each stage can be swapped or upgraded
* **Safe by default**: no live trading, no execution risk

ROT is meant to help you *see* market sentiment forming, not blindly act on it.

---

## Roadmap (Short-Term)

* Improved ticker/entity filtering
* Subreddit-specific trend thresholds
* Time-windowed top-N candidate ranking
* LLM prompt tuning for options-specific reasoning
* Backtesting hooks (offline replay from JSONL)

---

## Disclaimer

This project is for **research and educational purposes only**.
It does not provide financial advice and does not place trades.

---
.




