"""
Core data models for the Blind LLM-Adjudicated Debate System
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime
from enum import Enum
import uuid


class Side(Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"


class ModulationOutcome(Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


class BlockReason(Enum):
    OFF_TOPIC = "off_topic"
    PII = "pii"
    SPAM = "spam"
    HARASSMENT = "harassment"
    TOXICITY = "toxicity"
    PROMPT_INJECTION = "prompt_injection"


class EvidenceTier(Enum):
    TIER_1 = "TIER_1"  # primary/official
    TIER_2 = "TIER_2"  # reputable secondary synthesis
    TIER_3 = "TIER_3"  # limited/uncertain


class FactCheckVerdict(Enum):
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    INSUFFICIENT = "INSUFFICIENT"
    UNVERIFIED = "UNVERIFIED"


class FactCheckStatus(Enum):
    UNVERIFIED_OFFLINE = "UNVERIFIED_OFFLINE"
    CHECKED = "CHECKED"
    NO_ALLOWLIST_EVIDENCE = "NO_ALLOWLIST_EVIDENCE"
    ERROR_RECOVERED = "ERROR_RECOVERED"
    PENDING = "PENDING"
    STALE = "STALE"


@dataclass
class EvidenceRecord:
    """Evidence supporting or contradicting a fact"""
    source_url: str
    source_id: str
    source_version: Optional[str]
    source_title: str
    snippet: str
    content_hash: str
    retrieved_at: datetime
    relevance_score: float
    support_score: float
    contradiction_score: float
    selected_rank: int
    evidence_tier: EvidenceTier = EvidenceTier.TIER_3


@dataclass
class FactCheckResult:
    """Result of fact-checking a claim"""
    claim_text: str
    normalized_claim_text: str
    claim_hash: str
    fact_mode: str  # "OFFLINE" or "ONLINE_ALLOWLIST"
    allowlist_version: str
    status: FactCheckStatus
    verdict: FactCheckVerdict
    factuality_score: float  # P(fact true) ∈ [0,1]
    confidence: float  # confidence in the fact-check quality
    confidence_explanation: Optional[str]
    operationalization: Optional[str] = None  # what would confirm/refute
    evidence: List[EvidenceRecord] = field(default_factory=list)
    evidence_tier_counts: Dict[str, int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    invalidated_at: Optional[datetime] = None
    invalidation_reason: Optional[str] = None
    source_count_considered: int = 0
    source_count_retained: int = 0
    algorithm_version: str = "fc-1.0"
    processing_duration_ms: int = 0
    cache_result: Optional[str] = None


@dataclass
class Span:
    """
    Traceability primitive - a segment of text from a post.
    
    Per MSD §5: Spans are the sole provenance substrate for:
    - FACT nodes
    - ARGUMENT nodes  
    - Summaries
    - Coverage judgments
    """
    span_id: str
    post_id: str
    start_offset: int  # Character offset in canonical tokenization
    end_offset: int
    span_text: str
    topic_id: str
    side: Side
    span_type: str = "fact"  # "fact" or "inference"


@dataclass
class Fact:
    """Atomic, empirically checkable claim"""
    fact_id: str
    fact_text: str
    topic_id: str
    side: Side
    provenance_links: List[Span] = field(default_factory=list)
    fact_check: Optional[FactCheckResult] = None
    p_true: float = 0.5  # P(fact true), default is uncertain


@dataclass
class CanonicalFact:
    """Deduplicated canonical FACT node"""
    canon_fact_id: str
    canon_fact_text: str
    member_fact_ids: Set[str]
    merged_provenance_links: List[Span]
    referenced_by_au_ids: Set[str]
    p_true: float = 0.5
    centrality: float = 0.0
    distinct_support: int = 0
    is_rarity_slice: bool = False
    evidence_tier_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class ArgumentUnit:
    """Facts + Inference structure"""
    au_id: str
    topic_id: str
    side: Side
    fact_spans: List[Span]
    inference_spans: List[Span]
    au_facts: List[str]  # extracted fact texts
    au_inference: str  # extracted inference text
    provenance_links: Dict[str, List[Span]] = field(default_factory=dict)


@dataclass
class CanonicalArgument:
    """Deduplicated canonical ARGUMENT node"""
    canon_arg_id: str
    topic_id: str
    side: Side
    supporting_facts: Set[str]  # set of canon_fact_ids
    inference_text: str
    member_au_ids: Set[str]
    merged_provenance: List[Span]
    reasoning_score: float = 0.5  # median across judges
    reasoning_iqr: float = 0.0
    centrality: float = 0.0
    distinct_support: int = 0
    is_rarity_slice: bool = False


@dataclass
class Topic:
    """Neutral, bounded topic"""
    topic_id: str
    name: str
    scope: str
    frame_id: str = ""
    relevance: float = 0.0  # Rel_t - content mass share
    drift_score: float = 0.0
    coherence: float = 0.0
    distinctness: float = 0.0
    parent_topic_ids: List[str] = field(default_factory=list)
    operation: str = "created"  # created, merged, split, renamed, unchanged
    summary_for: str = ""
    summary_against: str = ""


@dataclass
class TopicSideScores:
    """Scores for a topic-side"""
    topic_id: str
    side: Side
    factuality: float = 0.0  # F_{t,s}
    reasoning: float = 0.0  # Reason_{t,s}
    coverage: float = 0.0  # Cov_{t,s}
    quality: float = 0.0  # Q_{t,s}
    reasoning_iqr: float = 0.0
    coverage_iqr: float = 0.0


@dataclass
class Post:
    """A debate post submission"""
    post_id: str
    side: Side
    topic_id: str
    facts: str
    inference: str
    counter_arguments: str
    timestamp: datetime
    frame_id: str = ""
    modulation_outcome: ModulationOutcome = ModulationOutcome.ALLOWED
    block_reason: Optional[BlockReason] = None
    
    def __post_init__(self):
        if not self.post_id:
            self.post_id = f"post_{uuid.uuid4().hex[:12]}"


@dataclass
class Snapshot:
    """Immutable capture of debate state"""
    snapshot_id: str
    timestamp: datetime
    trigger_type: str  # activity, time, manual
    template_name: str
    template_version: str
    posts: List[Post]
    allowed_count: int
    blocked_count: int
    block_reasons: Dict[BlockReason, int]
    topics: List[Topic]
    canonical_facts: Dict[str, List[CanonicalFact]]  # topic_id -> facts
    canonical_arguments: Dict[str, List[CanonicalArgument]]  # topic_id -> args
    topic_scores: Dict[str, TopicSideScores]  # "topic_id_side" -> scores
    frame_id: Optional[str] = None
    side_order: List[str] = field(default_factory=list)
    overall_scores: Dict[str, float] = field(default_factory=dict)
    overall_for: float = 0.0
    overall_against: float = 0.0
    margin_d: float = 0.0
    ci_d_lower: float = -0.1
    ci_d_upper: float = 0.1
    confidence: float = 0.0
    verdict: str = "NO VERDICT"


@dataclass
class DebateFrame:
    """Structured frame defining debate question, sides, rubric, and scope."""
    frame_id: str
    debate_id: str
    version: int
    stage: str
    motion: str
    frame_summary: str
    sides: List[Dict[str, str]]
    evaluation_criteria: List[str]
    definitions: List[Dict[str, str]]
    scope_constraints: List[str]
    created_at: datetime
    label: str = ""
    notes: str = ""
    supersedes_frame_id: Optional[str] = None
    framing_debate_id: Optional[str] = None
    is_active: bool = True


@dataclass
class Debate:
    """Complete debate state"""
    debate_id: str
    resolution: str
    scope: str
    created_at: datetime
    motion: str = ""
    moderation_criteria: str = ""
    debate_frame: str = ""
    active_frame_id: Optional[str] = None
    active_frame: Optional[DebateFrame] = None
    user_id: Optional[str] = None  # Creator of the debate
    current_snapshot: Optional[Snapshot] = None
    snapshots: List[Snapshot] = field(default_factory=list)
    pending_posts: List[Post] = field(default_factory=list)


@dataclass
class User:
    """User account for debate system"""
    user_id: str
    email: str
    password_hash: str
    display_name: str
    created_at: datetime
    is_active: bool = True
    is_verified: bool = False
    is_admin: bool = False
    last_login: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.user_id:
            self.user_id = f"user_{uuid.uuid4().hex[:12]}"
