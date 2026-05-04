"""Declarative find builder — fluent API for locating and interacting with UI elements.

Provides the :class:`FindBuilder` class whose instances are created via the
convenience function :func:`Find`.
"""

from __future__ import annotations

import time
from typing import Any, Callable, List, Optional, Union, TYPE_CHECKING

from mocharpa.core.locator import (
    Locator,
    LocatorChain,
    LocatorFactory,
    LocatorSpec,
    ById,
    ByName,
    ByType,
    ByClass,
    ByRegion,
    ByImage,
)
from mocharpa.core.element import Element, Rectangle
from mocharpa.core.exceptions import ElementNotFound, ActionNotPossible, TimeoutError
from mocharpa.core.context import AutomationContext
from mocharpa.core.driver import DriverAdapter, DriverNotConnectedError
from mocharpa.events import ElementFoundEvent, ElementNotFoundEvent


class FindBuilder:
    """Fluent builder for locating UI elements and performing actions on them.

    Usage::

        Find().name("Submit").type("Button").do(lambda e: e.click())

        Find().id("input1").within(5).get()

    The builder is immutable — each chained call returns a new instance.
    """

    __slots__ = (
        "_locators",
        "_timeout",
        "_context",
        "_find_all",
        "_wait_condition",
    )

    def __init__(
        self,
        locators: tuple[Locator, ...] = (),
        *,
        timeout: Optional[float] = None,
        context: Optional[AutomationContext] = None,
        find_all: bool = False,
    ) -> None:
        self._locators = locators
        self._timeout = timeout
        self._context = context
        self._find_all = find_all

    # ------------------------------------------------------------------
    # Locator building methods (return new builder)
    # ------------------------------------------------------------------

    def name(self, value: str, exact: bool = True) -> FindBuilder:
        """Add a ByName locator."""
        return self._push(ByName(value=value, exact=exact))

    def id(self, value: str) -> FindBuilder:
        """Add a ById locator."""
        return self._push(ById(value=value))

    def type(self, value: str) -> FindBuilder:
        """Add a ByType locator."""
        return self._push(ByType(value=value))

    def class_name(self, value: str) -> FindBuilder:
        """Add a ByClass locator."""
        return self._push(ByClass(value=value))

    def region(
        self, left: int, top: int, width: int, height: int
    ) -> FindBuilder:
        """Add a ByRegion locator."""
        return self._push(ByRegion(Rectangle(left, top, width, height)))

    def image(self, path: str, confidence: float = 0.85) -> FindBuilder:
        """Add a ByImage locator."""
        return self._push(ByImage(path=path, confidence=confidence))

    def locator(self, spec: LocatorSpec) -> FindBuilder:
        """Add any locator from a string, dict, or Locator instance."""
        return self._push(LocatorFactory.create(spec))

    # ------------------------------------------------------------------
    # Separator for chained searches ("Find().name('X').then.type('Y')")
    # ------------------------------------------------------------------

    @property
    def then(self) -> FindBuilder:
        """Begin a new search context while keeping the current timeout/context.

        Usage::

            Find().name("Login").then.type("Window").do(lambda w: w.click())
        """
        return FindBuilder(
            timeout=self._timeout,
            context=self._context,
        )

    # ------------------------------------------------------------------
    # Configuration methods
    # ------------------------------------------------------------------

    def within(self, timeout: float) -> FindBuilder:
        """Set the search timeout (seconds)."""
        return FindBuilder(
            self._locators,
            timeout=timeout,
            context=self._context,
        )

    def with_context(self, context: AutomationContext) -> FindBuilder:
        """Explicitly bind to an :class:`AutomationContext`."""
        return FindBuilder(
            self._locators,
            timeout=self._timeout,
            context=context,
            find_all=self._find_all,
        )

    def all(self) -> FindBuilder:
        """Switch to multi-element mode — ``.do()`` will receive a list."""
        return FindBuilder(
            self._locators,
            timeout=self._timeout,
            context=self._context,
            find_all=True,
        )

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _push(self, locator: Locator) -> FindBuilder:
        """Return a new builder with *locator* appended."""
        if self._locators:
            chain = LocatorChain(self._locators + (locator,))
            return FindBuilder(
                (chain,),
                timeout=self._timeout,
                context=self._context,
                find_all=self._find_all,
            )
        return FindBuilder(
            (locator,),
            timeout=self._timeout,
            context=self._context,
            find_all=self._find_all,
        )

    def _resolve_context(self) -> AutomationContext:
        """Return the effective context."""
        return self._context or AutomationContext.get_current()

    def _resolve_timeout(self) -> float:
        """Return the effective timeout."""
        if self._timeout is not None:
            return self._timeout
        return self._resolve_context().timeout

    def _get_driver(self) -> DriverAdapter:
        """Return the driver from the active context, or raise."""
        ctx = self._resolve_context()
        driver = ctx.driver
        if driver is None:
            raise DriverNotConnectedError("no driver set on context")
        if not driver.is_connected:
            raise DriverNotConnectedError(driver.name)
        return driver

    @property
    def _locator(self) -> Optional[Locator]:
        """The compiled locator representing all constraints."""
        if not self._locators:
            return None
        if len(self._locators) == 1:
            return self._locators[0]
        return LocatorChain(self._locators)

    # ------------------------------------------------------------------
    # Terminal operations
    # ------------------------------------------------------------------

    def get(self) -> Optional[Element]:
        """Find and return a single element, or ``None`` if not found."""
        if not self._locators:
            return None

        ctx = self._resolve_context()
        timeout = self._resolve_timeout()
        driver = self._get_driver()
        locator = self._locator

        ctx.trigger_hook("pre_find", locator=locator, timeout=timeout)
        result = driver.find_element(locator, timeout=timeout)
        ctx.trigger_hook("post_find", locator=locator, element=result)
        if result is not None:
            ctx.event_bus.emit(ElementFoundEvent(locator=locator, element=result, timeout=timeout))
        else:
            ctx.event_bus.emit(ElementNotFoundEvent(locator=locator, timeout=timeout))
        return result

    def get_all(self) -> List[Element]:
        """Find and return all matching elements."""
        if not self._locators:
            return []

        ctx = self._resolve_context()
        timeout = self._resolve_timeout()
        driver = self._get_driver()
        locator = self._locator

        ctx.trigger_hook("pre_find", locator=locator, timeout=timeout)
        results = driver.find_elements(locator, timeout=timeout)
        ctx.trigger_hook("post_find", locator=locator, element_count=len(results))
        return results

    def do(self, action: Callable, *args: Any) -> Any:
        """Find element(s) and execute *action* on the result.

        *action* receives a single :class:`Element` (or ``list[Element]`` when
        preceded by ``.all()``) as its first positional argument.

        Raises:
            ElementNotFound: If no element matched within the timeout.
        """
        ctx = self._resolve_context()

        if self._find_all:
            elements = self.get_all()
            ctx.trigger_hook("pre_action", action=action, elements=elements)
            result = action(elements, *args)
        else:
            element = self.get()
            if element is None:
                locator = self._locator
                timeout = self._resolve_timeout()
                raise ElementNotFound(
                    locator=locator,
                    timeout=timeout,
                )
            ctx.trigger_hook("pre_action", action=action, element=element)
            result = action(element, *args)

        ctx.trigger_hook("post_action", action=action, result=result)
        return result

    def wait_until(
        self,
        condition: Union[Callable[[Element], bool], str] = "is_visible",
        timeout: Optional[float] = None,
        interval: float = 0.3,
    ) -> Element:
        """Wait for an element to satisfy *condition*.

        *condition* can be a callable ``(Element) -> bool`` or a method name
        string like ``"is_visible"``, ``"is_enabled"``.

        Raises:
            TimeoutError: If the condition is not satisfied within *timeout*.
        """
        if timeout is None:
            timeout = self._resolve_timeout()

        driver = self._get_driver()
        locator = self._locator
        if locator is None:
            raise ValueError("No locators specified")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            element = driver.find_element(locator, timeout=interval)
            if element is not None:
                ok = self._evaluate_condition(element, condition)
                if ok:
                    return element
            time.sleep(interval)

        raise TimeoutError(
            f"Condition '{condition}' not met within {timeout}s",
            timeout=timeout,
        )

    @staticmethod
    def _evaluate_condition(
        element: Element,
        condition: Union[Callable[[Element], bool], str],
    ) -> bool:
        """Evaluate a human-readable condition."""
        if callable(condition):
            return condition(element)
        # method name string
        method = getattr(element, condition, None)
        if method is None:
            raise ValueError(f"Unknown condition method: {condition}")
        return bool(method())

    def exists(self) -> bool:
        """Quick check: does any matching element exist?  Non-blocking."""
        if not self._locators:
            return False
        return self.get() is not None

    # ------------------------------------------------------------------
    # Debugging
    # ------------------------------------------------------------------

    def describe(self) -> str:
        """Return a human-readable description of the search plan."""
        loc_repr = (
            " > ".join(repr(l) for l in self._locators)
            if self._locators
            else "<empty>"
        )
        timeout = self._resolve_timeout()
        return f"Find({loc_repr}) within={timeout}s all={self._find_all}"

    def __repr__(self) -> str:
        return self.describe()


# ======================================================================
# Convenience entry point
# ======================================================================

def Find() -> FindBuilder:
    """Create a new :class:`FindBuilder` instance.

    This is the primary entry-point for the declarative API::

        Find().name("OK").do(lambda e: e.click())

    Returns:
        A fresh :class:`FindBuilder`.
    """
    return FindBuilder()
