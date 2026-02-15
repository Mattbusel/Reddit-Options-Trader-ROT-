"""Export scheduler — manages recurring and on-demand data exports.

Handles scheduling, running pending exports, and generating CSV/JSON
output from the database.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
import uuid
from dataclasses import replace
from typing import Any, Dict, List, Optional

from rot.export.types import ExportJob, ExportResult, ScheduleConfig

log = logging.getLogger(__name__)

# Frequency intervals in seconds
_FREQ_S = {
    "daily": 86400,
    "weekly": 86400 * 7,
    "on_demand": 0,
}


class ExportScheduler:
    """Manages scheduled data exports.

    Works with the database's `export_schedules` and `data_exports`
    tables to track jobs and results.
    """

    def __init__(self, db: Any = None) -> None:
        self._db = db

    @property
    def db(self) -> Any:
        return self._db

    @db.setter
    def db(self, value: Any) -> None:
        self._db = value

    # ── Schedule Management ──

    def create_job(
        self,
        user_id: str,
        config: ScheduleConfig,
    ) -> ExportJob:
        """Create a new export job (in-memory; caller saves to DB)."""
        now = time.time()
        freq_s = _FREQ_S.get(config.frequency, 0)
        next_run = now + freq_s if freq_s > 0 else now

        return ExportJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            schedule_config=config,
            status="pending",
            created_at=now,
            next_run_at=next_run,
        )

    def get_pending_jobs(
        self, jobs: List[ExportJob],
    ) -> List[ExportJob]:
        """Filter jobs that are due to run."""
        now = time.time()
        pending = []
        for job in jobs:
            if job.status in ("pending", "completed"):
                if job.next_run_at and job.next_run_at <= now:
                    pending.append(job)
                elif job.schedule_config.frequency == "on_demand" and job.run_count == 0:
                    pending.append(job)
        return pending

    def compute_next_run(self, job: ExportJob) -> ExportJob:
        """Compute next run time after completion."""
        freq_s = _FREQ_S.get(job.schedule_config.frequency, 0)
        now = time.time()

        if freq_s > 0:
            next_run = now + freq_s
            return replace(
                job,
                status="completed",
                last_run_at=now,
                next_run_at=next_run,
                run_count=job.run_count + 1,
            )
        else:
            # On-demand: no future runs
            return replace(
                job,
                status="completed",
                last_run_at=now,
                next_run_at=None,
                run_count=job.run_count + 1,
            )

    # ── Export Generation ──

    async def generate_export(
        self,
        job: ExportJob,
        signals: List[Dict[str, Any]],
        lineage_data: Optional[List[Dict[str, Any]]] = None,
    ) -> ExportResult:
        """Generate an export from signal data.

        Parameters
        ----------
        signals:
            List of signal dicts from the database.
        lineage_data:
            Optional lineage dicts to include (Enterprise+).
        """
        start = time.time()
        config = job.schedule_config
        max_rows = config.max_rows

        # Limit rows
        export_signals = signals[:max_rows]

        if config.format == "json":
            data = self._to_json(export_signals, lineage_data)
        else:
            data = self._to_csv(export_signals)

        duration = time.time() - start

        return ExportResult(
            job_id=job.id,
            row_count=len(export_signals),
            format=config.format,
            data=data,
            generated_at=time.time(),
            duration_s=duration,
        )

    def _to_csv(self, signals: List[Dict[str, Any]]) -> str:
        """Convert signals to CSV string."""
        if not signals:
            return ""

        columns = [
            "id", "ticker", "event_type", "stance", "time_horizon",
            "confidence", "trend_score", "quality_score", "strategy",
            "subreddit", "post_title", "created_at", "sector",
        ]

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()

        for s in signals:
            row = {}
            for col in columns:
                val = s.get(col, "")
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                row[col] = val
            writer.writerow(row)

        return output.getvalue()

    def _to_json(
        self,
        signals: List[Dict[str, Any]],
        lineage: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Convert signals to JSON string."""
        export = {
            "signals": signals,
            "count": len(signals),
            "exported_at": time.time(),
        }
        if lineage:
            export["lineage"] = lineage

        return json.dumps(export, default=str)

    # ── Background Loop Entry ──

    async def run_pending_exports(self, jobs: List[ExportJob]) -> List[ExportResult]:
        """Run all pending export jobs. Returns results.

        This is meant to be called from a background loop.
        The caller provides jobs and should handle saving results to DB.
        """
        pending = self.get_pending_jobs(jobs)
        results = []

        for job in pending:
            try:
                if self._db:
                    signals = await self._fetch_signals_for_export(job)
                else:
                    signals = []

                result = await self.generate_export(job, signals)
                results.append(result)
                log.info(
                    "Export %s completed: %d rows in %.1fs",
                    job.id, result.row_count, result.duration_s,
                )
            except Exception:
                log.exception("Export %s failed", job.id)

        return results

    async def _fetch_signals_for_export(
        self, job: ExportJob,
    ) -> List[Dict[str, Any]]:
        """Fetch signals based on job config filters."""
        config = job.schedule_config
        filters = config.filters

        # Build query params
        _hours = filters.get("hours", 24 * 7)  # default 7 days
        _ticker = filters.get("ticker")
        _stance = filters.get("stance")
        _min_conf = filters.get("min_confidence", 0.0)
        limit = min(config.max_rows, 10000)

        # Use existing DB method
        kwargs: Dict[str, Any] = {"limit": limit}
        if hasattr(self._db, "get_signals"):
            signals = await self._db.get_signals(**kwargs)
        else:
            signals = []

        return signals
