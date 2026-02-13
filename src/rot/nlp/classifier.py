"""Multi-label event classifier for the ROT NLP engine.

Replaces the first-match-wins regex classification in event_builder.py
with weighted keyword scoring across 14 categories.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

from rot.nlp.types import ClassifiedEvent, Token


# ── Category keyword sets with weights ──
# Each category has (term, weight) pairs. Terms are matched against
# lowercased token text. Higher weight = more indicative of category.

_CATEGORY_TERMS: Dict[str, List[Tuple[str, float]]] = {
    "earnings_rumor": [
        ("earnings", 1.0), ("revenue", 0.9), ("eps", 1.0),
        ("guidance", 0.9), ("beat", 0.7), ("miss", 0.7), ("misses", 0.7),
        ("missed", 0.7), ("report", 0.5), ("reporting", 0.5),
        ("whisper", 0.8), ("estimate", 0.7), ("estimates", 0.7),
        ("quarter", 0.5), ("quarterly", 0.5), ("fiscal", 0.5),
        ("q1", 0.6), ("q2", 0.6), ("q3", 0.6), ("q4", 0.6),
        ("profit", 0.5), ("margin", 0.5), ("margins", 0.5),
        ("topline", 0.6), ("bottomline", 0.6), ("top-line", 0.6),
        ("bottom-line", 0.6), ("ebitda", 0.7), ("rev", 0.5),
        ("before open", 0.5), ("after close", 0.5),
        ("pre-market", 0.4), ("after-hours", 0.4),
    ],
    "squeeze_chatter": [
        ("squeeze", 1.0), ("short interest", 1.0), ("short_interest", 1.0),
        ("gamma", 0.8), ("gamma squeeze", 1.0), ("short squeeze", 1.0),
        ("si%", 0.9), ("days to cover", 0.9), ("days_to_cover", 0.9),
        ("short float", 0.8), ("borrow rate", 0.8), ("borrow_rate", 0.8),
        ("ftd", 0.7), ("fail to deliver", 0.8), ("ctb", 0.7),
        ("cost to borrow", 0.8), ("short ladder", 0.6),
        ("naked short", 0.8), ("dark pool", 0.5),
    ],
    "regulatory": [
        ("fda", 1.0), ("sec", 0.9), ("antitrust", 0.9),
        ("regulator", 0.8), ("regulatory", 0.8), ("lawsuit", 0.7),
        ("ruling", 0.8), ("ban", 0.6), ("tariff", 0.7), ("tariffs", 0.7),
        ("compliance", 0.6), ("enforcement", 0.7), ("clearance", 0.7),
        ("approval", 0.7), ("approved", 0.7), ("approve", 0.7),
        ("investigation", 0.7), ("subpoena", 0.8), ("fine", 0.5),
        ("penalty", 0.6), ("sanction", 0.7), ("sanctions", 0.7),
        ("legislation", 0.6), ("bill", 0.4), ("regulation", 0.7),
        ("doj", 0.8), ("ftc", 0.8), ("cftc", 0.8),
    ],
    "product_news": [
        ("patent", 0.8), ("merger", 0.9), ("acquisition", 0.9),
        ("partnership", 0.8), ("launch", 0.6), ("launched", 0.6),
        ("launches", 0.6), ("launching", 0.6), ("product", 0.5),
        ("release", 0.5), ("announcement", 0.6), ("reveal", 0.6),
        ("contract", 0.5), ("contracts", 0.5), ("deal", 0.6),
        ("awarded", 0.6), ("win", 0.4), ("wins", 0.4),
        ("innovation", 0.5), ("breakthrough", 0.7), ("trial", 0.5),
        ("clinical", 0.6), ("pipeline", 0.5), ("approval", 0.5),
    ],
    "macro": [
        ("cpi", 1.0), ("gdp", 0.9), ("fomc", 1.0),
        ("rate cut", 1.0), ("rate hike", 1.0), ("rate_cut", 1.0),
        ("rate_hike", 1.0), ("inflation", 0.9), ("recession", 0.9),
        ("macro", 0.8), ("federal reserve", 1.0), ("fed", 0.7),
        ("monetary policy", 0.9), ("treasury", 0.6), ("fiscal", 0.5),
        ("powell", 0.7), ("jpow", 0.7), ("yellen", 0.6),
        ("dovish", 0.8), ("hawkish", 0.8), ("pivot", 0.6),
        ("taper", 0.7), ("tapering", 0.7), ("stimulus", 0.7),
        ("jobs report", 0.8), ("nonfarm", 0.8), ("unemployment", 0.7),
        ("pce", 0.8), ("ppi", 0.7), ("ism", 0.6),
        ("debt ceiling", 0.8), ("shutdown", 0.6), ("trade war", 0.8),
        ("quantitative", 0.6), ("bonds", 0.4), ("yield", 0.5),
    ],
    "insider_activity": [
        ("insider", 1.0), ("insider buying", 1.0), ("insider selling", 1.0),
        ("form 4", 0.9), ("form4", 0.9), ("form_4", 0.9),
        ("director", 0.4), ("officer", 0.4), ("ceo bought", 0.9),
        ("ceo sold", 0.9), ("10b5-1", 0.8), ("10b5", 0.7),
        ("insider purchase", 0.9), ("insider sale", 0.9),
        ("executive purchase", 0.8), ("executive sale", 0.8),
        ("beneficial owner", 0.7), ("cluster buying", 0.8),
    ],
    "technical_breakout": [
        ("breakout", 1.0), ("breakdown", 0.8), ("golden cross", 1.0),
        ("death cross", 0.9), ("volume spike", 0.8), ("volume_spike", 0.8),
        ("cup and handle", 0.9), ("head and shoulders", 0.9),
        ("head shoulders", 0.8), ("macd", 0.7), ("rsi", 0.6),
        ("gap up", 0.7), ("gap-up", 0.7), ("gap down", 0.7),
        ("gap-down", 0.7), ("support", 0.4), ("resistance", 0.4),
        ("ascending triangle", 0.8), ("descending triangle", 0.8),
        ("bull flag", 0.8), ("bear flag", 0.8), ("wedge", 0.6),
        ("double top", 0.8), ("double bottom", 0.8),
        ("fibonacci", 0.7), ("fib", 0.5), ("moving average", 0.5),
        ("ema", 0.5), ("sma", 0.5), ("vwap", 0.6),
        ("channel", 0.4), ("trendline", 0.6),
    ],
    "options_flow": [
        ("unusual options", 1.0), ("unusual activity", 0.9),
        ("options flow", 1.0), ("options_flow", 1.0),
        ("sweep", 0.8), ("sweeps", 0.8), ("block trade", 0.8),
        ("dark pool", 0.7), ("dark_pool", 0.7),
        ("whale", 0.6), ("whales", 0.6),
        ("open interest", 0.6), ("oi spike", 0.8),
        ("put call ratio", 0.7), ("put_call_ratio", 0.7),
        ("options volume", 0.7), ("call volume", 0.7),
        ("put volume", 0.7), ("premium", 0.3),
    ],
    "dividend_play": [
        ("dividend", 1.0), ("dividends", 1.0), ("div", 0.5),
        ("ex-dividend", 1.0), ("ex dividend", 1.0), ("ex-div", 0.9),
        ("special dividend", 1.0), ("yield", 0.5), ("payout", 0.7),
        ("payout ratio", 0.8), ("dividend cut", 0.9),
        ("dividend increase", 0.9), ("dividend raise", 0.9),
        ("aristocrat", 0.7), ("dividend growth", 0.8),
    ],
    "buyback": [
        ("buyback", 1.0), ("buy back", 0.9), ("share buyback", 1.0),
        ("repurchase", 0.9), ("share repurchase", 1.0),
        ("authorization", 0.5), ("buyback program", 1.0),
        ("repurchase program", 0.9), ("treasury stock", 0.6),
    ],
    "ipo": [
        ("ipo", 1.0), ("initial public offering", 1.0),
        ("going public", 0.9), ("direct listing", 0.9),
        ("lockup expiration", 0.8), ("lock-up", 0.7),
        ("lockup", 0.7), ("s-1", 0.8), ("s1 filing", 0.8),
        ("pricing", 0.4), ("debut", 0.5),
    ],
    "spac": [
        ("spac", 1.0), ("de-spac", 0.9), ("despac", 0.9),
        ("blank check", 0.8), ("business combination", 0.7),
        ("definitive agreement", 0.7), ("pipe", 0.5),
        ("warrant", 0.5), ("warrants", 0.5), ("redemption", 0.5),
    ],
    "crypto_correlation": [
        ("bitcoin", 0.9), ("btc", 0.8), ("ethereum", 0.8),
        ("eth", 0.6), ("crypto", 0.9), ("cryptocurrency", 0.9),
        ("blockchain", 0.7), ("web3", 0.6), ("defi", 0.6),
        ("nft", 0.5), ("mining", 0.4), ("halving", 0.8),
        ("coinbase", 0.5), ("binance", 0.5),
    ],
}

# Pre-compute IDF-like weights: terms appearing in fewer categories
# are more discriminative
_TERM_DOC_FREQ: Dict[str, int] = {}
for _terms in _CATEGORY_TERMS.values():
    for _term, _ in _terms:
        _TERM_DOC_FREQ[_term] = _TERM_DOC_FREQ.get(_term, 0) + 1

_NUM_CATEGORIES = len(_CATEGORY_TERMS)


class EventClassifier:
    """Multi-label event classifier with weighted keyword scoring.

    Returns all categories with confidence > threshold, sorted by
    confidence descending. Categories use TF-IDF-like boosting
    for discriminative terms.
    """

    MIN_CONFIDENCE = 0.1  # minimum to include in results

    def classify(self, tokens: List[Token]) -> List[ClassifiedEvent]:
        """Classify tokens into event categories."""
        # Build lowercase word set for fast lookup
        token_texts = [t.text.lower() for t in tokens if t.token_type in ("word", "emoji")]

        # Also build bigrams for multi-word term matching
        bigrams: List[str] = []
        for i in range(len(token_texts) - 1):
            bigrams.append(f"{token_texts[i]} {token_texts[i + 1]}")

        trigrams: List[str] = []
        for i in range(len(token_texts) - 2):
            trigrams.append(f"{token_texts[i]} {token_texts[i + 1]} {token_texts[i + 2]}")

        all_terms = set(token_texts) | set(bigrams) | set(trigrams)

        results: List[ClassifiedEvent] = []

        for category, terms in _CATEGORY_TERMS.items():
            total_score = 0.0
            max_possible = 0.0
            matched: List[str] = []

            for term, weight in terms:
                term_lower = term.lower()
                # IDF boost: rarer terms get higher weight
                doc_freq = _TERM_DOC_FREQ.get(term_lower, 1)
                idf = math.log((_NUM_CATEGORIES + 1) / (doc_freq + 1)) + 1.0
                boosted_weight = weight * idf

                max_possible += boosted_weight

                if term_lower in all_terms:
                    total_score += boosted_weight
                    matched.append(term)

            if max_possible > 0 and total_score > 0:
                # Normalize to 0-1 range
                confidence = min(1.0, total_score / (max_possible * 0.3))
                # Additional boost for multiple matched terms
                match_diversity = min(1.0, len(matched) / 3.0)
                confidence = confidence * (0.6 + 0.4 * match_diversity)
                confidence = min(1.0, confidence)

                if confidence >= self.MIN_CONFIDENCE:
                    results.append(ClassifiedEvent(
                        category=category,
                        confidence=round(confidence, 3),
                        matched_terms=matched,
                    ))

        # Sort by confidence descending
        results.sort(key=lambda x: -x.confidence)

        # If no matches, return "other"
        if not results:
            results.append(ClassifiedEvent(
                category="other",
                confidence=0.5,
            ))

        return results
