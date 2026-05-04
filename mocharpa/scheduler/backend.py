"""Scheduler backends — pluggable storage and execution drivers.

Built-in: :class:`InMemorySchedulerBackend` for development / single-process use.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional

from mocharpa.scheduler.schedule import Schedule

logger = logging.getLogger("rpa.scheduler")


class SchedulerBackend(ABC):
    """Abstract backend for the :class:`Scheduler`.

    Subclass to add persistent storage (database, Redis) or distributed
    coordination without changing the public API.
    """

    @abstractmethod
    def add(self, schedule: Schedule) -> None:
        """Register a schedule."""

    @abstractmethod
    def remove(self, name: str) -> Optional[Schedule]:
        """Remove and return a schedule by name."""

    @abstractmethod
    def get(self, name: str) -> Optional[Schedule]:
        """Return a schedule by name."""

    @abstractmethod
    def list_all(self) -> List[Schedule]:
        """Return all registered schedules."""

    @abstractmethod
    def start(self) -> None:
        """Begin the scheduling loop."""

    @abstractmethod
    def stop(self) -> None:
        """Halt the scheduling loop."""

    @abstractmethod
    def run_once(self, name: str) -> bool:
        """Fire a single schedule immediately.  Returns True on success."""


# ======================================================================
# Cron matcher — simple 5-field cron without pulling extra dependencies
# ======================================================================

def _cron_field_matches(value: int, pattern: str, low: int, high: int) -> bool:
    """Check whether *value* satisfies a single cron field pattern."""
    if pattern == "*":
        return True
    for part in pattern.split(","):
        part = part.strip()
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base == "*":
                if value % step == 0:
                    return True
            else:
                base = int(base)
                if value >= base and (value - base) % step == 0:
                    return True
        elif "-" in part:
            lo, hi = part.split("-", 1)
            if int(lo) <= value <= int(hi):
                return True
        else:
            if int(part) == value:
                return True
    return False


def _cron_matches(cron: str, dt: datetime) -> bool:
    """Return True if *dt* matches a 5-field cron expression.

    Format: ``minute hour day-of-month month day-of-week`` (local time).
    """
    fields = cron.strip().split()
    if len(fields) != 5:
        raise ValueError(f"Invalid cron expression: {cron!r} (expected 5 fields)")

    minute, hour, dom, month, dow = fields
    return (
        _cron_field_matches(dt.minute, minute, 0, 59)
        and _cron_field_matches(dt.hour, hour, 0, 23)
        and _cron_field_matches(dt.day, dom, 1, 31)
        and _cron_field_matches(dt.month, month, 1, 12)
        and _cron_field_matches((dt.weekday() + 1) % 7, dow, 0, 7)
    )


# ======================================================================
# InMemorySchedulerBackend
# ======================================================================

class InMemorySchedulerBackend(SchedulerBackend):
    """Development backend that stores schedules in memory.

    Uses a background thread with a 30-second polling interval.  For production
    use-cases requiring persistence or distributed locking, swap in a
    database-backed implementation of :class:`SchedulerBackend`.
    """

    def __init__(self, poll_interval: float = 30.0) -> None:
        self._schedules: Dict[str, Schedule] = {}
        self._poll_interval = poll_interval
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, schedule: Schedule) -> None:
        if schedule.name in self._schedules:
            raise ValueError(f"Schedule '{schedule.name}' already exists")
        self._schedules[schedule.name] = schedule
        logger.info("Schedule '%s' added (cron=%s)", schedule.name, schedule.cron)

    def remove(self, name: str) -> Optional[Schedule]:
        sched = self._schedules.pop(name, None)
        if sched:
            logger.info("Schedule '%s' removed", name)
        return sched

    def get(self, name: str) -> Optional[Schedule]:
        return self._schedules.get(name)

    def list_all(self) -> List[Schedule]:
        return list(self._schedules.values())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="rpa-scheduler")
        self._thread.start()
        logger.info("Scheduler started (interval=%ss)", self._poll_interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        logger.info("Scheduler stopped")

    # ------------------------------------------------------------------
    # Manual execution
    # ------------------------------------------------------------------

    def run_once(self, name: str) -> bool:
        sched = self._schedules.get(name)
        if sched is None:
            logger.warning("Schedule '%s' not found", name)
            return False
        return self._fire(sched)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._tick()
            self._stop_event.wait(self._poll_interval)

    def _tick(self) -> None:
        now = datetime.now()
        for sched in list(self._schedules.values()):
            if not sched.enabled:
                continue
            if _cron_matches(sched.cron, now):
                # Avoid firing more than once per minute for the same schedule
                if sched.last_run is not None:
                    delta = (now - sched.last_run).total_seconds()
                    if delta < 60:
                        continue
                self._fire(sched)

    def _fire(self, sched: Schedule) -> bool:
        from mocharpa.pipeline.loader import load_yaml_file, load_json_file

        logger.info("Firing schedule '%s'", sched.name)
        sched.last_run = datetime.now()

        try:
            path = sched.pipeline if isinstance(sched.pipeline, str) else str(sched.pipeline)
            if path.endswith((".yaml", ".yml")):
                pl = load_yaml_file(path)
            else:
                pl = load_json_file(path)

            ctx = _create_context(sched.driver)
            result = pl.run(data=sched.data, context=ctx)
            sched.last_result = result

            if hasattr(ctx, "driver") and ctx.driver:
                ctx.driver.disconnect()

            logger.info("Schedule '%s' completed: %s", sched.name, "OK" if result.success else "FAILED")
            return result.success
        except Exception:
            logger.exception("Schedule '%s' failed", sched.name)
            return False


def _create_context(driver_type: str):
    """Create an AutomationContext for the scheduler (mirrors __main__.py)."""
    from mocharpa.core.context import AutomationContext

    if driver_type == "mock":
        from mocharpa.drivers.mock_driver import MockDriver
        driver = MockDriver()
        driver.connect()
        return AutomationContext(timeout=30, driver=driver)

    if driver_type == "playwright":
        from mocharpa.drivers.playwright_driver import PlaywrightDriver
        driver = PlaywrightDriver(headless=True)
        driver.connect()
        return AutomationContext(timeout=30, driver=driver)

    raise ValueError(f"Unknown driver: {driver_type}")
