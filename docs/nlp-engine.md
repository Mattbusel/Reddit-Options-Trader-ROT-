<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Custom NLP Engine

> Part of ROT docs. See [CLAUDE.md](../CLAUDE.md) for full index.

## Quick Start

- Files: `src/rot/nlp/engine.py` (orchestrator), `src/rot/nlp/types.py` (dataclasses)
- Zero-dependency financial NLP -- no spaCy/NLTK/transformers. 10 modules, pure Python.
- Entry: `NLPEngine().analyze(title, body, comments) -> NLPResult`

## Modules

| File | Purpose | ~Lines |
|------|---------|--------|
| `__init__.py` | Re-exports NLPEngine, NLPResult, SentimentResult, ResolvedEntity | 28 |
| `types.py` | NLP dataclasses (Token, SentimentResult, ResolvedEntity, NLPResult, etc.) | 150 |
| `tokenizer.py` | Financial tokenizer: cashtags, emojis, ALL-CAPS, repeated chars, options contracts, markdown | 300 |
| `lexicon.py` | 500+ term sentiment dictionary (polarity/intensity/conviction per term) | 400 |
| `sentiment.py` | Sentiment + 8-rule sarcasm + conviction scoring | 350 |
| `entities.py` | Entity resolution: cashtags, bare tickers, implicit refs, sector expansion | 400 |
| `classifier.py` | 14-category multi-label classification (TF-IDF-like) | 250 |
| `temporal.py` | Tense detection, actionability/urgency scoring, time expressions | 200 |
| `thread.py` | Comment consensus: polarity std dev, OP agreement, contrarian detection | 200 |
| `engine.py` | Orchestrator: `analyze()` -> NLPResult | 250 |

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

## Pipeline Stages (sequential in `engine.py`)

**1. Tokenize** (`tokenizer.py`): `$TICKER` cashtags, 50+ emoji maps, ALL-CAPS detection, repeated char normalization, options contract parsing (`TSLA 200C 1/19`), markdown stripping

**2. Sentiment** (`sentiment.py`): lexicon match (500+ terms) -> negation window (3-word) -> intensifier/diminisher -> emoji -> ALL-CAPS boost -> sarcasm detection -> conviction -> aggregation. Output: `SentimentResult` (polarity -1..+1, intensity, conviction, sarcasm_probability)

**3. Entity Resolution** (`entities.py`): cashtag extraction -> bare ticker filtering (blocklists from `enricher.py`/`event_builder.py`) -> implicit resolution (~50 CEO/company maps) -> sector expansion (~12 groups) -> options entity extraction -> position extraction -> per-ticker sentiment. Output: `List[ResolvedEntity]`

**4. Classification** (`classifier.py`): multi-label weighted keyword scoring. 14 categories: `earnings_rumor`, `product_news`, `regulatory`, `squeeze_chatter`, `macro`, `other`, `insider_activity`, `technical_breakout`, `options_flow`, `dividend_play`, `buyback`, `ipo`, `spac`, `crypto_correlation`. Output: `List[ClassifiedEvent]`

**5. Temporal** (`temporal.py`): tense detection (past/present/future/unknown), actionability (past=0.1-0.3, present=0.7-1.0, future=0.4-0.6), time expression extraction, urgency scoring (0-1)

**6. Thread Consensus** (`thread.py`): analyzes `ThreadSnapshot.top_comments` -- polarity std dev for consensus, OP agreement score, contrarian detection, quality weighting (score x log(length)). Output: `ThreadResult`

## Sarcasm Detection (8 Rules)

| # | Trigger -> boost |
|---|-----------------|
| 1 | ALL-CAPS positive + negative context -> +0.35 |
| 2 | Clown emoji after statement -> +0.40 |
| 3 | Known phrases ("what could go wrong", "cant go tits up") -> +0.50 |
| 4 | Emoji contradiction (rocket + bearish) -> +0.30 |
| 5 | Quoted positive in negative context -> +0.25 |
| 6 | Excessive rockets, no substance -> +0.15 |
| 7 | "This is fine" + negative context -> +0.35 |
| 8 | Rhetorical question + positive -> +0.45 |

## Lexicon Structure

500+ terms in `lexicon.py`. Categories: action, outcome, descriptor, emoji, slang, modifier. Domains: general, options, technical, wsb_slang, macro. Per-term fields: `polarity` (-1..+1), `intensity` (0..1), `conviction` (0..1).

## Pipeline Integration

1. **EventBuilder** (Stage 4): `EventBuilder(nlp_engine=NLPEngine())` uses full NLP analysis; falls back to legacy regex if not provided
2. **LLM Prompt** (Stage 7): NLP results (polarity, conviction, sarcasm, classifications, tense, consensus, per-ticker sentiment) included in event prompt
3. **Credibility** (Stage 6): sarcasm, conviction, consensus, actionability feed into heuristic + ML scoring

NLP engine is optional -- pipeline continues via legacy regex path if unavailable.
