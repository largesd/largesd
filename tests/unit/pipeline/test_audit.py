"""Unit tests for pipeline audit stage."""

import pytest
from unittest.mock import MagicMock

from backend.pipeline.context import PipelineContext
from backend.pipeline.audit import audit_stage


class FakeTopic:
    def __init__(self):
        self.topic_id = "t1"
        self.name = "T"
        self.scope = "S"
        self.relevance = 0.5
        self.drift_score = 0.0
        self.coherence = 0.5
        self.distinctness = 0.5
        self.parent_topic_ids = []


@pytest.fixture
def engine():
    e = MagicMock()
    e._build_decision_dossier.return_value = {"decisive_premises": []}
    e._build_replay_manifest.return_value = {"manifest": True}
    e._build_recipe_versions.return_value = {"recipe": True}
    e._remap_to_replicate.return_value = ({}, {}, {}, {})

    e.extraction_engine = MagicMock()
    e.extraction_engine.compute_extraction_stability.return_value = {"stable": True}

    e.scoring_engine = MagicMock()
    e.scoring_engine.run_side_label_symmetry_audit.return_value = {"sym": True}
    e.scoring_engine.compute_relevance_sensitivity.return_value = {"rel": True}

    e.llm_client = MagicMock()
    e.llm_client.get_usage_summary.return_value = {"call_count": 5, "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    e.llm_client.get_runtime_metadata.return_value = {"provider": "mock", "configured_model": "mock", "num_judges": 3}
    e.llm_client._usage_log = []

    e.num_judges = 3
    return e


def test_audit_stage(engine):
    ctx = PipelineContext(
        debate_id="d1", job_id="j1", request_id="r1",
        trigger_type="manual", engine=engine,
        topics=[FakeTopic()], side_order=["FOR", "AGAINST"], frame_context="scope",
        allowed_posts=[], blocked_posts=[], posts=[], drift_report={},
        canonical_facts={"t1": []}, canonical_args={"t1": []},
        selected_facts={"t1": []}, selected_args={"t1": []},
        topic_content_mass={"t1": 10},
        scores={"topic_scores": {}, "overall_scores": {}, "margin_d": 0.2},
        counterfactuals=[], symmetry_result={"sym": True},
        verdict_result={"verdict": "FOR", "ci_lower": 0.1, "ci_upper": 0.3, "confidence": 0.9},
        replicates=[], replicate_topics=[], selection_diagnostics={},
        selection_seed=42,
    )
    ctx = audit_stage(ctx)

    assert ctx.decision_dossier is not None
    assert ctx.audit_records is not None
    assert "extraction_stability" in ctx.audit_records
    assert ctx.input_hash_root is not None
    assert ctx.output_hash_root is not None
    assert ctx.provider_metadata is not None
    assert ctx.replay_manifest is not None
    assert ctx.recipe_versions is not None
    assert len(ctx.input_hash_root) == 64  # SHA-256 hex
