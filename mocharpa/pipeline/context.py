"""Pipeline context — extended automation context for pipeline-style data flow.

Extends :class:`~rpa.core.context.AutomationContext` with shared variables,
step history, and expression resolution.  Every step in a pipeline receives
this context as its sole argument.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from mocharpa.core.context import AutomationContext
from mocharpa.core.driver import DriverAdapter


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

    Usage inside a step action::

        def my_step(ctx: PipelineContext):
            user = ctx.resolve("${data.username}")
            ctx.data["token"] = login(user)
            return token
    """

    __slots__ = ("data", "previous", "step_results", "_plugin_manager", "_audit_collector")

    # Reserved variable prefixes for resolve()
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

        Args:
            expr: A string potentially containing ``${...}`` placeholders,
                  or any other value.

        Returns:
            The resolved value.
        """
        if not isinstance(expr, str):
            return expr

        # Full-string match → return the resolved value directly (not string)
        m = self._RESOLVE_RE.fullmatch(expr.strip())
        if m:
            return self._resolve_path(m.group(1))

        # Partial-string match → substitute placeholders in-place
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
            import os
            target = dict(os.environ)
            keys = parts[1:]
        elif root in self.step_results:
            target = self.step_results[root]
            keys = parts[1:]
        else:
            # Fallback: treat full path as keys into data dict
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
