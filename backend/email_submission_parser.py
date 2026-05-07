"""
Email Submission Parser

Parses structured debate submission emails into validated submission objects.

Expected email body format:
----------------------------------------
BDA Submission v1
Debate-ID: <debate_id>
Resolution: <resolution text>
Submission-ID: <uuid>
Submitted-At: <ISO timestamp>
Position: FOR | AGAINST
Topic-Area: <topic_id>

Facts:
<fact text>

Inference:
<inference text>

Counter-Arguments:
<optional counter-arguments text>
----------------------------------------
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal


class EmailSubmissionError(ValueError):
    """Raised when an email submission is malformed."""

    pass


@dataclass(frozen=True)
class EmailSubmission:
    debate_id: str
    resolution: str
    submission_id: str
    submitted_at: str
    side: str  # 'FOR' or 'AGAINST'
    topic_id: str
    facts: str
    inference: str
    counter_arguments: str | None
    submitter_email: str
    subject: str
    auth_token: str | None = None
    payload_hash: str | None = None
    payload_hash_alg: str | None = None


@dataclass(frozen=True)
class EmailSubmissionParseResult:
    decision: Literal["accept", "reject", "drop"]
    version_hint: Literal["v1", "v2", "v3", "unknown"] = "unknown"
    reason_code: str = ""
    ack_safe: bool = False
    submission: EmailSubmission | None = None
    exception: Exception | None = None


class EmailSubmissionParser:
    """Parse structured debate submission emails."""

    HEADER_RE = re.compile(r"^BDA Submission v1\s*$")
    HEADER_V2_RE = re.compile(r"^BDA Submission v2\s*$")
    HEADER_V3_RE = re.compile(r"^BDA Submission v3\s*$")
    FIELD_RE = re.compile(r"^([A-Za-z-]+):\s*(.*)$")
    FRONTMATTER_DELIM = "---"

    REQUIRED_FIELDS = {
        "Debate-ID",
        "Resolution",
        "Submission-ID",
        "Submitted-At",
        "Position",
        "Topic-Area",
    }

    REQUIRED_FIELDS_V3 = {
        "Debate-ID",
        "Resolution",
        "Submission-ID",
        "Submitted-At",
        "Expires-At",
        "Submitter-Email",
        "Position",
        "Topic-Area",
        "Payload-Hash-Alg",
        "Payload-Hash",
        "Auth-Token",
    }

    REQUIRED_FIELDS_LEGACY = {
        "Debate-ID",
        "Resolution",
        "Submission-ID",
        "Submitted-At",
        "Position",
        "Topic-Area",
    }

    VALID_SIDES = {"FOR", "AGAINST"}

    def parse_body(
        self,
        body: str,
        submitter_email: str,
        subject: str,
    ) -> EmailSubmission:
        """
        Parse an email body into an EmailSubmission.

        Args:
            body: The plain-text email body.
            submitter_email: The From address.
            subject: The email subject line.

        Returns:
            EmailSubmission if valid.

        Raises:
            EmailSubmissionError if the format is invalid.
        """
        lines = body.replace("\r\n", "\n").split("\n")

        # Must start with a recognized magic header
        if not lines:
            raise EmailSubmissionError("Email body is empty.")
        stripped_first = lines[0].strip()
        if self.HEADER_RE.match(stripped_first):
            return self._parse_v1(lines, body, submitter_email, subject)
        elif self.HEADER_V2_RE.match(stripped_first):
            return self._parse_v2(body, submitter_email, subject)
        elif self.HEADER_V3_RE.match(stripped_first):
            return self._parse_v3(lines, body, submitter_email, subject)
        else:
            raise EmailSubmissionError(
                "Email body must start with 'BDA Submission v1', 'BDA Submission v2', or 'BDA Submission v3'"
            )

    def parse_for_processor(
        self,
        body: str,
        submitter_email: str,
        subject: str,
        require_auth: bool = True,
        allow_legacy: bool = False,
    ) -> EmailSubmissionParseResult:
        lines = body.replace("\r\n", "\n").split("\n")
        if not lines:
            return EmailSubmissionParseResult(
                decision="drop", version_hint="unknown", reason_code="unrecognized", ack_safe=False
            )

        stripped_first = lines[0].strip()
        if self.HEADER_RE.match(stripped_first):
            version = "v1"
        elif self.HEADER_V2_RE.match(stripped_first):
            version = "v2"
        elif self.HEADER_V3_RE.match(stripped_first):
            version = "v3"
        else:
            return EmailSubmissionParseResult(
                decision="drop", version_hint="unknown", reason_code="unrecognized", ack_safe=False
            )

        if version in ("v1", "v2"):
            if require_auth and not allow_legacy:
                return EmailSubmissionParseResult(
                    decision="reject",
                    version_hint=version,
                    reason_code="legacy_disabled",
                    ack_safe=False,
                )
            try:
                submission = self.parse_body(body, submitter_email, subject)
                return EmailSubmissionParseResult(
                    decision="accept", version_hint=version, submission=submission, ack_safe=True
                )
            except EmailSubmissionError as exc:
                return EmailSubmissionParseResult(
                    decision="reject",
                    version_hint=version,
                    reason_code="invalid_body",
                    ack_safe=False,
                    exception=exc,
                )

        # v3 path
        try:
            submission = self._parse_v3(lines, body, submitter_email, subject)
        except EmailSubmissionError as exc:
            # Determine if missing token => missing_token, else invalid_body
            reason = "invalid_body"
            if "Auth-Token" in str(exc) or "Missing required fields" in str(exc):
                missing = self.REQUIRED_FIELDS_V3 - self._extract_v3_headers(lines)
                if "Auth-Token" in missing:
                    reason = "missing_token"
                elif missing:
                    reason = "missing_required_field"
            return EmailSubmissionParseResult(
                decision="reject",
                version_hint="v3",
                reason_code=reason,
                ack_safe=False,
                exception=exc,
            )

        if require_auth and not submission.auth_token:
            return EmailSubmissionParseResult(
                decision="reject", version_hint="v3", reason_code="missing_token", ack_safe=False
            )

        return EmailSubmissionParseResult(
            decision="accept", version_hint="v3", submission=submission, ack_safe=True
        )

    def _extract_v3_headers(self, lines: list[str]) -> set[str]:
        """Extract header keys from a v3 body without fully parsing it."""
        headers: set[str] = set()
        i = 1
        auth_token_parts: list[str] = []
        in_auth_token = False

        while i < len(lines):
            line = lines[i]
            if in_auth_token:
                if line.startswith(" ") or line.startswith("\t"):
                    auth_token_parts.append(line.lstrip(" \t"))
                    i += 1
                    continue
                else:
                    if auth_token_parts:
                        headers.add("Auth-Token")
                    in_auth_token = False
            m = self.FIELD_RE.match(line)
            if m:
                key, value = m.group(1), m.group(2).strip()
                if key == "Auth-Token":
                    in_auth_token = True
                    auth_token_parts = [value]
                else:
                    headers.add(key)
                i += 1
            elif line.strip() == "":
                if in_auth_token:
                    if auth_token_parts:
                        headers.add("Auth-Token")
                    in_auth_token = False
                i += 1
                break
            else:
                if in_auth_token:
                    if auth_token_parts:
                        headers.add("Auth-Token")
                    in_auth_token = False
                i += 1
                break

        if in_auth_token and auth_token_parts:
            headers.add("Auth-Token")

        return headers

    def _parse_v1(
        self, lines: list[str], body: str, submitter_email: str, subject: str
    ) -> EmailSubmission:
        """Parse a BDA Submission v1 format."""
        # Parse headers
        headers: dict[str, str] = {}
        i = 1
        while i < len(lines):
            line = lines[i]
            m = self.FIELD_RE.match(line)
            if m:
                key, value = m.group(1), m.group(2).strip()
                headers[key] = value
                i += 1
            elif line.strip() == "":
                i += 1
                break
            else:
                i += 1
                break

        missing = self.REQUIRED_FIELDS - set(headers.keys())
        if missing:
            raise EmailSubmissionError(f"Missing required fields: {', '.join(missing)}")

        # Validate side
        side = headers["Position"].upper().strip()
        if side not in self.VALID_SIDES:
            raise EmailSubmissionError(
                f"Position must be FOR or AGAINST, got: {headers['Position']}"
            )

        # Extract body sections
        remaining = "\n".join(lines[i:])
        facts = self._extract_section(remaining, "Facts")
        inference = self._extract_section(remaining, "Inference")
        counter_arguments = self._extract_section(remaining, "Counter-Arguments")

        if not facts or not facts.strip():
            raise EmailSubmissionError("Facts section is required and cannot be empty.")
        if not inference or not inference.strip():
            raise EmailSubmissionError("Inference section is required and cannot be empty.")

        # Validate topic_id format
        topic_id = headers["Topic-Area"].strip().lower()
        if not re.match(r"^[a-z0-9_-]+$", topic_id):
            raise EmailSubmissionError(f"Invalid Topic-Area format: {topic_id}")

        return EmailSubmission(
            debate_id=headers["Debate-ID"].strip(),
            resolution=headers["Resolution"].strip(),
            submission_id=headers["Submission-ID"].strip(),
            submitted_at=headers["Submitted-At"].strip(),
            side=side,
            topic_id=topic_id,
            facts=facts.strip(),
            inference=inference.strip(),
            counter_arguments=counter_arguments.strip() if counter_arguments else None,
            submitter_email=submitter_email,
            subject=subject,
        )

    def _parse_v2(self, body: str, submitter_email: str, subject: str) -> EmailSubmission:
        """Parse a BDA Submission v2 format (YAML frontmatter)."""
        lines = body.replace("\r\n", "\n").split("\n")
        if len(lines) < 3 or lines[1].strip() != self.FRONTMATTER_DELIM:
            raise EmailSubmissionError("v2 format must have '---' delimiter on the second line.")

        # Extract frontmatter between --- delimiters
        frontmatter_lines: list[str] = []
        i = 2
        while i < len(lines):
            if lines[i].strip() == self.FRONTMATTER_DELIM:
                i += 1
                break
            frontmatter_lines.append(lines[i])
            i += 1
        else:
            raise EmailSubmissionError("v2 format frontmatter not closed with '---'.")

        headers: dict[str, str] = {}
        for line in frontmatter_lines:
            m = self.FIELD_RE.match(line)
            if m:
                key, value = m.group(1), m.group(2).strip()
                headers[key] = value

        missing = self.REQUIRED_FIELDS - set(headers.keys())
        if missing:
            raise EmailSubmissionError(f"Missing required fields: {', '.join(missing)}")

        # Validate side
        side = headers["Position"].upper().strip()
        if side not in self.VALID_SIDES:
            raise EmailSubmissionError(
                f"Position must be FOR or AGAINST, got: {headers['Position']}"
            )

        # Extract body sections from remaining text
        remaining = "\n".join(lines[i:])
        facts = self._extract_section(remaining, "Facts")
        inference = self._extract_section(remaining, "Inference")
        counter_arguments = self._extract_section(remaining, "Counter-Arguments")

        if not facts or not facts.strip():
            raise EmailSubmissionError("Facts section is required and cannot be empty.")
        if not inference or not inference.strip():
            raise EmailSubmissionError("Inference section is required and cannot be empty.")

        # Validate topic_id format
        topic_id = headers["Topic-Area"].strip().lower()
        if not re.match(r"^[a-z0-9_-]+$", topic_id):
            raise EmailSubmissionError(f"Invalid Topic-Area format: {topic_id}")

        return EmailSubmission(
            debate_id=headers["Debate-ID"].strip(),
            resolution=headers["Resolution"].strip(),
            submission_id=headers["Submission-ID"].strip(),
            submitted_at=headers["Submitted-At"].strip(),
            side=side,
            topic_id=topic_id,
            facts=facts.strip(),
            inference=inference.strip(),
            counter_arguments=counter_arguments.strip() if counter_arguments else None,
            submitter_email=submitter_email,
            subject=subject,
        )

    def _parse_v3(self, lines, body, submitter_email, subject):
        headers: dict[str, str] = {}
        i = 1
        auth_token_parts: list[str] = []
        in_auth_token = False

        while i < len(lines):
            line = lines[i]
            if in_auth_token:
                if line.startswith(" ") or line.startswith("\t"):
                    auth_token_parts.append(line.lstrip(" \t"))
                    i += 1
                    continue
                else:
                    # End of Auth-Token continuation
                    if auth_token_parts:
                        headers["Auth-Token"] = "".join(auth_token_parts)
                    in_auth_token = False
                    # Fall through to normal field parsing for this line
            m = self.FIELD_RE.match(line)
            if m:
                key, value = m.group(1), m.group(2).strip()
                if key == "Auth-Token":
                    in_auth_token = True
                    auth_token_parts = [value]
                else:
                    headers[key] = value
                i += 1
            elif line.strip() == "":
                if in_auth_token:
                    if auth_token_parts:
                        headers["Auth-Token"] = "".join(auth_token_parts)
                    in_auth_token = False
                i += 1
                break
            else:
                if in_auth_token:
                    if auth_token_parts:
                        headers["Auth-Token"] = "".join(auth_token_parts)
                    in_auth_token = False
                i += 1
                break

        if in_auth_token and auth_token_parts:
            headers["Auth-Token"] = "".join(auth_token_parts)

        missing = self.REQUIRED_FIELDS_V3 - set(headers.keys())
        if missing:
            raise EmailSubmissionError(f"Missing required fields: {', '.join(missing)}")

        side = headers["Position"].upper().strip()
        if side not in self.VALID_SIDES:
            raise EmailSubmissionError(
                f"Position must be FOR or AGAINST, got: {headers['Position']}"
            )

        remaining = "\n".join(lines[i:])
        facts = self._extract_section(remaining, "Facts")
        inference = self._extract_section(remaining, "Inference")
        counter_arguments = self._extract_section(remaining, "Counter-Arguments")

        if not facts or not facts.strip():
            raise EmailSubmissionError("Facts section is required and cannot be empty.")
        if not inference or not inference.strip():
            raise EmailSubmissionError("Inference section is required and cannot be empty.")

        topic_id = headers["Topic-Area"].strip().lower()
        if not re.match(r"^[a-z0-9_-]+$", topic_id):
            raise EmailSubmissionError(f"Invalid Topic-Area format: {topic_id}")

        # Strip all internal whitespace from auth token before returning
        raw_token = headers.get("Auth-Token", "")
        cleaned_token = "".join(raw_token.split()) if raw_token else None

        return EmailSubmission(
            debate_id=headers["Debate-ID"].strip(),
            resolution=headers["Resolution"].strip(),
            submission_id=headers["Submission-ID"].strip(),
            submitted_at=headers["Submitted-At"].strip(),
            side=side,
            topic_id=topic_id,
            facts=facts.strip(),
            inference=inference.strip(),
            counter_arguments=counter_arguments.strip() if counter_arguments else None,
            submitter_email=submitter_email,
            subject=subject,
            auth_token=cleaned_token,
            payload_hash=headers.get("Payload-Hash"),
            payload_hash_alg=headers.get("Payload-Hash-Alg"),
        )

    def _extract_section(self, text: str, section_name: str) -> str | None:
        """Extract text after a section header like 'Facts:'."""
        # PASS 1: tolerant regex allowing single or double newlines
        pattern = (
            rf"(?:^|\n){{1,2}}\s*{re.escape(section_name)}\s*:\s*\n?"
            rf"(.*?)"
            rf"(?=(?:\n){{1,2}}\s*[A-Za-z-]+\s*:\s*\n|\Z)"
        )
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()

        # PASS 2: line-by-line scan (existing fallback, slightly improved)
        lines = text.split("\n")
        capturing = False
        captured: list[str] = []
        for line in lines:
            stripped = line.strip()
            if re.match(rf"^{re.escape(section_name)}\s*:\s*$", stripped, re.IGNORECASE):
                capturing = True
                continue
            if capturing and re.match(r"^[A-Za-z-]+\s*:\s*$", stripped):
                break
            if capturing:
                captured.append(line)
        if captured:
            return "\n".join(captured).strip()
        return None

    def build_email_body(
        self,
        debate_id: str,
        resolution: str,
        side: str,
        topic_id: str,
        facts: str,
        inference: str,
        counter_arguments: str | None = None,
        version: str = "v1",
        auth_token: str | None = None,
        expires_at: str | None = None,
        payload_hash: str | None = None,
        payload_hash_alg: str = "sha256",
        submitter_email: str = "",
    ) -> str:
        """
        Build a structured email body for frontend mailto: generation.

        Args:
            debate_id: The target debate ID.
            resolution: The debate resolution text.
            side: 'FOR' or 'AGAINST'.
            topic_id: The topic area ID.
            facts: The factual premises.
            inference: The inference/conclusion.
            counter_arguments: Optional counter-arguments addressed.
            version: Format version ('v1' or 'v3').
            auth_token: Auth token for v3 submissions.
            expires_at: Expiration timestamp for v3 submissions.
            payload_hash: Payload hash for v3 submissions.
            payload_hash_alg: Hash algorithm for v3 submissions.
            submitter_email: Submitter email for v3 submissions.

        Returns:
            A formatted plain-text email body.
        """
        if version == "v3":
            return self._build_v3_body(
                debate_id=debate_id,
                resolution=resolution,
                side=side,
                topic_id=topic_id,
                facts=facts,
                inference=inference,
                counter_arguments=counter_arguments,
                auth_token=auth_token,
                expires_at=expires_at,
                payload_hash=payload_hash,
                payload_hash_alg=payload_hash_alg,
                submitter_email=submitter_email,
            )

        submission_id = str(uuid.uuid4())
        submitted_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        lines = [
            "BDA Submission v1",
            f"Debate-ID: {debate_id}",
            f"Resolution: {resolution}",
            f"Submission-ID: {submission_id}",
            f"Submitted-At: {submitted_at}",
            f"Position: {side}",
            f"Topic-Area: {topic_id}",
            "",
            "Facts:",
            facts,
            "",
            "Inference:",
            inference,
        ]
        if counter_arguments:
            lines.extend(
                [
                    "",
                    "Counter-Arguments:",
                    counter_arguments,
                ]
            )
        return "\n".join(lines)

    def _build_v3_body(
        self,
        debate_id: str,
        resolution: str,
        side: str,
        topic_id: str,
        facts: str,
        inference: str,
        counter_arguments: str | None = None,
        auth_token: str | None = None,
        expires_at: str | None = None,
        payload_hash: str | None = None,
        payload_hash_alg: str = "sha256",
        submitter_email: str = "",
    ) -> str:
        """Build a BDA Submission v3 format email body."""
        submission_id = str(uuid.uuid4())
        submitted_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        lines = [
            "BDA Submission v3",
            f"Debate-ID: {debate_id}",
            f"Resolution: {resolution}",
            f"Submission-ID: {submission_id}",
            f"Submitted-At: {submitted_at}",
            f"Expires-At: {expires_at or ''}",
            f"Submitter-Email: {submitter_email}",
            f"Position: {side}",
            f"Topic-Area: {topic_id}",
            f"Payload-Hash-Alg: {payload_hash_alg}",
            f"Payload-Hash: {payload_hash or ''}",
            f"Auth-Token: {auth_token or ''}",
            "",
            "Facts:",
            facts,
            "",
            "Inference:",
            inference,
        ]
        if counter_arguments:
            lines.extend(
                [
                    "",
                    "Counter-Arguments:",
                    counter_arguments,
                ]
            )
        return "\n".join(lines)
