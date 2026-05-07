"""API integration tests for debate proposal endpoints."""


def test_submit_proposal_success(client, auth_headers):
    resp = client.post(
        "/api/debate-proposals",
        headers=auth_headers,
        json={
            "motion": "Should cities ban private cars downtown?",
            "moderation_criteria": "Allow evidence-based arguments.",
            "debate_frame": "Judge which side best balances access and emissions.",
            "frame_sides": "FOR | Supports the ban.\nAGAINST | Opposes the ban.",
            "frame_evaluation_criteria": "Logical coherence\nFeasibility",
            "frame_definitions": "Downtown: city center",
            "frame_scope_constraints": "Focus on next 10 years",
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "pending"
    assert "proposal_id" in data


def test_get_my_proposals(client, auth_headers):
    resp = client.get("/api/debate-proposals/mine", headers=auth_headers)
    assert resp.status_code == 200
    assert "proposals" in resp.get_json()


def test_list_proposal_queue_admin(client, auth_headers):
    resp = client.get("/api/admin/debate-proposals", headers=auth_headers)
    assert resp.status_code == 200
    assert "proposals" in resp.get_json()


def test_list_proposal_queue_non_admin(client, regular_auth_headers):
    resp = client.get("/api/admin/debate-proposals", headers=regular_auth_headers)
    assert resp.status_code == 403


def test_accept_proposal_not_found(client, auth_headers):
    resp = client.post("/api/admin/debate-proposals/nonexistent/accept", headers=auth_headers)
    assert resp.status_code == 404


def test_reject_proposal_not_found(client, auth_headers):
    resp = client.post("/api/admin/debate-proposals/nonexistent/reject", headers=auth_headers)
    assert resp.status_code == 404
