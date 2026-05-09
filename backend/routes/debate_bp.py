"""Debate blueprint — debate CRUD, active-debate lookup, activation, and incidents."""

import re
import uuid
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import quote

from flask import Blueprint, current_app, g, jsonify, request

from backend import extensions
from backend.email_submission_auth import (
    EmailSubmissionAuthConfig,
    compute_payload_hash,
    generate_email_submission_token,
)
from backend.sanitize import sanitize_html
from backend.utils.decorators import admin_required, login_required, optional_auth
from backend.utils.helpers import get_session_debate_id, set_session_debate
from backend.utils.validators import (
    ValidationError,
    validate_side,
    validate_string,
    validate_topic_id,
)

debate_bp = Blueprint("debate", __name__)


# ---------------------------------------------------------------------------
# Debate CRUD
# ---------------------------------------------------------------------------
@debate_bp.route("/api/debates", methods=["GET"])
@optional_auth
def list_debates() -> Any:
    """List debates accessible to user.
    ---
    tags:
      - debates
    security:
      - Bearer: []
    responses:
      200:
        description: List of debates
        schema:
          type: object
          properties:
            debates:
              type: array
              items:
                type: object
                properties:
                  debate_id:
                    type: string
                  resolution:
                    type: string
                  scope:
                    type: string
                  created_at:
                    type: string
                  has_snapshot:
                    type: boolean
    """
    if g.user:
        debates = extensions.db.get_debates_by_user(g.user["user_id"])
    else:
        debates = extensions.db.get_public_debates()

    return jsonify(
        {
            "debates": [
                {
                    "debate_id": d["debate_id"],
                    "resolution": d["resolution"],
                    "scope": d["scope"][:200] + "..." if len(d["scope"]) > 200 else d["scope"],
                    "created_at": d["created_at"],
                    "has_snapshot": d.get("has_snapshot", False),
                }
                for d in debates
            ]
        }
    )


@debate_bp.route("/api/debates", methods=["POST"])
@admin_required
def create_debate() -> Any:
    """Create a new debate directly (admin only).
    ---
    tags:
      - debates
    security:
      - Bearer: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - resolution
            - scope
          properties:
            resolution:
              type: string
              minLength: 10
              maxLength: 500
            scope:
              type: string
              minLength: 10
              maxLength: 2000
    responses:
      201:
        description: Debate created
        schema:
          type: object
          properties:
            debate_id:
              type: string
            resolution:
              type: string
            scope:
              type: string
            created_at:
              type: string
            creator:
              type: string
    """
    data = request.get_json()
    if not data:
        raise ValidationError("Request body required")

    resolution = validate_string(
        data.get("resolution"), "Resolution", min_length=10, max_length=500
    )
    resolution = sanitize_html(resolution or "")

    scope = validate_string(data.get("scope"), "Scope", min_length=10, max_length=2000)
    scope = sanitize_html(scope or "")

    debate = extensions.debate_engine.create_debate(resolution=resolution, scope=scope)
    debate["user_id"] = g.user["user_id"]
    extensions.db.save_debate(debate)
    set_session_debate(debate["debate_id"])

    return jsonify(
        {
            "debate_id": debate["debate_id"],
            "resolution": debate["resolution"],
            "scope": debate["scope"],
            "created_at": debate["created_at"],
            "creator": g.user["display_name"],
        }
    ), 201


@debate_bp.route("/api/debate", methods=["GET"])
@optional_auth
def get_debate() -> Any:
    """Get current/active debate.
    ---
    tags:
      - debates
    security:
      - Bearer: []
    responses:
      200:
        description: Current debate details
        schema:
          type: object
          properties:
            debate_id:
              type: string
            resolution:
              type: string
            scope:
              type: string
            created_at:
              type: string
            current_snapshot_id:
              type: string
            has_debate:
              type: boolean
            is_owner:
              type: boolean
      403:
        description: Access denied
      404:
        description: Debate not found
    """
    debate_id = get_session_debate_id()

    if not debate_id:
        return jsonify(
            {
                "debate_id": None,
                "resolution": None,
                "scope": None,
                "created_at": None,
                "current_snapshot_id": None,
                "has_debate": False,
            }
        )

    debate = extensions.db.get_debate(debate_id)

    if not debate:
        return jsonify({"error": "Debate not found", "code": "DEBATE_NOT_FOUND"}), 404

    if debate.get("is_private") and debate.get("user_id") != (
        g.user["user_id"] if g.user else None
    ):
        return jsonify({"error": "Access denied", "code": "ACCESS_DENIED"}), 403

    return jsonify(
        {
            "debate_id": debate["debate_id"],
            "resolution": debate["resolution"],
            "scope": debate["scope"],
            "created_at": debate["created_at"],
            "current_snapshot_id": debate.get("current_snapshot_id"),
            "has_debate": True,
            "is_owner": g.user and debate.get("user_id") == g.user["user_id"],
        }
    )


@debate_bp.route("/api/debate/<debate_id>", methods=["GET"])
@optional_auth
def get_debate_by_id(debate_id: str) -> Any:
    """Get specific debate by ID.
    ---
    tags:
      - debates
    security:
      - Bearer: []
    parameters:
      - name: debate_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Debate details
        schema:
          type: object
          properties:
            debate_id:
              type: string
            resolution:
              type: string
            scope:
              type: string
            created_at:
              type: string
            current_snapshot_id:
              type: string
            has_debate:
              type: boolean
      404:
        description: Debate not found
    """
    if not debate_id or not re.match(r"^[a-zA-Z0-9_-]+$", debate_id):
        raise ValidationError("Invalid debate ID")

    debate = extensions.db.get_debate(debate_id)

    if not debate:
        return jsonify({"error": "Debate not found"}), 404

    if g.user:
        set_session_debate(debate_id)

    return jsonify(
        {
            "debate_id": debate["debate_id"],
            "resolution": debate["resolution"],
            "scope": debate["scope"],
            "created_at": debate["created_at"],
            "current_snapshot_id": debate.get("current_snapshot_id"),
            "has_debate": True,
        }
    )


@debate_bp.route("/api/debate/<debate_id>/activate", methods=["POST"])
@login_required
def activate_debate(debate_id: str) -> Any:
    """Set a debate as the user's active debate.
    ---
    tags:
      - debates
    security:
      - Bearer: []
    parameters:
      - name: debate_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Debate activated
        schema:
          type: object
          properties:
            message:
              type: string
            debate_id:
              type: string
      404:
        description: Debate not found
    """
    if not debate_id or not re.match(r"^[a-zA-Z0-9_-]+$", debate_id):
        raise ValidationError("Invalid debate ID")

    debate = extensions.db.get_debate(debate_id)
    if not debate:
        return jsonify({"error": "Debate not found"}), 404

    set_session_debate(debate_id)

    return jsonify({"message": "Debate activated", "debate_id": debate_id})


# ---------------------------------------------------------------------------
# Debate-scoped incidents
# ---------------------------------------------------------------------------
@debate_bp.route("/api/debate/<debate_id>/incidents", methods=["GET"])
@optional_auth
def get_debate_incidents(debate_id: str) -> Any:
    """Get public incidents affecting one debate.
    ---
    tags:
      - incidents
    security:
      - Bearer: []
    parameters:
      - name: debate_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Debate incidents
        schema:
          type: object
          properties:
            debate_id:
              type: string
            incidents:
              type: array
              items:
                type: object
    """
    all_incidents = extensions.debate_engine.governance.get_incidents(limit=500)
    incidents = [
        incident for incident in all_incidents if debate_id in incident.get("affected_debates", [])
    ]
    return jsonify({"debate_id": debate_id, "incidents": incidents})


# ---------------------------------------------------------------------------
# Email submission draft (v3)
# ---------------------------------------------------------------------------
@debate_bp.route("/api/debate/email-submission-draft", methods=["POST"])
@login_required
def create_email_submission_draft() -> Any:
    """Generate a signed BDA Submission v3 email draft.
    ---
    tags:
      - debates
    security:
      - Bearer: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - debate_id
            - side
            - topic_id
            - facts
            - inference
          properties:
            debate_id:
              type: string
            side:
              type: string
              enum: [FOR, AGAINST]
            topic_id:
              type: string
            facts:
              type: string
              minLength: 5
              maxLength: 5000
            inference:
              type: string
              minLength: 5
              maxLength: 2000
            counter_arguments:
              type: string
              maxLength: 2000
    responses:
      200:
        description: v3 email draft generated
        schema:
          type: object
          properties:
            version:
              type: string
            submission_id:
              type: string
            submitted_at:
              type: string
            expires_at:
              type: string
            payload_hash_alg:
              type: string
            payload_hash:
              type: string
            body:
              type: string
            subject:
              type: string
            mailto:
              type: string
      400:
        description: Missing config or validation error
      401:
        description: Authentication required
      404:
        description: Debate not found
      429:
        description: Rate limit exceeded
    """
    data = request.get_json()
    if not data:
        raise ValidationError("Request body required")

    debate_id = data.get("debate_id")
    if not debate_id or not re.match(r"^[a-zA-Z0-9_-]+$", debate_id):
        raise ValidationError("Invalid debate ID")

    debate = extensions.db.get_debate(debate_id)
    if not debate:
        return jsonify(
            {
                "error": "Debate not available for posting",
                "code": "DEBATE_NOT_AVAILABLE_FOR_POSTING",
            }
        ), 404

    # Access check consistent with get_debate_by_id
    if debate.get("is_private") and debate.get("user_id") != g.user["user_id"]:
        return jsonify({"error": "Access denied", "code": "ACCESS_DENIED"}), 403

    side = validate_side(data.get("side"))
    topic_id = validate_topic_id(data.get("topic_id"))
    facts = cast(str, validate_string(data.get("facts"), "Facts", min_length=5, max_length=5000))
    inference = cast(
        str, validate_string(data.get("inference"), "Inference", min_length=5, max_length=2000)
    )
    counter_arguments = (
        validate_string(
            data.get("counter_arguments", ""), "Counter-arguments", required=False, max_length=2000
        )
        or ""
    )

    # Resolution from DB, not request
    resolution = debate.get("resolution", "")

    dest_email = current_app.config.get("PROCESSOR_DEST_EMAIL", "")
    if not dest_email:
        return jsonify(
            {
                "error": "Email posting is not configured on this server",
                "code": "EMAIL_DEST_MISSING",
            }
        ), 400

    # Build canonical payload for hashing (NO resolution, timestamps, token, mailto)
    canonical_payload = {
        "debate_id": debate_id,
        "side": side,
        "topic_id": topic_id or "",
        "facts": facts,
        "inference": inference,
        "counter_arguments": counter_arguments,
    }
    payload_hash = compute_payload_hash(canonical_payload)

    submission_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    expires_at = now.timestamp() + (current_app.config["EMAIL_SUBMISSION_TOKEN_TTL_MINUTES"] * 60)

    config = EmailSubmissionAuthConfig(
        secret=current_app.config["EMAIL_SUBMISSION_SECRET"],
        ttl_minutes=current_app.config["EMAIL_SUBMISSION_TOKEN_TTL_MINUTES"],
    )

    token = generate_email_submission_token(
        config,
        {
            "type": "email_submission",
            "user_id": g.user["user_id"],
            "email": g.user.get("email", ""),
            "debate_id": debate_id,
            "submission_id": submission_id,
            "side": side,
            "topic_id": topic_id or "",
            "payload_hash": payload_hash,
            "payload_hash_alg": "sha256",
        },
        now=now,
    )

    # Build v3 body
    submitted_at = now.isoformat().replace("+00:00", "Z")
    expires_at_iso = datetime.fromtimestamp(expires_at, UTC).isoformat().replace("+00:00", "Z")
    body_lines = [
        "BDA Submission v3",
        f"Debate-ID: {debate_id}",
        f"Resolution: {resolution}",
        f"Submission-ID: {submission_id}",
        f"Submitted-At: {submitted_at}",
        f"Expires-At: {expires_at_iso}",
        f"Submitter-Email: {g.user.get('email', '')}",
        f"Position: {side}",
        f"Topic-Area: {topic_id or ''}",
        "Payload-Hash-Alg: sha256",
        f"Payload-Hash: {payload_hash}",
        f"Auth-Token: {token}",
        "",
        "Facts:",
        facts,
        "",
        "Inference:",
        inference,
    ]
    if counter_arguments:
        body_lines.extend(["", "Counter-Arguments:", counter_arguments])
    body = "\n".join(body_lines)

    subject = f"BDA Submission - {side} - {debate_id}"
    encoded_subject = quote(subject, safe="")
    encoded_body = quote(body, safe="")
    mailto = f"mailto:{dest_email}?subject={encoded_subject}&body={encoded_body}"

    return jsonify(
        {
            "version": "BDA Submission v3",
            "submission_id": submission_id,
            "submitted_at": submitted_at,
            "expires_at": expires_at_iso,
            "payload_hash_alg": "sha256",
            "payload_hash": payload_hash,
            "body": body,
            "subject": subject,
            "mailto": mailto,
        }
    )
