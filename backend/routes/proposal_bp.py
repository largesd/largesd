"""Debate proposal blueprint — user proposals and admin review queue."""

import uuid
from datetime import datetime
from typing import Any

from flask import Blueprint, g, jsonify, request

from backend import extensions
from backend.sanitize import sanitize_html
from backend.utils.decorators import admin_required, login_required
from backend.utils.validators import ValidationError, validate_string

proposal_bp = Blueprint("proposal", __name__)


# ---------------------------------------------------------------------------
# User proposals
# ---------------------------------------------------------------------------
@proposal_bp.route("/api/debate-proposals", methods=["POST"])
@login_required
def submit_debate_proposal() -> Any:
    """Submit a new debate proposal (regular users).
    ---
    tags:
      - proposals
    security:
      - Bearer: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - motion
            - moderation_criteria
          properties:
            motion:
              type: string
            moderation_criteria:
              type: string
            debate_frame:
              type: string
            active_frame:
              type: object
    responses:
      201:
        description: Proposal submitted
        schema:
          type: object
          properties:
            proposal_id:
              type: string
            status:
              type: string
            message:
              type: string
    """
    from backend.debate_proposal import parse_debate_proposal_payload

    data = request.get_json()
    if not data:
        raise ValidationError("Request body required")

    proposal, missing_fields = parse_debate_proposal_payload(data)
    if missing_fields:
        raise ValidationError(f"Missing required fields: {', '.join(missing_fields)}")

    proposal_id = f"prop_{uuid.uuid4().hex[:10]}"
    now = datetime.now().isoformat()

    extensions.db.save_debate_proposal(
        {
            "proposal_id": proposal_id,
            "proposer_user_id": g.user["user_id"],
            "motion": proposal["motion"],
            "moderation_criteria": proposal["moderation_criteria"],
            "debate_frame": proposal.get("debate_frame", ""),
            "frame_payload_json": proposal.get("active_frame", {}),
            "status": "pending",
            "decision_reason": None,
            "reviewer_user_id": None,
            "reviewed_at": None,
            "accepted_debate_id": None,
            "created_at": now,
            "updated_at": now,
        }
    )

    return jsonify(
        {
            "proposal_id": proposal_id,
            "status": "pending",
            "message": "Proposal submitted for review",
        }
    ), 201


@proposal_bp.route("/api/debate-proposals/mine", methods=["GET"])
@login_required
def get_my_proposals() -> Any:
    """Get current user's debate proposals.
    ---
    tags:
      - proposals
    security:
      - Bearer: []
    responses:
      200:
        description: User proposals
        schema:
          type: object
          properties:
            proposals:
              type: array
              items:
                type: object
                properties:
                  proposal_id:
                    type: string
                  motion:
                    type: string
                  status:
                    type: string
                  decision_reason:
                    type: string
                  accepted_debate_id:
                    type: string
                  created_at:
                    type: string
                  reviewed_at:
                    type: string
    """
    proposals = extensions.db.get_debate_proposals_by_user(g.user["user_id"])
    return jsonify(
        {
            "proposals": [
                {
                    "proposal_id": p["proposal_id"],
                    "motion": p["motion"],
                    "status": p["status"],
                    "decision_reason": p.get("decision_reason"),
                    "accepted_debate_id": p.get("accepted_debate_id"),
                    "created_at": p["created_at"],
                    "reviewed_at": p.get("reviewed_at"),
                }
                for p in proposals
            ]
        }
    )


# ---------------------------------------------------------------------------
# Admin proposal queue
# ---------------------------------------------------------------------------
@proposal_bp.route("/api/admin/debate-proposals", methods=["GET"])
@admin_required
def list_proposal_queue() -> Any:
    """Admin queue: list debate proposals, filterable by status.
    ---
    tags:
      - admin
      - proposals
    security:
      - Bearer: []
    parameters:
      - name: status
        in: query
        type: string
        enum: [pending, accepted, rejected]
        required: false
    responses:
      200:
        description: Proposal queue
        schema:
          type: object
          properties:
            proposals:
              type: array
              items:
                type: object
    """
    status = request.args.get("status")
    if status and status not in {"pending", "accepted", "rejected"}:
        raise ValidationError("Status must be one of: pending, accepted, rejected")

    proposals = extensions.db.get_debate_proposals_by_status(status=status, limit=200)
    return jsonify(
        {
            "proposals": [
                {
                    "proposal_id": p["proposal_id"],
                    "proposer_user_id": p["proposer_user_id"],
                    "motion": p["motion"],
                    "moderation_criteria": p["moderation_criteria"],
                    "debate_frame": p.get("debate_frame", ""),
                    "frame_payload_json": p.get("frame_payload_json", {}),
                    "status": p["status"],
                    "decision_reason": p.get("decision_reason"),
                    "reviewer_user_id": p.get("reviewer_user_id"),
                    "reviewed_at": p.get("reviewed_at"),
                    "accepted_debate_id": p.get("accepted_debate_id"),
                    "created_at": p["created_at"],
                }
                for p in proposals
            ]
        }
    )


@proposal_bp.route("/api/admin/debate-proposals/<proposal_id>/accept", methods=["POST"])
@admin_required
def accept_proposal(proposal_id: str) -> Any:
    """Accept a debate proposal and create the debate.
    ---
    tags:
      - admin
      - proposals
    security:
      - Bearer: []
    parameters:
      - name: proposal_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Proposal accepted
        schema:
          type: object
          properties:
            message:
              type: string
            debate_id:
              type: string
            proposal_id:
              type: string
      404:
        description: Proposal not found
      409:
        description: Proposal already processed
    """
    proposal = extensions.db.get_debate_proposal(proposal_id)
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404
    if proposal["status"] != "pending":
        return jsonify({"error": f"Proposal is already {proposal['status']}"}), 409

    payload = {
        "motion": proposal["motion"],
        "moderation_criteria": proposal["moderation_criteria"],
        "debate_frame": proposal.get("debate_frame", ""),
        "frame": proposal.get("frame_payload_json", {}),
    }

    debate = extensions.debate_engine.create_debate(payload, user_id=proposal["proposer_user_id"])
    extensions.db.save_debate(debate)

    extensions.db.update_debate_proposal_status(
        proposal_id,
        status="accepted",
        reviewer_user_id=g.user["user_id"],
        accepted_debate_id=debate["debate_id"],
    )

    extensions.db.set_user_preference(
        proposal["proposer_user_id"],
        "active_debate_id",
        debate["debate_id"],
    )
    from backend.utils.helpers import set_session_debate

    set_session_debate(debate["debate_id"])

    return jsonify(
        {
            "message": "Proposal accepted and debate created",
            "debate_id": debate["debate_id"],
            "proposal_id": proposal_id,
        }
    )


@proposal_bp.route("/api/admin/debate-proposals/<proposal_id>/reject", methods=["POST"])
@admin_required
def reject_proposal(proposal_id: str) -> Any:
    """Reject a debate proposal with reason.
    ---
    tags:
      - admin
      - proposals
    security:
      - Bearer: []
    parameters:
      - name: proposal_id
        in: path
        type: string
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - reason
          properties:
            reason:
              type: string
              minLength: 5
              maxLength: 1000
    responses:
      200:
        description: Proposal rejected
        schema:
          type: object
          properties:
            message:
              type: string
            proposal_id:
              type: string
            reason:
              type: string
      404:
        description: Proposal not found
      409:
        description: Proposal already processed
    """
    proposal = extensions.db.get_debate_proposal(proposal_id)
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404
    if proposal["status"] != "pending":
        return jsonify({"error": f"Proposal is already {proposal['status']}"}), 409

    data = request.get_json() or {}
    reason = validate_string(data.get("reason"), "Reason", min_length=5, max_length=1000)
    reason = sanitize_html(reason or "")

    extensions.db.update_debate_proposal_status(
        proposal_id,
        status="rejected",
        decision_reason=reason,
        reviewer_user_id=g.user["user_id"],
    )

    return jsonify(
        {
            "message": "Proposal rejected",
            "proposal_id": proposal_id,
            "reason": reason,
        }
    )
