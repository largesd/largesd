"""
Pipeline stage: validate symmetry constraints.
"""

from backend.pipeline.context import PipelineContext


def symmetry_stage(ctx: PipelineContext) -> PipelineContext:
    """
    Run normative symmetry tests against frame evaluation criteria.

    Inputs (required on ctx):
      engine, selected_facts, active_frame, side_order, frame_context

    Outputs (written to ctx):
      symmetry_result
    """
    engine = ctx.engine
    selected_facts = ctx.selected_facts or {}
    active_frame = ctx.active_frame or {}
    side_order = ctx.side_order or ["FOR", "AGAINST"]
    frame_context = ctx.frame_context or ""

    frame_values = active_frame.get("evaluation_criteria", []) if active_frame else []
    normative_symmetry = engine.scoring_engine.run_symmetry_tests(
        dict(selected_facts),
        frame_values=frame_values,
        side_order=side_order,
        frame_context=frame_context,
    )

    ctx.symmetry_result = normative_symmetry
    return ctx
