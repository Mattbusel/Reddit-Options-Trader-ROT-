from __future__ import annotations

from typing import List

from rot.core.types import TrendCandidate


def top_n_candidates(candidates: List[TrendCandidate], n: int = 5) -> List[TrendCandidate]:
    """Return the *n* highest-scoring candidates sorted by ``trend_score`` descending."""
    return sorted(candidates, key=lambda c: c.trend_score, reverse=True)[:n]
