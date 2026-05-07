"""Frame blueprint — frames, cadence, emergency override, changelog."""

import json
import uuid
from typing import Any

from flask import Blueprint, g, jsonify, request

from backend import extensions
from backend.lsd_v1_2 import frame_mode as get_frame_mode_flag
from backend.utils.decorators import admin_required, optional_auth
from backend.utils.helpers import get_session_debate_id
from backend.utils.validators import validate_string

frame_bp = Blueprint("frame", __name__)


@frame_bp.route("/api/governance/frames", methods=["GET"])
@optional_auth
def get_frames() -> Any:
    """Get active frame and available frames.
    ---
    tags:
      - governance
      - frames
    security:
      - Bearer: []
    responses:
      200:
        description: Frame information
        schema:
          type: object
          properties:
            active_frame:
              type: object
            frames:
              type: array
              items:
                type: object
            mode:
              type: boolean
            frame_set_version:
              type: string
            review_schedule:
              type: array
              items:
                type: object
    """
    debate_id = get_session_debate_id()
    active_frame = extensions.db.get_active_debate_frame(debate_id) if debate_id else None
    frames = extensions.db.get_debate_frames(debate_id) if debate_id else []
    registry_frame = extensions.debate_engine.get_frame_info()
    frame_info = active_frame or registry_frame
    if frame_info and "statement" not in frame_info:
        dossier = {
            "statement": frame_info.get("frame_summary", ""),
            "scope": "; ".join(frame_info.get("scope_constraints", [])),
            "grounding_rationale": "Published active debate frame selected through the governance workflow.",
            "inclusion_justification": "; ".join(frame_info.get("evaluation_criteria", [])),
            "exclusion_note": frame_info.get("notes", ""),
            "known_tensions": frame_info.get("scope_constraints", []),
            "prioritized_values": frame_info.get("evaluation_criteria", [])[:4],
        }
        frame_info = {
            **frame_info,
            "statement": frame_info.get("frame_summary", ""),
            "scope": dossier["scope"],
            "dossier": dossier,
            "next_review_date": frame_info.get("review_date"),
            "review_cadence_months": frame_info.get("review_cadence_months", 6),
            "emergency_override_path": "Use /api/governance/emergency-override with a published rationale.",
        }
    return jsonify(
        {
            "active_frame": frame_info,
            "frames": frames,
            "mode": get_frame_mode_flag(),
            "frame_set_version": frame_info.get("version") if frame_info else None,
            "review_schedule": [
                {
                    "frame_id": frame.get("frame_id"),
                    "debate_id": frame.get("debate_id"),
                    "review_date": frame.get("review_date"),
                    "review_cadence_months": frame.get("review_cadence_months", 6),
                }
                for frame in frames
            ],
        }
    )


@frame_bp.route("/api/admin/frame-petitions/<petition_id>/accept", methods=["POST"])
@admin_required
def accept_frame_petition(petition_id: str) -> Any:
    """Accept a frame petition and activate a new frame version.
    ---
    tags:
      - admin
      - frames
    security:
      - Bearer: []
    parameters:
      - name: petition_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Frame petition accepted
        schema:
          type: object
          properties:
            petition:
              type: object
            debate:
              type: object
      404:
        description: Petition not found
    """
    petition = extensions.db.get_frame_petition(petition_id)
    if not petition:
        return jsonify({"error": "Petition not found"}), 404
    reviewer_user_id = (getattr(g, "user", None) or {}).get("user_id") or "admin"
    candidate = petition.get("candidate_frame") or {}
    try:
        debate = extensions.debate_engine.create_frame_version(petition["debate_id"], candidate)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    decision = {
        "decision": "accepted",
        "reason": (request.get_json() or {}).get("reason", "Accepted by admin governance review"),
        "activated_frame_id": debate.get("active_frame_id"),
    }
    updated = extensions.db.update_frame_petition_status(
        petition_id, "accepted", decision, reviewer_user_id
    )
    extensions.debate_engine.governance.log_change(
        change_type="frame",
        description=f"Accepted frame petition {petition_id}",
        changed_by=reviewer_user_id,
        justification=decision["reason"],
        new_value=debate.get("active_frame_id"),
    )
    return jsonify({"petition": updated, "debate": debate})


@frame_bp.route("/api/admin/frame-petitions/<petition_id>/reject", methods=["POST"])
@admin_required
def reject_frame_petition(petition_id: str) -> Any:
    """Reject a frame petition with a published governance decision.
    ---
    tags:
      - admin
      - frames
    security:
      - Bearer: []
    parameters:
      - name: petition_id
        in: path
        type: string
        required: true
      - name: body
        in: body
        required: false
        schema:
          type: object
          properties:
            reason:
              type: string
    responses:
      200:
        description: Frame petition rejected
        schema:
          type: object
          properties:
            petition:
              type: object
      404:
        description: Petition not found
    """
    petition = extensions.db.get_frame_petition(petition_id)
    if not petition:
        return jsonify({"error": "Petition not found"}), 404
    reviewer_user_id = (getattr(g, "user", None) or {}).get("user_id") or "admin"
    payload = request.get_json() or {}
    decision = {
        "decision": "rejected",
        "reason": payload.get("reason", "Rejected by admin governance review"),
    }
    updated = extensions.db.update_frame_petition_status(
        petition_id, "rejected", decision, reviewer_user_id
    )
    extensions.debate_engine.governance.log_change(
        change_type="frame",
        description=f"Rejected frame petition {petition_id}",
        changed_by=reviewer_user_id,
        justification=decision["reason"],
        previous_value=petition_id,
    )
    return jsonify({"petition": updated})


@frame_bp.route("/api/governance/frame-cadence", methods=["GET"])
@optional_auth
def get_frame_cadence() -> Any:
    """Get frame review cadence.
    ---
    tags:
      - governance
      - frames
    security:
      - Bearer: []
    responses:
      200:
        description: Frame cadence schedule
        schema:
          type: object
          properties:
            debate_id:
              type: string
            review_schedule:
              type: array
              items:
                type: object
    """
    debate_id = get_session_debate_id()
    frames = extensions.db.get_debate_frames(debate_id) if debate_id else []
    return jsonify(
        {
            "debate_id": debate_id,
            "review_schedule": [
                {
                    "frame_id": frame.get("frame_id"),
                    "version": frame.get("version"),
                    "review_date": frame.get("review_date"),
                    "review_cadence_months": frame.get("review_cadence_months", 6),
                    "governance_decision_id": frame.get("governance_decision_id"),
                }
                for frame in frames
            ],
        }
    )


@frame_bp.route("/api/governance/frame-cadence", methods=["POST"])
@admin_required
def set_frame_cadence() -> Any:
    """Set frame review cadence.
    ---
    tags:
      - governance
      - frames
    security:
      - Bearer: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            review_cadence_months:
              type: integer
            review_date:
              type: string
            justification:
              type: string
    responses:
      200:
        description: Updated frame cadence
      400:
        description: No active debate
    """
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({"error": "No active debate"}), 400
    payload = request.get_json() or {}
    cadence = int(payload.get("review_cadence_months") or 6)
    review_date = payload.get("review_date")
    extensions.db.update_frame_review_schedule(debate_id, review_date, cadence)
    extensions.debate_engine.governance.log_change(
        change_type="frame_cadence",
        description=f"Updated frame review cadence for {debate_id}",
        changed_by=(getattr(g, "user", None) or {}).get("user_id") or "admin",
        justification=payload.get("justification", "Frame stability review cadence update"),
        new_value=json.dumps({"review_date": review_date, "review_cadence_months": cadence}),
    )
    return get_frame_cadence()


@frame_bp.route("/api/governance/emergency-override", methods=["POST"])
@admin_required
def emergency_frame_override() -> Any:
    """Emergency frame override.
    ---
    tags:
      - governance
      - frames
    security:
      - Bearer: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            reason:
              type: string
              minLength: 10
              maxLength: 2000
            frame_id:
              type: string
    responses:
      200:
        description: Emergency override applied
        schema:
          type: object
          properties:
            governance_decision_id:
              type: string
            frame_id:
              type: string
            reason:
              type: string
      400:
        description: No active debate
      404:
        description: No active frame
    """
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({"error": "No active debate"}), 400
    payload = request.get_json() or {}
    reason = validate_string(
        payload.get("reason"), "Emergency reason", min_length=10, max_length=2000
    )
    target_frame_id = payload.get("frame_id")
    active = extensions.db.get_active_debate_frame(debate_id)
    frame_id = target_frame_id or (active or {}).get("frame_id")
    if not frame_id:
        return jsonify({"error": "No active frame"}), 404
    if target_frame_id:
        extensions.db.set_active_frame(debate_id, target_frame_id)
    actor = (getattr(g, "user", None) or {}).get("user_id") or "admin"
    governance_decision_id = f"gov_{uuid.uuid4().hex[:10]}"
    extensions.db.apply_emergency_override(frame_id, reason, actor, governance_decision_id)
    extensions.debate_engine.governance.log_change(
        change_type="emergency_override",
        description=f"Emergency frame override for {debate_id}",
        changed_by=actor,
        justification=reason,
        new_value=frame_id,
        approval_references=[governance_decision_id],
    )
    return jsonify(
        {
            "governance_decision_id": governance_decision_id,
            "frame_id": frame_id,
            "reason": reason,
        }
    )


@frame_bp.route("/api/governance/changelog", methods=["GET"])
@optional_auth
def get_changelog() -> Any:
    """Get system changelog.
    ---
    tags:
      - governance
    security:
      - Bearer: []
    parameters:
      - name: change_type
        in: query
        type: string
        required: false
      - name: limit
        in: query
        type: integer
        default: 100
    responses:
      200:
        description: Changelog entries
        schema:
          type: object
          properties:
            entries:
              type: array
              items:
                type: object
    """
    change_type = request.args.get("change_type")
    limit = request.args.get("limit", 100, type=int)
    entries = extensions.debate_engine.governance.get_changelog(
        change_type=change_type, limit=limit
    )
    return jsonify({"entries": entries})
