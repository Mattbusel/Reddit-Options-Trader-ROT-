"""Unified Control Plane for ROT.

Ports the PID self-tuning architecture from tokio-prompt-orchestrator into ROT's
Python async environment.  Five-layer stack:

    TelemetryBus → AnomalyDetector → TuningController → LiveTuning → HelixConfig

Each pipeline stage reports metrics to TelemetryBus.  TuningController reads
rolling snapshots, computes PID error signals, and issues parameter adjustments
via LiveTuning.  HelixConfig snapshots every adjustment and rolls back
automatically when signal accuracy degrades.
"""

from rot.control.telemetry_bus import TelemetryBus, StageMetrics, TelemetrySnapshot
from rot.control.anomaly_detector import AnomalyDetector, AnomalyReport, AnomalySeverity
from rot.control.live_tuning import LiveTuning, ParameterId, ParameterSpec
from rot.control.tuning_controller import TuningController
from rot.control.helix_config import HelixConfig, ConfigSnapshot

__all__ = [
    "TelemetryBus",
    "StageMetrics",
    "TelemetrySnapshot",
    "AnomalyDetector",
    "AnomalyReport",
    "AnomalySeverity",
    "LiveTuning",
    "ParameterId",
    "ParameterSpec",
    "TuningController",
    "HelixConfig",
    "ConfigSnapshot",
]
