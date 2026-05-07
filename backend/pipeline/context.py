"""
PipelineContext dataclass for passing mutable state between snapshot stages.

Each stage reads from specific fields and writes to specific fields.
Field annotations document the producing stage and consuming stage(s).
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineContext:
    """
    Mutable context passed through all snapshot pipeline stages.

    Stage I/O contract:
      extract       → writes: debate, active_frame, side_order, frame_id,
                              frame_context, posts, allowed_posts, blocked_posts,
                              block_reasons, borderline_rate, suppression_policy,
                              topics, drift_report, post_assignments, extracted
      fact_check    → reads: extracted; writes: extracted (facts resolved)
      canonicalize  → reads: extracted; writes: canonical_facts, canonical_args,
                              topic_content_mass
      score         → reads: canonical_facts, canonical_args, topic_content_mass,
                              topics, side_order, frame_context;
                      writes: selected_facts, selected_args, selection_diagnostics,
                              scores
      replicate     → reads: selected_facts, selected_args, topic_content_mass,
                              topics, side_order, frame_context, scores;
                      writes: replicates, replicate_topics, verdict_result
      counterfactual→ reads: topics, canonical_facts, canonical_args,
                              topic_content_mass, side_order, frame_context;
                      writes: counterfactuals
      symmetry      → reads: selected_facts, frame_values, side_order, frame_context;
                      writes: symmetry_result
      audit         → reads: nearly everything; writes: decision_dossier,
                              audit_records, replay_manifest, recipe_versions,
                              input_hash_root, output_hash_root, provider_metadata
      persist       → reads: everything; writes: snapshot_id, snapshot_data, result
    """

    # -- Immutable pipeline identifiers (set by caller) --
    debate_id: str
    job_id: str
    request_id: str
    trigger_type: str
    engine: Any  # DebateEngineV2 instance
    config: dict[str, Any] = field(default_factory=dict)

    # -- extract stage output --
    debate: dict[str, Any] | None = None
    active_frame: dict[str, Any] | None = None
    side_order: list[str] | None = None
    frame_id: str | None = None
    frame_context: str | None = None
    posts: list[dict[str, Any]] | None = None
    allowed_posts: list[dict[str, Any]] | None = None
    blocked_posts: list[dict[str, Any]] | None = None
    block_reasons: dict[str, int] | None = None
    borderline_rate: float | None = None
    suppression_policy: dict[str, Any] | None = None
    previous_topics: list[Any] | None = None
    topics: list[Any] | None = None
    drift_report: dict[str, Any] | None = None
    post_assignments: dict[str, list[str]] | None = None

    # extracted[topic_id] -> {"topic_posts": [...], "spans": [...],
    #                         "facts": [...], "args": [...]}
    extracted: dict[str, dict[str, Any]] | None = None

    # -- fact_check stage output (mutates extracted facts in-place) --
    fact_checks: list[dict[str, Any]] | None = None

    # -- canonicalize stage output --
    canonical_facts: dict[str, list[dict[str, Any]]] | None = None
    canonical_args: dict[str, list[dict[str, Any]]] | None = None
    topic_content_mass: dict[str, int] | None = None

    # -- score stage output --
    selected_facts: dict[str, list[dict[str, Any]]] | None = None
    selected_args: dict[str, list[dict[str, Any]]] | None = None
    selection_diagnostics: dict[str, Any] | None = None
    selection_seed: int = 42
    scores: dict[str, Any] | None = None

    # -- replicate stage output --
    replicates: list[Any] | None = None
    replicate_topics: list[Any] | None = None
    verdict_result: dict[str, Any] | None = None

    # -- counterfactual stage output --
    counterfactuals: list[dict[str, Any]] | None = None

    # -- symmetry stage output --
    symmetry_result: dict[str, Any] | None = None

    # -- audit stage output --
    decision_dossier: dict[str, Any] | None = None
    audit_records: dict[str, Any] | None = None
    replay_manifest: dict[str, Any] | None = None
    recipe_versions: dict[str, Any] | None = None
    input_hash_root: str | None = None
    output_hash_root: str | None = None
    provider_metadata: dict[str, Any] | None = None

    # -- persist stage output --
    snapshot_id: str | None = None
    snapshot_data: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
