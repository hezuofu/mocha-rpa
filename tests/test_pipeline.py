"""Tests for the pipeline orchestration engine."""

import pytest

from mocharpa.pipeline.context import PipelineContext
from mocharpa.pipeline.step import Step, StepResult
from mocharpa.pipeline.pipeline import Pipeline, PipelineResult

from mocharpa.core.context import AutomationContext
from mocharpa.drivers.mock_driver import MockDriver, MockNativeElement


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def driver():
    d = MockDriver()
    d.connect()
    return d


@pytest.fixture
def ctx(driver):
    return PipelineContext(driver=driver, timeout=2)


# ======================================================================
# PipelineContext
# ======================================================================

class TestPipelineContext:
    def test_inherits_automation_context(self, ctx):
        assert isinstance(ctx, AutomationContext)
        assert ctx.driver is not None
        assert ctx.timeout == 2

    def test_data_and_previous(self, ctx):
        ctx.data["x"] = 42
        ctx.previous = "hello"
        assert ctx.data["x"] == 42
        assert ctx.previous == "hello"

    def test_record_step(self, ctx):
        ctx.record_step("login", "token123")
        assert ctx.step_results["login"] == "token123"
        assert ctx.previous == "token123"

    def test_resolve_data(self, ctx):
        ctx.data["user"] = "admin"
        assert ctx.resolve("${data.user}") == "admin"

    def test_resolve_previous(self, ctx):
        ctx.previous = [1, 2, 3]
        assert ctx.resolve("${previous}") == [1, 2, 3]

    def test_resolve_step_result(self, ctx):
        ctx.record_step("extract", "results")
        assert ctx.resolve("${extract}") == "results"

    def test_resolve_partial_string(self, ctx):
        ctx.data["name"] = "world"
        result = ctx.resolve("Hello ${data.name}!")
        assert result == "Hello world!"

    def test_resolve_nested(self, ctx):
        ctx.data["config"] = {"host": "localhost"}
        assert ctx.resolve("${data.config.host}") == "localhost"

    def test_resolve_non_string_passthrough(self, ctx):
        assert ctx.resolve(42) == 42
        assert ctx.resolve(None) is None


# ======================================================================
# Step
# ======================================================================

class TestStep:
    def test_execute_basic(self, ctx):
        step = Step("test", lambda c: "ok")
        result = step.execute(ctx)
        assert isinstance(result, StepResult)
        assert result.output == "ok"
        assert result.error is None
        assert result.skipped is False

    def test_skip_on_condition(self, ctx):
        step = Step("test", lambda c: "never", condition=False)
        result = step.execute(ctx)
        assert result.skipped is True
        assert result.output is None

    def test_condition_callable(self, ctx):
        counter = [0]
        def lazy():
            counter[0] += 1
            return counter[0] > 2

        step = Step("test", lambda c: "ok", condition=lazy)
        assert step.should_skip(ctx)  # counter=1, not > 2
        assert step.should_skip(ctx)  # counter=2, not > 2
        assert not step.should_skip(ctx)  # counter=3, > 2

    def test_retry(self, ctx):
        counter = [0]

        def fail_twice(c):
            counter[0] += 1
            if counter[0] < 3:
                raise ValueError("not ready")
            return counter[0]

        step = Step("test", fail_twice, max_retries=2, retry_delay=0.01)
        result = step.execute(ctx)
        assert result.output == 3
        assert counter[0] == 3

    def test_retry_exhausted(self, ctx):
        def always_fail(c):
            raise RuntimeError("permanent")

        step = Step("test", always_fail, max_retries=1)
        with pytest.raises(RuntimeError, match="permanent"):
            step.execute(ctx)

    def test_continue_on_error(self, ctx):
        def boom(c):
            raise ValueError("oops")

        step = Step("test", boom, continue_on_error=True)
        result = step.execute(ctx)
        assert result.error == "oops"
        assert result.output is None

    def test_name_required(self, ctx):
        step = Step("my_step", lambda c: 123)
        result = step.execute(ctx)
        assert result.step_name == "my_step"

    def test_to_dict(self):
        step = Step("login", lambda c: None, max_retries=1, continue_on_error=True)
        d = step.to_dict()
        assert d["name"] == "login"
        assert d["max_retries"] == 1
        assert d["continue_on_error"] is True


# ======================================================================
# Pipeline
# ======================================================================

class TestPipeline:
    def test_empty_pipeline(self):
        pl = Pipeline("empty")
        result = pl.run()
        assert result.success is True
        assert result.step_results == {}
        assert result.errors == {}

    def test_pipeline(self, ctx):
        pl = Pipeline("pipe")
        pl.step("step1", lambda c: 1)
        pl.step("step2", lambda c: c.previous + 1)
        pl.step("step3", lambda c: c.previous * 10)

        result = pl.run(context=ctx)
        assert result.success
        assert result.step_results == {"step1": 1, "step2": 2, "step3": 20}

    def test_data_passing(self, ctx):
        pl = Pipeline("data_test")
        pl.step("set", lambda c: c.data["greeting"])

        result = pl.run(data={"greeting": "hello"}, context=ctx)
        assert result.step_results["set"] == "hello"

    def test_conditional_step(self, ctx):
        pl = Pipeline("conditional")
        pl.step("always", lambda c: 1)
        pl.step("maybe", lambda c: 999, condition=False)

        result = pl.run(context=ctx)
        assert result.success
        assert "always" in result.step_results
        assert "maybe" not in result.step_results
        assert "maybe" in result.skipped

    def test_error_breaks_pipeline(self, ctx):
        def boom(c):
            raise RuntimeError("broken")

        pl = Pipeline("fail")
        pl.step("ok", lambda c: 1)
        pl.step("boom", boom)
        pl.step("never_reached", lambda c: 3)

        result = pl.run(context=ctx)
        assert result.success is False
        assert result.step_results == {"ok": 1}
        assert "boom" in result.errors
        assert "never_reached" not in result.step_results

    def test_continue_on_error(self, ctx):
        def boom(c):
            raise RuntimeError("ignored")

        pl = Pipeline("safe")
        pl.step("fail_safe", boom, continue_on_error=True)
        pl.step("still_runs", lambda c: "ok")

        result = pl.run(context=ctx)
        assert result.success is False  # because fail_safe had an error
        assert result.step_results == {"still_runs": "ok"}
        assert result.errors == {"fail_safe": "ignored"}

    def test_callable(self, ctx):
        pl = Pipeline("callable")
        pl.step("x", lambda c: 42)
        result = pl(context=ctx)
        assert result.step_results["x"] == 42

    def test_to_dict_from_dict(self):
        pl = Pipeline("ser")
        pl.step("a", lambda c: 1)
        d = pl.to_dict()
        assert d["name"] == "ser"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["name"] == "a"

        pl2 = Pipeline.from_dict(d)
        assert pl2.name == "ser"
        assert pl2.step_count == 0  # actions not restored

    def test_step_chain(self):
        pl = Pipeline("chain")
        (pl.step("a", lambda c: 1)
           .step("b", lambda c: c.previous + 2))

        assert pl.step_count == 2

    def test_properties(self):
        pl = Pipeline("props")
        pl.step("a", lambda c: None)
        assert pl.steps[0].name == "a"
        assert pl.step_count == 1


# ======================================================================
# YAML Loader
# ======================================================================

class TestYamlLoader:
    """Tests requiring pyyaml."""

    @pytest.fixture(autouse=True)
    def _check_yaml(self):
        pytest.importorskip("yaml")

    def test_load_basic(self):
        yaml_str = """\
workflow:
  name: yaml_test
  steps:
    - name: echo
      action: transform
"""
        pl = Pipeline.from_yaml(yaml_str)
        assert pl.name == "yaml_test"
        assert pl.step_count == 1

    def test_load_ui_action(self):
        yaml_str = """\
steps:
  - name: click_btn
    action: find_click
    locator:
      name: OK
"""
        pl = Pipeline.from_yaml(yaml_str)
        assert pl.step_count == 1

    def test_load_with_settings(self):
        yaml_str = """\
workflow:
  name: settings_test
  steps:
    - name: risky
      action: transform
      max_retries: 3
      retry_delay: 0.5
      continue_on_error: true
"""
        pl = Pipeline.from_yaml(yaml_str)
        assert pl.step_count == 1

    def test_load_from_file(self, tmp_path):
        yaml_path = tmp_path / "pl.yaml"
        yaml_path.write_text("""\
workflow:
  name: file_test
  steps:
    - name: s1
      action: transform
""", encoding="utf-8")
        pl = Pipeline.from_yaml_file(str(yaml_path))
        assert pl.name == "file_test"


# ======================================================================
# JSON Loader
# ======================================================================

class TestJsonLoader:
    def test_load_json(self):
        import json
        data = {
            "workflow": {
                "name": "json_test",
                "steps": [
                    {"name": "s1", "action": "transform"}
                ]
            }
        }
        pl = Pipeline.from_json(json.dumps(data))
        assert pl.name == "json_test"
        assert pl.step_count == 1

    def test_load_json_file(self, tmp_path):
        import json
        json_path = tmp_path / "pl.json"
        json_path.write_text(json.dumps({
            "workflow": {
                "name": "json_file_test",
                "steps": [{"name": "s1", "action": "transform"}]
            }
        }), encoding="utf-8")
        pl = Pipeline.from_json_file(str(json_path))
        assert pl.name == "json_file_test"
