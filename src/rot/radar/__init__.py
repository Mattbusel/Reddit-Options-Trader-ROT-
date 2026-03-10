"""Attention Radar — formalizes ROT's emergent pre-catalyst signal detection.

Fires when high-confidence signals arrive on tickers with UNKNOWN event
classification and anomalous mention volume, creating a dedicated output
track for signals the system detects before the market has language for them.
"""

from rot.radar.attention_radar import AttentionRadar, AttentionRadarEvent, RadarFireCondition

__all__ = ["AttentionRadar", "AttentionRadarEvent", "RadarFireCondition"]
