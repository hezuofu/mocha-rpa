"""Plugin system for extending the RPA framework.

Plugins follow a simple lifecycle protocol and are managed by a central
:class:`PluginManager` that handles registration, initialization, and
graceful teardown.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger("rpa.plugin")


# ======================================================================
# Plugin protocol
# ======================================================================

@runtime_checkable
class Plugin(Protocol):
    """Protocol that every plugin must satisfy.

    Attributes:
        name: Unique plugin identifier.
    """

    name: str

    def initialize(self, context: Any) -> None:
        """Called once after registration.  Receives the current
        :class:`~rpa.core.context.AutomationContext`.
        """
        ...

    def cleanup(self) -> None:
        """Called when the framework shuts down or the plugin is removed."""
        ...


# ======================================================================
# PluginManager
# ======================================================================

class PluginManager:
    """Central registry and lifecycle manager for plugins.

    Usage::

        mgr = PluginManager(context)

        class LogPlugin:
            name = "logger"
            def initialize(self, ctx): ...
            def cleanup(self): ...

        mgr.register(LogPlugin())
        mgr.start_all()
        # ... run automation ...
        mgr.shutdown_all()
    """

    def __init__(self, context: Optional[Any] = None) -> None:
        self._plugins: Dict[str, Plugin] = {}
        self._context = context

    @property
    def context(self) -> Optional[Any]:
        """The :class:`AutomationContext` bound to this manager."""
        return self._context

    @context.setter
    def context(self, value: Any) -> None:
        self._context = value

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, plugin: Plugin) -> None:
        """Register a plugin instance.

        Raises:
            ValueError: If a plugin with the same name is already registered.
        """
        if plugin.name in self._plugins:
            raise ValueError(
                f"Plugin '{plugin.name}' is already registered"
            )
        self._plugins[plugin.name] = plugin
        logger.info("Registered plugin: %s", plugin.name)

    def unregister(self, name: str) -> Optional[Plugin]:
        """Remove and return a plugin by name (``None`` if not found)."""
        plugin = self._plugins.pop(name, None)
        if plugin:
            logger.info("Unregistered plugin: %s", name)
        return plugin

    def get(self, name: str) -> Optional[Plugin]:
        """Return a registered plugin by name."""
        return self._plugins.get(name)

    def list_names(self) -> List[str]:
        """Return the names of all registered plugins."""
        return list(self._plugins.keys())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_all(self) -> None:
        """Initialize all registered plugins."""
        for name, plugin in self._plugins.items():
            try:
                plugin.initialize(self._context)
                logger.info("Plugin started: %s", name)
            except Exception:
                logger.exception("Failed to start plugin: %s", name)

    def shutdown_all(self) -> None:
        """Clean up all registered plugins (reverse order)."""
        for name in reversed(list(self._plugins.keys())):
            plugin = self._plugins[name]
            try:
                plugin.cleanup()
                logger.info("Plugin shut down: %s", name)
            except Exception:
                logger.exception("Failed to shut down plugin: %s", name)
        self._plugins.clear()

    def start(self, name: str) -> None:
        """Initialize a single plugin by name."""
        plugin = self._plugins.get(name)
        if plugin is None:
            raise KeyError(f"Plugin not found: {name}")
        plugin.initialize(self._context)

    def shutdown(self, name: str) -> None:
        """Clean up and unregister a single plugin."""
        plugin = self._plugins.pop(name, None)
        if plugin is not None:
            plugin.cleanup()

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: str) -> bool:
        return name in self._plugins
