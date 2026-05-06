"""
Pipeline stage: write snapshot to database, update debate, save audits.
"""

from datetime import datetime

from backend.pipeline.context import PipelineContext


def persist_stage(ctx: PipelineContext) -> PipelineContext:
    """
    Persist snapshot data, audits, and build the final result dict.

    Inputs (required on ctx):
      engine, debate_id, frame_id, trigger_type, side_order,
      snapshot_data fields computed in prior stages.

    Outputs (written to ctx):
      snapshot_id, snapshot_data, result
    """
    engine = ctx.engine
    debate_id = ctx.debate_id
    frame_id = ctx.frame_id
    topics = ctx.topics or []
    scores = ctx.scores or {}
    verdict_result = ctx.verdict_result or {}
    replay_manifest = ctx.replay_manifest or {}
    recipe_versions = ctx.recipe_versions or {}

    snapshot_id = f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{__import__('uuid').uuid4().hex[:4]}"
    snapshot_data = {
        "snapshot_id": snapshot_id,
        "debate_id": debate_id,
        "frame_id": frame_id,
        "timestamp": datetime.now().isoformat(),
        "trigger_type": ctx.trigger_type,
        "template_name": engine.modulation_engine.template.name,
        "template_version": engine.modulation_engine.template.version,
        "allowed_count": len(ctx.allowed_posts or []),
        "blocked_count": len(ctx.blocked_posts or []),
        "block_reasons": ctx.block_reasons or {},
        "borderline_rate": ctx.borderline_rate,
        "suppression_policy_json": ctx.suppression_policy,
        "status": "valid",
        "side_order": ctx.side_order,
        "overall_scores": scores.get("overall_scores", {}),
        "overall_for": scores.get("overall_for", 0.0),
        "overall_against": scores.get("overall_against", 0.0),
        "margin_d": scores.get("margin_d", 0.0),
        "ci_d_lower": verdict_result.get("ci_lower"),
        "ci_d_upper": verdict_result.get("ci_upper"),
        "confidence": verdict_result.get("confidence"),
        "verdict": verdict_result.get("verdict"),
        "topic_scores": scores.get("topic_scores", {}),
        "replay_manifest_json": replay_manifest,
        "input_hash_root": ctx.input_hash_root,
        "output_hash_root": ctx.output_hash_root,
        "recipe_versions_json": recipe_versions,
        "provider_metadata": ctx.provider_metadata or {},
        "fact_checker_version": "v1.5",
        "evidence_policy_version": "v1.5-default",
        "synthesis_rule_engine_version": "v1.5",
    }

    engine.db.save_snapshot(snapshot_data)

    debate = ctx.debate or {}
    debate["current_snapshot_id"] = snapshot_id
    engine.db.save_debate(debate)
    engine._debate_cache[debate_id] = engine._attach_active_frame(debate)

    for audit_type, audit_data in (ctx.audit_records or {}).items():
        engine.db.save_audit({
            "audit_id": f"audit_{snapshot_id}_{audit_type}",
            "snapshot_id": snapshot_id,
            "audit_type": audit_type,
            "result_data": audit_data,
            "created_at": datetime.now().isoformat(),
            "request_id": ctx.request_id,
        })

    frame_info = engine.get_frame_info()
    result = {
        **snapshot_data,
        "frame": frame_info,
        "leader": verdict_result.get("leader"),
        "runner_up": verdict_result.get("runner_up"),
        "topics": [
            {
                "topic_id": t.topic_id, "name": t.name, "scope": t.scope,
                "relevance": t.relevance, "drift_score": t.drift_score,
                "coherence": t.coherence, "distinctness": t.distinctness,
                "summary_for": t.summary_for, "summary_against": t.summary_against,
                "operation": t.operation, "parent_topic_ids": t.parent_topic_ids,
            }
            for t in topics
        ],
        "canonical_facts": ctx.canonical_facts or {},
        "canonical_arguments": ctx.canonical_args or {},
        "selected_facts": ctx.selected_facts or {},
        "selected_arguments": ctx.selected_args or {},
        "audits": ctx.audit_records or {},
        "counterfactuals": ctx.counterfactuals or [],
        "decision_dossier": ctx.decision_dossier or {},
    }

    ctx.snapshot_id = snapshot_id
    ctx.snapshot_data = snapshot_data
    ctx.result = result
    return ctx
