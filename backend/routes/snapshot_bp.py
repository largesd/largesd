"""Snapshot blueprint — snapshot generation, polling, retrieval, history, diff."""

import json
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request

from backend import extensions
from backend.job_queue import JobStatus
from backend.utils.decorators import (
    get_admin_access_mode,
    is_user_in_restricted_admin_list,
    login_required,
    optional_auth,
)
from backend.utils.helpers import get_session_debate_id
from backend.utils.validators import ValidationError, validate_string

snapshot_bp = Blueprint("snapshot", __name__)


@snapshot_bp.route("/api/debate/snapshot", methods=["POST"])
@login_required
def generate_snapshot() -> Any:
    """Enqueue a new snapshot generation job and return job_id for polling.
    ---
    tags:
      - snapshots
    security:
      - Bearer: []
    parameters:
      - name: body
        in: body
        required: false
        schema:
          type: object
          properties:
            trigger_type:
              type: string
              enum: [manual, activity, time, scheduled]
              default: manual
    responses:
      202:
        description: Snapshot generation queued
        schema:
          type: object
          properties:
            job_id:
              type: string
            status:
              type: string
            message:
              type: string
      400:
        description: No active debate
      403:
        description: Access denied
      404:
        description: Debate not found
    """
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({"error": "No active debate"}), 400

    data = request.get_json() or {}
    trigger_type = validate_string(
        data.get("trigger_type", "manual"), "Trigger type", required=False, max_length=50
    )
    valid_triggers = ["manual", "activity", "time", "scheduled"]
    if trigger_type not in valid_triggers:
        raise ValidationError(f"Trigger type must be one of: {', '.join(valid_triggers)}")

    debate = extensions.db.get_debate(debate_id)
    if not debate:
        return jsonify({"error": "Debate not found"}), 404
    if debate.get("is_private") and debate.get("user_id") != g.user["user_id"]:
        return jsonify({"error": "Access denied"}), 403

    job_id = extensions.job_queue.create_job(
        "snapshot",
        {
            "debate_id": debate_id,
            "trigger_type": trigger_type,
            "user_id": g.user["user_id"],
        },
        runtime_profile_id=extensions.current_runtime_profile["runtime_profile_id"],
        request_id=getattr(g, "request_id", None),
    )

    return jsonify(
        {
            "job_id": job_id,
            "status": "queued",
            "message": "Snapshot generation queued. Poll /api/debate/snapshot-jobs/<job_id> for status.",
        }
    ), 202


@snapshot_bp.route("/api/debate/snapshot-jobs/<job_id>", methods=["GET"])
@login_required
def get_snapshot_job(job_id: str) -> Any:
    """Poll snapshot job status and result.
    ---
    tags:
      - snapshots
    security:
      - Bearer: []
    parameters:
      - name: job_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Job status
        schema:
          type: object
          properties:
            job_id:
              type: string
            status:
              type: string
            progress:
              type: integer
            snapshot_summary:
              type: object
      403:
        description: Access denied
      404:
        description: Job not found
    """
    job = extensions.job_queue.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    job_user_id = (job.parameters or {}).get("user_id")
    if job_user_id and g.user["user_id"] != job_user_id:
        mode = get_admin_access_mode()
        if mode != "open" and not is_user_in_restricted_admin_list(g.user):
            return jsonify({"error": "Access denied"}), 403

    result = extensions.job_queue.to_public_dict(job)
    if job.status == JobStatus.COMPLETED and job.result:
        result["snapshot_summary"] = {
            "snapshot_id": job.result.get("snapshot_id"),
            "verdict": job.result.get("verdict"),
            "confidence": job.result.get("confidence"),
            "status": job.result.get("status"),
        }
    return jsonify(result)


@snapshot_bp.route("/api/debate/snapshot", methods=["GET"])
@optional_auth
def get_current_snapshot() -> Any:
    """Get current snapshot for the active debate.
    ---
    tags:
      - snapshots
    security:
      - Bearer: []
    responses:
      200:
        description: Current snapshot
        schema:
          type: object
          properties:
            has_debate:
              type: boolean
            has_snapshot:
              type: boolean
            snapshot_id:
              type: string
            timestamp:
              type: string
            trigger_type:
              type: string
            template_name:
              type: string
            allowed_count:
              type: integer
            blocked_count:
              type: integer
            block_reasons:
              type: object
            borderline_rate:
              type: number
            status:
              type: string
            overall_for:
              type: number
            overall_against:
              type: number
            margin_d:
              type: number
            ci_d:
              type: array
              items:
                type: number
            confidence:
              type: number
            verdict:
              type: string
            frame_mode:
              type: boolean
            review_cadence_months:
              type: integer
            policy_context:
              type: object
      400:
        description: No active debate
    """
    from backend.lsd_v1_2 import frame_mode as get_frame_mode_flag

    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({"error": "No active debate", "has_debate": False}), 400

    snapshot = extensions.db.get_latest_snapshot(debate_id)
    frame_info = extensions.db.get_active_debate_frame(debate_id) if debate_id else None
    moderation_template = extensions.db.get_active_moderation_template() or {}
    policy_context = {
        "moderation_template_name": moderation_template.get("template_name")
        or moderation_template.get("name"),
        "moderation_template_version": moderation_template.get("version"),
    }

    if not snapshot:
        return jsonify(
            {
                "has_debate": True,
                "has_snapshot": False,
                "snapshot_id": None,
                "timestamp": None,
                "trigger_type": None,
                "template_name": None,
                "template_version": None,
                "allowed_count": 0,
                "blocked_count": 0,
                "block_reasons": {},
                "borderline_rate": 0.0,
                "suppression_policy": {"k": 5, "affected_buckets": [], "affected_bucket_count": 0},
                "status": "valid",
                "overall_for": None,
                "overall_against": None,
                "margin_d": None,
                "ci_d": None,
                "confidence": None,
                "verdict": "NO VERDICT",
                "frame_mode": frame_info.get("frame_mode") if frame_info else get_frame_mode_flag(),
                "review_cadence_months": frame_info.get("review_cadence_months", 6)
                if frame_info
                else 6,
                "policy_context": policy_context,
            }
        )

    return jsonify(
        {
            "has_debate": True,
            "has_snapshot": True,
            "snapshot_id": snapshot["snapshot_id"],
            "timestamp": snapshot["timestamp"],
            "trigger_type": snapshot["trigger_type"],
            "template_name": snapshot["template_name"],
            "template_version": snapshot["template_version"],
            "allowed_count": snapshot["allowed_count"],
            "blocked_count": snapshot["blocked_count"],
            "block_reasons": json.loads(snapshot.get("block_reasons", "{}")),
            "borderline_rate": snapshot.get("borderline_rate", 0.0) or 0.0,
            "suppression_policy": json.loads(snapshot.get("suppression_policy_json", "{}") or "{}"),
            "status": snapshot.get("status", "valid") or "valid",
            "overall_for": snapshot["overall_for"],
            "overall_against": snapshot["overall_against"],
            "margin_d": snapshot["margin_d"],
            "ci_d": [snapshot["ci_d_lower"], snapshot["ci_d_upper"]],
            "confidence": snapshot["confidence"],
            "verdict": snapshot["verdict"],
            "replay_manifest": json.loads(snapshot.get("replay_manifest_json", "{}") or "{}"),
            "input_hash_root": snapshot.get("input_hash_root"),
            "output_hash_root": snapshot.get("output_hash_root"),
            "recipe_versions": json.loads(snapshot.get("recipe_versions_json", "{}") or "{}"),
            "provider_metadata": json.loads(snapshot.get("provider_metadata_json", "{}") or "{}"),
            "cost_estimate": snapshot.get("cost_estimate"),
            "frame_mode": frame_info.get("frame_mode") if frame_info else get_frame_mode_flag(),
            "review_cadence_months": frame_info.get("review_cadence_months", 6)
            if frame_info
            else 6,
            "policy_context": policy_context,
        }
    )


@snapshot_bp.route("/api/debate/snapshot-history", methods=["GET"])
@optional_auth
def get_snapshot_history() -> Any:
    """Get snapshot history for the active debate.
    ---
    tags:
      - snapshots
    security:
      - Bearer: []
    responses:
      200:
        description: Snapshot history
        schema:
          type: object
          properties:
            debate_id:
              type: string
            snapshot_count:
              type: integer
            snapshots:
              type: array
              items:
                type: object
      400:
        description: No active debate
    """
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({"error": "No active debate"}), 400
    history = extensions.debate_engine.get_snapshot_history(debate_id)
    return jsonify({"debate_id": debate_id, "snapshot_count": len(history), "snapshots": history})


@snapshot_bp.route("/api/debate/snapshot-diff", methods=["GET"])
@optional_auth
def get_snapshot_diff() -> Any:
    """Compare two snapshots.
    ---
    tags:
      - snapshots
    security:
      - Bearer: []
    parameters:
      - name: old_snapshot_id
        in: query
        type: string
        required: false
      - name: new_snapshot_id
        in: query
        type: string
        required: false
    responses:
      200:
        description: Snapshot diff
        schema:
          type: object
      400:
        description: No active debate or insufficient snapshots
      500:
        description: Failed to compare snapshots
    """
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({"error": "No active debate"}), 400
    old_id = request.args.get("old_snapshot_id")
    new_id = request.args.get("new_snapshot_id")
    try:
        if old_id and new_id:
            diff = extensions.debate_engine.diff_snapshots(old_id, new_id)
        else:
            diff = extensions.debate_engine.compare_consecutive_snapshots(debate_id)
            if diff is None:
                return jsonify({"error": "Need at least 2 snapshots for comparison"}), 400
        return jsonify(diff)
    except Exception as e:
        current_app.logger.error(f"Snapshot diff error: {str(e)}")
        return jsonify({"error": "Failed to compare snapshots", "code": "DIFF_ERROR"}), 500
