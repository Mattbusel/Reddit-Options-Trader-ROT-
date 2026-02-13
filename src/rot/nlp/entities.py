"""Context-aware entity resolver for the ROT NLP engine.

Extracts tickers via cashtag, bare ticker, implicit resolution
(CEO names, company descriptions), and sector expansion.
Reuses existing blocklists from enricher.py and event_builder.py.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from rot.nlp.types import (
    OptionsEntity,
    PositionEntity,
    ResolvedEntity,
    Token,
)

# Import existing blocklists (no duplication)
from rot.market.enricher import ALIAS_MAP, NON_EQUITY_TOKENS
from rot.extract.event_builder import (
    _BARE_TICKER_BLOCKLIST,
    _CONTEXT_REQUIRED_TICKERS,
    _FINANCIAL_CONTEXT_RE,
)

# ── Implicit entity resolution map ──
# CEO names, founder references, company descriptions → tickers

_IMPLICIT_ENTITIES: Dict[str, str] = {
    # Tesla
    "elon": "TSLA", "musk": "TSLA", "papa elon": "TSLA",
    "elon musk": "TSLA", "tesla": "TSLA",
    "the ev maker": "TSLA", "the ev company": "TSLA",
    # NVIDIA
    "jensen": "NVDA", "jensen huang": "NVDA", "huang": "NVDA",
    "the chip maker": "NVDA", "the gpu company": "NVDA",
    "nvidia": "NVDA",
    # Apple
    "tim cook": "AAPL", "tim apple": "AAPL",
    "the fruit company": "AAPL", "cupertino": "AAPL",
    # Meta
    "zuck": "META", "zuckerberg": "META", "mark zuckerberg": "META",
    "the social network": "META", "metaverse company": "META",
    "facebook": "META",
    # Amazon
    "bezos": "AMZN", "jeff bezos": "AMZN",
    "the everything store": "AMZN",
    # Microsoft
    "satya": "MSFT", "nadella": "MSFT", "satya nadella": "MSFT",
    "microsoft": "MSFT",
    # Google
    "pichai": "GOOGL", "sundar": "GOOGL", "sundar pichai": "GOOGL",
    "the search giant": "GOOGL", "google": "GOOGL", "alphabet": "GOOGL",
    # AMD
    "su bae": "AMD", "lisa su": "AMD",
    # ARK
    "cathie": "ARKK", "cathie wood": "ARKK",
    # Berkshire
    "buffett": "BRK-B", "warren buffett": "BRK-B", "the oracle": "BRK-B",
    "uncle warren": "BRK-B",
    # JPMorgan
    "jamie dimon": "JPM", "dimon": "JPM",
    # GameStop
    "gamestop": "GME", "roaring kitty": "GME", "dfv": "GME",
    "deep fucking value": "GME", "keith gill": "GME",
    # Others
    "palantir": "PLTR", "peter thiel": "PLTR",
    "chamath": "SOFI",
    "michael burry": "SCION",  # not directly tradeable but context
    "jpow": "SPY", "jerome powell": "SPY", "powell": "SPY",  # Fed proxy
    "yellen": "TLT", "janet yellen": "TLT",  # bond proxy
}

# ── Sector expansion map ──

_SECTOR_TICKERS: Dict[str, List[str]] = {
    "semiconductor": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM"],
    "semiconductors": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM"],
    "chip": ["NVDA", "AMD", "INTC", "TSM"],
    "chips": ["NVDA", "AMD", "INTC", "TSM"],
    "ev": ["TSLA", "RIVN", "LCID", "NIO", "LI"],
    "electric vehicle": ["TSLA", "RIVN", "LCID", "NIO"],
    "faang": ["META", "AAPL", "AMZN", "NVDA", "GOOGL"],
    "mag7": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"],
    "magnificent seven": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"],
    "magnificent 7": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"],
    "bank": ["JPM", "BAC", "GS", "MS", "C"],
    "banks": ["JPM", "BAC", "GS", "MS", "C"],
    "banking": ["JPM", "BAC", "GS", "MS", "C"],
    "pharma": ["PFE", "JNJ", "MRK", "LLY", "ABBV"],
    "biotech": ["MRNA", "GILD", "REGN", "VRTX", "BIIB"],
    "defense": ["LMT", "RTX", "NOC", "GD", "BA"],
    "aerospace": ["BA", "LMT", "RTX", "NOC"],
    "meme": ["GME", "AMC", "BB"],
    "meme stock": ["GME", "AMC", "BB"],
    "meme stocks": ["GME", "AMC", "BB"],
    "big tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META"],
    "oil": ["XOM", "CVX", "COP", "OXY"],
    "energy": ["XOM", "CVX", "COP", "OXY", "SLB"],
    "cannabis": ["TLRY", "CGC", "ACB"],
    "weed": ["TLRY", "CGC", "ACB"],
    "ai": ["NVDA", "MSFT", "GOOGL", "AMD", "PLTR"],
    "artificial intelligence": ["NVDA", "MSFT", "GOOGL", "AMD"],
    "crypto": ["COIN", "MSTR", "MARA", "RIOT"],
    "bitcoin": ["COIN", "MSTR", "MARA"],
    "retail": ["WMT", "TGT", "COST", "AMZN"],
    "streaming": ["NFLX", "DIS", "ROKU"],
}

# Pattern for "$SECTOR stocks" references
_SECTOR_STOCKS_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(_SECTOR_TICKERS.keys(), key=len, reverse=True))
    + r")\s+stocks?\b",
    re.I,
)

# Position patterns
_POSITION_RE = re.compile(
    r"\b(?:i(?:'?m|\s+am)|im|went|going)\s+(long|short)\s+(\d+)?\s*(shares?|contracts?|calls?|puts?)?\b",
    re.I,
)
_SIMPLE_POSITION_RE = re.compile(
    r"\b(long|short)\s+(\d+)\s*(shares?|contracts?|calls?|puts?)\b",
    re.I,
)


class EntityResolver:
    """Context-aware entity resolver for financial text.

    Resolution layers (in priority order):
    1. Cashtag tokens ($TSLA) — highest confidence
    2. Bare uppercase tickers — filtered by blocklist + context
    3. Implicit entities — CEO names, company descriptions
    4. Sector expansion — "semiconductor stocks" → [NVDA, AMD, ...]
    5. Options entities — "$450C", "300P 1/17"
    6. Position entities — "I'm long 100 shares"
    """

    def resolve(
        self,
        tokens: List[Token],
        full_text: str,
    ) -> Tuple[List[ResolvedEntity], List[OptionsEntity], List[PositionEntity]]:
        """Resolve all entities from tokens + full text."""
        entities: List[ResolvedEntity] = []
        seen_symbols: Set[str] = set()

        # Layer 1: Cashtag tokens
        for t in tokens:
            if t.token_type == "cashtag":
                sym = ALIAS_MAP.get(t.text.upper(), t.text.upper())
                if sym not in NON_EQUITY_TOKENS and sym not in seen_symbols:
                    entities.append(ResolvedEntity(
                        symbol=sym,
                        raw_text=f"${t.text}",
                        resolution_method="cashtag",
                        confidence=0.95,
                        span=(t.start, t.end),
                    ))
                    seen_symbols.add(sym)

        # Layer 2: Bare uppercase tickers
        has_cashtag = len(entities) > 0
        if not has_cashtag:
            for t in tokens:
                if t.token_type != "word":
                    continue
                sym = t.text.upper()
                if len(sym) < 2 or len(sym) > 5:
                    continue
                if not sym.isalpha():
                    continue
                if not t.meta.get("is_caps", False) and len(sym) > 1:
                    # Only consider words that were ALL-CAPS in original
                    continue

                sym = ALIAS_MAP.get(sym, sym)
                if sym in NON_EQUITY_TOKENS:
                    continue
                if sym in _BARE_TICKER_BLOCKLIST:
                    continue
                if sym in _CONTEXT_REQUIRED_TICKERS:
                    if not self._has_financial_context(full_text, sym):
                        continue
                # Skip single repeated char
                if len(set(sym)) == 1:
                    continue
                if sym not in seen_symbols:
                    entities.append(ResolvedEntity(
                        symbol=sym,
                        raw_text=t.raw,
                        resolution_method="bare_ticker",
                        confidence=0.6,
                        span=(t.start, t.end),
                    ))
                    seen_symbols.add(sym)

        # Layer 3: Implicit entities (CEO names, company descriptions)
        text_lower = full_text.lower()
        # Sort by phrase length (longest first) to match multi-word phrases first
        for phrase, ticker in sorted(_IMPLICIT_ENTITIES.items(), key=lambda x: -len(x[0])):
            if phrase in text_lower and ticker not in seen_symbols:
                idx = text_lower.find(phrase)
                entities.append(ResolvedEntity(
                    symbol=ticker,
                    raw_text=full_text[idx:idx + len(phrase)],
                    resolution_method="implicit",
                    confidence=0.7,
                    span=(idx, idx + len(phrase)),
                ))
                seen_symbols.add(ticker)

        # Layer 4: Sector expansion
        for m in _SECTOR_STOCKS_RE.finditer(full_text):
            sector_key = m.group(1).lower()
            tickers = _SECTOR_TICKERS.get(sector_key, [])
            for ticker in tickers:
                if ticker not in seen_symbols:
                    entities.append(ResolvedEntity(
                        symbol=ticker,
                        raw_text=m.group(),
                        resolution_method="sector",
                        confidence=0.4,
                        span=(m.start(), m.end()),
                    ))
                    seen_symbols.add(ticker)

        # Layer 5: Options entities
        options = self._extract_options(tokens)

        # Layer 6: Position entities
        positions = self._extract_positions(full_text)

        # Sort by confidence descending, cap at 5
        entities.sort(key=lambda e: -e.confidence)
        entities = entities[:5]

        # Assign per-ticker sentiment from nearby tokens
        entities = self._assign_ticker_sentiment(entities, tokens)

        return entities, options, positions

    def extract_tickers_only(self, tokens: List[Token], full_text: str) -> List[str]:
        """Quick ticker extraction — returns just symbol strings."""
        entities, _, _ = self.resolve(tokens, full_text)
        return [e.symbol for e in entities]

    @staticmethod
    def _has_financial_context(text: str, ticker: str) -> bool:
        """Check if a bare ticker appears near financial context words."""
        for m in re.finditer(rf"\b{re.escape(ticker)}\b", text):
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + 80)
            window = text[start:end]
            if _FINANCIAL_CONTEXT_RE.search(window):
                return True
        return False

    @staticmethod
    def _extract_options(tokens: List[Token]) -> List[OptionsEntity]:
        """Extract options contract entities from tokens."""
        options: List[OptionsEntity] = []
        for t in tokens:
            if t.token_type == "options_contract":
                options.append(OptionsEntity(
                    ticker_context=None,  # may be inferred from nearby cashtag
                    strike=t.meta.get("strike"),
                    kind=t.meta.get("option_kind"),
                    expiry_text=t.meta.get("expiry_text"),
                    raw_text=t.raw,
                    span=(t.start, t.end),
                ))
        return options

    @staticmethod
    def _extract_positions(full_text: str) -> List[PositionEntity]:
        """Extract position descriptions from text."""
        positions: List[PositionEntity] = []

        for pattern in (_POSITION_RE, _SIMPLE_POSITION_RE):
            for m in pattern.finditer(full_text):
                pos_type = m.group(1).lower()
                qty_str = m.group(2)
                instrument = m.group(3)

                quantity = int(qty_str) if qty_str else None
                inst = instrument.rstrip("s").lower() if instrument else None

                positions.append(PositionEntity(
                    position_type=pos_type,
                    quantity=quantity,
                    instrument=inst,
                    raw_text=m.group(),
                    span=(m.start(), m.end()),
                ))

        return positions

    def _assign_ticker_sentiment(
        self, entities: List[ResolvedEntity], tokens: List[Token]
    ) -> List[ResolvedEntity]:
        """Assign per-ticker sentiment by checking nearby tokens.

        E.g., "NVDA calls and AMD puts" → NVDA=bullish, AMD=bearish
        """
        from rot.nlp.lexicon import get_lexicon
        lex = get_lexicon()
        result: List[ResolvedEntity] = []

        for entity in entities:
            # Find tokens within 3 positions of this entity's span
            nearby_polarity = 0.0
            nearby_count = 0
            for t in tokens:
                if t.token_type not in ("word", "emoji"):
                    continue
                # Check if this token is within ~60 chars of the entity mention
                dist = min(
                    abs(t.start - entity.span[1]),
                    abs(t.end - entity.span[0]),
                )
                if dist > 60:
                    continue
                entry = lex.get(t.text.lower())
                if entry and abs(entry.polarity) > 0.3:
                    nearby_polarity += entry.polarity
                    nearby_count += 1

            sentiment = None
            if nearby_count > 0:
                avg = nearby_polarity / nearby_count
                if avg > 0.15:
                    sentiment = "bullish"
                elif avg < -0.15:
                    sentiment = "bearish"

            if sentiment != entity.sentiment_toward:
                result.append(ResolvedEntity(
                    symbol=entity.symbol,
                    raw_text=entity.raw_text,
                    resolution_method=entity.resolution_method,
                    confidence=entity.confidence,
                    span=entity.span,
                    sentiment_toward=sentiment,
                ))
            else:
                result.append(entity)

        return result
