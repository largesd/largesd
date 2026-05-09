"""Flask-independent auth helper for email submission tokens.

This module must NOT import flask, current_app, g, or request.
The email processor imports it directly.
"""

import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt


@dataclass(frozen=True)
class EmailSubmissionAuthConfig:
    secret: str
    algorithm: str = "HS256"
    ttl_minutes: int = 1440
    require_verified_email: bool = False


def compute_payload_hash(payload: dict[str, str]) -> str:
    """Canonical JSON -> SHA-256 -> base64url nopad."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_email_submission_token(
    config: EmailSubmissionAuthConfig,
    claims: dict[str, Any],
    now: datetime | None = None,
) -> str:
    if now is None:
        now = datetime.now(UTC)
    exp = now.timestamp() + (config.ttl_minutes * 60)
    payload = {**claims, "exp": int(exp), "iat": int(now.timestamp())}
    return jwt.encode(payload, config.secret, algorithm=config.algorithm)


def decode_email_submission_token(
    config: EmailSubmissionAuthConfig,
    token: str,
    now: datetime | None = None,
) -> dict:
    if now is None:
        now = datetime.now(UTC)
    return jwt.decode(
        token,
        config.secret,
        algorithms=[config.algorithm],
        options={"require": ["exp", "iat", "type"]},
        clock_skew=60,
    )


def verify_email_submission_claims(
    config: EmailSubmissionAuthConfig,
    token: str,
    submission: Any,  # EmailSubmission dataclass from parser
    sender_email: str,
    user_lookup: Callable[[Any], Any],
    now: datetime | None = None,
) -> dict:
    """Decode and verify a token against the parsed submission.
    Returns the verified user dict on success, or raises ValueError.
    """
    decoded = decode_email_submission_token(config, token, now)

    if decoded.get("type") != "email_submission":
        raise ValueError("wrong_token_type")

    # Cross-debate / cross-submission reuse prevention
    if decoded.get("debate_id") != submission.debate_id:
        raise ValueError("debate_mismatch")
    if decoded.get("submission_id") != submission.submission_id:
        raise ValueError("submission_mismatch")
    if decoded.get("side") != submission.side:
        raise ValueError("side_mismatch")
    if decoded.get("topic_id") != submission.topic_id:
        raise ValueError("topic_mismatch")

    # Email / forwarding attack prevention
    normalized_from = sender_email.lower().strip()
    normalized_claim = (decoded.get("email") or "").lower().strip()
    if normalized_from != normalized_claim:
        raise ValueError("email_mismatch")

    # Payload edit prevention
    expected_hash = decoded.get("payload_hash")
    expected_alg = decoded.get("payload_hash_alg")
    if expected_alg != "sha256":
        raise ValueError("unsupported_hash_alg")
    if submission.payload_hash != expected_hash:
        raise ValueError("payload_mismatch")

    user = user_lookup(decoded.get("user_id"))
    if not user:
        raise ValueError("unknown_user")
    if not user.get("is_active", True):
        raise ValueError("inactive_user")
    if config.require_verified_email and not user.get("is_verified", False):
        raise ValueError("unverified_email")

    return user  # type: ignore[no-any-return]
