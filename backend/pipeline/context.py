"""
PipelineContext dataclass for passing mutable state between snapshot stages.

Each stage reads from specific fields and writes to specific fields.
Field annotations document the producing stage and consuming stage(s).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    config: Dict[str, Any] = field(default_factory=dict)

    # -- extract stage output --
    debate: Optional[Dict[str, Any]] = None
    active_frame: Optional[Dict[str, Any]] = None
    side_order: Optional[List[str]] = None
    frame_id: Optional[str] = None
    frame_context: Optional[str] = None
    posts: Optional[List[Dict[str, Any]]] = None
    allowed_posts: Optional[List[Dict[str, Any]]] = None
    blocked_posts: Optional[List[Dict[str, Any]]] = None
    block_reasons: Optional[Dict[str, int]] = None
    borderline_rate: Optional[float] = None
    suppression_policy: Optional[Dict[str, Any]] = None
    previous_topics: Optional[List[Any]] = None
    topics: Optional[List[Any]] = None
    drift_report: Optional[Dict[str, Any]] = None
    post_assignments: Optional[Dict[str, List[str]]] = None

    # extracted[topic_id] -> {"topic_posts": [...], "spans": [...],
    #                         "facts": [...], "args": [...]}
    extracted: Optional[Dict[str, Dict[str, Any]]] = None

    # -- fact_check stage output (mutates extracted facts in-place) --
    fact_checks: Optional[List[Dict[str, Any]]] = None

    # -- canonicalize stage output --
    canonical_facts: Optional[Dict[str, List[Dict[str, Any]]]] = None
    canonical_args: Optional[Dict[str, List[Dict[str, Any]]]] = None
    topic_content_mass: Optional[Dict[str, int]] = None

    # -- score stage output --
    selected_facts: Optional[Dict[str, List[Dict[str, Any]]]] = None
    selected_args: Optional[Dict[str, List[Dict[str, Any]]]] = None
    selection_diagnostics: Optional[Dict[str, Any]] = None
    selection_seed: int = 42
    scores: Optional[Dict[str, Any]] = None

    # -- replicate stage output --
    replicates: Optional[List[Any]] = None
    replicate_topics: Optional[List[Any]] = None
    verdict_result: Optional[Dict[str, Any]] = None

    # -- counterfactual stage output --
    counterfactuals: Optional[List[Dict[str, Any]]] = None

    # -- symmetry stage output --
    symmetry_result: Optional[Dict[str, Any]] = None

    # -- audit stage output --
    decision_dossier: Optional[Dict[str, Any]] = None
    audit_records: Optional[Dict[str, Any]] = None
    replay_manifest: Optional[Dict[str, Any]] = None
    recipe_versions: Optional[Dict[str, Any]] = None
    input_hash_root: Optional[str] = None
    output_hash_root: Optional[str] = None
    provider_metadata: Optional[Dict[str, Any]] = None

    # -- persist stage output --
    snapshot_id: Optional[str] = None
    snapshot_data: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
