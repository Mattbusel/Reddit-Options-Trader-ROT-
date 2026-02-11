from __future__ import annotations

import re
from typing import List, Tuple

from rot.core.types import Evidence, Event, EventType, Horizon, Stance, TrendCandidate
from rot.market.enricher import NON_EQUITY_TOKENS, ALIAS_MAP

# Matches $TSLA or TSLA
_TICKER_RE = re.compile(r"(?:\$([A-Z]{1,5})\b|\b([A-Z]{1,5})\b)")

# Additional filter for bare (non-$) tickers: common short words that sneak
# through NON_EQUITY_TOKENS because there are too many 2-3 letter combos.
# These are words that appear constantly in Reddit posts but are never tickers.
_BARE_TICKER_BLOCKLIST = {
    # 2-letter words that aren't tickers
    "IF", "IS", "IT", "IN", "ON", "OR", "SO", "NO", "UP", "MY",
    "DO", "GO", "TO", "AT", "BY", "WE", "AN", "AS", "BE", "HE",
    # 3-letter words frequently seen in Reddit finance posts
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN",
    "HAS", "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "HAD", "HOT",
    "ITS", "SAY", "SHE", "TOO", "USE", "HIM", "HIS", "HOW", "MAN",
    "OWN", "SAW", "GOT", "LET", "MAY", "RUN", "SET", "TRY", "WHY",
    "BIG", "END", "FAR", "FEW", "GOT", "OLD", "RED", "SIT", "TOP",
    "WIN", "WON", "YET", "ADD", "AGO", "BAD", "DID", "EAR", "FIT",
    "HIT", "JOB", "LAW", "OIL", "PAY", "PUT", "RAN", "TAX", "WAR",
    # Words that look like tickers but aren't
    # NOTE: Real tickers (COST, LOVE, GAIN, FIRE, PLAY, WORK, UNIT, RIDE,
    # WISH, NICE, OPEN) are in _CONTEXT_REQUIRED_TICKERS instead — they get
    # extracted only when near financial context words.
    "LMAO", "LMFAO", "ROFL", "IMHO", "FWIW", "AFAIK",
    "EDIT", "INFO", "LINK", "POST", "RISK", "SAFE",
    "FREE", "HELP", "HOPE", "IDEA", "PLAN",
    "SURE", "TRUE", "WANT", "ZERO", "BEST",
    "BEEN", "DEAL", "DONE", "DOWN", "DROP",
    "EASY", "FACT", "FALL", "FEEL", "FIND",
    "FULL", "GAVE", "GIVE", "GOES", "GONE",
    "GREW", "GROW", "HALF", "HAND", "HARD", "HATE",
    "HEAR", "HUGE", "JUMP", "KNEW", "KNOW", "LATE",
    "LEAD", "LEFT", "LESS", "LIFE", "LINE", "LIST",
    "LIVE", "LOAD", "LOOK", "LOSE", "LOSS", "LOST",
    "LUCK", "MAIN", "MISS", "MUST", "NEED",
    "NEWS", "NONE", "NOTE", "ONCE", "PAID",
    "PART", "PASS", "PAST", "PICK", "PULL", "PUSH",
    "RATE", "READ", "REST", "RISE", "RODE", "RULE",
    "RUNS", "RUSH", "SAVE", "SEEN", "SELL", "SENT",
    "SHOW", "SIDE", "SIGN", "SIZE", "SOLD", "SOON",
    "STOP", "TALK", "TELL", "TEST", "TIME", "TOLD",
    "TOOK", "TURN", "TYPE", "USED", "VIEW",
    "WAIT", "WAKE", "WALK", "WALL", "WEAK", "WEEK",
    "WENT", "WIDE", "WILD", "WORD", "WORE", "WRAP",
    # 5-letter words common on Reddit
    "ABOUT", "AFTER", "AGAIN", "BEING", "BELOW",
    "COULD", "EVERY", "FIRST", "FOUND", "GOING",
    "GREAT", "GREEN", "GUESS", "HEARD", "NEVER",
    "OTHER", "POINT", "PRICE", "RIGHT", "SHALL",
    "SINCE", "START", "STILL", "STOCK", "THEIR",
    "THERE", "THESE", "THING", "THINK", "THOSE",
    "THREE", "TODAY", "TRADE", "UNDER", "UNTIL",
    "VALUE", "WATCH", "WHERE", "WHICH", "WHILE",
    "WHOLE", "WORLD", "WORSE", "WORST", "WORTH",
    "WOULD", "WRONG", "MONEY", "SHARE", "CRASH",
    "SHORT", "CALLS", "MIGHT", "EARLY",
    # Government / institutional words (not tickers)
    "FILED", "AWARD", "GRANT", "PHASE", "TRIAL", "AGENT", "CLAIM",
    # Junk patterns (repeated letters, all same char)
    "GOOOO", "GOOO", "AAAA", "BBBB",
}

# Real tickers that are also common English words. We only extract these
# as bare (non-$) tickers when they appear near financial context words.
_CONTEXT_REQUIRED_TICKERS = {
    "COST", "LOVE", "GAIN", "FIRE", "PLAY", "WORK",
    "UNIT", "RIDE", "WISH", "NICE", "OPEN",
}

# Pattern to check for financial context near an ambiguous ticker
_FINANCIAL_CONTEXT_RE = re.compile(
    r"\b(?:stock|shares?|calls?|puts?|options?|position|earnings|buy|sell|"
    r"portfolio|contracts?|strike|expir|otm|itm|atm|premium|spread|bullish|bearish)\b",
    re.I,
)

# Keyword-based event type classification
# Patterns are tested in order; first match wins.
_EVENT_KEYWORDS: list[Tuple[str, EventType]] = [
    (r"\b(?:earnings|revenue|eps|guidance|beat|miss|report(?:ing)?)\b", "earnings_rumor"),
    (r"\b(?:squeeze|short\s*interest|gamma|si%|days\s*to\s*cover)\b", "squeeze_chatter"),
    (r"\b(?:fda|sec|antitrust|regulator|lawsuit|ruling|ban|tariff|compliance|enforcement|clearance|approv(?:al|ed))\b", "regulatory"),
    # Product news: tighter patterns to reduce false positives ("launch into puts", etc.)
    (r"\b(?:patent|merger|acquisition|partnership)\b", "product_news"),
    (r"\b(?:launch(?:es|ed|ing)?)\b(?!.*?\b(?:into|my|his|her)\b)", "product_news"),
    (r"\b(?:product\s+(?:release|announcement|reveal))\b", "product_news"),
    (r"\bcontract(?:s)?\s+(?:award|win|value|worth)\b", "product_news"),
    (r"\b(?:cpi|gdp|fomc|rate\s*cut|rate\s*hike|inflation|recession|macro|federal\s*reserve|monetary\s*policy|treasury|fiscal)\b", "macro"),
]

# Regex to strip negated phrases before sentiment counting
_NEGATION_RE = re.compile(
    r"\b(?:not|don'?t|won'?t|isn'?t|aren'?t|can'?t|never|no)\s+\w+", re.I
)

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
    @staticmethod
    def _has_financial_context(text: str, ticker: str) -> bool:
        """Check if a bare ticker appears near financial context words."""
        # Find all positions of the ticker in the text
        for m in re.finditer(rf"\b{re.escape(ticker)}\b", text):
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + 80)
            window = text[start:end]
            if _FINANCIAL_CONTEXT_RE.search(window):
                return True
        return False

    def extract_entities(self, title: str, body: str) -> List[str]:
        text = f"{title}\n{body}"
        matches = _TICKER_RE.findall(text)

        # Prefer explicit $TICKER mentions
        dollar = [a for (a, b) in matches if a]
        bare = [b for (a, b) in matches if b]

        # Use explicit $TICKER if available; otherwise fall back to bare
        is_explicit = bool(dollar)
        raw = dollar if dollar else bare

        out: List[str] = []
        for s in raw:
            s = ALIAS_MAP.get(s.upper(), s.upper())
            if s in NON_EQUITY_TOKENS:
                continue
            if len(s) == 1:
                continue
            # Bare tickers (no $) get extra filtering — too many common
            # English words match [A-Z]{2,5}
            if not is_explicit and s in _BARE_TICKER_BLOCKLIST:
                continue
            # Ambiguous tickers (real tickers that are also common words)
            # require financial context nearby to be extracted
            if not is_explicit and s in _CONTEXT_REQUIRED_TICKERS:
                if not self._has_financial_context(text, s):
                    continue
            # Skip tokens with repeated chars (e.g. GOOOO, AAAA)
            if not is_explicit and len(set(s)) == 1:
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
        # Strip negated phrases so "not bullish" / "don't buy" don't count
        cleaned = _NEGATION_RE.sub("", text)
        bull_count = len(_BULLISH_WORDS.findall(cleaned))
        bear_count = len(_BEARISH_WORDS.findall(cleaned))

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
