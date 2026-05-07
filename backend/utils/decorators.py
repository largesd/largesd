"""Authentication and authorization decorators."""

import os
from datetime import UTC
from functools import wraps
from typing import Any

import jwt
from flask import current_app, g, jsonify, request


def generate_token(user_id: str, email: str, display_name: str, is_admin: bool = False) -> str:
    """Generate JWT token"""
    from datetime import datetime, timedelta

    payload = {
        "user_id": user_id,
        "email": email,
        "display_name": display_name,
        "is_admin": bool(is_admin),
        "exp": datetime.now(UTC) + timedelta(hours=current_app.config["JWT_EXPIRATION_HOURS"]),
        "iat": datetime.now(UTC),
        "type": "access",
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and validate JWT token"""
    try:
        payload = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
        return payload  # type: ignore[no-any-return]
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_auth_token() -> str | None:
    """Extract token from Authorization header"""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    return parts[1]


def get_admin_access_mode() -> str:
    """Return API admin access mode: open, authenticated, or restricted."""
    mode = (os.getenv("ADMIN_ACCESS_MODE") or "restricted").strip().lower()
    return mode if mode in {"open", "authenticated", "restricted"} else "restricted"


# Admin access startup warning
_admin_mode = get_admin_access_mode()
if _admin_mode != "restricted":
    import warnings

    warnings.warn(
        f"ADMIN_ACCESS_MODE is set to '{_admin_mode}'. "
        "For production deployments, use 'restricted' with explicit ADMIN_USER_EMAILS or ADMIN_USER_IDS. "
        f"Current mode: {_admin_mode}",
        RuntimeWarning,
        stacklevel=2,
    )


def parse_csv_env(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def is_user_in_restricted_admin_list(user: dict[str, str]) -> bool:
    allowed_emails = parse_csv_env(os.getenv("ADMIN_USER_EMAILS"))
    allowed_ids = parse_csv_env(os.getenv("ADMIN_USER_IDS"))
    user_email = (user.get("email") or "").lower()
    user_id = (user.get("user_id") or "").lower()
    return bool(
        (allowed_emails and user_email in allowed_emails)
        or (allowed_ids and user_id in allowed_ids)
    )


def log_admin_action(action_type: str, description: str) -> None:
    """Log an admin action for audit trail."""
    import logging

    user_id = (getattr(g, "user", None) or {}).get("user_id", "anonymous")
    app_logger = logging.getLogger("debate_system")
    app_logger.info(
        f"Admin action: {action_type} by {user_id}",
        extra={"event_type": "admin_action", "user_id": user_id},
    )


def login_required(f: Any) -> Any:
    """Decorator to require authentication"""

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        token = get_auth_token()

        if not token:
            return jsonify({"error": "Authentication required", "code": "AUTH_REQUIRED"}), 401

        payload = decode_token(token)
        if not payload:
            return jsonify({"error": "Invalid or expired token", "code": "AUTH_INVALID"}), 401

        # Store user info in flask g object
        g.user = {
            "user_id": payload["user_id"],
            "email": payload["email"],
            "display_name": payload["display_name"],
            "is_admin": payload.get("is_admin", False),
        }

        return f(*args, **kwargs)

    return decorated_function


def optional_auth(f: Any) -> Any:
    """Decorator for optional authentication"""

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        token = get_auth_token()
        g.user = None

        if token:
            payload = decode_token(token)
            if payload:
                g.user = {
                    "user_id": payload["user_id"],
                    "email": payload["email"],
                    "display_name": payload["display_name"],
                    "is_admin": payload.get("is_admin", False),
                }

        return f(*args, **kwargs)

    return decorated_function


def admin_required(f: Any) -> Any:
    """Decorator for admin APIs with configurable access policy."""

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        mode = get_admin_access_mode()
        token = get_auth_token()
        g.user = None

        if token:
            payload = decode_token(token)
            if payload:
                g.user = {
                    "user_id": payload["user_id"],
                    "email": payload["email"],
                    "display_name": payload["display_name"],
                    "is_admin": payload.get("is_admin", False),
                }

        if mode == "open":
            return f(*args, **kwargs)

        if not g.user:
            return jsonify(
                {
                    "error": "Authentication required for admin actions",
                    "code": "AUTH_REQUIRED",
                }
            ), 401

        if mode == "restricted":
            # Restricted mode: explicit env allowlist ONLY.
            # The is_admin JWT flag is NOT sufficient on its own.
            if is_user_in_restricted_admin_list(g.user):
                return f(*args, **kwargs)
            return jsonify(
                {
                    "error": "Admin access restricted to explicitly allowlisted accounts",
                    "code": "ADMIN_RESTRICTED",
                    "detail": "Contact the operator to be added to ADMIN_USER_EMAILS or ADMIN_USER_IDS",
                }
            ), 403

        # authenticated mode: user must have is_admin flag in their JWT
        if g.user.get("is_admin"):
            return f(*args, **kwargs)

        return jsonify(
            {
                "error": "Admin access denied for this account",
                "code": "ADMIN_FORBIDDEN",
            }
        ), 403

    return decorated_function
