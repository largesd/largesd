"""
Pipeline modules for debate snapshot generation.

Breaks the monolithic generate_snapshot() into discrete,
independently testable stages orchestrated by run_snapshot_pipeline().
"""

from backend.pipeline.context import PipelineContext
from backend.pipeline.orchestrator import handle_pipeline_failure, run_snapshot_pipeline

__all__ = [
    "PipelineContext",
    "run_snapshot_pipeline",
    "handle_pipeline_failure",
]
