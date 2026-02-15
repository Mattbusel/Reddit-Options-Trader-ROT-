"""Parametrized NLP tests.

Comprehensive parametrized coverage for stance detection, entity extraction,
and confidence scoring using the NLP engine.
"""
from __future__ import annotations

import pytest
from rot.nlp.engine import NLPEngine
from rot.nlp.tokenizer import Tokenizer


# ---------------------------------------------------------------------------
# Stance / sentiment detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,body,expected_stance", [
    ("$TSLA bullish!", "Going to the moon", "bullish"),
    ("$TSLA bearish", "Crashing hard, buying puts", "bearish"),
    ("$TSLA neutral", "Stock is flat, no clear trend either way", "unknown"),
    ("$TSLA no clear direction", "Just trading sideways", "unknown"),
    ("$AAPL calls printing!", "Bought calls, this is going up big", "bullish"),
    ("$AMD puts are the play", "This stock is going to tank hard", "bearish"),
    ("NVDA earnings beat big", "Stock surging after hours, calls are printing", "bullish"),
    ("SPY crashing", "Market in freefall, puts everywhere", "bearish"),
])
def test_stance_detection(title, body, expected_stance):
    """NLP engine detects correct stance from title+body."""
    engine = NLPEngine()
    result = engine.analyze(title, body)
    assert result.primary_stance == expected_stance, (
        f"Expected {expected_stance} for '{title}', got {result.primary_stance}"
    )


# ---------------------------------------------------------------------------
# Entity (ticker) extraction via NLPEngine
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,body,expected_tickers", [
    ("$AAPL is going up!", "Calls printing", ["AAPL"]),
    ("$TSLA and $NVDA are printing", "Big moves", ["TSLA", "NVDA"]),
    ("$QQQ puts are the play", "Bearish setup", ["QQQ"]),
])
def test_entity_extraction(title, body, expected_tickers):
    """NLP engine extracts ticker symbols from text."""
    engine = NLPEngine()
    result = engine.analyze(title, body)
    for ticker in expected_tickers:
        assert ticker in result.ticker_symbols, (
            f"Expected {ticker} in {result.ticker_symbols}"
        )


# ---------------------------------------------------------------------------
# NLP engine full analysis — confidence ranges
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,body,expected_polarity_sign", [
    ("$TSLA TO THE MOON!", "Massive call volume, earnings beat, going up!", "positive"),
    ("$SPY crashing hard", "Market dumping, puts printing, bearish", "negative"),
])
def test_sentiment_polarity_direction(title, body, expected_polarity_sign):
    """NLP sentiment polarity matches expected direction."""
    engine = NLPEngine()
    result = engine.analyze(title, body)
    if expected_polarity_sign == "positive":
        assert result.sentiment.polarity > 0, (
            f"Expected positive polarity, got {result.sentiment.polarity}"
        )
    else:
        assert result.sentiment.polarity < 0, (
            f"Expected negative polarity, got {result.sentiment.polarity}"
        )


# ---------------------------------------------------------------------------
# Tokenizer — edge cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_min_tokens", [
    ("Hello world", 2),
    ("", 0),
    ("$AAPL", 1),
    ("A very long sentence with many words to test tokenization", 8),
])
def test_tokenizer_basic(text, expected_min_tokens):
    """Tokenizer produces expected minimum token counts."""
    tokenizer = Tokenizer()
    tokens = tokenizer.tokenize(text)
    assert len(tokens) >= expected_min_tokens
