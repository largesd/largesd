"""Unit tests for pipeline replicate stage."""

from unittest.mock import MagicMock

import pytest

from backend.pipeline.context import PipelineContext
from backend.pipeline.replicate import replicate_stage
from backend.scoring_engine import ReplicateResult


class FakeTopic:
    def __init__(self):
        self.topic_id = "t1"
        self.scope = "scope"


@pytest.fixture
def engine():
    e = MagicMock()
    e.topic_engine = MagicMock()
    e.topic_engine.MIN_TOPICS = 1
    e.topic_engine.merge_variant_replicate.return_value = []
    e.scoring_engine = MagicMock()
    e.scoring_engine.run_replicates.return_value = [
        ReplicateResult(
            overall_for=0.6,
            overall_against=0.4,
            margin_d=0.2,
            topic_scores={},
            overall_scores={},
            side_order=["FOR", "AGAINST"],
            metadata={},
        )
    ]
    e.scoring_engine.compute_debate_scores.return_value = {
        "overall_for": 0.6,
        "overall_against": 0.4,
        "margin_d": 0.2,
        "topic_scores": {},
        "overall_scores": {},
    }
    e.scoring_engine.compute_verdict.return_value = {
        "verdict": "FOR",
        "ci_lower": 0.1,
        "ci_upper": 0.3,
        "confidence": 0.9,
    }
    e._remap_to_replicate.return_value = ({}, {}, {}, {})
    return e


def test_replicate_stage(engine):
    ctx = PipelineContext(
        debate_id="d1",
        job_id="j1",
        request_id="r1",
        trigger_type="manual",
        engine=engine,
        topics=[FakeTopic()],
        side_order=["FOR", "AGAINST"],
        frame_context="scope",
        selected_facts={"t1": []},
        selected_args={"t1": []},
        topic_content_mass={"t1": 10},
        scores={
            "overall_for": 0.6,
            "overall_against": 0.4,
            "margin_d": 0.2,
            "topic_scores": {},
            "overall_scores": {},
        },
    )
    ctx = replicate_stage(ctx)

    assert ctx.replicates is not None
    assert len(ctx.replicates) == 2  # bootstrap + merge_variant
    assert ctx.verdict_result is not None
    assert ctx.verdict_result["verdict"] == "FOR"
    assert "replicate_composition" in ctx.verdict_result
