"""Shared ticker-resolution constants.

Extracted from ``event_builder.py`` so that ``rot.nlp.entities`` (and any other
module) can import them without creating a cyclic import chain through the NLP
engine.
"""
from __future__ import annotations

import re

# Matches $TSLA or TSLA
TICKER_RE = re.compile(r"(?:\$([A-Z]{1,5})\b|\b([A-Z]{1,5})\b)")

# Additional filter for bare (non-$) tickers: common short words that sneak
# through NON_EQUITY_TOKENS because there are too many 2-3 letter combos.
BARE_TICKER_BLOCKLIST = {
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
    # Profanity / slang / junk that pass yfinance but aren't real tickers
    "FUCK", "BS", "EOY", "JP", "OF", "GEX", "SIX",
    # Economic indicators / data releases (not tickers)
    "JOLTS", "NFP", "PMI", "PCE", "PPI", "ADP", "ISM",
    # Business metrics that look like tickers
    "GMV", "MAU", "ARR", "MRR", "GFC",
}

# Real tickers that are also common English words. We only extract these
# as bare (non-$) tickers when they appear near financial context words.
CONTEXT_REQUIRED_TICKERS = {
    "COST", "LOVE", "GAIN", "FIRE", "PLAY", "WORK",
    "UNIT", "RIDE", "WISH", "NICE", "OPEN",
}

# Pattern to check for financial context near an ambiguous ticker
FINANCIAL_CONTEXT_RE = re.compile(
    r"\b(?:stock|shares?|calls?|puts?|options?|position|earnings|buy|sell|"
    r"portfolio|contracts?|strike|expir|otm|itm|atm|premium|spread|bullish|bearish)\b",
    re.I,
)
