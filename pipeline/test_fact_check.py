"""Unit tests for pipeline fact_check stage."""

from unittest.mock import MagicMock

import pytest

from backend.extraction import ExtractedFact
from backend.pipeline.context import PipelineContext
from backend.pipeline.fact_check import fact_check_stage


@pytest.fixture
def engine():
    e = MagicMock()
    e._resolve_fact_checks = MagicMock(side_effect=lambda facts: facts)
    return e


def test_fact_check_stage_resolves_facts(engine):
    fact = ExtractedFact(
        fact_id="f1",
        fact_text="ft",
        topic_id="t1",
        side="FOR",
        fact_check_job_id="j1",
        fact_check_status="pending",
    )
    ctx = PipelineContext(
        debate_id="d1",
        job_id="j1",
        request_id="r1",
        trigger_type="manual",
        engine=engine,
        extracted={"t1": {"facts": [fact], "args": []}},
    )
    ctx = fact_check_stage(ctx)
    engine._resolve_fact_checks.assert_called_once_with([fact])
    assert ctx.extracted["t1"]["facts"] == [fact]


def test_fact_check_stage_empty_extracted(engine):
    ctx = PipelineContext(
        debate_id="d1",
        job_id="j1",
        request_id="r1",
        trigger_type="manual",
        engine=engine,
        extracted={},
    )
    ctx = fact_check_stage(ctx)
    engine._resolve_fact_checks.assert_not_called()
