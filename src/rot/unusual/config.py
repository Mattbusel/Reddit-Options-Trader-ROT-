"""Unusual activity detection configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnusualDetectorConfig:
    """Thresholds and weights for unusual activity detection."""

    # IV spike detection
    iv_rank_threshold: float = 80.0       # flag if IV rank > 80th percentile
    iv_weight: float = 25.0               # max contribution to composite score

    # Volume surge detection
    volume_surge_multiplier: float = 2.0  # flag if volume > 2x avg
    volume_weight: float = 25.0

    # OI surge detection
    oi_surge_pct: float = 20.0            # flag if OI increases > 20%
    oi_weight: float = 20.0

    # Put/call skew shift
    skew_std_threshold: float = 2.0       # flag if P/C ratio > 2 std devs
    skew_weight: float = 15.0

    # Sweep approximation
    sweep_vol_oi_threshold: float = 3.0   # flag if vol/oi > 3x (aggressive)
    sweep_weight: float = 15.0

    # Composite thresholds
    composite_min_score: float = 25.0     # minimum score to report event
    history_window_days: int = 20         # rolling window for baselines
    max_events_per_signal: int = 5        # cap events per signal scan

    def total_weight(self) -> float:
        """Sum of all detector component weights (used to normalise composite scores)."""
        return (
            self.iv_weight + self.volume_weight + self.oi_weight
            + self.skew_weight + self.sweep_weight
        )
