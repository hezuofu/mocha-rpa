"""Tests for pipeline audit module."""

from mocharpa.pipeline.audit import AuditCollector, PipelineRunRecord, StepRunRecord


class TestStepRunRecord:
    def test_defaults(self):
        sr = StepRunRecord(step_name="test")
        assert sr.status == "ok"
        assert sr.error is None
        assert sr.elapsed == 0.0

    def test_error_status(self):
        sr = StepRunRecord(step_name="fail", status="error", error="bad thing")
        assert sr.status == "error"
        assert sr.error == "bad thing"


class TestAuditCollector:
    def test_full_lifecycle(self):
        ac = AuditCollector("test_pipeline", {"env": "dev"})
        ac.start()
        ac.record_ok("login", "token123", 1.5)
        ac.record_skipped("optional_step")
        ac.record_error("bad_step", "connection refused", 2.0)
        ac.record_exception("crash", "segfault", 0.1)
        ac.finish(False)

        record = ac.record
        assert record.pipeline_name == "test_pipeline"
        assert record.input_data == {"env": "dev"}
        assert record.success is False
        assert len(record.step_records) == 4

        ok_step = record.step_records[0]
        assert ok_step.step_name == "login"
        assert ok_step.status == "ok"
        assert ok_step.output == "token123"
        assert ok_step.elapsed == 1.5

        skipped_step = record.step_records[1]
        assert skipped_step.status == "skipped"

        error_step = record.step_records[2]
        assert error_step.status == "error"
        assert error_step.error == "connection refused"

        exc_step = record.step_records[3]
        assert exc_step.status == "exception"

    def test_json_serialization(self):
        ac = AuditCollector("p1")
        ac.start()
        ac.record_ok("s1", {"nested": True}, 0.1)
        ac.finish(True)

        json_str = ac.record.to_json()
        assert "p1" in json_str
        assert "s1" in json_str
        assert "nested" in json_str

    def test_summary(self):
        ac = AuditCollector("sum_test")
        ac.start()
        ac.record_ok("a", "x", 0.1)
        ac.record_ok("b", "y", 0.2)
        ac.record_skipped("c")
        ac.record_error("d", "oops", 0.3)
        ac.finish(False)

        summary = ac.record.summary()
        assert "sum_test" in summary
        assert "FAILED" in summary
        assert "2 ok" in summary
        assert "1 skipped" in summary
        assert "1 failed" in summary

    def test_sanitize_output(self):
        # Complex objects should be sanitized
        ac = AuditCollector("san")
        ac.start()
        ac.record_ok("s1", [1, 2, 3], 0.1)
        assert isinstance(ac.record.step_records[0].output, list)
