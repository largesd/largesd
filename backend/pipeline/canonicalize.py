"""
Pipeline stage: canonicalize facts/arguments, deduplicate, compute mass.
"""

from datetime import datetime
from typing import Any

from backend.lsd_v1_2 import compute_completeness_proxy
from backend.pipeline.context import PipelineContext


def canonicalize_stage(ctx: PipelineContext) -> PipelineContext:
    """
    Canonicalize extracted facts and arguments, persist them,
    and compute per-topic content mass.

    Inputs (required on ctx):
      engine, debate_id, frame_id, extracted

    Outputs (written to ctx):
      canonical_facts, canonical_args, topic_content_mass
    """
    engine = ctx.engine
    debate_id = ctx.debate_id
    frame_id = ctx.frame_id
    extracted = ctx.extracted or {}

    canonical_facts: dict[str, list[dict[str, Any]]] = {}
    canonical_args: dict[str, list[dict[str, Any]]] = {}
    topic_content_mass: dict[str, int] = {}

    for tid, data in extracted.items():
        topic = data["topic"]
        all_facts = data.get("facts", [])
        all_args = data.get("args", [])
        all_spans = data.get("spans", [])

        # Canonicalize facts
        cfacts = engine.extraction_engine.canonicalize_facts(all_facts, topic.scope)
        topic_facts = []
        for cf in cfacts:
            fact_data = {
                "canon_fact_id": cf.canon_fact_id,
                "debate_id": debate_id,
                "frame_id": frame_id,
                "topic_id": cf.topic_id,
                "side": cf.side,
                "canon_fact_text": cf.canon_fact_text,
                "member_fact_ids": cf.member_fact_ids,
                "p_true": cf.p_true,
                "fact_type": getattr(cf, "fact_type", "empirical"),
                "normative_provenance": getattr(cf, "normative_provenance", ""),
                "operationalization": getattr(cf, "operationalization", ""),
                "provenance_links": [
                    {"span_id": s.span_id, "text": s.span_text} for s in cf.provenance_spans
                ],
                "evidence_tier_counts": getattr(cf, "evidence_tier_counts", {}),
                "referenced_by_au_ids": [],
                "created_at": datetime.now().isoformat(),
                "v15_status": cf.v15_status,
                "v15_insufficiency_reason": cf.v15_insufficiency_reason,
                "v15_human_review_flags": cf.v15_human_review_flags,
                "v15_best_evidence_tier": cf.v15_best_evidence_tier,
            }
            engine.db.save_canonical_fact(fact_data)
            topic_facts.append(fact_data)
        canonical_facts[tid] = topic_facts

        # Canonicalize arguments
        cargs = engine.extraction_engine.canonicalize_arguments(all_args, cfacts, topic.scope)
        topic_arguments = []
        for ca in cargs:
            arg_data = {
                "canon_arg_id": ca.canon_arg_id,
                "debate_id": debate_id,
                "frame_id": frame_id,
                "topic_id": ca.topic_id,
                "side": ca.side,
                "inference_text": ca.inference_text,
                "supporting_facts": list(ca.supporting_facts),
                "member_au_ids": ca.member_au_ids,
                "provenance_links": [
                    {"span_id": s.span_id, "text": s.span_text} for s in ca.provenance_spans
                ],
                "reasoning_score": 0.5,
                "reasoning_iqr": 0.0,
                "completeness_proxy": compute_completeness_proxy(
                    {
                        "inference_text": ca.inference_text,
                        "supporting_facts": list(ca.supporting_facts),
                        "provenance_links": [
                            {"span_id": s.span_id, "text": s.span_text} for s in ca.provenance_spans
                        ],
                        "member_au_ids": ca.member_au_ids,
                    }
                ),
                "created_at": datetime.now().isoformat(),
            }
            engine.db.save_canonical_argument(arg_data)
            topic_arguments.append(arg_data)
        canonical_args[tid] = topic_arguments

        # Content mass
        spans_lookup = {s["span_id"]: s for s in all_spans}
        content_mass = engine.content_mass_calculator.calculate_topic_mass(
            topic_facts, topic_arguments, spans_lookup
        )
        topic_content_mass[tid] = content_mass

    ctx.canonical_facts = canonical_facts
    ctx.canonical_args = canonical_args
    ctx.topic_content_mass = topic_content_mass
    return ctx
