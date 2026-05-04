"""Pipeline definition validator — schema checks for YAML / JSON pipelines.

Usage::

    from mocharpa.pipeline.validator import validate_pipeline

    errors = validate_pipeline(data)
    if errors:
        for e in errors:
            print(e)
    else:
        pl = load_yaml(yaml_str)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Known action types and their required / optional parameters
_ACTION_SCHEMA: Dict[str, Dict[str, Any]] = {
    "find_click":         {"required": ["locator"]},
    "send_keys":          {"required": ["locator", "text"]},
    "extract_text":       {"required": ["locator"]},
    "extract_all_texts":  {"required": ["locator"]},
    "extract_attribute":  {"required": ["locator", "attr"]},
    "wait_for":           {"required": ["locator"], "optional": ["timeout"]},
    "http_get":           {"required": ["url"], "optional": ["headers"]},
    "http_post":          {"required": ["url"], "optional": ["body", "headers"]},
    "http_put":           {"required": ["url"], "optional": ["body", "headers"]},
    "http_patch":         {"required": ["url"], "optional": ["body", "headers"]},
    "http_delete":        {"required": ["url"], "optional": ["headers"]},
    "db_insert":          {"required": ["table"], "optional": ["data"]},
    "db_query":           {"optional": ["sql", "table", "filters"]},
    "db_execute":         {"required": ["sql"]},
    "excel_read":         {"required": ["path", "cell"], "optional": ["sheet"]},
    "excel_write":        {"required": ["path", "cell"], "optional": ["value", "sheet"]},
    "word_open":          {"required": ["path"]},
    "word_add_paragraph": {"required": ["path", "text"], "optional": ["style"]},
    "word_add_heading":   {"required": ["path", "text"], "optional": ["level"]},
    "word_get_text":      {"required": ["path"]},
    "word_find_replace":  {"required": ["path", "old", "new"]},
    "word_add_table":     {"required": ["path", "rows", "cols"], "optional": ["data"]},
    "word_add_picture":   {"required": ["path", "image_path"], "optional": ["width"]},
    "word_save":          {"required": ["path"], "optional": ["target"]},
    "word_close":         {"required": ["path"], "optional": ["save"]},
    "map_each":           {"required": ["fn"]},
    "filter_items":       {"required": ["fn"]},
    "transform":          {"required": ["fn"]},
    "sequence":           {"required": ["steps"]},
    "if":                 {"required": ["condition", "then"]},
    "switch":             {"required": ["value", "cases"]},
    "for_each":           {"required": ["items", "steps"]},
    "ai_generate":        {"required": ["prompt"], "optional": ["content", "system", "temperature"]},
    "ai_extract":         {"required": ["schema"], "optional": ["content", "temperature"]},
    "ai_classify":        {"required": ["categories"], "optional": ["content", "temperature"]},
    "ai_summarize":       {"optional": ["content", "system", "temperature"]},
    "ai_decide":          {"required": ["question"], "optional": ["content", "temperature"]},
    "while_":             {"required": ["condition", "steps"]},
    "until_":             {"required": ["condition", "steps"]},
    "repeat":             {"required": ["count", "steps"]},
}

# Locator types that can appear in string/dict form
_KNOWN_LOCATOR_TYPES = {"id", "name", "type", "class", "region", "image", "chain"}


def validate_pipeline(data: dict) -> List[str]:
    """Validate a pipeline definition dict.

    Returns a list of human-readable error messages (empty = valid).
    """
    errors: List[str] = []

    pl_spec = data.get("pipeline", data)
    if "pipeline" not in data and "name" not in data and "steps" not in data:
        errors.append("Top-level key must be 'pipeline' or include 'name' + 'steps'.")

    name = pl_spec.get("name", "")
    steps = pl_spec.get("steps", [])
    if isinstance(pl_spec, list):
        steps = pl_spec

    if not name:
        errors.append("'name' is required (pipeline name).")
    if not steps:
        errors.append("'steps' must be a non-empty list.")

    if isinstance(steps, list):
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"steps[{i}]: expected dict, got {type(step).__name__}")
                continue
            _validate_step(step, i, errors)

    return errors


def _validate_step(step: dict, index: int, errors: List[str]) -> None:
    prefix = f"steps[{index}]"
    step_name = step.get("name", f"<unnamed-{index}>")

    if "name" not in step:
        errors.append(f"{prefix}: 'name' is required.")
    if "action" not in step:
        errors.append(f"{prefix} ({step_name}): 'action' is required.")
        return

    action = step["action"]
    schema = _ACTION_SCHEMA.get(action)

    if schema is None:
        errors.append(
            f"{prefix} ({step_name}): unknown action type '{action}'. "
            f"Known: {sorted(_ACTION_SCHEMA.keys())}"
        )
        return

    for req in schema.get("required", []):
        if req not in step:
            errors.append(f"{prefix} ({step_name}): missing required parameter '{req}' for action '{action}'.")

    if "locator" in step:
        _validate_locator(step["locator"], f"{prefix} ({step_name})", errors)

    if "condition" in step:
        _validate_condition(step["condition"], f"{prefix} ({step_name}).condition", errors)


def _validate_locator(loc: Any, prefix: str, errors: List[str]) -> None:
    """Validate a locator value."""
    if isinstance(loc, str):
        if ":" in loc:
            t = loc.split(":", 1)[0].strip().lower()
            if t not in _KNOWN_LOCATOR_TYPES:
                errors.append(f"{prefix}: unknown locator type '{t}' in '{loc}'.")
    elif isinstance(loc, dict):
        t = loc.get("type", "name")
        if t not in _KNOWN_LOCATOR_TYPES:
            errors.append(f"{prefix}: unknown locator type '{t}'.")
        if "value" not in loc and t != "region" and t != "chain":
            errors.append(f"{prefix}: locator dict missing 'value' key.")
    elif not hasattr(loc, "__class__"):  # unlikely
        errors.append(f"{prefix}: invalid locator type {type(loc).__name__}.")


def _validate_condition(cond: Any, prefix: str, errors: List[str]) -> None:
    """Recursively validate a condition expression."""
    if isinstance(cond, (bool, str)):
        return
    if isinstance(cond, dict):
        op = list(cond.keys())[0] if cond else ""
        if op in ("and", "or"):
            items = cond.get(op, [])
            if not isinstance(items, list):
                errors.append(f"{prefix}: '{op}' expects a list of conditions.")
            else:
                for i, item in enumerate(items):
                    _validate_condition(item, f"{prefix}.{op}[{i}]", errors)
        elif op == "not":
            _validate_condition(cond["not"], f"{prefix}.not", errors)
        elif op in ("exists", "not_exists", "visible", "enabled", "selected"):
            if "locator" in cond:
                _validate_locator(cond["locator"], prefix, errors)
        elif op in ("eq", "neq", "contains", "gt", "lt"):
            pass  # value comparisons are validated at runtime
        # else: unknown, validated at runtime
