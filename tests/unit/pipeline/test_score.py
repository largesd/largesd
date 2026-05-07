"""Unit tests for pipeline score stage."""

from unittest.mock import MagicMock

import pytest

from backend.pipeline.context import PipelineContext
from backend.pipeline.score import score_stage


class FakeTopic:
    def __init__(self):
        self.topic_id = "t1"
        self.name = "Topic"
        self.scope = "scope"
        self.relevance = 0.5
        self.drift_score = 0.0
        self.coherence = 0.5
        self.distinctness = 0.5
        self.summary_for = ""
        self.summary_against = ""


class FakeSelectedSet:
    def __init__(self):
        self.selected_facts = []
        self.selected_arguments = []
        self.selected_fact_ids = []
        self.selected_arg_ids = []
        self.diagnostics = {"pools": {}}


@pytest.fixture
def engine():
    e = MagicMock()
    e._update_canonical_metrics = MagicMock()
    e.selection_engine = MagicMock()
    e.selection_engine.select_for_topic_side.return_value = FakeSelectedSet()
    e.selection_engine.get_diagnostics.return_value = {}
    e.llm_client = MagicMock()
    e.llm_client.generate_steelman_summary.return_value = {"summary": "s"}
    e.scoring_engine = MagicMock()
    e.scoring_engine.compute_debate_scores.return_value = {
        "overall_scores": {},
        "overall_for": 0.6,
        "overall_against": 0.4,
        "margin_d": 0.2,
        "topic_scores": {},
    }
    return e


def test_score_stage(engine):
    ctx = PipelineContext(
        debate_id="d1",
        job_id="j1",
        request_id="r1",
        trigger_type="manual",
        engine=engine,
        topics=[FakeTopic()],
        side_order=["FOR", "AGAINST"],
        frame_context="scope",
        canonical_facts={"t1": [{"canon_fact_id": "cf1", "side": "FOR", "fact_type": "empirical"}]},
        canonical_args={"t1": [{"canon_arg_id": "ca1", "side": "FOR"}]},
        topic_content_mass={"t1": 10},
    )
    ctx = score_stage(ctx)

    engine._update_canonical_metrics.assert_called_once()
    engine.scoring_engine.compute_debate_scores.assert_called_once()
    assert ctx.scores is not None
    assert ctx.selected_facts is not None
    assert ctx.selection_diagnostics is not None


def test_score_stage_no_topics(engine):
    ctx = PipelineContext(
        debate_id="d1",
        job_id="j1",
        request_id="r1",
        trigger_type="manual",
        engine=engine,
        topics=[],
        side_order=["FOR", "AGAINST"],
        frame_context="scope",
        canonical_facts={},
        canonical_args={},
        topic_content_mass={},
    )
    ctx = score_stage(ctx)
    engine._update_canonical_metrics.assert_called_once()
    assert ctx.scores is not None
