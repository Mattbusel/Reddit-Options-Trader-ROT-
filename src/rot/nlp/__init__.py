"""ROT Custom NLP Engine — financial-aware text intelligence.

The NLP engine provides:
- Financial-aware tokenization (cashtags, emojis, options contracts)
- 500+ term sentiment lexicon tuned for Reddit finance slang
- 8-rule sarcasm detection heuristics
- Conviction scoring (hedge-word detection)
- Context-aware entity resolution (CEO names, sector expansion)
- Multi-label event classification (14 categories)
- Temporal analysis (tense, actionability, urgency)
- Thread consensus scoring (comment sentiment distribution)

Usage:
    from rot.nlp import NLPEngine

    engine = NLPEngine()
    result = engine.analyze(title="$TSLA to the moon!", body="Buying calls...")

    print(result.primary_stance)        # "bullish"
    print(result.ticker_symbols)        # ["TSLA"]
    print(result.sentiment.polarity)    # 0.85
    print(result.sentiment.conviction)  # 0.7
    print(result.sentiment.sarcasm_probability)  # 0.0
"""
from rot.nlp.engine import NLPEngine
from rot.nlp.types import NLPResult, SentimentResult, ResolvedEntity

__all__ = ["NLPEngine", "NLPResult", "SentimentResult", "ResolvedEntity"]
