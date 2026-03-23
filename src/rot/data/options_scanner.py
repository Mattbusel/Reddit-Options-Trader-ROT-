"""Scan options chains for trading opportunities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class ScanCriteria:
    min_volume: int
    min_oi: int
    max_bid_ask_spread: float
    iv_rank_range: Tuple[float, float]
    dte_range: Tuple[int, int]
    delta_range: Tuple[float, float]


class OptionsScanner:
    """Filter and rank options chain entries by configurable criteria."""

    def __init__(self, criteria: ScanCriteria) -> None:
        self.criteria = criteria

    # ------------------------------------------------------------------
    # Core scan
    # ------------------------------------------------------------------

    def scan(self, chain: List[dict]) -> List[dict]:
        """Return options that satisfy every criterion in self.criteria."""
        c = self.criteria
        result = []
        for opt in chain:
            volume = opt.get("volume", 0)
            oi = opt.get("open_interest", 0)
            spread = opt.get("bid_ask_spread", float("inf"))
            iv_rank = opt.get("iv_rank", 0.0)
            dte = opt.get("dte", 0)
            delta = opt.get("delta", 0.0)

            if volume < c.min_volume:
                continue
            if oi < c.min_oi:
                continue
            if spread > c.max_bid_ask_spread:
                continue
            if not (c.iv_rank_range[0] <= iv_rank <= c.iv_rank_range[1]):
                continue
            if not (c.dte_range[0] <= dte <= c.dte_range[1]):
                continue
            if not (c.delta_range[0] <= delta <= c.delta_range[1]):
                continue
            result.append(opt)
        return result

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_option(self, opt: dict) -> float:
        """
        Score an option by:
          - IV/HV ratio (high IV relative to HV preferred)
          - Liquidity proxy: log(volume * OI + 1)
          - Spread tightness: 1 / (spread + 0.01)
        """
        import math

        iv = opt.get("iv", 0.0)
        hv = opt.get("hv", max(opt.get("iv", 0.01), 0.01))
        iv_hv = iv / hv if hv > 0 else 0.0

        volume = opt.get("volume", 0)
        oi = opt.get("open_interest", 0)
        liquidity = math.log(volume * oi + 1)

        spread = opt.get("bid_ask_spread", float("inf"))
        tightness = 1.0 / (spread + 0.01)

        return iv_hv + liquidity + tightness

    # ------------------------------------------------------------------
    # Specialised finders
    # ------------------------------------------------------------------

    def find_high_iv_rank(
        self, chain: List[dict], min_rank: float = 0.7
    ) -> List[dict]:
        """Return options whose iv_rank >= min_rank."""
        return [opt for opt in chain if opt.get("iv_rank", 0.0) >= min_rank]

    def find_unusual_volume(
        self, chain: List[dict], volume_oi_ratio: float = 2.0
    ) -> List[dict]:
        """Return options where volume / open_interest >= volume_oi_ratio."""
        result = []
        for opt in chain:
            oi = opt.get("open_interest", 0)
            vol = opt.get("volume", 0)
            if oi > 0 and (vol / oi) >= volume_oi_ratio:
                result.append(opt)
        return result

    def find_high_probability(
        self, chain: List[dict], min_prob_otm: float = 0.7
    ) -> List[dict]:
        """
        Return options with probability OTM >= min_prob_otm.
        prob_OTM ≈ 1 - |delta|.
        """
        result = []
        for opt in chain:
            delta = opt.get("delta", 0.0)
            prob_otm = 1.0 - abs(delta)
            if prob_otm >= min_prob_otm:
                result.append(opt)
        return result

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def rank_opportunities(self, chain: List[dict]) -> List[dict]:
        """Return chain entries sorted by score descending."""
        return sorted(chain, key=lambda opt: self.score_option(opt), reverse=True)
