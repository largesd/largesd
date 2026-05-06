"""API integration tests for snapshot endpoints."""
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
# Snapshot generation
# ---------------------------------------------------------------------------
def test_generate_snapshot_success(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.post(
        "/api/debate/snapshot",
        headers=auth_headers,
        json={"trigger_type": "manual"},
    )
    assert resp.status_code == 202
    data = resp.get_json()
    assert "job_id" in data
    assert data["status"] == "queued"


def test_generate_snapshot_no_active_debate(client, auth_headers):
    resp = client.post("/api/debate/snapshot", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert "No active debate" in resp.get_json()["error"]


def test_generate_snapshot_invalid_trigger(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.post(
        "/api/debate/snapshot",
        headers=auth_headers,
        json={"trigger_type": "invalid"},
    )
    assert resp.status_code == 400
    assert "VALIDATION_ERROR" == resp.get_json().get("code")


def test_generate_snapshot_missing_auth(client, created_debate):
    from tests.integration.conftest import _get_csrf_from_cookie
    resp = client.post(
        "/api/debate/snapshot",
        headers={"X-CSRF-Token": _get_csrf_from_cookie(client)},
        json={"trigger_type": "manual"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Snapshot job polling
# ---------------------------------------------------------------------------
def test_get_snapshot_job_not_found(client, auth_headers):
    resp = client.get("/api/debate/snapshot-jobs/nonexistent-job", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Current snapshot
# ---------------------------------------------------------------------------
def test_get_current_snapshot_no_snapshot(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.get("/api/debate/snapshot", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["has_snapshot"] is False
    assert data["verdict"] == "NO VERDICT"


def test_get_current_snapshot_no_active_debate(client, auth_headers):
    resp = client.get("/api/debate/snapshot", headers=auth_headers)
    assert resp.status_code == 400
    assert "No active debate" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# Snapshot history
# ---------------------------------------------------------------------------
def test_get_snapshot_history(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.get("/api/debate/snapshot-history", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["debate_id"] == created_debate
    assert "snapshots" in data


def test_get_snapshot_history_no_active_debate(client, auth_headers):
    resp = client.get("/api/debate/snapshot-history", headers=auth_headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Snapshot diff
# ---------------------------------------------------------------------------
def test_get_snapshot_diff_need_two(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.get("/api/debate/snapshot-diff", headers=auth_headers)
    assert resp.status_code == 400
    assert "Need at least 2 snapshots" in resp.get_json()["error"]


def test_get_snapshot_diff_no_active_debate(client, auth_headers):
    resp = client.get("/api/debate/snapshot-diff", headers=auth_headers)
    assert resp.status_code == 400
