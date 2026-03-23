"""Signal strength ranking for the ROT platform.

Ranks tickers by composite signal strength across multiple sentiment and
technical dimensions.  Each ticker receives a weighted composite score and
a tier label, and an ASCII leaderboard can be printed for quick review.

Usage::

    from rot.ranking import SignalRanker, RankingDimension

    ranker = SignalRanker()
    dimension_scores = {
        "AAPL": {
            RankingDimension.SENTIMENT: 0.85,
            RankingDimension.IV_RANK: 0.60,
            RankingDimension.VOLUME_SURGE: 0.45,
            RankingDimension.MOMENTUM: 0.72,
            RankingDimension.OPTIONS_FLOW: 0.90,
        },
        "TSLA": {
            RankingDimension.SENTIMENT: 0.30,
            RankingDimension.IV_RANK: 0.70,
        },
    }
    rankings = ranker.rank(["AAPL", "TSLA"], dimension_scores)
    print(ranker.leaderboard(top_n=5))
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------


class RankingDimension(str, enum.Enum):
    """Available signal dimensions for composite ranking.

    Each dimension represents an independent axis of signal quality.
    Scores should be normalised to ``[0, 1]`` before passing to
    :meth:`SignalRanker.rank`.
    """

    SENTIMENT = "sentiment"
    IV_RANK = "iv_rank"
    VOLUME_SURGE = "volume_surge"
    MOMENTUM = "momentum"
    OPTIONS_FLOW = "options_flow"


# Default equal weights for all dimensions
_DEFAULT_WEIGHTS: Dict[RankingDimension, float] = {
    RankingDimension.SENTIMENT: 1.0,
    RankingDimension.IV_RANK: 1.0,
    RankingDimension.VOLUME_SURGE: 1.0,
    RankingDimension.MOMENTUM: 1.0,
    RankingDimension.OPTIONS_FLOW: 1.0,
}

# Tier thresholds (inclusive lower bound)
_TIER_THRESHOLDS = [
    ("S", 0.8),
    ("A", 0.6),
    ("B", 0.4),
    ("C", 0.2),
    ("D", 0.0),
]


def _score_to_tier(score: float) -> str:
    """Convert a composite score in [0, 1] to a tier label."""
    for tier, threshold in _TIER_THRESHOLDS:
        if score > threshold:
            return tier
    # score == 0.0 exactly falls through to D
    return "D"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class TierRanking:
    """Ranking result for a single ticker.

    Attributes:
        ticker:     Equity/crypto ticker symbol.
        score:      Composite weighted score in ``[0, 1]``.
        tier:       Letter tier (``S`` > ``A`` > ``B`` > ``C`` > ``D``).
        breakdown:  Per-dimension score contributions (weighted fractions).
    """

    ticker: str
    score: float
    tier: str
    breakdown: Dict[str, float] = field(default_factory=dict)

    def __lt__(self, other: "TierRanking") -> bool:
        return self.score < other.score


# ---------------------------------------------------------------------------
# Ranker
# ---------------------------------------------------------------------------


class SignalRanker:
    """Ranks tickers by composite signal strength across multiple dimensions.

    Parameters
    ----------
    weights:
        Optional mapping of ``RankingDimension -> float`` for the weighted
        sum.  Missing dimensions default to 1.0.  Weights are normalised
        internally so relative values matter, not their absolute magnitude.

    Notes
    -----
    * Scores for individual dimensions should be in ``[0, 1]``.
    * Missing dimension scores for a ticker are treated as ``0.0``.
    * The ranker stores the most-recent ranking for use by
      :meth:`leaderboard`.
    """

    def __init__(
        self,
        weights: Optional[Dict[RankingDimension, float]] = None,
    ) -> None:
        raw_weights = weights or _DEFAULT_WEIGHTS
        total = sum(raw_weights.values()) or 1.0
        self._weights: Dict[RankingDimension, float] = {
            dim: w / total for dim, w in raw_weights.items()
        }
        # Ensure all dimensions have an entry
        for dim in RankingDimension:
            if dim not in self._weights:
                self._weights[dim] = 0.0

        self._last_rankings: List[TierRanking] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rank(
        self,
        tickers: List[str],
        dimension_scores: Dict[str, Dict],
    ) -> List[TierRanking]:
        """Rank *tickers* by composite signal strength.

        Parameters
        ----------
        tickers:
            List of ticker symbols to rank.
        dimension_scores:
            Mapping ``{ticker: {dimension: score}}`` where *dimension* may
            be a :class:`RankingDimension` member or its string value.

        Returns
        -------
        list[TierRanking]
            Tickers sorted by descending composite score.
        """
        rankings: List[TierRanking] = []

        for ticker in tickers:
            raw_scores = dimension_scores.get(ticker, {})
            # Normalise keys: accept both enum and string keys
            normalised: Dict[RankingDimension, float] = {}
            for k, v in raw_scores.items():
                if isinstance(k, RankingDimension):
                    normalised[k] = float(v)
                else:
                    try:
                        normalised[RankingDimension(str(k))] = float(v)
                    except ValueError:
                        pass  # unknown dimension — skip

            composite = 0.0
            breakdown: Dict[str, float] = {}
            for dim in RankingDimension:
                dim_score = normalised.get(dim, 0.0)
                w = self._weights.get(dim, 0.0)
                contribution = dim_score * w
                composite += contribution
                breakdown[dim.value] = contribution

            tier = _score_to_tier(composite)
            rankings.append(
                TierRanking(
                    ticker=ticker,
                    score=round(composite, 6),
                    tier=tier,
                    breakdown=breakdown,
                )
            )

        rankings.sort(key=lambda r: r.score, reverse=True)
        self._last_rankings = rankings
        return rankings

    def leaderboard(self, top_n: int = 10) -> str:
        """Format the most-recent ranking as an ASCII leaderboard table.

        Parameters
        ----------
        top_n:
            Maximum number of rows to display.

        Returns
        -------
        str
            Formatted ASCII table string.
        """
        rankings = self._last_rankings[:top_n]
        if not rankings:
            return "(no rankings computed yet — call rank() first)"

        header = f"{'Rank':>4}  {'Ticker':<8}  {'Score':>6}  {'Tier':>4}  Breakdown"
        sep = "-" * (len(header) + 10)
        lines = [sep, header, sep]

        for i, r in enumerate(rankings, start=1):
            bd_parts = [
                f"{dim_name}={v:.2f}"
                for dim_name, v in sorted(r.breakdown.items())
                if v > 0.0
            ]
            bd_str = "  ".join(bd_parts) if bd_parts else "-"
            lines.append(
                f"{i:>4}  {r.ticker:<8}  {r.score:>6.4f}  {r.tier:>4}  {bd_str}"
            )

        lines.append(sep)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def weights(self) -> Dict[RankingDimension, float]:
        """Normalised per-dimension weights (sum to 1.0)."""
        return dict(self._weights)

    def update_weights(self, weights: Dict[RankingDimension, float]) -> None:
        """Replace dimension weights and re-normalise.

        Parameters
        ----------
        weights:
            New weight mapping.  Missing dimensions are set to 0.0.
        """
        total = sum(weights.values()) or 1.0
        self._weights = {
            dim: weights.get(dim, 0.0) / total for dim in RankingDimension
        }
