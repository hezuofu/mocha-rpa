"""Functional programming utilities for building robust automation workflows.

Provides composable higher-order functions: retry logic, function pipelines,
safe execution, side-effect tapping, context injection, and polling.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Optional, TypeVar

from rpabot.core.context import AutomationContext

F = TypeVar("F", bound=Callable[..., Any])
T = TypeVar("T")


# ======================================================================
# retry
# ======================================================================

def retry(
    max_retries: int = 3,
    delay: float = 0.5,
    *,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_error: Optional[Callable[[Exception, int], None]] = None,
) -> Callable[[F], F]:
    """Decorator / wrapper that retries a function on failure.

    Args:
        max_retries: Maximum number of attempts.
        delay: Seconds between retries.
        exceptions: Exception types to catch.
        on_error: Optional callback ``(exception, attempt_number)`` invoked on
            each failure (useful for logging).

    Can be used as a decorator or applied directly::

        @retry(max_retries=3, delay=1.0)
        def click_save():
            Find().name("Save").do(lambda e: e.click())

        # Or as a wrapper:
        result = retry(3, 0.5)(unstable_func)()
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[Exception] = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if on_error:
                        on_error(exc, attempt + 1)
                    if attempt < max_retries - 1:
                        time.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


# ======================================================================
# pipe
# ======================================================================

def pipe(*funcs: Callable) -> Callable:
    """Compose functions into a left-to-right pipeline.

    ``pipe(f, g, h)(x)`` is equivalent to ``h(g(f(x)))``.

    Usage::

        process = pipe(
            lambda x: x.upper(),
            lambda s: s.replace(" ", "_"),
        )
        assert process("hello world") == "HELLO_WORLD"
    """
    if not funcs:
        return lambda x: x

    def composed(value: Any) -> Any:
        for func in funcs:
            value = func(value)
        return value

    return composed


# ======================================================================
# tap
# ======================================================================

def tap(func: Callable[[T], Any]) -> Callable[[T], T]:
    """Execute *func* as a side-effect while passing through the original value.

    Useful for logging or other read-only operations inside a ``pipe``::

        pipeline = pipe(
            Find().name("Input").do,
            tap(lambda e: print("Found:", e.name)),
            lambda e: e.send_keys("hello"),
        )
    """

    def wrapper(value: T) -> T:
        func(value)
        return value

    return wrapper


# ======================================================================
# maybe
# ======================================================================

def maybe(func: Callable[..., T]) -> Callable[..., Optional[T]]:
    """Wrap *func* so that it returns ``None`` on failure instead of raising.

    Usage::

        safe_click = maybe(lambda: Find().name("OptionalBtn").do(lambda e: e.click()))
        safe_click()  # returns None if the button doesn't exist
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Optional[T]:
        try:
            return func(*args, **kwargs)
        except Exception:
            return None

    return wrapper


# ======================================================================
# with_context
# ======================================================================

def with_context(ctx: AutomationContext) -> Callable[[F], F]:
    """Decorator that injects an :class:`AutomationContext` into every call.

    The function must accept a keyword argument ``context``.

    Usage::

        @with_context(AutomationContext(timeout=5))
        def do_stuff(*, context):
            Find().with_context(context).name("X").do(...)
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("context", ctx)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


# ======================================================================
# wait_until
# ======================================================================

def wait_until(
    condition: Callable[[], bool],
    timeout: float = 10.0,
    interval: float = 0.3,
    *,
    description: str = "condition",
) -> None:
    """Poll *condition* until it returns ``True`` or *timeout* elapses.

    Args:
        condition: A no-argument callable returning ``bool``.
        timeout: Maximum wait time (seconds).
        interval: Polling interval (seconds).
        description: Human-readable label for error messages.

    Raises:
        TimeoutError: From :mod:`rpa.core.exceptions`.
    """
    from rpabot.core.exceptions import TimeoutError as RpaTimeoutError

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(interval)
    raise RpaTimeoutError(f"wait_until '{description}' timed out after {timeout}s")


# ======================================================================
# ignore_err
# ======================================================================

def ignore_err(
    func: Callable[..., T],
    default: T = None,
    *,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[..., Optional[T]]:
    """Wrap *func* to return *default* on error.

    Similar to ``maybe`` but with configurable fallback value.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Optional[T]:
        try:
            return func(*args, **kwargs)
        except exceptions:
            return default

    return wrapper
