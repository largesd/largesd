"""Unit tests for pipeline canonicalize stage."""

from unittest.mock import MagicMock

import pytest

from backend.extraction import CanonicalArgument, CanonicalFact
from backend.pipeline.canonicalize import canonicalize_stage
from backend.pipeline.context import PipelineContext


class FakeTopic:
    def __init__(self):
        self.topic_id = "t1"
        self.scope = "scope"


@pytest.fixture
def engine():
    e = MagicMock()
    e.db = MagicMock()
    e.extraction_engine = MagicMock()
    cf = CanonicalFact(
        canon_fact_id="cf1",
        topic_id="t1",
        side="FOR",
        canon_fact_text="fact",
        member_fact_ids=["f1"],
        provenance_spans=[],
        p_true=0.8,
    )
    ca = CanonicalArgument(
        canon_arg_id="ca1",
        topic_id="t1",
        side="FOR",
        inference_text="inf",
        supporting_facts=["cf1"],
        member_au_ids=["au1"],
        provenance_spans=[],
    )
    e.extraction_engine.canonicalize_facts.return_value = [cf]
    e.extraction_engine.canonicalize_arguments.return_value = [ca]
    e.content_mass_calculator = MagicMock()
    e.content_mass_calculator.calculate_topic_mass.return_value = 42
    return e


def test_canonicalize_stage(engine):
    ctx = PipelineContext(
        debate_id="d1",
        job_id="j1",
        request_id="r1",
        trigger_type="manual",
        engine=engine,
        extracted={
            "t1": {"topic": FakeTopic(), "topic_posts": [], "spans": [], "facts": [], "args": []}
        },
    )
    ctx = canonicalize_stage(ctx)

    assert ctx.canonical_facts is not None
    assert "t1" in ctx.canonical_facts
    assert len(ctx.canonical_facts["t1"]) == 1
    assert ctx.canonical_args is not None
    assert len(ctx.canonical_args["t1"]) == 1
    assert ctx.topic_content_mass == {"t1": 42}
    engine.db.save_canonical_fact.assert_called_once()
    engine.db.save_canonical_argument.assert_called_once()


def test_canonicalize_stage_empty(engine):
    e = MagicMock()
    e.db = MagicMock()
    e.extraction_engine = MagicMock()
    e.extraction_engine.canonicalize_facts.return_value = []
    e.extraction_engine.canonicalize_arguments.return_value = []
    e.content_mass_calculator = MagicMock()
    e.content_mass_calculator.calculate_topic_mass.return_value = 0

    ctx = PipelineContext(
        debate_id="d1",
        job_id="j1",
        request_id="r1",
        trigger_type="manual",
        engine=e,
        extracted={
            "t1": {"topic": FakeTopic(), "topic_posts": [], "spans": [], "facts": [], "args": []}
        },
    )
    ctx = canonicalize_stage(ctx)
    assert ctx.canonical_facts["t1"] == []
    assert ctx.canonical_args["t1"] == []
