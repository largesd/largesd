"""
Pipeline stage: extract facts, arguments, and topics from debate posts.
"""

from collections import defaultdict
from typing import Any

from backend.extraction import ExtractedSpan
from backend.lsd_v1_2 import SUPPRESSION_K, build_suppression_policy, compute_borderline_rate
from backend.pipeline.context import PipelineContext


def _make_span(s: dict) -> ExtractedSpan:
    return ExtractedSpan(
        span_id=s["span_id"],
        post_id=s["post_id"],
        start_offset=s["start_offset"],
        end_offset=s["end_offset"],
        span_text=s["span_text"],
        topic_id=s.get("topic_id"),
        side=s["side"],
        span_type=s["span_type"],
    )


def extract_stage(ctx: PipelineContext) -> PipelineContext:
    """
    Extract topics, facts, and arguments from debate posts.

    Outputs (written to ctx):
      posts, allowed_posts, blocked_posts, block_reasons,
      borderline_rate, suppression_policy, previous_topics,
      topics, drift_report, post_assignments, extracted
    """
    engine = ctx.engine
    debate_id = ctx.debate_id
    frame_id = ctx.frame_id
    frame_context = ctx.frame_context

    posts = engine.db.get_posts_by_debate(debate_id, frame_id=frame_id)
    allowed_posts = [p for p in posts if p.get("modulation_outcome") == "allowed"]
    blocked_posts = [p for p in posts if p.get("modulation_outcome") == "blocked"]

    block_reasons: dict[str, int] = defaultdict(int)
    for p in blocked_posts:
        if p.get("block_reason"):
            block_reasons[p["block_reason"]] += 1

    borderline_rate = compute_borderline_rate(posts)
    suppression_policy = build_suppression_policy(posts, dict(block_reasons), k=SUPPRESSION_K)

    previous_topics = []
    previous_snapshot = engine.db.get_latest_snapshot(debate_id, frame_id=frame_id)
    if previous_snapshot:
        prev_topics_data = engine.db.get_topics_by_debate(debate_id, frame_id=frame_id)
        previous_topics = [engine._topic_from_record(t) for t in prev_topics_data]

    topics = engine.topic_engine.extract_topics_from_posts(allowed_posts, frame_context)
    topics = engine.topic_engine.enforce_topic_bounds(topics, allowed_posts, frame_context)
    drift_report = engine.topic_engine.compute_topic_drift(topics, previous_topics)
    post_assignments = engine.topic_engine.assign_posts_to_topics(allowed_posts, topics)

    for topic in topics:
        engine.db.save_topic(
            {
                "topic_id": topic.topic_id,
                "debate_id": debate_id,
                "frame_id": frame_id,
                "name": topic.name,
                "scope": topic.scope,
                "relevance": topic.relevance,
                "drift_score": topic.drift_score,
                "coherence": topic.coherence,
                "distinctness": topic.distinctness,
                "parent_topic_ids": topic.parent_topic_ids,
                "operation": topic.operation,
                "summary_for": topic.summary_for,
                "summary_against": topic.summary_against,
                "created_at": __import__("datetime").datetime.now().isoformat(),
            }
        )

    extracted: dict[str, dict[str, Any]] = {}
    for topic in topics:
        tid = topic.topic_id
        topic_posts = [
            p
            for p in allowed_posts
            if p.get("topic_id") == tid or p["post_id"] in post_assignments.get(tid, [])
        ]
        all_facts, all_args, all_spans = [], [], []

        for post in topic_posts:
            spans = engine.db.get_spans_by_post(post["post_id"])
            all_spans.extend(spans)
            fact_spans = [_make_span(s) for s in spans if s["span_type"] == "fact"]
            inf_spans = [_make_span(s) for s in spans if s["span_type"] == "inference"]
            inference_span = inf_spans[0] if inf_spans else None

            facts = engine.extraction_engine.extract_facts_from_spans(
                fact_spans, tid, post["side"], post_id=post["post_id"]
            )
            all_facts.extend(facts)
            if inference_span:
                all_args.extend(
                    engine.extraction_engine.create_argument_units(
                        fact_spans, inference_span, facts, tid, post["side"]
                    )
                )

        extracted[tid] = {
            "topic": topic,
            "topic_posts": topic_posts,
            "spans": all_spans,
            "facts": all_facts,
            "args": all_args,
        }

    ctx.posts = posts
    ctx.allowed_posts = allowed_posts
    ctx.blocked_posts = blocked_posts
    ctx.block_reasons = dict(block_reasons)
    ctx.borderline_rate = borderline_rate
    ctx.suppression_policy = suppression_policy
    ctx.previous_topics = previous_topics
    ctx.topics = topics
    ctx.drift_report = drift_report
    ctx.post_assignments = post_assignments
    ctx.extracted = extracted
    return ctx
