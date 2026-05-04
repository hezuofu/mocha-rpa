"""Pipeline run audit — structured records for observability and debugging.

Every :class:`Pipeline` run produces a :class:`PipelineRunRecord` that captures
timing, step-level outcomes, and error details.  Records can be serialised to
JSON for downstream consumption (logging, dashboards, alerting).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class StepRunRecord:
    """Audit entry for a single step execution.

    Attributes:
        step_name: Name from the pipeline definition.
        status: ``"ok"``, ``"skipped"``, ``"error"``, or ``"exception"``.
        output: Return value of the action (serialisable subset).
        error: Error message if the step failed.
        elapsed: Wall-clock seconds.
        retries: Number of retries consumed (0 = first attempt succeeded).
    """

    step_name: str
    status: str = "ok"  # ok | skipped | error | exception
    output: Any = None
    error: Optional[str] = None
    elapsed: float = 0.0
    retries: int = 0


@dataclass
class PipelineRunRecord:
    """Complete audit record for one pipeline execution.

    Attributes:
        pipeline_name: Name from the pipeline definition.
        started_at: ISO-8601 UTC timestamp when ``run()`` was called.
        finished_at: ISO-8601 UTC timestamp when ``run()`` returned.
        success: ``True`` if the pipeline completed without unhandled errors.
        elapsed: Total wall-clock seconds.
        step_records: Per-step :class:`StepRunRecord` list.
        input_data: Snapshot of ``data`` passed to ``run()`` (shallow copy).
    """

    pipeline_name: str = ""
    started_at: str = ""
    finished_at: str = ""
    success: bool = False
    elapsed: float = 0.0
    step_records: List[StepRunRecord] = field(default_factory=list)
    input_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to a plain dict (suitable for JSON)."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str, ensure_ascii=False)

    def summary(self) -> str:
        """One-line human-readable summary."""
        ok = sum(1 for s in self.step_records if s.status == "ok")
        skipped = sum(1 for s in self.step_records if s.status == "skipped")
        failed = sum(1 for s in self.step_records if s.status in ("error", "exception"))
        status = "OK" if self.success else "FAILED"
        return (
            f"{self.pipeline_name} {status} "
            f"({ok} ok, {skipped} skipped, {failed} failed) "
            f"in {self.elapsed:.2f}s"
        )


class AuditCollector:
    """Collects step records during pipeline execution.

    The collector is attached to the :class:`PipelineContext` and populated
    by :meth:`Pipeline.run`.  After execution the caller can retrieve the
    completed :class:`PipelineRunRecord`.
    """

    def __init__(self, pipeline_name: str = "", input_data: Optional[Dict[str, Any]] = None) -> None:
        self._record = PipelineRunRecord(
            pipeline_name=pipeline_name,
            input_data=dict(input_data or {}),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._record.started_at = datetime.now(timezone.utc).isoformat()
        self._start = time.monotonic()

    def finish(self, success: bool) -> None:
        self._record.finished_at = datetime.now(timezone.utc).isoformat()
        self._record.elapsed = time.monotonic() - self._start
        self._record.success = success

    # ------------------------------------------------------------------
    # Per-step recording
    # ------------------------------------------------------------------

    def record_ok(self, step_name: str, output: Any, elapsed: float, retries: int = 0) -> None:
        self._record.step_records.append(StepRunRecord(
            step_name=step_name,
            status="ok",
            output=self._sanitize_output(output),
            elapsed=elapsed,
            retries=retries,
        ))

    def record_skipped(self, step_name: str) -> None:
        self._record.step_records.append(StepRunRecord(
            step_name=step_name,
            status="skipped",
        ))

    def record_error(self, step_name: str, error: str, elapsed: float) -> None:
        self._record.step_records.append(StepRunRecord(
            step_name=step_name,
            status="error",
            error=error,
            elapsed=elapsed,
        ))

    def record_exception(self, step_name: str, error: str, elapsed: float) -> None:
        self._record.step_records.append(StepRunRecord(
            step_name=step_name,
            status="exception",
            error=error,
            elapsed=elapsed,
        ))

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    @property
    def record(self) -> PipelineRunRecord:
        return self._record

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_output(output: Any) -> Any:
        """Convert output to a JSON-serialisable value."""
        if output is None:
            return None
        if isinstance(output, (str, int, float, bool)):
            return output
        if isinstance(output, (list, tuple)):
            return [AuditCollector._sanitize_output(v) for v in output]
        if isinstance(output, dict):
            return {str(k): AuditCollector._sanitize_output(v) for k, v in output.items()}
        return str(output)
