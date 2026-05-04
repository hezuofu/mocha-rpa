"""AI Agent — natural-language-driven RPA orchestrator.

The :class:`AIAgent` accepts a high-level goal in plain language and
autonomously plans and executes RPA actions to achieve it.  It uses the
configured LLM provider to decide each step, observes the result, and
adapts the plan as needed.

Architecture::

    User goal ->LLM (planning) ->tool call ->execute ->observe ->repeat
                                                                  ↑___↲

Usage::

    from mocharpa.plugins.ai.agent import AIAgent
    from mocharpa.plugins.ai.plugin import AIPlugin, AnthropicProvider

    ai = AIPlugin(provider=AnthropicProvider(model="claude-sonnet-4-6"))
    ai.initialize(ctx)

    agent = AIAgent(ctx, ai_plugin=ai)
    result = agent.run(
        "Go to https://example.com, find the login form, "
        "enter username 'admin' and password 'secret', click login, "
        "then extract all product names from the table"
    )
    print(result.summary)
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from mocharpa.builder.find_builder import FindBuilder
from mocharpa.core.locator import LocatorFactory, Locator
from mocharpa.pipeline.context import PipelineContext

logger = logging.getLogger("rpa.ai.agent")


# ======================================================================
# Tool definitions — maps action names to LLM-friendly schemas
# ======================================================================

_TOOLS: List[Dict[str, Any]] = [
    # -- Browser --
    {
        "name": "navigate",
        "description": "Navigate the browser to a URL",
        "parameters": {"url": "str — full URL to navigate to"},
        "returns": "None",
    },
    {
        "name": "find_and_click",
        "description": "Find an element on the page and click it. Use locator strings like 'name:Login', 'id:btn1', 'type:Button', or CSS-like 'name:Submit > type:Button'.",
        "parameters": {"locator": "str — locator expression (name:X, id:X, type:X, class:X)"},
        "returns": "None",
    },
    {
        "name": "send_keys",
        "description": "Find an input field and type text into it",
        "parameters": {
            "locator": "str — locator expression for the input field",
            "text": "str — text to type",
        },
        "returns": "None",
    },
    {
        "name": "extract_text",
        "description": "Extract the visible text of a single element",
        "parameters": {"locator": "str — locator expression"},
        "returns": "str — the element's text content",
    },
    {
        "name": "extract_all_texts",
        "description": "Extract text from ALL matching elements (e.g. all rows in a table)",
        "parameters": {"locator": "str — locator expression"},
        "returns": "list[str] — text of each matching element",
    },
    {
        "name": "wait_for",
        "description": "Wait for an element to become visible on the page",
        "parameters": {
            "locator": "str — locator expression",
            "timeout": "float (optional) — max seconds to wait (default 10)",
        },
        "returns": "None",
    },
    {
        "name": "get_page_text",
        "description": "Get all visible text from the current page (useful for understanding page state)",
        "parameters": {},
        "returns": "str — all visible text on the page",
    },
    {
        "name": "get_current_url",
        "description": "Get the current browser URL",
        "parameters": {},
        "returns": "str — current URL",
    },
    # -- HTTP --
    {
        "name": "http_get",
        "description": "Send an HTTP GET request and return the JSON response",
        "parameters": {"url": "str — URL to fetch"},
        "returns": "dict/list — parsed JSON response",
    },
    {
        "name": "http_post",
        "description": "Send an HTTP POST request with data",
        "parameters": {
            "url": "str — URL",
            "data": "any (optional) — body to send (defaults to previous result)",
        },
        "returns": "dict — response JSON",
    },
    # -- File --
    {
        "name": "file_read",
        "description": "Read the contents of a text file",
        "parameters": {"path": "str — file path"},
        "returns": "str — file content",
    },
    {
        "name": "file_write",
        "description": "Write content to a file (overwrites)",
        "parameters": {
            "path": "str — file path",
            "content": "str — content to write (defaults to previous result)",
        },
        "returns": "str — the file path",
    },
    {
        "name": "file_glob",
        "description": "Find files matching a glob pattern",
        "parameters": {"pattern": "str — glob pattern (e.g. 'data/*.csv')"},
        "returns": "list[str] — matching file paths",
    },
    {
        "name": "file_exists",
        "description": "Check if a file or directory exists",
        "parameters": {"path": "str — path to check"},
        "returns": "bool",
    },
    # -- CSV --
    {
        "name": "csv_read",
        "description": "Read a CSV file and return its rows as list of dicts",
        "parameters": {"path": "str — path to CSV file"},
        "returns": "list[dict] — CSV rows",
    },
    {
        "name": "csv_write",
        "description": "Write rows to a CSV file",
        "parameters": {
            "path": "str — output path",
            "data": "list[dict] (optional) — rows to write (defaults to previous result)",
        },
        "returns": "None",
    },
    # -- Database --
    {
        "name": "db_query",
        "description": "Execute a SQL SELECT query",
        "parameters": {"sql": "str — SQL SELECT statement"},
        "returns": "list[dict] — query result rows",
    },
    {
        "name": "db_execute",
        "description": "Execute a SQL INSERT/UPDATE/DELETE statement",
        "parameters": {"sql": "str — SQL statement"},
        "returns": "int — rowcount",
    },
    # -- Queue --
    {
        "name": "queue_push",
        "description": "Push a message to a queue",
        "parameters": {
            "queue": "str — queue name",
            "payload": "any — message payload (defaults to previous result)",
        },
        "returns": "int — message ID",
    },
    # -- AI --
    {
        "name": "ai_think",
        "description": "Use this to reason about the current state, plan next steps, or decide between options. NOT for final answer — use that for 'done'.",
        "parameters": {"thought": "str — your reasoning"},
        "returns": "None — this is for internal reasoning only",
    },
]

# Build a compact description for the system prompt
def _build_tool_prompt() -> str:
    lines = []
    for t in _TOOLS:
        params = ", ".join(
            f"{k}: {v}" for k, v in t.get("parameters", {}).items()
        )
        lines.append(
            f"  {t['name']}({params}) ->{t['returns']}\n"
            f"    {t['description']}"
        )
    return "\n".join(lines)


_SYSTEM_PROMPT = """You are an RPA automation agent. Your job is to accomplish a user's goal
by calling tools step by step.  You CANNOT interact with the user — you must
decide every action yourself based on observations.

## Available tools

Each message from you must be a valid JSON object.  There are two types:

### Action message — execute a tool
{"thought": "explain your reasoning briefly",
 "action": "<tool_name>",
 "args": {<parameters>}}

### Done message — task complete (or cannot proceed)
{"thought": "explain why you're done",
 "done": true,
 "summary": "what was accomplished",
 "success": true|false}

## Rules

1. ONE tool call per message.
2. Always observe the result before calling the next tool.
3. If a tool fails or the result is unexpected, ADAPT — try a different approach.
4. When the goal is achieved, send a 'done' message with success: true.
5. If you're stuck after several attempts, send a 'done' message with success: false and explain why.
6. Use 'ai_think' to reason through complex situations before acting.
7. Use 'get_page_text' to understand page state before interacting with elements.
8. For locators: observe element names from get_page_text, then use 'name:X' format.
"""


# ======================================================================
# AgentResult
# ======================================================================

@dataclass
class AgentResult:
    """Outcome of an AIAgent run.

    Attributes:
        goal: The original goal.
        success: True if the agent declared success.
        summary: Human-readable summary from the agent.
        steps: Number of tool calls executed.
        elapsed: Wall-clock seconds.
        history: Full list of (tool_name, args, result) tuples.
    """

    goal: str = ""
    success: bool = False
    summary: str = ""
    steps: int = 0
    elapsed: float = 0.0
    history: List[Dict[str, Any]] = field(default_factory=list)


# ======================================================================
# AIAgent
# ======================================================================

class AIAgent:
    """AI-powered RPA agent that executes goals in natural language.

    Args:
        context: An :class:`AutomationContext` with a connected driver.
        ai_plugin: An initialised :class:`AIPlugin`.
        max_steps: Safety limit — maximum tool calls per run.
        verbose: If True, print each step to stdout.
    """

    def __init__(
        self,
        context: Any,
        ai_plugin: Any,
        *,
        max_steps: int = 30,
        verbose: bool = False,
    ) -> None:
        self._ctx = context
        self._ai = ai_plugin
        self._max_steps = max_steps
        self._verbose = verbose
        self._messages: List[Dict[str, Any]] = []
        self._previous: Any = None

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self, goal: str) -> AgentResult:
        """Execute a natural language *goal* autonomously.

        Args:
            goal: A description of what to accomplish, e.g.
                ``"Log into example.com with user 'admin', then download the report CSV"``.

        Returns:
            :class:`AgentResult` with summary and execution history.
        """
        start = time.monotonic()
        self._previous = None

        # Build initial conversation
        self._messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "system", "content": _build_tool_prompt()},
            {"role": "user", "content": f"Goal: {goal}\n\nBegin. Respond with your first action JSON."},
        ]

        history: List[Dict[str, Any]] = []
        steps = 0

        while steps < self._max_steps:
            # Get LLM response
            response = self._ai.generate(
                "", system=self._build_conversation_str(), temperature=0.3, max_tokens=2048,
            )

            parsed = self._parse_json_response(response)
            if parsed is None:
                self._messages.append({"role": "assistant", "content": response})
                self._messages.append({"role": "user", "content": "Invalid JSON. Reply with valid JSON only."})
                steps += 1
                continue

            if parsed.get("done"):
                elapsed = time.monotonic() - start
                summary = parsed.get("summary", "No summary provided.")
                success = parsed.get("success", False)
                if self._verbose:
                    print(f"\n[Agent] {'[OK]' if success else '[FAIL]'} {summary} ({steps} steps, {elapsed:.1f}s)")
                return AgentResult(
                    goal=goal, success=success, summary=summary,
                    steps=steps, elapsed=elapsed, history=history,
                )

            action = parsed.get("action", "")
            args = parsed.get("args", {})
            thought = parsed.get("thought", "")

            if self._verbose:
                print(f"\n[Agent] [think] {thought}")
                print(f"[Agent] [tool] {action}({args})")

            # Execute
            try:
                result = self._execute(action, args)
                history.append({"action": action, "args": args, "result": result, "thought": thought})
                result_str = self._format_result(result)
                if self._verbose:
                    preview = str(result)[:100] + ("..." if len(str(result)) > 100 else "")
                    print(f"[Agent] ->{preview}")
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                history.append({"action": action, "args": args, "error": error_msg, "thought": thought})
                result_str = f"ERROR: {error_msg}\n{traceback.format_exc()}"
                if self._verbose:
                    print(f"[Agent] [FAIL] {error_msg}")

            # Feed result back to LLM
            self._messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
            self._messages.append({"role": "user", "content": f"Result: {result_str}"})
            steps += 1

        # Max steps reached
        elapsed = time.monotonic() - start
        return AgentResult(
            goal=goal, success=False,
            summary=f"Reached max steps ({self._max_steps}) without completing the goal.",
            steps=steps, elapsed=elapsed, history=history,
        )

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute(self, action: str, args: Dict[str, Any]) -> Any:
        """Dispatch a tool call to the appropriate handler."""
        method = getattr(self, f"_tool_{action}", None)
        if method is None:
            return f"Unknown action: {action}. Available: {[t['name'] for t in _TOOLS]}"
        return method(**args)

    # -- Browser tools --

    def _tool_navigate(self, url: str) -> str:
        driver = self._ctx.driver
        if hasattr(driver, "navigate"):
            driver.navigate(url)
            return f"Navigated to {url}"
        return "Driver does not support navigation"

    def _tool_find_and_click(self, locator: str) -> str:
        loc = LocatorFactory.create(locator)
        fb = FindBuilder((loc,))
        if hasattr(self._ctx, "driver") and self._ctx.driver:
            fb = fb.with_context(self._ctx)
        fb.do(lambda e: e.click())
        return f"Clicked element matching '{locator}'"

    def _tool_send_keys(self, locator: str, text: str) -> str:
        loc = LocatorFactory.create(locator)
        fb = FindBuilder((loc,))
        if hasattr(self._ctx, "driver") and self._ctx.driver:
            fb = fb.with_context(self._ctx)
        fb.do(lambda e: e.send_keys(str(text)))
        return f"Typed '{text}' into element matching '{locator}'"

    def _tool_extract_text(self, locator: str) -> str:
        loc = LocatorFactory.create(locator)
        fb = FindBuilder((loc,))
        if hasattr(self._ctx, "driver") and self._ctx.driver:
            fb = fb.with_context(self._ctx)
        result = fb.do(lambda e: e.get_text())
        self._previous = result
        return str(result) if result else "(empty)"

    def _tool_extract_all_texts(self, locator: str) -> str:
        loc = LocatorFactory.create(locator)
        fb = FindBuilder((loc,))
        if hasattr(self._ctx, "driver") and self._ctx.driver:
            fb = fb.with_context(self._ctx)
        elements = fb.all().get_all()
        texts = [e.get_text() for e in elements]
        self._previous = texts
        return json.dumps(texts, ensure_ascii=False)

    def _tool_wait_for(self, locator: str, timeout: float = 10.0) -> str:
        loc = LocatorFactory.create(locator)
        fb = FindBuilder((loc,))
        if hasattr(self._ctx, "driver") and self._ctx.driver:
            fb = fb.with_context(self._ctx)
        fb.wait_until("is_visible", timeout=timeout)
        return f"Element '{locator}' is now visible"

    def _tool_get_page_text(self) -> str:
        driver = self._ctx.driver
        if hasattr(driver, "get_root_element"):
            root = driver.get_root_element()
            return root.get_text()
        if hasattr(driver, "execute_js"):
            return driver.execute_js("document.body.innerText") or ""
        return "(cannot get page text from this driver)"

    def _tool_get_current_url(self) -> str:
        driver = self._ctx.driver
        if hasattr(driver, "current_url"):
            return driver.current_url
        return "(not available)"

    # -- HTTP tools --

    def _tool_http_get(self, url: str) -> str:
        plugin = self._ctx.plugin("http") if hasattr(self._ctx, "plugin") else None
        if plugin is None:
            import requests
            resp = requests.get(url, timeout=30)
            result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        else:
            result = plugin.get_json(url)
        self._previous = result
        return json.dumps(result, ensure_ascii=False, default=str)

    def _tool_http_post(self, url: str, data: Any = None) -> str:
        payload = data if data is not None else self._previous
        plugin = self._ctx.plugin("http") if hasattr(self._ctx, "plugin") else None
        if plugin is None:
            import requests
            resp = requests.post(url, json=payload, timeout=30)
            result = resp.json()
        else:
            result = plugin.post_json(url, data=payload)
        self._previous = result
        return json.dumps(result, ensure_ascii=False, default=str)

    # -- File tools --

    def _tool_file_read(self, path: str) -> str:
        plugin = self._ctx.plugin("file") if hasattr(self._ctx, "plugin") else None
        if plugin:
            result = plugin.read_text(path)
        else:
            with open(path) as f:
                result = f.read()
        self._previous = result
        return result[:5000] + ("..." if len(result) > 5000 else "")

    def _tool_file_write(self, path: str, content: Any = None) -> str:
        text = str(content if content is not None else self._previous)
        plugin = self._ctx.plugin("file") if hasattr(self._ctx, "plugin") else None
        if plugin:
            plugin.write_text(path, text)
        else:
            import os
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
        return f"Wrote {len(text)} chars to {path}"

    def _tool_file_glob(self, pattern: str) -> str:
        import glob
        result = glob.glob(pattern, recursive=True)
        return json.dumps(result)

    def _tool_file_exists(self, path: str) -> str:
        import os
        return str(os.path.exists(path))

    # -- CSV tools --

    def _tool_csv_read(self, path: str) -> str:
        plugin = self._ctx.plugin("csv") if hasattr(self._ctx, "plugin") else None
        if plugin:
            rows = plugin.read(path)
        else:
            import csv
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
        self._previous = rows
        return json.dumps(rows, ensure_ascii=False, default=str)

    def _tool_csv_write(self, path: str, data: Any = None) -> str:
        rows = data if data is not None else self._previous
        plugin = self._ctx.plugin("csv") if hasattr(self._ctx, "plugin") else None
        if plugin:
            plugin.write(path, rows)
        else:
            import csv, os
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", newline="") as f:
                if rows and isinstance(rows[0], dict):
                    w = csv.DictWriter(f, fieldnames=rows[0].keys())
                    w.writeheader()
                    w.writerows(rows)
        return f"Wrote {len(rows)} rows to {path}"

    # -- Database tools --

    def _tool_db_query(self, sql: str) -> str:
        plugin = self._ctx.plugin("database")
        rows = plugin.fetch_all(sql)
        self._previous = rows
        return json.dumps(rows, ensure_ascii=False, default=str)

    def _tool_db_execute(self, sql: str) -> str:
        plugin = self._ctx.plugin("database")
        result = plugin.execute(sql)
        return f"Rowcount: {result.rowcount}"

    # -- Queue tools --

    def _tool_queue_push(self, queue: str, payload: Any = None) -> str:
        data = payload if payload is not None else self._previous
        plugin = self._ctx.plugin("queue")
        mid = plugin.push(queue, data)
        return f"Message {mid} pushed to queue '{queue}'"

    # -- AI internal tools --

    def _tool_ai_think(self, thought: str) -> str:
        return f"Thought recorded: {thought[:200]}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Try to parse JSON from the LLM response."""
        import re
        text = text.strip()
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try code block
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass
        # Try brace match
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return None

    def _build_conversation_str(self) -> str:
        """Build a compact conversation string for the LLM."""
        # The system prompt and tool list are the first two messages
        # The rest is the conversation
        lines = []
        for msg in self._messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                lines.append(content)
            elif role == "user":
                lines.append(f"USER: {content}")
            elif role == "assistant":
                lines.append(f"ASSISTANT: {content}")
        return "\n\n".join(lines)

    def _format_result(self, result: Any) -> str:
        if result is None:
            return "(no result)"
        if isinstance(result, str):
            return result
        if isinstance(result, (list, dict)):
            return json.dumps(result, ensure_ascii=False, default=str)
        return str(result)
