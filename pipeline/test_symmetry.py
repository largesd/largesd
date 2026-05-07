"""Unit tests for pipeline symmetry stage."""

from unittest.mock import MagicMock

import pytest

from backend.pipeline.context import PipelineContext
from backend.pipeline.symmetry import symmetry_stage


@pytest.fixture
def engine():
    e = MagicMock()
    e.scoring_engine = MagicMock()
    e.scoring_engine.run_symmetry_tests.return_value = {"symmetry_score": 0.95}
    return e


def test_symmetry_stage(engine):
    ctx = PipelineContext(
        debate_id="d1",
        job_id="j1",
        request_id="r1",
        trigger_type="manual",
        engine=engine,
        selected_facts={"t1": []},
        active_frame={"evaluation_criteria": ["fairness"]},
        side_order=["FOR", "AGAINST"],
        frame_context="scope",
    )
    ctx = symmetry_stage(ctx)
    assert ctx.symmetry_result == {"symmetry_score": 0.95}
    engine.scoring_engine.run_symmetry_tests.assert_called_once()
