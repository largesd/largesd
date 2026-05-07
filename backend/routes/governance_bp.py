"""Governance blueprint — fairness audits, incidents, summary."""

from typing import Any

from flask import Blueprint, jsonify, request

from backend import extensions
from backend.utils.decorators import optional_auth

governance_bp = Blueprint("governance", __name__)


@governance_bp.route("/api/governance/fairness-audits", methods=["GET"])
@optional_auth
def get_fairness_audits() -> Any:
    """Get fairness audit summary.
    ---
    tags:
      - governance
    security:
      - Bearer: []
    parameters:
      - name: limit
        in: query
        type: integer
        default: 100
    responses:
      200:
        description: Fairness audit summary
        schema:
          type: object
    """
    limit = request.args.get("limit", 100, type=int)
    summary = extensions.debate_engine.governance.get_fairness_audit_summary(limit=limit)
    return jsonify(summary)


@governance_bp.route("/api/governance/incidents", methods=["GET"])
@optional_auth
def get_incidents() -> Any:
    """Get incidents.
    ---
    tags:
      - governance
      - incidents
    security:
      - Bearer: []
    parameters:
      - name: status
        in: query
        type: string
        required: false
      - name: severity
        in: query
        type: string
        required: false
      - name: limit
        in: query
        type: integer
        default: 100
    responses:
      200:
        description: Incidents list
        schema:
          type: object
          properties:
            incidents:
              type: array
              items:
                type: object
      400:
        description: Invalid severity
    """
    status = request.args.get("status")
    limit = request.args.get("limit", 100, type=int)
    from backend.governance import IncidentSeverity

    severity_enum = None
    severity = request.args.get("severity")
    if severity:
        try:
            severity_enum = IncidentSeverity(severity)
        except ValueError:
            return jsonify({"error": "Invalid severity"}), 400
    incidents = extensions.debate_engine.governance.get_incidents(
        status=status, severity=severity_enum, limit=limit
    )
    return jsonify({"incidents": incidents})


@governance_bp.route("/api/governance/summary", methods=["GET"])
@optional_auth
def get_governance_summary() -> Any:
    """Get complete governance summary.
    ---
    tags:
      - governance
    security:
      - Bearer: []
    responses:
      200:
        description: Governance summary
        schema:
          type: object
    """
    summary = extensions.debate_engine.governance.get_governance_summary()
    return jsonify(summary)
