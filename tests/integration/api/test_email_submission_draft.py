"""Integration tests for /api/debate/email-submission-draft (Task 06)."""

import importlib
import os

import jwt
import pytest


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


class TestEmailSubmissionDraftAuth:
    def test_post_without_auth_returns_401(self, client, csrf_token):
        resp = client.post(
            "/api/debate/email-submission-draft",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert resp.status_code == 401
        assert resp.get_json()["code"] == "AUTH_REQUIRED"


class TestEmailSubmissionDraftBody:
    def _post_draft(self, client, auth_headers, draft_debate, **overrides):
        payload = {
            "debate_id": draft_debate,
            "side": "FOR",
            "topic_id": "t1",
            "facts": "This is a fact statement that is more than five characters long.",
            "inference": "This is an inference that is more than five chars.",
            "counter_arguments": "",
            **overrides,
        }
        resp = client.post(
            "/api/debate/email-submission-draft",
            headers=auth_headers,
            json=payload,
        )
        return resp

    def test_logged_in_receives_v3_body_and_mailto(self, client, auth_headers, draft_debate):
        resp = self._post_draft(client, auth_headers, draft_debate)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"] == "BDA Submission v3"
        assert "mailto:" in data["mailto"]
        assert "Auth-Token:" in data["body"]
        assert "Payload-Hash:" in data["body"]

    def test_response_payload_hash_matches_token_claim(
        self, client, auth_headers, draft_debate, app
    ):
        resp = self._post_draft(client, auth_headers, draft_debate)
        assert resp.status_code == 200
        data = resp.get_json()

        # Extract token from body
        token_line = [line for line in data["body"].split("\n") if line.startswith("Auth-Token:")][
            0
        ]
        token = token_line.split("Auth-Token: ")[1]

        decoded = jwt.decode(
            token,
            app.config["EMAIL_SUBMISSION_SECRET"],
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "type"]},
            leeway=60,
        )
        assert decoded["payload_hash"] == data["payload_hash"]
        assert decoded["payload_hash_alg"] == "sha256"

    def test_response_mailto_contains_destination_email(
        self, client, auth_headers, draft_debate, app
    ):
        resp = self._post_draft(client, auth_headers, draft_debate)
        assert resp.status_code == 200
        data = resp.get_json()
        dest_email = app.config["PROCESSOR_DEST_EMAIL"]
        assert dest_email in data["mailto"]


class TestEmailSubmissionDraftValidation:
    def _post_draft(self, client, auth_headers, draft_debate, **overrides):
        payload = {
            "debate_id": draft_debate,
            "side": "FOR",
            "topic_id": "t1",
            "facts": "This is a fact statement that is more than five characters long.",
            "inference": "This is an inference that is more than five chars.",
            **overrides,
        }
        resp = client.post(
            "/api/debate/email-submission-draft",
            headers=auth_headers,
            json=payload,
        )
        return resp

    def test_invalid_side_returns_validation_error(self, client, auth_headers, draft_debate):
        resp = self._post_draft(client, auth_headers, draft_debate, side="INVALID")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data.get("code") == "VALIDATION_ERROR" or "side" in data.get("error", "").lower()

    def test_invalid_topic_id_returns_validation_error(self, client, auth_headers, draft_debate):
        resp = self._post_draft(client, auth_headers, draft_debate, topic_id="BAD TOPIC!")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data.get("code") == "VALIDATION_ERROR" or "topic" in data.get("error", "").lower()

    def test_empty_facts_returns_validation_error(self, client, auth_headers, draft_debate):
        resp = self._post_draft(client, auth_headers, draft_debate, facts="")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data.get("code") == "VALIDATION_ERROR" or "facts" in data.get("error", "").lower()

    def test_empty_inference_returns_validation_error(self, client, auth_headers, draft_debate):
        resp = self._post_draft(client, auth_headers, draft_debate, inference="")
        assert resp.status_code == 400
        data = resp.get_json()
        assert (
            data.get("code") == "VALIDATION_ERROR" or "inference" in data.get("error", "").lower()
        )


class TestEmailSubmissionDraftErrors:
    def _post_draft(self, client, auth_headers, draft_debate, **overrides):
        payload = {
            "debate_id": draft_debate,
            "side": "FOR",
            "topic_id": "t1",
            "facts": "This is a fact statement that is more than five characters long.",
            "inference": "This is an inference that is more than five chars.",
            **overrides,
        }
        resp = client.post(
            "/api/debate/email-submission-draft",
            headers=auth_headers,
            json=payload,
        )
        return resp

    def test_cache_only_debate_id_returns_not_available(self, client, auth_headers):
        """A debate_id that is not persisted in the DB should return 404."""
        resp = client.post(
            "/api/debate/email-submission-draft",
            headers=auth_headers,
            json={
                "debate_id": "definitely_not_in_db_12345",
                "side": "FOR",
                "topic_id": "t1",
                "facts": "Some facts here that are more than five chars long.",
                "inference": "Some inference here that is more than five chars.",
            },
        )
        assert resp.status_code == 404
        assert resp.get_json()["code"] == "DEBATE_NOT_AVAILABLE_FOR_POSTING"

    def test_missing_processor_dest_email_returns_400(
        self, client, auth_headers, draft_debate, app
    ):
        old_dest = app.config["PROCESSOR_DEST_EMAIL"]
        app.config["PROCESSOR_DEST_EMAIL"] = ""
        try:
            resp = self._post_draft(client, auth_headers, draft_debate)
            assert resp.status_code == 400
            assert resp.get_json()["code"] == "EMAIL_DEST_MISSING"
        finally:
            app.config["PROCESSOR_DEST_EMAIL"] = old_dest


class TestEmailSubmissionDraftRateLimit:
    def test_rate_limit_decorator_configured_for_draft_endpoint(self, monkeypatch):
        """Verify the draft endpoint has a per-user rate limit configured."""
        redis = pytest.importorskip("redis")
        from flask_limiter import Limiter

        captured_calls = []
        original_limit = Limiter.limit

        def tracking_limit(self, limit_value, **kwargs):
            captured_calls.append({"limit_value": limit_value, "kwargs": kwargs})
            return original_limit(self, limit_value, **kwargs)

        monkeypatch.setattr(Limiter, "limit", tracking_limit)

        original_init = Limiter.__init__

        def mock_limiter_init(self, *args, **kwargs):
            kwargs["storage_uri"] = "memory://"
            return original_init(self, *args, **kwargs)

        monkeypatch.setattr(Limiter, "__init__", mock_limiter_init)

        class FakeRedis:
            def ping(self):
                return True

        monkeypatch.setattr(redis, "from_url", lambda url, **kwargs: FakeRedis())

        env_keys = [
            "ENABLE_RATE_LIMITER",
            "REDIS_URL",
            "ENV",
            "DEBATE_DB_PATH",
            "SECRET_KEY",
            "ADMIN_ACCESS_MODE",
            "ADMIN_USER_EMAILS",
            "ADMIN_USER_IDS",
            "DISABLE_JOB_WORKER",
            "ALLOWED_ORIGINS",
            "LLM_PROVIDER",
            "PROCESSOR_DEST_EMAIL",
        ]
        old_env = {k: os.environ.get(k) for k in env_keys}
        os.environ["ENABLE_RATE_LIMITER"] = "true"
        os.environ["REDIS_URL"] = "redis://localhost:6379/0"
        os.environ["ENV"] = "development"
        os.environ["DEBATE_DB_PATH"] = old_env.get("DEBATE_DB_PATH") or os.environ.get(
            "DEBATE_DB_PATH", "data/debate_system.db"
        )
        os.environ["SECRET_KEY"] = "test-secret-key-32-bytes-long!!!"
        os.environ["ADMIN_ACCESS_MODE"] = "authenticated"
        os.environ["ADMIN_USER_EMAILS"] = ""
        os.environ["ADMIN_USER_IDS"] = ""
        os.environ["DISABLE_JOB_WORKER"] = "1"
        os.environ["ALLOWED_ORIGINS"] = ""
        os.environ["LLM_PROVIDER"] = "mock"
        os.environ["PROCESSOR_DEST_EMAIL"] = "processor@example.com"

        try:
            import backend.app_v3 as app_v3

            app_v3 = importlib.reload(app_v3)
            app = app_v3.create_app()
            app.config["TESTING"] = True

            # One of the captured calls should be the draft endpoint limit
            draft_calls = [c for c in captured_calls if c["limit_value"] == "5 per hour"]
            assert len(draft_calls) >= 1, f"Expected '5 per hour' limit, got: {captured_calls}"
            # The key_func should be a callable (lambda g.user["user_id"])
            assert callable(draft_calls[0]["kwargs"]["key_func"])
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
