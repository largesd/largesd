"""Unit tests for email submission auth helper (flask-independent)."""

import pytest
import jwt
from datetime import UTC, datetime, timedelta

from backend.email_submission_auth import (
    EmailSubmissionAuthConfig,
    compute_payload_hash,
    generate_email_submission_token,
    decode_email_submission_token,
    verify_email_submission_claims,
)
from backend.email_submission_parser import EmailSubmission


@pytest.fixture
def config():
    return EmailSubmissionAuthConfig(secret="test-secret", ttl_minutes=60)


@pytest.fixture
def base_submission():
    return EmailSubmission(
        debate_id="deb_123",
        resolution="Test Resolution",
        submission_id="550e8400-e29b-41d4-a716-446655440000",
        submitted_at="2026-04-30T01:00:00Z",
        side="FOR",
        topic_id="t1",
        facts="Fact one",
        inference="Inference one",
        counter_arguments=None,
        submitter_email="test@example.com",
        subject="Test",
        auth_token="test_token",
        payload_hash="abc123",
        payload_hash_alg="sha256",
    )


def _make_token(config, **overrides):
    claims = {
        "type": "email_submission",
        "user_id": "user_123",
        "email": "test@example.com",
        "debate_id": "deb_123",
        "submission_id": "550e8400-e29b-41d4-a716-446655440000",
        "side": "FOR",
        "topic_id": "t1",
        "payload_hash": "abc123",
        "payload_hash_alg": "sha256",
        **overrides,
    }
    return generate_email_submission_token(config, claims)


def _user_lookup(user_id):
    if user_id == "user_123":
        return {
            "user_id": "user_123",
            "email": "test@example.com",
            "is_active": True,
            "is_verified": True,
        }
    if user_id == "inactive_user":
        return {
            "user_id": "inactive_user",
            "email": "inactive@example.com",
            "is_active": False,
        }
    return None


# ---------------------------------------------------------------------------
# compute_payload_hash
# ---------------------------------------------------------------------------


def test_compute_payload_hash_stable(config):
    p = {
        "debate_id": "d1",
        "side": "FOR",
        "topic_id": "t1",
        "facts": "f",
        "inference": "i",
        "counter_arguments": "",
    }
    assert compute_payload_hash(p) == compute_payload_hash(p)


def test_compute_payload_hash_changes_when_dict_content_changes(config):
    p1 = {
        "debate_id": "d1",
        "side": "FOR",
        "topic_id": "t1",
        "facts": "f",
        "inference": "i",
        "counter_arguments": "",
    }
    p2 = {**p1, "facts": "g"}
    assert compute_payload_hash(p1) != compute_payload_hash(p2)


# ---------------------------------------------------------------------------
# Token generation / decode
# ---------------------------------------------------------------------------


def test_generate_email_submission_token_produces_decodable_jwt(config):
    token = generate_email_submission_token(config, {"type": "email_submission"})
    decoded = jwt.decode(
        token,
        config.secret,
        algorithms=[config.algorithm],
        options={"require": ["exp", "iat"]},
    )
    assert "exp" in decoded
    assert "iat" in decoded


def test_decode_email_submission_token_returns_correct_claims(config):
    claims = {
        "type": "email_submission",
        "user_id": "user_123",
        "debate_id": "deb_123",
    }
    token = generate_email_submission_token(config, claims)
    decoded = decode_email_submission_token(config, token)
    assert decoded["type"] == "email_submission"
    assert decoded["user_id"] == "user_123"
    assert decoded["debate_id"] == "deb_123"


def test_reject_expired_token(config):
    past = datetime.now(UTC) - timedelta(hours=2)
    token = generate_email_submission_token(
        config, {"type": "email_submission"}, now=past
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_email_submission_token(config, token)


# ---------------------------------------------------------------------------
# verify_email_submission_claims — rejection paths
# ---------------------------------------------------------------------------


def test_reject_wrong_type_claim(config, base_submission):
    token = _make_token(config, type="wrong_type")
    with pytest.raises(ValueError, match="wrong_token_type"):
        verify_email_submission_claims(
            config, token, base_submission, "test@example.com", _user_lookup
        )


def test_reject_wrong_debate_id(config, base_submission):
    token = _make_token(config, debate_id="deb_other")
    with pytest.raises(ValueError, match="debate_mismatch"):
        verify_email_submission_claims(
            config, token, base_submission, "test@example.com", _user_lookup
        )


def test_reject_wrong_submission_id(config, base_submission):
    token = _make_token(config, submission_id="other-id")
    with pytest.raises(ValueError, match="submission_mismatch"):
        verify_email_submission_claims(
            config, token, base_submission, "test@example.com", _user_lookup
        )


def test_reject_wrong_side(config, base_submission):
    token = _make_token(config, side="AGAINST")
    with pytest.raises(ValueError, match="side_mismatch"):
        verify_email_submission_claims(
            config, token, base_submission, "test@example.com", _user_lookup
        )


def test_reject_wrong_topic_id(config, base_submission):
    token = _make_token(config, topic_id="t2")
    with pytest.raises(ValueError, match="topic_mismatch"):
        verify_email_submission_claims(
            config, token, base_submission, "test@example.com", _user_lookup
        )


def test_reject_payload_hash_mismatch(config, base_submission):
    token = _make_token(config, payload_hash="different_hash")
    with pytest.raises(ValueError, match="payload_mismatch"):
        verify_email_submission_claims(
            config, token, base_submission, "test@example.com", _user_lookup
        )


def test_reject_email_mismatch(config, base_submission):
    token = _make_token(config)
    with pytest.raises(ValueError, match="email_mismatch"):
        verify_email_submission_claims(
            config, token, base_submission, "attacker@example.com", _user_lookup
        )


def test_reject_unknown_user(config, base_submission):
    token = _make_token(config, user_id="unknown_user")
    with pytest.raises(ValueError, match="unknown_user"):
        verify_email_submission_claims(
            config, token, base_submission, "test@example.com", _user_lookup
        )


def test_reject_inactive_user(config, base_submission):
    token = _make_token(config, user_id="inactive_user")
    with pytest.raises(ValueError, match="inactive_user"):
        verify_email_submission_claims(
            config, token, base_submission, "test@example.com", _user_lookup
        )


# ---------------------------------------------------------------------------
# verify_email_submission_claims — acceptance path
# ---------------------------------------------------------------------------


def test_accept_valid_token_with_matching_everything(config, base_submission):
    token = _make_token(config)
    user = verify_email_submission_claims(
        config, token, base_submission, "test@example.com", _user_lookup
    )
    assert user["user_id"] == "user_123"
    assert user["is_active"] is True


def test_token_issued_by_flask_endpoint_simulated_verified_standalone(
    config, base_submission
):
    """Simulate Flask endpoint generating a token, then verify in standalone context."""
    now = datetime.now(UTC)
    token = generate_email_submission_token(
        config,
        {
            "type": "email_submission",
            "user_id": "user_123",
            "email": "test@example.com",
            "debate_id": "deb_123",
            "submission_id": "550e8400-e29b-41d4-a716-446655440000",
            "side": "FOR",
            "topic_id": "t1",
            "payload_hash": "abc123",
            "payload_hash_alg": "sha256",
        },
        now=now,
    )
    # Verify in standalone context (no Flask imports)
    user = verify_email_submission_claims(
        config, token, base_submission, "test@example.com", _user_lookup, now=now
    )
    assert user["user_id"] == "user_123"
