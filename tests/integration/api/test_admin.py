"""API integration tests for admin-only endpoints."""
import pytest


# ---------------------------------------------------------------------------
# Moderation template
# ---------------------------------------------------------------------------
def test_get_moderation_template_current_success(client, auth_headers):
    resp = client.get("/api/admin/moderation-template/current", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "template" in data
    assert "moderation_outcomes" in data


def test_get_moderation_template_current_non_admin(client, regular_auth_headers):
    resp = client.get("/api/admin/moderation-template/current", headers=regular_auth_headers)
    assert resp.status_code == 403


def test_get_moderation_template_history_success(client, auth_headers):
    resp = client.get("/api/admin/moderation-template/history", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "history" in data
    assert "count" in data


def test_save_moderation_template_draft(client, auth_headers):
    resp = client.post(
        "/api/admin/moderation-template/draft",
        headers=auth_headers,
        json={
            "base_template_id": "standard",
            "template_name": "Test Draft",
            "version": "1.0.0",
            "topic_requirements": {"enforce_scope": True},
        },
    )
    assert resp.status_code == 201
    assert resp.get_json()["message"] == "Draft template saved"


def test_apply_moderation_template(client, auth_headers):
    resp = client.post(
        "/api/admin/moderation-template/apply",
        headers=auth_headers,
        json={
            "base_template_id": "standard",
            "template_name": "Test Active",
            "version": "1.0.0",
            "topic_requirements": {"enforce_scope": True},
        },
    )
    assert resp.status_code == 200
    assert "Template applied and set active" in resp.get_json()["message"]


# ---------------------------------------------------------------------------
# Snapshot admin
# ---------------------------------------------------------------------------
def test_verify_snapshot_not_found(client, auth_headers):
    resp = client.post("/api/admin/snapshots/nonexistent/verify", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("verified") is False
    assert "error" in data


def test_enqueue_verify_job_not_found(client, auth_headers):
    resp = client.post("/api/admin/snapshots/nonexistent/verify-job", headers=auth_headers)
    assert resp.status_code == 202
    assert "job_id" in resp.get_json()


def test_mark_snapshot_incident_not_found(client, auth_headers):
    resp = client.post(
        "/api/admin/snapshots/nonexistent/mark-incident",
        headers=auth_headers,
        json={"description": "Incident description here.", "severity": "medium"},
    )
    assert resp.status_code == 404


def test_mark_snapshot_incident_not_found(client, auth_headers):
    resp = client.post(
        "/api/admin/snapshots/nonexistent/mark-incident",
        headers=auth_headers,
        json={"description": "Incident description here.", "severity": "medium"},
    )
    assert resp.status_code == 404
    assert "Snapshot not found" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# Audit export
# ---------------------------------------------------------------------------
def test_export_audit_bundle_not_found(client, auth_headers):
    resp = client.get("/api/audit/export/nonexistent", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Admin proposal routes
# ---------------------------------------------------------------------------
def test_list_proposal_queue_success(client, auth_headers):
    resp = client.get("/api/admin/debate-proposals", headers=auth_headers)
    assert resp.status_code == 200
    assert "proposals" in resp.get_json()


def test_list_proposal_queue_non_admin(client, regular_auth_headers):
    resp = client.get("/api/admin/debate-proposals", headers=regular_auth_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin frame petitions
# ---------------------------------------------------------------------------
def test_accept_frame_petition_not_found(client, auth_headers):
    resp = client.post("/api/admin/frame-petitions/nonexistent/accept", headers=auth_headers)
    assert resp.status_code == 404


def test_reject_frame_petition_not_found(client, auth_headers):
    resp = client.post("/api/admin/frame-petitions/nonexistent/reject", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Judge pool composition (admin)
# ---------------------------------------------------------------------------
def test_record_judge_pool_composition_admin(client, auth_headers):
    resp = client.post(
        "/api/governance/judge-pool/composition",
        headers=auth_headers,
        json={"category": "general", "count": 5},
    )
    assert resp.status_code == 201
    assert "composition_id" in resp.get_json()


def test_record_judge_pool_composition_non_admin(client, regular_auth_headers):
    resp = client.post(
        "/api/governance/judge-pool/composition",
        headers=regular_auth_headers,
        json={"category": "general", "count": 5},
    )
    assert resp.status_code == 403
