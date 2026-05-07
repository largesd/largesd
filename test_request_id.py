"""Unit tests for request_id tracing across middleware, job queue, engine, and DB."""

import json
import logging
import os
import tempfile
import uuid

import pytest
from flask import Flask

from backend.database import DebateDatabase
from backend.database_v3 import Database
from backend.job_queue import JobQueue
from backend.utils.middleware import setup_middleware


class TestMiddlewareRequestId:
    """Tests that middleware attaches request_id to responses."""

    @pytest.fixture
    def app(self):
        app = Flask(__name__)
        setup_middleware(app)

        @app.route("/api/test")
        def test_route():
            return {"ok": True}

        return app

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    def test_x_request_id_header_on_response(self, client):
        resp = client.get("/api/test")
        assert "X-Request-ID" in resp.headers
        header_rid = resp.headers["X-Request-ID"]
        assert header_rid
        uuid.UUID(header_rid)

    def test_x_request_id_passthrough_from_request(self, client):
        incoming_rid = str(uuid.uuid4())
        resp = client.get(
            "/api/test",
            headers={"X-Request-ID": incoming_rid},
        )
        assert resp.headers["X-Request-ID"] == incoming_rid

    def test_x_request_id_generated_when_missing(self, client):
        resp = client.get("/api/test")
        assert "X-Request-ID" in resp.headers
        rid = resp.headers["X-Request-ID"]
        assert rid
        uuid.UUID(rid)


class TestJobQueueRequestId:
    """Tests that job queue stores and returns request_id."""

    def test_create_job_with_request_id(self):
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "test.db"))
        queue = JobQueue(db)
        rid = str(uuid.uuid4())
        job_id = queue.create_job(
            "snapshot",
            {"debate_id": "d1"},
            runtime_profile_id="runtime-1",
            request_id=rid,
        )
        job = queue.get_job(job_id)
        assert job is not None
        assert job.request_id == rid

    def test_create_job_without_request_id(self):
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "test.db"))
        queue = JobQueue(db)
        job_id = queue.create_job(
            "snapshot",
            {"debate_id": "d1"},
            runtime_profile_id="runtime-1",
        )
        job = queue.get_job(job_id)
        assert job is not None
        assert job.request_id is None

    def test_job_public_dict_includes_request_id(self):
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "test.db"))
        queue = JobQueue(db)
        rid = str(uuid.uuid4())
        job_id = queue.create_job(
            "snapshot",
            {"debate_id": "d1"},
            request_id=rid,
        )
        job = queue.get_job(job_id)
        public = queue.to_public_dict(job)
        assert public["request_id"] == rid

    def test_job_round_trip_request_id(self):
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "test.db"))
        queue = JobQueue(db)
        rid = str(uuid.uuid4())
        job_id = queue.create_job(
            "snapshot",
            {"debate_id": "d1"},
            request_id=rid,
        )
        # Close and reopen queue to force DB reload
        queue2 = JobQueue(db)
        job = queue2.get_job(job_id)
        assert job.request_id == rid


class TestDebateEngineV2RequestId:
    """Tests that generate_snapshot accepts and propagates request_id."""

    def test_generate_snapshot_uses_provided_request_id(self):
        from backend.debate_engine_v2 import DebateEngineV2

        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "test.db")
        engine = DebateEngineV2(
            db_path=db_path,
            llm_provider="mock",
            fact_check_mode="OFFLINE",
        )
        debate = engine.create_debate(
            motion="Test motion",
            moderation_criteria="Test criteria",
            debate_frame="Test frame",
        )
        debate_id = debate["debate_id"]
        rid = str(uuid.uuid4())
        result = engine.generate_snapshot(debate_id, trigger_type="manual", request_id=rid)
        # The snapshot was persisted; verify audit records carry the request_id
        snapshot_id = result["snapshot_id"]
        audits = engine.db.get_audits_by_snapshot(snapshot_id)
        assert len(audits) > 0
        for audit in audits:
            assert audit.get("request_id") == rid

    def test_generate_snapshot_generates_request_id_when_none(self):
        from backend.debate_engine_v2 import DebateEngineV2

        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "test.db")
        engine = DebateEngineV2(
            db_path=db_path,
            llm_provider="mock",
            fact_check_mode="OFFLINE",
        )
        debate = engine.create_debate(
            motion="Test motion",
            moderation_criteria="Test criteria",
            debate_frame="Test frame",
        )
        debate_id = debate["debate_id"]
        result = engine.generate_snapshot(debate_id, trigger_type="manual")
        snapshot_id = result["snapshot_id"]
        audits = engine.db.get_audits_by_snapshot(snapshot_id)
        assert len(audits) > 0
        for audit in audits:
            assert audit.get("request_id")
            uuid.UUID(audit["request_id"])


class TestDatabaseAuditRequestId:
    """Tests that audit records can store request_id."""

    def test_save_audit_with_request_id(self):
        tmp = tempfile.mkdtemp()
        db = DebateDatabase(os.path.join(tmp, "test.db"))
        rid = str(uuid.uuid4())
        db.save_audit(
            {
                "audit_id": "audit_test_1",
                "snapshot_id": "snap_test",
                "audit_type": "test_audit",
                "result_data": {"foo": "bar"},
                "created_at": "2024-01-01T00:00:00",
                "request_id": rid,
            }
        )
        audits = db.get_audits_by_snapshot("snap_test")
        assert len(audits) == 1
        assert audits[0]["request_id"] == rid

    def test_save_audit_without_request_id(self):
        tmp = tempfile.mkdtemp()
        db = DebateDatabase(os.path.join(tmp, "test.db"))
        db.save_audit(
            {
                "audit_id": "audit_test_2",
                "snapshot_id": "snap_test2",
                "audit_type": "test_audit",
                "result_data": {"foo": "bar"},
                "created_at": "2024-01-01T00:00:00",
            }
        )
        audits = db.get_audits_by_snapshot("snap_test2")
        assert len(audits) == 1


class TestJSONFormatterRequestId:
    """Tests that JSONFormatter includes request_id in log output."""

    def test_formatter_includes_request_id(self):
        from backend.utils.logging import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="debate_system",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.request_id = "req-123"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["request_id"] == "req-123"

    def test_formatter_omits_request_id_when_missing(self):
        from backend.utils.logging import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="debate_system",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "request_id" not in parsed
