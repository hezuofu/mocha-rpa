"""Asynchronous wrappers for the RPA framework.

Provides async equivalents of FindBuilder, retry, and concurrency helpers
so that RPA operations can be used within ``asyncio``-based applications
without blocking the event loop.
"""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Awaitable, Callable, List, Optional, TypeVar

from mocharpa.builder.find_builder import FindBuilder
from mocharpa.core.element import Element
from mocharpa.core.context import AutomationContext

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])


# ======================================================================
# Async runner for blocking code
# ======================================================================

def run_async(func: Callable[..., T], *args: Any, **kwargs: Any) -> Awaitable[T]:
    """Run a synchronous function in a thread pool, returning an awaitable.

    Usage::

        result = await run_async(Find().name("X").do, lambda e: e.click())
    """
    return asyncio.get_event_loop().run_in_executor(
        None,
        functools.partial(func, *args, **kwargs),
    )


async def gather(*coros: Awaitable) -> List[Any]:
    """Run multiple coroutines concurrently and return their results.

    Thin wrapper around ``asyncio.gather`` for convenience.
    """
    return await asyncio.gather(*coros)


# ======================================================================
# async_retry
# ======================================================================

def async_retry(
    max_retries: int = 3,
    delay: float = 0.5,
    *,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_error: Optional[Callable[[Exception, int], Optional[Awaitable[None]]]] = None,
) -> Callable[[F], F]:
    """Async version of :func:`rpa.functional.utils.retry`.

    The decorated function must be a coroutine (``async def``).
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[Exception] = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if on_error:
                        result = on_error(exc, attempt + 1)
                        if result is not None:
                            await result
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


# ======================================================================
# AsyncFindBuilder
# ======================================================================

class AsyncFindBuilder:
    """Async wrapper around :class:`FindBuilder`.

    Each terminal method delegates the underlying blocking operation to
    a thread pool, returning an awaitable.

    Usage::

        async def login():
            builder = AsyncFind(AsyncFindBuilder())
            await builder.name("Username").do_async(lambda e: e.send_keys("user"))
    """

    __slots__ = ("_sync_builder",)

    def __init__(self, sync_builder: Optional[FindBuilder] = None) -> None:
        self._sync_builder = sync_builder or FindBuilder()

    # -- locator building (synchronous, returns new AsyncFindBuilder) ------

    def _clone(self, sync: FindBuilder) -> AsyncFindBuilder:
        inst = AsyncFindBuilder()
        inst._sync_builder = sync
        return inst

    def name(self, value: str, exact: bool = True) -> AsyncFindBuilder:
        return self._clone(self._sync_builder.name(value, exact))

    def id(self, value: str) -> AsyncFindBuilder:
        return self._clone(self._sync_builder.id(value))

    def type(self, value: str) -> AsyncFindBuilder:
        return self._clone(self._sync_builder.type(value))

    def class_name(self, value: str) -> AsyncFindBuilder:
        return self._clone(self._sync_builder.class_name(value))

    def within(self, timeout: float) -> AsyncFindBuilder:
        return self._clone(self._sync_builder.within(timeout))

    def with_context(self, context: AutomationContext) -> AsyncFindBuilder:
        return self._clone(self._sync_builder.with_context(context))

    def all(self) -> AsyncFindBuilder:
        return self._clone(self._sync_builder.all())

    @property
    def then(self) -> AsyncFindBuilder:
        return self._clone(self._sync_builder.then)

    # -- async terminal operations ----------------------------------------

    async def do_async(self, action: Callable, *args: Any) -> Any:
        return await run_async(self._sync_builder.do, action, *args)

    async def get_async(self) -> Optional[Element]:
        return await run_async(self._sync_builder.get)

    async def get_all_async(self) -> List[Element]:
        return await run_async(self._sync_builder.get_all)

    async def wait_until_async(
        self,
        condition: Any = "is_visible",
        timeout: Optional[float] = None,
        interval: float = 0.3,
    ) -> Element:
        return await run_async(
            self._sync_builder.wait_until,
            condition,
            timeout,
            interval,
        )

    async def exists_async(self) -> bool:
        return await run_async(self._sync_builder.exists)


def AsyncFind() -> AsyncFindBuilder:
    """Create a new :class:`AsyncFindBuilder`."""
    return AsyncFindBuilder()
