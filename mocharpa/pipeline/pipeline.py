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

from mocharpa.core.context import AutomationContext
from mocharpa.core.driver import DriverAdapter
from mocharpa.plugins.base import PluginManager
from mocharpa.pipeline.context import PipelineContext
from mocharpa.pipeline.step import Step, StepResult
from mocharpa.events import (
    PipelineStartEvent,
    PipelineEndEvent,
    StepStartEvent,
    StepEndEvent,
    StepSkippedEvent,
    StepErrorEvent,
)

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
    audit: Any = None

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
        retry_count: int = 0,
        retry_delay: float = 1.0,
        audit: bool = False,
    ) -> PipelineResult:
        """Execute all steps in order.

        Args:
            data: Initial shared data dictionary (accessible as ``ctx.data``).
            context: Optional existing :class:`AutomationContext` to extend.
            driver: Driver to bind (creates one if context has none).
            plugins: Plugin manager to bind.
            retry_count: Number of times to retry the entire pipeline on failure.
            retry_delay: Seconds between pipeline-level retries.
            audit: If True, attach an :class:`AuditCollector` to the context
                and return the audit record via ``PipelineResult.audit``.

        Returns:
            :class:`PipelineResult` with per-step outputs and diagnostics.
        """
        from mocharpa.pipeline.audit import AuditCollector

        outer_start = time.monotonic()
        collector = AuditCollector(pipeline_name=self.name, input_data=data) if audit else None

        attempts = retry_count + 1
        last_result: Optional[PipelineResult] = None

        for attempt in range(attempts):
            if collector:
                collector.start()
            else:
                pass

            ctx = self._build_context(data=data, context=context, driver=driver, plugins=plugins)
            if collector:
                ctx._audit_collector = collector

            bus = ctx.event_bus

            bus.emit(PipelineStartEvent(pipeline_name=self.name, data=data or {}))

            result = PipelineResult(name=self.name, success=True)

            for step in self._steps:
                logger.info("Running step: %s", step.name)
                bus.emit(StepStartEvent(step_name=step.name))
                try:
                    sr: StepResult = step.execute(ctx)
                    if sr.skipped:
                        result.skipped.append(step.name)
                        logger.info("Skipped step: %s", step.name)
                        bus.emit(StepSkippedEvent(step_name=step.name))
                        if collector:
                            collector.record_skipped(step.name)
                        continue

                    if sr.error is not None:
                        result.errors[step.name] = sr.error
                        result.success = False
                        logger.warning(
                            "Step '%s' failed (continue_on_error): %s",
                            step.name,
                            sr.error,
                        )
                        bus.emit(StepErrorEvent(
                            step_name=step.name, error=sr.error,
                            elapsed=sr.elapsed, unhandled=False,
                        ))
                        if collector:
                            collector.record_error(step.name, sr.error, sr.elapsed)
                    else:
                        ctx.record_step(step.name, sr.output)
                        result.step_results[step.name] = sr.output
                        bus.emit(StepEndEvent(
                            step_name=step.name, output=sr.output,
                            elapsed=sr.elapsed,
                        ))
                        if collector:
                            collector.record_ok(step.name, sr.output, sr.elapsed)

                except Exception as exc:
                    logger.exception("Step '%s' raised unhandled exception", step.name)
                    result.errors[step.name] = str(exc)
                    result.success = False
                    bus.emit(StepErrorEvent(
                        step_name=step.name, error=str(exc),
                        elapsed=time.monotonic() - outer_start, unhandled=True,
                    ))
                    if collector:
                        collector.record_exception(step.name, str(exc), time.monotonic() - outer_start)
                    break

            if collector:
                collector.finish(result.success)

            error_count = len(result.errors)
            step_count = len(result.step_results)

            bus.emit(PipelineEndEvent(
                pipeline_name=self.name,
                success=result.success,
                elapsed=time.monotonic() - outer_start,
                step_count=step_count,
                error_count=error_count,
            ))

            if result.success:
                result.elapsed = time.monotonic() - outer_start
                if collector:
                    result.audit = collector.record  # type: ignore[attr-defined]
                ctx.cleanup_tempdir()
                logger.info("Pipeline '%s' finished: %s", self.name, result)
                return result

            last_result = result
            if attempt < attempts - 1:
                logger.info("Pipeline '%s' retrying (attempt %d/%d)...", self.name, attempt + 1, attempts)
                time.sleep(retry_delay)

        # All attempts exhausted
        last_result.elapsed = time.monotonic() - outer_start  # type: ignore[union-attr]
        if collector:
            collector.finish(False)
            last_result.audit = collector.record  # type: ignore[attr-defined, union-attr]
        error_count = len(last_result.errors)  # type: ignore[union-attr]
        step_count = len(last_result.step_results)  # type: ignore[union-attr]
        bus.emit(PipelineEndEvent(
            pipeline_name=self.name,
            success=False,
            elapsed=last_result.elapsed,  # type: ignore[union-attr]
            step_count=step_count,
            error_count=error_count,
        ))
        ctx.cleanup_tempdir()
        logger.info("Pipeline '%s' finished (all retries exhausted): %s", self.name, last_result)
        return last_result  # type: ignore[return-value]

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
        # Propagate plugin_manager from base if not explicitly overridden
        if plugins is None and hasattr(base, '_plugin_manager'):
            plugins = base._plugin_manager  # type: ignore[assignment]
        return PipelineContext(
            driver=driver or base.driver,
            timeout=base.timeout,
            log_level=base.log_level,
            retry_count=base.retry_count,
            retry_delay=base.retry_delay,
            data=data,
            plugin_manager=plugins,
            event_bus=base.event_bus,
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

    @staticmethod
    def from_yaml(yaml_str: str) -> Pipeline:
        """Parse a YAML string into a :class:`Pipeline`.

        Requires ``pyyaml``.  Thin wrapper around :func:`mocharpa.pipeline.loader.load_yaml`.
        """
        from mocharpa.pipeline.loader import load_yaml
        return load_yaml(yaml_str)

    @staticmethod
    def from_yaml_file(path) -> Pipeline:
        """Load a pipeline from a ``.yaml`` / ``.yml`` file."""
        from mocharpa.pipeline.loader import load_yaml_file
        return load_yaml_file(path)

    @staticmethod
    def from_json(json_str: str) -> Pipeline:
        """Parse a JSON string into a :class:`Pipeline`."""
        from mocharpa.pipeline.loader import load_json
        return load_json(json_str)

    @staticmethod
    def from_json_file(path) -> Pipeline:
        """Load a pipeline from a ``.json`` file."""
        from mocharpa.pipeline.loader import load_json_file
        return load_json_file(path)

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Pipeline({self.name!r} steps={len(self._steps)})"
