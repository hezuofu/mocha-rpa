"""Tests for scheduler module."""

import pytest
from datetime import datetime
from mocharpa.scheduler import Schedule, Scheduler
from mocharpa.scheduler.backend import _cron_matches, _cron_field_matches


class TestCronMatching:
    def test_star_matches_all(self):
        assert _cron_field_matches(5, "*", 0, 59)

    def test_exact_match(self):
        assert _cron_field_matches(5, "5", 0, 59)
        assert not _cron_field_matches(6, "5", 0, 59)

    def test_range(self):
        assert _cron_field_matches(3, "1-5", 0, 59)
        assert not _cron_field_matches(6, "1-5", 0, 59)

    def test_list(self):
        assert _cron_field_matches(3, "1,3,5", 0, 59)
        assert not _cron_field_matches(2, "1,3,5", 0, 59)

    def test_step(self):
        assert _cron_field_matches(0, "*/15", 0, 59)
        assert _cron_field_matches(15, "*/15", 0, 59)
        assert _cron_field_matches(30, "*/15", 0, 59)
        assert not _cron_field_matches(5, "*/15", 0, 59)

    def test_full_cron_every_minute(self):
        dt = datetime(2026, 5, 4, 9, 0)
        assert _cron_matches("* * * * *", dt)

    def test_full_cron_specific(self):
        dt = datetime(2026, 5, 4, 9, 0, 0)  # Monday = 0 in Python
        # 9:00 on Monday (weekday 1 in cron, which is Monday)
        assert _cron_matches("0 9 * * 1", dt)

    def test_full_cron_no_match(self):
        dt = datetime(2026, 5, 4, 9, 30)  # 9:30
        assert not _cron_matches("0 9 * * *", dt)  # expects 9:00

    def test_invalid_cron(self):
        with pytest.raises(ValueError):
            _cron_matches("* * * *", datetime.now())


class TestSchedule:
    def test_defaults(self):
        s = Schedule(name="test", cron="0 9 * * *", pipeline="test.yaml")
        assert s.name == "test"
        assert s.enabled is True
        assert s.driver == "mock"
        assert s.data == {}


class TestScheduler:
    def test_add_remove(self):
        sched = Scheduler()
        s = Schedule(name="daily", cron="0 9 * * *", pipeline="test.yaml")
        sched.add(s)
        assert len(sched.list_all()) == 1
        assert sched.get("daily") is s
        sched.remove("daily")
        assert len(sched.list_all()) == 0

    def test_add_duplicate_raises(self):
        sched = Scheduler()
        s = Schedule(name="dup", cron="0 9 * * *", pipeline="test.yaml")
        sched.add(s)
        with pytest.raises(ValueError):
            sched.add(s)
        sched.remove("dup")

    def test_run_once_not_found(self):
        sched = Scheduler()
        assert sched.run_once("nonexistent") is False
