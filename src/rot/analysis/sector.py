"""Sector rotation analysis engine.

Computes momentum, detects rotation, ranks sectors, and measures capital flow
from signal data returned by the database.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from rot.analysis.sector_types import (
    CapitalFlow,
    RotationEvent,
    SectorMomentum,
    SectorRanking,
)


class SectorAnalyzer:
    """Analyzes sector rotation patterns from signal data."""

    def __init__(self, min_signals: int = 3) -> None:
        self._min_signals = min_signals

    # ── Momentum ──

    def compute_sector_momentum(
        self,
        sector_data: List[Dict[str, Any]],
        days: int = 30,
    ) -> List[SectorMomentum]:
        """Compute momentum scores for each sector.

        Parameters
        ----------
        sector_data:
            List of signal dicts with at least: sector, stance, confidence, created_at.
        days:
            Time window in days.

        Returns
        -------
        List of SectorMomentum sorted by score descending.
        """
        now = time.time()
        cutoff = now - (days * 86400)
        half_point = now - (days * 86400 / 2)

        # Group by sector
        by_sector: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for s in sector_data:
            sector = s.get("sector", "").strip()
            ts = s.get("created_at", 0)
            if sector and ts >= cutoff:
                by_sector[sector].append(s)

        results = []
        for sector, signals in by_sector.items():
            if len(signals) < self._min_signals:
                continue

            total = len(signals)
            # Split into recent vs older half
            recent = [s for s in signals if s.get("created_at", 0) >= half_point]
            older = [s for s in signals if s.get("created_at", 0) < half_point]

            days_total = max(days, 1)
            half_days = max(days / 2, 1)
            velocity = total / days_total
            recent_velocity = len(recent) / half_days
            older_velocity = len(older) / half_days

            acceleration = recent_velocity - older_velocity
            if acceleration > 0.1:
                trend = "accelerating"
            elif acceleration < -0.1:
                trend = "decelerating"
            else:
                trend = "stable"

            bullish = sum(1 for s in signals if s.get("stance") == "bullish")
            bearish = sum(1 for s in signals if s.get("stance") == "bearish")
            bullish_pct = (bullish / total) * 100 if total else 0
            bearish_pct = (bearish / total) * 100 if total else 0

            # Momentum score: volume + acceleration + sentiment balance
            volume_score = min(50.0, velocity * 10)
            accel_score = min(30.0, max(0, acceleration * 20))
            balance = abs(bullish_pct - bearish_pct) / 100
            conviction_score = balance * 20
            score = min(100.0, volume_score + accel_score + conviction_score)

            results.append(SectorMomentum(
                sector=sector,
                signal_velocity=velocity,
                trend=trend,
                acceleration=acceleration,
                score=round(score, 1),
                signal_count=total,
                bullish_pct=bullish_pct,
                bearish_pct=bearish_pct,
            ))

        results.sort(key=lambda m: m.score, reverse=True)
        return results

    # ── Rotation Detection ──

    def detect_rotation(
        self,
        sector_snapshots: List[Dict[str, Any]],
        days: int = 30,
    ) -> List[RotationEvent]:
        """Detect sector leadership changes.

        Compares recent half vs older half momentum to find sectors
        that are rising while the former leader is falling.
        """
        momentum_list = self.compute_sector_momentum(sector_snapshots, days)
        if len(momentum_list) < 2:
            return []

        # Also compute momentum for prior period to detect shifts
        now = time.time()
        prior_cutoff = now - (days * 2 * 86400)
        prior_signals = [
            s for s in sector_snapshots
            if s.get("created_at", 0) >= prior_cutoff
            and s.get("created_at", 0) < now - (days * 86400)
        ]
        prior_momentum = self.compute_sector_momentum(prior_signals, days) if prior_signals else []
        prior_map = {m.sector: m for m in prior_momentum}

        events = []
        current_leader = momentum_list[0]

        for prior_sector, prior_m in prior_map.items():
            # Was this the prior leader that's now declining?
            current_m = next(
                (m for m in momentum_list if m.sector == prior_sector), None
            )
            if not current_m:
                continue

            # Prior leader that decelerated, while new leader accelerated
            if (
                prior_m.score > current_leader.score * 0.5
                and current_m.acceleration < -0.1
                and current_leader.acceleration > 0.1
                and current_leader.sector != prior_sector
            ):
                confidence = min(1.0, (
                    abs(current_m.acceleration) * 0.4
                    + current_leader.acceleration * 0.4
                    + (current_leader.score / 100) * 0.2
                ))
                events.append(RotationEvent(
                    from_sector=prior_sector,
                    to_sector=current_leader.sector,
                    detected_at=now,
                    confidence=round(confidence, 2),
                    from_velocity_delta=current_m.acceleration,
                    to_velocity_delta=current_leader.acceleration,
                ))

        events.sort(key=lambda e: e.confidence, reverse=True)
        return events

    # ── Capital Flow ──

    def compute_capital_flow(
        self,
        sector_data: List[Dict[str, Any]],
        days: int = 30,
        prior_days: Optional[int] = None,
    ) -> List[CapitalFlow]:
        """Compute net bullish/bearish intensity per sector.

        Parameters
        ----------
        prior_days:
            If given, also compute flow_change vs this prior period.
        """
        now = time.time()
        cutoff = now - (days * 86400)
        prior_cutoff = now - ((prior_days or days * 2) * 86400)

        by_sector: Dict[str, Dict[str, list]] = defaultdict(
            lambda: {"current": [], "prior": []}
        )
        for s in sector_data:
            sector = s.get("sector", "").strip()
            ts = s.get("created_at", 0)
            if not sector:
                continue
            if ts >= cutoff:
                by_sector[sector]["current"].append(s)
            elif prior_days and ts >= prior_cutoff:
                by_sector[sector]["prior"].append(s)

        results = []
        for sector, buckets in by_sector.items():
            current = buckets["current"]
            if not current:
                continue

            bullish = [s for s in current if s.get("stance") == "bullish"]
            bearish = [s for s in current if s.get("stance") == "bearish"]
            mixed = [s for s in current if s.get("stance") == "mixed"]

            bull_conf = sum(s.get("confidence", 0.5) for s in bullish)
            bear_conf = sum(s.get("confidence", 0.5) for s in bearish)
            bull_intensity = bull_conf / len(bullish) if bullish else 0
            bear_intensity = bear_conf / len(bearish) if bearish else 0

            net_flow = bull_conf - bear_conf

            # Compute change vs prior period
            prior = buckets["prior"]
            prior_net = 0.0
            if prior:
                p_bull = sum(
                    s.get("confidence", 0.5)
                    for s in prior if s.get("stance") == "bullish"
                )
                p_bear = sum(
                    s.get("confidence", 0.5)
                    for s in prior if s.get("stance") == "bearish"
                )
                prior_net = p_bull - p_bear

            results.append(CapitalFlow(
                sector=sector,
                bullish_count=len(bullish),
                bearish_count=len(bearish),
                mixed_count=len(mixed),
                bullish_intensity=bull_intensity,
                bearish_intensity=bear_intensity,
                net_flow=net_flow,
                flow_change=net_flow - prior_net,
            ))

        results.sort(key=lambda f: abs(f.net_flow), reverse=True)
        return results

    # ── Ranking ──

    def rank_sectors(
        self,
        sector_data: List[Dict[str, Any]],
        performance_data: Optional[Dict[str, Dict[str, Any]]] = None,
        days: int = 30,
    ) -> List[SectorRanking]:
        """Rank sectors by composite score.

        Parameters
        ----------
        performance_data:
            Optional dict of {sector: {win_rate, total_tracked}} from DB.
        """
        momentum_list = self.compute_sector_momentum(sector_data, days)
        if not momentum_list:
            return []

        # Compute per-sector sentiment
        by_sector: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for s in sector_data:
            sector = s.get("sector", "").strip()
            if sector:
                by_sector[sector].append(s)

        rankings = []
        for mom in momentum_list:
            signals = by_sector.get(mom.sector, [])
            bullish = sum(1 for s in signals if s.get("stance") == "bullish")
            bearish = sum(1 for s in signals if s.get("stance") == "bearish")
            total = max(len(signals), 1)
            net_sentiment = (bullish - bearish) / total

            win_rate = None
            wr_bonus = 0.0
            if performance_data and mom.sector in performance_data:
                perf = performance_data[mom.sector]
                wr = perf.get("win_rate")
                tracked = perf.get("total_tracked", 0)
                if wr is not None and tracked >= 5:
                    win_rate = wr
                    wr_bonus = (wr - 0.5) * 40  # +/- 20 points for win rate

            # Composite: 60% momentum + 20% win rate + 20% volume
            score = mom.score * 0.6 + wr_bonus + min(20, mom.signal_count * 0.5)
            score = max(0.0, min(100.0, score))

            rankings.append(SectorRanking(
                sector=mom.sector,
                rank=0,  # placeholder, set below
                score=round(score, 1),
                signal_count=mom.signal_count,
                win_rate=win_rate,
                momentum=mom,
                net_sentiment=net_sentiment,
            ))

        rankings.sort(key=lambda r: r.score, reverse=True)

        # Assign ranks (frozen dataclass — need replace)
        from dataclasses import replace
        ranked = []
        for i, r in enumerate(rankings, start=1):
            ranked.append(replace(r, rank=i))

        return ranked
