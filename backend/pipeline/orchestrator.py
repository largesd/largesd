"""
Pipeline orchestrator: execute snapshot stages in order with error handling.
"""

import logging
from collections.abc import Callable

from backend.pipeline.audit import audit_stage
from backend.pipeline.canonicalize import canonicalize_stage
from backend.pipeline.context import PipelineContext
from backend.pipeline.counterfactual import counterfactual_stage
from backend.pipeline.extract import extract_stage
from backend.pipeline.fact_check import fact_check_stage
from backend.pipeline.persist import persist_stage
from backend.pipeline.replicate import replicate_stage
from backend.pipeline.score import score_stage
from backend.pipeline.symmetry import symmetry_stage

logger = logging.getLogger(__name__)

STAGES: list[tuple[str, Callable[[PipelineContext], PipelineContext]]] = [
    ("extract", extract_stage),
    ("fact_check", fact_check_stage),
    ("canonicalize", canonicalize_stage),
    ("score", score_stage),
    ("replicate", replicate_stage),
    ("counterfactual", counterfactual_stage),
    ("symmetry", symmetry_stage),
    ("audit", audit_stage),
    ("persist", persist_stage),
]


def handle_pipeline_failure(ctx: PipelineContext, stage_name: str, exc: Exception) -> None:
    """Log pipeline failure and update job status if a job queue is available."""
    logger.error(f"[{ctx.request_id}] Pipeline failed at stage '{stage_name}': {exc}")
    # Future: update job status via engine.job_queue if available


def run_snapshot_pipeline(ctx: PipelineContext) -> PipelineContext:
    """
    Execute all pipeline stages sequentially with error handling.

    On failure, calls handle_pipeline_failure() and re-raises.
    """
    for stage_name, stage_func in STAGES:
        try:
            logger.info(f"[{ctx.request_id}] Starting stage: {stage_name}")
            ctx = stage_func(ctx)
            logger.info(f"[{ctx.request_id}] Completed stage: {stage_name}")
        except Exception as e:
            logger.error(f"[{ctx.request_id}] Stage {stage_name} failed: {e}")
            handle_pipeline_failure(ctx, stage_name, e)
            raise
    return ctx
