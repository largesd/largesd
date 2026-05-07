"""
Pipeline stage: resolve fact-checking results on extracted facts.
"""

from backend.pipeline.context import PipelineContext


def fact_check_stage(ctx: PipelineContext) -> PipelineContext:
    """
    Resolve pending fact checks for all extracted facts.

    Inputs (required on ctx):
      engine, extracted

    Outputs (written to ctx):
      extracted (facts mutated in-place with resolved p_true / status)
    """
    engine = ctx.engine
    extracted = ctx.extracted or {}

    for _tid, data in extracted.items():
        facts: list = data.get("facts", [])
        if facts:
            resolved = engine._resolve_fact_checks(facts)
            data["facts"] = resolved

    ctx.extracted = extracted
    return ctx
