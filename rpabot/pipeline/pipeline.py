"""Pipeline builder and execution engine.

The :class:`Pipeline` class is the primary entry point for defining and
running pipeline-style automation steps.  Steps are registered in order
and executed sequentially, with each step's output becoming the ``previous``
value available to the next step.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from rpabot.core.context import AutomationContext
from rpabot.core.driver import DriverAdapter
from rpabot.plugin.base import PluginManager
from rpabot.pipeline.context import PipelineContext
from rpabot.pipeline.step import Step, StepResult

logger = logging.getLogger("rpa.pipeline")


# ======================================================================
# PipelineResult
# ======================================================================

@dataclass
class PipelineResult:
    """Aggregated result of a completed pipeline run.

    Attributes:
        name: Pipeline name.
        success: ``True`` if all steps completed without unhandled errors.
        step_results: Mapping of step name → return value.
        errors: Mapping of step name → error message (only for steps that
            failed with ``continue_on_error=True``).
        skipped: List of step names that were skipped (condition returned False).
        elapsed: Total wall-clock seconds.
    """

    name: str = ""
    success: bool = False
    step_results: Dict[str, Any] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    skipped: List[str] = field(default_factory=list)
    elapsed: float = 0.0

    def __repr__(self) -> str:
        status = "OK" if self.success else "FAILED"
        return (
            f"PipelineResult({self.name!r} {status} "
            f"steps={len(self.step_results)} "
            f"errors={len(self.errors)} elapsed={self.elapsed:.2f}s)"
        )


# ======================================================================
# Pipeline
# ======================================================================

class Pipeline:
    """Declarative pipeline builder for composing automation steps.

    Usage (Python DSL)::

        pl = Pipeline("report_pipeline")

        pl.step("login", lambda ctx: login())
          .step("extract", lambda ctx: extract_data())
          .step("save", lambda ctx: save_to_db(ctx.previous))
          .run(data={"env": "prod"})

    Steps are executed in registration order.  Each step's return value
    becomes ``ctx.previous`` for the next step and is recorded in
    ``ctx.step_results`` by name.

    Serialization::

        pl.to_dict()               # → plain dict
        Pipeline.from_dict(d)      # → Pipeline (action lambdas lost)
        Pipeline.from_yaml(yml)    # → Pipeline (YAML DSL)
    """

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._steps: List[Step] = []

    # ------------------------------------------------------------------
    # Builder API
    # ------------------------------------------------------------------

    def step(
        self,
        name: str,
        action: Callable[[PipelineContext], Any],
        *,
        condition: Any = None,
        max_retries: int = 0,
        retry_delay: float = 1.0,
        continue_on_error: bool = False,
        timeout: Optional[float] = None,
    ) -> Pipeline:
        """Append a step and return self for chaining.

        Args:
            name: Unique step identifier.
            action: Callable ``(ctx: PipelineContext) -> Any``.
            condition: Optional precondition (see :class:`Step`).
            max_retries: Retry attempts on failure.
            retry_delay: Seconds between retries.
            continue_on_error: If ``True``, record error and continue.
            timeout: Maximum step duration in seconds.
        """
        step = Step(
            name,
            action,
            condition=condition,
            max_retries=max_retries,
            retry_delay=retry_delay,
            continue_on_error=continue_on_error,
            timeout=timeout,
        )
        self._steps.append(step)
        return self

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        data: Optional[Dict[str, Any]] = None,
        context: Optional[AutomationContext] = None,
        driver: Optional[DriverAdapter] = None,
        plugins: Optional[PluginManager] = None,
    ) -> PipelineResult:
        """Execute all steps in order.

        Args:
            data: Initial shared data dictionary (accessible as ``ctx.data``).
            context: Optional existing :class:`AutomationContext` to extend.
            driver: Driver to bind (creates one if context has none).
            plugins: Plugin manager to bind.

        Returns:
            :class:`PipelineResult` with per-step outputs and diagnostics.
        """
        start = time.monotonic()

        # Build PipelineContext
        ctx = self._build_context(data=data, context=context, driver=driver, plugins=plugins)

        result = PipelineResult(name=self.name, success=True)

        for step in self._steps:
            logger.info("Running step: %s", step.name)
            try:
                sr: StepResult = step.execute(ctx)
                if sr.skipped:
                    result.skipped.append(step.name)
                    logger.info("Skipped step: %s", step.name)
                    continue

                if sr.error is not None:
                    result.errors[step.name] = sr.error
                    result.success = False
                    logger.warning(
                        "Step '%s' failed (continue_on_error): %s",
                        step.name,
                        sr.error,
                    )
                else:
                    ctx.record_step(step.name, sr.output)
                    result.step_results[step.name] = sr.output

            except Exception as exc:
                logger.exception("Step '%s' raised unhandled exception", step.name)
                result.errors[step.name] = str(exc)
                result.success = False
                break

        result.elapsed = time.monotonic() - start
        logger.info("Pipeline '%s' finished: %s", self.name, result)
        return result

    def __call__(
        self,
        *,
        data: Optional[Dict[str, Any]] = None,
        context: Optional[AutomationContext] = None,
        driver: Optional[DriverAdapter] = None,
        plugins: Optional[PluginManager] = None,
    ) -> PipelineResult:
        """Convenience alias for :meth:`run`."""
        return self.run(data=data, context=context, driver=driver, plugins=plugins)

    def _build_context(
        self,
        *,
        data: Optional[Dict[str, Any]] = None,
        context: Optional[AutomationContext] = None,
        driver: Optional[DriverAdapter] = None,
        plugins: Optional[PluginManager] = None,
    ) -> PipelineContext:
        """Construct the PipelineContext for execution."""
        base = context or AutomationContext.get_current()
        return PipelineContext(
            driver=driver or base.driver,
            timeout=base.timeout,
            log_level=base.log_level,
            retry_count=base.retry_count,
            retry_delay=base.retry_delay,
            data=data,
            plugin_manager=plugins,
        )

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def steps(self) -> List[Step]:
        """Return a copy of the step list."""
        return list(self._steps)

    @property
    def step_count(self) -> int:
        """Number of registered steps."""
        return len(self._steps)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize pipeline metadata (action callables are NOT serialized)."""
        return {
            "name": self.name,
            "steps": [s.to_dict() for s in self._steps],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Pipeline:
        """Create a Pipeline from a dict.  Steps must be re-bound manually."""
        pl = cls(name=d.get("name", ""))
        # Note: action callables cannot be deserialized —
        # use from_yaml() + loader for full round-trip.
        return pl

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Pipeline({self.name!r} steps={len(self._steps)})"
