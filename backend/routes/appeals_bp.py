"""Appeals blueprint — appeals submission and resolution."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from backend import extensions
from backend.utils.decorators import admin_required, log_admin_action, login_required
from backend.utils.helpers import get_session_debate_id
from backend.utils.validators import validate_string

appeals_bp = Blueprint("appeals", __name__)


@appeals_bp.route("/api/governance/appeals", methods=["GET"])
@login_required
def get_appeals() -> Any:
    """Get appeals.
    ---
    tags:
      - governance
      - appeals
    security:
      - Bearer: []
    parameters:
      - name: status
        in: query
        type: string
        required: false
      - name: limit
        in: query
        type: integer
        default: 100
    responses:
      200:
        description: Appeals list
        schema:
          type: object
          properties:
            appeals:
              type: array
              items:
                type: object
    """
    debate_id = get_session_debate_id()
    status = request.args.get("status")
    limit = request.args.get("limit", 100, type=int)
    from backend.governance import AppealStatus

    status_enum = None
    if status:
        try:
            status_enum = AppealStatus(status)
        except ValueError:
            return jsonify({"error": "Invalid status"}), 400
    appeals = extensions.debate_engine.governance.get_appeals(
        debate_id=debate_id, status=status_enum, limit=limit
    )
    return jsonify({"appeals": appeals})


@appeals_bp.route("/api/debate/<debate_id>/appeals", methods=["POST"])
@login_required
def submit_appeal(debate_id: str) -> Any:
    """Submit a new appeal for a specific debate.
    ---
    tags:
      - governance
      - appeals
    security:
      - Bearer: []
    parameters:
      - name: debate_id
        in: path
        type: string
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - description
          properties:
            appeal_type:
              type: string
              enum: [moderation_error, topic_misframing, missing_argument, provenance_error]
            description:
              type: string
              minLength: 10
              maxLength: 2000
            evidence_references:
              type: array
              items:
                type: string
            requested_relief:
              type: string
    responses:
      201:
        description: Appeal submitted
        schema:
          type: object
          properties:
            appeal_id:
              type: string
            status:
              type: string
      400:
        description: Invalid appeal type
      404:
        description: No snapshot available
    """
    snapshot = extensions.db.get_latest_snapshot(debate_id)
    if not snapshot:
        return jsonify({"error": "No snapshot available"}), 404
    data = request.get_json() or {}
    appeal_type = validate_string(
        data.get("appeal_type", "moderation_error"), "Appeal type", max_length=50
    )
    valid_types = ["moderation_error", "topic_misframing", "missing_argument", "provenance_error"]
    if appeal_type not in valid_types:
        return jsonify({"error": f"Invalid appeal type. Must be one of: {valid_types}"}), 400
    description = validate_string(
        data.get("description") or data.get("grounds"),
        "Description",
        min_length=10,
        max_length=2000,
    )
    evidence = data.get("evidence_references", [])
    relief = validate_string(
        data.get("requested_relief") or "Review and correct snapshot.",
        "Requested relief",
        min_length=5,
        max_length=500,
    )
    appeal_id = extensions.debate_engine.governance.submit_appeal(
        debate_id=debate_id,
        snapshot_id=snapshot["snapshot_id"],
        claimant_id=g.user["user_id"],
        grounds=f"[{appeal_type}] {description}",
        evidence_references=evidence if isinstance(evidence, list) else [],
        requested_relief=relief,
    )
    return jsonify({"appeal_id": appeal_id, "status": "submitted"}), 201


@appeals_bp.route("/api/debate/<debate_id>/appeals/mine", methods=["GET"])
@login_required
def get_my_appeals(debate_id: str) -> Any:
    """Get appeals submitted by the current user for a debate.
    ---
    tags:
      - governance
      - appeals
    security:
      - Bearer: []
    parameters:
      - name: debate_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: User appeals
        schema:
          type: object
          properties:
            appeals:
              type: array
              items:
                type: object
    """
    appeals = extensions.debate_engine.governance.get_appeals(debate_id=debate_id, limit=500)
    my_appeals = [a for a in appeals if a.get("claimant_id") == g.user["user_id"]]
    return jsonify({"appeals": my_appeals})


@appeals_bp.route("/api/admin/appeals", methods=["GET"])
@admin_required
def get_admin_appeals() -> Any:
    """Admin queue: get all appeals.
    ---
    tags:
      - admin
      - appeals
    security:
      - Bearer: []
    parameters:
      - name: status
        in: query
        type: string
        required: false
    responses:
      200:
        description: All appeals
        schema:
          type: object
          properties:
            appeals:
              type: array
              items:
                type: object
    """
    status = request.args.get("status")
    from backend.governance import AppealStatus

    status_enum = None
    if status:
        try:
            status_enum = AppealStatus(status)
        except ValueError:
            return jsonify({"error": "Invalid status"}), 400
    appeals = extensions.debate_engine.governance.get_appeals(status=status_enum, limit=500)
    return jsonify({"appeals": appeals})


@appeals_bp.route("/api/admin/appeals/<appeal_id>/resolve", methods=["POST"])
@admin_required
def resolve_appeal(appeal_id: str) -> Any:
    """Admin action: resolve an appeal with published rationale.
    ---
    tags:
      - admin
      - appeals
    security:
      - Bearer: []
    parameters:
      - name: appeal_id
        in: path
        type: string
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - decision
            - decision_reason
          properties:
            decision:
              type: string
              enum: [accepted, rejected]
            decision_reason:
              type: string
              minLength: 10
              maxLength: 2000
            resolution:
              type: string
    responses:
      200:
        description: Appeal resolved
        schema:
          type: object
          properties:
            appeal_id:
              type: string
            status:
              type: string
            reason:
              type: string
      400:
        description: Invalid decision
      404:
        description: Appeal not found
    """
    data = request.get_json() or {}
    decision = validate_string(data.get("decision"), "Decision", max_length=20)
    valid_decisions = ["accepted", "rejected"]
    if decision not in valid_decisions:
        return jsonify({"error": f"Decision must be one of: {valid_decisions}"}), 400
    decision_reason = validate_string(
        data.get("decision_reason"), "Decision reason", min_length=10, max_length=2000
    )
    resolution = data.get("resolution", "")
    from backend.governance import AppealStatus

    status = AppealStatus.ACCEPTED if decision == "accepted" else AppealStatus.REJECTED
    success = extensions.debate_engine.governance.review_appeal(
        appeal_id=appeal_id,
        reviewer_id=g.user["user_id"],
        decision=status,
        decision_reason=decision_reason,
        resolution=resolution,
    )
    if not success:
        return jsonify({"error": "Appeal not found or already resolved"}), 404
    if decision == "accepted":
        appeals = extensions.debate_engine.governance.get_appeals(limit=500)
        appeal = next((a for a in appeals if a["appeal_id"] == appeal_id), None)
        if appeal:
            extensions.db.update_snapshot_status(appeal["snapshot_id"], "superseded")
    log_admin_action("appeal_resolve", f"Resolved appeal {appeal_id} as {decision}")
    return jsonify({"appeal_id": appeal_id, "status": decision, "reason": decision_reason}), 200
