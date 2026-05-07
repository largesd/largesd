"""API integration tests for debate CRUD, posts, and related endpoints."""

import pytest


@pytest.fixture
def created_debate(client, auth_headers):
    """Helper fixture: create and return a debate ID."""
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
# Debate listing
# ---------------------------------------------------------------------------
def test_list_debates_anonymous(client):
    resp = client.get("/api/debates")
    assert resp.status_code == 200
    assert "debates" in resp.get_json()


def test_list_debates_authenticated(client, auth_headers, created_debate):
    resp = client.get("/api/debates", headers=auth_headers)
    assert resp.status_code == 200
    debates = resp.get_json()["debates"]
    assert any(d["debate_id"] == created_debate for d in debates)


# ---------------------------------------------------------------------------
# Debate creation
# ---------------------------------------------------------------------------
def test_create_debate_admin_success(client, auth_headers):
    resp = client.post(
        "/api/debates",
        headers=auth_headers,
        json={
            "resolution": "Resolved: Space exploration should be publicly funded.",
            "scope": "Assess the societal value of publicly funded space programs.",
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["debate_id"]
    assert "resolution" in data


def test_create_debate_non_admin_forbidden(client, regular_auth_headers):
    resp = client.post(
        "/api/debates",
        headers=regular_auth_headers,
        json={
            "resolution": "Resolved: Test.",
            "scope": "Test scope.",
        },
    )
    assert resp.status_code == 403


def test_create_debate_validation_error(client, auth_headers):
    resp = client.post(
        "/api/debates",
        headers=auth_headers,
        json={"resolution": "Short", "scope": "Too short"},
    )
    assert resp.status_code == 400
    assert "VALIDATION_ERROR" == resp.get_json().get("code")


def test_create_debate_unauthenticated(client):
    resp = client.post(
        "/api/debates",
        json={"resolution": "Resolved: Test.", "scope": "Test scope."},
    )
    # Without CSRF and without Bearer, CSRF check blocks it
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "CSRF_INVALID"


# ---------------------------------------------------------------------------
# Get debate
# ---------------------------------------------------------------------------
def test_get_debate_no_active(client):
    resp = client.get("/api/debate")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["has_debate"] is False


def test_get_debate_success(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.get("/api/debate", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["has_debate"] is True
    assert data["debate_id"] == created_debate


def test_get_debate_by_id_success(client, auth_headers, created_debate):
    resp = client.get(f"/api/debate/{created_debate}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["debate_id"] == created_debate


def test_get_debate_by_id_not_found(client, auth_headers):
    resp = client.get("/api/debate/nonexistent", headers=auth_headers)
    assert resp.status_code == 404


def test_get_debate_by_id_invalid_id(client, auth_headers):
    resp = client.get("/api/debate/bad!!!id", headers=auth_headers)
    assert resp.status_code == 400
    assert "VALIDATION_ERROR" == resp.get_json().get("code")


# ---------------------------------------------------------------------------
# Activate debate
# ---------------------------------------------------------------------------
def test_activate_debate_success(client, auth_headers, created_debate):
    resp = client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["debate_id"] == created_debate


def test_activate_debate_not_found(client, auth_headers):
    resp = client.post("/api/debate/nonexistent/activate", headers=auth_headers)
    assert resp.status_code == 404


def test_activate_debate_missing_auth(client, created_debate):
    from tests.integration.conftest import _get_csrf_from_cookie

    resp = client.post(
        f"/api/debate/{created_debate}/activate",
        headers={"X-CSRF-Token": _get_csrf_from_cookie(client)},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------
def test_submit_post_success(client, auth_headers, created_debate):
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
    data = resp.get_json()
    assert "post_id" in data
    assert data["side"] == "FOR"


def test_submit_post_no_active_debate(client, auth_headers):
    resp = client.post(
        "/api/debate/posts",
        headers=auth_headers,
        json={"side": "FOR", "topic_id": "t1", "facts": "Facts.", "inference": "Inference."},
    )
    assert resp.status_code == 400
    assert "No active debate" in resp.get_json()["error"]


def test_submit_post_validation_error(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.post(
        "/api/debate/posts",
        headers=auth_headers,
        json={"side": "INVALID", "topic_id": "t1", "facts": "Facts.", "inference": "Inference."},
    )
    assert resp.status_code == 400
    assert "VALIDATION_ERROR" == resp.get_json().get("code")


def test_get_posts_success(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    client.post(
        "/api/debate/posts",
        headers=auth_headers,
        json={
            "side": "FOR",
            "topic_id": "t1",
            "facts": "Some facts here.",
            "inference": "Some inference.",
        },
    )
    resp = client.get("/api/debate/posts", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["posts"]) >= 1


def test_get_posts_no_active_debate(client, auth_headers):
    resp = client.get("/api/debate/posts", headers=auth_headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Frame petitions
# ---------------------------------------------------------------------------
def test_create_frame_petition_success(client, auth_headers, created_debate):
    resp = client.post(
        f"/api/debate/{created_debate}/frame-petitions",
        headers=auth_headers,
        json={"candidate_frame": {"summary": "New frame", "criteria": ["logic"]}},
    )
    assert resp.status_code == 201
    assert "petition" in resp.get_json()


def test_create_frame_petition_not_found(client, auth_headers):
    resp = client.post(
        "/api/debate/nonexistent/frame-petitions",
        headers=auth_headers,
        json={"candidate_frame": {"summary": "New frame"}},
    )
    assert resp.status_code == 404


def test_list_frame_petitions(client, auth_headers, created_debate):
    resp = client.get(f"/api/debate/{created_debate}/frame-petitions", headers=auth_headers)
    assert resp.status_code == 200
    assert "petitions" in resp.get_json()


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------
def test_get_debate_incidents(client, auth_headers, created_debate):
    resp = client.get(f"/api/debate/{created_debate}/incidents", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["debate_id"] == created_debate
    assert "incidents" in resp.get_json()
