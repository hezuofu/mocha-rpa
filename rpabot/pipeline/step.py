"""Workflow step definition — a single executable unit in a workflow pipeline.

Each step wraps an action callable with optional condition, retry, error
handling, and timeout controls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union

from rpabot.flow.conditions import Condition, _ensure_callable


# ======================================================================
# StepResult
# ======================================================================

@dataclass(slots=True)
class StepResult:
    """Outcome of executing a single step.

    Attributes:
        step_name: Name of the step.
        output: Return value of the action (None if skipped or errored).
        error: Exception message if the step failed, else None.
        skipped: True if the step was skipped due to a false condition.
        elapsed: Wall-clock seconds for this step.
    """

    step_name: str
    output: Any = None
    error: Optional[str] = None
    skipped: bool = False
    elapsed: float = 0.0


# ======================================================================
# Step
# ======================================================================

class Step:
    """A single workflow step — condition + action + error strategy.

    Args:
        name: Unique identifier for this step (used for result history).
        action: Callable ``(ctx) -> Any`` that performs the step's work.
        condition: Optional precondition.  If it evaluates to ``False``
            the step is skipped.  Accepts a bare bool, a ``() -> bool``
            callable, or any :class:`~rpa.flow.conditions.Condition`.
        max_retries: Number of retry attempts on failure (total = 1 + N).
        retry_delay: Seconds to wait between retries.
        continue_on_error: If ``True``, exceptions are recorded but the
            workflow continues to the next step.
        timeout: Maximum seconds for this step; raises
            :class:`~rpa.core.exceptions.TimeoutError` if exceeded.
    """

    __slots__ = (
        "name",
        "_action",
        "_condition",
        "max_retries",
        "retry_delay",
        "continue_on_error",
        "timeout",
    )

    def __init__(
        self,
        name: str,
        action: Callable[[Any], Any],
        *,
        condition: Optional[Condition] = None,
        max_retries: int = 0,
        retry_delay: float = 1.0,
        continue_on_error: bool = False,
        timeout: Optional[float] = None,
    ) -> None:
        self.name = name
        self._action = action
        self._condition = condition
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.continue_on_error = continue_on_error
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def should_skip(self, ctx: Any) -> bool:
        """Check whether this step should be skipped."""
        if self._condition is None:
            return False
        check = _ensure_callable(self._condition)
        return not check()

    def execute(self, ctx: Any) -> StepResult:
        """Run this step against *ctx* and return a :class:`StepResult`.

        Handles condition check, retry, timeout, and continue_on_error.
        """
        start = time.monotonic()

        # Check precondition
        if self.should_skip(ctx):
            return StepResult(self.name, skipped=True, elapsed=0.0)

        # Retry loop
        attempts = self.max_retries + 1
        last_error: Optional[str] = None

        for attempt in range(attempts):
            try:
                if self.timeout is not None:
                    elapsed = time.monotonic() - start
                    remaining = self.timeout - elapsed
                    if remaining <= 0:
                        raise TimeoutError(
                            f"Step '{self.name}' timed out after {self.timeout}s"
                        )
                    # Execute with timeout via context override
                    if hasattr(ctx, "with_timeout"):
                        with ctx.with_timeout(min(remaining, self.timeout)):
                            output = self._action(ctx)
                    else:
                        output = self._action(ctx)
                else:
                    output = self._action(ctx)

                elapsed = time.monotonic() - start
                return StepResult(self.name, output=output, elapsed=elapsed)

            except Exception as exc:
                last_error = str(exc)
                if attempt < attempts - 1:
                    time.sleep(self.retry_delay)
                else:
                    if self.continue_on_error:
                        elapsed = time.monotonic() - start
                        return StepResult(
                            self.name, error=last_error, elapsed=elapsed
                        )
                    raise

        # Should not reach here
        elapsed = time.monotonic() - start
        return StepResult(self.name, error=last_error, elapsed=elapsed)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize the step to a plain dict (for YAML/JSON export)."""
        d: dict = {
            "name": self.name,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "continue_on_error": self.continue_on_error,
        }
        if self.timeout is not None:
            d["timeout"] = self.timeout
        if self._condition is not None:
            d["condition"] = _serialize_condition(self._condition)
        return d

    def __repr__(self) -> str:
        flags = []
        if self._condition is not None:
            flags.append("conditional")
        if self.continue_on_error:
            flags.append("safe")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        return f"Step({self.name!r}{flag_str})"


# ======================================================================
# helpers
# ======================================================================

def _serialize_condition(cond: Condition) -> str:
    """Best-effort serialization of a condition."""
    if isinstance(cond, bool):
        return str(cond)
    if callable(cond):
        qualname = getattr(cond, "__qualname__", None)
        name = getattr(cond, "__name__", None)
        return qualname or name or str(cond)
    return str(cond)
