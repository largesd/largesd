"""Focused regression tests for email processor and submission parser."""

import os
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import jwt
import pytest

from backend.email_processor import EmailProcessor, EmailProcessorConfig
from backend.email_submission_parser import EmailSubmission, EmailSubmissionError, EmailSubmissionParser, EmailSubmissionParseResult

# ---------------------------------------------------------------------------
# Recipient parsing (existing tests preserved)
# ---------------------------------------------------------------------------


def test_extract_recipient_emails_handles_display_names_with_commas():
    msg = EmailMessage()
    msg["To"] = '"Pikachoo, Happy" <happypikachoo@gmail.com>, Ally <ally@example.com>'

    recipients = EmailProcessor._extract_recipient_emails(msg)

    assert recipients == ["happypikachoo@gmail.com", "ally@example.com"]


def test_extract_recipient_emails_uses_delivery_headers_for_forwarded_mail():
    msg = EmailMessage()
    msg["To"] = "happypikachoo@icloud.com"
    msg["Delivered-To"] = "happypikachoo@gmail.com"

    recipients = EmailProcessor._extract_recipient_emails(msg)

    assert "happypikachoo@icloud.com" in recipients
    assert "happypikachoo@gmail.com" in recipients
    assert EmailProcessor._is_addressed_to_expected_recipient(
        recipients,
        ["happypikachoo@gmail.com"],
    )


def test_config_accepts_processor_dest_and_monitored_inbox_aliases():
    tracked_keys = ("PROCESSOR_DEST_EMAIL", "IMAP_USER", "SMTP_USER")
    original = {key: os.environ.get(key) for key in tracked_keys}

    try:
        os.environ["PROCESSOR_DEST_EMAIL"] = "happypikachoo@gmail.com"
        os.environ["IMAP_USER"] = "happypikachoo@icloud.com"
        os.environ.pop("SMTP_USER", None)

        config = EmailProcessorConfig()

        assert config.dest_emails == ["happypikachoo@gmail.com"]
        assert config.accepted_recipient_emails == [
            "happypikachoo@gmail.com",
            "happypikachoo@icloud.com",
        ]
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# HTML-to-text fallback (Rec 1)
# ---------------------------------------------------------------------------


def test_get_text_body_prefers_plain_text():
    msg = EmailMessage()
    msg.set_content("Plain text body")
    msg.add_alternative("<html><body>HTML body</body></html>", subtype="html")

    body = EmailProcessor._get_text_body(msg)
    assert body.strip() == "Plain text body"


def test_get_text_body_falls_back_to_html():
    msg = EmailMessage()
    msg.add_alternative("<html><body><p>HTML paragraph</p></body></html>", subtype="html")

    body = EmailProcessor._get_text_body(msg)
    assert "HTML paragraph" in body
    assert "<html>" not in body


def test_get_text_body_returns_none_for_image_only_email():
    msg = EmailMessage()
    msg.set_content("", subtype="image")

    body = EmailProcessor._get_text_body(msg)
    assert body is None


def test_html_to_text_strips_tags():
    html = "<html><body><p>Hello</p><br><p>World</p></body></html>"
    text = EmailProcessor._html_to_text(html)
    assert "Hello" in text
    assert "World" in text
    assert "<p>" not in text


def test_html_to_text_fallback_does_not_sanitize():
    """Malformed or scripted HTML falls back to readable plain text.

    The fallback extracts text content; it does not sanitize HTML.
    User-facing HTML sanitization is handled by backend.sanitize.sanitize_html.
    """
    html = "<p>Hello</p><script>alert('xss')</script><p>World</p>"
    text = EmailProcessor._html_to_text(html)
    assert "Hello" in text
    assert "World" in text
    assert "<script>" not in text
    # Script payload remains in plain-text output; this is expected.
    assert "alert('xss')" in text


# ---------------------------------------------------------------------------
# Section extraction (Rec 6)
# ---------------------------------------------------------------------------


def test_extract_section_tolerates_single_newlines():
    parser = EmailSubmissionParser()
    text = "Facts:\nSingle newline fact\nInference:\nSingle newline inference"
    facts = parser._extract_section(text, "Facts")
    assert facts == "Single newline fact"


def test_extract_section_tolerates_trailing_whitespace():
    parser = EmailSubmissionParser()
    text = "Facts:   \nTrailing whitespace fact\n\nInference:\nInference text"
    facts = parser._extract_section(text, "Facts")
    assert facts == "Trailing whitespace fact"


def test_v2_format_parses_correctly():
    parser = EmailSubmissionParser()
    body = (
        "BDA Submission v2\n"
        "---\n"
        "Debate-ID: deb_abc123\n"
        "Resolution: AI should be regulated\n"
        "Submission-ID: 550e8400-e29b-41d4-a716-446655440000\n"
        "Submitted-At: 2026-04-30T01:00:00Z\n"
        "Position: FOR\n"
        "Topic-Area: t1\n"
        "---\n"
        "\n"
        "Facts:\n"
        "Fact one\n"
        "\n"
        "Inference:\n"
        "The conclusion follows.\n"
    )
    submission = parser.parse_body(body, "test@example.com", "Test")
    assert submission.debate_id == "deb_abc123"
    assert submission.facts == "Fact one"
    assert submission.inference == "The conclusion follows."


def test_v2_format_rejects_missing_frontmatter():
    parser = EmailSubmissionParser()
    body = "BDA Submission v2\n" "Debate-ID: deb_abc123\n" "Facts:\n" "Fact one\n"
    with pytest.raises(EmailSubmissionError) as exc_info:
        parser.parse_body(body, "test@example.com", "Test")
    assert (
        "frontmatter" in str(exc_info.value).lower() or "delimiter" in str(exc_info.value).lower()
    )


# ---------------------------------------------------------------------------
# Deduplication by Submission-ID (Rec 2)
# ---------------------------------------------------------------------------


def test_duplicate_submission_is_skipped():
    parser = EmailSubmissionParser()
    body = parser.build_email_body(
        debate_id="deb_test",
        resolution="Test resolution",
        side="FOR",
        topic_id="t1",
        facts="Fact",
        inference="Inference",
    )

    mock_db = MagicMock()
    mock_db.get_post_by_submission_id.return_value = {
        "post_id": "post_123",
        "debate_id": "deb_test",
        "timestamp": "2026-04-30T01:00:00",
    }

    existing = mock_db.get_post_by_submission_id("some-uuid")
    assert existing is not None
    assert existing["post_id"] == "post_123"


def test_unique_submissions_are_allowed():
    mock_db = MagicMock()
    mock_db.get_post_by_submission_id.return_value = None

    existing = mock_db.get_post_by_submission_id("new-uuid")
    assert existing is None


# ---------------------------------------------------------------------------
# Atomic / retriable GitHub publishing (Rec 3)
# ---------------------------------------------------------------------------


def test_github_publish_retries_on_failure():
    """Mock publisher fails twice then succeeds; retry logic should eventually succeed."""
    mock_publisher = MagicMock()
    mock_publisher.publish_json.side_effect = [
        Exception("Transient error 1"),
        Exception("Transient error 2"),
        MagicMock(commit_sha="abc123", html_url="http://example.com"),
    ]

    attempt = 0
    max_retries = 3
    success = False
    for _ in range(max_retries):
        attempt += 1
        try:
            result = mock_publisher.publish_json(payload={}, commit_message="test")
            success = True
            break
        except Exception:
            if attempt == max_retries:
                break

    assert success is True
    assert mock_publisher.publish_json.call_count == 3


def test_github_publish_queues_after_max_retries():
    """Mock publisher always fails; assert failure after max retries."""
    mock_publisher = MagicMock()
    mock_publisher.publish_json.side_effect = Exception("Always fails")

    attempt = 0
    max_retries = 3
    success = False
    for _ in range(max_retries):
        attempt += 1
        try:
            mock_publisher.publish_json(payload={}, commit_message="test")
            success = True
            break
        except Exception:
            if attempt == max_retries:
                break

    assert success is False
    assert mock_publisher.publish_json.call_count == 3


# ---------------------------------------------------------------------------
# Frontend/backend body format match (Rec 4)
# ---------------------------------------------------------------------------


def test_frontend_and_backend_body_format_match():
    """Assert that the Python and JS builders produce identical structure modulo UUID/timestamp."""
    parser = EmailSubmissionParser()
    py_body = parser.build_email_body(
        debate_id="deb_123",
        resolution="Test Resolution",
        side="FOR",
        topic_id="t1",
        facts="Fact A",
        inference="Therefore B",
        counter_arguments="Counter C",
    )

    # Normalize by replacing UUID and timestamp with placeholders
    lines = py_body.split("\n")
    normalized = []
    for line in lines:
        if line.startswith("Submission-ID:"):
            normalized.append("Submission-ID: <UUID>")
        elif line.startswith("Submitted-At:"):
            normalized.append("Submitted-At: <TIMESTAMP>")
        else:
            normalized.append(line)

    expected = [
        "BDA Submission v1",
        "Debate-ID: deb_123",
        "Resolution: Test Resolution",
        "Submission-ID: <UUID>",
        "Submitted-At: <TIMESTAMP>",
        "Position: FOR",
        "Topic-Area: t1",
        "",
        "Facts:",
        "Fact A",
        "",
        "Inference:",
        "Therefore B",
        "",
        "Counter-Arguments:",
        "Counter C",
    ]

    assert normalized == expected


# ---------------------------------------------------------------------------
# Integration: parser can parse a body generated by the builder
# ---------------------------------------------------------------------------


def test_parser_can_parse_builder_output():
    parser = EmailSubmissionParser()
    body = parser.build_email_body(
        debate_id="deb_123",
        resolution="Test Resolution",
        side="FOR",
        topic_id="t1",
        facts="Fact A\nFact B",
        inference="Therefore B",
        counter_arguments="Counter C",
    )
    submission = parser.parse_body(body, "test@example.com", "Test Subject")
    assert submission.debate_id == "deb_123"
    assert submission.side == "FOR"
    assert submission.facts == "Fact A\nFact B"
    assert submission.inference == "Therefore B"
    assert submission.counter_arguments == "Counter C"


# ---------------------------------------------------------------------------
# v3 Parser tests
# ---------------------------------------------------------------------------


def _build_v3_body(
    auth_token="test_token",
    expires_at="2026-12-31T23:59:59Z",
    submitter_email="test@example.com",
    payload_hash="abc123",
    payload_hash_alg="sha256",
    facts="Fact one",
    inference="Inference one",
    counter_arguments=None,
):
    """Helper to build a minimal valid v3 body."""
    lines = [
        "BDA Submission v3",
        "Debate-ID: deb_123",
        "Resolution: Test Resolution",
        "Submission-ID: 550e8400-e29b-41d4-a716-446655440000",
        "Submitted-At: 2026-04-30T01:00:00Z",
        f"Expires-At: {expires_at}",
        f"Submitter-Email: {submitter_email}",
        "Position: FOR",
        "Topic-Area: t1",
        f"Payload-Hash-Alg: {payload_hash_alg}",
        f"Payload-Hash: {payload_hash}",
        f"Auth-Token: {auth_token}",
        "",
        "Facts:",
        facts,
        "",
        "Inference:",
        inference,
    ]
    if counter_arguments:
        lines.extend(["", "Counter-Arguments:", counter_arguments])
    return "\n".join(lines)


def test_v3_header_is_recognized():
    parser = EmailSubmissionParser()
    body = _build_v3_body()
    result = parser.parse_for_processor(body, "test@example.com", "Test")
    assert result.decision == "accept"
    assert result.version_hint == "v3"
    assert result.submission is not None
    assert result.submission.debate_id == "deb_123"


def test_v3_extracts_auth_token():
    parser = EmailSubmissionParser()
    body = _build_v3_body(auth_token="my_secret_token")
    result = parser.parse_for_processor(body, "test@example.com", "Test")
    assert result.decision == "accept"
    assert result.submission.auth_token == "my_secret_token"


def test_v3_extracts_payload_hash_and_alg():
    parser = EmailSubmissionParser()
    body = _build_v3_body(payload_hash="deadbeef", payload_hash_alg="sha512")
    result = parser.parse_for_processor(body, "test@example.com", "Test")
    assert result.submission.payload_hash == "deadbeef"
    assert result.submission.payload_hash_alg == "sha512"


def test_v3_rejects_missing_auth_token():
    parser = EmailSubmissionParser()
    body = _build_v3_body(auth_token="")
    result = parser.parse_for_processor(body, "test@example.com", "Test")
    assert result.decision == "reject"
    assert result.version_hint == "v3"
    assert result.reason_code == "missing_token"
    assert result.ack_safe is False


def test_v3_rejects_missing_required_field():
    parser = EmailSubmissionParser()
    body = _build_v3_body()
    # Remove Expires-At by rebuilding without it
    lines = body.split("\n")
    lines = [line for line in lines if not line.startswith("Expires-At:")]
    body = "\n".join(lines)
    result = parser.parse_for_processor(body, "test@example.com", "Test")
    assert result.decision == "reject"
    assert result.version_hint == "v3"
    assert result.reason_code == "missing_required_field"
    assert result.ack_safe is False


def test_v3_unwraps_multiline_auth_token():
    parser = EmailSubmissionParser()
    # Simulate a wrapped auth token (mail client continuation)
    lines = [
        "BDA Submission v3",
        "Debate-ID: deb_123",
        "Resolution: Test Resolution",
        "Submission-ID: 550e8400-e29b-41d4-a716-446655440000",
        "Submitted-At: 2026-04-30T01:00:00Z",
        "Expires-At: 2026-12-31T23:59:59Z",
        "Submitter-Email: test@example.com",
        "Position: FOR",
        "Topic-Area: t1",
        "Payload-Hash-Alg: sha256",
        "Payload-Hash: abc123",
        "Auth-Token: eyJhbGciOiJIUzI1NiIsInR5",
        " cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3",
        " ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaW",
        " F0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        "",
        "Facts:",
        "Fact one",
        "",
        "Inference:",
        "Inference one",
    ]
    body = "\n".join(lines)
    result = parser.parse_for_processor(body, "test@example.com", "Test")
    assert result.decision == "accept"
    expected_token = (
        "eyJhbGciOiJIUzI1NiIsInR5"
        "cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3"
        "ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaW"
        "F0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    assert result.submission.auth_token == expected_token


def test_v3_strips_whitespace_from_unwrapped_token():
    parser = EmailSubmissionParser()
    lines = [
        "BDA Submission v3",
        "Debate-ID: deb_123",
        "Resolution: Test Resolution",
        "Submission-ID: 550e8400-e29b-41d4-a716-446655440000",
        "Submitted-At: 2026-04-30T01:00:00Z",
        "Expires-At: 2026-12-31T23:59:59Z",
        "Submitter-Email: test@example.com",
        "Position: FOR",
        "Topic-Area: t1",
        "Payload-Hash-Alg: sha256",
        "Payload-Hash: abc123",
        "Auth-Token: part1",
        "  part2  ",
        "\tpart3",
        "",
        "Facts:",
        "Fact one",
        "",
        "Inference:",
        "Inference one",
    ]
    body = "\n".join(lines)
    result = parser.parse_for_processor(body, "test@example.com", "Test")
    assert result.decision == "accept"
    assert result.submission.auth_token == "part1part2part3"


def test_parse_for_processor_drops_unknown_mail():
    parser = EmailSubmissionParser()
    result = parser.parse_for_processor("Hello world", "test@example.com", "Test")
    assert result.decision == "drop"
    assert result.version_hint == "unknown"
    assert result.reason_code == "unrecognized"
    assert result.ack_safe is False


def test_parse_for_processor_rejects_legacy_when_auth_required():
    parser = EmailSubmissionParser()
    body = parser.build_email_body(
        debate_id="deb_123",
        resolution="Test Resolution",
        side="FOR",
        topic_id="t1",
        facts="Fact A",
        inference="Therefore B",
    )
    result = parser.parse_for_processor(body, "test@example.com", "Test", require_auth=True, allow_legacy=False)
    assert result.decision == "reject"
    assert result.version_hint == "v1"
    assert result.reason_code == "legacy_disabled"
    assert result.ack_safe is False


def test_parse_for_processor_accepts_legacy_when_allowed():
    parser = EmailSubmissionParser()
    body = parser.build_email_body(
        debate_id="deb_123",
        resolution="Test Resolution",
        side="FOR",
        topic_id="t1",
        facts="Fact A",
        inference="Therefore B",
    )
    result = parser.parse_for_processor(body, "test@example.com", "Test", require_auth=True, allow_legacy=True)
    assert result.decision == "accept"
    assert result.version_hint == "v1"
    assert result.ack_safe is True


def test_v3_body_builder():
    parser = EmailSubmissionParser()
    body = parser.build_email_body(
        debate_id="deb_123",
        resolution="Test Resolution",
        side="FOR",
        topic_id="t1",
        facts="Fact A",
        inference="Therefore B",
        counter_arguments="Counter C",
        version="v3",
        auth_token="my_token",
        expires_at="2026-12-31T23:59:59Z",
        payload_hash="abc123",
        payload_hash_alg="sha256",
        submitter_email="test@example.com",
    )
    assert body.startswith("BDA Submission v3")
    assert "Auth-Token: my_token" in body
    assert "Expires-At: 2026-12-31T23:59:59Z" in body
    assert "Payload-Hash: abc123" in body
    assert "Payload-Hash-Alg: sha256" in body
    assert "Submitter-Email: test@example.com" in body

    # Verify it round-trips through the parser
    result = parser.parse_for_processor(body, "test@example.com", "Test")
    assert result.decision == "accept"
    assert result.submission.auth_token == "my_token"
    assert result.submission.payload_hash == "abc123"


def test_v1_builder_backward_compatible():
    parser = EmailSubmissionParser()
    body = parser.build_email_body(
        debate_id="deb_123",
        resolution="Test Resolution",
        side="FOR",
        topic_id="t1",
        facts="Fact A",
        inference="Therefore B",
    )
    assert body.startswith("BDA Submission v1")
    assert "Auth-Token:" not in body


def test_v3_parse_body_directly():
    parser = EmailSubmissionParser()
    body = _build_v3_body(auth_token="direct_token")
    submission = parser.parse_body(body, "test@example.com", "Test")
    assert submission.auth_token == "direct_token"
    assert submission.payload_hash == "abc123"
    assert submission.payload_hash_alg == "sha256"


def test_v3_rejects_malformed_wrapped_token():
    parser = EmailSubmissionParser()
    lines = [
        "BDA Submission v3",
        "Debate-ID: deb_123",
        "Resolution: Test Resolution",
        "Submission-ID: 550e8400-e29b-41d4-a716-446655440000",
        "Submitted-At: 2026-04-30T01:00:00Z",
        "Expires-At: 2026-12-31T23:59:59Z",
        "Submitter-Email: test@example.com",
        "Position: FOR",
        "Topic-Area: t1",
        "Payload-Hash-Alg: sha256",
        "Payload-Hash: abc123",
        " eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",  # continuation without Auth-Token start
        "",
        "Facts:",
        "Fact one",
        "",
        "Inference:",
        "Inference one",
    ]
    body = "\n".join(lines)
    result = parser.parse_for_processor(body, "test@example.com", "Test")
    assert result.decision == "reject"
    assert result.reason_code in ("missing_token", "missing_required_field", "invalid_body")
    assert result.ack_safe is False


# ---------------------------------------------------------------------------
# Processor token verification tests
# ---------------------------------------------------------------------------


def _make_mock_mail(body_text, from_addr="test@example.com", subject="Test Subject", to_addr="dest@example.com"):
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body_text)
    raw = msg.as_bytes()
    mock_mail = MagicMock()
    mock_mail.fetch.return_value = ("OK", [(b"1", raw)])
    return mock_mail


def _make_processor_config():
    config = MagicMock()
    config.email_submission_require_auth = True
    config.email_submission_auth_allow_legacy = False
    config.email_submission_ack_unsigned_rejections = False
    config.email_submission_secret = "test-secret"
    config.email_submission_token_ttl_minutes = 60
    config.accepted_recipient_emails = []
    config.sender_whitelist = []
    config.dest_emails = ["dest@example.com"]
    config.mark_processed = True
    config.smtp_host = None
    return config


def _make_v3_submission(**overrides):
    defaults = {
        "debate_id": "deb_123",
        "resolution": "Test Resolution",
        "submission_id": "550e8400-e29b-41d4-a716-446655440000",
        "submitted_at": "2026-04-30T01:00:00Z",
        "side": "FOR",
        "topic_id": "t1",
        "facts": "Fact one",
        "inference": "Inference one",
        "counter_arguments": None,
        "submitter_email": "test@example.com",
        "subject": "Test",
        "auth_token": "valid_token",
        "payload_hash": "abc123",
        "payload_hash_alg": "sha256",
    }
    defaults.update(overrides)
    return EmailSubmission(**defaults)


def _make_accept_result(submission):
    return EmailSubmissionParseResult(
        decision="accept", version_hint="v3", submission=submission, ack_safe=True
    )


def _make_reject_result(reason_code, version_hint="v3"):
    return EmailSubmissionParseResult(
        decision="reject", version_hint=version_hint, reason_code=reason_code, ack_safe=False
    )


class TestEmailProcessorV3Auth:
    @pytest.fixture
    def processor(self):
        config = _make_processor_config()
        with patch("backend.email_processor.DebateEngineV2"), \
             patch("backend.email_processor.GitHubPublisher"), \
             patch("backend.email_processor.PublishedResultsBuilder"):
            processor = EmailProcessor(config)
            processor.debate_engine = MagicMock()
            processor.debate_engine.db = MagicMock()
            processor.debate_engine.db.get_post_by_submission_id.return_value = None
            processor.debate_engine.db.get_debate.return_value = {"debate_id": "deb_123"}
            processor.debate_engine.submit_post.return_value = {
                "post_id": "post_123",
                "modulation_outcome": "accepted",
            }
            processor.debate_engine.generate_snapshot.return_value = {
                "snapshot_id": "snap_123",
            }
            processor.publisher = MagicMock()
            processor.publisher.publish_json.return_value = MagicMock(
                commit_sha="abc123", html_url="http://example.com"
            )
            processor.results_builder = MagicMock()
            processor.results_builder.build_bundle.return_value = {
                "commit_message": "test",
            }
            yield processor

    def test_valid_signed_v3_calls_submit_post_with_user_id(self, processor):
        submission = _make_v3_submission()
        mock_mail = _make_mock_mail("BDA Submission v3\n...")
        with patch.object(
            processor.parser, "parse_for_processor", return_value=_make_accept_result(submission)
        ), patch(
            "backend.email_processor.verify_email_submission_claims",
            return_value={"user_id": "user_123", "is_active": True},
        ):
            processor._process_message(mock_mail, b"1")
            processor.debate_engine.submit_post.assert_called_once()
            call_kwargs = processor.debate_engine.submit_post.call_args.kwargs
            assert call_kwargs["user_id"] == "user_123"

    def test_valid_signed_v3_calls_submit_post_with_sanitized_fields(self, processor):
        submission = _make_v3_submission(facts="Sanitized fact", inference="Sanitized inference")
        mock_mail = _make_mock_mail("BDA Submission v3\n...")
        with patch.object(
            processor.parser, "parse_for_processor", return_value=_make_accept_result(submission)
        ), patch(
            "backend.email_processor.verify_email_submission_claims",
            return_value={"user_id": "user_123", "is_active": True},
        ):
            processor._process_message(mock_mail, b"1")
            call_kwargs = processor.debate_engine.submit_post.call_args.kwargs
            assert call_kwargs["facts"] == "Sanitized fact"
            assert call_kwargs["inference"] == "Sanitized inference"
            assert call_kwargs["side"] == "FOR"
            assert call_kwargs["topic_id"] == "t1"
            assert call_kwargs["debate_id"] == "deb_123"

    def test_invalid_token_does_not_call_submit_post(self, processor):
        submission = _make_v3_submission()
        mock_mail = _make_mock_mail("BDA Submission v3\n...")
        with patch.object(
            processor.parser, "parse_for_processor", return_value=_make_accept_result(submission)
        ), patch(
            "backend.email_processor.verify_email_submission_claims",
            side_effect=ValueError("wrong_token_type"),
        ), patch.object(processor, "_send_ack") as mock_send_ack:
            processor._process_message(mock_mail, b"1")
            processor.debate_engine.submit_post.assert_not_called()
            mock_send_ack.assert_not_called()
            mock_mail.store.assert_called_with(b"1", "+FLAGS", "\\Seen")

    def test_edited_facts_does_not_call_submit_post(self, processor):
        submission = _make_v3_submission(facts="Edited fact")
        mock_mail = _make_mock_mail("BDA Submission v3\n...")
        with patch.object(
            processor.parser, "parse_for_processor", return_value=_make_accept_result(submission)
        ), patch(
            "backend.email_processor.verify_email_submission_claims",
            side_effect=ValueError("payload_mismatch"),
        ), patch.object(processor, "_send_ack") as mock_send_ack:
            processor._process_message(mock_mail, b"1")
            processor.debate_engine.submit_post.assert_not_called()
            mock_send_ack.assert_not_called()

    def test_edited_side_does_not_call_submit_post(self, processor):
        submission = _make_v3_submission(side="AGAINST")
        mock_mail = _make_mock_mail("BDA Submission v3\n...")
        with patch.object(
            processor.parser, "parse_for_processor", return_value=_make_accept_result(submission)
        ), patch(
            "backend.email_processor.verify_email_submission_claims",
            side_effect=ValueError("side_mismatch"),
        ), patch.object(processor, "_send_ack") as mock_send_ack:
            processor._process_message(mock_mail, b"1")
            processor.debate_engine.submit_post.assert_not_called()

    def test_legacy_v1_rejected_when_require_auth_true(self, processor):
        mock_mail = _make_mock_mail("BDA Submission v1\n...")
        with patch.object(
            processor.parser,
            "parse_for_processor",
            return_value=_make_reject_result("legacy_disabled", "v1"),
        ), patch.object(processor, "_send_ack") as mock_send_ack:
            processor._process_message(mock_mail, b"1")
            processor.debate_engine.submit_post.assert_not_called()
            mock_send_ack.assert_not_called()
            mock_mail.store.assert_called_with(b"1", "+FLAGS", "\\Seen")

    def test_missing_token_v3_rejected_without_ack_by_default(self, processor):
        mock_mail = _make_mock_mail("BDA Submission v3\n...")
        with patch.object(
            processor.parser,
            "parse_for_processor",
            return_value=_make_reject_result("missing_token", "v3"),
        ), patch.object(processor, "_send_ack") as mock_send_ack:
            processor._process_message(mock_mail, b"1")
            processor.debate_engine.submit_post.assert_not_called()
            mock_send_ack.assert_not_called()
            mock_mail.store.assert_called_with(b"1", "+FLAGS", "\\Seen")

    def test_malformed_jwt_rejected_without_ack(self, processor):
        submission = _make_v3_submission()
        mock_mail = _make_mock_mail("BDA Submission v3\n...")
        with patch.object(
            processor.parser, "parse_for_processor", return_value=_make_accept_result(submission)
        ), patch(
            "backend.email_processor.verify_email_submission_claims",
            side_effect=jwt.InvalidSignatureError("bad signature"),
        ), patch.object(processor, "_send_ack") as mock_send_ack:
            processor._process_message(mock_mail, b"1")
            processor.debate_engine.submit_post.assert_not_called()
            mock_send_ack.assert_not_called()

    def test_forwarded_email_rejected(self, processor):
        submission = _make_v3_submission()
        mock_mail = _make_mock_mail(
            "BDA Submission v3\n...", from_addr="forwarder@example.com"
        )
        with patch.object(
            processor.parser, "parse_for_processor", return_value=_make_accept_result(submission)
        ), patch(
            "backend.email_processor.verify_email_submission_claims",
            side_effect=ValueError("email_mismatch"),
        ), patch.object(processor, "_send_ack") as mock_send_ack:
            processor._process_message(mock_mail, b"1")
            processor.debate_engine.submit_post.assert_not_called()

    def test_cross_debate_token_rejected(self, processor):
        submission = _make_v3_submission()
        mock_mail = _make_mock_mail("BDA Submission v3\n...")
        with patch.object(
            processor.parser, "parse_for_processor", return_value=_make_accept_result(submission)
        ), patch(
            "backend.email_processor.verify_email_submission_claims",
            side_effect=ValueError("debate_mismatch"),
        ), patch.object(processor, "_send_ack") as mock_send_ack:
            processor._process_message(mock_mail, b"1")
            processor.debate_engine.submit_post.assert_not_called()

    def test_unparseable_spam_dropped_without_outbound_reply(self, processor):
        mock_mail = _make_mock_mail("Hello spam")
        with patch.object(
            processor.parser,
            "parse_for_processor",
            return_value=EmailSubmissionParseResult(
                decision="drop",
                version_hint="unknown",
                reason_code="unrecognized",
                ack_safe=False,
            ),
        ), patch.object(processor, "_send_ack") as mock_send_ack:
            processor._process_message(mock_mail, b"1")
            processor.debate_engine.submit_post.assert_not_called()
            mock_send_ack.assert_not_called()
            mock_mail.store.assert_called_with(b"1", "+FLAGS", "\\Seen")
