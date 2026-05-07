"""API integration tests for dossier endpoints."""

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


def test_get_verdict_no_snapshot(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.get("/api/debate/verdict", headers=auth_headers)
    assert resp.status_code == 404
    assert "No snapshot available" in resp.get_json()["error"]


def test_get_audits_no_snapshot(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.get("/api/debate/audits", headers=auth_headers)
    assert resp.status_code == 404
    assert "No snapshot available" in resp.get_json()["error"]


def test_get_decision_dossier_no_snapshot(client, auth_headers, created_debate):
    client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
    resp = client.get("/api/debate/decision-dossier", headers=auth_headers)
    assert resp.status_code == 404
    assert "No snapshot available" in resp.get_json()["error"]
