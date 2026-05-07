"""
Data models for the LSD Fact-Checking System v1.5 (Phase 1).

Implements all schemas, types, enums, and validation rules from 01_DATA_MODELS.md.
Kept in a separate module to avoid shadowing legacy v1 models in models.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class NodeType(Enum):
    ATOMIC = "ATOMIC"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    IF_THEN = "IF_THEN"
    COMPARISON = "COMPARISON"
    QUANTIFIER = "QUANTIFIER"


class ValueType(Enum):
    NUMBER = "NUMBER"
    DATE = "DATE"
    BOOLEAN = "BOOLEAN"
    CATEGORY = "CATEGORY"
    TEXT = "TEXT"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"


class SourceType(Enum):
    OFFICIAL_STAT = "OFFICIAL_STAT"
    GOV_DB = "GOV_DB"
    SCIENTIFIC_DB = "SCIENTIFIC_DB"
    LEGAL_DB = "LEGAL_DB"
    WIKIDATA = "WIKIDATA"
    WIKIPEDIA = "WIKIPEDIA"
    NEWS = "NEWS"
    WEB = "WEB"
    OTHER = "OTHER"


class RetrievalPath(Enum):
    DIRECT_CONNECTOR = "DIRECT_CONNECTOR"
    WIKIDATA_REFERENCE = "WIKIDATA_REFERENCE"
    RAG_RETRIEVAL = "RAG_RETRIEVAL"
    LIVE_SEARCH_DISCOVERY = "LIVE_SEARCH_DISCOVERY"
    MANUAL_UPLOAD = "MANUAL_UPLOAD"
    OFFLINE_PLACEHOLDER = "OFFLINE_PLACEHOLDER"


class Direction(Enum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    UNCLEAR = "UNCLEAR"
    NEUTRAL = "NEUTRAL"


class DirectionMethod(Enum):
    DETERMINISTIC_STRUCTURED = "DETERMINISTIC_STRUCTURED"
    LLM_CLASSIFIER = "LLM_CLASSIFIER"
    MANUAL = "MANUAL"


class DeterministicComparisonResult(Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_COMPARABLE = "NOT_COMPARABLE"
    NOT_RUN = "NOT_RUN"


class HumanReviewFlag(Enum):
    NONE = "NONE"
    ENTITY_AMBIGUITY = "ENTITY_AMBIGUITY"
    POLICY_GAP = "POLICY_GAP"
    CONTRADICTORY_TIER1_EVIDENCE = "CONTRADICTORY_TIER1_EVIDENCE"
    HIGH_IMPACT_INSUFFICIENT = "HIGH_IMPACT_INSUFFICIENT"
    HIGH_IMPACT_LLM_DIRECTION = "HIGH_IMPACT_LLM_DIRECTION"
    CAUSAL_COMPLEXITY = "CAUSAL_COMPLEXITY"
    SCIENTIFIC_SCOPE_OVERCLAIM = "SCIENTIFIC_SCOPE_OVERCLAIM"
    LLM_VALIDATION_FAILURE = "LLM_VALIDATION_FAILURE"
    CONNECTOR_FAILURE = "CONNECTOR_FAILURE"
    TEMPORAL_SCOPE_AMBIGUITY = "TEMPORAL_SCOPE_AMBIGUITY"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"


class ReviewOutcome(Enum):
    REVIEWED_NO_CHANGE = "REVIEWED_NO_CHANGE"
    REVIEWED_CORRECTION = "REVIEWED_CORRECTION"
    REVIEWED_POLICY_GAP = "REVIEWED_POLICY_GAP"
    REVIEWED_SOURCE_DISPUTE = "REVIEWED_SOURCE_DISPUTE"


class ClaimType(Enum):
    NUMERIC_STATISTICAL = "NUMERIC_STATISTICAL"
    LEGAL_REGULATORY = "LEGAL_REGULATORY"
    SCIENTIFIC = "SCIENTIFIC"
    GEOGRAPHIC_DEMOGRAPHIC = "GEOGRAPHIC_DEMOGRAPHIC"
    CURRENT_EVENT = "CURRENT_EVENT"
    CAUSAL = "CAUSAL"
    EMPIRICAL_ATOMIC = "EMPIRICAL_ATOMIC"


class FactMode(Enum):
    OFFLINE = "OFFLINE"
    ONLINE_ALLOWLIST = "ONLINE_ALLOWLIST"
    PERFECT_CHECKER = "PERFECT_CHECKER"
    LIVE_CONNECTORS = "LIVE_CONNECTORS"


class Side(Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ProvenanceSpan:
    span_id: str
    post_id: str
    offsets: dict[str, int] = field(default_factory=dict)
    span_text: str = ""


@dataclass
class VerdictScope:
    temporal_scope: str | None = None
    geographic_scope: str | None = None
    population_scope: str | None = None
    measurement_definition: str | None = None
    source_basis: str | None = None
    rounding_tolerance: str | None = None


@dataclass
class ResolvedValue:
    value: Any = None
    unit: str | None = None
    value_type: ValueType = ValueType.UNKNOWN
    lower_bound: float | None = None
    upper_bound: float | None = None
    measurement_definition: str | None = None
    source_basis: str | None = None
    verdict_scope: VerdictScope = field(default_factory=VerdictScope)
    rounding_tolerance: str | None = None


@dataclass
class ClaimExpression:
    node_type: NodeType
    children: list[ClaimExpression] = field(default_factory=list)
    subclaim_id: str | None = None
    operator: str | None = None
    quantifier: str | None = None
    quantifier_parameter: Any = None
    comparison_target: str | None = None

    def __post_init__(self):
        # Basic structural validation
        if self.node_type == NodeType.ATOMIC:
            if not self.subclaim_id:
                raise ValueError("ATOMIC node must have subclaim_id")
            if self.children:
                raise ValueError("ATOMIC node must have no children")
        elif self.node_type in (NodeType.AND, NodeType.OR):
            if len(self.children) < 2:
                raise ValueError(f"{self.node_type.value} must have at least two children")
        elif self.node_type == NodeType.NOT:
            if len(self.children) != 1:
                raise ValueError("NOT must have exactly one child")
        elif self.node_type == NodeType.IF_THEN:
            if len(self.children) != 2:
                raise ValueError("IF_THEN must have exactly two children")
        elif self.node_type == NodeType.COMPARISON:
            if not self.operator:
                raise ValueError("COMPARISON must define operator")
        elif self.node_type == NodeType.QUANTIFIER:
            if not self.quantifier:
                raise ValueError("QUANTIFIER must define quantifier")


@dataclass
class AtomicSubclaim:
    subclaim_id: str
    parent_premise_id: str
    text: str
    claim_type: ClaimType
    secondary_claim_types: list[ClaimType] = field(default_factory=list)
    operationalization_hint: str = ""
    verdict_scope_hint: VerdictScope = field(default_factory=VerdictScope)
    provenance_spans: list[ProvenanceSpan] = field(default_factory=list)
    decomposition_rationale: str = ""


@dataclass
class ValidationResult:
    valid: bool = True
    errors: list[str] = field(default_factory=list)


@dataclass
class PremiseDecomposition:
    premise_id: str
    snapshot_id: str
    original_text: str
    topic_id: str
    side: Side
    root_claim_expression: ClaimExpression
    atomic_subclaims: list[AtomicSubclaim] = field(default_factory=list)
    provenance_spans: list[ProvenanceSpan] = field(default_factory=list)
    decomposition_model_metadata: dict[str, Any] = field(default_factory=dict)
    decomposition_prompt_hash: str = ""
    validation_result: ValidationResult = field(default_factory=ValidationResult)


@dataclass
class EvidencePolicy:
    policy_id: str
    claim_type: ClaimType
    required_source_types: list[SourceType] = field(default_factory=list)
    preferred_source_types: list[SourceType] = field(default_factory=list)
    minimum_acceptable_tier: int = 3  # Tier N or stronger. 1 and 2 both satisfy 2.
    cross_verification_required: bool = False
    cross_verification_minimum_sources: int = 1
    temporal_constraint: dict[str, Any] | None = None
    verdict_scope_requirements: list[str] = field(default_factory=list)
    frame_dependent: bool = False
    special_rules: list[str] = field(default_factory=list)


@dataclass
class EvidenceItem:
    evidence_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subclaim_id: str = ""
    source_type: SourceType = SourceType.OTHER
    source_tier: int = 3
    retrieval_path: RetrievalPath = RetrievalPath.DIRECT_CONNECTOR
    source_url: str = ""
    source_title: str = ""
    source_date: str | None = None
    source_authority: str = ""
    quote_or_span: str = ""
    quote_context: str = ""
    verdict_scope: VerdictScope = field(default_factory=VerdictScope)
    relevance_score: float = 0.0
    direction: Direction = Direction.UNCLEAR
    direction_confidence: float = 0.0
    direction_method: DirectionMethod = DirectionMethod.DETERMINISTIC_STRUCTURED
    retrieval_timestamp: str | None = None
    connector_version: str = ""
    connector_query_hash: str = ""
    source_snapshot_id: str | None = None
    raw_response_hash: str = ""
    # v1.5 additions
    claimed_value: ResolvedValue | None = None
    source_value: ResolvedValue | None = None
    deterministic_comparison_result: DeterministicComparisonResult = (
        DeterministicComparisonResult.NOT_RUN
    )
    decisive_quote_required: bool = False
    decisive_quote_span: str | None = None
    source_independence_group_id: str | None = None
    llm_direction_allowed: bool = False
    llm_direction_validation_result: ValidationResult | None = None


@dataclass
class SynthesisLogic:
    status_rule_applied: str = ""
    policy_rule_id: str = ""
    decisive_evidence: list[str] = field(default_factory=list)
    contradictory_evidence: list[str] = field(default_factory=list)
    subclaim_results: list[Any] = field(default_factory=list)
    verdict_scope_applied: VerdictScope = field(default_factory=VerdictScope)
    insufficiency_trigger: str | None = None
    human_review_flags: list[HumanReviewFlag] = field(default_factory=list)
    authority_ranking_applied: bool = False
    claim_expression_node_type: NodeType = NodeType.ATOMIC


@dataclass
class SubclaimResult:
    subclaim_id: str
    status: str  # SUPPORTED, REFUTED, INSUFFICIENT
    p: float
    confidence: float = 0.0
    best_evidence_tier: int | None = None
    limiting_evidence_tier: int | None = None
    decisive_evidence_tier: int | None = None
    citations: list[str] = field(default_factory=list)
    operationalization: str = ""
    verdict_scope: VerdictScope = field(default_factory=VerdictScope)
    insufficiency_reason: str | None = None
    human_review_flags: list[HumanReviewFlag] = field(default_factory=list)
    provenance_spans: list[ProvenanceSpan] = field(default_factory=list)
    synthesis_logic: SynthesisLogic = field(default_factory=SynthesisLogic)
    synthesis_rule_engine_version: str = "v1.5"
    resolved_value: ResolvedValue | None = None

    def __post_init__(self):
        if self.p not in (1.0, 0.0, 0.5):
            raise ValueError(f"p must be exactly 1.0, 0.0, or 0.5, got {self.p}")
        if self.status not in ("SUPPORTED", "REFUTED", "INSUFFICIENT"):
            raise ValueError(f"Invalid status: {self.status}")


@dataclass
class FactCheckResult:
    premise_id: str
    snapshot_id: str
    topic_id: str
    side: Side
    status: str  # SUPPORTED, REFUTED, INSUFFICIENT
    p: float
    confidence: float = 0.0
    best_evidence_tier: int | None = None
    limiting_evidence_tier: int | None = None
    decisive_evidence_tier: int | None = None
    citations: list[str] = field(default_factory=list)
    operationalization: str = ""
    verdict_scope: VerdictScope = field(default_factory=VerdictScope)
    insufficiency_reason: str | None = None
    human_review_flags: list[HumanReviewFlag] = field(default_factory=list)
    provenance_spans: list[ProvenanceSpan] = field(default_factory=list)
    insufficiency_sensitivity: dict[str, Any] = field(default_factory=dict)
    decisive_premise_rank: int | None = None
    subclaim_results: list[SubclaimResult] = field(default_factory=list)
    audit_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.p not in (1.0, 0.0, 0.5):
            raise ValueError(f"p must be exactly 1.0, 0.0, or 0.5, got {self.p}")
        if self.status not in ("SUPPORTED", "REFUTED", "INSUFFICIENT"):
            raise ValueError(f"Invalid status: {self.status}")


@dataclass
class HumanReviewRecord:
    review_id: str
    target_audit_id: str
    target_snapshot_id: str
    reviewer_role: str
    review_outcome: ReviewOutcome
    review_note: str
    review_timestamp: str
    review_record_hash: str


@dataclass
class FrameDependencyKey:
    frame_set_version: str
    frame_id: str
    frame_scope_hash: str


@dataclass
class CacheKey:
    claim_hash: str
    normalized_subclaim_text: str
    claim_type: ClaimType
    resolved_entity_ids_hash: str
    verdict_scope_hash: str
    operationalization_hash: str
    decomposition_version: str
    evidence_policy_version: str
    connector_snapshot_versions_hash: str
    fact_mode: FactMode
    frame_dependency_key: FrameDependencyKey | None = None
