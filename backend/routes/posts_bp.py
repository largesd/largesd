"""Posts blueprint — submit and retrieve debate posts."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from backend import extensions
from backend.sanitize import sanitize_html
from backend.utils.decorators import login_required, optional_auth
from backend.utils.helpers import get_session_debate_id
from backend.utils.validators import (
    ValidationError,
    validate_side,
    validate_string,
    validate_topic_id,
)

posts_bp = Blueprint("posts", __name__)


@posts_bp.route("/api/debate/posts", methods=["POST"])
@login_required
def submit_post() -> Any:
    """Submit a new post.
    ---
    tags:
      - posts
    security:
      - Bearer: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - side
            - topic_id
            - facts
            - inference
          properties:
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
        description: Post submitted
        schema:
          type: object
          properties:
            post_id:
              type: string
            side:
              type: string
            topic_id:
              type: string
            modulation_outcome:
              type: string
            block_reason:
              type: string
            timestamp:
              type: string
      400:
        description: No active debate or invalid input
    """
    debate_id = get_session_debate_id()

    if not debate_id:
        return jsonify({"error": "No active debate"}), 400

    data = request.get_json()
    if not data:
        raise ValidationError("Request body required")

    side = validate_side(data.get("side"))
    topic_id = validate_topic_id(data.get("topic_id"))
    facts = validate_string(data.get("facts"), "Facts", min_length=5, max_length=5000)
    inference = validate_string(data.get("inference"), "Inference", min_length=5, max_length=2000)
    counter_arguments = data.get("counter_arguments", "")

    if counter_arguments:
        counter_arguments = validate_string(
            counter_arguments, "Counter-arguments", required=False, max_length=2000
        )

    facts = sanitize_html(facts or "")
    inference = sanitize_html(inference or "")
    counter_arguments = sanitize_html(counter_arguments or "")

    post = extensions.debate_engine.submit_post(
        debate_id=debate_id,
        side=side,
        topic_id=topic_id,
        facts=facts,
        inference=inference,
        counter_arguments=counter_arguments,
    )
    post["user_id"] = g.user["user_id"]
    extensions.db.save_post(post)

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


@posts_bp.route("/api/debate/posts", methods=["GET"])
@optional_auth
def get_posts() -> Any:
    """Get posts for current debate.
    ---
    tags:
      - posts
    security:
      - Bearer: []
    responses:
      200:
        description: List of posts
        schema:
          type: object
          properties:
            posts:
              type: array
              items:
                type: object
                properties:
                  post_id:
                    type: string
                  side:
                    type: string
                  topic_id:
                    type: string
                  modulation_outcome:
                    type: string
                  block_reason:
                    type: string
                  timestamp:
                    type: string
      400:
        description: No active debate
    """
    debate_id = get_session_debate_id()

    if not debate_id:
        return jsonify({"error": "No active debate"}), 400

    posts = extensions.db.get_posts_by_debate(debate_id)

    return jsonify(
        {
            "posts": [
                {
                    "post_id": p["post_id"],
                    "side": p["side"],
                    "topic_id": p["topic_id"],
                    "modulation_outcome": p["modulation_outcome"],
                    "block_reason": p.get("block_reason"),
                    "timestamp": p["timestamp"],
                }
                for p in posts
            ]
        }
    )
