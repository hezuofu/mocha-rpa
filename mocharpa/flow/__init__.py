"""Flow-control primitives for building RPA workflows.

Provides conditional branching, loops, sequential execution, and structured
error handling — all composable with :class:`~rpa.builder.find_builder.FindBuilder`
and the existing functional utilities.
"""

from mocharpa.flow.conditions import (
    Condition,
    exists,
    not_exists,
    visible,
    enabled,
    selected,
    eq,
    neq,
    contains,
    gt,
    lt,
    is_none,
    is_not_none,
    AND,
    OR,
    NOT,
)
from mocharpa.flow.branching import if_, switch_
from mocharpa.flow.loops import for_each, while_, until_, repeat
from mocharpa.flow.sequence import sequence, try_catch

__all__ = [
    # Conditions
    "Condition",
    "exists",
    "not_exists",
    "visible",
    "enabled",
    "selected",
    "eq",
    "neq",
    "contains",
    "gt",
    "lt",
    "is_none",
    "is_not_none",
    "AND",
    "OR",
    "NOT",
    # Branching
    "if_",
    "switch_",
    # Loops
    "for_each",
    "while_",
    "until_",
    "repeat",
    # Sequential
    "sequence",
    "try_catch",
]
