from __future__ import annotations

from typing import Dict, List, Tuple

from rot.core.types import TrendCandidate
from rot.market.symbol_validator import SymbolValidator


def top_ticker_candidates(
    candidates: List[TrendCandidate],
    extracted: Dict[str, List[str]],
    validator: SymbolValidator,
    n: int = 5,
) -> List[Tuple[TrendCandidate, List[str]]]:
    """Return the top *n* (candidate, tickers) pairs ordered by trend score.

    Filters *extracted* symbols through *validator*, deduplicates, and pairs
    each valid candidate with up to five normalised ticker symbols.
    """
    pairs: List[Tuple[TrendCandidate, List[str]]] = []

    for c in candidates:
        syms = extracted.get(c.key, [])
        good = []
        for s in syms:
            s2 = validator.normalize(s)
            if validator.is_valid(s2):
                good.append(s2)
        good = sorted(set(good))[:5]
        if good:
            pairs.append((c, good))

    pairs.sort(key=lambda x: x[0].trend_score, reverse=True)
    return pairs[:n]

