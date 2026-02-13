"""Enterprise export data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ScheduleConfig:
    """Export schedule configuration."""

    frequency: str = "daily"      # "daily" | "weekly" | "on_demand"
    format: str = "csv"           # "csv" | "json"
    export_type: str = "signals"  # "signals" | "performance" | "unusual" | "all"
    filters: Dict[str, Any] = field(default_factory=dict)
    include_lineage: bool = False
    max_rows: int = 10000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frequency": self.frequency,
            "format": self.format,
            "export_type": self.export_type,
            "filters": self.filters,
            "include_lineage": self.include_lineage,
            "max_rows": self.max_rows,
        }


@dataclass(frozen=True)
class ExportJob:
    """A scheduled or on-demand export job."""

    id: str
    user_id: str
    schedule_config: ScheduleConfig
    status: str = "pending"       # "pending" | "running" | "completed" | "failed"
    created_at: float = 0.0
    last_run_at: Optional[float] = None
    next_run_at: Optional[float] = None
    run_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "schedule_config": self.schedule_config.to_dict(),
            "status": self.status,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
            "next_run_at": self.next_run_at,
            "run_count": self.run_count,
        }


@dataclass(frozen=True)
class ExportResult:
    """Result of running an export job."""

    job_id: str
    row_count: int
    format: str
    data: str                     # CSV or JSON string
    generated_at: float
    duration_s: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "row_count": self.row_count,
            "format": self.format,
            "generated_at": self.generated_at,
            "duration_s": round(self.duration_s, 2),
        }


@dataclass(frozen=True)
class LineageStep:
    """A single step in the signal provenance chain."""

    stage: str                    # e.g., "ingestion", "trend", "nlp", etc.
    timestamp: float
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "timestamp": self.timestamp,
            "details": self.details,
        }


@dataclass(frozen=True)
class SignalLineage:
    """Full provenance chain for a signal."""

    signal_id: str
    ticker: str
    steps: List[LineageStep] = field(default_factory=list)
    source: str = ""              # "reddit" | "rss" | "stocktwits" | "twitter"
    created_at: float = 0.0

    @property
    def total_processing_time_s(self) -> float:
        if len(self.steps) < 2:
            return 0.0
        return self.steps[-1].timestamp - self.steps[0].timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "ticker": self.ticker,
            "source": self.source,
            "created_at": self.created_at,
            "steps": [s.to_dict() for s in self.steps],
            "total_processing_time_s": round(self.total_processing_time_s, 2),
        }
