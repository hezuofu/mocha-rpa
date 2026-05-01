"""Sequential and error-handling flow primitives — ``sequence`` and ``try_catch``.

Provides structured execution of ordered actions and structured error recovery.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional, Tuple, Type, Union

logger = logging.getLogger("rpa.flow")


# ======================================================================
# sequence
# ======================================================================

class _SequenceBuilder:
    """Fluent builder for running actions in order.

    Usage::

        sequence(
            lambda: Find().name("Username").do(lambda e: e.send_keys("admin")),
            lambda: Find().name("Password").do(lambda e: e.send_keys("pass")),
            lambda: Find().name("Login").do(lambda e: e.click()),
        )
    """

    __slots__ = ("_actions",)

    def __init__(self, *actions: Callable[[], Any]) -> None:
        self._actions = list(actions)

    def then(self, action: Callable[[], Any]) -> _SequenceBuilder:
        """Append another action.  Returns a new builder (immutable)."""
        return _SequenceBuilder(*self._actions, action)

    def run(self) -> List[Any]:
        """Execute all actions in order.  Returns list of results."""
        return [a() for a in self._actions]

    def __call__(self) -> List[Any]:
        return self.run()


def sequence(*actions: Callable[[], Any]) -> _SequenceBuilder:
    """Execute a series of actions sequentially.

    Usage::

        sequence(
            lambda: print("step 1"),
            lambda: print("step 2"),
        ).run()

        # Or use .then() to extend:
        seq = sequence(open_app).then(login).then(do_work)
        seq.run()
    """
    return _SequenceBuilder(*actions)


# ======================================================================
# try_catch
# ======================================================================

class _TryBuilder:
    """Fluent builder for try/catch/finally.

    Usage::

        try_catch(lambda: Find().name("Risky").do(lambda e: e.click()))
            .catch(ElementNotFound, lambda e: print("Not found"))
            .catch(Exception, lambda e: print("Other:", e))
            .finally_(lambda: cleanup())
    """

    __slots__ = ("_action", "_catchers", "_finally")

    def __init__(self, action: Callable[[], Any]) -> None:
        self._action = action
        self._catchers: List[Tuple[Type[BaseException], Callable[[BaseException], Any]]] = []
        self._finally: Optional[Callable[[], Any]] = None

    def catch(
        self,
        exc_type: Type[BaseException],
        handler: Callable[[BaseException], Any],
    ) -> _TryBuilder:
        """Register a handler for *exc_type* (and its subclasses).

        Multiple catches are evaluated in registration order (first match wins).
        """
        self._catchers.append((exc_type, handler))
        return self

    def finally_(self, action: Callable[[], Any]) -> _TryBuilder:
        """Register a finally block."""
        self._finally = action
        return self

    def run(self) -> Any:
        """Execute the try/catch/finally block.  Returns the action result
        (or handler result if caught)."""
        try:
            return self._action()
        except BaseException as exc:
            for exc_type, handler in self._catchers:
                if isinstance(exc, exc_type):
                    logger.debug("Caught %s: %s", type(exc).__name__, exc)
                    return handler(exc)
            raise
        finally:
            if self._finally:
                self._finally()

    def __call__(self) -> Any:
        return self.run()


def try_catch(action: Callable[[], Any]) -> _TryBuilder:
    """Wrap an action with structured error handling.

    Usage::

        try_catch(lambda: risky_operation())
            .catch(ValueError, lambda e: print("Bad value"))
            .catch(Exception, lambda e: print("Unexpected:", e))
            .finally_(lambda: print("Done"))
            .run()
    """
    return _TryBuilder(action)
