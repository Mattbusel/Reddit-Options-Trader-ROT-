"""Institutional options flow intelligence package for ROT.

Detects unusual institutional activity (block trades, sweeps), computes
Black-Scholes Greeks, tracks per-ticker flow history, recognises multi-event
patterns, and cross-references flow with Reddit sentiment for convergence scoring.
"""

from rot.flow.convergence import ConvergenceDetector
from rot.flow.detector import FlowDetector
from rot.flow.greeks import GreeksEngine
from rot.flow.history import FlowHistory
from rot.flow.patterns import FlowPatternRecognizer
from rot.flow.types import (
    FlowEvent,
    FlowPattern,
    FlowScore,
    FlowSignalConvergence,
    FlowSummary,
    GreeksSnapshot,
)

__all__ = [
    "ConvergenceDetector",
    "FlowDetector",
    "FlowEvent",
    "FlowHistory",
    "FlowPattern",
    "FlowPatternRecognizer",
    "FlowScore",
    "FlowSignalConvergence",
    "FlowSummary",
    "GreeksEngine",
    "GreeksSnapshot",
]
