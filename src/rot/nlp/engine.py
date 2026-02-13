"""NLP Engine orchestrator for the ROT NLP pipeline.

Single entry point that coordinates tokenization, sentiment analysis,
entity resolution, event classification, temporal analysis, and
thread consensus scoring.
"""
from __future__ import annotations

import time
from typing import List, Optional

from rot.core.types import Comment
from rot.nlp.types import NLPResult, TemporalResult, ThreadResult
from rot.nlp.tokenizer import Tokenizer
from rot.nlp.sentiment import SentimentAnalyzer
from rot.nlp.entities import EntityResolver
from rot.nlp.classifier import EventClassifier
from rot.nlp.temporal import TemporalAnalyzer
from rot.nlp.thread import ThreadAnalyzer


class NLPEngine:
    """Orchestrator for the ROT custom NLP pipeline.

    Usage:
        engine = NLPEngine()
        result = engine.analyze(title, body, comments)
        # result.ticker_symbols, result.primary_stance, etc.

    Each sub-component runs independently. If any component fails,
    the engine returns partial results (graceful degradation).
    """

    def __init__(self) -> None:
        self._tokenizer = Tokenizer()
        self._sentiment = SentimentAnalyzer()
        self._entities = EntityResolver()
        self._classifier = EventClassifier()
        self._temporal = TemporalAnalyzer()
        self._thread = ThreadAnalyzer(self._sentiment)

    def analyze(
        self,
        title: str,
        body: str,
        comments: Optional[List[Comment]] = None,
    ) -> NLPResult:
        """Full NLP analysis of a Reddit post + optional comments.

        Returns an NLPResult with all analysis outputs. Components that
        fail individually return sensible defaults without breaking
        the overall pipeline.
        """
        t0 = time.perf_counter()
        full_text = f"{title} {body}"

        # ── 1. Tokenize ──
        title_tokens, body_tokens = self._tokenizer.tokenize_post(title, body)
        all_tokens = title_tokens + body_tokens

        # ── 2. Sentiment ──
        sentiment = self._sentiment.analyze(all_tokens)

        # ── 3. Entities ──
        try:
            entities, options_entities, positions = self._entities.resolve(all_tokens, full_text)
        except Exception:
            entities, options_entities, positions = [], [], []

        # ── 4. Classification ──
        try:
            classifications = self._classifier.classify(all_tokens)
        except Exception:
            classifications = []

        # ── 5. Temporal ──
        temporal: Optional[TemporalResult] = None
        try:
            temporal = self._temporal.analyze(all_tokens, full_text)
        except Exception:
            pass

        # ── 6. Thread analysis ──
        thread: Optional[ThreadResult] = None
        if comments:
            try:
                thread = self._thread.analyze(sentiment, comments)
            except Exception:
                pass

        # ── 7. Derive convenience fields ──
        ticker_symbols = sorted(set(
            e.symbol for e in entities if e.confidence >= 0.3
        ))[:5]

        primary_stance = self._derive_stance(sentiment, thread)

        primary_event_type = "other"
        if classifications:
            primary_event_type = classifications[0].category

        elapsed_ms = (time.perf_counter() - t0) * 1000

        return NLPResult(
            sentiment=sentiment,
            entities=entities,
            options_entities=options_entities,
            positions=positions,
            classifications=classifications,
            temporal=temporal,
            thread=thread,
            ticker_symbols=ticker_symbols,
            primary_stance=primary_stance,
            primary_event_type=primary_event_type,
            token_count=len(all_tokens),
            processing_time_ms=round(elapsed_ms, 2),
        )

    def extract_tickers(self, title: str, body: str) -> List[str]:
        """Quick ticker extraction — for backward compat with runner.py.

        Only runs tokenizer + entity resolver, skipping sentiment/classification
        for speed.
        """
        title_tokens, body_tokens = self._tokenizer.tokenize_post(title, body)
        all_tokens = title_tokens + body_tokens
        full_text = f"{title} {body}"

        try:
            entities = self._entities.extract_tickers_only(all_tokens, full_text)
        except Exception:
            entities = []

        return entities

    @staticmethod
    def _derive_stance(sentiment, thread: Optional[ThreadResult]) -> str:
        """Map continuous polarity to discrete stance.

        Factors in thread consensus and sarcasm probability.
        """
        polarity = sentiment.polarity

        # If thread analysis shows strong disagreement with OP, lean mixed
        if thread and thread.agreement_with_op < 0.3:
            return "mixed"

        # Sarcasm flip already applied in sentiment analyzer,
        # but if sarcasm is very high and polarity is near zero, it's uncertain
        if sentiment.sarcasm_probability > 0.7 and abs(polarity) < 0.2:
            return "unknown"

        # Map polarity to stance
        if polarity > 0.15:
            return "bullish"
        elif polarity < -0.15:
            return "bearish"
        elif sentiment.bullish_count > 0 and sentiment.bearish_count > 0:
            return "mixed"
        else:
            return "unknown"
