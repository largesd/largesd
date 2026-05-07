"""
Pipeline stage: compute selection, scores, confidence, and verdict prerequisites.
"""

from collections import defaultdict
from typing import Any

from backend.pipeline.context import PipelineContext


def score_stage(ctx: PipelineContext) -> PipelineContext:
    """
    Update canonical metrics, run stratified selection, generate steelman
    summaries, and compute debate scores.

    Inputs (required on ctx):
      engine, topics, canonical_facts, canonical_args,
      topic_content_mass, side_order, frame_context

    Outputs (written to ctx):
      selected_facts, selected_args, selection_diagnostics, scores
    """
    engine = ctx.engine
    topics = ctx.topics or []
    side_order = ctx.side_order or ["FOR", "AGAINST"]
    frame_context = ctx.frame_context or ""
    canonical_facts = ctx.canonical_facts or {}
    canonical_args = ctx.canonical_args or {}
    topic_content_mass = ctx.topic_content_mass or {}

    # Update centrality, distinct_support, cross-references
    engine._update_canonical_metrics(canonical_facts, canonical_args)

    # Deterministic stratified selection per topic-side
    selected_facts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    selected_args: dict[str, list[dict[str, Any]]] = defaultdict(list)
    selection_diagnostics: dict[str, Any] = {}
    selection_seed = ctx.selection_seed

    for topic in topics:
        tid = topic.topic_id
        facts_pool = canonical_facts.get(tid, [])
        args_pool = canonical_args.get(tid, [])

        for side in side_order:
            normative_count = len(
                [
                    f
                    for f in facts_pool
                    if f.get("side") == side and f.get("fact_type") == "normative"
                ]
            )
            empirical_count = len(
                [
                    f
                    for f in facts_pool
                    if f.get("side") == side and f.get("fact_type", "empirical") == "empirical"
                ]
            )
            budgets = {
                "K_E": max(3, min(empirical_count, 10)) if empirical_count else 0,
                "K_N": max(1, min(normative_count, 5)) if normative_count else 0,
                "K_A": max(3, min(len([a for a in args_pool if a.get("side") == side]), 8)),
            }

            selected_set = engine.selection_engine.select_for_topic_side(
                facts_pool, args_pool, tid, side, budgets, selection_seed
            )

            selected_facts[tid].extend([dict(f) for f in selected_set.selected_facts])
            selected_args[tid].extend([dict(a) for a in selected_set.selected_arguments])

            # Mark selected items in-place for downstream consumers
            sel_fact_ids = set(selected_set.selected_fact_ids)
            sel_arg_ids = set(selected_set.selected_arg_ids)
            for f in facts_pool:
                if f["canon_fact_id"] in sel_fact_ids:
                    f["is_selected"] = True
                    f["is_rarity_slice"] = f.get("canon_fact_id") in (
                        selected_set.diagnostics.get("pools", {})
                        .get("empirical_facts", {})
                        .get("rarity_ids", [])
                    )
            for a in args_pool:
                if a["canon_arg_id"] in sel_arg_ids:
                    a["is_selected"] = True
                    a["is_rarity_slice"] = a.get("canon_arg_id") in (
                        selected_set.diagnostics.get("pools", {})
                        .get("arguments", {})
                        .get("rarity_ids", [])
                    )

            selection_diagnostics[f"{tid}_{side}"] = engine.selection_engine.get_diagnostics(
                selected_set
            )

    # Generate steelman summaries
    for topic in topics:
        tid = topic.topic_id
        args = canonical_args.get(tid, [])
        if "FOR" in side_order:
            for_args = [a for a in args if a.get("side") == "FOR"]
            if for_args:
                summary = engine.llm_client.generate_steelman_summary(for_args, "FOR")
                topic.summary_for = summary.get("summary", "")
        if "AGAINST" in side_order:
            against_args = [a for a in args if a.get("side") == "AGAINST"]
            if against_args:
                summary = engine.llm_client.generate_steelman_summary(against_args, "AGAINST")
                topic.summary_against = summary.get("summary", "")

    # Compute scores on selected items
    scores = engine.scoring_engine.compute_debate_scores(
        [
            {
                "topic_id": t.topic_id,
                "name": t.name,
                "scope": t.scope,
                "relevance": t.relevance,
                "drift_score": t.drift_score,
                "coherence": t.coherence,
                "distinctness": t.distinctness,
            }
            for t in topics
        ],
        dict(selected_facts),
        dict(selected_args),
        topic_content_mass,
        side_order=side_order,
        frame_context=frame_context,
    )

    ctx.selected_facts = dict(selected_facts)
    ctx.selected_args = dict(selected_args)
    ctx.selection_diagnostics = selection_diagnostics
    ctx.scores = scores
    return ctx
