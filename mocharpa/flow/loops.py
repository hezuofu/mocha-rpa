"""Looping primitives — ``for_each``, ``while_``, ``until_``, ``repeat``.

Integrates with :class:`FindBuilder` results, condition helpers, and
the broader RPA flow system.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable, List, Optional, Union

from mocharpa.flow.conditions import Condition, _ensure_callable
from mocharpa.core.exceptions import TimeoutError


# ======================================================================
# for_each
# ======================================================================

class _ForEachBuilder:
    """Fluent builder for iterating over items.

    Usage::

        for_each(["a", "b", "c"]).do(lambda item: print(item))

        for_each(Find().name("Row").get_all()).do(lambda el: el.click())
    """

    __slots__ = ("_items",)

    def __init__(self, items: Union[Iterable, Callable[[], Iterable]]) -> None:
        self._items = items

    def do(self, action: Callable[[Any], Any]) -> List[Any]:
        """Execute *action* for every item in the collection.

        *action* receives the item as its first argument.
        Returns a list of results.
        """
        items = self._items() if callable(self._items) else self._items
        return [action(item) for item in items]

    def do_with_index(self, action: Callable[[int, Any], Any]) -> List[Any]:
        """Like :meth:`do`, but *action* receives ``(index, item)``."""
        items = self._items() if callable(self._items) else self._items
        return [action(i, item) for i, item in enumerate(items)]


class for_each:
    """Iterate over a collection.

    Supports lists, generators, and lazy evaluation::

        # Static list
        for_each([1, 2, 3]).do(lambda n: print(n))

        # Found elements
        for_each(lambda: Find().name("Row").get_all())
            .do(lambda el: el.click())

        # With index
        for_each(users).do_with_index(lambda i, u: print(i, u))
    """

    def __new__(cls, items: Union[Iterable, Callable[[], Iterable]]) -> _ForEachBuilder:
        return _ForEachBuilder(items)


# ======================================================================
# while_ / until_
# ======================================================================

class _LoopBuilder:
    """Fluent builder for while/until loops.

    Usage::

        while_(exists(Find().name("Loading")))
            .do(lambda: time.sleep(0.5))
    """

    __slots__ = ("_condition", "_max_iterations", "_timeout")

    def __init__(
        self,
        condition: Condition,
        *,
        max_iterations: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._condition = condition
        self._max_iterations = max_iterations
        self._timeout = timeout

    def do(self, action: Callable[[], Any]) -> None:
        """Execute *action* repeatedly while the condition holds."""
        check = _ensure_callable(self._condition)
        deadline = time.monotonic() + self._timeout if self._timeout else None
        iteration = 0

        while True:
            if self._max_iterations is not None and iteration >= self._max_iterations:
                break
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(
                    f"Loop timed out after {self._timeout}s",
                    timeout=self._timeout,
                )
            if not check():
                break
            action()
            iteration += 1


class _UntilBuilder:
    """Fluent builder for until loops (execute at least once).

    Usage::

        until_(eq(retries, 3))
            .do(lambda: attempt_login())
    """

    __slots__ = ("_condition", "_max_iterations", "_interval")

    def __init__(
        self,
        condition: Condition,
        *,
        max_iterations: Optional[int] = None,
        interval: float = 0.0,
    ) -> None:
        self._condition = condition
        self._max_iterations = max_iterations
        self._interval = interval

    def do(self, action: Callable[[], Any]) -> None:
        """Execute *action* at least once, repeating until *condition* is True.

        Equivalent to ``do { ... } while (!condition)``.
        """
        check = _ensure_callable(self._condition)
        iteration = 0

        while True:
            action()
            iteration += 1
            if self._max_iterations is not None and iteration >= self._max_iterations:
                break
            if check():
                break
            if self._interval > 0:
                time.sleep(self._interval)


class while_:
    """Loop while a condition is True (can execute zero times).

    Usage::

        while_(exists(Find().name("Spinner")))
            .do(lambda: time.sleep(0.2))

        while_(lt(counter, 10), max_iterations=100)
            .do(lambda: increment())
    """

    def __new__(
        cls,
        condition: Condition,
        *,
        max_iterations: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> _LoopBuilder:
        return _LoopBuilder(condition, max_iterations=max_iterations, timeout=timeout)


class until_:
    """Loop until a condition becomes True (executes at least once).

    Usage::

        until_(eq(status, "ready"), max_iterations=10, interval=0.5)
            .do(lambda: check_status())
    """

    def __new__(
        cls,
        condition: Condition,
        *,
        max_iterations: Optional[int] = None,
        interval: float = 0.0,
    ) -> _UntilBuilder:
        return _UntilBuilder(
            condition, max_iterations=max_iterations, interval=interval
        )


# ======================================================================
# repeat
# ======================================================================

class _RepeatBuilder:
    """Fluent builder for fixed-count repetition.

    Usage::

        repeat(5).do(lambda i: print(f"Iteration {i}"))
    """

    __slots__ = ("_count",)

    def __init__(self, count: int) -> None:
        if count < 0:
            raise ValueError(f"repeat count must be >= 0, got {count}")
        self._count = count

    def do(self, action: Callable[[int], Any]) -> List[Any]:
        """Execute *action* *count* times.

        *action* receives the zero-based iteration index.
        Returns a list of results.
        """
        return [action(i) for i in range(self._count)]


class repeat:
    """Repeat an action a fixed number of times.

    Usage::

        repeat(3).do(lambda i: print(f"Attempt {i+1}"))
    """

    def __new__(cls, count: int) -> _RepeatBuilder:
        return _RepeatBuilder(count)
