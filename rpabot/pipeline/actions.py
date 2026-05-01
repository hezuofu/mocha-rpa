"""Pre-built action factories for common RPA operations.

Each factory returns a callable ``(ctx: PipelineContext) -> Any`` that can be
passed directly to ``Pipeline.step()``.  The callable automatically resolves
template expressions in its arguments via ``ctx.resolve()``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from rpabot.core.locator import Locator, LocatorFactory, LocatorSpec


# ======================================================================
# Helpers
# ======================================================================

def _resolve(ctx: Any, value: Any) -> Any:
    """Resolve a value through the PipelineContext."""
    if hasattr(ctx, "resolve"):
        return ctx.resolve(value)
    return value


def _ensure_find_builder(ctx: Any, locator: LocatorSpec):
    """Create a FindBuilder bound to *ctx* from a string/dict/Locator."""
    from rpabot.builder.find_builder import FindBuilder

    # Build with correct locator
    if isinstance(locator, (str, dict)):
        loc = LocatorFactory.create(locator)
    elif isinstance(locator, Locator):
        loc = locator
    else:
        loc = LocatorFactory.create(locator)

    fb = FindBuilder((loc,))
    # Bind context for driver/timeout
    if hasattr(ctx, "driver"):
        fb = fb.with_context(ctx)
    return fb


# ======================================================================
# UI Actions
# ======================================================================

def find_click(locator: LocatorSpec) -> Callable[[Any], Any]:
    """Find an element and click it.

    Args:
        locator: A string, dict, or :class:`Locator` instance.

    Usage::

        Workflow("login").step("click_login", find_click({"name": "LoginBtn"}))
    """
    def _action(ctx: Any) -> Any:
        find = _ensure_find_builder(ctx, locator)
        return find.do(lambda el: el.click())
    return _action


def send_keys(locator: LocatorSpec, text: Any) -> Callable[[Any], Any]:
    """Find an element and send keystrokes.

    *text* supports ``${data.xxx}`` and ``${previous}`` template expressions.

    Usage::

        Workflow("login").step("enter_user", send_keys({"name": "Username"}, "${data.user}"))
    """
    def _action(ctx: Any) -> Any:
        resolved = _resolve(ctx, text)
        find = _ensure_find_builder(ctx, locator)
        return find.do(lambda el: el.send_keys(str(resolved)))
    return _action


def extract_text(locator: LocatorSpec) -> Callable[[Any], Any]:
    """Extract the visible text of a single element.

    Returns the text string, which becomes ``ctx.previous`` for the next step.
    """
    def _action(ctx: Any) -> Any:
        find = _ensure_find_builder(ctx, locator)
        return find.do(lambda el: el.get_text())
    return _action


def extract_all_texts(locator: LocatorSpec) -> Callable[[Any], Any]:
    """Extract text from all matching elements.  Returns ``list[str]``."""
    def _action(ctx: Any) -> Any:
        find = _ensure_find_builder(ctx, locator)
        elements = find.with_context(ctx).all().get_all()
        return [el.get_text() for el in elements] if elements else []
    return _action


def extract_attribute(locator: LocatorSpec, attr: str) -> Callable[[Any], Any]:
    """Extract a named attribute from an element."""
    def _action(ctx: Any) -> Any:
        find = _ensure_find_builder(ctx, locator)
        return find.do(lambda el: el.get_attribute(_resolve(ctx, attr)))
    return _action


def wait_for(
    locator: LocatorSpec, timeout: float = 10.0
) -> Callable[[Any], Any]:
    """Wait for an element to become visible, then return it.

    Uses ``FindBuilder.wait_until("is_visible")``.
    """
    def _action(ctx: Any) -> Any:
        find = _ensure_find_builder(ctx, locator)
        return find.with_context(ctx).within(timeout).wait_until("is_visible")
    return _action


# ======================================================================
# HTTP Actions
# ======================================================================

def http_get(url: Any, *, headers: Any = None) -> Callable[[Any], Any]:
    """Perform an HTTP GET request and return the decoded JSON body.

    Requires an ``http`` plugin registered on the context's plugin manager.
    """
    def _action(ctx: Any) -> Any:
        resolved_url = _resolve(ctx, url)
        resolved_headers = _resolve(ctx, headers) if headers else None
        plugin = ctx.plugin("http")
        return plugin.get(resolved_url, headers=resolved_headers)
    return _action


def http_post(url: Any, data: Any = None, *, headers: Any = None) -> Callable[[Any], Any]:
    """Perform an HTTP POST request.

    *data* defaults to ``ctx.previous`` when ``None``.
    """
    def _action(ctx: Any) -> Any:
        resolved_url = _resolve(ctx, url)
        resolved_data = _resolve(ctx, data) if data is not None else ctx.previous
        resolved_headers = _resolve(ctx, headers) if headers else None
        plugin = ctx.plugin("http")
        return plugin.post(resolved_url, data=resolved_data, headers=resolved_headers)
    return _action


# ======================================================================
# Database Actions
# ======================================================================

def db_insert(table: Any, data: Any = None) -> Callable[[Any], Any]:
    """Insert a record (or list of records) into *table*.

    *data* defaults to ``ctx.previous`` when ``None``.
    """
    def _action(ctx: Any) -> Any:
        resolved_table = _resolve(ctx, table)
        resolved_data = _resolve(ctx, data) if data is not None else ctx.previous
        plugin = ctx.plugin("database")
        return plugin.insert(resolved_table, resolved_data)
    return _action


def db_query(sql: Any, **kwargs: Any) -> Callable[[Any], Any]:
    """Execute a SQL query and return fetched rows."""
    def _action(ctx: Any) -> Any:
        resolved_sql = _resolve(ctx, sql)
        resolved_kwargs = {k: _resolve(ctx, v) for k, v in kwargs.items()}
        plugin = ctx.plugin("database")
        return plugin.query(resolved_sql, **resolved_kwargs)
    return _action


def db_execute(sql: Any, **kwargs: Any) -> Callable[[Any], Any]:
    """Execute a SQL statement (INSERT/UPDATE/DELETE)."""
    def _action(ctx: Any) -> Any:
        resolved_sql = _resolve(ctx, sql)
        resolved_kwargs = {k: _resolve(ctx, v) for k, v in kwargs.items()}
        plugin = ctx.plugin("database")
        return plugin.execute(resolved_sql, **resolved_kwargs)
    return _action


# ======================================================================
# Excel Actions
# ======================================================================

def excel_read(path: Any, cell: Any) -> Callable[[Any], Any]:
    """Read a value from an Excel file.  Returns the cell content."""
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_cell = _resolve(ctx, cell)
        plugin = ctx.plugin("excel")
        plugin.open(resolved_path)
        return plugin.read_cell(resolved_cell)
    return _action


def excel_write(path: Any, cell: Any, value: Any = None) -> Callable[[Any], Any]:
    """Write a value to an Excel cell.

    *value* defaults to ``ctx.previous`` when ``None``.
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_cell = _resolve(ctx, cell)
        resolved_value = _resolve(ctx, value) if value is not None else ctx.previous
        plugin = ctx.plugin("excel")
        plugin.open(resolved_path)
        plugin.write_cell(resolved_cell, resolved_value)
        plugin.save()
        return resolved_value
    return _action


# ======================================================================
# Generic Transform Actions
# ======================================================================

def map_each(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """Map *fn* over ``ctx.previous`` (expecting an iterable)."""
    def _action(ctx: Any) -> List[Any]:
        return [fn(item) for item in (ctx.previous or [])]
    return _action


def filter_items(fn: Callable[[Any], bool]) -> Callable[[Any], Any]:
    """Filter ``ctx.previous`` (expecting an iterable)."""
    def _action(ctx: Any) -> List[Any]:
        return [item for item in (ctx.previous or []) if fn(item)]
    return _action


def transform(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """Apply *fn* to ``ctx.previous`` and return the result.

    Equivalent to a ``pipe`` step: output = fn(previous).
    """
    def _action(ctx: Any) -> Any:
        return fn(ctx.previous)
    return _action
