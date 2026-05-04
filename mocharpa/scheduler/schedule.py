"""Schedule definition and high-level Scheduler facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from mocharpa.pipeline.pipeline import PipelineResult


@dataclass
class Schedule:
    """A recurring pipeline execution schedule.

    Attributes:
        name: Unique schedule identifier.
        cron: 5-field cron expression (minute hour dom month dow).
        pipeline: Path to a ``.yaml`` / ``.json`` pipeline file.
        driver: ``"mock"`` or ``"playwright"``.
        data: Initial data passed to the pipeline on each run.
        enabled: If False, the schedule is skipped by the tick loop.
        last_run: Timestamp of the last execution (set automatically).
        last_result: Outcome of the most recent run.
    """

    name: str
    cron: str
    pipeline: str
    driver: str = "mock"
    data: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run: Optional[datetime] = None
    last_result: Optional[PipelineResult] = None


class Scheduler:
    """High-level scheduler facade.

    Usage::

        sched = Scheduler()
        sched.add(Schedule(
            name="morning_sync",
            cron="30 8 * * 1-5",
            pipeline="sync_data.yaml",
            driver="playwright",
            data={"env": "prod"},
        ))
        sched.start()
        # ... later ...
        sched.stop()
    """

    def __init__(self, backend=None) -> None:
        from mocharpa.scheduler.backend import InMemorySchedulerBackend

        self._backend = backend or InMemorySchedulerBackend()

    @property
    def backend(self):
        return self._backend

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, schedule: Schedule) -> None:
        """Register a schedule."""
        self._backend.add(schedule)

    def remove(self, name: str) -> Optional[Schedule]:
        """Remove a schedule by name."""
        return self._backend.remove(name)

    def get(self, name: str) -> Optional[Schedule]:
        """Return a schedule by name."""
        return self._backend.get(name)

    def list_all(self) -> List[Schedule]:
        """Return all registered schedules."""
        return self._backend.list_all()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduling loop (non-blocking)."""
        self._backend.start()

    def stop(self) -> None:
        """Stop the scheduling loop."""
        self._backend.stop()

    # ------------------------------------------------------------------
    # Manual run
    # ------------------------------------------------------------------

    def run_once(self, name: str) -> bool:
        """Execute a named schedule immediately.  Returns True on success."""
        return self._backend.run_once(name)
