"""Judge-pool blueprint — judge pool, rotation, calibration, conflicts."""

from typing import Any

from flask import Blueprint, jsonify, request

from backend import extensions
from backend.utils.decorators import admin_required, optional_auth

judge_bp = Blueprint("judge", __name__)


@judge_bp.route("/api/governance/judge-pool", methods=["GET"])
@optional_auth
def get_judge_pool() -> Any:
    """Get judge pool summary.
    ---
    tags:
      - governance
      - judge-pool
    security:
      - Bearer: []
    responses:
      200:
        description: Judge pool summary
        schema:
          type: object
    """
    summary = extensions.debate_engine.governance.get_judge_pool_summary()
    return jsonify(summary)


@judge_bp.route("/api/governance/judge-pool/composition", methods=["POST"])
@admin_required
def record_judge_pool_composition() -> Any:
    """Record judge pool composition entry.
    ---
    tags:
      - governance
      - judge-pool
    security:
      - Bearer: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            category:
              type: string
            count:
              type: integer
            qualification_rubric:
              type: object
            snapshot_id:
              type: string
    responses:
      201:
        description: Composition recorded
        schema:
          type: object
          properties:
            composition_id:
              type: string
    """
    payload = request.get_json() or {}
    composition_id = extensions.debate_engine.governance.record_judge_pool_composition(
        category=payload.get("category", "general"),
        count=payload.get("count", 0),
        qualification_rubric=payload.get("qualification_rubric", {}),
        snapshot_id=payload.get("snapshot_id"),
    )
    return jsonify({"composition_id": composition_id}), 201


@judge_bp.route("/api/governance/judge-pool/rotation-policy", methods=["GET"])
@optional_auth
def get_rotation_policy() -> Any:
    """Get active rotation policy.
    ---
    tags:
      - governance
      - judge-pool
    security:
      - Bearer: []
    responses:
      200:
        description: Rotation policy
        schema:
          type: object
    """
    policy = extensions.debate_engine.governance.get_rotation_policy()
    return jsonify(policy or {})


@judge_bp.route("/api/governance/judge-pool/rotation-policy", methods=["POST"])
@admin_required
def set_rotation_policy() -> Any:
    """Set rotation policy.
    ---
    tags:
      - governance
      - judge-pool
    security:
      - Bearer: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            max_consecutive_snapshots:
              type: integer
            cooldown_snapshots:
              type: integer
    responses:
      201:
        description: Policy set
        schema:
          type: object
          properties:
            policy_id:
              type: string
    """
    payload = request.get_json() or {}
    policy_id = extensions.debate_engine.governance.set_rotation_policy(
        max_consecutive_snapshots=payload.get("max_consecutive_snapshots", 5),
        cooldown_snapshots=payload.get("cooldown_snapshots", 2),
    )
    return jsonify({"policy_id": policy_id}), 201


@judge_bp.route("/api/governance/judge-pool/calibration-protocol", methods=["GET"])
@optional_auth
def get_calibration_protocol() -> Any:
    """Get active calibration protocol.
    ---
    tags:
      - governance
      - judge-pool
    security:
      - Bearer: []
    responses:
      200:
        description: Calibration protocol
        schema:
          type: object
    """
    protocol = extensions.debate_engine.governance.get_calibration_protocol()
    return jsonify(protocol or {})


@judge_bp.route("/api/governance/judge-pool/calibration-protocol", methods=["POST"])
@admin_required
def set_calibration_protocol() -> Any:
    """Set calibration protocol.
    ---
    tags:
      - governance
      - judge-pool
    security:
      - Bearer: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            guideline_version:
              type: string
            shared_guidelines:
              type: object
            inter_judge_consistency_check:
              type: object
    responses:
      201:
        description: Protocol set
        schema:
          type: object
          properties:
            protocol_id:
              type: string
    """
    payload = request.get_json() or {}
    protocol_id = extensions.debate_engine.governance.set_calibration_protocol(
        guideline_version=payload.get("guideline_version", "v1.0"),
        shared_guidelines=payload.get("shared_guidelines", {}),
        inter_judge_consistency_check=payload.get("inter_judge_consistency_check", {}),
    )
    return jsonify({"protocol_id": protocol_id}), 201


@judge_bp.route("/api/governance/judge-pool/conflict-of-interest", methods=["POST"])
@admin_required
def log_conflict_of_interest() -> Any:
    """Log a conflict-of-interest entry.
    ---
    tags:
      - governance
      - judge-pool
    security:
      - Bearer: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            judge_id:
              type: string
            conflict_type:
              type: string
            description:
              type: string
            debate_id:
              type: string
            topic_id:
              type: string
    responses:
      201:
        description: Entry logged
        schema:
          type: object
          properties:
            entry_id:
              type: string
    """
    payload = request.get_json() or {}
    entry_id = extensions.debate_engine.governance.log_conflict_of_interest(
        judge_id=payload.get("judge_id"),
        conflict_type=payload.get("conflict_type", "recusal"),
        description=payload.get("description", ""),
        debate_id=payload.get("debate_id"),
        topic_id=payload.get("topic_id"),
    )
    return jsonify({"entry_id": entry_id}), 201
