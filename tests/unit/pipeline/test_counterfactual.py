"""Unit tests for pipeline counterfactual stage."""

import pytest
from unittest.mock import MagicMock

from backend.pipeline.context import PipelineContext
from backend.pipeline.counterfactual import counterfactual_stage


class FakeTopic:
    def __init__(self):
        self.topic_id = "t1"


@pytest.fixture
def engine():
    e = MagicMock()
    e.scoring_engine = MagicMock()
    e.scoring_engine.compute_counterfactuals.return_value = [{"delta": 0.1}]
    return e


def test_counterfactual_stage(engine):
    ctx = PipelineContext(
        debate_id="d1", job_id="j1", request_id="r1",
        trigger_type="manual", engine=engine,
        topics=[FakeTopic()], side_order=["FOR", "AGAINST"], frame_context="scope",
        canonical_facts={}, canonical_args={}, topic_content_mass={},
    )
    ctx = counterfactual_stage(ctx)
    assert ctx.counterfactuals == [{"delta": 0.1}]
    engine.scoring_engine.compute_counterfactuals.assert_called_once()
