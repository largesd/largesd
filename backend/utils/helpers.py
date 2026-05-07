"""Shared helper functions for debate system routes."""

from flask import g, request

from backend import extensions


def get_session_debate_id() -> str | None:
    """Get debate ID from session or query params"""
    debate_id = request.args.get("debate_id")
    if debate_id:
        return str(debate_id)
    debate_id = request.headers.get("X-Debate-ID")
    if debate_id:
        return str(debate_id)
    user = getattr(g, "user", None)
    if user:
        user_prefs = extensions.db.get_user_preferences(user["user_id"])
        if user_prefs and user_prefs.get("active_debate_id"):
            return str(user_prefs["active_debate_id"])
    return None


def set_session_debate(debate_id: str) -> None:
    """Set active debate for user"""
    user = getattr(g, "user", None)
    if user:
        extensions.db.set_user_preference(user["user_id"], "active_debate_id", debate_id)
