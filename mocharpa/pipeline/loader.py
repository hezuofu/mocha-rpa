"""YAML / JSON pipeline loader.

Parses declarative pipeline definitions into :class:`Pipeline` instances.
Supports template expressions (``${data.key}``, ``${previous}``, etc.) and
nested flow-control blocks (``if``, ``switch``, ``for_each``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from mocharpa.pipeline.pipeline import Pipeline
from mocharpa.core.exceptions import TimeoutError


# ======================================================================
# Action registry — maps YAML "action" names to factory functions
# ======================================================================

def _get_action_registry() -> Dict[str, Callable[..., Any]]:
    """Lazy-built mapping of action names → factory callables."""
    from mocharpa.pipeline import actions as a

    return {
        "find_click": a.find_click,
        "send_keys": a.send_keys,
        "extract_text": a.extract_text,
        "extract_all_texts": a.extract_all_texts,
        "extract_attribute": a.extract_attribute,
        "wait_for": a.wait_for,
        "http_get": a.http_get,
        "http_post": a.http_post,
        "http_put": a.http_put,
        "http_patch": a.http_patch,
        "http_delete": a.http_delete,
        "db_insert": a.db_insert,
        "db_query": a.db_query,
        "db_execute": a.db_execute,
        "excel_read": a.excel_read,
        "excel_write": a.excel_write,
        "word_open": a.word_open,
        "word_add_paragraph": a.word_add_paragraph,
        "word_add_heading": a.word_add_heading,
        "word_get_text": a.word_get_text,
        "word_find_replace": a.word_find_replace,
        "word_add_table": a.word_add_table,
        "word_add_picture": a.word_add_picture,
        "word_save": a.word_save,
        "word_close": a.word_close,
        "map_each": a.map_each,
        "filter_items": a.filter_items,
        "transform": a.transform,
        "csv_read": a.csv_read,
        "csv_write": a.csv_write,
        "csv_append": a.csv_append,
        "file_read_text": a.file_read_text,
        "file_write_text": a.file_write_text,
        "file_copy": a.file_copy,
        "file_move": a.file_move,
        "file_delete": a.file_delete,
        "file_glob": a.file_glob,
        "file_exists": a.file_exists,
        "file_mkdir": a.file_mkdir,
        "queue_push": a.queue_push,
        "queue_pop": a.queue_pop,
        "queue_ack": a.queue_ack,
        "queue_fail": a.queue_fail,
        "ai_generate": a.ai_generate,
        "ai_extract": a.ai_extract,
        "ai_classify": a.ai_classify,
        "ai_summarize": a.ai_summarize,
        "ai_decide": a.ai_decide,
    }


# ======================================================================
# Public API
# ======================================================================

def load_yaml(yaml_str: str) -> Pipeline:
    """Parse a YAML string into a :class:`Pipeline`.

    Requires ``pyyaml`` to be installed (``pip install pyyaml``).

    Args:
        yaml_str: YAML content.

    Returns:
        A ready-to-run :class:`Pipeline`.

    Raises:
        ImportError: If ``pyyaml`` is not available.
    """
    try:
        import yaml
    except ImportError:
        raise ImportError(
            "yaml support requires pyyaml.  Install with: pip install pyyaml"
        ) from None

    data = yaml.safe_load(yaml_str)
    return _build_from_dict(data)


def load_yaml_file(path: Union[str, Path]) -> Pipeline:
    """Load a pipeline from a ``.yaml`` / ``.yml`` file.

    Args:
        path: Path to the YAML file.

    Returns:
        A :class:`Pipeline`.
    """
    content = Path(path).read_text(encoding="utf-8")
    return load_yaml(content)


def load_json(json_str: str) -> Pipeline:
    """Parse a JSON string into a :class:`Pipeline`.  No extra dependencies."""
    data = json.loads(json_str)
    return _build_from_dict(data)


def load_json_file(path: Union[str, Path]) -> Pipeline:
    """Load a pipeline from a ``.json`` file."""
    content = Path(path).read_text(encoding="utf-8")
    return load_json(content)


# ======================================================================
# Internal builders
# ======================================================================

def _build_from_dict(data: dict) -> Pipeline:
    """Recursively build a Pipeline from a parsed dict."""
    pl_spec = data.get("pipeline", data)  # tolerate 'workflow' for backwards compat
    if "workflow" in data:
        pl_spec = data["workflow"]
    name = pl_spec.get("name", "")
    pl = Pipeline(name=name)

    steps = pl_spec.get("steps", [])
    if not steps and isinstance(pl_spec, list):
        steps = pl_spec  # bare list of steps

    for step_data in steps:
        _add_step(pl, step_data)

    return pl


def _add_step(pl: Pipeline, step_data: dict) -> None:
    """Parse a single step dict and add it to the pipeline."""
    step_name = step_data["name"]
    action_type = step_data.get("action", "")

    # Optional step settings
    step_kwargs: Dict[str, Any] = {}
    if "max_retries" in step_data:
        step_kwargs["max_retries"] = step_data["max_retries"]
    if "retry_delay" in step_data:
        step_kwargs["retry_delay"] = step_data["retry_delay"]
    if "continue_on_error" in step_data:
        step_kwargs["continue_on_error"] = step_data["continue_on_error"]
    if "timeout" in step_data:
        step_kwargs["timeout"] = step_data["timeout"]
    if "condition" in step_data:
        step_kwargs["condition"] = _parse_condition(step_data["condition"])

    # Build action
    action = _build_action(action_type, step_data)
    pl.step(step_name, action, **step_kwargs)


def _build_action(action_type: str, data: dict) -> Callable[[Any], Any]:
    """Resolve an action type to a factory callable and invoke it."""
    registry = _get_action_registry()

    if action_type == "sequence":
        # Nested sub-steps → single callable that runs them inline
        sub_steps = data.get("steps", [])
        return _sequence_action(sub_steps)

    if action_type in ("if", "switch", "for_each", "while_", "until_", "repeat"):
        return _build_flow_control(action_type, data)

    # Standard action from registry
    if action_type not in registry:
        raise ValueError(
            f"Unknown action type '{action_type}'. "
            f"Available: {sorted(registry.keys())}"
        )

    # transform/map_each/filter_items require a callable 'fn' —
    # YAML can't serialize callables.  Recognised string aliases:
    #   "identity"  →  lambda x: x
    #   builtin name (str, int, len, ...) → builtin
    if action_type in ("map_each", "filter_items", "transform"):
        fn_raw = data.get("fn")
        if fn_raw is None:
            return lambda ctx: ctx.previous
        if isinstance(fn_raw, str):
            if fn_raw == "identity":
                data["fn"] = lambda x: x
            else:
                import builtins
                if hasattr(builtins, fn_raw):
                    data["fn"] = getattr(builtins, fn_raw)

    factory = registry[action_type]
    args = _extract_action_args(action_type, data)
    return factory(**args)


def _extract_action_args(action_type: str, data: dict) -> Dict[str, Any]:
    """Extract factory arguments from a step dict based on action type."""
    # Common args
    args: Dict[str, Any] = {}

    # locator-based actions
    if action_type in (
        "find_click", "send_keys", "extract_text",
        "extract_all_texts", "extract_attribute",
    ):
        if "locator" in data:
            args["locator"] = data["locator"]

    if action_type in ("send_keys",):
        if "text" in data:
            args["text"] = data["text"]

    if action_type in ("extract_attribute",):
        if "attr" in data:
            args["attr"] = data["attr"]

    if action_type in ("wait_for",):
        if "locator" in data:
            args["locator"] = data["locator"]
        if "timeout" in data:
            args["timeout"] = data["timeout"]

    # HTTP actions
    if action_type in ("http_get",):
        if "url" in data:
            args["url"] = data["url"]
        if "headers" in data:
            args["headers"] = data["headers"]

    if action_type in ("http_post", "http_put", "http_patch"):
        if "url" in data:
            args["url"] = data["url"]
        if "body" in data:
            args["data"] = data["body"]
        if "headers" in data:
            args["headers"] = data["headers"]

    if action_type in ("http_delete",):
        if "url" in data:
            args["url"] = data["url"]
        if "headers" in data:
            args["headers"] = data["headers"]

    # Database actions
    if action_type in ("db_insert",):
        if "table" in data:
            args["table"] = data["table"]
        if "data" in data:
            args["data"] = data["data"]

    if action_type in ("db_query",):
        if "sql" in data:
            args["sql"] = data["sql"]
        if "table" in data:
            args["table"] = data["table"]
        if "filters" in data:
            args.update(data["filters"])

    if action_type in ("db_execute",):
        if "sql" in data:
            args["sql"] = data["sql"]

    # Excel actions
    if action_type in ("excel_read", "excel_write"):
        if "path" in data:
            args["path"] = data["path"]
        if "cell" in data:
            args["cell"] = data["cell"]
        if "sheet" in data:
            args["sheet"] = data["sheet"]
    if action_type in ("excel_write",):
        if "value" in data:
            args["value"] = data["value"]

    # Word actions
    if action_type.startswith("word_"):
        if "path" in data:
            args["path"] = data["path"]

    if action_type in ("word_add_paragraph", "word_add_heading", "word_get_text"):
        if "text" in data:
            args["text"] = data["text"]

    if action_type in ("word_add_paragraph",):
        if "style" in data:
            args["style"] = data["style"]

    if action_type in ("word_add_heading",):
        if "level" in data:
            args["level"] = data["level"]

    if action_type in ("word_find_replace",):
        if "old" in data:
            args["old"] = data["old"]
        if "new" in data:
            args["new"] = data["new"]

    if action_type in ("word_add_table",):
        if "rows" in data:
            args["rows"] = data["rows"]
        if "cols" in data:
            args["cols"] = data["cols"]
        if "data" in data:
            args["data"] = data["data"]

    if action_type in ("word_add_picture",):
        if "image_path" in data:
            args["image_path"] = data["image_path"]
        if "width" in data:
            args["width"] = data["width"]

    if action_type in ("word_save",):
        if "target" in data:
            args["target"] = data["target"]

    if action_type in ("word_close",):
        if "save" in data:
            args["save"] = data["save"]

    # CSV actions
    if action_type in ("csv_read",):
        if "path" in data:
            args["path"] = data["path"]
        if "as_dicts" in data:
            args["as_dicts"] = data["as_dicts"]

    if action_type in ("csv_write", "csv_append"):
        if "path" in data:
            args["path"] = data["path"]
        if "data" in data:
            args["data"] = data["data"]
    if action_type in ("csv_write",):
        if "fieldnames" in data:
            args["fieldnames"] = data["fieldnames"]

    # File actions
    if action_type in ("file_read_text",):
        if "path" in data:
            args["path"] = data["path"]
        if "encoding" in data:
            args["encoding"] = data["encoding"]

    if action_type in ("file_write_text",):
        if "path" in data:
            args["path"] = data["path"]
        if "content" in data:
            args["content"] = data["content"]
        if "encoding" in data:
            args["encoding"] = data["encoding"]

    if action_type in ("file_copy", "file_move"):
        if "src" in data:
            args["src"] = data["src"]
        if "dst" in data:
            args["dst"] = data["dst"]

    if action_type in ("file_delete", "file_mkdir", "file_exists"):
        if "path" in data:
            args["path"] = data["path"]

    if action_type in ("file_glob",):
        if "pattern" in data:
            args["pattern"] = data["pattern"]
        if "recursive" in data:
            args["recursive"] = data["recursive"]

    # Queue actions
    if action_type in ("queue_push",):
        if "queue" in data:
            args["queue"] = data["queue"]
        if "payload" in data:
            args["payload"] = data["payload"]
        if "priority" in data:
            args["priority"] = data["priority"]
        if "delay" in data:
            args["delay"] = data["delay"]

    if action_type in ("queue_pop",):
        if "queue" in data:
            args["queue"] = data["queue"]

    if action_type in ("queue_ack", "queue_fail"):
        if "msg_id" in data:
            args["msg_id"] = data["msg_id"]
    if action_type in ("queue_fail",):
        if "error" in data:
            args["error"] = data["error"]

    # AI actions
    if action_type in ("ai_generate",):
        if "prompt" in data:
            args["prompt"] = data["prompt"]
        if "content" in data:
            args["content"] = data["content"]
        if "system" in data:
            args["system"] = data["system"]
        if "temperature" in data:
            args["temperature"] = data["temperature"]

    if action_type in ("ai_extract",):
        if "content" in data:
            args["content"] = data["content"]
        if "schema" in data:
            args["schema"] = data["schema"]
        if "temperature" in data:
            args["temperature"] = data["temperature"]

    if action_type in ("ai_classify",):
        if "content" in data:
            args["content"] = data["content"]
        if "categories" in data:
            args["categories"] = data["categories"]
        if "temperature" in data:
            args["temperature"] = data["temperature"]

    if action_type in ("ai_summarize",):
        if "content" in data:
            args["content"] = data["content"]
        if "system" in data:
            args["system"] = data["system"]
        if "temperature" in data:
            args["temperature"] = data["temperature"]

    if action_type in ("ai_decide",):
        if "question" in data:
            args["question"] = data["question"]
        if "content" in data:
            args["content"] = data["content"]
        if "temperature" in data:
            args["temperature"] = data["temperature"]

    # Generic transform actions
    if action_type in ("transform", "map_each", "filter_items"):
        if "fn" in data:
            args["fn"] = data["fn"]

    return args


# ======================================================================
# Sub-step / flow-control actions
# ======================================================================

def _sequence_action(sub_steps: List[dict]) -> Callable[[Any], Any]:
    """Build a callable that runs a list of sub-steps inline."""
    sub_actions = [_build_action(s["action"], s) for s in sub_steps]

    def _action(ctx: Any) -> Any:
        last = None
        for act in sub_actions:
            last = act(ctx)
            if hasattr(ctx, "record_step"):
                ctx.previous = last
        return last

    return _action


def _build_flow_control(flow_type: str, data: dict) -> Callable[[Any], Any]:
    """Build a callable for if/switch/for_each defined in YAML."""
    if flow_type == "if":
        condition = _parse_condition(data.get("condition", True))
        then_steps = data.get("then", [])
        else_steps = data.get("else", [])

        then_act = _sequence_action(then_steps) if then_steps else lambda ctx: None
        else_act = _sequence_action(else_steps) if else_steps else lambda ctx: None

        def _action(ctx: Any) -> Any:
            check = condition() if callable(condition) else bool(condition)
            if check:
                return then_act(ctx)
            return else_act(ctx)
        return _action

    if flow_type == "switch":
        value_key = data.get("value", "previous")
        cases = data.get("cases", [])
        default_steps = data.get("default", [])

        default_act = _sequence_action(default_steps) if default_steps else lambda ctx: None

        def _action(ctx: Any) -> Any:
            actual = _resolve_value(ctx, value_key)
            for case in cases:
                match_val = case.get("match")
                if actual == match_val:
                    return _sequence_action(case.get("steps", []))(ctx)
            return default_act(ctx)
        return _action

    if flow_type == "for_each":
        items_key = data.get("items", "previous")
        steps = data.get("steps", [])
        seq = _sequence_action(steps) if steps else lambda ctx: None

        def _action(ctx: Any) -> Any:
            items = _resolve_value(ctx, items_key) or []
            results = []
            for item in items:
                ctx.previous = item
                results.append(seq(ctx))
            return results
        return _action

    if flow_type == "while_":
        condition = _parse_condition(data.get("condition", False))
        steps = data.get("steps", [])
        max_iterations = data.get("max_iterations", None)
        timeout = data.get("timeout", None)
        seq = _sequence_action(steps) if steps else lambda ctx: None

        def _action(ctx: Any) -> Any:
            import time as _time
            check = condition() if callable(condition) else bool(condition)
            deadline = _time.monotonic() + timeout if timeout else None
            iteration = 0
            while check:
                if max_iterations is not None and iteration >= max_iterations:
                    break
                if deadline is not None and _time.monotonic() > deadline:
                    raise TimeoutError(f"while_ loop timed out after {timeout}s")
                seq(ctx)
                iteration += 1
                check = condition() if callable(condition) else bool(condition)
            return None
        return _action

    if flow_type == "until_":
        condition = _parse_condition(data.get("condition", True))
        steps = data.get("steps", [])
        max_iterations = data.get("max_iterations", None)
        interval = data.get("interval", 0.0)
        seq = _sequence_action(steps) if steps else lambda ctx: None

        def _action(ctx: Any) -> Any:
            import time as _time
            iteration = 0
            while True:
                seq(ctx)
                iteration += 1
                if max_iterations is not None and iteration >= max_iterations:
                    break
                check = condition() if callable(condition) else bool(condition)
                if check:
                    break
                if interval > 0:
                    _time.sleep(interval)
            return None
        return _action

    if flow_type == "repeat":
        count = int(data.get("count", 1))
        steps = data.get("steps", [])
        seq = _sequence_action(steps) if steps else lambda ctx: None

        def _action(ctx: Any) -> Any:
            results = []
            for i in range(count):
                ctx.previous = i
                results.append(seq(ctx))
            return results
        return _action

    raise ValueError(f"Unknown flow-control type: {flow_type}")


def _parse_condition(raw: Any) -> Any:
    """Parse a condition expression into a callable ``(ctx) -> bool``.

    Supports:
        - ``bool`` → as-is
        - ``str`` → ``"${data.key}"`` style resolved at runtime
        - ``dict`` → complex expressions:
          ``{"exists": {"name": "Popup"}}``
          ``{"eq": ["${data.status}", "ok"]}``
          ``{"and": [cond1, cond2]}``
          ``{"or": [...]}``
          ``{"not": cond}``
          ``{"gt": [left, right]}``
          ``{"lt": [left, right]}``
          ``{"contains": [value, item]}``
    """
    if isinstance(raw, bool):
        return raw

    if isinstance(raw, str):
        def _cond(ctx: Any) -> bool:
            resolved = ctx.resolve(raw) if hasattr(ctx, "resolve") else raw
            return bool(resolved)
        return _cond

    if isinstance(raw, dict):
        return _parse_dict_condition(raw)

    return raw


def _parse_dict_condition(data: dict) -> Callable[[Any], bool]:
    """Parse a dict-based condition expression."""
    if not data:
        return lambda ctx: False

    op = next(iter(data))

    if op == "and":
        subs = [_parse_condition(item) for item in data["and"]]
        def _and(ctx: Any) -> bool:
            for sub in subs:
                check = sub(ctx) if callable(sub) else bool(sub)
                if not check:
                    return False
            return True
        return _and

    if op == "or":
        subs = [_parse_condition(item) for item in data["or"]]
        def _or(ctx: Any) -> bool:
            for sub in subs:
                check = sub(ctx) if callable(sub) else bool(sub)
                if check:
                    return True
            return False
        return _or

    if op == "not":
        sub = _parse_condition(data["not"])
        def _not(ctx: Any) -> bool:
            check = sub(ctx) if callable(sub) else bool(sub)
            return not check
        return _not

    # Element conditions
    if op == "exists":
        from mocharpa.builder.find_builder import FindBuilder
        from mocharpa.core.locator import LocatorFactory
        loc = LocatorFactory.create(data["exists"])
        def _exists(ctx: Any) -> bool:
            fb = FindBuilder((loc,))
            if hasattr(ctx, "driver") and ctx.driver:
                fb = fb.with_context(ctx)
            return fb.exists()
        return _exists

    if op == "not_exists":
        sub = _parse_dict_condition({"exists": data["not_exists"]})
        def _not_exists(ctx: Any) -> bool:
            return not sub(ctx)
        return _not_exists

    if op == "visible":
        from mocharpa.builder.find_builder import FindBuilder
        from mocharpa.core.locator import LocatorFactory
        loc = LocatorFactory.create(data["visible"])
        def _visible(ctx: Any) -> bool:
            fb = FindBuilder((loc,))
            if hasattr(ctx, "driver") and ctx.driver:
                fb = fb.with_context(ctx)
            el = fb.get()
            return el is not None and el.is_visible()
        return _visible

    if op == "enabled":
        from mocharpa.builder.find_builder import FindBuilder
        from mocharpa.core.locator import LocatorFactory
        loc = LocatorFactory.create(data["enabled"])
        def _enabled(ctx: Any) -> bool:
            fb = FindBuilder((loc,))
            if hasattr(ctx, "driver") and ctx.driver:
                fb = fb.with_context(ctx)
            el = fb.get()
            return el is not None and el.is_enabled()
        return _enabled

    # Value comparisons — expect [left, right]
    if op in ("eq", "neq", "gt", "lt", "contains"):
        pair = data[op]
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f"'{op}' condition expects a list of [left, right], got: {pair}")
        left, right = pair

        def _resolve_side(ctx: Any, side: Any) -> Any:
            if isinstance(side, str) and hasattr(ctx, "resolve"):
                return ctx.resolve(side)
            return side

        if op == "eq":
            return lambda ctx: _resolve_side(ctx, left) == _resolve_side(ctx, right)
        if op == "neq":
            return lambda ctx: _resolve_side(ctx, left) != _resolve_side(ctx, right)
        if op == "gt":
            return lambda ctx: _resolve_side(ctx, left) > _resolve_side(ctx, right)
        if op == "lt":
            return lambda ctx: _resolve_side(ctx, left) < _resolve_side(ctx, right)
        if op == "contains":
            return lambda ctx: _resolve_side(ctx, right) in _resolve_side(ctx, left)

    # Fallback: treat as raw value
    return lambda ctx: bool(data)


def _resolve_value(ctx: Any, key: str) -> Any:
    """Resolve a key expression to a concrete value."""
    if key == "previous":
        return ctx.previous
    if key.startswith("data."):
        return ctx.data.get(key[5:])
    if key in ctx.step_results:
        return ctx.step_results[key]
    return ctx.data.get(key, ctx.previous)



