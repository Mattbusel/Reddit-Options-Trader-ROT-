from __future__ import annotations

import re
from typing import List, Tuple

from rot.core.types import Evidence, Event, EventType, Horizon, Stance, TrendCandidate
from rot.market.enricher import NON_EQUITY_TOKENS, ALIAS_MAP

# Matches $TSLA or TSLA
_TICKER_RE = re.compile(r"(?:\$([A-Z]{1,5})\b|\b([A-Z]{1,5})\b)")

# Keyword-based event type classification
_EVENT_KEYWORDS: list[Tuple[str, EventType]] = [
    (r"\b(?:earnings|er|revenue|eps|guidance|beat|miss|report(?:ing)?)\b", "earnings_rumor"),
    (r"\b(?:squeeze|short\s*interest|gamma|si%|days\s*to\s*cover)\b", "squeeze_chatter"),
    (r"\b(?:fda|sec|antitrust|regulator|lawsuit|ruling|ban|tariff)\b", "regulatory"),
    (r"\b(?:launch|release|product|patent|partner|merger|acquisition|deal)\b", "product_news"),
    (r"\b(?:cpi|gdp|fomc|rate\s*cut|rate\s*hike|inflation|recession|macro)\b", "macro"),
]

# Sentiment keywords for basic stance detection
_BULLISH_WORDS = re.compile(
    r"\b(?:moon|calls|bull|long|buy|breakout|rip|rocket|tendies|gap\s*up|ATH|squeeze)\b", re.I
)
_BEARISH_WORDS = re.compile(
    r"\b(?:puts|bear|short|sell|dump|crash|tank|drill|gap\s*down|plunge|collapse)\b", re.I
)

# Time horizon keywords
_INTRADAY_WORDS = re.compile(r"\b(?:0DTE|0dte|FD|scalp|intraday|today|expir(?:ing|es)\s*today)\b", re.I)
_WEEKLY_WORDS = re.compile(r"\b(?:this\s*week|weeklies|weekly|next\s*week|friday)\b", re.I)
_EARNINGS_WORDS = re.compile(r"\b(?:earnings|ER|before\s*open|after\s*close|report)\b", re.I)


class EventBuilder:
    def extract_entities(self, title: str, body: str) -> List[str]:
        text = f"{title}\n{body}"
        matches = _TICKER_RE.findall(text)

        # Prefer explicit $TICKER mentions
        dollar = [a for (a, b) in matches if a]
        bare = [b for (a, b) in matches if b]
        raw = dollar if dollar else bare

        out: List[str] = []
        for s in raw:
            s = ALIAS_MAP.get(s.upper(), s.upper())
            if s in NON_EQUITY_TOKENS:
                continue
            if len(s) == 1:
                continue
            out.append(s)

        return sorted(set(out))[:5]

    def _has_explicit_ticker(self, title: str, body: str) -> bool:
        """Check if any $TICKER format was used."""
        return bool(re.search(r"\$[A-Z]{1,5}\b", f"{title}\n{body}"))

    def _classify_event_type(self, text: str) -> EventType:
        text_lower = text.lower()
        for pattern, event_type in _EVENT_KEYWORDS:
            if re.search(pattern, text_lower):
                return event_type
        return "other"

    def _detect_stance(self, text: str) -> Stance:
        bull_count = len(_BULLISH_WORDS.findall(text))
        bear_count = len(_BEARISH_WORDS.findall(text))

        if bull_count > 0 and bear_count > 0:
            return "mixed"
        if bull_count > 0:
            return "bullish"
        if bear_count > 0:
            return "bearish"
        return "unknown"

    def _detect_horizon(self, text: str) -> Horizon:
        if _INTRADAY_WORDS.search(text):
            return "intraday"
        if _EARNINGS_WORDS.search(text):
            return "earnings"
        if _WEEKLY_WORDS.search(text):
            return "1w"
        return "unknown"

    def from_candidate(self, c: TrendCandidate) -> List[Event]:
        post = c.snapshot.post
        tickers = self.extract_entities(post.title, post.selftext)

        if not tickers:
            return []

        full_text = f"{post.title} {post.selftext}"
        event_type = self._classify_event_type(full_text)
        stance = self._detect_stance(full_text)
        horizon = self._detect_horizon(full_text)

        # Base confidence: explicit $TICKER = 0.4, bare = 0.25
        base_confidence = 0.4 if self._has_explicit_ticker(post.title, post.selftext) else 0.25
        # Boost for classified event type
        if event_type != "other":
            base_confidence += 0.1

        ev = Event(
            event_type=event_type,
            entities=tickers,
            stance=stance,
            time_horizon=horizon,
            evidence=[
                Evidence(
                    post_id=post.id,
                    permalink=post.permalink,
                    subreddit=post.subreddit,
                    excerpt=post.title[:200],
                )
            ],
            confidence=min(base_confidence, 1.0),
            meta={
                "trend_score": c.trend_score,
                "features": c.features,
                "score": post.score,
                "num_comments": post.num_comments,
                "upvote_ratio": post.upvote_ratio,
                "author": post.author,
                "flair": post.flair,
                "is_crosspost": post.is_crosspost,
                "body_excerpt": post.selftext[:500] if post.selftext else "",
            },
        )

        return [ev]
