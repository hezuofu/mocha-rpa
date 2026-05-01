"""Built-in condition predicates for flow-control components.

These helpers produce callables that can be used with :func:`if_`,
:func:`while_`, :func:`until_`, etc.  They also accept :class:`FindBuilder`
instances and evaluate them lazily.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Union, TYPE_CHECKING

from mocharpa.core.element import Element

if TYPE_CHECKING:
    from mocharpa.builder.find_builder import FindBuilder

# Shorthand: a condition can be a plain bool or a callable returning bool.
Condition = Union[bool, Callable[[], bool]]


# ======================================================================
# Element helpers
# ======================================================================

def exists(builder: FindBuilder) -> Callable[[], bool]:
    """Return a condition that checks whether an element exists.

    Usage::

        if_(exists(Find().name("OK"))).then(lambda: print("found"))
    """
    def _check() -> bool:
        return builder.exists()
    return _check


def not_exists(builder: FindBuilder) -> Callable[[], bool]:
    """Inverse of :func:`exists`."""
    def _check() -> bool:
        return not builder.exists()
    return _check


def visible(builder: FindBuilder) -> Callable[[], bool]:
    """Return a condition that checks element visibility.

    Returns ``False`` if the element is not found.
    """
    def _check() -> bool:
        el = builder.get()
        return el is not None and el.is_visible()
    return _check


def enabled(builder: FindBuilder) -> Callable[[], bool]:
    """Return a condition that checks whether an element is enabled.

    Returns ``False`` if the element is not found.
    """
    def _check() -> bool:
        el = builder.get()
        return el is not None and el.is_enabled()
    return _check


def selected(builder: FindBuilder) -> Callable[[], bool]:
    """Return a condition that checks whether an element is selected."""
    def _check() -> bool:
        el = builder.get()
        return el is not None and el.is_selected()
    return _check


# ======================================================================
# Value helpers
# ======================================================================

def eq(left: Any, right: Any) -> Callable[[], bool]:
    """Equality check — both sides may be callable (lazy evaluation)."""
    def _check() -> bool:
        lv = left() if callable(left) else left
        rv = right() if callable(right) else right
        return lv == rv
    return _check


def neq(left: Any, right: Any) -> Callable[[], bool]:
    """Inequality check."""
    def _check() -> bool:
        lv = left() if callable(left) else left
        rv = right() if callable(right) else right
        return lv != rv
    return _check


def contains(value: Any, item: Any) -> Callable[[], bool]:
    """Membership test — ``item in value`` with lazy evaluation."""
    def _check() -> bool:
        v = value() if callable(value) else value
        i = item() if callable(item) else item
        return i in v
    return _check


def gt(left: Any, right: Any) -> Callable[[], bool]:
    def _check() -> bool:
        lv = left() if callable(left) else left
        rv = right() if callable(right) else right
        return lv > rv
    return _check


def lt(left: Any, right: Any) -> Callable[[], bool]:
    def _check() -> bool:
        lv = left() if callable(left) else left
        rv = right() if callable(right) else right
        return lv < rv
    return _check


def is_none(value: Any) -> Callable[[], bool]:
    def _check() -> bool:
        v = value() if callable(value) else value
        return v is None
    return _check


def is_not_none(value: Any) -> Callable[[], bool]:
    def _check() -> bool:
        v = value() if callable(value) else value
        return v is not None
    return _check


# ======================================================================
# Combinators
# ======================================================================

def AND(*conditions: Condition) -> Callable[[], bool]:
    """Logical AND of multiple conditions.  Lazy — stops on first False."""
    compiled = [_ensure_callable(c) for c in conditions]
    def _check() -> bool:
        for c in compiled:
            if not c():
                return False
        return True
    return _check


def OR(*conditions: Condition) -> Callable[[], bool]:
    """Logical OR of multiple conditions.  Lazy — stops on first True."""
    compiled = [_ensure_callable(c) for c in conditions]
    def _check() -> bool:
        for c in compiled:
            if c():
                return True
        return False
    return _check


def NOT(condition: Condition) -> Callable[[], bool]:
    """Logical negation."""
    c = _ensure_callable(condition)
    def _check() -> bool:
        return not c()
    return _check


# ======================================================================
# Internal
# ======================================================================

def _ensure_callable(value: Condition) -> Callable[[], bool]:
    """Wrap a bare bool as a callable, pass callables through."""
    if callable(value):
        return value
    return lambda: bool(value)
