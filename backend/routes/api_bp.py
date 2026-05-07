"""API misc blueprint — health, version, metrics, static files."""

import os
from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify, send_from_directory

from backend import extensions

api_bp = Blueprint("api", __name__)


@api_bp.route("/api/health", methods=["GET"])
def health() -> Any:
    """Health check endpoint.
    ---
    tags:
      - system
    responses:
      200:
        description: System health status
        schema:
          type: object
          properties:
            status:
              type: string
              example: healthy
            version:
              type: string
              example: "3.0"
            auth_enabled:
              type: boolean
            timestamp:
              type: string
            redis:
              type: string
              example: connected
    """
    redis_status = (
        "connected"
        if extensions.redis_connected is True
        else "disconnected"
        if extensions.redis_connected is False
        else "not_configured"
    )
    return jsonify(
        {
            "status": "healthy",
            "version": "3.0",
            "auth_enabled": True,
            "timestamp": datetime.now().isoformat(),
            "redis": redis_status,
        }
    )


@api_bp.route("/api/email-submission-template", methods=["GET"])
def get_email_submission_template() -> Any:
    """Return the canonical email body template and expected fields.
    ---
    tags:
      - system
    responses:
      410:
        description: Unsigned email submission templates are deprecated
        schema:
          type: object
          properties:
            error:
              type: string
            code:
              type: string
    """
    return jsonify(
        {
            "error": "Unsigned email submission templates are deprecated. "
            "Use POST /api/debate/email-submission-draft after logging in.",
            "code": "DEPRECATED",
        }
    ), 410


@api_bp.route("/metrics", methods=["GET"])
def get_metrics() -> Any:
    """Prometheus-style metrics endpoint for observability.
    ---
    tags:
      - system
    produces:
      - text/plain
    responses:
      200:
        description: Prometheus metrics
    """
    lines = []
    lines.append("# HELP snapshot_count_total Total snapshots generated")
    lines.append("# TYPE snapshot_count_total counter")
    try:
        conn = extensions.db._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM snapshots")
        count = cursor.fetchone()["c"]
        conn.close()
        lines.append(f"snapshot_count_total {count}")
    except Exception:
        lines.append("snapshot_count_total 0")
    lines.append("# HELP llm_calls_total Total LLM API calls")
    lines.append("# TYPE llm_calls_total counter")
    usage = extensions.debate_engine.llm_client.get_usage_summary()
    lines.append(
        f'llm_calls_total{{provider="{usage.get("provider", "mock")}"}} {usage.get("call_count", 0)}'
    )
    lines.append("# HELP llm_tokens_total Total LLM tokens consumed")
    lines.append("# TYPE llm_tokens_total counter")
    lines.append(f'llm_tokens_total{{type="prompt"}} {usage.get("prompt_tokens", 0)}')
    lines.append(f'llm_tokens_total{{type="completion"}} {usage.get("completion_tokens", 0)}')
    return "\n".join(lines) + "\n", 200, {"Content-Type": "text/plain; version=0.0.4"}


@api_bp.route("/", defaults={"path": ""})
@api_bp.route("/<path:path>")
def serve_static(path: str) -> Any:
    """Serve static files.
    ---
    tags:
      - system
    parameters:
      - name: path
        in: path
        type: string
        required: false
    responses:
      200:
        description: Static file or SPA index.html
    """
    if not path:
        path = "index.html"
    # Security: prevent directory traversal
    path = path.replace("..", "").lstrip("/")

    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

    try:
        response = send_from_directory(frontend_dir, path)
    except Exception:
        # Return index.html for SPA routing
        response = send_from_directory(frontend_dir, "index.html")

    # Set CSRF cookie for HTML pages so forms can include the token
    if getattr(response, "content_type", "").startswith("text/html"):
        from backend.utils.middleware import set_csrf_cookie

        response = set_csrf_cookie(response)

    return response
