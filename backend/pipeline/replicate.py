"""
Pipeline stage: generate replicate snapshots and compute verdict.
"""

from backend.pipeline.context import PipelineContext
from backend.scoring_engine import ReplicateResult


def replicate_stage(ctx: PipelineContext) -> PipelineContext:
    """
    Run judge/extraction/bootstrap replicates, merge-variant channel,
    and compute the final verdict.

    Inputs (required on ctx):
      engine, topics, selected_facts, selected_args,
      topic_content_mass, side_order, frame_context, scores

    Outputs (written to ctx):
      replicates, replicate_topics, verdict_result
    """
    engine = ctx.engine
    topics = ctx.topics or []
    side_order = ctx.side_order or ["FOR", "AGAINST"]
    frame_context = ctx.frame_context or ""
    selected_facts = ctx.selected_facts or {}
    selected_args = ctx.selected_args or {}
    topic_content_mass = ctx.topic_content_mass or {}

    # Run replicates (judges + extraction + bootstrap)
    replicates = engine.scoring_engine.run_replicates(
        [{"topic_id": t.topic_id} for t in topics],
        selected_facts,
        selected_args,
        topic_content_mass,
        side_order=side_order,
        frame_context=frame_context,
        extraction_reruns=2,
        bootstrap=True,
    )

    # Merge-variant replicate channel
    replicate_topics = engine.topic_engine.merge_variant_replicate(topics, variant_seed=99)
    rep_mass, rep_facts, rep_args, primary_to_rep = engine._remap_to_replicate(
        topics, replicate_topics, topic_content_mass, selected_facts, selected_args
    )
    replicate_scores = engine.scoring_engine.compute_debate_scores(
        [{"topic_id": t.topic_id, "scope": t.scope} for t in replicate_topics],
        rep_facts,
        rep_args,
        rep_mass,
        side_order=side_order,
        frame_context=frame_context,
    )

    merge_replicate = ReplicateResult(
        overall_for=replicate_scores.get("overall_for", 0.0),
        overall_against=replicate_scores.get("overall_against", 0.0),
        margin_d=replicate_scores.get("margin_d", 0.0),
        topic_scores=replicate_scores.get("topic_scores", {}),
        overall_scores=replicate_scores.get("overall_scores", {}),
        side_order=side_order,
        metadata={
            "replicate_type": "merge_variant",
            "replicate_seed": 99,
            "variant_target": max(engine.topic_engine.MIN_TOPICS, len(topics) - 1),
        },
    )
    replicates.append(merge_replicate)

    # Verdict from full replicate set
    verdict_result = engine.scoring_engine.compute_verdict(replicates, side_order=side_order)

    structural_count = sum(
        1 for r in replicates if getattr(r, "metadata", {}).get("replicate_type") == "merge_variant"
    )
    verdict_result["replicate_composition"] = {
        "bootstrap_samples": len(replicates) - structural_count,
        "structural_replicate_count": structural_count,
        "replicate_count": len(replicates),
    }

    ctx.replicates = replicates
    ctx.replicate_topics = replicate_topics
    ctx.verdict_result = verdict_result
    return ctx
