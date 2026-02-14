# Custom NLP Engine — ROT Architecture Reference

> Part of the ROT documentation suite. See [CLAUDE.md](../CLAUDE.md) for the full index.

## Quick Start for Agents

- Key file(s): `src/rot/nlp/engine.py` (orchestrator), `src/rot/nlp/types.py` (all NLP dataclasses)
- Key pattern: Zero-dependency financial NLP pipeline -- no spaCy, no NLTK, no transformers. 10 modules, pure Python.
- Entry point: `NLPEngine().analyze(title, body, comments) --> NLPResult`

---

## Overview

The NLP engine (`src/rot/nlp/`) is ROT's differentiator -- a zero-dependency, financial-domain NLP pipeline built from scratch. No external NLP libraries.

### Module Inventory

| File | Purpose | ~Lines |
|------|---------|--------|
| `__init__.py` | Re-exports NLPEngine, NLPResult, SentimentResult, ResolvedEntity | 28 |
| `types.py` | All NLP dataclasses (Token, SentimentResult, ResolvedEntity, NLPResult, etc.) | 150 |
| `tokenizer.py` | Financial-aware tokenizer (cashtags, emojis, ALL-CAPS, repeated chars, options contracts) | 300 |
| `lexicon.py` | 500+ term sentiment dictionary (polarity, intensity, conviction per term) | 400 |
| `sentiment.py` | Sentiment analysis + 8-rule sarcasm detection + conviction scoring | 350 |
| `entities.py` | Context-aware entity resolution (cashtags, bare tickers, implicit refs, sector expansion) | 400 |
| `classifier.py` | Multi-label event classification (14 categories, TF-IDF-like scoring) | 250 |
| `temporal.py` | Tense detection, actionability scoring, urgency scoring, time expression extraction | 200 |
| `thread.py` | Comment consensus analysis (polarity std dev, OP agreement, contrarian detection) | 200 |
| `engine.py` | Orchestrator: `analyze(title, body, comments) --> NLPResult` | 250 |

---

## Usage

```python
from rot.nlp import NLPEngine

engine = NLPEngine()
result = engine.analyze(title="$TSLA to the moon!", body="Buying calls...", comments=[...])

result.primary_stance          # "bullish"
result.ticker_symbols          # ["TSLA"]
result.sentiment.polarity      # 0.85
result.sentiment.conviction    # 0.7
result.sentiment.sarcasm_probability  # 0.0
result.classifications         # [ClassifiedEvent(category="squeeze_chatter", confidence=0.6)]
result.temporal.actionability  # 0.9
result.thread.consensus_score  # 0.75
```

---

## Pipeline Stages

Executed sequentially in `engine.py`:

### 1. Tokenize (`tokenizer.py`)

Financial-aware tokenizer handles:
- `$TICKER` cashtags
- 50+ emoji mappings
- ALL-CAPS detection
- Repeated character normalization
- Options contract parsing (`TSLA 200C 1/19`)
- Markdown stripping

### 2. Sentiment (`sentiment.py`)

Processing chain:
1. Lexicon-matching (500+ terms)
2. Negation window (3-word lookahead)
3. Intensifier/diminisher pass
4. Emoji pass
5. ALL-CAPS boost
6. Sarcasm detection
7. Conviction scoring
8. Aggregation

Output: `SentimentResult` with polarity (-1 to +1), intensity, conviction, sarcasm probability.

### 3. Entity Resolution (`entities.py`)

Resolution chain:
1. Cashtag extraction (`$TICKER`)
2. Bare ticker filtering (imports blocklists from `enricher.py` and `event_builder.py`)
3. Implicit resolution (~50 CEO/company maps, e.g., "Elon" --> TSLA)
4. Sector expansion (~12 sector groups)
5. Options entity extraction
6. Position extraction
7. Per-ticker sentiment assignment

Output: `List[ResolvedEntity]` with symbol, raw text, resolution method, confidence, sentiment.

### 4. Classification (`classifier.py`)

Multi-label weighted keyword scoring across 14 categories:

| Category | Description |
|----------|-------------|
| `earnings_rumor` | Earnings-related speculation |
| `product_news` | Product launches, updates |
| `regulatory` | FDA, SEC, government action |
| `squeeze_chatter` | Short squeeze discussion |
| `macro` | Macroeconomic events |
| `other` | Uncategorized |
| `insider_activity` | Insider buying/selling |
| `technical_breakout` | Chart patterns, breakouts |
| `options_flow` | Unusual options activity |
| `dividend_play` | Dividend-related |
| `buyback` | Share buybacks |
| `ipo` | IPO-related |
| `spac` | SPAC mergers/deals |
| `crypto_correlation` | Crypto market correlation |

Output: `List[ClassifiedEvent]` with category, confidence, evidence spans, matched terms.

### 5. Temporal (`temporal.py`)

| Analysis | Output Range |
|----------|-------------|
| Verb pattern tense detection | past / present / future / unknown |
| Actionability scoring | past=0.1-0.3, present=0.7-1.0, future=0.4-0.6 |
| Time expression extraction | List of temporal phrases |
| Urgency scoring | 0.0-1.0 |

### 6. Thread Consensus (`thread.py`)

Analyzes `ThreadSnapshot.top_comments`:
- Polarity standard deviation for consensus measurement
- OP sentiment agreement score
- Contrarian detection (top comment disagrees with OP)
- Quality weighting: score x log(length)

Output: `ThreadResult` with consensus_polarity, consensus_score, agreement_with_op, contrarian_detected.

---

## Sarcasm Detection (8 Rules)

| Rule | Trigger | Probability Boost |
|------|---------|-------------------|
| 1 | ALL-CAPS positive + negative context | +0.35 |
| 2 | Clown emoji after statement | +0.40 |
| 3 | Known sarcastic phrases ("what could go wrong", "cant go tits up") | +0.50 |
| 4 | Emoji contradiction (rocket + bearish words) | +0.30 |
| 5 | Quoted positive words in negative context | +0.25 |
| 6 | Excessive rockets with no substance | +0.15 |
| 7 | "This is fine" pattern + negative context | +0.35 |
| 8 | Rhetorical question + positive | +0.45 |

---

## Lexicon Structure

The 500+ term lexicon (`lexicon.py`) is organized by:

### Categories
- action, outcome, descriptor, emoji, slang, modifier

### Domains
- general, options, technical, wsb_slang, macro

### Per-Term Fields

| Field | Range | Description |
|-------|-------|-------------|
| `polarity` | -1.0 to +1.0 | Sentiment direction |
| `intensity` | 0.0 to 1.0 | Signal strength |
| `conviction` | 0.0 to 1.0 | Author certainty |

---

## Integration with Pipeline

The NLP engine integrates at two points:

1. **EventBuilder** (Stage 4): `EventBuilder(nlp_engine=NLPEngine())` uses the full NLP analysis to produce events. Falls back to legacy regex if NLP engine not provided.

2. **LLM Prompt** (Stage 7): NLP results are included in the event prompt sent to the LLM -- polarity, conviction, sarcasm, classifications, tense, thread consensus, per-ticker sentiment.

3. **Credibility Scoring** (Stage 6): NLP signals (sarcasm, conviction, consensus, actionability) feed into both heuristic and ML credibility scoring.

The NLP engine is designed to be optional. If it fails or is not provided, the pipeline continues via the legacy regex path.
