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
        "db_insert": a.db_insert,
        "db_query": a.db_query,
        "db_execute": a.db_execute,
        "excel_read": a.excel_read,
        "excel_write": a.excel_write,
        "map_each": a.map_each,
        "filter_items": a.filter_items,
        "transform": a.transform,
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

    if action_type in ("if", "switch", "for_each"):
        return _build_flow_control(action_type, data)

    # Standard action from registry
    if action_type not in registry:
        raise ValueError(
            f"Unknown action type '{action_type}'. "
            f"Available: {sorted(registry.keys())}"
        )

    # transform/map_each/filter_items require a callable 'fn' —
    # YAML can't serialize callables; provide identity default.
    if action_type in ("map_each", "filter_items", "transform"):
        if "fn" not in data:
            return lambda ctx: ctx.previous

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

    if action_type in ("http_post",):
        if "url" in data:
            args["url"] = data["url"]
        if "body" in data:
            args["data"] = data["body"]
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

    if action_type in ("db_execute",):
        if "sql" in data:
            args["sql"] = data["sql"]

    # Excel actions
    if action_type in ("excel_read", "excel_write"):
        if "path" in data:
            args["path"] = data["path"]
        if "cell" in data:
            args["cell"] = data["cell"]
    if action_type in ("excel_write",):
        if "value" in data:
            args["value"] = data["value"]

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

    raise ValueError(f"Unknown flow-control type: {flow_type}")


def _parse_condition(raw: Any) -> Any:
    """Best-effort condition parser.  Returns a callable or a bare value.

    Currently supports:
        - ``bool`` → as-is
        - ``str`` like ``"${data.has_data}"`` → resolved at runtime
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        # Deferred resolution via PipelineContext.resolve
        def _cond(ctx: Any) -> bool:
            resolved = ctx.resolve(raw) if hasattr(ctx, "resolve") else raw
            return bool(resolved)
        return _cond
    return raw


def _resolve_value(ctx: Any, key: str) -> Any:
    """Resolve a key expression to a concrete value."""
    if key == "previous":
        return ctx.previous
    if key.startswith("data."):
        return ctx.data.get(key[5:])
    if key in ctx.step_results:
        return ctx.step_results[key]
    return ctx.data.get(key, ctx.previous)


# ======================================================================
# Pipeline.from_yaml integration
# ======================================================================

def _patch_pipeline_class() -> None:
    """Add ``from_yaml`` / ``from_yaml_file`` class methods to Pipeline."""
    Pipeline.from_yaml = staticmethod(load_yaml)    # type: ignore[attr-defined]
    Pipeline.from_yaml_file = staticmethod(load_yaml_file)  # type: ignore[attr-defined]
    Pipeline.from_json = staticmethod(load_json)    # type: ignore[attr-defined]
    Pipeline.from_json_file = staticmethod(load_json_file)  # type: ignore[attr-defined]
