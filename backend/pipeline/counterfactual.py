"""
Pipeline stage: run counterfactual perturbation tests.
"""

from backend.pipeline.context import PipelineContext


def counterfactual_stage(ctx: PipelineContext) -> PipelineContext:
    """
    Compute counterfactual scores on full fact/argument sets.

    Inputs (required on ctx):
      engine, topics, canonical_facts, canonical_args,
      topic_content_mass, side_order, frame_context

    Outputs (written to ctx):
      counterfactuals
    """
    engine = ctx.engine
    topics = ctx.topics or []
    side_order = ctx.side_order or ["FOR", "AGAINST"]
    frame_context = ctx.frame_context or ""

    counterfactuals = engine.scoring_engine.compute_counterfactuals(
        [{"topic_id": t.topic_id} for t in topics],
        ctx.canonical_facts or {},
        ctx.canonical_args or {},
        ctx.topic_content_mass or {},
        side_order=side_order,
        frame_context=frame_context,
    )

    ctx.counterfactuals = counterfactuals
    return ctx
