"""
Enhanced Flask API for Blind Debate Adjudicator v2
Uses the new debate engine with full MSD compliance
"""

import json
import os
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.debate_engine_v2 import DebateEngineV2
from backend.debate_proposal import hydrate_debate_record, parse_debate_proposal_payload

app = Flask(__name__, static_folder=None)
CORS(app)

# Initialize debate engine
# Use MOCK provider by default, can be overridden with env var
debate_engine = DebateEngineV2(
    db_path="data/debate_system.db",
    fact_check_mode=os.getenv("FACT_CHECK_MODE", "OFFLINE"),
    llm_provider=os.getenv("LLM_PROVIDER", "mock"),
    num_judges=int(os.getenv("NUM_JUDGES", "5")),
    openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
)

# Store for current debate
current_debate = None


def _debate_response_payload(debate):
    hydrated = hydrate_debate_record(debate) or {}
    active_frame = hydrated.get("active_frame")
    return {
        "debate_id": hydrated.get("debate_id"),
        "motion": hydrated.get("motion"),
        "resolution": hydrated.get("resolution"),
        "moderation_criteria": hydrated.get("moderation_criteria"),
        "debate_frame": hydrated.get("debate_frame"),
        "scope": hydrated.get("scope"),
        "active_frame_id": hydrated.get("active_frame_id"),
        "active_frame": active_frame,
        "created_at": hydrated.get("created_at"),
    }


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify(
        {
            "status": "healthy",
            "version": "2.0",
            "auth_enabled": False,
            "supports_frame_versioning": True,
            "timestamp": datetime.now().isoformat(),
        }
    )


@app.route("/api/debate", methods=["POST"])
def create_debate():
    """Create a new debate"""
    global current_debate

    data = request.json or {}
    proposal, missing_fields = parse_debate_proposal_payload(data)
    if missing_fields:
        return jsonify(
            {
                "error": f"Missing required fields: {', '.join(missing_fields)}",
                "missing_fields": missing_fields,
            }
        ), 400

    current_debate = debate_engine.create_debate(data)

    return jsonify(_debate_response_payload(current_debate))


@app.route("/api/debate", methods=["GET"])
def get_debate():
    """Get current debate info"""
    global current_debate

    if not current_debate:
        # Return empty state when no debate has been started
        return jsonify(
            {
                "debate_id": None,
                "motion": None,
                "resolution": None,
                "moderation_criteria": None,
                "debate_frame": None,
                "scope": None,
                "active_frame_id": None,
                "active_frame": None,
                "frame_count": 0,
                "created_at": None,
                "current_snapshot_id": None,
                "has_debate": False,
            }
        )

    payload = _debate_response_payload(current_debate)
    payload["frame_count"] = len(debate_engine.get_debate_frames(current_debate["debate_id"]))
    payload.update(
        {"current_snapshot_id": current_debate.get("current_snapshot_id"), "has_debate": True}
    )
    return jsonify(payload)


@app.route("/api/debate/frame", methods=["GET"])
def get_active_frame():
    """Get the active debate frame."""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    return jsonify(
        {
            "debate_id": current_debate["debate_id"],
            "active_frame": current_debate.get("active_frame"),
        }
    )


@app.route("/api/debate/frames", methods=["GET"])
def list_debate_frames():
    """List all debate frame versions."""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    frames = debate_engine.get_debate_frames(current_debate["debate_id"])
    return jsonify(
        {
            "debate_id": current_debate["debate_id"],
            "active_frame_id": current_debate.get("active_frame_id"),
            "frames": frames,
        }
    )


@app.route("/api/debate/frames", methods=["POST"])
def create_frame_version():
    """Create and activate a new frame version on the current debate."""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    data = request.json or {}
    try:
        current_debate = debate_engine.create_frame_version(
            current_debate["debate_id"],
            data,
        )
        return jsonify(_debate_response_payload(current_debate))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/debate/posts", methods=["POST"])
def submit_post():
    """Submit a new post"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    data = request.json or {}

    required = ["side", "facts", "inference"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Missing required field: {field}"}), 400

    post = debate_engine.submit_post(
        debate_id=current_debate["debate_id"],
        side=data["side"],
        topic_id=data.get("topic_id"),
        facts=data["facts"],
        inference=data["inference"],
        counter_arguments=data.get("counter_arguments", ""),
    )

    return jsonify(
        {
            "post_id": post["post_id"],
            "side": post["side"],
            "topic_id": post.get("topic_id"),
            "modulation_outcome": post["modulation_outcome"],
            "block_reason": post.get("block_reason"),
            "timestamp": post["timestamp"],
        }
    )


@app.route("/api/debate/snapshot", methods=["POST"])
def generate_snapshot():
    """Generate a new snapshot with full processing"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    data = request.json or {}
    trigger_type = data.get("trigger_type", "manual")

    try:
        snapshot = debate_engine.generate_snapshot(
            debate_id=current_debate["debate_id"], trigger_type=trigger_type
        )

        return jsonify(
            {
                "snapshot_id": snapshot["snapshot_id"],
                "frame_id": snapshot.get("frame_id"),
                "timestamp": snapshot["timestamp"],
                "trigger_type": snapshot["trigger_type"],
                "template_name": snapshot["template_name"],
                "template_version": snapshot["template_version"],
                "allowed_count": snapshot["allowed_count"],
                "blocked_count": snapshot["blocked_count"],
                "block_reasons": snapshot["block_reasons"],
                "side_order": snapshot.get("side_order", []),
                "overall_scores": snapshot.get("overall_scores", {}),
                "overall_for": snapshot["overall_for"],
                "overall_against": snapshot["overall_against"],
                "margin_d": snapshot["margin_d"],
                "ci_d": [snapshot["ci_d_lower"], snapshot["ci_d_upper"]],
                "confidence": snapshot["confidence"],
                "verdict": snapshot["verdict"],
                "leader": snapshot.get("leader"),
                "runner_up": snapshot.get("runner_up"),
                "num_topics": len(snapshot.get("topics", [])),
                "audits_available": list(snapshot.get("audits", {}).keys()),
            }
        )

    except Exception as e:
        import traceback

        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/debate/snapshot", methods=["GET"])
def get_current_snapshot():
    """Get current snapshot data"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate", "has_debate": False}), 400

    # Get latest snapshot from database
    snapshot = debate_engine.db.get_latest_snapshot(
        current_debate["debate_id"],
        frame_id=current_debate.get("active_frame_id"),
    )

    if not snapshot:
        # Return empty state when debate exists but no snapshot yet
        return jsonify(
            {
                "has_debate": True,
                "has_snapshot": False,
                "snapshot_id": None,
                "frame_id": current_debate.get("active_frame_id"),
                "timestamp": None,
                "trigger_type": None,
                "template_name": None,
                "template_version": None,
                "allowed_count": 0,
                "blocked_count": 0,
                "block_reasons": {},
                "side_order": [],
                "overall_scores": {},
                "overall_for": None,
                "overall_against": None,
                "margin_d": None,
                "ci_d": None,
                "confidence": None,
                "verdict": "NO VERDICT",
            }
        )

    return jsonify(
        {
            "has_debate": True,
            "has_snapshot": True,
            "snapshot_id": snapshot["snapshot_id"],
            "frame_id": snapshot.get("frame_id"),
            "timestamp": snapshot["timestamp"],
            "trigger_type": snapshot["trigger_type"],
            "template_name": snapshot["template_name"],
            "template_version": snapshot["template_version"],
            "allowed_count": snapshot["allowed_count"],
            "blocked_count": snapshot["blocked_count"],
            "block_reasons": json.loads(snapshot.get("block_reasons", "{}")),
            "side_order": json.loads(snapshot.get("side_order", "[]")),
            "overall_scores": json.loads(snapshot.get("overall_scores", "{}")),
            "overall_for": snapshot["overall_for"],
            "overall_against": snapshot["overall_against"],
            "margin_d": snapshot["margin_d"],
            "ci_d": [snapshot["ci_d_lower"], snapshot["ci_d_upper"]],
            "confidence": snapshot["confidence"],
            "verdict": snapshot["verdict"],
        }
    )


@app.route("/api/debate/topics", methods=["GET"])
def get_topics():
    """Get all topics with scores"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    # Get topics from database
    topics = debate_engine.db.get_topics_by_debate(
        current_debate["debate_id"],
        frame_id=current_debate.get("active_frame_id"),
    )

    if not topics:
        return jsonify({"topics": [], "side_order": []})

    # Get latest snapshot for scores
    snapshot = debate_engine.db.get_latest_snapshot(
        current_debate["debate_id"],
        frame_id=current_debate.get("active_frame_id"),
    )
    topic_scores = {}
    side_order = []

    if snapshot:
        topic_scores = json.loads(snapshot.get("topic_scores", "{}"))
        side_order = json.loads(snapshot.get("side_order", "[]"))

    topics_data = []
    for topic in topics:
        tid = topic["topic_id"]
        scores_by_side = topic_scores.get(tid, {})

        topics_data.append(
            {
                "topic_id": tid,
                "name": topic["name"],
                "scope": topic["scope"],
                "relevance": topic["relevance"],
                "drift_score": topic["drift_score"],
                "coherence": topic["coherence"],
                "distinctness": topic["distinctness"],
                "summary_for": topic.get("summary_for", ""),
                "summary_against": topic.get("summary_against", ""),
                "operation": topic.get("operation", "created"),
                "parent_topic_ids": json.loads(topic.get("parent_topic_ids", "[]")),
                "scores_by_side": scores_by_side,
                "scores": {
                    "FOR": scores_by_side.get("FOR", {}),
                    "AGAINST": scores_by_side.get("AGAINST", {}),
                },
            }
        )

    return jsonify({"topics": topics_data, "side_order": side_order})


@app.route("/api/debate/topics/<topic_id>/facts", methods=["GET"])
def get_topic_facts(topic_id):
    """Get facts for a topic"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    facts = debate_engine.db.get_canonical_facts_by_topic(topic_id)

    return jsonify(
        {
            "topic_id": topic_id,
            "facts": [
                {
                    "canon_fact_id": f["canon_fact_id"],
                    "canon_fact_text": f["canon_fact_text"],
                    "side": f["side"],
                    "p_true": f["p_true"],
                    "member_count": len(json.loads(f.get("member_fact_ids", "[]"))),
                }
                for f in facts
            ],
        }
    )


@app.route("/api/debate/topics/<topic_id>/arguments", methods=["GET"])
def get_topic_arguments(topic_id):
    """Get arguments for a topic"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    args = debate_engine.db.get_canonical_arguments_by_topic(topic_id)

    return jsonify(
        {
            "topic_id": topic_id,
            "arguments": [
                {
                    "canon_arg_id": a["canon_arg_id"],
                    "side": a["side"],
                    "inference_text": a["inference_text"],
                    "supporting_facts": json.loads(a.get("supporting_facts", "[]")),
                    "member_count": len(json.loads(a.get("member_au_ids", "[]"))),
                    "reasoning_score": a.get("reasoning_score", 0.5),
                }
                for a in args
            ],
        }
    )


@app.route("/api/debate/verdict", methods=["GET"])
def get_verdict():
    """Get complete verdict data"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    snapshot = debate_engine.db.get_latest_snapshot(
        current_debate["debate_id"],
        frame_id=current_debate.get("active_frame_id"),
    )

    if not snapshot:
        return jsonify({"error": "No snapshot available"}), 404

    # Build topic contributions
    topic_scores = json.loads(snapshot.get("topic_scores", "{}"))
    overall_scores = json.loads(snapshot.get("overall_scores", "{}"))
    side_order = json.loads(snapshot.get("side_order", "[]"))
    topics = debate_engine.db.get_topics_by_debate(
        current_debate["debate_id"],
        frame_id=current_debate.get("active_frame_id"),
    )

    contributions = []
    for topic in topics:
        tid = topic["topic_id"]
        scores_by_side = topic_scores.get(tid, {})
        ordered_sides = sorted(
            scores_by_side.items(),
            key=lambda item: (-item[1].get("quality", 0), item[0]),
        )
        leader_side = ordered_sides[0][0] if ordered_sides else None
        runner_up_side = ordered_sides[1][0] if len(ordered_sides) > 1 else None
        lead_quality = ordered_sides[0][1].get("quality", 0) if ordered_sides else 0
        runner_up_quality = ordered_sides[1][1].get("quality", 0) if len(ordered_sides) > 1 else 0
        contribution = topic["relevance"] * (lead_quality - runner_up_quality)
        contributions.append(
            {
                "topic_id": tid,
                "name": topic["name"],
                "relevance": topic["relevance"],
                "scores_by_side": scores_by_side,
                "q_for": scores_by_side.get("FOR", {}).get("quality", 0),
                "q_against": scores_by_side.get("AGAINST", {}).get("quality", 0),
                "leader_side": leader_side,
                "runner_up_side": runner_up_side,
                "contribution_to_d": round(contribution, 4),
            }
        )

    return jsonify(
        {
            "snapshot_id": snapshot["snapshot_id"],
            "frame_id": snapshot.get("frame_id"),
            "side_order": side_order,
            "overall_scores": overall_scores,
            "overall_for": snapshot["overall_for"],
            "overall_against": snapshot["overall_against"],
            "margin_d": snapshot["margin_d"],
            "ci_d": [snapshot["ci_d_lower"], snapshot["ci_d_upper"]],
            "confidence": snapshot["confidence"],
            "verdict": snapshot["verdict"],
            "leader": json.loads(snapshot.get("overall_scores", "{}"))
            and max(overall_scores.items(), key=lambda item: item[1])[0]
            if overall_scores
            else None,
            "topic_contributions": contributions,
        }
    )


@app.route("/api/debate/audits", methods=["GET"])
def get_audits():
    """Get audit data"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    snapshot = debate_engine.db.get_latest_snapshot(
        current_debate["debate_id"],
        frame_id=current_debate.get("active_frame_id"),
    )

    if not snapshot:
        return jsonify({"error": "No snapshot available"}), 404

    # Get audits for this snapshot
    audits = debate_engine.get_audits_for_snapshot(snapshot["snapshot_id"])

    # Get topic geometry
    topics = debate_engine.db.get_topics_by_debate(
        current_debate["debate_id"],
        frame_id=current_debate.get("active_frame_id"),
    )
    topic_geometry = [
        {
            "topic_id": t["topic_id"],
            "content_mass": t["relevance"],
            "drift_score": t["drift_score"],
            "coherence": t["coherence"],
            "distinctness": t["distinctness"],
            "operation": t.get("operation", "created"),
        }
        for t in topics
    ]

    # Build response
    extraction_stability = audits.get("extraction_stability", {})
    side_label_symmetry = audits.get("side_label_symmetry", {})
    relevance_sensitivity = audits.get("relevance_sensitivity", {})

    return jsonify(
        {
            "snapshot_id": snapshot["snapshot_id"],
            "topic_geometry": topic_geometry,
            "extraction_stability": {
                "fact_overlap": extraction_stability.get("fact_overlap", {}),
                "argument_overlap": extraction_stability.get("argument_overlap", {}),
                "mismatches": extraction_stability.get("mismatches", []),
                "stability_score": extraction_stability.get("stability_score", 0),
            },
            "evaluator_disagreement": {
                "reasoning_iqr_median": 0.19,  # Would come from actual judge disagreements
                "coverage_iqr_median": 0.16,
                "overall_iqr": 0.06,
            },
            "label_symmetry": {
                "median_delta_d": side_label_symmetry.get("median_delta_d", 0),
                "abs_delta_d": side_label_symmetry.get("abs_delta_d", 0),
                "interpretation": side_label_symmetry.get("interpretation", ""),
            },
            "relevance_sensitivity": relevance_sensitivity,
        }
    )


@app.route("/api/debate/evidence", methods=["GET"])
def get_evidence_targets():
    """Get 'what evidence would change this' targets"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    snapshot = debate_engine.db.get_latest_snapshot(
        current_debate["debate_id"],
        frame_id=current_debate.get("active_frame_id"),
    )

    if not snapshot:
        return jsonify({"error": "No snapshot available"}), 404

    # Get all facts
    all_facts = []
    topics = debate_engine.db.get_topics_by_debate(
        current_debate["debate_id"],
        frame_id=current_debate.get("active_frame_id"),
    )
    for topic in topics:
        facts = debate_engine.db.get_canonical_facts_by_topic(topic["topic_id"])
        all_facts.extend(facts)

    # Find high-leverage facts (those with p near 0.5)
    targets = []
    for f in all_facts:
        p_true = f.get("p_true", 0.5)
        decisiveness = abs(p_true - 0.5)

        if decisiveness < 0.15:  # Near 0.5
            targets.append(
                {
                    "topic_id": f["topic_id"],
                    "fact_id": f["canon_fact_id"],
                    "fact_text": f["canon_fact_text"],
                    "p_true": p_true,
                    "decisiveness": round(decisiveness, 2),
                    "why_matters": f"Fact with high uncertainty (p ≈ {p_true:.2f}). New evidence could significantly change the outcome.",
                    "evidence_needed": "Independent empirical studies with clear findings",
                }
            )

    # Sort by decisiveness (lowest first = most uncertain)
    targets.sort(key=lambda x: x["decisiveness"])

    return jsonify(
        {
            "high_leverage_targets": targets[:5],
            "update_triggers": [
                "If uncertain facts (p ≈ 0.5) move to strongly supported (p > 0.75), their supporting arguments gain leverage",
                "If high-leverage facts are contradicted (p < 0.3), their arguments lose significant weight",
                "New evidence on borderline facts can flip topic-level quality scores",
            ],
        }
    )


@app.route("/api/debate/topic-lineage", methods=["GET"])
def get_topic_lineage():
    """Get topic lineage across snapshots"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    lineage = debate_engine.get_topic_lineage(current_debate["debate_id"])

    return jsonify({"lineage": lineage})


@app.route("/api/debate/snapshot-history", methods=["GET"])
def get_snapshot_history():
    """Get chronological snapshot history for the debate (MSD §16)"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    history = debate_engine.get_snapshot_history(current_debate["debate_id"])

    return jsonify(
        {
            "debate_id": current_debate["debate_id"],
            "snapshot_count": len(history),
            "snapshots": history,
        }
    )


@app.route("/api/debate/snapshot-diff", methods=["GET"])
def get_snapshot_diff():
    """
    Compare two snapshots (MSD §16).
    Query params: old_snapshot_id, new_snapshot_id
    If not provided, compares the two most recent snapshots.
    """
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    old_id = request.args.get("old_snapshot_id")
    new_id = request.args.get("new_snapshot_id")

    try:
        if old_id and new_id:
            # Compare specific snapshots
            diff = debate_engine.diff_snapshots(old_id, new_id)
        else:
            # Compare most recent consecutive snapshots
            diff = debate_engine.compare_consecutive_snapshots(current_debate["debate_id"])
            if diff is None:
                return jsonify({"error": "Need at least 2 snapshots for comparison"}), 400

        return jsonify(diff)

    except Exception as e:
        import traceback

        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/debate/modulation-info", methods=["GET"])
def get_modulation_info():
    """Get current modulation template info (MSD §3)"""
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    info = debate_engine.get_modulation_info()

    return jsonify(info)


@app.route("/api/debate/modulation-templates", methods=["GET"])
def list_modulation_templates():
    """List available modulation templates (MSD §3)"""
    from modulation import ModulationEngine

    templates = ModulationEngine.list_builtin_templates()

    return jsonify(
        {
            "templates": templates,
            "current_debate_template": debate_engine.modulation_engine.template.template_id
            if current_debate
            else None,
        }
    )


@app.route("/api/debate/evidence-targets", methods=["GET"])
def get_evidence_targets_v2():
    """
    Get 'what evidence would change this' analysis (MSD §15).
    Enhanced version using the EvidenceTargetAnalyzer.
    """
    global current_debate

    if not current_debate:
        return jsonify({"error": "No active debate"}), 400

    snapshot_id = request.args.get("snapshot_id")

    try:
        targets = debate_engine.get_evidence_targets(current_debate["debate_id"], snapshot_id)
        return jsonify(targets)

    except Exception as e:
        import traceback

        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


# Static file serving
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    """Serve static frontend files"""
    if not path:
        path = "index.html"

    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")

    try:
        return send_from_directory(frontend_dir, path)
    except Exception:
        return send_from_directory(frontend_dir, "index.html")


if __name__ == "__main__":
    # Start with no debate - user must create one via the UI
    current_debate = None

    print("=" * 60)
    print("Blind Debate Adjudicator Server v2")
    print("=" * 60)
    print("No active debate - create one via the New Debate page")
    print("-" * 60)
    print("API available at: http://localhost:5000")
    print("Web UI available at: http://localhost:5000")
    print("=" * 60)

    app.run(host="0.0.0.0", port=5000, debug=True)
