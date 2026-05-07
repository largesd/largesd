"""Unit tests for pipeline extract stage."""

from unittest.mock import MagicMock

import pytest

from backend.extraction import ExtractedFact
from backend.pipeline.context import PipelineContext
from backend.pipeline.extract import extract_stage


class FakeTopic:
    def __init__(self, topic_id, name="T", scope="S"):
        self.topic_id = topic_id
        self.name = name
        self.scope = scope
        self.relevance = 0.5
        self.drift_score = 0.0
        self.coherence = 0.5
        self.distinctness = 0.5
        self.parent_topic_ids = []
        self.operation = "created"
        self.summary_for = ""
        self.summary_against = ""


@pytest.fixture
def engine():
    e = MagicMock()
    e.db = MagicMock()
    e.db.get_posts_by_debate.return_value = [
        {
            "post_id": "p1",
            "modulation_outcome": "allowed",
            "side": "FOR",
            "facts": "f",
            "inference": "i",
        },
        {
            "post_id": "p2",
            "modulation_outcome": "blocked",
            "side": "AGAINST",
            "block_reason": "spam",
            "facts": "f",
            "inference": "i",
        },
    ]
    e.db.get_latest_snapshot.return_value = None
    e.db.get_spans_by_post.return_value = [
        {
            "span_id": "s1",
            "post_id": "p1",
            "start_offset": 0,
            "end_offset": 2,
            "span_text": "ab",
            "topic_id": "t1",
            "side": "FOR",
            "span_type": "fact",
        },
        {
            "span_id": "s2",
            "post_id": "p1",
            "start_offset": 3,
            "end_offset": 5,
            "span_text": "cd",
            "topic_id": "t1",
            "side": "FOR",
            "span_type": "inference",
        },
    ]

    e.topic_engine = MagicMock()
    e.topic_engine.extract_topics_from_posts.return_value = [FakeTopic("t1")]
    e.topic_engine.enforce_topic_bounds.side_effect = lambda topics, *_: topics
    e.topic_engine.compute_topic_drift.return_value = {"drift": 0}
    e.topic_engine.assign_posts_to_topics.return_value = {"t1": ["p1"]}

    e.extraction_engine = MagicMock()
    e.extraction_engine.extract_facts_from_spans.return_value = [
        ExtractedFact(fact_id="f1", fact_text="ft", topic_id="t1", side="FOR")
    ]
    e.extraction_engine.create_argument_units.return_value = []

    e._topic_from_record = MagicMock()
    return e


def test_extract_stage_populates_ctx(engine):
    ctx = PipelineContext(
        debate_id="d1",
        job_id="j1",
        request_id="r1",
        trigger_type="manual",
        engine=engine,
        frame_id="f1",
        frame_context="scope",
    )
    ctx = extract_stage(ctx)

    assert ctx.allowed_posts is not None
    assert len(ctx.allowed_posts) == 1
    assert ctx.blocked_posts is not None
    assert len(ctx.blocked_posts) == 1
    assert ctx.block_reasons == {"spam": 1}
    assert ctx.topics is not None
    assert len(ctx.topics) == 1
    assert ctx.extracted is not None
    assert "t1" in ctx.extracted
    assert len(ctx.extracted["t1"]["facts"]) == 1
    engine.db.save_topic.assert_called_once()


def test_extract_stage_no_posts(engine):
    engine.db.get_posts_by_debate.return_value = []
    engine.topic_engine.extract_topics_from_posts.return_value = []
    ctx = PipelineContext(
        debate_id="d1",
        job_id="j1",
        request_id="r1",
        trigger_type="manual",
        engine=engine,
        frame_id="f1",
        frame_context="scope",
    )
    ctx = extract_stage(ctx)
    assert ctx.allowed_posts == []
    assert ctx.extracted == {}
