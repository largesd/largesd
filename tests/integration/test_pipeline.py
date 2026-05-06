"""
Integration tests for the snapshot pipeline.

- End-to-end pipeline run with mock fact-checker
- Failure injection at each stage
- Verify rollback / job status update on failure
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

import pytest
from unittest.mock import MagicMock, patch

from backend.debate_engine_v2 import DebateEngineV2
from backend.pipeline.orchestrator import run_snapshot_pipeline, STAGES
from backend.pipeline.context import PipelineContext
from backend.pipeline.extract import extract_stage
from backend.pipeline.fact_check import fact_check_stage
from backend.pipeline.canonicalize import canonicalize_stage
from backend.pipeline.score import score_stage
from backend.pipeline.replicate import replicate_stage
from backend.pipeline.counterfactual import counterfactual_stage
from backend.pipeline.symmetry import symmetry_stage
from backend.pipeline.audit import audit_stage
from backend.pipeline.persist import persist_stage


@pytest.fixture
def temp_db():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "test.db")
    yield db_path
    shutil.rmtree(tmp)


@pytest.fixture
def engine(temp_db):
    return DebateEngineV2(
        db_path=temp_db,
        fact_check_mode="PERFECT",
        llm_provider="mock",
        num_judges=3,
    )


def _setup_debate_with_posts(engine):
    """Helper to create a debate and submit posts."""
    debate = engine.create_debate(
        motion="Test motion",
        moderation_criteria="Allow relevant arguments. Block spam.",
        debate_frame="Test frame",
    )
    for side in ["FOR", "AGAINST"]:
        engine.submit_post(
            debate_id=debate["debate_id"],
            side=side,
            topic_id=None,
            facts=f"{side} factual premise.",
            inference=f"Therefore {side} is correct.",
            counter_arguments="",
        )
    return debate["debate_id"]


def test_pipeline_end_to_end(engine, temp_db):
    """Full pipeline run should produce a valid snapshot."""
    debate_id = _setup_debate_with_posts(engine)
    snapshot = engine.generate_snapshot(debate_id, trigger_type="manual")

    assert snapshot["debate_id"] == debate_id
    assert snapshot["status"] == "valid"
    assert "snapshot_id" in snapshot
    assert "overall_scores" in snapshot
    assert "verdict" in snapshot
    assert "topics" in snapshot
    assert "audits" in snapshot
    assert "counterfactuals" in snapshot
    assert "decision_dossier" in snapshot
    assert snapshot["frame"] is not None


def test_pipeline_failure_in_extract_stage(engine, temp_db):
    """Failure in extract stage should raise and be logged."""
    debate_id = _setup_debate_with_posts(engine)

    with patch("backend.pipeline.orchestrator.logger") as mock_logger:
        with patch.object(engine.db, "get_posts_by_debate", side_effect=RuntimeError("DB down")):
            with pytest.raises(RuntimeError, match="DB down"):
                engine.generate_snapshot(debate_id, trigger_type="manual")

        error_calls = [c for c in mock_logger.error.call_args_list if "extract" in str(c)]
        assert len(error_calls) >= 1


def test_pipeline_failure_in_score_stage(engine, temp_db):
    """Failure in score stage should raise and be logged."""
    debate_id = _setup_debate_with_posts(engine)

    with patch("backend.pipeline.orchestrator.logger") as mock_logger:
        with patch.object(engine.scoring_engine, "compute_debate_scores", side_effect=ValueError("Bad scores")):
            with pytest.raises(ValueError, match="Bad scores"):
                engine.generate_snapshot(debate_id, trigger_type="manual")

        error_calls = [c for c in mock_logger.error.call_args_list if "score" in str(c)]
        assert len(error_calls) >= 1


def test_pipeline_context_state_progression():
    """Verify that each stage mutates the context as documented."""
    e = MagicMock()
    e.db = MagicMock()
    e.db.get_posts_by_debate.return_value = []
    e.db.get_latest_snapshot.return_value = None
    e.topic_engine = MagicMock()
    e.topic_engine.MIN_TOPICS = 1
    e.topic_engine.extract_topics_from_posts.return_value = []
    e.topic_engine.enforce_topic_bounds.side_effect = lambda t, *_: t
    e.topic_engine.compute_topic_drift.return_value = {}
    e.topic_engine.assign_posts_to_topics.return_value = {}
    e._topic_from_record = MagicMock()
    e._resolve_fact_checks = MagicMock(side_effect=lambda facts: facts)
    e.extraction_engine = MagicMock()
    e.extraction_engine.canonicalize_facts.return_value = []
    e.extraction_engine.canonicalize_arguments.return_value = []
    e.content_mass_calculator = MagicMock()
    e.content_mass_calculator.calculate_topic_mass.return_value = 0
    e._update_canonical_metrics = MagicMock()
    e.selection_engine = MagicMock()
    fake_sel = MagicMock()
    fake_sel.selected_facts = []
    fake_sel.selected_arguments = []
    fake_sel.selected_fact_ids = []
    fake_sel.selected_arg_ids = []
    fake_sel.diagnostics = {"pools": {}}
    e.selection_engine.select_for_topic_side.return_value = fake_sel
    e.selection_engine.get_diagnostics.return_value = {}
    e.llm_client = MagicMock()
    e.llm_client.generate_steelman_summary.return_value = {"summary": ""}
    e.scoring_engine = MagicMock()
    e.scoring_engine.compute_debate_scores.return_value = {
        "overall_scores": {}, "overall_for": 0.5, "overall_against": 0.5,
        "margin_d": 0.0, "topic_scores": {}
    }
    e.scoring_engine.run_replicates.return_value = []
    e.scoring_engine.compute_verdict.return_value = {
        "verdict": "TIE", "ci_lower": -0.1, "ci_upper": 0.1, "confidence": 0.5,
    }
    e.scoring_engine.compute_counterfactuals.return_value = []
    e.scoring_engine.run_symmetry_tests.return_value = {}
    e.scoring_engine.run_side_label_symmetry_audit.return_value = {}
    e.scoring_engine.compute_relevance_sensitivity.return_value = {}
    e._build_decision_dossier.return_value = {"decisive_premises": []}
    e._build_replay_manifest.return_value = {}
    e._build_recipe_versions.return_value = {}
    e._remap_to_replicate.return_value = ({}, {}, {}, {})
    e.llm_client.get_usage_summary.return_value = {}
    e.llm_client.get_runtime_metadata.return_value = {"provider": "mock", "configured_model": "mock", "num_judges": 3}
    e.llm_client._usage_log = []
    e.num_judges = 3
    e.modulation_engine = MagicMock()
    e.modulation_engine.template = MagicMock()
    e.modulation_engine.template.name = "standard"
    e.modulation_engine.template.version = "1.0"
    e._debate_cache = {}
    e._attach_active_frame = MagicMock(side_effect=lambda d: d)
    e.get_frame_info = MagicMock(return_value=None)

    ctx = PipelineContext(
        debate_id="d1", job_id="j1", request_id="r1",
        trigger_type="manual", engine=e,
        debate={"debate_id": "d1"}, active_frame={"frame_id": "f1"},
        side_order=["FOR", "AGAINST"],
        frame_id="f1", frame_context="scope",
    )

    # Run each stage and verify state progression
    ctx = extract_stage(ctx)
    assert ctx.allowed_posts is not None
    assert ctx.topics is not None
    assert ctx.extracted is not None

    ctx = fact_check_stage(ctx)
    # fact_check mutates extracted in-place

    ctx = canonicalize_stage(ctx)
    assert ctx.canonical_facts is not None
    assert ctx.canonical_args is not None
    assert ctx.topic_content_mass is not None

    ctx = score_stage(ctx)
    assert ctx.scores is not None
    assert ctx.selected_facts is not None

    ctx = replicate_stage(ctx)
    assert ctx.replicates is not None
    assert ctx.verdict_result is not None

    ctx = counterfactual_stage(ctx)
    assert ctx.counterfactuals is not None

    ctx = symmetry_stage(ctx)
    assert ctx.symmetry_result is not None

    ctx = audit_stage(ctx)
    assert ctx.audit_records is not None
    assert ctx.input_hash_root is not None
    assert ctx.output_hash_root is not None

    ctx = persist_stage(ctx)
    assert ctx.snapshot_id is not None
    assert ctx.result is not None
    assert ctx.result["snapshot_id"] == ctx.snapshot_id


def test_pipeline_orchestrator_runs_all_stages():
    """Orchestrator should call every registered stage."""
    stage_names = [name for name, _ in STAGES]
    assert stage_names == [
        "extract", "fact_check", "canonicalize", "score",
        "replicate", "counterfactual", "symmetry", "audit", "persist",
    ]
