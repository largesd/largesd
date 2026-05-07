"""Frame petition blueprint — user-facing frame petitions for debates."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from backend import extensions
from backend.utils.decorators import login_required, optional_auth

frame_petition_bp = Blueprint("frame_petition", __name__)


@frame_petition_bp.route("/api/debate/<debate_id>/frame-petitions", methods=["GET"])
@optional_auth
def list_frame_petitions(debate_id: str) -> Any:
    """List public frame petitions for a debate.
    ---
    tags:
      - frames
    security:
      - Bearer: []
    parameters:
      - name: debate_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: List of frame petitions
        schema:
          type: object
          properties:
            petitions:
              type: array
              items:
                type: object
    """
    return jsonify(
        {
            "petitions": extensions.db.get_frame_petitions(debate_id=debate_id),
        }
    )


@frame_petition_bp.route("/api/debate/<debate_id>/frame-petitions", methods=["POST"])
@login_required
def create_frame_petition(debate_id: str) -> Any:
    """Submit a candidate frame petition separate from debate proposals.
    ---
    tags:
      - frames
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
          properties:
            candidate_frame:
              type: object
    responses:
      201:
        description: Frame petition created
        schema:
          type: object
          properties:
            petition:
              type: object
      404:
        description: Debate not found
    """
    if not extensions.db.get_debate(debate_id):
        return jsonify({"error": "Debate not found"}), 404
    data = request.get_json() or {}
    candidate = data.get("candidate_frame") or data
    if not isinstance(candidate, dict):
        return jsonify({"error": "candidate_frame must be an object"}), 400
    petition = extensions.db.create_frame_petition(
        debate_id=debate_id,
        proposer_user_id=g.user["user_id"],
        candidate_frame=candidate,
    )
    extensions.debate_engine.governance.log_change(
        change_type="frame_petition",
        description=f"Frame petition submitted for {debate_id}",
        changed_by=g.user["user_id"],
        justification="Public frame petition intake",
        new_value=petition.get("petition_id"),
    )
    return jsonify({"petition": petition}), 201
