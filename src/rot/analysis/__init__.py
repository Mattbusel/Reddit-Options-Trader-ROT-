"""Analysis engines — sector rotation, correlation, and shared analytics."""

from rot.analysis.sector import SectorAnalyzer
from rot.analysis.sector_types import (
    CapitalFlow,
    RotationEvent,
    SectorMomentum,
    SectorRanking,
)
from rot.analysis.correlations import CorrelationAnalyzer
from rot.analysis.correlation_types import (
    LeadLagPair,
    PredictivePair,
    SignalCorrelationMatrix,
    TickerCluster,
)

__all__ = [
    "SectorAnalyzer",
    "SectorMomentum",
    "RotationEvent",
    "SectorRanking",
    "CapitalFlow",
    "CorrelationAnalyzer",
    "SignalCorrelationMatrix",
    "TickerCluster",
    "LeadLagPair",
    "PredictivePair",
]
