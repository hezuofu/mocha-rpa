"""Tests for AIAgent orchestration with scripted/mock LLM providers."""

import json
from mocharpa import *
from mocharpa.drivers.mock_driver import MockDriver, MockNativeElement
from mocharpa.plugins.ai.plugin import AIPlugin, AIProvider
from mocharpa.plugins.ai.agent import AIAgent
from mocharpa.pipeline.context import PipelineContext


def _make_ctx():
    driver = MockDriver()
    driver.connect()
    root = driver.root_native
    page = root.add_child(MockNativeElement(
        name="TestPage", automation_id="page", control_type="Pane",
    ))
    page.add_child(MockNativeElement(
        name="Username", automation_id="user", control_type="Edit",
    ))
    page.add_child(MockNativeElement(
        name="Login", automation_id="login_btn", control_type="Button",
    ))
    return driver, PipelineContext(driver=driver, timeout=10)


class _ScriptedProvider(AIProvider):
    def __init__(self, script):
        super().__init__(model="scripted")
        self._calls = 0
        self._script = script

    def complete(self, prompt, *, system="", temperature=0.7, max_tokens=4096, json_mode=False):
        if self._calls < len(self._script):
            action = self._script[self._calls]
            self._calls += 1
            return json.dumps(action)
        return json.dumps({"done": True, "success": False, "summary": "script exhausted"})

    def is_available(self):
        return True


class TestAIAgentBasic:
    def test_success_flow(self):
        driver, ctx = _make_ctx()
        script = [
            {"thought": "Type user", "action": "send_keys",
             "args": {"locator": "name:Username", "text": "admin"}},
            {"thought": "Click login", "action": "find_and_click",
             "args": {"locator": "name:Login"}},
            {"thought": "Done", "done": True, "success": True,
             "summary": "Task completed successfully"},
        ]
        ai = AIPlugin(provider=_ScriptedProvider(script))
        ai.initialize(ctx)
        agent = AIAgent(ctx, ai, max_steps=10)
        result = agent.run("Log in")
        driver.disconnect()
        assert result.success
        assert result.steps == 2  # 2 tool calls; done message doesn't count
        assert len(result.history) == 2

    def test_failure_handling(self):
        driver, ctx = _make_ctx()
        script = [
            {"thought": "Try click", "action": "find_and_click",
             "args": {"locator": "name:NotFound"}},
            {"thought": "Giving up", "done": True, "success": False,
             "summary": "Could not find the element"},
        ]
        ai = AIPlugin(provider=_ScriptedProvider(script))
        ai.initialize(ctx)
        agent = AIAgent(ctx, ai, max_steps=10)
        result = agent.run("Click missing button")
        driver.disconnect()
        assert not result.success
        assert "Could not find" in result.summary
        assert len(result.history) == 1

    def test_max_steps_limit(self):
        driver, ctx = _make_ctx()
        script = [
            {"thought": "try again", "action": "ai_think",
             "args": {"thought": "keep trying"}},
        ] * 50
        ai = AIPlugin(provider=_ScriptedProvider(script))
        ai.initialize(ctx)
        agent = AIAgent(ctx, ai, max_steps=3)
        result = agent.run("Keep trying")
        driver.disconnect()
        assert not result.success
        assert "max steps" in result.summary.lower()

    def test_invalid_json_recovery(self):
        driver, ctx = _make_ctx()

        class MessyProvider(AIProvider):
            def __init__(self):
                super().__init__(model="messy")
                self._calls = 0

            def complete(self, prompt, *, system="", temperature=0.7, max_tokens=4096, json_mode=False):
                self._calls += 1
                if self._calls == 1:
                    return "not valid json at all"
                if self._calls == 2:
                    return '```json\n{"thought": "ok", "done": true, "success": true, "summary": "recovered from bad JSON"}\n```'
                return json.dumps({"done": True, "success": False, "summary": "nope"})

            def is_available(self):
                return True

        ai = AIPlugin(provider=MessyProvider())
        ai.initialize(ctx)
        agent = AIAgent(ctx, ai, max_steps=5)
        result = agent.run("Test recovery")
        driver.disconnect()
        assert result.success
        assert "recovered" in result.summary

    def test_agent_result_dataclass(self):
        from mocharpa.plugins.ai.agent import AgentResult
        r = AgentResult(
            goal="test", success=True, summary="Done",
            steps=3, elapsed=1.5,
        )
        assert r.success
        assert r.goal == "test"
