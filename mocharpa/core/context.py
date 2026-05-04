"""Automation context — shared configuration, caching, and hooks.

The :class:`AutomationContext` serves as the central configuration hub for
the RPA framework.  It provides:

* Default timeout / retry settings
* A scoped key-value cache with optional TTL
* A hook system for instrumenting the find/action lifecycle
* Thread-local storage support
* Context-manager based temporary overrides
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional

from mocharpa.core.driver import DriverAdapter

logger = logging.getLogger("rpa.context")

HookCallback = Callable[..., Any]


# ======================================================================
# Cache
# ======================================================================

class _Cache:
    """Simple in-memory cache with optional per-entry TTL."""

    def __init__(self) -> None:
        self._store: Dict[str, tuple[Any, Optional[float]]] = {}

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store *value* with an optional time-to-live (seconds)."""
        expires = time.monotonic() + ttl if ttl is not None else None
        self._store[key] = (value, expires)

    def get(self, key: str) -> Optional[Any]:
        """Retrieve value, returning ``None`` if missing or expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires = entry
        if expires is not None and time.monotonic() > expires:
            del self._store[key]
            return None
        return value

    def clear(self) -> None:
        """Remove all entries."""
        self._store.clear()

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __len__(self) -> int:
        return len(self._store)


# ======================================================================
# Hook registry
# ======================================================================

class HookRegistry:
    """Manages callback registration and dispatching for lifecycle events.

    Built-in events:
        ``pre_find``     —  before a locator-based search starts
        ``post_find``    —  after an element is found
        ``pre_action``   —  before an action is performed on an element
        ``post_action``  —  after an action completes
        ``on_error``     —  when an error occurs during any operation
    """

    def __init__(self) -> None:
        self._hooks: Dict[str, List[HookCallback]] = {}

    def register(self, event: str, callback: HookCallback) -> None:
        """Register *callback* for *event*."""
        self._hooks.setdefault(event, []).append(callback)

    def trigger(self, event: str, **kwargs: Any) -> None:
        """Call all registered listeners for *event*."""
        for cb in self._hooks.get(event, ()):
            try:
                cb(**kwargs)
            except Exception:
                logger.exception("Hook %s failed", event)

    def clear(self) -> None:
        """Remove all registered hooks."""
        self._hooks.clear()


# ======================================================================
# AutomationContext
# ======================================================================

class AutomationContext:
    """Central configuration and runtime context for RPA operations.

    Usage::

        ctx = AutomationContext(timeout=15.0, retry_count=5)
        ctx.register_hook("pre_find", lambda **kw: print("Finding ..."))

        with ctx.with_timeout(5):
            ...

    The context is **not** a singleton by default.  Use :meth:`get_current` /
    :meth:`set_current` for thread-local global access when needed.
    """

    _thread_local: threading.local = threading.local()

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        log_level: str = "INFO",
        retry_count: int = 3,
        retry_delay: float = 0.5,
        driver: Optional[DriverAdapter] = None,
        event_bus: Any = None,
    ) -> None:
        self.timeout: float = timeout
        self.log_level: str = log_level
        self.retry_count: int = retry_count
        self.retry_delay: float = retry_delay
        self.driver: Optional[DriverAdapter] = driver

        self._hooks = HookRegistry()
        self._cache = _Cache()
        self._overrides: Dict[str, Any] = {}

        from mocharpa.events import EventBus
        self.event_bus: EventBus = event_bus if event_bus is not None else EventBus()
        if driver is not None:
            driver._event_bus = self.event_bus

        self._configure_logging()

    # ------------------------------------------------------------------
    # Thread-local access
    # ------------------------------------------------------------------

    @classmethod
    def get_current(cls) -> AutomationContext:
        """Return the thread-local default context, creating one if needed."""
        ctx = getattr(cls._thread_local, "context", None)
        if ctx is None:
            ctx = AutomationContext()
            cls._thread_local.context = ctx
        return ctx

    @classmethod
    def set_current(cls, context: AutomationContext) -> None:
        """Set the thread-local default context."""
        cls._thread_local.context = context

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _configure_logging(self) -> None:
        level = getattr(logging, self.log_level.upper(), logging.INFO)
        logger.setLevel(level)

    @contextmanager
    def with_timeout(self, timeout: float):
        """Temporarily override the context timeout.

        Usage::

            with ctx.with_timeout(5):
                Find().name("X").do(...)
        """
        old = self.timeout
        self.timeout = timeout
        try:
            yield self
        finally:
            self.timeout = old

    @contextmanager
    def with_config(self, **overrides: Any):
        """Temporarily override multiple configuration values.

        Supported keys: ``timeout``, ``retry_count``, ``retry_delay``.
        """
        snapshot = {}
        for key in ("timeout", "retry_count", "retry_delay"):
            if key in overrides:
                snapshot[key] = getattr(self, key)
                setattr(self, key, overrides[key])
        try:
            yield self
        finally:
            for key, value in snapshot.items():
                setattr(self, key, value)

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def cache_set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store a value in the context cache."""
        self._cache.set(key, value, ttl)

    def cache_get(self, key: str) -> Optional[Any]:
        """Retrieve a value from the context cache."""
        return self._cache.get(key)

    def cache_clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def register_hook(self, event: str, callback: HookCallback) -> None:
        """Register a lifecycle hook.

        Args:
            event: Event name (``pre_find``, ``post_find``, ``pre_action``,
                ``post_action``, ``on_error``).
            callback: Callable that receives ``**kwargs``.
        """
        self._hooks.register(event, callback)

    def trigger_hook(self, event: str, **kwargs: Any) -> None:
        """Fire all listeners for *event*."""
        self._hooks.trigger(event, **kwargs)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _resolve_value(self, key: str, default: Any) -> Any:
        """Resolve a value considering temporary overrides."""
        return self._overrides.get(key, default)

    def __repr__(self) -> str:
        return (
            f"<AutomationContext timeout={self.timeout}s "
            f"retries={self.retry_count} driver={self.driver}>"
        )
