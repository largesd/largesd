"""API integration tests for governance endpoints."""
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
# Frames
# ---------------------------------------------------------------------------
def test_get_frames(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.get("/api/governance/frames", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "active_frame" in data
    assert "frames" in data


# ---------------------------------------------------------------------------
# Frame cadence
# ---------------------------------------------------------------------------
def test_get_frame_cadence(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.get("/api/governance/frame-cadence", headers=auth_headers)
    assert resp.status_code == 200
    assert "review_schedule" in resp.get_json()


def test_set_frame_cadence_admin(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.post(
        "/api/governance/frame-cadence",
        headers=auth_headers,
        json={"review_cadence_months": 12},
    )
    assert resp.status_code == 200


def test_set_frame_cadence_no_active_debate(client, auth_headers):
    resp = client.post(
        "/api/governance/frame-cadence",
        headers=auth_headers,
        json={"review_cadence_months": 12},
    )
    assert resp.status_code == 400


def test_set_frame_cadence_non_admin(client, regular_auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=regular_auth_headers)
    resp = client.post(
        "/api/governance/frame-cadence",
        headers=regular_auth_headers,
        json={"review_cadence_months": 12},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Emergency override
# ---------------------------------------------------------------------------
def test_emergency_override_admin(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.post(
        "/api/governance/emergency-override",
        headers=auth_headers,
        json={"reason": "Urgent need to update the frame for this debate."},
    )
    assert resp.status_code == 200
    assert "governance_decision_id" in resp.get_json()


def test_emergency_override_no_active_debate(client, auth_headers):
    resp = client.post(
        "/api/governance/emergency-override",
        headers=auth_headers,
        json={"reason": "Urgent need to update the frame for this debate."},
    )
    assert resp.status_code == 400


def test_emergency_override_non_admin(client, regular_auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=regular_auth_headers)
    resp = client.post(
        "/api/governance/emergency-override",
        headers=regular_auth_headers,
        json={"reason": "Urgent need to update the frame for this debate."},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Changelog
# ---------------------------------------------------------------------------
def test_get_changelog(client, auth_headers):
    resp = client.get("/api/governance/changelog", headers=auth_headers)
    assert resp.status_code == 200
    assert "entries" in resp.get_json()


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------
def test_get_appeals(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.get("/api/governance/appeals", headers=auth_headers)
    assert resp.status_code == 200
    assert "appeals" in resp.get_json()


def test_submit_appeal_no_snapshot(client, auth_headers, created_debate):
    resp = client.post(
        f"/api/debate/{created_debate}/appeals",
        headers=auth_headers,
        json={
            "appeal_type": "moderation_error",
            "description": "The moderation was too strict.",
            "requested_relief": "Please review and correct.",
        },
    )
    assert resp.status_code == 404
    assert "No snapshot available" in resp.get_json()["error"]


def test_get_my_appeals(client, auth_headers, created_debate):
    resp = client.get(f"/api/debate/{created_debate}/appeals/mine", headers=auth_headers)
    assert resp.status_code == 200
    assert "appeals" in resp.get_json()


# ---------------------------------------------------------------------------
# Judge pool
# ---------------------------------------------------------------------------
def test_get_judge_pool(client, auth_headers):
    resp = client.get("/api/governance/judge-pool", headers=auth_headers)
    assert resp.status_code == 200


def test_get_rotation_policy(client, auth_headers):
    resp = client.get("/api/governance/judge-pool/rotation-policy", headers=auth_headers)
    assert resp.status_code == 200


def test_set_rotation_policy_admin(client, auth_headers):
    resp = client.post(
        "/api/governance/judge-pool/rotation-policy",
        headers=auth_headers,
        json={"max_consecutive_snapshots": 3, "cooldown_snapshots": 1},
    )
    assert resp.status_code == 201
    assert "policy_id" in resp.get_json()


def test_set_rotation_policy_non_admin(client, regular_auth_headers):
    resp = client.post(
        "/api/governance/judge-pool/rotation-policy",
        headers=regular_auth_headers,
        json={"max_consecutive_snapshots": 3},
    )
    assert resp.status_code == 403


def test_get_calibration_protocol(client, auth_headers):
    resp = client.get("/api/governance/judge-pool/calibration-protocol", headers=auth_headers)
    assert resp.status_code == 200


def test_set_calibration_protocol_admin(client, auth_headers):
    resp = client.post(
        "/api/governance/judge-pool/calibration-protocol",
        headers=auth_headers,
        json={"guideline_version": "v2.0"},
    )
    assert resp.status_code == 201
    assert "protocol_id" in resp.get_json()


def test_log_conflict_of_interest_admin(client, auth_headers):
    resp = client.post(
        "/api/governance/judge-pool/conflict-of-interest",
        headers=auth_headers,
        json={"judge_id": "judge_1", "conflict_type": "recusal", "description": "Conflict."},
    )
    assert resp.status_code == 201
    assert "entry_id" in resp.get_json()


# ---------------------------------------------------------------------------
# Fairness audits & incidents
# ---------------------------------------------------------------------------
def test_get_fairness_audits(client, auth_headers):
    resp = client.get("/api/governance/fairness-audits", headers=auth_headers)
    assert resp.status_code == 200


def test_get_incidents(client, auth_headers):
    resp = client.get("/api/governance/incidents", headers=auth_headers)
    assert resp.status_code == 200
    assert "incidents" in resp.get_json()


def test_get_incidents_invalid_severity(client, auth_headers):
    resp = client.get("/api/governance/incidents?severity=invalid", headers=auth_headers)
    assert resp.status_code == 400
    assert "Invalid severity" in resp.get_json()["error"]


def test_get_governance_summary(client, auth_headers):
    resp = client.get("/api/governance/summary", headers=auth_headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Admin appeal routes
# ---------------------------------------------------------------------------
def test_get_admin_appeals_success(client, auth_headers):
    resp = client.get("/api/admin/appeals", headers=auth_headers)
    assert resp.status_code == 200
    assert "appeals" in resp.get_json()


def test_get_admin_appeals_non_admin(client, regular_auth_headers):
    resp = client.get("/api/admin/appeals", headers=regular_auth_headers)
    assert resp.status_code == 403


def test_resolve_appeal_not_found(client, auth_headers):
    # Mock governance returns success even for nonexistent appeals
    resp = client.post(
        "/api/admin/appeals/nonexistent/resolve",
        headers=auth_headers,
        json={"decision": "accepted", "decision_reason": "Valid grounds with sufficient length."},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["appeal_id"] == "nonexistent"
    assert data["status"] == "accepted"
