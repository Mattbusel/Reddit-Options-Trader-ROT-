"""Tests for NLP Engine orchestrator.

Comprehensive tests for the NLP pipeline orchestrator that coordinates
tokenization, sentiment analysis, entity resolution, event classification,
temporal analysis, and thread consensus scoring.
"""

import pytest
from unittest.mock import Mock, patch
import time

from rot.core.types import Comment
from rot.nlp.engine import NLPEngine
from rot.nlp.types import (
    NLPResult,
    SentimentResult,
    SentimentSignal,
    ResolvedEntity,
    OptionsEntity,
    PositionEntity,
    ClassifiedEvent,
    TemporalResult,
    ThreadResult,
    CommentAnalysis,
    Token,
)


# ============================================================================
# NLPEngine basic initialization
# ============================================================================


def test_nlp_engine_initialization():
    """Test NLPEngine initializes all components."""
    engine = NLPEngine()

    # All components should be initialized
    assert engine._tokenizer is not None
    assert engine._sentiment is not None
    assert engine._entities is not None
    assert engine._classifier is not None
    assert engine._temporal is not None
    assert engine._thread is not None


# ============================================================================
# 7-stage pipeline integration tests
# ============================================================================


def test_analyze_full_pipeline_integration():
    """Test analyze() runs all 7 pipeline stages successfully."""
    engine = NLPEngine()

    title = "$TSLA bullish momentum"
    body = "Tesla is looking great! Earnings beat expected. Buying calls."

    result = engine.analyze(title, body)

    # 1. Tokenization (reflected in token_count)
    assert result.token_count > 0

    # 2. Sentiment analysis (always present)
    assert result.sentiment is not None
    assert isinstance(result.sentiment, SentimentResult)

    # 3. Entity resolution (should find TSLA)
    assert len(result.entities) > 0
    assert any(e.symbol == "TSLA" for e in result.entities)

    # 4. Classification (should have some event category)
    assert len(result.classifications) > 0

    # 5. Temporal analysis (present if no error)
    assert result.temporal is not None
    assert isinstance(result.temporal, TemporalResult)

    # 6. Thread analysis (None when no comments)
    assert result.thread is None

    # 7. Derived fields (always present)
    assert "TSLA" in result.ticker_symbols
    assert result.primary_stance in ["bullish", "bearish", "mixed", "unknown"]
    assert result.primary_event_type != ""
    assert result.processing_time_ms > 0


def test_analyze_with_comments_includes_thread_analysis():
    """Test analyze() with comments runs thread consensus analysis."""
    engine = NLPEngine()

    title = "$AAPL to the moon"
    body = "Apple is going to explode upward!"
    comments = [
        Comment(
            id="c1",
            created_utc=int(time.time()),
            author="user1",
            body="Totally agree, bullish AF",
            score=10,
        ),
        Comment(
            id="c2",
            created_utc=int(time.time()),
            author="user2",
            body="This is the way! 🚀",
            score=5,
        ),
    ]

    result = engine.analyze(title, body, comments)

    # Thread analysis should be present
    assert result.thread is not None
    assert isinstance(result.thread, ThreadResult)
    assert result.thread.comment_count_analyzed == 2
    assert len(result.thread.comment_analyses) == 2

    # Consensus should be positive (all comments bullish)
    assert result.thread.consensus_polarity > 0
    assert result.thread.agreement_with_op > 0.5


def test_analyze_without_comments_thread_is_none():
    """Test analyze() without comments has None thread result."""
    engine = NLPEngine()

    result = engine.analyze("Test title", "Test body")

    assert result.thread is None


def test_analyze_empty_comments_thread_is_none():
    """Test analyze() with empty comment list has None thread result."""
    engine = NLPEngine()

    result = engine.analyze("Test title", "Test body", comments=[])

    assert result.thread is None


# ============================================================================
# Graceful degradation tests (component failures)
# ============================================================================


def test_analyze_graceful_degradation_entity_failure():
    """Test analyze() continues when entity resolution fails."""
    engine = NLPEngine()

    # Mock entity resolver to raise exception
    with patch.object(engine._entities, 'resolve', side_effect=Exception("Entity error")):
        result = engine.analyze("$TSLA test", "Body text")

    # Should complete with empty entities
    assert result.entities == []
    assert result.options_entities == []
    assert result.positions == []

    # Other components still work
    assert result.sentiment is not None
    assert result.token_count > 0


def test_analyze_graceful_degradation_classifier_failure():
    """Test analyze() continues when classification fails."""
    engine = NLPEngine()

    with patch.object(engine._classifier, 'classify', side_effect=Exception("Classifier error")):
        result = engine.analyze("Test title", "Test body")

    # Should complete with empty classifications
    assert result.classifications == []

    # Primary event type defaults to "other"
    assert result.primary_event_type == "other"

    # Other components still work
    assert result.sentiment is not None
    assert result.token_count > 0


def test_analyze_graceful_degradation_temporal_failure():
    """Test analyze() continues when temporal analysis fails."""
    engine = NLPEngine()

    with patch.object(engine._temporal, 'analyze', side_effect=Exception("Temporal error")):
        result = engine.analyze("Test title", "Test body")

    # Should complete with None temporal
    assert result.temporal is None

    # Other components still work
    assert result.sentiment is not None
    assert result.token_count > 0


def test_analyze_graceful_degradation_thread_failure():
    """Test analyze() continues when thread analysis fails."""
    engine = NLPEngine()

    comments = [
        Comment(
            id="c1",
            created_utc=int(time.time()),
            author="user1",
            body="Test comment",
            score=1,
        )
    ]

    with patch.object(engine._thread, 'analyze', side_effect=Exception("Thread error")):
        result = engine.analyze("Test title", "Test body", comments)

    # Should complete with None thread
    assert result.thread is None

    # Other components still work
    assert result.sentiment is not None
    assert result.token_count > 0


def test_analyze_graceful_degradation_multiple_failures():
    """Test analyze() continues when multiple components fail."""
    engine = NLPEngine()

    with patch.object(engine._entities, 'resolve', side_effect=Exception("Entity error")), \
         patch.object(engine._classifier, 'classify', side_effect=Exception("Classifier error")), \
         patch.object(engine._temporal, 'analyze', side_effect=Exception("Temporal error")):

        result = engine.analyze("Test title", "Test body")

    # Should complete with empty/None for failed components
    assert result.entities == []
    assert result.classifications == []
    assert result.temporal is None

    # Core components still work
    assert result.sentiment is not None
    assert result.token_count > 0
    assert result.processing_time_ms > 0


# ============================================================================
# Stance mapping tests
# ============================================================================


def test_derive_stance_bullish_high_polarity():
    """Test stance derivation for strongly bullish sentiment."""
    engine = NLPEngine()

    result = engine.analyze("$AAPL to the moon! 🚀🚀🚀", "Bullish AF! Buying calls!")

    # Should be bullish with high polarity
    assert result.primary_stance == "bullish"
    assert result.sentiment.polarity > 0.15


def test_derive_stance_bearish_high_polarity():
    """Test stance derivation for strongly bearish sentiment."""
    engine = NLPEngine()

    result = engine.analyze("$TSLA crashing", "Bearish! Stock is tanking. Buying puts.")

    # Should be bearish with negative polarity
    assert result.primary_stance == "bearish"
    assert result.sentiment.polarity < -0.15


def test_derive_stance_mixed_bullish_and_bearish():
    """Test stance derivation for mixed sentiment."""
    # Create a mock sentiment result with mixed signals
    sentiment = SentimentResult(
        polarity=0.05,  # Near zero
        intensity=0.5,
        conviction=0.5,
        sarcasm_probability=0.0,
        bullish_count=3,
        bearish_count=3,  # Equal counts
    )

    stance = NLPEngine._derive_stance(sentiment, None)

    assert stance == "mixed"


def test_derive_stance_unknown_low_polarity():
    """Test stance derivation for unknown (low polarity, no clear signals)."""
    # Create a mock sentiment result with low polarity
    sentiment = SentimentResult(
        polarity=0.05,  # Near zero
        intensity=0.2,
        conviction=0.3,
        sarcasm_probability=0.0,
        bullish_count=0,
        bearish_count=0,
    )

    stance = NLPEngine._derive_stance(sentiment, None)

    assert stance == "unknown"


def test_derive_stance_thread_disagreement_mixed():
    """Test stance becomes mixed when thread strongly disagrees with OP."""
    sentiment = SentimentResult(
        polarity=0.8,  # Strongly bullish
        intensity=0.9,
        conviction=0.8,
        sarcasm_probability=0.0,
        bullish_count=5,
        bearish_count=0,
    )

    thread = ThreadResult(
        consensus_polarity=-0.5,  # Bearish consensus
        consensus_score=0.8,
        agreement_with_op=0.2,  # Low agreement
        contrarian_detected=True,
        top_comment_aligns=False,
        comment_count_analyzed=10,
    )

    stance = NLPEngine._derive_stance(sentiment, thread)

    # Should be mixed due to thread disagreement
    assert stance == "mixed"


def test_derive_stance_high_sarcasm_unknown():
    """Test stance becomes unknown when high sarcasm and low polarity."""
    sentiment = SentimentResult(
        polarity=0.1,  # Low polarity
        intensity=0.5,
        conviction=0.3,
        sarcasm_probability=0.8,  # High sarcasm
        bullish_count=1,
        bearish_count=1,
    )

    stance = NLPEngine._derive_stance(sentiment, None)

    assert stance == "unknown"


def test_derive_stance_thread_agreement_preserves_bullish():
    """Test thread agreement preserves bullish stance."""
    sentiment = SentimentResult(
        polarity=0.6,  # Bullish
        intensity=0.8,
        conviction=0.7,
        sarcasm_probability=0.0,
        bullish_count=5,
        bearish_count=0,
    )

    thread = ThreadResult(
        consensus_polarity=0.7,  # Also bullish
        consensus_score=0.9,
        agreement_with_op=0.9,  # High agreement
        contrarian_detected=False,
        top_comment_aligns=True,
        comment_count_analyzed=10,
    )

    stance = NLPEngine._derive_stance(sentiment, thread)

    assert stance == "bullish"


# ============================================================================
# Primary event type derivation
# ============================================================================


def test_primary_event_type_highest_confidence():
    """Test primary_event_type is the highest confidence classification."""
    engine = NLPEngine()

    # Create mock classifications (classifier would return sorted by confidence)
    with patch.object(engine._classifier, 'classify', return_value=[
        ClassifiedEvent(category="earnings_rumor", confidence=0.8, evidence_spans=[], matched_terms=[]),
        ClassifiedEvent(category="product_news", confidence=0.6, evidence_spans=[], matched_terms=[]),
        ClassifiedEvent(category="squeeze_chatter", confidence=0.4, evidence_spans=[], matched_terms=[]),
    ]):
        result = engine.analyze("Earnings beat expected", "Revenue up 20%")

    # Should be first classification (highest confidence)
    assert result.primary_event_type == "earnings_rumor"


def test_primary_event_type_no_classifications():
    """Test primary_event_type defaults to 'other' when no classifications."""
    engine = NLPEngine()

    with patch.object(engine._classifier, 'classify', return_value=[]):
        result = engine.analyze("Random text", "No clear event")

    assert result.primary_event_type == "other"


# ============================================================================
# Ticker symbol extraction
# ============================================================================


def test_ticker_symbols_top_5_sorted():
    """Test ticker_symbols returns top 5 entities sorted."""
    engine = NLPEngine()

    # Create mock entities (confidence >= 0.3 threshold)
    mock_entities = [
        ResolvedEntity("TSLA", "$TSLA", "cashtag", 0.9, (0, 5)),
        ResolvedEntity("AAPL", "AAPL", "bare_ticker", 0.8, (6, 10)),
        ResolvedEntity("NVDA", "$NVDA", "cashtag", 0.7, (11, 16)),
        ResolvedEntity("SPY", "SPY", "bare_ticker", 0.6, (17, 20)),
        ResolvedEntity("QQQ", "QQQ", "bare_ticker", 0.5, (21, 24)),
        ResolvedEntity("AMD", "AMD", "bare_ticker", 0.4, (25, 28)),  # 6th entity
        ResolvedEntity("WEAK", "weak", "bare_ticker", 0.2, (29, 33)),  # Below threshold
    ]

    with patch.object(engine._entities, 'resolve', return_value=(mock_entities, [], [])):
        result = engine.analyze("Test", "Test")

    # Should have top 5, sorted alphabetically
    assert len(result.ticker_symbols) == 5
    assert result.ticker_symbols == ["AAPL", "AMD", "NVDA", "QQQ", "SPY", "TSLA"][:5]  # sorted, first 5


def test_ticker_symbols_confidence_threshold():
    """Test ticker_symbols filters by confidence >= 0.3."""
    engine = NLPEngine()

    mock_entities = [
        ResolvedEntity("STRONG", "STRONG", "cashtag", 0.9, (0, 6)),
        ResolvedEntity("MEDIUM", "MEDIUM", "bare_ticker", 0.4, (7, 13)),
        ResolvedEntity("WEAK", "WEAK", "bare_ticker", 0.2, (14, 18)),  # Below threshold
        ResolvedEntity("VWEAK", "VWEAK", "bare_ticker", 0.1, (19, 24)),  # Below threshold
    ]

    with patch.object(engine._entities, 'resolve', return_value=(mock_entities, [], [])):
        result = engine.analyze("Test", "Test")

    # Should only have entities with confidence >= 0.3
    assert "STRONG" in result.ticker_symbols
    assert "MEDIUM" in result.ticker_symbols
    assert "WEAK" not in result.ticker_symbols
    assert "VWEAK" not in result.ticker_symbols


def test_ticker_symbols_deduplication():
    """Test ticker_symbols deduplicates repeated symbols."""
    engine = NLPEngine()

    # Same ticker mentioned multiple times
    mock_entities = [
        ResolvedEntity("TSLA", "$TSLA", "cashtag", 0.9, (0, 5)),
        ResolvedEntity("TSLA", "Tesla", "implicit", 0.8, (6, 11)),
        ResolvedEntity("TSLA", "TSLA", "bare_ticker", 0.7, (12, 16)),
        ResolvedEntity("AAPL", "AAPL", "bare_ticker", 0.6, (17, 21)),
    ]

    with patch.object(engine._entities, 'resolve', return_value=(mock_entities, [], [])):
        result = engine.analyze("Test", "Test")

    # Should have unique symbols only
    assert result.ticker_symbols.count("TSLA") == 1
    assert len(result.ticker_symbols) == 2  # TSLA and AAPL


def test_ticker_symbols_empty_when_no_entities():
    """Test ticker_symbols is empty when no entities found."""
    engine = NLPEngine()

    with patch.object(engine._entities, 'resolve', return_value=([], [], [])):
        result = engine.analyze("No tickers here", "Just random text")

    assert result.ticker_symbols == []


# ============================================================================
# Processing time tracking
# ============================================================================


def test_processing_time_ms_populated():
    """Test processing_time_ms is populated and reasonable."""
    engine = NLPEngine()

    result = engine.analyze("Test title", "Test body")

    # Should have processing time > 0
    assert result.processing_time_ms > 0

    # Should be reasonable (< 1 second for simple input)
    assert result.processing_time_ms < 1000


def test_processing_time_increases_with_comments():
    """Test processing time increases with comment analysis."""
    engine = NLPEngine()

    # Without comments
    result1 = engine.analyze("Test", "Test")

    # With many comments
    comments = [
        Comment(
            id=f"c{i}",
            created_utc=int(time.time()),
            author=f"user{i}",
            body=f"Comment {i} with some text",
            score=i,
        )
        for i in range(10)
    ]
    result2 = engine.analyze("Test", "Test", comments)

    # Processing time should be higher with comments
    assert result2.processing_time_ms > result1.processing_time_ms


# ============================================================================
# Token count tracking
# ============================================================================


def test_token_count_populated():
    """Test token_count reflects total tokens from title + body."""
    engine = NLPEngine()

    result = engine.analyze("Short title", "Short body")

    # Should have some tokens
    assert result.token_count > 0


def test_token_count_increases_with_text():
    """Test token_count increases with more text."""
    engine = NLPEngine()

    result1 = engine.analyze("Short", "Text")
    result2 = engine.analyze(
        "This is a much longer title with many words",
        "This is a much longer body with even more words and sentences."
    )

    # Longer text should have more tokens
    assert result2.token_count > result1.token_count


# ============================================================================
# Edge cases
# ============================================================================


def test_analyze_empty_input():
    """Test analyze() with empty strings."""
    engine = NLPEngine()

    result = engine.analyze("", "")

    # Should complete without error
    assert result is not None
    assert result.token_count >= 0
    assert result.sentiment is not None
    assert result.processing_time_ms > 0


def test_analyze_only_whitespace():
    """Test analyze() with only whitespace."""
    engine = NLPEngine()

    result = engine.analyze("   ", "   \n\n  ")

    # Should complete without error
    assert result is not None
    assert result.sentiment is not None


def test_analyze_very_long_text():
    """Test analyze() with very long text doesn't break."""
    engine = NLPEngine()

    # Generate long text
    long_text = " ".join(["word"] * 1000)

    result = engine.analyze("Title", long_text)

    # Should complete without error
    assert result is not None
    assert result.token_count > 500  # Should have many tokens


def test_analyze_special_characters():
    """Test analyze() with special characters."""
    engine = NLPEngine()

    result = engine.analyze(
        "Test 💎🙌 with emojis",
        "Body with $pecial ch@rs & symbols! #test"
    )

    # Should complete without error
    assert result is not None
    assert result.sentiment is not None


def test_analyze_unicode_text():
    """Test analyze() with unicode characters."""
    engine = NLPEngine()

    result = engine.analyze(
        "Test with unicode: café résumé",
        "More unicode: 日本語 中文 한국어"
    )

    # Should complete without error
    assert result is not None
    assert result.sentiment is not None


# ============================================================================
# extract_tickers() method tests
# ============================================================================


def test_extract_tickers_returns_list():
    """Test extract_tickers() returns list of ticker strings."""
    engine = NLPEngine()

    tickers = engine.extract_tickers("$TSLA is great", "Also check out $AAPL")

    assert isinstance(tickers, list)
    assert len(tickers) > 0


def test_extract_tickers_basic_cashtags():
    """Test extract_tickers() extracts basic cashtags."""
    engine = NLPEngine()

    tickers = engine.extract_tickers("$TSLA and $AAPL", "Also $NVDA")

    # Should find all three tickers
    assert "TSLA" in tickers
    assert "AAPL" in tickers
    assert "NVDA" in tickers


def test_extract_tickers_graceful_degradation():
    """Test extract_tickers() returns empty list on entity resolver failure."""
    engine = NLPEngine()

    with patch.object(engine._entities, 'extract_tickers_only', side_effect=Exception("Error")):
        tickers = engine.extract_tickers("$TSLA test", "Body")

    # Should return empty list, not raise
    assert tickers == []


def test_extract_tickers_empty_input():
    """Test extract_tickers() with empty input."""
    engine = NLPEngine()

    tickers = engine.extract_tickers("", "")

    # Should return empty list or minimal result
    assert isinstance(tickers, list)


# ============================================================================
# Full integration test with realistic Reddit post
# ============================================================================


def test_full_integration_realistic_reddit_post():
    """Test full pipeline with realistic Reddit post data.

    This integration test simulates a real-world WSB post with:
    - Multiple tickers
    - Strong sentiment
    - Emojis
    - Slang
    - Comments with varying sentiment
    """
    engine = NLPEngine()

    title = "$TSLA to the moon! 🚀🚀🚀 Earnings beat!"
    body = """
    Just saw the earnings report and Tesla CRUSHED it! Revenue up 30%,
    EPS beat by $0.50. This is going to $500 by end of month.

    My positions:
    - 10x TSLA 450C 2/18
    - Adding more if it dips below $420

    This is not financial advice, I'm just a retard who likes the stock.
    Diamond hands 💎🙌
    """

    comments = [
        Comment(
            id="c1",
            created_utc=int(time.time()),
            author="bull_user",
            body="100% agree! TSLA 🚀🚀🚀 Loading up on calls!",
            score=50,
        ),
        Comment(
            id="c2",
            created_utc=int(time.time()),
            author="bear_user",
            body="You guys are delusional. This stock is overvalued. Buying puts.",
            score=5,
        ),
        Comment(
            id="c3",
            created_utc=int(time.time()),
            author="neutral_user",
            body="Interesting play. What's your exit strategy?",
            score=10,
        ),
    ]

    result = engine.analyze(title, body, comments)

    # === Sentiment ===
    assert result.sentiment is not None
    assert result.sentiment.polarity > 0.3  # Should be bullish
    assert result.sentiment.bullish_count > result.sentiment.bearish_count

    # === Entities ===
    assert "TSLA" in result.ticker_symbols
    assert len(result.entities) > 0

    # === Classifications ===
    assert len(result.classifications) > 0
    # Should likely classify as earnings_rumor or product_news
    assert any(
        c.category in ["earnings_rumor", "product_news", "squeeze_chatter"]
        for c in result.classifications
    )

    # === Temporal ===
    assert result.temporal is not None
    # Should detect temporal signals (tense can vary based on specific phrases)
    assert result.temporal.dominant_tense in ["past", "present", "future"]
    assert result.temporal.actionability > 0.5

    # === Thread ===
    assert result.thread is not None
    assert result.thread.comment_count_analyzed == 3
    # Should have mixed consensus (2 bullish, 1 bearish)
    assert result.thread.consensus_score < 1.0  # Not perfect consensus

    # === Derived fields ===
    assert result.primary_stance == "bullish"  # Overall bullish post
    assert result.primary_event_type != "other"  # Should have event classification

    # === Processing ===
    assert result.token_count > 50  # Substantial text
    assert result.processing_time_ms > 0
    assert result.processing_time_ms < 5000  # Should be fast


# ============================================================================
# Multiple stances with different patterns
# ============================================================================


@pytest.mark.parametrize("title,body,expected_stance", [
    ("$TSLA bullish!", "Going to the moon 🚀", "bullish"),
    ("$TSLA bearish", "Crashing hard, buying puts", "bearish"),
    ("$TSLA neutral", "Stock is flat, no clear trend either way", "unknown"),  # Low polarity → unknown
    ("$TSLA no clear direction", "Just trading sideways", "unknown"),
])
def test_stance_detection_patterns(title, body, expected_stance):
    """Test stance detection with various sentiment patterns."""
    engine = NLPEngine()

    result = engine.analyze(title, body)

    # Should match expected stance
    assert result.primary_stance == expected_stance


# ============================================================================
# Different entity types preservation
# ============================================================================


def test_all_entity_types_preserved():
    """Test all entity types (tickers, options, positions) are preserved."""
    engine = NLPEngine()

    mock_entities = [
        ResolvedEntity("TSLA", "$TSLA", "cashtag", 0.9, (0, 5)),
    ]
    mock_options = [
        OptionsEntity("TSLA", 450.0, "call", "2/18", "TSLA 450C 2/18", (10, 24)),
    ]
    mock_positions = [
        PositionEntity("long", 100, "shares", "100 shares", (30, 40)),
    ]

    with patch.object(
        engine._entities,
        'resolve',
        return_value=(mock_entities, mock_options, mock_positions)
    ):
        result = engine.analyze("Test", "Test")

    # All entity types should be preserved
    assert len(result.entities) == 1
    assert len(result.options_entities) == 1
    assert len(result.positions) == 1
    assert result.entities[0].symbol == "TSLA"
    assert result.options_entities[0].strike == 450.0
    assert result.positions[0].position_type == "long"


# ============================================================================
# NLPResult frozen/immutable tests
# ============================================================================


def test_nlp_result_frozen():
    """Test NLPResult is frozen (immutable)."""
    engine = NLPEngine()

    result = engine.analyze("Test", "Test")

    # Should not be able to modify
    with pytest.raises(Exception):  # FrozenInstanceError
        result.primary_stance = "modified"


def test_nlp_result_reproducible():
    """Test same input produces consistent results."""
    engine = NLPEngine()

    title = "Test title with $AAPL"
    body = "Test body"

    result1 = engine.analyze(title, body)
    result2 = engine.analyze(title, body)

    # Core fields should be identical
    assert result1.primary_stance == result2.primary_stance
    assert result1.ticker_symbols == result2.ticker_symbols
    assert result1.sentiment.polarity == result2.sentiment.polarity
    assert result1.token_count == result2.token_count
