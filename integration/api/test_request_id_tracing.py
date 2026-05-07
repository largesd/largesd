"""Integration tests for request_id tracing across API → Engine → DB → Job Queue."""

import uuid

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


class TestRequestIdTracing:
    """End-to-end tests that verify request_id propagation."""

    def test_api_response_includes_x_request_id(self, client):
        resp = client.get("/api/debates")
        assert resp.status_code == 200
        assert "X-Request-ID" in resp.headers
        rid = resp.headers["X-Request-ID"]
        assert rid
        uuid.UUID(rid)

    def test_x_request_id_passed_through(self, client):
        incoming_rid = str(uuid.uuid4())
        resp = client.get(
            "/api/debates",
            headers={"X-Request-ID": incoming_rid},
        )
        assert resp.headers["X-Request-ID"] == incoming_rid

    def test_snapshot_job_includes_request_id(self, client, auth_headers, created_debate):
        client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
        incoming_rid = str(uuid.uuid4())
        resp = client.post(
            "/api/debate/snapshot",
            headers={**auth_headers, "X-Request-ID": incoming_rid},
            json={"trigger_type": "manual"},
        )
        assert resp.status_code == 202
        data = resp.get_json()
        assert "job_id" in data

        # Poll job endpoint and verify request_id is present
        job_resp = client.get(
            f"/api/debate/snapshot-jobs/{data['job_id']}",
            headers=auth_headers,
        )
        assert job_resp.status_code == 200
        job_data = job_resp.get_json()
        assert job_data["request_id"] == incoming_rid

    def test_logs_share_request_id_for_snapshot_request(
        self, client, auth_headers, created_debate, caplog
    ):
        import logging

        from backend.app_v3 import app_logger

        # Ensure our logger captures INFO by attaching caplog's handler
        original_level = app_logger.level
        app_logger.setLevel(logging.INFO)
        app_logger.addHandler(caplog.handler)

        client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
        incoming_rid = str(uuid.uuid4())

        resp = client.post(
            "/api/debate/snapshot",
            headers={**auth_headers, "X-Request-ID": incoming_rid},
            json={"trigger_type": "manual"},
        )
        assert resp.status_code == 202

        app_logger.removeHandler(caplog.handler)
        app_logger.setLevel(original_level)

        # Find log records that mention our request_id
        rid_records = [r for r in caplog.records if getattr(r, "request_id", None) == incoming_rid]
        # At minimum the HTTP request log should have it
        assert len(rid_records) >= 1
        http_record = [r for r in rid_records if getattr(r, "event_type", None) == "http_request"]
        assert len(http_record) >= 1

    def test_audit_records_store_request_id(self, client, auth_headers, created_debate):
        from backend import extensions

        client.post(f"/api/debate/{created_debate}/activate", headers=auth_headers)
        incoming_rid = str(uuid.uuid4())

        # Directly call generate_snapshot to ensure synchronous path
        result = extensions.debate_engine.generate_snapshot(
            created_debate,
            trigger_type="manual",
            request_id=incoming_rid,
        )
        snapshot_id = result["snapshot_id"]

        audits = extensions.db.get_audits_by_snapshot(snapshot_id)
        assert len(audits) > 0
        for audit in audits:
            assert audit.get("request_id") == incoming_rid
