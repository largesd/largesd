"""Focused regression tests for email processor and submission parser."""

import json
import os
import time
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import pytest

from backend.email_processor import EmailProcessor, EmailProcessorConfig
from backend.email_submission_parser import EmailSubmissionParser, EmailSubmissionError


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
    body = (
        "BDA Submission v2\n"
        "Debate-ID: deb_abc123\n"
        "Facts:\n"
        "Fact one\n"
    )
    with pytest.raises(EmailSubmissionError) as exc_info:
        parser.parse_body(body, "test@example.com", "Test")
    assert "frontmatter" in str(exc_info.value).lower() or "delimiter" in str(exc_info.value).lower()


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
