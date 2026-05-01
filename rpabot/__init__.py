"""RPA Framework - A modern, extensible robotic process automation framework."""

__version__ = "0.1.0"

from rpabot.core.exceptions import (
    RPABaseError,
    ElementNotFound,
    ActionNotPossible,
    TimeoutError,
    DriverError,
)
from rpabot.core.locator import (
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
from rpabot.core.element import Element, Rectangle
from rpabot.core.context import AutomationContext
from rpabot.core.driver import DriverAdapter
from rpabot.builder.find_builder import FindBuilder, Find
from rpabot.functional.utils import retry, pipe, tap, maybe, with_context, wait_until
from rpabot.plugin.base import Plugin, PluginManager
from rpabot.flow.conditions import (
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
from rpabot.flow.branching import if_, switch_
from rpabot.flow.loops import for_each, while_, until_, repeat
from rpabot.flow.sequence import sequence, try_catch
from rpabot.pipeline.context import PipelineContext
from rpabot.pipeline.step import Step, StepResult
from rpabot.pipeline.pipeline import Pipeline, PipelineResult

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
