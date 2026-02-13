"""Sentiment analyzer for the ROT NLP engine.

Lexicon-based sentiment scoring with contextual modifiers, sarcasm
detection, conviction scoring, and intensity aggregation.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from rot.nlp.types import SentimentResult, SentimentSignal, Token
from rot.nlp.lexicon import (
    DIMINISHERS,
    HIGH_CONVICTION_PHRASES,
    INTENSIFIERS,
    LOW_CONVICTION_PHRASES,
    NEGATORS,
    SARCASTIC_PHRASES,
    LexiconEntry,
    get_lexicon,
)


class SentimentAnalyzer:
    """Multi-pass sentiment analyzer with sarcasm detection and conviction scoring.

    Pipeline:
    1. Lexicon lookup (single + 2/3-gram)
    2. Negation window (flips polarity of next 1-3 tokens)
    3. Intensifier/diminisher modifier pass
    4. ALL-CAPS and repeated-char intensity boost
    5. Sarcasm heuristic detection
    6. Conviction scoring
    7. Aggregate into SentimentResult
    """

    NEGATION_WINDOW = 3  # tokens ahead a negator affects

    def __init__(self, lexicon: Optional[Dict[str, LexiconEntry]] = None) -> None:
        self._lex = lexicon or get_lexicon()
        # Pre-compute lowercased sarcastic phrases for fast matching
        self._sarcastic_phrases_lower = [p.lower() for p in SARCASTIC_PHRASES]
        self._high_conviction_lower = [p.lower() for p in HIGH_CONVICTION_PHRASES]
        self._low_conviction_lower = [p.lower() for p in LOW_CONVICTION_PHRASES]

    def analyze(self, tokens: List[Token]) -> SentimentResult:
        """Run full sentiment analysis on a list of tokens."""
        if not tokens:
            return SentimentResult(
                polarity=0.0, intensity=0.0, conviction=0.5,
                sarcasm_probability=0.0,
            )

        # ── Pass 1: Lexicon lookup (including n-grams) ──
        signals = self._lexicon_pass(tokens)

        # ── Pass 2: Negation pass ──
        signals = self._negation_pass(tokens, signals)

        # ── Pass 3: Intensifier/diminisher pass ──
        signals = self._modifier_pass(tokens, signals)

        # ── Pass 4: ALL-CAPS and repeat boost ──
        signals = self._boost_pass(tokens, signals)

        # ── Pass 5: Sarcasm detection ──
        full_text = " ".join(t.text for t in tokens if t.token_type in ("word", "emoji"))
        sarcasm_prob = self._detect_sarcasm(tokens, signals, full_text)

        # ── Pass 6: Conviction scoring ──
        conviction = self._score_conviction(tokens, full_text)

        # ── Pass 7: Aggregate ──
        return self._aggregate(signals, sarcasm_prob, conviction)

    def analyze_text(self, text: str) -> SentimentResult:
        """Convenience: tokenize then analyze."""
        from rot.nlp.tokenizer import Tokenizer
        tokens = Tokenizer().tokenize(text)
        return self.analyze(tokens)

    # ── Pass 1: Lexicon lookup ──

    def _lexicon_pass(self, tokens: List[Token]) -> List[SentimentSignal]:
        """Look up tokens in the lexicon, including 2-gram and 3-gram phrases."""
        signals: List[SentimentSignal] = []
        consumed: set[int] = set()  # token indices consumed by n-grams
        word_tokens = [
            (i, t) for i, t in enumerate(tokens)
            if t.token_type in ("word", "emoji")
        ]

        # 3-gram pass
        for idx in range(len(word_tokens) - 2):
            if word_tokens[idx][0] in consumed:
                continue
            i0, t0 = word_tokens[idx]
            i1, t1 = word_tokens[idx + 1]
            i2, t2 = word_tokens[idx + 2]
            trigram = f"{t0.text} {t1.text} {t2.text}".lower()
            entry = self._lex.get(trigram)
            if entry:
                signals.append(self._signal_from_entry(entry, trigram, t0))
                consumed.update({i0, i1, i2})

        # 2-gram pass
        for idx in range(len(word_tokens) - 1):
            if word_tokens[idx][0] in consumed:
                continue
            i0, t0 = word_tokens[idx]
            i1, t1 = word_tokens[idx + 1]
            bigram = f"{t0.text} {t1.text}".lower()
            entry = self._lex.get(bigram)
            if entry:
                signals.append(self._signal_from_entry(entry, bigram, t0))
                consumed.update({i0, i1})

        # 1-gram pass
        for i, t in word_tokens:
            if i in consumed:
                continue
            term = t.text.lower()
            entry = self._lex.get(term)
            if entry:
                signals.append(self._signal_from_entry(entry, term, t))

        return signals

    def _signal_from_entry(self, entry: LexiconEntry, matched: str, token: Token) -> SentimentSignal:
        """Create a SentimentSignal from a lexicon entry match."""
        return SentimentSignal(
            token_text=matched,
            raw_text=token.raw,
            polarity=entry.polarity,
            intensity=entry.intensity,
            category="lexicon" if entry.category != "emoji" else "emoji",
            span=(token.start, token.end),
            context="",
        )

    # ── Pass 2: Negation ──

    def _negation_pass(
        self, tokens: List[Token], signals: List[SentimentSignal]
    ) -> List[SentimentSignal]:
        """Flip polarity of sentiment signals within a negation window."""
        # Find negation token positions
        negation_positions: List[int] = []
        for i, t in enumerate(tokens):
            if t.token_type == "word" and t.text.lower().replace("'", "") in NEGATORS:
                negation_positions.append(i)

        if not negation_positions:
            return signals

        # Build a set of token start offsets that are in negation windows
        negated_spans: set[Tuple[int, int]] = set()
        for neg_idx in negation_positions:
            # Affect the next NEGATION_WINDOW word/emoji tokens
            count = 0
            for j in range(neg_idx + 1, len(tokens)):
                if tokens[j].token_type in ("word", "emoji"):
                    negated_spans.add((tokens[j].start, tokens[j].end))
                    count += 1
                    if count >= self.NEGATION_WINDOW:
                        break

        # Flip polarity of affected signals
        new_signals: List[SentimentSignal] = []
        negated_count = 0
        for sig in signals:
            if sig.span in negated_spans and sig.polarity != 0:
                negated_count += 1
                new_signals.append(SentimentSignal(
                    token_text=sig.token_text,
                    raw_text=sig.raw_text,
                    polarity=-sig.polarity * 0.8,  # flip + dampen slightly
                    intensity=sig.intensity * 0.7,  # negated = less intense
                    category="negation",
                    span=sig.span,
                    context=sig.context,
                ))
            else:
                new_signals.append(sig)

        return new_signals

    # ── Pass 3: Modifier pass ──

    def _modifier_pass(
        self, tokens: List[Token], signals: List[SentimentSignal]
    ) -> List[SentimentSignal]:
        """Adjust intensity of signals near intensifiers or diminishers."""
        # Map token offsets to modifier types
        modifier_positions: Dict[int, str] = {}  # token_index -> "intensifier" | "diminisher"
        for i, t in enumerate(tokens):
            if t.token_type != "word":
                continue
            term = t.text.lower()
            if term in INTENSIFIERS:
                modifier_positions[i] = "intensifier"
            elif term in DIMINISHERS:
                modifier_positions[i] = "diminisher"

        if not modifier_positions:
            return signals

        # For each modifier, find nearest sentiment signal (forward 1-2 tokens)
        boosted_spans: Dict[Tuple[int, int], float] = {}
        for mod_idx, mod_type in modifier_positions.items():
            multiplier = 1.4 if mod_type == "intensifier" else 0.5
            for j in range(mod_idx + 1, min(mod_idx + 3, len(tokens))):
                if tokens[j].token_type in ("word", "emoji"):
                    span = (tokens[j].start, tokens[j].end)
                    boosted_spans[span] = multiplier
                    break

        # Apply modifiers
        new_signals: List[SentimentSignal] = []
        for sig in signals:
            mult = boosted_spans.get(sig.span)
            if mult is not None:
                new_signals.append(SentimentSignal(
                    token_text=sig.token_text,
                    raw_text=sig.raw_text,
                    polarity=sig.polarity,
                    intensity=min(1.0, sig.intensity * mult),
                    category=sig.category,
                    span=sig.span,
                    context=sig.context,
                ))
            else:
                new_signals.append(sig)

        return new_signals

    # ── Pass 4: ALL-CAPS and repeat boost ──

    def _boost_pass(
        self, tokens: List[Token], signals: List[SentimentSignal]
    ) -> List[SentimentSignal]:
        """Boost intensity for ALL-CAPS and repeated-character tokens."""
        # Build map of token spans to boost factors
        boost_map: Dict[Tuple[int, int], float] = {}
        for t in tokens:
            boost = 1.0
            if t.meta.get("is_caps"):
                boost *= 1.3
            repeat_count = t.meta.get("repeat_count", 0)
            if repeat_count > 0:
                boost *= min(1.5, 1.0 + 0.1 * repeat_count)
            if boost > 1.0:
                boost_map[(t.start, t.end)] = boost

        if not boost_map:
            return signals

        new_signals: List[SentimentSignal] = []
        for sig in signals:
            boost = boost_map.get(sig.span, 1.0)
            if boost > 1.0:
                new_signals.append(SentimentSignal(
                    token_text=sig.token_text,
                    raw_text=sig.raw_text,
                    polarity=sig.polarity,
                    intensity=min(1.0, sig.intensity * boost),
                    category=sig.category,
                    span=sig.span,
                    context=sig.context,
                ))
            else:
                new_signals.append(sig)

        return new_signals

    # ── Pass 5: Sarcasm detection ──

    def _detect_sarcasm(
        self, tokens: List[Token], signals: List[SentimentSignal], full_text: str
    ) -> float:
        """Detect sarcasm using 8 heuristic rules. Returns probability 0.0-1.0."""
        score = 0.0
        text_lower = full_text.lower()

        # Rule 1: ALL-CAPS positive word followed by negative context (within 5 tokens)
        for i, t in enumerate(tokens):
            if t.meta.get("is_caps") and t.token_type == "word":
                term_lower = t.text.lower()
                entry = self._lex.get(term_lower)
                if entry and entry.polarity > 0.3:
                    # Check next 5 word tokens for negative context
                    look_count = 0
                    for j in range(i + 1, len(tokens)):
                        if tokens[j].token_type in ("word", "emoji"):
                            neg_entry = self._lex.get(tokens[j].text.lower())
                            if neg_entry and neg_entry.polarity < -0.3:
                                score += 0.35
                                break
                            look_count += 1
                            if look_count >= 5:
                                break

        # Rule 2: Clown emoji after any statement
        has_clown = any(t.text == "CLOWN_EMOJI" for t in tokens)
        if has_clown:
            score += 0.40

        # Rule 3: Known sarcastic phrases
        for phrase in self._sarcastic_phrases_lower:
            if phrase in text_lower:
                # Check for negative context nearby (10-word window)
                phrase_idx = text_lower.find(phrase)
                window = text_lower[max(0, phrase_idx - 60):phrase_idx + len(phrase) + 60]
                has_neg_context = any(
                    self._lex.get(w) and self._lex[w].polarity < -0.3
                    for w in re.findall(r"[a-z]+", window)
                )
                score += 0.50 if has_neg_context else 0.25
                break  # only count strongest match

        # Rule 4: Emoji contradiction (positive emoji + negative lexicon words)
        positive_emojis = sum(1 for s in signals if s.category == "emoji" and s.polarity > 0.3)
        negative_words = sum(1 for s in signals if s.category != "emoji" and s.polarity < -0.3)
        negative_emojis = sum(1 for s in signals if s.category == "emoji" and s.polarity < -0.3)
        positive_words = sum(1 for s in signals if s.category != "emoji" and s.polarity > 0.3)

        if (positive_emojis > 0 and negative_words > 0) or (negative_emojis > 0 and positive_words > 0):
            score += 0.30

        # Rule 5: Quotation marks around positive words
        quoted_positive = re.findall(r'["\u201c](\w+)["\u201d]', full_text)
        for qw in quoted_positive:
            entry = self._lex.get(qw.lower())
            if entry and entry.polarity > 0.3:
                score += 0.25
                break

        # Rule 6: Excessive positive emojis with minimal substance
        rocket_count = sum(1 for t in tokens if t.text == "ROCKET_EMOJI")
        word_count = sum(1 for t in tokens if t.token_type == "word")
        if rocket_count >= 3 and word_count < 15:
            score += 0.15

        # Rule 7: Eyeroll emoji = strong sarcasm marker
        has_eyeroll = any(t.text == "EYEROLL_EMOJI" for t in tokens)
        if has_eyeroll:
            score += 0.35

        # Rule 8: Rhetorical question + positive statement
        if "?" in full_text:
            rhetorical_patterns = [
                r"what could\s+(?:go wrong|possibly)",
                r"how could this\s+(?:happen|fail)",
                r"who could have\s+(?:predicted|seen|known)",
                r"right\s*\?",
            ]
            for pattern in rhetorical_patterns:
                if re.search(pattern, text_lower):
                    score += 0.35
                    break

        return min(1.0, score)

    # ── Pass 6: Conviction scoring ──

    def _score_conviction(self, tokens: List[Token], full_text: str) -> float:
        """Score conviction level from 0.0 (uncertain) to 1.0 (absolute).

        Based on high-conviction vs low-conviction phrase counting.
        Default is 0.5 (neutral) when no conviction indicators found.
        """
        text_lower = full_text.lower()

        high_count = sum(1 for p in self._high_conviction_lower if p in text_lower)
        low_count = sum(1 for p in self._low_conviction_lower if p in text_lower)

        total = high_count + low_count
        if total == 0:
            return 0.5  # neutral — no conviction signals

        # Score: high pulls toward 1.0, low pulls toward 0.0
        raw = (high_count - low_count) / total
        # Map from [-1, 1] to [0.1, 0.95]
        return max(0.1, min(0.95, 0.5 + raw * 0.45))

    # ── Pass 7: Aggregation ──

    def _aggregate(
        self,
        signals: List[SentimentSignal],
        sarcasm_prob: float,
        conviction: float,
    ) -> SentimentResult:
        """Aggregate all signals into a final SentimentResult."""
        if not signals:
            return SentimentResult(
                polarity=0.0, intensity=0.0, conviction=conviction,
                sarcasm_probability=sarcasm_prob,
            )

        bullish_count = sum(1 for s in signals if s.polarity > 0.05)
        bearish_count = sum(1 for s in signals if s.polarity < -0.05)
        negated_count = sum(1 for s in signals if s.category == "negation")

        # Weighted average polarity (weighted by intensity)
        total_weight = sum(s.intensity for s in signals)
        if total_weight > 0:
            polarity = sum(s.polarity * s.intensity for s in signals) / total_weight
        else:
            polarity = 0.0

        # Intensity: average intensity scaled by signal count
        # More signals = higher confidence in the intensity reading
        avg_intensity = sum(s.intensity for s in signals) / len(signals)
        signal_count_factor = min(1.0, len(signals) / 10.0)  # saturates at 10 signals
        intensity = avg_intensity * (0.5 + 0.5 * signal_count_factor)

        # Sarcasm flip: if high sarcasm probability, flip polarity
        if sarcasm_prob > 0.6:
            polarity = -polarity * 0.7  # flip + dampen
            intensity *= 0.7  # less confident when sarcasm detected

        # Clamp
        polarity = max(-1.0, min(1.0, polarity))
        intensity = max(0.0, min(1.0, intensity))

        return SentimentResult(
            polarity=polarity,
            intensity=intensity,
            conviction=conviction,
            sarcasm_probability=sarcasm_prob,
            raw_signals=signals,
            bullish_count=bullish_count,
            bearish_count=bearish_count,
            negated_count=negated_count,
        )
