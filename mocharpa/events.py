"""Typed event system for the RPA framework.

Provides a lightweight publish/subscribe event bus with support for:

* Typed event objects with propagation control
* Priority-ordered synchronous subscribers
* Async subscribers (``emit_async``)
* One-shot subscribers (``once``)
* Thread-safe registration and dispatch

Usage::

    from mocharpa.events import EventBus, PipelineStartEvent, StepEndEvent

    bus = EventBus()

    @bus.on(PipelineStartEvent)
    def on_start(event: PipelineStartEvent):
        print(f"Pipeline '{event.pipeline_name}' starting")

    bus.emit(PipelineStartEvent(pipeline_name="report"))
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union

logger = logging.getLogger("rpa.events")

T = TypeVar("T", bound="Event")
EventHandler = Callable[..., Any]
AsyncEventHandler = Callable[..., Any]  # coroutine


# ======================================================================
# Event base
# ======================================================================

class Event:
    """Base class for all framework events.

    Attributes:
        timestamp: Unix timestamp when the event was created.
        source: Optional reference to the object that emitted the event.

    Propagation control (inspired by DOM events):
        :meth:`stop_propagation` — remaining subscribers are skipped.
        :meth:`prevent_default` — hints that the default action should not
            be performed (checked by the emitter after dispatch).
    """

    def __init__(self, *, source: Any = None) -> None:
        self.timestamp: float = time.time()
        self.source: Any = source
        self._stopped: bool = False
        self._prevented: bool = False

    def stop_propagation(self) -> None:
        """Prevent remaining subscribers from receiving this event."""
        self._stopped = True

    def prevent_default(self) -> None:
        """Signal that the default action should be skipped."""
        self._prevented = True

    @property
    def is_stopped(self) -> bool:
        return self._stopped

    @property
    def is_default_prevented(self) -> bool:
        return self._prevented


# ======================================================================
# Pipeline events
# ======================================================================

class PipelineEvent(Event):
    """Base for pipeline lifecycle events."""

    def __init__(self, pipeline_name: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.pipeline_name: str = pipeline_name


class PipelineStartEvent(PipelineEvent):
    """Emitted when :meth:`Pipeline.run` is called."""

    def __init__(
        self,
        pipeline_name: str = "",
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(pipeline_name=pipeline_name, **kwargs)
        self.data: Optional[Dict[str, Any]] = data


class PipelineEndEvent(PipelineEvent):
    """Emitted when :meth:`Pipeline.run` returns."""

    def __init__(
        self,
        pipeline_name: str = "",
        success: bool = False,
        elapsed: float = 0.0,
        step_count: int = 0,
        error_count: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pipeline_name=pipeline_name, **kwargs)
        self.success: bool = success
        self.elapsed: float = elapsed
        self.step_count: int = step_count
        self.error_count: int = error_count


class StepEvent(Event):
    """Base for step lifecycle events."""

    def __init__(self, step_name: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.step_name: str = step_name


class StepStartEvent(StepEvent):
    """Emitted before a step executes."""

    def __init__(self, step_name: str = "", **kwargs: Any) -> None:
        super().__init__(step_name=step_name, **kwargs)


class StepEndEvent(StepEvent):
    """Emitted after a step completes successfully."""

    def __init__(
        self,
        step_name: str = "",
        output: Any = None,
        elapsed: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(step_name=step_name, **kwargs)
        self.output: Any = output
        self.elapsed: float = elapsed


class StepSkippedEvent(StepEvent):
    """Emitted when a step's condition evaluates to False."""

    def __init__(self, step_name: str = "", **kwargs: Any) -> None:
        super().__init__(step_name=step_name, **kwargs)


class StepErrorEvent(StepEvent):
    """Emitted when a step fails (both ``continue_on_error`` and unhandled)."""

    def __init__(
        self,
        step_name: str = "",
        error: str = "",
        elapsed: float = 0.0,
        unhandled: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(step_name=step_name, **kwargs)
        self.error: str = error
        self.elapsed: float = elapsed
        self.unhandled: bool = unhandled


# ======================================================================
# Driver / element events
# ======================================================================

class DriverConnectEvent(Event):
    """Emitted after a driver successfully connects."""

    def __init__(self, driver_name: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.driver_name: str = driver_name


class DriverDisconnectEvent(Event):
    """Emitted before a driver disconnects."""

    def __init__(self, driver_name: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.driver_name: str = driver_name


class ElementFoundEvent(Event):
    """Emitted when an element is located."""

    def __init__(
        self,
        locator: Any = None,
        element: Any = None,
        timeout: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.locator: Any = locator
        self.element: Any = element
        self.timeout: float = timeout


class ElementNotFoundEvent(Event):
    """Emitted when an element is NOT found within the timeout."""

    def __init__(
        self,
        locator: Any = None,
        timeout: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.locator: Any = locator
        self.timeout: float = timeout


class ActionEvent(Event):
    """Emitted around element actions (click, send_keys, etc.)."""

    def __init__(
        self,
        action: str = "",
        element: Any = None,
        args: tuple = (),
        result: Any = None,
        error: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.action: str = action
        self.element: Any = element
        self.args: tuple = args
        self.result: Any = result
        self.error: Optional[str] = error


# ======================================================================
# Plugin events
# ======================================================================

class PluginRegisteredEvent(Event):
    """Emitted when a plugin is registered with :class:`PluginManager`."""

    def __init__(self, plugin_name: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.plugin_name: str = plugin_name


class PluginInitializedEvent(Event):
    """Emitted after ``plugin.initialize()`` succeeds."""

    def __init__(self, plugin_name: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.plugin_name: str = plugin_name


# ======================================================================
# EventBus
# ======================================================================

class EventBus:
    """Lightweight publish/subscribe event dispatcher.

    Subscribers are called in priority order (higher = earlier).  Handlers
    receive the event object as their first positional argument.

    Usage::

        bus = EventBus()

        bus.subscribe(PipelineStartEvent, lambda e: print(e.pipeline_name))
        bus.emit(PipelineStartEvent(pipeline_name="hello"))

        # Decorator style
        @bus.on(StepEndEvent)
        def log_step(event):
            print(f"Done: {event.step_name}")

        # Async
        await bus.emit_async(StepStartEvent(step_name="login"))

        # One-shot
        bus.once(PipelineEndEvent, lambda e: print("Pipeline done"))
    """

    def __init__(self) -> None:
        self._subscribers: Dict[Type[Event], List[tuple[int, EventHandler]]] = {}
        self._async_subscribers: Dict[Type[Event], List[tuple[int, AsyncEventHandler]]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Subscribe
    # ------------------------------------------------------------------

    def subscribe(
        self,
        event_type: Type[T],
        handler: Callable[[T], Any],
        *,
        priority: int = 0,
    ) -> EventHandler:
        """Register a synchronous *handler* for *event_type*.

        Handlers with higher *priority* are called first.  Return the
        handler for use with :meth:`unsubscribe`.
        """
        with self._lock:
            subs = self._subscribers.setdefault(event_type, [])
            subs.append((priority, handler))
            subs.sort(key=lambda x: -x[0])
        return handler

    def subscribe_async(
        self,
        event_type: Type[T],
        handler: Callable[[T], Any],
        *,
        priority: int = 0,
    ) -> AsyncEventHandler:
        """Register a coroutine *handler* for *event_type*.

        Called by :meth:`emit_async`.  Sync subscribers are NOT invoked
        during async emission.
        """
        with self._lock:
            subs = self._async_subscribers.setdefault(event_type, [])
            subs.append((priority, handler))
            subs.sort(key=lambda x: -x[0])
        return handler

    def on(
        self,
        event_type: Type[T],
        *,
        priority: int = 0,
    ) -> Callable[[EventHandler], EventHandler]:
        """Decorator: register a sync handler for *event_type*.

        Usage::

            @bus.on(PipelineStartEvent)
            def handle_start(event):
                print(event.pipeline_name)
        """
        def decorator(handler: EventHandler) -> EventHandler:
            self.subscribe(event_type, handler, priority=priority)
            return handler
        return decorator

    def once(
        self,
        event_type: Type[T],
        handler: Callable[[T], Any],
        *,
        priority: int = 0,
    ) -> None:
        """Register a one-shot handler — auto-unsubscribes after first call."""
        def _wrapper(event: T) -> Any:
            self.unsubscribe(event_type, _wrapper)
            return handler(event)
        self.subscribe(event_type, _wrapper, priority=priority)

    # ------------------------------------------------------------------
    # Unsubscribe
    # ------------------------------------------------------------------

    def unsubscribe(
        self,
        event_type: Type[T],
        handler: EventHandler,
    ) -> None:
        """Remove a previously registered *handler*."""
        with self._lock:
            subs = self._subscribers.get(event_type, [])
            self._subscribers[event_type] = [
                (p, h) for (p, h) in subs if h is not handler
            ]

    def clear(self) -> None:
        """Remove all subscribers."""
        with self._lock:
            self._subscribers.clear()
            self._async_subscribers.clear()

    # ------------------------------------------------------------------
    # Emit
    # ------------------------------------------------------------------

    def emit(self, event: Event) -> Event:
        """Dispatch *event* to all matching sync subscribers.

        Dispatching walks the MRO so subscribers of :class:`Event` receive
        all events, subscribers of :class:`PipelineEvent` receive all
        pipeline events, etc.

        Returns the event (so callers can check ``is_default_prevented``).
        """
        for cls in type(event).__mro__:
            if cls is object:
                break
            with self._lock:
                subs = list(self._subscribers.get(cls, ()))
            for _pri, handler in subs:
                try:
                    handler(event)
                except Exception:
                    logger.exception("Event handler %s failed for %s", handler, cls.__name__)
                if event.is_stopped:
                    break
            if event.is_stopped:
                break
        return event

    async def emit_async(self, event: Event) -> Event:
        """Dispatch *event* to async subscribers.

        Sync subscribers are NOT invoked — use :meth:`subscribe_async` to
        register coroutine handlers.
        """
        for cls in type(event).__mro__:
            if cls is object:
                break
            with self._lock:
                subs = list(self._async_subscribers.get(cls, ()))
            for _pri, handler in subs:
                try:
                    result = handler(event)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.exception("Async event handler %s failed", handler)
                if event.is_stopped:
                    break
            if event.is_stopped:
                break
        return event

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def subscriber_count(self, event_type: Optional[Type[Event]] = None) -> int:
        """Return the number of registered subscribers.

        If *event_type* is None, returns the total across all event types.
        """
        with self._lock:
            if event_type is not None:
                return len(self._subscribers.get(event_type, []))
            return sum(len(s) for s in self._subscribers.values())
