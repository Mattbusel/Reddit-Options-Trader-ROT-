"""Institutional options flow intelligence package for ROT.

Detects unusual institutional activity (block trades, sweeps), computes
Black-Scholes Greeks, tracks per-ticker flow history, recognises multi-event
patterns, and cross-references flow with Reddit sentiment for convergence scoring.
"""

from rot.flow.convergence import ConvergenceDetector
from rot.flow.detector import FlowDetector
from rot.flow.greeks import GreeksEngine
from rot.flow.history import FlowHistory
from rot.flow.intelligence import (
    FlowAnalysis,
    FlowSignalIntegrator,
    FlowType,
    OptionsFlowEvent,
    Sentiment,
)
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
    "FlowAnalysis",
    "FlowDetector",
    "FlowEvent",
    "FlowHistory",
    "FlowPattern",
    "FlowPatternRecognizer",
    "FlowScore",
    "FlowSignalConvergence",
    "FlowSignalIntegrator",
    "FlowSummary",
    "FlowType",
    "GreeksEngine",
    "GreeksSnapshot",
    "OptionsFlowEvent",
    "Sentiment",
]
