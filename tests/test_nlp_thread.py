"""Tests for rot.nlp.thread - Thread/comment consensus analysis.

Comprehensive test coverage for the NLP thread analyzer that handles:
- Consensus polarity (weighted average by score × log(length/50))
- Consensus score (1.0 - std_dev_of_polarities, clamped [0-1])
- Agreement with OP (sign comparison + magnitude delta)
- Contrarian detection (high-scoring comment contradicts majority)
- Top comment alignment (binary check if top comment agrees with OP)
- Quality weighting (higher score + longer length = more weight)
- Empty comments list → None result
- Single comment → consensus_score=0.5 (neutral consensus)
- Edge cases (all neutral, extreme polarities, equal split)
"""
import pytest
from unittest.mock import Mock

from rot.core.types import Comment
from rot.nlp.thread import ThreadAnalyzer
from rot.nlp.types import SentimentResult, ThreadResult


@pytest.fixture
def mock_sentiment_analyzer():
    """Provide a mock sentiment analyzer that returns configurable results."""
    analyzer = Mock()
    # Default: return neutral sentiment
    analyzer.analyze_text.return_value = SentimentResult(
        polarity=0.0,
        intensity=0.0,
        conviction=0.5,
        sarcasm_probability=0.0,
    )
    return analyzer


@pytest.fixture
def thread_analyzer(mock_sentiment_analyzer):
    """Provide a fresh ThreadAnalyzer instance for each test."""
    return ThreadAnalyzer(mock_sentiment_analyzer)


@pytest.fixture
def op_sentiment():
    """Provide a default OP sentiment for tests."""
    return SentimentResult(
        polarity=0.6,
        intensity=0.7,
        conviction=0.8,
        sarcasm_probability=0.0,
    )


def make_comment(comment_id: str, author: str, body: str, score: int = 1) -> Comment:
    """Helper to create a Comment instance."""
    return Comment(
        id=comment_id,
        created_utc=1234567890.0,
        author=author,
        body=body,
        score=score,
    )


class TestEmptyComments:
    """Test handling of empty comment lists."""

    def test_empty_comments_list(self, thread_analyzer, op_sentiment):
        """Empty comments should return a zero-state ThreadResult."""
        result = thread_analyzer.analyze(op_sentiment, [])

        assert result.consensus_polarity == 0.0
        assert result.consensus_score == 0.0
        assert result.agreement_with_op == 0.5
        assert result.contrarian_detected is False
        assert result.top_comment_aligns is None
        assert result.comment_count_analyzed == 0
        assert len(result.comment_analyses) == 0

    def test_none_sentiment_all_comments_fail(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """If all comments fail sentiment analysis, should return zero-state."""
        # Make sentiment analyzer raise exception for all comments
        mock_sentiment_analyzer.analyze_text.side_effect = Exception("Analysis failed")

        comments = [
            make_comment("c1", "user1", "Test comment", score=10),
            make_comment("c2", "user2", "Another comment", score=5),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        assert result.consensus_polarity == 0.0
        assert result.consensus_score == 0.0
        assert result.agreement_with_op == 0.5
        assert result.contrarian_detected is False
        assert result.top_comment_aligns is None
        assert result.comment_count_analyzed == 0


class TestSingleComment:
    """Test handling of a single comment."""

    def test_single_comment_neutral_consensus(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Single comment should yield consensus_score=0.5 (neutral)."""
        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [make_comment("c1", "user1", "Bullish comment!", score=10)]
        result = thread_analyzer.analyze(op_sentiment, comments)

        # Single comment = no variance = neutral consensus score
        assert result.consensus_score == 0.5
        assert result.consensus_polarity == 0.7
        assert result.comment_count_analyzed == 1
        assert len(result.comment_analyses) == 1

    def test_single_comment_top_alignment(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Single comment should be checked for OP alignment."""
        # OP sentiment is 0.6 (bullish), comment is 0.7 (bullish)
        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [make_comment("c1", "user1", "I agree!", score=10)]
        result = thread_analyzer.analyze(op_sentiment, comments)

        # Both bullish → should align
        assert result.top_comment_aligns is True

    def test_single_comment_top_misalignment(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Single bearish comment vs bullish OP should not align."""
        # OP sentiment is 0.6 (bullish), comment is -0.7 (bearish)
        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=-0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [make_comment("c1", "user1", "This is bearish!", score=10)]
        result = thread_analyzer.analyze(op_sentiment, comments)

        # Opposite signs → should not align
        assert result.top_comment_aligns is False


class TestConsensusPolarity:
    """Test consensus polarity calculation (weighted average)."""

    def test_consensus_polarity_simple_average(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """With equal weights, consensus should be simple average."""
        # Two comments with same score/length → equal weights
        polarities = [0.5, -0.5]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "A" * 50, score=10),  # Same length and score
            make_comment("c2", "user2", "B" * 50, score=10),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Average of 0.5 and -0.5 = 0.0
        assert result.consensus_polarity == 0.0

    def test_consensus_polarity_weighted_by_score(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Higher score comments should have more weight in consensus."""
        polarities = [0.8, -0.2]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "A" * 50, score=100),  # High score, bullish
            make_comment("c2", "user2", "B" * 50, score=1),    # Low score, bearish
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Should be weighted heavily toward 0.8 due to 100x score difference
        # (ignoring log length adjustment since both same length)
        assert result.consensus_polarity > 0.6

    def test_consensus_polarity_weighted_by_length(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Longer comments should have slightly more weight."""
        polarities = [0.8, -0.2]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "Short", score=10),      # 5 chars
            make_comment("c2", "user2", "A" * 500, score=10),    # 500 chars
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Second comment is much longer, so should weight toward -0.2
        # But log dampens the effect
        assert result.consensus_polarity < 0.8

    def test_consensus_polarity_all_bullish(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """All bullish comments should yield bullish consensus."""
        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [
            make_comment("c1", "user1", "Bullish!", score=10),
            make_comment("c2", "user2", "To the moon!", score=5),
            make_comment("c3", "user3", "YOLO!", score=20),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        assert result.consensus_polarity > 0.6

    def test_consensus_polarity_all_bearish(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """All bearish comments should yield bearish consensus."""
        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=-0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [
            make_comment("c1", "user1", "Bearish!", score=10),
            make_comment("c2", "user2", "Dump it!", score=5),
            make_comment("c3", "user3", "Puts!", score=20),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        assert result.consensus_polarity < -0.6


class TestConsensusScore:
    """Test consensus score calculation (agreement among commenters)."""

    def test_consensus_score_high_agreement(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """All comments with similar polarity → high consensus."""
        # All comments ~0.7 polarity
        polarities = [0.7, 0.71, 0.69, 0.72]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.7,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "Bullish!", score=10),
            make_comment("c2", "user2", "Agree!", score=5),
            make_comment("c3", "user3", "Moon!", score=8),
            make_comment("c4", "user4", "Rocket!", score=12),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Low variance → high consensus score (close to 1.0)
        assert result.consensus_score > 0.95

    def test_consensus_score_low_agreement(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Mixed polarities → low consensus score."""
        polarities = [0.8, -0.8, 0.6, -0.6]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "Bullish!", score=10),
            make_comment("c2", "user2", "Bearish!", score=10),
            make_comment("c3", "user3", "Buy!", score=10),
            make_comment("c4", "user4", "Sell!", score=10),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # High variance → low consensus score
        assert result.consensus_score < 0.3

    def test_consensus_score_all_neutral(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """All neutral comments → perfect consensus (1.0)."""
        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.0,
            intensity=0.0,
            conviction=0.5,
            sarcasm_probability=0.0,
        )

        comments = [
            make_comment("c1", "user1", "Neutral.", score=10),
            make_comment("c2", "user2", "Meh.", score=5),
            make_comment("c3", "user3", "Whatever.", score=8),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Zero variance → consensus_score = 1.0
        assert result.consensus_score == 1.0

    def test_consensus_score_clamped_to_range(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Consensus score should be clamped to [0.0, 1.0]."""
        # Extreme variance (std_dev could theoretically exceed 1.0)
        polarities = [1.0, -1.0, 1.0, -1.0]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "Max bullish!", score=10),
            make_comment("c2", "user2", "Max bearish!", score=10),
            make_comment("c3", "user3", "Max bullish!", score=10),
            make_comment("c4", "user4", "Max bearish!", score=10),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Should be clamped to 0.0
        assert 0.0 <= result.consensus_score <= 1.0


class TestAgreementWithOP:
    """Test agreement_with_op calculation."""

    def test_agreement_same_sign_bullish(
        self, thread_analyzer, mock_sentiment_analyzer
    ):
        """Bullish OP + bullish consensus → high agreement."""
        op = SentimentResult(polarity=0.6, intensity=0.7, conviction=0.8, sarcasm_probability=0.0)

        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [
            make_comment("c1", "user1", "Bullish!", score=10),
            make_comment("c2", "user2", "Moon!", score=5),
        ]

        result = thread_analyzer.analyze(op, comments)

        # Same sign → should have min 0.6 agreement
        assert result.agreement_with_op >= 0.6

    def test_agreement_same_sign_bearish(
        self, thread_analyzer, mock_sentiment_analyzer
    ):
        """Bearish OP + bearish consensus → high agreement."""
        op = SentimentResult(polarity=-0.6, intensity=0.7, conviction=0.8, sarcasm_probability=0.0)

        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=-0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [
            make_comment("c1", "user1", "Bearish!", score=10),
            make_comment("c2", "user2", "Dump!", score=5),
        ]

        result = thread_analyzer.analyze(op, comments)

        # Same sign → should have min 0.6 agreement
        assert result.agreement_with_op >= 0.6

    def test_agreement_opposite_signs(
        self, thread_analyzer, mock_sentiment_analyzer
    ):
        """Bullish OP + bearish consensus → low agreement."""
        op = SentimentResult(polarity=0.6, intensity=0.7, conviction=0.8, sarcasm_probability=0.0)

        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=-0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [
            make_comment("c1", "user1", "Bearish!", score=10),
            make_comment("c2", "user2", "Puts!", score=5),
        ]

        result = thread_analyzer.analyze(op, comments)

        # Opposite signs → should have max 0.4 agreement
        assert result.agreement_with_op <= 0.4

    def test_agreement_neutral_op(
        self, thread_analyzer, mock_sentiment_analyzer
    ):
        """Neutral OP (|polarity| < 0.05) → 0.5 agreement."""
        op = SentimentResult(polarity=0.02, intensity=0.1, conviction=0.5, sarcasm_probability=0.0)

        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [
            make_comment("c1", "user1", "Bullish!", score=10),
        ]

        result = thread_analyzer.analyze(op, comments)

        # Neutral OP → 0.5 agreement regardless of comments
        assert result.agreement_with_op == 0.5

    def test_agreement_magnitude_delta(
        self, thread_analyzer, mock_sentiment_analyzer
    ):
        """Agreement decreases with magnitude difference."""
        op = SentimentResult(polarity=0.3, intensity=0.5, conviction=0.6, sarcasm_probability=0.0)

        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.8,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [
            make_comment("c1", "user1", "Very bullish!", score=10),
        ]

        result = thread_analyzer.analyze(op, comments)

        # pol_diff = |0.3 - 0.8| = 0.5
        # agreement_with_op = 1.0 - 0.5/2.0 = 0.75
        # But same sign, so min 0.6
        assert result.agreement_with_op >= 0.6


class TestContrarianDetection:
    """Test contrarian comment detection."""

    def test_contrarian_detected_bearish_in_bullish_thread(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """High-score bearish comment in bullish thread → contrarian."""
        # Many bullish comments + one bearish contrarian
        # The contrarian polarity must be weak enough not to flip consensus
        polarities = [0.9, 0.85, 0.95, 0.9, 0.88, 0.92, -0.2]  # Last is weak bearish contrarian

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "Bullish!", score=10),
            make_comment("c2", "user2", "Moon!", score=8),
            make_comment("c3", "user3", "Rocket!", score=9),
            make_comment("c4", "user4", "YOLO!", score=11),
            make_comment("c5", "user5", "Calls!", score=7),
            make_comment("c6", "user6", "Buy!", score=10),
            make_comment("c7", "user7", "Bearish take", score=50),  # High score, contradicts
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Contrarian should be detected:
        # - consensus_polarity should be > 0.1 (bullish)
        # - contrarian comment has score=50 > median*2
        # - contrarian polarity=-0.2 < -0.15 (contradicts bullish consensus)
        assert result.contrarian_detected is True

    def test_contrarian_detected_bullish_in_bearish_thread(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """High-score bullish comment in bearish thread → contrarian."""
        # Many bearish comments + one bullish contrarian
        # The contrarian polarity must be weak enough not to flip consensus
        polarities = [-0.9, -0.85, -0.95, -0.9, -0.88, -0.92, 0.2]  # Last is weak bullish contrarian

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "Bearish!", score=10),
            make_comment("c2", "user2", "Dump!", score=8),
            make_comment("c3", "user3", "Puts!", score=9),
            make_comment("c4", "user4", "Sell!", score=11),
            make_comment("c5", "user5", "Crash!", score=7),
            make_comment("c6", "user6", "Down!", score=10),
            make_comment("c7", "user7", "Bullish take", score=50),  # High score, contradicts
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Contrarian should be detected:
        # - consensus_polarity should be < -0.1 (bearish)
        # - contrarian comment has score=50 > median*2
        # - contrarian polarity=0.2 > 0.15 (contradicts bearish consensus)
        assert result.contrarian_detected is True

    def test_no_contrarian_all_agree(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """No contrarian if all comments agree."""
        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [
            make_comment("c1", "user1", "Bullish!", score=10),
            make_comment("c2", "user2", "Moon!", score=50),  # High score, but agrees
            make_comment("c3", "user3", "Rocket!", score=5),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        assert result.contrarian_detected is False

    def test_no_contrarian_low_score_dissent(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Low-score dissenting comment is not contrarian."""
        polarities = [0.7, 0.6, 0.8, -0.5]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "Bullish!", score=10),
            make_comment("c2", "user2", "Moon!", score=8),
            make_comment("c3", "user3", "Rocket!", score=12),
            make_comment("c4", "user4", "Bearish!", score=2),  # Low score, doesn't trigger
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Score 2 is below threshold (median*2 = 10*2 = 20, or min 5)
        assert result.contrarian_detected is False

    def test_no_contrarian_fewer_than_3_comments(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Contrarian detection requires at least 3 comments."""
        polarities = [0.7, -0.8]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "Bullish!", score=10),
            make_comment("c2", "user2", "Bearish!", score=100),  # High score but <3 comments
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        assert result.contrarian_detected is False


class TestTopCommentAlignment:
    """Test top comment alignment with OP."""

    def test_top_comment_aligns_bullish(
        self, thread_analyzer, mock_sentiment_analyzer
    ):
        """Top bullish comment + bullish OP → aligns."""
        op = SentimentResult(polarity=0.6, intensity=0.7, conviction=0.8, sarcasm_probability=0.0)

        polarities = [0.7, -0.3]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "Bullish!", score=10),  # First = top
            make_comment("c2", "user2", "Bearish!", score=5),
        ]

        result = thread_analyzer.analyze(op, comments)

        assert result.top_comment_aligns is True

    def test_top_comment_misaligns(
        self, thread_analyzer, mock_sentiment_analyzer
    ):
        """Top bearish comment + bullish OP → does not align."""
        op = SentimentResult(polarity=0.6, intensity=0.7, conviction=0.8, sarcasm_probability=0.0)

        polarities = [-0.7, 0.3]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "Bearish!", score=10),  # First = top
            make_comment("c2", "user2", "Bullish!", score=5),
        ]

        result = thread_analyzer.analyze(op, comments)

        assert result.top_comment_aligns is False

    def test_top_comment_alignment_none_if_neutral_op(
        self, thread_analyzer, mock_sentiment_analyzer
    ):
        """Neutral OP (|polarity| < 0.1) → alignment is None."""
        op = SentimentResult(polarity=0.05, intensity=0.1, conviction=0.5, sarcasm_probability=0.0)

        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.0,
        )

        comments = [make_comment("c1", "user1", "Bullish!", score=10)]

        result = thread_analyzer.analyze(op, comments)

        assert result.top_comment_aligns is None

    def test_top_comment_alignment_none_if_neutral_comment(
        self, thread_analyzer, mock_sentiment_analyzer
    ):
        """Neutral top comment (|polarity| < 0.1) → alignment is None."""
        op = SentimentResult(polarity=0.6, intensity=0.7, conviction=0.8, sarcasm_probability=0.0)

        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.05,
            intensity=0.1,
            conviction=0.5,
            sarcasm_probability=0.0,
        )

        comments = [make_comment("c1", "user1", "Neutral.", score=10)]

        result = thread_analyzer.analyze(op, comments)

        assert result.top_comment_aligns is None


class TestQualityWeighting:
    """Test quality weighting (score × log(1 + length/50))."""

    def test_quality_weight_score_dominates(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Score should dominate the quality weight."""
        polarities = [0.8, -0.2]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "A" * 50, score=1000),  # Very high score
            make_comment("c2", "user2", "B" * 50, score=1),     # Very low score
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Consensus should be heavily weighted toward 0.8
        assert result.consensus_polarity > 0.7

    def test_quality_weight_length_adjusts(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Length should adjust weight via log dampening."""
        polarities = [0.5, -0.5]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "Short", score=10),      # 5 chars
            make_comment("c2", "user2", "A" * 1000, score=10),   # 1000 chars
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Weight1 = 10 * log(1 + 5/50) = 10 * log(1.1) ≈ 10 * 0.095 ≈ 0.95
        # Weight2 = 10 * log(1 + 1000/50) = 10 * log(21) ≈ 10 * 3.04 ≈ 30.4
        # So second comment has ~32x weight
        # Consensus should be weighted toward -0.5
        assert result.consensus_polarity < 0.0

    def test_quality_weight_min_score_is_1(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Score is clamped to min 1 to avoid zero weights."""
        polarities = [0.8, -0.2]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "A" * 50, score=0),   # Score 0 → clamped to 1
            make_comment("c2", "user2", "B" * 50, score=-5),  # Negative score → clamped to 1
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Both have effective score=1, so should be simple average
        # (0.8 + -0.2) / 2 = 0.3
        assert abs(result.consensus_polarity - 0.3) < 0.1


class TestMaxCommentsLimit:
    """Test MAX_COMMENTS cap (default 20)."""

    def test_max_comments_cap(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Should only analyze first MAX_COMMENTS comments."""
        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.5,
            intensity=0.5,
            conviction=0.5,
            sarcasm_probability=0.0,
        )

        # Create 30 comments (exceeds MAX_COMMENTS=20)
        comments = [
            make_comment(f"c{i}", f"user{i}", f"Comment {i}", score=10)
            for i in range(30)
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Should only analyze first 20
        assert result.comment_count_analyzed == 20
        assert len(result.comment_analyses) == 20


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_all_comments_equal_split(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Equal split of bullish/bearish → consensus near zero."""
        polarities = [0.8, 0.8, -0.8, -0.8]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "A" * 50, score=10),
            make_comment("c2", "user2", "B" * 50, score=10),
            make_comment("c3", "user3", "C" * 50, score=10),
            make_comment("c4", "user4", "D" * 50, score=10),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Should be near zero
        assert abs(result.consensus_polarity) < 0.1

    def test_extreme_polarities(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Extreme polarities at -1.0 and +1.0 should work."""
        polarities = [1.0, -1.0]

        def side_effect(text):
            idx = len(mock_sentiment_analyzer.analyze_text.call_args_list) - 1
            return SentimentResult(
                polarity=polarities[idx] if idx < len(polarities) else 0.0,
                intensity=0.5,
                conviction=0.5,
                sarcasm_probability=0.0,
            )

        mock_sentiment_analyzer.analyze_text.side_effect = side_effect

        comments = [
            make_comment("c1", "user1", "A" * 50, score=10),
            make_comment("c2", "user2", "B" * 50, score=10),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Average of 1.0 and -1.0 = 0.0
        assert abs(result.consensus_polarity) < 0.1
        # High variance → low consensus
        assert result.consensus_score < 0.2

    def test_comment_analyses_populated(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """comment_analyses field should be populated with CommentAnalysis objects."""
        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.7,
            intensity=0.8,
            conviction=0.9,
            sarcasm_probability=0.1,
        )

        comments = [
            make_comment("c1", "user1", "Test comment", score=10),
            make_comment("c2", "user2", "Another comment", score=5),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        assert len(result.comment_analyses) == 2

        # Check first analysis
        analysis = result.comment_analyses[0]
        assert analysis.comment_id == "c1"
        assert analysis.author == "user1"
        assert analysis.score == 10
        assert analysis.polarity == 0.7
        assert analysis.conviction == 0.9
        assert analysis.sarcasm_probability == 0.1
        assert analysis.length == len("Test comment")

    def test_rounding_to_3_decimals(
        self, thread_analyzer, op_sentiment, mock_sentiment_analyzer
    ):
        """Results should be rounded to 3 decimal places."""
        mock_sentiment_analyzer.analyze_text.return_value = SentimentResult(
            polarity=0.123456789,
            intensity=0.5,
            conviction=0.5,
            sarcasm_probability=0.0,
        )

        comments = [
            make_comment("c1", "user1", "Test", score=10),
            make_comment("c2", "user2", "Test2", score=10),
        ]

        result = thread_analyzer.analyze(op_sentiment, comments)

        # Check rounding (consensus_polarity should be rounded)
        assert result.consensus_polarity == 0.123
        assert result.consensus_score == round(result.consensus_score, 3)
        assert result.agreement_with_op == round(result.agreement_with_op, 3)
