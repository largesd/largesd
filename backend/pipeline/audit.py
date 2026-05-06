"""
Pipeline stage: generate audit records, SHA-256 hashes, and diagnostics.
"""

import hashlib
import json
from typing import Any, Dict

from backend.lsd_v1_2 import (
    budget_adequacy,
    burstiness_indicators,
    centrality_cap_effect,
    coverage_adequacy_trace,
    evaluator_variance_from_scores,
    formula_registry,
    frame_mode as get_frame_mode_flag,
    insufficiency_sensitivity,
    merge_sensitivity,
    participation_concentration,
    rarity_utilization,
    template_similarity_prevalence,
    topic_diagnostics,
    unselected_tail_summary,
)
from backend.pipeline.context import PipelineContext


def _canonical_json_hash(obj: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _topic_meta(topics):
    return [{"topic_id": t.topic_id, "name": t.name, "scope": t.scope,
             "relevance": t.relevance, "drift_score": t.drift_score,
             "coherence": t.coherence, "distinctness": t.distinctness} for t in topics]


def _topic_meta_parents(topics):
    return [{"topic_id": t.topic_id, "name": t.name, "scope": t.scope,
             "relevance": t.relevance, "parent_topic_ids": list(t.parent_topic_ids)} for t in topics]


def audit_stage(ctx: PipelineContext) -> PipelineContext:
    """
    Build decision dossier, run all audits, compute tamper-evident hashes,
    and prepare provider metadata.
    """
    engine = ctx.engine
    topics = ctx.topics or []
    side_order = ctx.side_order or ["FOR", "AGAINST"]
    frame_context = ctx.frame_context or ""
    cfacts = ctx.canonical_facts or {}
    cargs = ctx.canonical_args or {}
    sfacts = ctx.selected_facts or {}
    sargs = ctx.selected_args or {}
    mass = ctx.topic_content_mass or {}
    scores = ctx.scores or {}
    posts = ctx.posts or []
    allowed_posts = ctx.allowed_posts or []
    blocked_posts = ctx.blocked_posts or []
    selection_seed = ctx.selection_seed

    # Decision dossier
    dd = engine._build_decision_dossier(topics, cfacts, cargs, sfacts, sargs, scores.get("topic_scores", {}))
    dd["counterfactuals"] = ctx.counterfactuals or []
    dd["unselected_tail_summary"] = unselected_tail_summary(cfacts, cargs, sfacts, sargs)
    dd["insufficiency_sensitivity"] = insufficiency_sensitivity(scores.get("topic_scores", {}), scores.get("margin_d", 0.0))
    dd["formula_metadata"] = formula_registry()
    dd["normative_symmetry"] = ctx.symmetry_result or {}

    # Core audits
    stability = engine.extraction_engine.compute_extraction_stability(allowed_posts, topics[0].scope if topics else "")
    symmetry = engine.scoring_engine.run_side_label_symmetry_audit(_topic_meta(topics), cfacts, cargs, mass, side_order=side_order, frame_context=frame_context)
    relevance = engine.scoring_engine.compute_relevance_sensitivity(_topic_meta(topics), cfacts, cargs, mass, side_order=side_order, frame_context=frame_context)

    tdiag = topic_diagnostics(_topic_meta(topics), mass, sfacts, sargs)

    rep_topics = ctx.replicate_topics or []
    p2r = engine._remap_to_replicate(topics, rep_topics, mass, sfacts, sargs)[3] if rep_topics else {}
    rep_md = next(({"margin_d": getattr(r, "margin_d", 0.0)} for r in (ctx.replicates or []) if getattr(r, "metadata", {}).get("replicate_type") == "merge_variant"), {})
    merge = merge_sensitivity(_topic_meta_parents(topics), _topic_meta_parents(rep_topics), mass, scores.get("margin_d", 0.0), rep_md.get("margin_d", 0.0), p2r)

    ev = evaluator_variance_from_scores(scores.get("topic_scores", {}), scores.get("overall_scores", {}))
    part = participation_concentration(posts)
    integrity = {"version_id": "lsd-10-v1.2.0", "burstiness_indicators": burstiness_indicators(posts),
                 "template_similarity_prevalence": template_similarity_prevalence(posts),
                 "participation_entropy": part.get("participation_entropy", 0.0),
                 "concentration_buckets": part.get("concentration_buckets", {})}
    frame_sens = {"version_id": "lsd-19.4-v1.2.0", "frame_mode": get_frame_mode_flag(), "max_delta_d": 0.0,
                  "interpretation": "inactive_single_frame" if get_frame_mode_flag() == "single" else "multi-frame dispersion computed from active frame baseline",
                  "threshold": 0.1}

    # Manifests / hashes
    replay = engine._build_replay_manifest(ctx.debate_id, selection_seed, allowed_posts, blocked_posts, topics, side_order)
    recipes = engine._build_recipe_versions()
    ib = {"allowed_posts": [{"post_id": p["post_id"], "side": p["side"], "facts": p["facts"], "inference": p["inference"], "topic_id": p.get("topic_id")} for p in allowed_posts],
          "blocked_posts": [{"post_id": p["post_id"], "side": p["side"], "modulation_outcome": p["modulation_outcome"], "block_reason": p.get("block_reason")} for p in blocked_posts],
          "frame_id": ctx.frame_id, "side_order": side_order, "selection_seed": selection_seed}
    ob = {"topics": [{"topic_id": t.topic_id, "name": t.name, "relevance": t.relevance} for t in topics],
          "overall_scores": scores.get("overall_scores", {}), "verdict": (ctx.verdict_result or {}).get("verdict"), "topic_scores": scores.get("topic_scores", {})}

    # Provider metadata
    usage = engine.llm_client.get_usage_summary()
    rt = engine.llm_client.get_runtime_metadata()
    mdl = rt.get("configured_model", "mock")
    if isinstance(mdl, list):
        mdl = mdl[0] if mdl else "mock"
    if engine.llm_client._usage_log:
        mdl = engine.llm_client._usage_log[0].get("model", mdl)
    prov = {"provider": rt.get("provider", usage.get("provider", "mock")), "configured_model": rt.get("configured_model", "mock"),
            "actual_model": mdl, "num_judges": rt.get("num_judges", engine.num_judges),
            "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0), "llm_call_count": usage.get("call_count", 0)}

    ctx.decision_dossier = dd
    ctx.audit_records = {"extraction_stability": stability, "side_label_symmetry": symmetry,
                         "normative_symmetry": ctx.symmetry_result or {}, "relevance_sensitivity": relevance,
                         "topic_drift": ctx.drift_report, "selection_transparency": ctx.selection_diagnostics or {},
                         "verdict_replicates": ctx.verdict_result or {}, "decision_dossier": dd,
                         "evaluator_variance": ev, "topic_diagnostics": tdiag, "topic_merge_sensitivity": merge,
                         "participation_concentration": part, "integrity_indicators": integrity,
                         "budget_adequacy": budget_adequacy(ctx.selection_diagnostics or {}),
                         "centrality_cap_effect": centrality_cap_effect(ctx.selection_diagnostics or {}),
                         "rarity_utilization": rarity_utilization(ctx.selection_diagnostics or {}),
                         "coverage_adequacy_trace": coverage_adequacy_trace(scores.get("topic_scores", {})),
                         "frame_sensitivity": frame_sens, "formula_registry": formula_registry()}
    ctx.replay_manifest = replay
    ctx.recipe_versions = recipes
    ctx.input_hash_root = _canonical_json_hash(ib)
    ctx.output_hash_root = _canonical_json_hash(ob)
    ctx.provider_metadata = prov
    return ctx
