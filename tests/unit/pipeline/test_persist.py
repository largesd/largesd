"""Unit tests for pipeline persist stage."""

import pytest
from unittest.mock import MagicMock

from backend.pipeline.context import PipelineContext
from backend.pipeline.persist import persist_stage


class FakeTopic:
    def __init__(self):
        self.topic_id = "t1"
        self.name = "T"
        self.scope = "S"
        self.relevance = 0.5
        self.drift_score = 0.0
        self.coherence = 0.5
        self.distinctness = 0.5
        self.summary_for = ""
        self.summary_against = ""
        self.operation = "created"
        self.parent_topic_ids = []


@pytest.fixture
def engine():
    e = MagicMock()
    e.db = MagicMock()
    e.modulation_engine = MagicMock()
    e.modulation_engine.template = MagicMock()
    e.modulation_engine.template.name = "standard"
    e.modulation_engine.template.version = "1.0"
    e._debate_cache = {}
    e._attach_active_frame = MagicMock(side_effect=lambda d: d)
    e.get_frame_info = MagicMock(return_value={"frame_id": "f1"})
    return e


def test_persist_stage(engine):
    ctx = PipelineContext(
        debate_id="d1", job_id="j1", request_id="r1",
        trigger_type="manual", engine=engine,
        debate={"debate_id": "d1"}, active_frame={"frame_id": "f1"},
        frame_id="f1", side_order=["FOR", "AGAINST"],
        allowed_posts=[], blocked_posts=[], block_reasons={},
        borderline_rate=0.0, suppression_policy={},
        topics=[FakeTopic()],
        scores={"overall_scores": {}, "overall_for": 0.6, "overall_against": 0.4, "margin_d": 0.2, "topic_scores": {}},
        verdict_result={"verdict": "FOR", "ci_lower": 0.1, "ci_upper": 0.3, "confidence": 0.9},
        audit_records={"extraction_stability": {}},
        replay_manifest={}, recipe_versions={},
        input_hash_root="abc", output_hash_root="def",
        provider_metadata={"provider": "mock"},
        canonical_facts={}, canonical_args={},
        selected_facts={}, selected_args={},
        counterfactuals=[], decision_dossier={},
    )
    ctx = persist_stage(ctx)

    assert ctx.snapshot_id is not None
    assert ctx.snapshot_data is not None
    assert ctx.result is not None
    assert ctx.result["snapshot_id"] == ctx.snapshot_id
    assert ctx.result["frame"] == {"frame_id": "f1"}
    engine.db.save_snapshot.assert_called_once()
    engine.db.save_debate.assert_called_once()
    assert engine.db.save_audit.call_count == 1


def test_persist_stage_saves_multiple_audits(engine):
    ctx = PipelineContext(
        debate_id="d1", job_id="j1", request_id="r1",
        trigger_type="manual", engine=engine,
        debate={"debate_id": "d1"}, active_frame={"frame_id": "f1"},
        frame_id="f1", side_order=["FOR", "AGAINST"],
        allowed_posts=[], blocked_posts=[], block_reasons={},
        borderline_rate=0.0, suppression_policy={},
        topics=[FakeTopic()],
        scores={"overall_scores": {}, "overall_for": 0.6, "overall_against": 0.4, "margin_d": 0.2, "topic_scores": {}},
        verdict_result={"verdict": "FOR", "ci_lower": 0.1, "ci_upper": 0.3, "confidence": 0.9},
        audit_records={"a1": {}, "a2": {}},
        replay_manifest={}, recipe_versions={},
        input_hash_root="abc", output_hash_root="def",
        provider_metadata={"provider": "mock"},
        canonical_facts={}, canonical_args={},
        selected_facts={}, selected_args={},
        counterfactuals=[], decision_dossier={},
    )
    ctx = persist_stage(ctx)
    assert engine.db.save_audit.call_count == 2
