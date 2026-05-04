"""Pipeline context — extended automation context for pipeline-style data flow.

Extends :class:`~rpa.core.context.AutomationContext` with shared variables,
step history, expression resolution, and large-data tempfile management.
Every step in a pipeline receives this context as its sole argument.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import shutil
import tempfile
import uuid
from typing import Any, Dict, Optional

from mocharpa.core.context import AutomationContext
from mocharpa.core.driver import DriverAdapter

logger = logging.getLogger("rpa.pipeline.ctx")


# ======================================================================
# Ref — lightweight handle for large intermediate data
# ======================================================================

class Ref:
    """A lightweight handle that points to large data stored on disk.

    When a step produces large data (e.g. a downloaded file, database dump)
    it can store the content via :meth:`PipelineContext.put_large` and pass
    a ``Ref`` as ``ctx.previous``.  The next step reads it back on-demand
    with :meth:`PipelineContext.get_large`.

    ``Ref`` objects are recognised by the audit system and serialised as
    ``"<ref:key>"`` instead of expanding the full content.

    Attributes:
        key: The storage key used with ``put_large`` / ``get_large``.
        path: Absolute path to the temp file on disk.
        size: Size in bytes (if known at creation time).
    """

    __slots__ = ("key", "path", "size")

    def __init__(self, key: str, path: str, size: int = 0) -> None:
        self.key = key
        self.path = path
        self.size = size

    def read_text(self, encoding: str = "utf-8") -> str:
        with open(self.path, "r", encoding=encoding) as f:
            return f.read()

    def read_bytes(self) -> bytes:
        with open(self.path, "rb") as f:
            return f.read()

    def __repr__(self) -> str:
        return f"Ref(key={self.key!r}, size={self.size})"


# ======================================================================
# PipelineContext
# ======================================================================

class PipelineContext(AutomationContext):
    """Extended context carrying pipeline-scoped data between steps.

    Key additions over :class:`AutomationContext`:

    * ``data`` — shared variable bag (e.g. username, URLs)
    * ``previous`` — return value of the previous step (pipeline core)
    * ``step_results`` — history of all step outputs keyed by step name
    * ``resolve(expr)`` — template expression resolver
    * ``tempdir`` — auto-created temporary directory (cleaned after pipeline)
    * ``put_large / get_large / ref`` — disk-backed storage for large data

    Usage inside a step action::

        def my_step(ctx: PipelineContext):
            user = ctx.resolve("${data.username}")
            ctx.data["token"] = login(user)
            return token

        # Large data pattern:
        def download_step(ctx: PipelineContext):
            data = requests.get(url).content  # 500 MB
            return ctx.put_large("report", data)  # returns Ref

        def process_step(ctx: PipelineContext):
            ref = ctx.previous  # Ref("report", "/tmp/.../abc.dat", 500MB)
            content = ref.read_bytes()  # on-demand, not duplicated
    """

    __slots__ = (
        "data", "previous", "step_results",
        "_plugin_manager", "_audit_collector",
        "_tempdir", "_large_data",
    )

    _RESOLVE_RE = re.compile(r"\$\{(\w+(?:\.\w+)*)\}")

    def __init__(
        self,
        *,
        driver: Optional[DriverAdapter] = None,
        timeout: float = 10.0,
        data: Optional[Dict[str, Any]] = None,
        plugin_manager: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(driver=driver, timeout=timeout, **kwargs)
        self.data: Dict[str, Any] = data or {}
        self.previous: Any = None
        self.step_results: Dict[str, Any] = {}
        self._plugin_manager = plugin_manager
        self._tempdir: Optional[str] = None
        self._large_data: Dict[str, Ref] = {}

    # ------------------------------------------------------------------
    # Tempfile / large data
    # ------------------------------------------------------------------

    @property
    def tempdir(self) -> str:
        """A pipeline-scoped temporary directory (created on first access).

        The directory and all its contents are automatically removed when
        :meth:`cleanup_tempdir` is called (typically by :class:`Pipeline`
        after execution finishes).
        """
        if self._tempdir is None:
            self._tempdir = tempfile.mkdtemp(prefix="mocharpa_")
            atexit.register(self.cleanup_tempdir)
            logger.debug("Created tempdir: %s", self._tempdir)
        return self._tempdir

    def put_large(self, key: str, data: bytes | str, *, encoding: str = "utf-8") -> Ref:
        """Store *data* in a temp file and return a :class:`Ref` handle.

        This is the recommended pattern for steps that produce large outputs
        (downloaded files, database dumps, generated PDFs, etc.)::

            big_data = download_report()
            return ctx.put_large("report", big_data)

        The returned ``Ref`` can be passed as ``ctx.previous``.  The next
        step retrieves the data via :meth:`get_large` or reads the file
        directly from ``ref.path``.

        Args:
            key: Logical name for the data (used for retrieval).
            data: ``bytes`` or ``str`` content.
            encoding: Used when *data* is ``str``.

        Returns:
            A :class:`Ref` pointing to the temp file.
        """
        if isinstance(data, str):
            data_bytes = data.encode(encoding)
        else:
            data_bytes = data

        fname = f"{key}_{uuid.uuid4().hex[:8]}"
        fpath = os.path.join(self.tempdir, fname)
        with open(fpath, "wb") as f:
            f.write(data_bytes)

        ref = Ref(key=key, path=fpath, size=len(data_bytes))
        self._large_data[key] = ref
        logger.debug("put_large: key=%s size=%d path=%s", key, len(data_bytes), fpath)
        return ref

    def get_large(self, key: str) -> Optional[Ref]:
        """Retrieve a previously-stored :class:`Ref` by *key*.

        Returns ``None`` if *key* was never stored.
        """
        return self._large_data.get(key)

    def ref(self, key: str) -> Ref:
        """Create a :class:`Ref` for an existing temp file or path.

        Unlike :meth:`put_large`, this does NOT write any data — it just
        creates the handle.  Useful when an external operation already
        wrote a file to ``ctx.tempdir``.

        Raises:
            KeyError: If *key* was not previously stored via :meth:`put_large`.
        """
        ref = self._large_data.get(key)
        if ref is None:
            raise KeyError(
                f"No large data stored under '{key}'. "
                f"Use put_large() first, or pass a path to ref()."
            )
        return ref

    def cleanup_tempdir(self) -> None:
        """Remove the temporary directory and all contents."""
        if self._tempdir and os.path.isdir(self._tempdir):
            shutil.rmtree(self._tempdir, ignore_errors=True)
            logger.debug("Cleaned tempdir: %s", self._tempdir)
            self._tempdir = None
        self._large_data.clear()

    # ------------------------------------------------------------------
    # Pipeline helpers
    # ------------------------------------------------------------------

    def record_step(self, name: str, result: Any) -> None:
        """Store a step's output so other steps can reference it."""
        self.step_results[name] = result
        self.previous = result

    def resolve(self, expr: Any) -> Any:
        """Resolve template expressions in *expr*.

        Supports::

            ${data.key}       →  self.data["key"]
            ${previous}       →  self.previous
            ${step_name}      →  self.step_results["step_name"]
            ${data.a.b.c}     →  nested dict traversal

        If *expr* is not a string, it is returned unchanged.
        If the expression cannot be resolved, the original placeholder is kept.
        """
        if not isinstance(expr, str):
            return expr

        m = self._RESOLVE_RE.fullmatch(expr.strip())
        if m:
            return self._resolve_path(m.group(1))

        def _replace(match: re.Match) -> str:
            path = match.group(1)
            val = self._resolve_path(path)
            return str(val) if val is not None else match.group(0)

        return self._RESOLVE_RE.sub(_replace, expr)

    def _resolve_path(self, path: str) -> Any:
        """Resolve a dot-separated path against context namespaces."""
        parts = path.split(".")
        root = parts[0]

        if root == "previous":
            target = self.previous
            keys = parts[1:]
        elif root == "data":
            target = self.data
            keys = parts[1:]
        elif root == "env":
            import os as _os
            target = dict(_os.environ)
            keys = parts[1:]
        elif root in self.step_results:
            target = self.step_results[root]
            keys = parts[1:]
        else:
            target = self.data
            keys = parts

        for key in keys:
            if isinstance(target, dict):
                target = target.get(key)
            elif hasattr(target, key):
                target = getattr(target, key)
            else:
                return None
        return target

    # ------------------------------------------------------------------
    # Plugin access
    # ------------------------------------------------------------------

    @property
    def plugins(self) -> Any:
        """Return the bound :class:`~rpa.plugin.base.PluginManager`, if any."""
        return self._plugin_manager

    def plugin(self, name: str) -> Any:
        """Get a registered plugin by name.

        Raises:
            KeyError: If no plugin manager is bound or the plugin is not found.
        """
        if self._plugin_manager is None:
            raise KeyError(
                f"No plugin manager bound to context; cannot resolve plugin '{name}'"
            )
        return self._plugin_manager.get(name)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        base = super().__repr__()
        return base.replace(
            "AutomationContext", "PipelineContext"
        ) + f" data_keys={list(self.data.keys())}"
