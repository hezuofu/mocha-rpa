"""Pipeline orchestration engine for composing RPA steps.

Provides:

* :class:`Pipeline` — builder + runner for step pipelines
* :class:`PipelineContext` — extended context with data-sharing and template resolution
* :class:`Step` — single executable unit with condition/retry/error strategy
* ``actions`` — pre-built action factories (find_click, send_keys, http_get, etc.)
* ``loader`` — YAML / JSON pipeline loader
* ``validator`` — pipeline definition schema validation
* ``audit`` — structured run recording for observability
"""

from mocharpa.pipeline.context import PipelineContext
from mocharpa.pipeline.step import Step, StepResult
from mocharpa.pipeline.pipeline import Pipeline, PipelineResult
from mocharpa.pipeline import actions, loader, validator, audit

__all__ = [
    "PipelineContext",
    "Step",
    "StepResult",
    "Pipeline",
    "PipelineResult",
    "actions",
    "loader",
    "validator",
    "audit",
]
