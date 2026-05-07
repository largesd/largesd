"""Acceptance tests for /api/debate/email-submission-draft (Task 02)."""

import ast
import jwt
import pytest

from backend.email_submission_auth import compute_payload_hash


@pytest.fixture
def draft_debate(client, auth_headers):
    """Create a debate and return its ID."""
    resp = client.post(
        "/api/debates",
        headers=auth_headers,
        json={
            "resolution": "Resolved: AI should be regulated.",
            "scope": "Evaluate the benefits and risks of regulating AI systems.",
        },
    )
    assert resp.status_code == 201
    return resp.get_json()["debate_id"]


class TestEmailSubmissionDraft:
    def test_logged_out_returns_401(self, client, csrf_token):
        resp = client.post(
            "/api/debate/email-submission-draft",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert resp.status_code == 401
        assert resp.get_json()["code"] == "AUTH_REQUIRED"

    def _post_draft(self, client, auth_headers, draft_debate):
        resp = client.post(
            "/api/debate/email-submission-draft",
            headers=auth_headers,
            json={
                "debate_id": draft_debate,
                "side": "FOR",
                "topic_id": "t1",
                "facts": "This is a fact statement that is more than five characters long.",
                "inference": "This is an inference that is more than five chars.",
                "counter_arguments": "",
            },
        )
        assert resp.status_code == 200
        return resp.get_json()

    def test_logged_in_returns_v3_body_with_auth_token(
        self, client, auth_headers, draft_debate
    ):
        data = self._post_draft(client, auth_headers, draft_debate)
        assert data["version"] == "BDA Submission v3"
        assert "Auth-Token:" in data["body"]
        assert "Payload-Hash:" in data["body"]

    def test_token_decodes_and_contains_required_claims(
        self, client, auth_headers, draft_debate, app
    ):
        data = self._post_draft(client, auth_headers, draft_debate)
        token_line = [l for l in data["body"].split("\n") if l.startswith("Auth-Token:")][0]
        token = token_line.split("Auth-Token: ")[1]
        decoded = jwt.decode(
            token,
            app.config["EMAIL_SUBMISSION_SECRET"],
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "type"]},
            leeway=60,
        )
        for claim in [
            "type", "user_id", "email", "debate_id", "submission_id",
            "side", "topic_id", "payload_hash", "payload_hash_alg", "exp", "iat",
        ]:
            assert claim in decoded, f"Missing claim: {claim}"
        assert decoded["type"] == "email_submission"
        assert decoded["debate_id"] == draft_debate
        assert decoded["side"] == "FOR"
        assert decoded["topic_id"] == "t1"
        assert decoded["payload_hash_alg"] == "sha256"

    def test_payload_hash_matches_body_and_recomputes(
        self, client, auth_headers, draft_debate
    ):
        data = self._post_draft(client, auth_headers, draft_debate)
        body_hash_line = [l for l in data["body"].split("\n") if l.startswith("Payload-Hash:")][0]
        body_hash = body_hash_line.split("Payload-Hash: ")[1]
        assert body_hash == data["payload_hash"]

        # Extract fields from body
        facts = data["body"].split("Facts:\n")[1].split("\n\nInference:")[0]
        inference = (
            data["body"].split("Inference:\n")[1].split("\n\nCounter-Arguments:")[0]
            if "Counter-Arguments:" in data["body"]
            else data["body"].split("Inference:\n")[1]
        )
        counter_args = ""
        if "Counter-Arguments:" in data["body"]:
            counter_args = data["body"].split("Counter-Arguments:\n")[1]

        recomputed = compute_payload_hash({
            "debate_id": draft_debate,
            "side": "FOR",
            "topic_id": "t1",
            "facts": facts,
            "inference": inference,
            "counter_arguments": counter_args,
        })
        assert recomputed == data["payload_hash"]

    def test_missing_dest_email_returns_400(self, client, auth_headers, draft_debate, app):
        old_dest = app.config["PROCESSOR_DEST_EMAIL"]
        app.config["PROCESSOR_DEST_EMAIL"] = ""
        try:
            resp = client.post(
                "/api/debate/email-submission-draft",
                headers=auth_headers,
                json={
                    "debate_id": draft_debate,
                    "side": "FOR",
                    "topic_id": "t1",
                    "facts": "Some facts here that are more than five chars long.",
                    "inference": "Some inference here that is more than five chars.",
                },
            )
            assert resp.status_code == 400
            assert resp.get_json()["code"] == "EMAIL_DEST_MISSING"
        finally:
            app.config["PROCESSOR_DEST_EMAIL"] = old_dest

    def test_nonexistent_debate_returns_404(self, client, auth_headers):
        resp = client.post(
            "/api/debate/email-submission-draft",
            headers=auth_headers,
            json={
                "debate_id": "nonexistent_debate",
                "side": "FOR",
                "topic_id": "t1",
                "facts": "Some facts here that are more than five chars long.",
                "inference": "Some inference here that is more than five chars.",
            },
        )
        assert resp.status_code == 404
        assert resp.get_json()["code"] == "DEBATE_NOT_AVAILABLE_FOR_POSTING"

    def test_auth_helper_has_zero_flask_imports(self):
        with open("backend/email_submission_auth.py") as f:
            tree = ast.parse(f.read())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        flask_imports = [i for i in imports if i and "flask" in i]
        assert not flask_imports, f"Flask imports found: {flask_imports}"
