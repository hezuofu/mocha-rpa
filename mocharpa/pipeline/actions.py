"""Pre-built action factories for common RPA operations.

Each factory returns a callable ``(ctx: PipelineContext) -> Any`` that can be
passed directly to ``Pipeline.step()``.  The callable automatically resolves
template expressions in its arguments via ``ctx.resolve()``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from mocharpa.core.locator import Locator, LocatorFactory, LocatorSpec


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
    from mocharpa.builder.find_builder import FindBuilder

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


def http_put(url: Any, data: Any = None, *, headers: Any = None) -> Callable[[Any], Any]:
    """Perform an HTTP PUT request.

    *data* defaults to ``ctx.previous`` when ``None``.
    """
    def _action(ctx: Any) -> Any:
        resolved_url = _resolve(ctx, url)
        resolved_data = _resolve(ctx, data) if data is not None else ctx.previous
        resolved_headers = _resolve(ctx, headers) if headers else None
        plugin = ctx.plugin("http")
        return plugin.put(resolved_url, data=resolved_data, headers=resolved_headers)
    return _action


def http_patch(url: Any, data: Any = None, *, headers: Any = None) -> Callable[[Any], Any]:
    """Perform an HTTP PATCH request.

    *data* defaults to ``ctx.previous`` when ``None``.
    """
    def _action(ctx: Any) -> Any:
        resolved_url = _resolve(ctx, url)
        resolved_data = _resolve(ctx, data) if data is not None else ctx.previous
        resolved_headers = _resolve(ctx, headers) if headers else None
        plugin = ctx.plugin("http")
        return plugin.patch(resolved_url, data=resolved_data, headers=resolved_headers)
    return _action


def http_delete(url: Any, *, headers: Any = None) -> Callable[[Any], Any]:
    """Perform an HTTP DELETE request."""
    def _action(ctx: Any) -> Any:
        resolved_url = _resolve(ctx, url)
        resolved_headers = _resolve(ctx, headers) if headers else None
        plugin = ctx.plugin("http")
        return plugin.delete(resolved_url, headers=resolved_headers)
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


def db_query(sql: Any = None, *, table: Any = None, **filters: Any) -> Callable[[Any], Any]:
    """Execute a SQL SELECT query or simple table lookup.

    Two modes:
        - ``sql`` — raw SQL (uses ``fetch_all``)
        - ``table`` + ``**filters`` — simple column-equality query (uses ``query``)
    """
    def _action(ctx: Any) -> Any:
        plugin = ctx.plugin("database")
        if sql is not None:
            resolved_sql = _resolve(ctx, sql)
            resolved_filters = {k: _resolve(ctx, v) for k, v in filters.items()}
            return plugin.fetch_all(resolved_sql, resolved_filters or None)
        resolved_table = _resolve(ctx, table)
        resolved_filters = {k: _resolve(ctx, v) for k, v in filters.items()}
        return plugin.query(resolved_table, **resolved_filters)
    return _action


def db_execute(sql: Any, **kwargs: Any) -> Callable[[Any], Any]:
    """Execute a SQL statement (INSERT/UPDATE/DELETE) and return rowcount."""
    def _action(ctx: Any) -> Any:
        resolved_sql = _resolve(ctx, sql)
        resolved_kwargs = {k: _resolve(ctx, v) for k, v in kwargs.items()}
        plugin = ctx.plugin("database")
        result = plugin.execute(resolved_sql, resolved_kwargs or None)
        return result.rowcount
    return _action


# ======================================================================
# Excel Actions
# ======================================================================

def _parse_cell_ref(cell: str) -> tuple:
    """Parse a cell reference like ``"A1"`` or ``"Sheet1!B2"``.

    Returns ``(sheet, row, col)`` where row/col are 1-indexed.
    If no sheet is given, defaults to ``None`` (use active sheet).
    """
    import re

    sheet = None
    target = cell
    m = re.match(r"^(.+)!(.+)$", cell)
    if m:
        sheet = m.group(1).strip("'")
        target = m.group(2)

    m = re.match(r"^([A-Z]+)(\d+)$", target, re.IGNORECASE)
    if not m:
        raise ValueError(f"Invalid cell reference: {cell!r}. Expected format: 'A1' or 'Sheet1!A1'")

    col_letters = m.group(1).upper()
    col = 0
    for ch in col_letters:
        col = col * 26 + (ord(ch) - ord("A") + 1)
    row = int(m.group(2))
    return sheet, row, col


def excel_read(path: Any, cell: Any, *, sheet: Any = None) -> Callable[[Any], Any]:
    """Read a value from an Excel file.

    Args:
        path: Path to the Excel file.
        cell: Cell reference, e.g. ``"A1"`` or ``"Sheet1!B2"``.
        sheet: Optional sheet name (overrides sheet in cell reference).

    Returns the cell content.
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_cell = _resolve(ctx, cell)
        resolved_sheet = _resolve(ctx, sheet) if sheet is not None else None

        ref_sheet, row, col = _parse_cell_ref(str(resolved_cell))
        active_sheet = resolved_sheet or ref_sheet

        plugin = ctx.plugin("excel")
        wb = plugin.open(resolved_path)
        return plugin.read_cell(wb, active_sheet or "Sheet", row, col)
    return _action


def excel_write(path: Any, cell: Any, value: Any = None, *, sheet: Any = None) -> Callable[[Any], Any]:
    """Write a value to an Excel cell.

    Args:
        path: Path to the Excel file.
        cell: Cell reference, e.g. ``"A1"`` or ``"Sheet1!B2"``.
        value: Value to write.  Defaults to ``ctx.previous``.
        sheet: Optional sheet name (overrides sheet in cell reference).
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_cell = _resolve(ctx, cell)
        resolved_value = _resolve(ctx, value) if value is not None else ctx.previous
        resolved_sheet = _resolve(ctx, sheet) if sheet is not None else None

        ref_sheet, row, col = _parse_cell_ref(str(resolved_cell))
        active_sheet = resolved_sheet or ref_sheet

        plugin = ctx.plugin("excel")
        wb = plugin.open(resolved_path)
        plugin.write_cell(wb, active_sheet or "Sheet", row, col, resolved_value)
        plugin.save(plugin._key_from_path(resolved_path), resolved_path)
        return resolved_value
    return _action


# ======================================================================
# Word Actions
# ======================================================================

def word_open(path: Any) -> Callable[[Any], Any]:
    """Open or create a Word document.

    If the file exists it is opened; otherwise a new blank document is
    created (but NOT saved until :func:`word_save` is called).

    Returns the document stem name for use in subsequent Word steps.
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        plugin = ctx.plugin("word")
        import os
        if os.path.exists(resolved_path):
            plugin.open(resolved_path)
        else:
            plugin.create(resolved_path)
        return plugin._key_from_path(resolved_path)
    return _action


def word_add_paragraph(path: Any, text: Any, *, style: Any = None) -> Callable[[Any], Any]:
    """Add a paragraph to a Word document.

    *text* supports ``${...}`` template expressions.
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_text = _resolve(ctx, text)
        resolved_style = _resolve(ctx, style) if style is not None else None
        plugin = ctx.plugin("word")
        doc = plugin.open(resolved_path)
        return plugin.add_paragraph(doc, str(resolved_text), style=resolved_style)
    return _action


def word_add_heading(path: Any, text: Any, *, level: Any = 1) -> Callable[[Any], Any]:
    """Add a heading to a Word document.

    Args:
        path: Path to the document.
        text: Heading text (supports ``${...}`` templates).
        level: Heading level 1–9 (default ``1``).
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_text = _resolve(ctx, text)
        resolved_level = int(_resolve(ctx, level))
        plugin = ctx.plugin("word")
        doc = plugin.open(resolved_path)
        return plugin.add_heading(doc, str(resolved_text), level=resolved_level)
    return _action


def word_get_text(path: Any) -> Callable[[Any], Any]:
    """Extract the full plain text of a Word document."""
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        plugin = ctx.plugin("word")
        doc = plugin.open(resolved_path)
        return plugin.get_text(doc)
    return _action


def word_find_replace(path: Any, old: Any, new: Any) -> Callable[[Any], Any]:
    """Find and replace text in a Word document.

    Replaces all occurrences of *old* with *new* in both paragraphs and
    tables.  Returns the number of replacements made.
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_old = str(_resolve(ctx, old))
        resolved_new = str(_resolve(ctx, new))
        plugin = ctx.plugin("word")
        doc = plugin.open(resolved_path)
        return plugin.find_and_replace(doc, resolved_old, resolved_new)
    return _action


def word_add_table(
    path: Any,
    rows: Any,
    cols: Any,
    *,
    data: Any = None,
) -> Callable[[Any], Any]:
    """Add a table to a Word document.

    Args:
        path: Path to the document.
        rows: Number of rows.
        cols: Number of columns.
        data: Optional ``list[list[str]]`` to populate (supports ``${...}``).
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_rows = int(_resolve(ctx, rows))
        resolved_cols = int(_resolve(ctx, cols))
        resolved_data = _resolve(ctx, data) if data is not None else None
        plugin = ctx.plugin("word")
        doc = plugin.open(resolved_path)
        return plugin.add_table(doc, resolved_rows, resolved_cols, data=resolved_data)
    return _action


def word_add_picture(
    path: Any,
    image_path: Any,
    *,
    width: Any = 3.0,
) -> Callable[[Any], Any]:
    """Insert an image into a Word document.

    Args:
        path: Path to the document.
        image_path: Path to the image file.
        width: Image width in inches (default ``3.0``).
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_image = _resolve(ctx, image_path)
        resolved_width = float(_resolve(ctx, width))
        plugin = ctx.plugin("word")
        doc = plugin.open(resolved_path)
        return plugin.add_picture(doc, str(resolved_image), width_inches=resolved_width)
    return _action


def word_save(path: Any, *, target: Any = None) -> Callable[[Any], Any]:
    """Save a managed Word document and optionally close it.

    Args:
        path: Path key (same as used in ``word_open``).
        target: Optional output path.  If omitted, saves back to *path*.
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_target = _resolve(ctx, target) if target is not None else None
        plugin = ctx.plugin("word")
        key = plugin._key_from_path(resolved_path)
        plugin.save(key, path=resolved_target)
        return resolved_target or resolved_path
    return _action


def word_close(path: Any, *, save: Any = False) -> Callable[[Any], Any]:
    """Close a managed Word document, optionally saving first.

    Args:
        path: Path key.
        save: If truthy, save before closing.
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_save = bool(_resolve(ctx, save))
        plugin = ctx.plugin("word")
        key = plugin._key_from_path(resolved_path)
        plugin.close(key, save=resolved_save)
        return None
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


# ======================================================================
# CSV Actions
# ======================================================================

def csv_read(path: Any, *, as_dicts: Any = True) -> Callable[[Any], Any]:
    """Read a CSV file and return its contents.

    Args:
        path: Path to the CSV file.
        as_dicts: If True (default), return list of dicts. Else list of lists.
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_as_dicts = _resolve(ctx, as_dicts)
        plugin = ctx.plugin("csv")
        return plugin.read(resolved_path, as_dicts=resolved_as_dicts)
    return _action


def csv_write(path: Any, data: Any = None, *, fieldnames: Any = None) -> Callable[[Any], Any]:
    """Write rows to a CSV file (overwrites).

    *data* defaults to ``ctx.previous`` when ``None``.
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_data = _resolve(ctx, data) if data is not None else ctx.previous
        resolved_fields = _resolve(ctx, fieldnames) if fieldnames else None
        plugin = ctx.plugin("csv")
        plugin.write(resolved_path, resolved_data, fieldnames=resolved_fields)
        return resolved_data
    return _action


def csv_append(path: Any, data: Any = None) -> Callable[[Any], Any]:
    """Append rows to an existing CSV file.

    *data* defaults to ``ctx.previous`` when ``None``.
    """
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_data = _resolve(ctx, data) if data is not None else ctx.previous
        plugin = ctx.plugin("csv")
        plugin.append(resolved_path, resolved_data)
        return resolved_data
    return _action


# ======================================================================
# File Actions
# ======================================================================

def file_read_text(path: Any, *, encoding: Any = "utf-8") -> Callable[[Any], Any]:
    """Read the full contents of a text file."""
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_enc = _resolve(ctx, encoding)
        plugin = ctx.plugin("file")
        return plugin.read_text(resolved_path, encoding=resolved_enc)
    return _action


def file_write_text(path: Any, content: Any = None, *, encoding: Any = "utf-8") -> Callable[[Any], Any]:
    """Write text to a file.  *content* defaults to ``ctx.previous``."""
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        resolved_content = _resolve(ctx, content) if content is not None else ctx.previous
        resolved_enc = _resolve(ctx, encoding)
        plugin = ctx.plugin("file")
        plugin.write_text(resolved_path, str(resolved_content), encoding=resolved_enc)
        return resolved_path
    return _action


def file_copy(src: Any, dst: Any) -> Callable[[Any], Any]:
    """Copy a file from *src* to *dst*."""
    def _action(ctx: Any) -> Any:
        resolved_src = _resolve(ctx, src)
        resolved_dst = _resolve(ctx, dst)
        plugin = ctx.plugin("file")
        return plugin.copy(resolved_src, resolved_dst)
    return _action


def file_move(src: Any, dst: Any) -> Callable[[Any], Any]:
    """Move/rename a file."""
    def _action(ctx: Any) -> Any:
        resolved_src = _resolve(ctx, src)
        resolved_dst = _resolve(ctx, dst)
        plugin = ctx.plugin("file")
        return plugin.move(resolved_src, resolved_dst)
    return _action


def file_delete(path: Any) -> Callable[[Any], Any]:
    """Delete a file or empty directory."""
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        plugin = ctx.plugin("file")
        plugin.delete(resolved_path)
        return None
    return _action


def file_glob(pattern: Any, *, recursive: Any = False) -> Callable[[Any], Any]:
    """Glob for files matching a pattern."""
    def _action(ctx: Any) -> Any:
        resolved_pattern = _resolve(ctx, pattern)
        resolved_rec = _resolve(ctx, recursive)
        plugin = ctx.plugin("file")
        return plugin.glob(resolved_pattern, recursive=resolved_rec)
    return _action


def file_exists(path: Any) -> Callable[[Any], Any]:
    """Check if a file or directory exists."""
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        plugin = ctx.plugin("file")
        return plugin.exists(resolved_path)
    return _action


def file_mkdir(path: Any) -> Callable[[Any], Any]:
    """Create a directory (with parents)."""
    def _action(ctx: Any) -> Any:
        resolved_path = _resolve(ctx, path)
        plugin = ctx.plugin("file")
        return plugin.mkdir(resolved_path)
    return _action


# ======================================================================
# Queue Actions
# ======================================================================

def queue_push(queue: Any, payload: Any = None, *, priority: Any = 0, delay: Any = 0) -> Callable[[Any], Any]:
    """Enqueue a message.  *payload* defaults to ``ctx.previous``.

    Returns the message ID.
    """
    def _action(ctx: Any) -> Any:
        resolved_queue = _resolve(ctx, queue)
        resolved_payload = _resolve(ctx, payload) if payload is not None else ctx.previous
        resolved_priority = int(_resolve(ctx, priority))
        resolved_delay = float(_resolve(ctx, delay))
        plugin = ctx.plugin("queue")
        return plugin.push(resolved_queue, resolved_payload,
                          priority=resolved_priority, delay=resolved_delay)
    return _action


def queue_pop(queue: Any) -> Callable[[Any], Any]:
    """Claim the next message from a queue.

    Returns ``[message_id, payload]`` or ``None``.
    """
    def _action(ctx: Any) -> Any:
        resolved_queue = _resolve(ctx, queue)
        plugin = ctx.plugin("queue")
        result = plugin.pop(resolved_queue)
        return list(result) if result else None
    return _action


def queue_ack(msg_id: Any) -> Callable[[Any], Any]:
    """Mark a message as processed.

    *msg_id* defaults to ``ctx.previous[0]`` (the ID from a ``queue_pop`` result).
    """
    def _action(ctx: Any) -> Any:
        resolved_id = _resolve(ctx, msg_id) if msg_id is not None else (
            ctx.previous[0] if isinstance(ctx.previous, (list, tuple)) else None
        )
        plugin = ctx.plugin("queue")
        plugin.ack(int(resolved_id))
        return None
    return _action


def queue_fail(msg_id: Any, error: Any = "") -> Callable[[Any], Any]:
    """Mark a message as failed (will retry or move to dead-letter).

    *msg_id* defaults to ``ctx.previous[0]``.
    """
    def _action(ctx: Any) -> Any:
        resolved_id = _resolve(ctx, msg_id) if msg_id is not None else (
            ctx.previous[0] if isinstance(ctx.previous, (list, tuple)) else None
        )
        resolved_error = _resolve(ctx, error) or ""
        plugin = ctx.plugin("queue")
        return plugin.fail(int(resolved_id), str(resolved_error))
    return _action


# ======================================================================
# AI Actions
# ======================================================================

def ai_generate(
    prompt: Any,
    *,
    content: Any = "",
    system: Any = "",
    temperature: Any = 0.7,
) -> Callable[[Any], Any]:
    """Generate text using AI.  *content* defaults to ``ctx.previous`` when empty."""
    def _action(ctx: Any) -> Any:
        resolved_prompt = _resolve(ctx, prompt)
        resolved_content = _resolve(ctx, content) if content else ctx.previous or ""
        resolved_system = _resolve(ctx, system) or ""
        resolved_temp = float(_resolve(ctx, temperature))
        plugin = ctx.plugin("ai")
        return plugin.generate(
            resolved_prompt,
            content=str(resolved_content),
            system=str(resolved_system),
            temperature=resolved_temp,
        )
    return _action


def ai_extract(
    content: Any = "",
    schema: Any = None,
    *,
    temperature: Any = 0.0,
) -> Callable[[Any], Any]:
    """Extract structured data from *content* using AI.

    *content* defaults to ``ctx.previous``.  *schema* must be a dict
    like ``{"name": "str", "price": "float"}``.
    """
    def _action(ctx: Any) -> Any:
        resolved_content = _resolve(ctx, content) if content else ctx.previous or ""
        resolved_schema = _resolve(ctx, schema) if schema is not None else {}
        resolved_temp = float(_resolve(ctx, temperature))
        plugin = ctx.plugin("ai")
        return plugin.extract(
            str(resolved_content),
            schema=resolved_schema,
            temperature=resolved_temp,
        )
    return _action


def ai_classify(
    content: Any = "",
    categories: Any = None,
    *,
    temperature: Any = 0.0,
) -> Callable[[Any], Any]:
    """Classify *content* into one of the given *categories*.

    *content* defaults to ``ctx.previous``.  *categories* must be a list of strings.
    """
    def _action(ctx: Any) -> Any:
        resolved_content = _resolve(ctx, content) if content else ctx.previous or ""
        resolved_categories = _resolve(ctx, categories) if categories is not None else []
        resolved_temp = float(_resolve(ctx, temperature))
        plugin = ctx.plugin("ai")
        return plugin.classify(
            str(resolved_content),
            categories=resolved_categories,
            temperature=resolved_temp,
        )
    return _action


def ai_summarize(
    content: Any = "",
    *,
    system: Any = "",
    temperature: Any = 0.3,
) -> Callable[[Any], Any]:
    """Summarize *content* using AI.  *content* defaults to ``ctx.previous``."""
    def _action(ctx: Any) -> Any:
        resolved_content = _resolve(ctx, content) if content else ctx.previous or ""
        resolved_system = _resolve(ctx, system) or "You are a concise summariser. Return only the summary."
        resolved_temp = float(_resolve(ctx, temperature))
        plugin = ctx.plugin("ai")
        return plugin.generate(
            "Summarise the following content concisely.",
            content=str(resolved_content),
            system=str(resolved_system),
            temperature=resolved_temp,
        )
    return _action


def ai_decide(
    question: Any,
    *,
    content: Any = "",
    temperature: Any = 0.0,
) -> Callable[[Any], Any]:
    """Make a yes/no decision.  *content* defaults to ``ctx.previous``.

    Returns ``True`` or ``False``.
    """
    def _action(ctx: Any) -> Any:
        resolved_question = _resolve(ctx, question)
        resolved_content = _resolve(ctx, content) if content else ctx.previous or ""
        resolved_temp = float(_resolve(ctx, temperature))
        plugin = ctx.plugin("ai")
        return plugin.decide(
            str(resolved_question),
            content=str(resolved_content),
            temperature=resolved_temp,
        )
    return _action
