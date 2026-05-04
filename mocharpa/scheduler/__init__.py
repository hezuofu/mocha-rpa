"""Scheduler for recurring pipeline execution.

Provides cron-based scheduling so RPA pipelines can run on a regular cadence
without external orchestration.

    from mocharpa.scheduler import Schedule, Scheduler

    sched = Scheduler()
    sched.add(Schedule(
        name="daily_report",
        cron="0 9 * * 1-5",
        pipeline="report.yaml",
        driver="playwright",
        data={"env": "prod"},
    ))
    sched.start()
"""

from mocharpa.scheduler.schedule import Schedule, Scheduler
from mocharpa.scheduler.backend import SchedulerBackend, InMemorySchedulerBackend

__all__ = [
    "Schedule",
    "Scheduler",
    "SchedulerBackend",
    "InMemorySchedulerBackend",
]
