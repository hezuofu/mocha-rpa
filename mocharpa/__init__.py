"""RPA Framework - A modern, extensible robotic process automation framework."""

__version__ = "0.1.0"

from mocharpa.core.exceptions import (
    RPABaseError,
    ElementNotFound,
    ActionNotPossible,
    TimeoutError,
    DriverError,
)
from mocharpa.core.locator import (
    Locator,
    ById,
    ByName,
    ByType,
    ByClass,
    ByRegion,
    ByImage,
    LocatorChain,
    LocatorFactory,
)
from mocharpa.core.element import Element, Rectangle
from mocharpa.core.context import AutomationContext
from mocharpa.core.driver import DriverAdapter
from mocharpa.builder.find_builder import FindBuilder, Find
from mocharpa.functional.utils import retry, pipe, tap, maybe, with_context, wait_until
from mocharpa.plugin.base import Plugin, PluginManager
from mocharpa.flow.conditions import (
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
from mocharpa.pipeline.context import PipelineContext
from mocharpa.pipeline.step import Step, StepResult
from mocharpa.pipeline.pipeline import Pipeline, PipelineResult

__all__ = [
    # Version
    "__version__",
    # Exceptions
    "RPABaseError",
    "ElementNotFound",
    "ActionNotPossible",
    "TimeoutError",
    "DriverError",
    # Locators
    "Locator",
    "ById",
    "ByName",
    "ByType",
    "ByClass",
    "ByRegion",
    "ByImage",
    "LocatorChain",
    "LocatorFactory",
    # Element
    "Element",
    "Rectangle",
    # Context
    "AutomationContext",
    # Driver
    "DriverAdapter",
    # Builder
    "FindBuilder",
    "Find",
    # Functional
    "retry",
    "pipe",
    "tap",
    "maybe",
    "with_context",
    "wait_until",
    # Plugin
    "Plugin",
    "PluginManager",
    # Flow — conditions
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
    # Flow — branching
    "if_",
    "switch_",
    # Flow — loops
    "for_each",
    "while_",
    "until_",
    "repeat",
    # Flow — sequence
    "sequence",
    "try_catch",
    # Pipeline
    "PipelineContext",
    "Step",
    "StepResult",
    "Pipeline",
    "PipelineResult",
]
