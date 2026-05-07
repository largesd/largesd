"""API integration tests for moderation, content filtering, and rate limiting."""

import importlib
import os

import pytest


@pytest.fixture
def created_debate(client, auth_headers):
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


# ---------------------------------------------------------------------------
# Content filtering via posts
# ---------------------------------------------------------------------------
def test_submit_post_blocked_toxicity(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.post(
        "/api/debate/posts",
        headers=auth_headers,
        json={
            "side": "FOR",
            "topic_id": "t1",
            "facts": "I will kill everyone who disagrees with me.",
            "inference": "Therefore, my view is the only valid one.",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["modulation_outcome"].lower() == "blocked"
    assert "toxicity" in (data.get("block_reason") or "").lower()


def test_submit_post_allowed(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.post(
        "/api/debate/posts",
        headers=auth_headers,
        json={
            "side": "FOR",
            "topic_id": "t1",
            "facts": "Studies show renewable energy creates jobs.",
            "inference": "Therefore, we should invest in solar power.",
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["modulation_outcome"].lower() == "allowed"


# ---------------------------------------------------------------------------
# Rate limiting (429)
# ---------------------------------------------------------------------------
def test_rate_limit_submit_post(client, auth_headers, created_debate):
    """Enable rate limiter and exceed the per-hour limit on submit_post."""
    import shutil
    import tempfile

    old_env = {k: os.environ.get(k) for k in ["ENABLE_RATE_LIMITER", "DEBATE_DB_PATH"]}
    temp_dir = tempfile.mkdtemp()
    os.environ["DEBATE_DB_PATH"] = os.path.join(temp_dir, "rate_limit.db")
    os.environ["ENABLE_RATE_LIMITER"] = "true"

    import backend.app_v3 as app_v3

    app_v3 = importlib.reload(app_v3)
    app = app_v3.create_app()
    app.config["TESTING"] = True
    test_client = app.test_client()

    # Register admin (first user -> auto admin)
    test_client.get("/login.html")
    csrf = test_client.get_cookie("csrf_token").value
    reg = test_client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": csrf},
        json={"email": "ratelimit@example.com", "password": "password123", "display_name": "Rate"},
    )
    token = reg.get_json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create and activate debate
    r = test_client.post(
        "/api/debates",
        headers=headers,
        json={
            "resolution": "Resolved: AI should be regulated.",
            "scope": "Evaluate the benefits and risks of regulating AI systems.",
        },
    )
    assert r.status_code == 201, f"Debate creation failed: {r.get_json()}"
    debate_id = r.get_json()["debate_id"]
    test_client.post(f"/api/debate/{debate_id}/activate", headers=headers)

    # Exhaust the 10/hour limit on submit_post
    last_status = 200
    last_resp = None
    for i in range(12):
        r = test_client.post(
            "/api/debate/posts",
            headers=headers,
            json={
                "side": "FOR",
                "topic_id": "t1",
                "facts": f"Facts number {i} for rate limit test.",
                "inference": "Inference here.",
            },
        )
        last_status = r.status_code
        last_resp = r
        if last_status == 429:
            break

    # Teardown
    try:
        app_v3.extensions.debate_engine.shutdown()
    except Exception:
        pass
    shutil.rmtree(temp_dir, ignore_errors=True)
    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    assert last_status == 429
    data = last_resp.get_json()
    assert data["code"] == "RATE_LIMITED"
    assert "Rate limit exceeded" in data["error"]


# ---------------------------------------------------------------------------
# Auth decorator behaviors
# ---------------------------------------------------------------------------
def test_login_required_rejects_missing_token(client, created_debate):
    from tests.integration.conftest import _get_csrf_from_cookie

    resp = client.post(
        f"/api/debate/{created_debate}/activate",
        headers={"X-CSRF-Token": _get_csrf_from_cookie(client)},
    )
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "AUTH_REQUIRED"


def test_login_required_rejects_invalid_token(client, created_debate):
    from tests.integration.conftest import _get_csrf_from_cookie

    resp = client.post(
        f"/api/debate/{created_debate}/activate",
        headers={
            "Authorization": "Bearer totally.invalid.token",
            "X-CSRF-Token": _get_csrf_from_cookie(client),
        },
    )
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "AUTH_INVALID"


def test_admin_required_rejects_non_admin(client, regular_auth_headers):
    resp = client.get("/api/admin/moderation-template/current", headers=regular_auth_headers)
    assert resp.status_code == 403


def test_admin_required_rejects_unauthenticated(client):
    resp = client.get("/api/admin/moderation-template/current")
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "AUTH_REQUIRED"


def test_optional_auth_allows_anonymous(client):
    resp = client.get("/api/debates")
    assert resp.status_code == 200


def test_optional_auth_allows_valid_token(client, auth_headers):
    resp = client.get("/api/debates", headers=auth_headers)
    assert resp.status_code == 200
