"""Thread/comment consensus analyzer for the ROT NLP engine.

Analyzes sentiment distribution across a post's comments to
determine consensus, OP agreement, and contrarian presence.
"""
from __future__ import annotations

import math
from typing import List, Optional

from rot.core.types import Comment
from rot.nlp.types import (
    CommentAnalysis,
    SentimentResult,
    ThreadResult,
)


class ThreadAnalyzer:
    """Analyzes comment thread sentiment for consensus and agreement.

    Metrics:
    - consensus_score: How much commenters agree with each other (0-1)
    - agreement_with_op: How much comments agree with OP's thesis (0-1)
    - contrarian_detected: High-karma comment contradicts majority
    - top_comment_aligns: Whether top comment agrees with OP
    """

    MAX_COMMENTS = 20  # Cap to avoid processing huge threads

    def __init__(self, sentiment_analyzer: object) -> None:
        """Accept a SentimentAnalyzer instance (duck-typed to avoid circular import)."""
        self._sentiment = sentiment_analyzer

    def analyze(
        self,
        op_sentiment: SentimentResult,
        comments: List[Comment],
    ) -> ThreadResult:
        """Analyze comment thread against OP sentiment."""
        if not comments:
            return ThreadResult(
                consensus_polarity=0.0,
                consensus_score=0.0,
                agreement_with_op=0.5,
                contrarian_detected=False,
                top_comment_aligns=None,
                comment_count_analyzed=0,
            )

        # Cap comments for performance
        comments = comments[:self.MAX_COMMENTS]

        # Analyze each comment
        analyses: List[CommentAnalysis] = []
        for comment in comments:
            try:
                result = self._sentiment.analyze_text(comment.body)
                analyses.append(CommentAnalysis(
                    comment_id=comment.id,
                    author=comment.author,
                    score=comment.score,
                    polarity=result.polarity,
                    conviction=result.conviction,
                    sarcasm_probability=result.sarcasm_probability,
                    length=len(comment.body),
                ))
            except Exception:
                continue  # Skip comments that fail analysis

        if not analyses:
            return ThreadResult(
                consensus_polarity=0.0,
                consensus_score=0.0,
                agreement_with_op=0.5,
                contrarian_detected=False,
                top_comment_aligns=None,
                comment_count_analyzed=0,
            )

        # Compute quality weights: score * log(1 + length/50)
        weights = [
            max(1, a.score) * math.log(1 + a.length / 50)
            for a in analyses
        ]
        total_weight = sum(weights) or 1.0

        # ── Consensus polarity (weighted average) ──
        consensus_polarity = sum(
            a.polarity * w for a, w in zip(analyses, weights)
        ) / total_weight

        # ── Consensus score (agreement among commenters) ──
        # Low std dev of polarities = high consensus
        if len(analyses) >= 2:
            mean_pol = sum(a.polarity for a in analyses) / len(analyses)
            variance = sum((a.polarity - mean_pol) ** 2 for a in analyses) / len(analyses)
            std_dev = math.sqrt(variance)
            # Map std_dev to score: 0 std_dev → 1.0, 1.0 std_dev → 0.0
            consensus_score = max(0.0, min(1.0, 1.0 - std_dev))
        else:
            consensus_score = 0.5  # single comment = neutral consensus

        # ── Agreement with OP ──
        op_pol = op_sentiment.polarity
        if abs(op_pol) < 0.05:
            # OP has no clear sentiment → measure based on comment clarity
            agreement_with_op = 0.5
        else:
            # Compare signs and magnitude
            pol_diff = abs(op_pol - consensus_polarity)
            agreement_with_op = max(0.0, min(1.0, 1.0 - pol_diff / 2.0))
            # Strong boost if same sign
            if op_pol * consensus_polarity > 0:
                agreement_with_op = max(agreement_with_op, 0.6)
            elif op_pol * consensus_polarity < 0:
                agreement_with_op = min(agreement_with_op, 0.4)

        # ── Contrarian detection ──
        contrarian_detected = False
        if len(analyses) >= 3:
            median_score = sorted(a.score for a in analyses)[len(analyses) // 2]
            threshold = max(median_score * 2, 5)
            for a in analyses:
                if a.score > threshold:
                    # High-score comment — check if it contradicts consensus
                    if consensus_polarity > 0.1 and a.polarity < -0.15:
                        contrarian_detected = True
                        break
                    elif consensus_polarity < -0.1 and a.polarity > 0.15:
                        contrarian_detected = True
                        break

        # ── Top comment alignment ──
        top_comment_aligns: Optional[bool] = None
        if analyses:
            # The first comment is typically highest-scored
            top = analyses[0]
            if abs(op_pol) > 0.1 and abs(top.polarity) > 0.1:
                top_comment_aligns = (op_pol * top.polarity > 0)

        return ThreadResult(
            consensus_polarity=round(consensus_polarity, 3),
            consensus_score=round(consensus_score, 3),
            agreement_with_op=round(agreement_with_op, 3),
            contrarian_detected=contrarian_detected,
            top_comment_aligns=top_comment_aligns,
            comment_count_analyzed=len(analyses),
            comment_analyses=analyses,
        )
