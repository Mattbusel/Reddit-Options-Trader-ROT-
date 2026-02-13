"""Financial-aware tokenizer for the ROT NLP engine.

Understands cashtags ($TSLA), emojis, ALL-CAPS emphasis, repeated chars,
options contracts, Reddit markdown, and financial abbreviations.
Zero external dependencies.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from rot.nlp.types import Token, TokenType

# ── Emoji lookup: financial-relevant emoji → named tokens ──

_EMOJI_MAP: dict[str, str] = {
    # Bullish
    "\U0001f680": "ROCKET_EMOJI",          # rocket
    "\U0001f4c8": "CHART_UP_EMOJI",        # chart increasing
    "\U0001f402": "BULL_EMOJI",            # ox/bull
    "\U0001f48e": "DIAMOND_EMOJI",         # diamond
    "\U0001f64c": "RAISED_HANDS_EMOJI",    # raised hands
    "\U0001f525": "FIRE_EMOJI",            # fire/hot
    "\U0001f4b0": "MONEY_BAG_EMOJI",       # money bag
    "\U0001f4b5": "DOLLAR_EMOJI",          # dollar banknote
    "\U0001f911": "MONEY_FACE_EMOJI",      # money-mouth face
    "\U0001f389": "PARTY_EMOJI",           # party popper
    "\u2705": "CHECK_EMOJI",               # green checkmark
    "\U0001f31d": "MOON_FACE_EMOJI",       # full moon face
    "\U0001f315": "MOON_EMOJI",            # full moon
    "\U0001f31a": "NEW_MOON_FACE_EMOJI",   # new moon face
    "\U0001f4aa": "MUSCLE_EMOJI",          # flexed bicep
    # Bearish
    "\U0001f4c9": "CHART_DOWN_EMOJI",      # chart decreasing
    "\U0001f43b": "BEAR_EMOJI",            # bear
    "\U0001f4a9": "POOP_EMOJI",            # pile of poop
    "\U0001f62d": "CRYING_EMOJI",          # loudly crying
    "\U0001f4b8": "MONEY_WINGS_EMOJI",     # money with wings
    "\U0001f480": "SKULL_EMOJI",           # skull
    "\u2620\ufe0f": "SKULL_CROSSBONES",    # skull and crossbones
    "\u2620": "SKULL_CROSSBONES",          # skull and crossbones (no VS16)
    "\U0001f6a8": "SIREN_EMOJI",           # police siren
    "\U0001f494": "BROKEN_HEART_EMOJI",    # broken heart
    # Sarcasm / irony
    "\U0001f921": "CLOWN_EMOJI",           # clown face
    "\U0001f913": "NERD_EMOJI",            # nerd face
    "\U0001f644": "EYEROLL_EMOJI",         # rolling eyes
    "\U0001f928": "RAISED_EYEBROW_EMOJI",  # face with raised eyebrow
    "\U0001f3b0": "SLOT_MACHINE_EMOJI",    # slot machine / gambling
    "\U0001f92f": "MIND_BLOWN_EMOJI",      # exploding head
    # Neutral / context
    "\u26a0\ufe0f": "WARNING_EMOJI",       # warning
    "\u26a0": "WARNING_EMOJI",             # warning (no VS16)
    "\U0001f4ca": "BAR_CHART_EMOJI",       # bar chart
    "\U0001f4dd": "MEMO_EMOJI",            # memo / DD
    "\U0001f4e2": "LOUDSPEAKER_EMOJI",     # loudspeaker / announcement
    "\u2757": "EXCLAMATION_EMOJI",         # exclamation mark
    "\u203c\ufe0f": "DOUBLE_EXCL_EMOJI",   # double exclamation
    "\u203c": "DOUBLE_EXCL_EMOJI",
    "\u2049\ufe0f": "EXCL_QUESTION_EMOJI", # exclamation question mark
    "\u2049": "EXCL_QUESTION_EMOJI",
}

# Build a regex alternation from emoji keys (longest first to match multi-char)
_EMOJI_PATTERN = re.compile(
    "|".join(re.escape(e) for e in sorted(_EMOJI_MAP.keys(), key=len, reverse=True))
)

# ── Regex patterns (applied in priority order) ──

# Cashtag: $TSLA, $SPY — NOT dollar amounts like $100
_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")

# Dollar amount: $100, $1,234.56
_DOLLAR_AMOUNT_RE = re.compile(r"\$[\d,]+(?:\.\d+)?")

# Options contract shorthand: 450C, 300P, $450C, 450c 1/17, TSLA 450C
_OPTIONS_CONTRACT_RE = re.compile(
    r"(?:\$?)(\d+(?:\.\d+)?)\s*([CcPp])\b(?:\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?))?",
)

# URL
_URL_RE = re.compile(r"https?://[^\s\)>\]]+")

# Reddit mention u/username
_MENTION_RE = re.compile(r"\bu/[A-Za-z0-9_-]+")

# Hashtag
_HASHTAG_RE = re.compile(r"#[A-Za-z0-9_]+")

# Markdown formatting to strip
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_MD_STRIKE_RE = re.compile(r"~~(.+?)~~")
_MD_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_MD_INLINE_CODE_RE = re.compile(r"`(.+?)`")
_MD_BLOCKQUOTE_RE = re.compile(r"^>\s?", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^\)]*\)")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)

# Repeated characters: GOOOOO → GO + repeat_count
_REPEATED_CHARS_RE = re.compile(r"(.)\1{2,}")

# Financial abbreviations that should stay whole
_FINANCIAL_ABBREVS = {
    "0DTE", "0dte", "P/E", "p/e", "EPS", "eps", "GDP", "gdp",
    "CPI", "cpi", "FOMC", "fomc", "IPO", "ipo", "ATH", "ath",
    "ATM", "atm", "OTM", "otm", "ITM", "itm", "IV", "iv",
    "OI", "oi", "DTE", "dte", "DYOR", "dyor", "DD", "dd",
    "SI", "si", "FD", "fd", "YOLO", "yolo", "FOMO", "fomo",
    "RSI", "rsi", "MACD", "macd", "EMA", "ema", "SMA", "sma",
    "VWAP", "vwap", "52wk",
}

# Word boundary split pattern — keeps hyphenated words together
_WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*|[A-Za-z]+")

# Number pattern
_NUMBER_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?%?")


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting, preserving inner text."""
    text = _MD_CODE_BLOCK_RE.sub(" ", text)
    text = _MD_INLINE_CODE_RE.sub(r"\1", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_ITALIC_RE.sub(r"\1", text)
    text = _MD_STRIKE_RE.sub(r"\1", text)
    text = _MD_BLOCKQUOTE_RE.sub("", text)
    text = _MD_HEADING_RE.sub("", text)
    return text


def _normalize_repeated_chars(word: str) -> Tuple[str, int]:
    """Normalize repeated characters: GOOOOO → (GO, 4).

    Returns (normalized_word, repeat_count). repeat_count = 0 if no repeats.
    """
    match = _REPEATED_CHARS_RE.search(word)
    if not match:
        return word, 0

    # Count max run of any single char
    max_run = 0
    for m in _REPEATED_CHARS_RE.finditer(word):
        run_len = m.end() - m.start()
        max_run = max(max_run, run_len)

    normalized = _REPEATED_CHARS_RE.sub(r"\1", word)
    return normalized, max_run


class Tokenizer:
    """Financial-aware tokenizer for Reddit posts.

    Produces Token objects with metadata for downstream NLP components.
    Handles cashtags, emojis, ALL-CAPS, repeated chars, options contracts,
    and Reddit markdown.
    """

    def tokenize(self, text: str) -> List[Token]:
        """Tokenize raw text into a list of Token objects."""
        # Strip markdown formatting
        cleaned = _strip_markdown(text)

        tokens: List[Token] = []
        # We process the text by finding special patterns first,
        # then tokenizing the remaining text as words/numbers.
        segments = self._segment(cleaned)

        for seg_text, seg_start, seg_type, seg_meta in segments:
            tokens.append(Token(
                text=seg_text,
                raw=text[seg_start:seg_start + len(seg_text)] if seg_start < len(text) else seg_text,
                token_type=seg_type,
                start=seg_start,
                end=seg_start + len(seg_text),
                meta=seg_meta,
            ))

        return tokens

    def tokenize_post(self, title: str, body: str) -> Tuple[List[Token], List[Token]]:
        """Tokenize title and body separately, returning both token lists."""
        return self.tokenize(title), self.tokenize(body)

    def _segment(self, text: str) -> List[Tuple[str, int, TokenType, dict]]:
        """Segment text into (normalized_text, start, type, meta) tuples.

        Applies pattern matching in priority order. Remaining gaps
        are tokenized as words/numbers.
        """
        # Mark character spans that have been claimed by special patterns
        claimed: List[Tuple[int, int, str, TokenType, dict]] = []

        # 1. URLs (strip from analysis but mark position)
        for m in _URL_RE.finditer(text):
            claimed.append((m.start(), m.end(), m.group(), "url", {}))

        # 2. Emojis
        for m in _EMOJI_PATTERN.finditer(text):
            emoji_name = _EMOJI_MAP.get(m.group(), "UNKNOWN_EMOJI")
            claimed.append((m.start(), m.end(), emoji_name, "emoji", {"emoji_raw": m.group()}))

        # 3. Cashtags ($TSLA)
        for m in _CASHTAG_RE.finditer(text):
            # Make sure this isn't inside a URL
            if self._is_in_claimed(m.start(), claimed):
                continue
            claimed.append((m.start(), m.end(), m.group(1).upper(), "cashtag", {}))

        # 4. Dollar amounts ($100)
        for m in _DOLLAR_AMOUNT_RE.finditer(text):
            if self._is_in_claimed(m.start(), claimed):
                continue
            claimed.append((m.start(), m.end(), m.group(), "dollar_amount", {}))

        # 5. Options contracts (450C, 300P 1/17)
        for m in _OPTIONS_CONTRACT_RE.finditer(text):
            if self._is_in_claimed(m.start(), claimed):
                continue
            strike = float(m.group(1))
            kind = "call" if m.group(2).upper() == "C" else "put"
            expiry = m.group(3) if m.group(3) else None
            meta = {"strike": strike, "option_kind": kind}
            if expiry:
                meta["expiry_text"] = expiry
            claimed.append((m.start(), m.end(), m.group().strip(), "options_contract", meta))

        # 6. Mentions (u/username)
        for m in _MENTION_RE.finditer(text):
            if self._is_in_claimed(m.start(), claimed):
                continue
            claimed.append((m.start(), m.end(), m.group(), "mention", {}))

        # 7. Hashtags (#tag)
        for m in _HASHTAG_RE.finditer(text):
            if self._is_in_claimed(m.start(), claimed):
                continue
            claimed.append((m.start(), m.end(), m.group(), "hashtag", {}))

        # Sort claimed by start position
        claimed.sort(key=lambda x: x[0])

        # 8. Fill gaps with words/numbers
        result: List[Tuple[str, int, TokenType, dict]] = []
        pos = 0

        for c_start, c_end, c_text, c_type, c_meta in claimed:
            # Process gap before this claimed span
            if pos < c_start:
                gap = text[pos:c_start]
                result.extend(self._tokenize_plain_text(gap, pos))
            # Add the claimed token
            result.append((c_text, c_start, c_type, c_meta))
            pos = c_end

        # Process trailing gap
        if pos < len(text):
            gap = text[pos:]
            result.extend(self._tokenize_plain_text(gap, pos))

        return result

    def _tokenize_plain_text(self, text: str, offset: int) -> List[Tuple[str, int, TokenType, dict]]:
        """Tokenize plain text (no special patterns) into words and numbers."""
        tokens: List[Tuple[str, int, TokenType, dict]] = []

        # Numbers first
        num_spans: set[Tuple[int, int]] = set()
        for m in _NUMBER_RE.finditer(text):
            abs_start = offset + m.start()
            tokens.append((m.group(), abs_start, "number", {}))
            num_spans.add((m.start(), m.end()))

        # Words
        for m in _WORD_RE.finditer(text):
            # Skip if overlaps with a number
            if any(m.start() < ne and m.end() > ns for ns, ne in num_spans):
                continue

            word = m.group()
            abs_start = offset + m.start()
            meta: dict = {}

            # Check if financial abbreviation (keep as-is)
            if word in _FINANCIAL_ABBREVS or word.upper() in _FINANCIAL_ABBREVS:
                tokens.append((word.upper(), abs_start, "word", {"is_abbrev": True}))
                continue

            # ALL-CAPS detection (2+ letter words)
            if len(word) >= 2 and word == word.upper() and word.isalpha():
                meta["is_caps"] = True

            # Repeated character normalization
            normalized, repeat_count = _normalize_repeated_chars(word)
            if repeat_count > 0:
                meta["repeat_count"] = repeat_count
                meta["is_caps"] = meta.get("is_caps", False)
                word = normalized

            tokens.append((word, abs_start, "word", meta))

        # Sort by position
        tokens.sort(key=lambda x: x[1])
        return tokens

    @staticmethod
    def _is_in_claimed(pos: int, claimed: List[Tuple[int, int, str, TokenType, dict]]) -> bool:
        """Check if a position falls inside an already-claimed span."""
        for c_start, c_end, *_ in claimed:
            if c_start <= pos < c_end:
                return True
        return False
