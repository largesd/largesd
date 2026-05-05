"""
Email Processor — Server-side daemon that ingests debate submissions via email
and publishes consolidated results to GitHub.

Usage:
    python -m backend.email_processor --poll-interval 60

Environment variables:
    IMAP_HOST         — IMAP server hostname (required)
    IMAP_PORT         — IMAP server port (default 993)
    IMAP_USER         — IMAP username (required)
    IMAP_PASSWORD     — IMAP password (required)
    IMAP_FOLDER       — Folder to poll (default INBOX)
    SMTP_HOST         — SMTP server for acknowledgments (optional)
    SMTP_PORT         — SMTP port (default 587)
    SMTP_USER         — SMTP username (optional)
    SMTP_PASSWORD     — SMTP password (optional)
    GITHUB_REPO       — GitHub repo 'owner/name' (required)
    GITHUB_TOKEN      — GitHub PAT (required)
    GITHUB_BRANCH     — Target branch (default main)
    DEBATE_DB_PATH    — SQLite DB path (default data/debate_system.db)
    FACT_CHECK_MODE   — OFFLINE or ONLINE_ALLOWLIST (default OFFLINE)
    LLM_PROVIDER      — mock or openrouter (default mock)
    NUM_JUDGES        — Number of judges (default 5)
    OPENROUTER_API_KEY— API key if using openrouter
    PROCESSOR_DEST_EMAIL — The destination email address that submissions are sent to.
                           Used to filter emails addressed to this account.
"""
import argparse
import email
import imaplib
import json
import os
import re
import smtplib
import sys
import time
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

# Ensure backend modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from debate_engine_v2 import DebateEngineV2
from email_submission_parser import EmailSubmissionParser, EmailSubmissionError
from github_publisher import GitHubPublisher, GitHubPublishError
from published_results import PublishedResultsBuilder


class EmailProcessorConfig:
    """Configuration for the email processor."""

    def __init__(self):
        self.imap_host = os.getenv("IMAP_HOST")
        self.imap_port = int(os.getenv("IMAP_PORT", "993"))
        self.imap_user = os.getenv("IMAP_USER")
        self.imap_password = os.getenv("IMAP_PASSWORD")
        self.imap_folder = os.getenv("IMAP_FOLDER", "INBOX")
        self.imap_use_ssl = os.getenv("IMAP_USE_SSL", "true").lower() in ("1", "true", "yes")

        self.smtp_host = os.getenv("SMTP_HOST")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")

        self.github_repo = os.getenv("GITHUB_REPO")
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.github_branch = os.getenv("GITHUB_BRANCH", "main")
        self.github_path = os.getenv("GITHUB_RESULTS_PATH", "data/consolidated_results.json")

        self.db_path = os.getenv("DEBATE_DB_PATH", "data/debate_system.db")
        self.fact_check_mode = os.getenv("FACT_CHECK_MODE", "OFFLINE")
        self.llm_provider = os.getenv("LLM_PROVIDER", "mock")
        self.num_judges = int(os.getenv("NUM_JUDGES", "5"))
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")

        self.dest_emails = self._parse_email_list(os.getenv("PROCESSOR_DEST_EMAIL", ""))
        self.dest_email = ", ".join(self.dest_emails)
        self.accepted_recipient_emails = self._build_expected_recipient_emails(
            self.dest_emails,
            self.imap_user,
            self.smtp_user,
        )
        self.sender_whitelist = self._parse_whitelist(os.getenv("SENDER_WHITELIST", ""))
        self.poll_interval = int(os.getenv("POLL_INTERVAL", "60"))
        self.mark_processed = os.getenv("MARK_PROCESSED", "true").lower() in ("1", "true", "yes")

    def is_valid(self) -> bool:
        return bool(
            self.imap_host and self.imap_user and self.imap_password
            and self.github_repo and self.github_token
        )

    @staticmethod
    def _parse_whitelist(value: str) -> List[str]:
        if not value:
            return []
        return [e.strip().lower() for e in value.split(",") if e.strip()]

    @staticmethod
    def _parse_email_list(value: str) -> List[str]:
        if not value:
            return []

        parsed = []
        seen = set()
        for _, addr in email.utils.getaddresses([value]):
            candidate = addr.lower().strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                parsed.append(candidate)

        if parsed:
            return parsed

        # Fallback for simple comma-separated values that may not parse cleanly.
        for part in value.split(","):
            candidate = part.lower().strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                parsed.append(candidate)
        return parsed

    @classmethod
    def _build_expected_recipient_emails(
        cls,
        dest_emails: List[str],
        imap_user: Optional[str],
        smtp_user: Optional[str],
    ) -> List[str]:
        expected = []
        seen = set()

        for candidate in dest_emails:
            if candidate not in seen:
                seen.add(candidate)
                expected.append(candidate)

        for raw in (imap_user or "", smtp_user or ""):
            for candidate in cls._parse_email_list(raw):
                if candidate not in seen:
                    seen.add(candidate)
                    expected.append(candidate)

        return expected


class EmailProcessor:
    """Polls an IMAP inbox for debate submissions and publishes results to GitHub."""

    RECIPIENT_HEADERS = (
        "To",
        "Cc",
        "Bcc",
        "Delivered-To",
        "X-Original-To",
        "Envelope-To",
        "Apparently-To",
        "Resent-To",
        "Resent-Cc",
    )

    def __init__(self, config: EmailProcessorConfig):
        self.config = config
        self.parser = EmailSubmissionParser()
        self.debate_engine = DebateEngineV2(
            db_path=config.db_path,
            fact_check_mode=config.fact_check_mode,
            llm_provider=config.llm_provider,
            num_judges=config.num_judges,
            openrouter_api_key=config.openrouter_api_key,
        )
        self.publisher = GitHubPublisher(
            repository_full_name=config.github_repo,
            token=config.github_token,
            path=config.github_path,
            branch=config.github_branch,
        )
        self.results_builder = PublishedResultsBuilder(
            db_path=config.db_path,
            engine=self.debate_engine,
        )

    def _log_startup(self, interval: Optional[int] = None) -> None:
        """Print the active processor configuration for diagnostics."""
        if interval is None:
            print("[EmailProcessor] Running single poll")
        else:
            print(f"[EmailProcessor] Starting poll loop (interval={interval}s)")
        print(f"[EmailProcessor] IMAP: {self.config.imap_host}:{self.config.imap_port}")
        print(f"[EmailProcessor] Mailbox: {self.config.imap_folder}")
        print(f"[EmailProcessor] GitHub: {self.config.github_repo}/{self.config.github_branch}")
        print(f"[EmailProcessor] DB: {self.config.db_path}")
        if self.config.accepted_recipient_emails:
            print(
                "[EmailProcessor] Accepting messages addressed to: "
                + ", ".join(self.config.accepted_recipient_emails)
            )

    def run(self, poll_interval: Optional[int] = None) -> None:
        """Run the polling loop indefinitely."""
        interval = poll_interval or self.config.poll_interval
        self._log_startup(interval=interval)

        while True:
            try:
                self._poll_once()
            except Exception as exc:
                print(f"[EmailProcessor] Error during poll: {exc}")
            time.sleep(interval)

    def _poll_once(self, search_criteria: str = "UNSEEN") -> None:
        """Connect to IMAP, fetch unread emails, process submissions."""
        # Before processing new mail, retry any queued failures
        self._retry_failed_publishes()

        if self.config.imap_use_ssl:
            mail = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port)
        else:
            mail = imaplib.IMAP4(self.config.imap_host, self.config.imap_port)

        try:
            mail.login(self.config.imap_user, self.config.imap_password)
            self._select_mailbox(mail)

            # Search for candidate messages
            status, messages = mail.search(None, search_criteria)
            if status != "OK":
                print(f"[EmailProcessor] Search failed for criteria: {search_criteria}")
                return

            raw_matches = messages[0] if messages else b""
            if not raw_matches:
                print(
                    f"[EmailProcessor] No messages matched search criteria: {search_criteria}"
                )
                return

            msg_ids = raw_matches.split()
            print(
                f"[EmailProcessor] Found {len(msg_ids)} message(s) for search: {search_criteria}"
            )

            # Backpressure: if >100 unread, batch process and slow down
            backpressure_threshold = int(os.getenv("EMAIL_BACKPRESSURE_THRESHOLD", "100"))
            if len(msg_ids) > backpressure_threshold:
                print(
                    f"[EmailProcessor] BACKPRESSURE: {len(msg_ids)} unread messages exceed "
                    f"threshold ({backpressure_threshold}). Processing in batches."
                )
                # Process only first batch, leave rest for next poll
                msg_ids = msg_ids[:backpressure_threshold]

            for msg_id in msg_ids:
                self._process_message(mail, msg_id)
        finally:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass

    def _select_mailbox(self, mail: imaplib.IMAP4) -> None:
        """
        Select the configured IMAP mailbox with compatibility retries.

        Some servers are picky about mailbox quoting, so we try both the raw
        value and an explicitly quoted variant.
        """
        mailbox = (self.config.imap_folder or "INBOX").strip()
        candidates = [mailbox]
        if not (mailbox.startswith('"') and mailbox.endswith('"')):
            candidates.append(f'"{mailbox}"')

        last_error: Optional[Exception] = None
        for candidate in candidates:
            try:
                status, _ = mail.select(candidate)
                if status == "OK":
                    if candidate != mailbox:
                        print(
                            f"[EmailProcessor] Selected mailbox via quoted fallback: {candidate}"
                        )
                    return
            except imaplib.IMAP4.error as exc:
                last_error = exc
                continue

        print(f"[EmailProcessor] Failed to select mailbox: {mailbox!r}")
        self._print_available_mailboxes(mail)
        if last_error:
            raise last_error
        raise imaplib.IMAP4.error(f"Unable to select mailbox: {mailbox!r}")

    @staticmethod
    def _print_available_mailboxes(mail: imaplib.IMAP4) -> None:
        """Print available mailboxes to help with IMAP_FOLDER debugging."""
        try:
            status, boxes = mail.list()
            if status != "OK" or not boxes:
                print("[EmailProcessor] Could not list mailboxes from server.")
                return

            print("[EmailProcessor] Available mailboxes:")
            for raw in boxes:
                if isinstance(raw, bytes):
                    print(f"  - {raw.decode('utf-8', errors='replace')}")
                else:
                    print(f"  - {raw}")
        except Exception as exc:
            print(f"[EmailProcessor] Failed to list mailboxes: {exc}")

    def _process_message(self, mail: imaplib.IMAP4, msg_id: bytes) -> None:
        """Fetch and process a single email message."""
        status, data = mail.fetch(msg_id, "(RFC822)")
        if status != "OK" or not data:
            return

        raw_email = data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = self._decode_header(msg.get("Subject", ""))
        from_addr = self._decode_header(msg.get("From", ""))
        submitter_email = self._extract_email(from_addr)
        recipient_emails = self._extract_recipient_emails(msg)

        print(f"[EmailProcessor] Processing email from {submitter_email}: {subject}")

        # Filter by destination email if configured
        if self.config.accepted_recipient_emails:
            if not self._is_addressed_to_expected_recipient(
                recipient_emails,
                self.config.accepted_recipient_emails,
            ):
                expected = ", ".join(self.config.accepted_recipient_emails)
                found = ", ".join(recipient_emails) if recipient_emails else "(none found)"
                print(
                    f"[EmailProcessor] Skipping — not addressed to {expected}"
                    f" (found: {found})"
                )
                return

        # Sender whitelist
        if self.config.sender_whitelist:
            if submitter_email.lower() not in self.config.sender_whitelist:
                print(f"[EmailProcessor] Skipping — sender not in whitelist")
                self._send_ack(submitter_email, subject, False, "Sender not in whitelist.")
                return

        # Extract plain-text body (with HTML fallback)
        body = self._get_text_body(msg)
        if not body:
            print("[EmailProcessor] No plain-text body found")
            self._send_ack(submitter_email, subject, False, "No plain-text body found.")
            return

        # Parse submission
        try:
            submission = self.parser.parse_body(body, submitter_email, subject)
        except EmailSubmissionError as exc:
            print(f"[EmailProcessor] Parse error: {exc}")
            self._send_ack(submitter_email, subject, False, f"Parse error: {exc}")
            return

        # DEDUPLICATION CHECK
        existing = self.debate_engine.db.get_post_by_submission_id(
            submission.submission_id
        )
        if existing:
            print(f"[EmailProcessor] Duplicate submission detected: {submission.submission_id}")
            self._send_ack(
                submitter_email,
                subject,
                True,  # treat as success since it was already processed
                f"Submission already processed (post {existing['post_id']}).",
            )
            if self.config.mark_processed:
                mail.store(msg_id, "+FLAGS", "\\Seen")
            return

        # Validate debate exists
        debate = self.debate_engine.db.get_debate(submission.debate_id)
        if not debate:
            print(f"[EmailProcessor] Debate not found: {submission.debate_id}")
            self._send_ack(submitter_email, subject, False, "Debate not found.")
            return

        # Submit to debate engine
        try:
            post = self.debate_engine.submit_post(
                debate_id=submission.debate_id,
                side=submission.side,
                topic_id=submission.topic_id,
                facts=submission.facts,
                inference=submission.inference,
                counter_arguments=submission.counter_arguments or "",
                submission_id=submission.submission_id,
            )
            print(f"[EmailProcessor] Post submitted: {post['post_id']} ({post['modulation_outcome']})")
        except Exception as exc:
            print(f"[EmailProcessor] Engine error: {exc}")
            self._send_ack(submitter_email, subject, False, f"Engine error: {exc}")
            return

        # Generate snapshot
        try:
            snapshot = self.debate_engine.generate_snapshot(
                debate_id=submission.debate_id,
                trigger_type="activity",
            )
            print(f"[EmailProcessor] Snapshot generated: {snapshot['snapshot_id']}")
        except Exception as exc:
            print(f"[EmailProcessor] Snapshot error: {exc}")
            self._send_ack(submitter_email, subject, False, f"Snapshot error: {exc}")
            return

        # Build and publish consolidated results with retry logic
        MAX_RETRIES = 3
        BASE_DELAY = 5  # seconds
        bundle = None
        result = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                bundle = self.results_builder.build_bundle(
                    debate_id=submission.debate_id,
                    commit_message=f"Snapshot {snapshot['snapshot_id']} — post {post['post_id']} via email",
                )
                result = self.publisher.publish_json(
                    payload=bundle,
                    commit_message=bundle["commit_message"],
                )
                print(f"[EmailProcessor] Published to GitHub: {result.commit_sha}")
                break  # success
            except GitHubPublishError as exc:
                print(f"[EmailProcessor] GitHub publish attempt {attempt} failed: {exc}")
                if attempt == MAX_RETRIES:
                    # Queue for later retry
                    self._queue_failed_publish(
                        submission.debate_id, snapshot, bundle, str(exc)
                    )
                    self._send_ack(
                        submitter_email, subject, False,
                        f"GitHub publish failed after {MAX_RETRIES} attempts. It will be retried automatically."
                    )
                    return
                time.sleep(BASE_DELAY * (2 ** (attempt - 1)))
            except Exception as exc:
                print(f"[EmailProcessor] Bundle/build error: {exc}")
                # Unexpected error, also queue if we have a bundle
                if bundle is not None:
                    self._queue_failed_publish(
                        submission.debate_id, snapshot, bundle, str(exc)
                    )
                self._send_ack(submitter_email, subject, False, f"Bundle error: {exc}")
                return

        # Send success acknowledgment
        self._send_ack(
            submitter_email,
            subject,
            True,
            f"Your submission was processed. Post {post['post_id']} ({post['modulation_outcome']}). "
            f"Snapshot {snapshot['snapshot_id']}. Published to GitHub: {result.html_url or result.commit_sha[:7]}",
        )

        # Mark as seen if configured
        if self.config.mark_processed:
            mail.store(msg_id, "+FLAGS", "\\Seen")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_header(value: str) -> str:
        """Decode MIME-encoded header values."""
        decoded_parts = email.header.decode_header(value)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(part)
        return "".join(result)

    @staticmethod
    def _extract_email(from_header: str) -> str:
        """Extract bare email from 'Name <email@example.com>'."""
        normalized = EmailProcessor._normalize_email_address(from_header)
        if normalized:
            return normalized

        m = re.search(r"<([^>]+)>", from_header)
        if m:
            return m.group(1).lower().strip()
        # Fallback: assume it's just an email
        return from_header.lower().strip()

    @staticmethod
    def _normalize_email_address(value: str) -> str:
        if not value:
            return ""

        _, parsed = email.utils.parseaddr(value)
        candidate = (parsed or value).strip().lower()
        if "@" not in candidate:
            return ""
        return candidate

    @classmethod
    def _extract_recipient_emails(cls, msg: email.message.Message) -> List[str]:
        decoded_values = []
        for header in cls.RECIPIENT_HEADERS:
            for raw_value in msg.get_all(header, []):
                decoded = cls._decode_header(raw_value)
                if decoded:
                    decoded_values.append(decoded)

        recipients = []
        seen = set()
        for _, addr in email.utils.getaddresses(decoded_values):
            normalized = cls._normalize_email_address(addr)
            if normalized and normalized not in seen:
                seen.add(normalized)
                recipients.append(normalized)
        return recipients

    @staticmethod
    def _is_addressed_to_expected_recipient(
        recipient_emails: List[str],
        expected_emails: List[str],
    ) -> bool:
        return bool(set(recipient_emails) & set(expected_emails))

    @staticmethod
    def _get_html_body(msg: email.message.Message) -> Optional[str]:
        """Extract HTML body from an email message."""
        html = None
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html = payload.decode(charset, errors="replace")
                        break
        else:
            if msg.get_content_type() == "text/html":
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
        return html

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to plain text using a lightweight parser."""
        class _HTMLToText(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = []
            def handle_data(self, data):
                self.text.append(data)
            def get_text(self):
                return re.sub(r'\n\s*\n+', '\n\n', ''.join(self.text)).strip()

        parser = _HTMLToText()
        try:
            parser.feed(html)
            return parser.get_text()
        except Exception:
            # Ultimate fallback: regex strip
            text = re.sub(r'<[^>]+>', '', html)
            return re.sub(r'\n\s*\n+', '\n\n', text).strip()

    @staticmethod
    def _get_text_body(msg: email.message.Message) -> Optional[str]:
        """Extract the plain-text body from an email message, falling back to HTML."""
        # Try plain text first
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")
        else:
            content_type = msg.get_content_type()
            if content_type == "text/plain":
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        # Fallback to HTML extraction and conversion
        html = EmailProcessor._get_html_body(msg)
        if html:
            return EmailProcessor._html_to_text(html)
        return None

    def _queue_failed_publish(self, debate_id, snapshot, bundle, error_msg):
        """Queue a failed GitHub publish for later retry."""
        if not hasattr(self.debate_engine.db, 'queue_failed_publish'):
            return
        self.debate_engine.db.queue_failed_publish(
            debate_id=debate_id,
            snapshot_id=snapshot.get('snapshot_id') if snapshot else None,
            payload_json=json.dumps(bundle) if bundle else "{}",
            commit_message=bundle["commit_message"] if bundle else "",
            last_error=error_msg,
        )

    def _retry_failed_publishes(self):
        """Retry any queued failed publishes from previous poll cycles."""
        if not hasattr(self.debate_engine.db, 'get_failed_publishes'):
            return
        pending = self.debate_engine.db.get_failed_publishes(limit=10)
        for item in pending:
            try:
                payload = json.loads(item['payload_json'])
                result = self.publisher.publish_json(
                    payload=payload,
                    commit_message=item['commit_message'],
                )
                self.debate_engine.db.mark_publish_success(item['id'])
                print(f"[EmailProcessor] Retried publish succeeded: {result.commit_sha}")
            except Exception as exc:
                self.debate_engine.db.increment_publish_retry(
                    item['id'], str(exc)
                )
                print(f"[EmailProcessor] Retried publish failed again: {exc}")

    def _send_ack(
        self,
        to_email: str,
        original_subject: str,
        success: bool,
        message: str,
    ) -> None:
        """Send an acknowledgment email back to the submitter."""
        if not self.config.smtp_host:
            return

        try:
            subject = f"Re: {original_subject}" if not original_subject.startswith("Re:") else original_subject
            status = "Success" if success else "Failed"

            msg = EmailMessage()
            msg["Subject"] = f"[{status}] {subject}"
            msg["From"] = self.config.smtp_user or self.config.imap_user
            msg["To"] = to_email
            msg.set_content(
                f"Blind Debate Adjudicator — Submission Status\n"
                f"{'=' * 50}\n\n"
                f"Status: {status}\n"
                f"Message: {message}\n\n"
                f"Original subject: {original_subject}\n"
                f"Processed at: {datetime.now(timezone.utc).replace(tzinfo=None).isoformat()}Z\n"
            )

            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
                server.starttls()
                server.login(
                    self.config.smtp_user or self.config.imap_user,
                    self.config.smtp_password or self.config.imap_password,
                )
                server.send_message(msg)
            print(f"[EmailProcessor] Ack sent to {to_email}")
        except Exception as exc:
            print(f"[EmailProcessor] Failed to send ack: {exc}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Poll IMAP inbox for debate submissions and publish to GitHub."
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=None,
        help="Polling interval in seconds (overrides env var)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Poll once and exit instead of looping",
    )
    parser.add_argument(
        "--include-seen",
        action="store_true",
        help="Search all messages in the mailbox instead of only UNSEEN ones.",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    config = EmailProcessorConfig()
    if not config.is_valid():
        print("[EmailProcessor] Configuration invalid. Required env vars:")
        print("  IMAP_HOST, IMAP_USER, IMAP_PASSWORD")
        print("  GITHUB_REPO, GITHUB_TOKEN")
        sys.exit(1)

    processor = EmailProcessor(config)

    if args.once:
        processor._log_startup()
        processor._poll_once(search_criteria="ALL" if args.include_seen else "UNSEEN")
    else:
        processor.run(poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()
