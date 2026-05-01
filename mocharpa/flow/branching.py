"""Conditional branching primitives — ``if_`` and ``switch_``.

These provide RPA-friendly control flow that integrates with
:class:`FindBuilder` results and the condition helpers from
:mod:`rpa.flow.conditions`.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Union, List

from mocharpa.flow.conditions import Condition, _ensure_callable


# ======================================================================
# if_ / else_
# ======================================================================

class _Branch:
    """Internal: a single branch of an if_ chain."""

    __slots__ = ("_condition", "_action", "_next_branch")

    def __init__(
        self,
        condition: Condition,
        action: Callable[[], Any],
        next_branch: Optional[_Branch] = None,
    ) -> None:
        self._condition = condition
        self._action = action
        self._next_branch = next_branch

    def _evaluate(self) -> Any:
        check = _ensure_callable(self._condition)
        if check():
            return self._action()
        if self._next_branch is not None:
            return self._next_branch._evaluate()
        return None


class _IfBuilder:
    """Fluent builder for if/elif/else chains.

    Usage::

        if_(exists(Find().name("OK")))
            .then(lambda: print("found"))
            .else_(lambda: print("not found"))
    """

    __slots__ = ("_condition", "_head", "_tail")

    def __init__(self, condition: Condition) -> None:
        self._head: Optional[_Branch] = None
        self._tail: Optional[_Branch] = None
        self._condition = condition

    def then(self, action: Callable[[], Any]) -> _IfBuilder:
        branch = _Branch(self._condition, action)
        self._head = branch
        self._tail = branch
        return self

    def elif_(self, condition: Condition) -> _IfBuilder:
        if self._tail is None:
            raise RuntimeError("Call .then() before .elif_()")
        return self._add_branch(condition)

    def else_(self, action: Callable[[], Any]) -> Any:
        if self._tail is None:
            raise RuntimeError("Call .then() before .else_()")
        self._tail._next_branch = _Branch(True, action)
        return self._exec()

    def _add_branch(self, condition: Condition) -> _IfBuilder:
        """Called by elif_() — defers action binding."""
        self._elif_condition = condition
        return self

    # Override __getattr__ to allow .elif_(cond).then(action) chaining
    # Actually, let's restructure: elif_ returns a special holder

    def _exec(self) -> Any:
        if self._head is None:
            return None
        return self._head._evaluate()

    def run(self) -> Any:
        """Execute the if chain without an else (returns None if condition fails)."""
        return self._exec()


class _ElifHolder:
    """Intermediate object returned by .elif_() before .then() is called."""

    __slots__ = ("_parent", "_condition")

    def __init__(self, parent: _IfBuilder, condition: Condition) -> None:
        self._parent = parent
        self._condition = condition

    def then(self, action: Callable[[], Any]) -> _IfBuilder:
        branch = _Branch(self._condition, action)
        self._parent._tail._next_branch = branch  # type: ignore[union-attr]
        self._parent._tail = branch
        return self._parent


class if_:
    """Start an if/elif/else chain.

    Supports bare bools, callables, and condition helpers::

        # Simple
        if_(True).then(lambda: print("yes")).else_(lambda: print("no"))

        # With FindBuilder
        if_(exists(Find().name("Popup")))
            .then(lambda: Find().name("Close").do(lambda e: e.click()))
            .else_(lambda: print("no popup"))

        # Multi-branch
        if_(eq(status, "ok"))
            .then(lambda: ...)
            .elif_(eq(status, "warn"))
            .then(lambda: ...)
            .else_(lambda: ...)
    """

    def __new__(cls, condition: Condition) -> _IfBuilder:
        return _IfBuilder(condition)


# Monkey-patch elif_ to return _ElifHolder for fluent chaining
_IfBuilder.elif_ = (  # type: ignore[assignment]
    lambda self, cond: _ElifHolder(self, cond)
)


# ======================================================================
# switch_
# ======================================================================

class _CaseBuilder:
    """Fluent builder for switch/case chains.

    Usage::

        switch_(status)
            .case("ok", lambda: print("OK"))
            .case("error", lambda: print("ERROR"))
            .default(lambda: print("unknown"))
    """

    __slots__ = ("_value", "_cases", "_default")

    def __init__(self, value: Any) -> None:
        self._value = value
        self._cases: List[tuple[Any, Callable[[], Any]]] = []
        self._default: Optional[Callable[[], Any]] = None

    def case(self, match_value: Any, action: Callable[[], Any]) -> _CaseBuilder:
        self._cases.append((match_value, action))
        return self

    def default(self, action: Callable[[], Any]) -> Any:
        self._default = action
        return self._exec()

    def run(self) -> Any:
        """Execute without a default branch (returns None on no match)."""
        return self._exec()

    def _exec(self) -> Any:
        val = self._value() if callable(self._value) else self._value
        for match_val, action in self._cases:
            mv = match_val() if callable(match_val) else match_val
            if val == mv:
                return action()
        if self._default:
            return self._default()
        return None


class switch_:
    """Start a switch/case chain.

    Usage::

        switch_(status)
            .case("ok", lambda: handle_ok())
            .case("error", lambda: handle_error())
            .default(lambda: handle_unknown())
    """

    def __new__(cls, value: Any) -> _CaseBuilder:
        return _CaseBuilder(value)
