"""
Data models for the Fact Checking Skill.

V1 support is intentionally narrow: only atomic identity/date/status/location
claims about notable public entities are eligible for decisive resolution.
Unsupported, compound, poorly scoped, or stale claims should remain
INSUFFICIENT and carry diagnostics that explain why.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Any
from datetime import datetime
from enum import Enum
import uuid


class EvidenceTier(Enum):
    """Evidence quality tier per LSD §13"""
    TIER_1 = "TIER_1"  # primary/official
    TIER_2 = "TIER_2"  # reputable secondary synthesis
    TIER_3 = "TIER_3"  # limited/uncertain


class FactCheckVerdict(Enum):
    """Deterministic verdict values"""
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    INSUFFICIENT = "INSUFFICIENT"
    UNVERIFIED = "UNVERIFIED"


class FactCheckStatus(Enum):
    """Status of fact-check operation"""
    UNVERIFIED_OFFLINE = "UNVERIFIED_OFFLINE"
    CHECKED = "CHECKED"
    NO_ALLOWLIST_EVIDENCE = "NO_ALLOWLIST_EVIDENCE"
    ERROR_RECOVERED = "ERROR_RECOVERED"
    PENDING = "PENDING"
    STALE = "STALE"


class CacheResult(Enum):
    """Cache hit/miss indicators"""
    HIT_MEMORY = "HIT_MEMORY"
    HIT_REDIS = "HIT_REDIS"
    HIT_DB = "HIT_DB"
    MISS = "MISS"


class SourceConfidence(Enum):
    """How strongly a source supports or contradicts a claim."""
    CONFIRMS = "confirms"      # Source explicitly confirms
    CONTRADICTS = "contradicts"  # Source explicitly contradicts
    SILENT = "silent"          # Source has no relevant information
    AMBIGUOUS = "ambiguous"    # Source has mixed or unclear information


@dataclass
class SourceResult:
    """Result from querying a single source."""
    source_id: str
    source_url: str
    source_title: str
    confidence: SourceConfidence
    excerpt: str  # Verbatim quote or summary from the source
    content_hash: str
    retrieved_at: Optional[datetime]
    tier: EvidenceTier


@dataclass
class TemporalContext:
    """Temporal context for time-sensitive claims"""
    is_temporal: bool = False
    observation_date: Optional[datetime] = None
    expiration_policy: Optional[str] = None  # "NEVER", "30_DAYS", "90_DAYS", "1_YEAR"
    
    def is_expired(self) -> bool:
        """Check if temporal claim has expired"""
        if not self.is_temporal or not self.observation_date:
            return False
        
        if self.expiration_policy == "NEVER" or not self.expiration_policy:
            return False
        
        now = datetime.now()
        delta = now - self.observation_date
        
        policy_days = {
            "30_DAYS": 30,
            "90_DAYS": 90,
            "1_YEAR": 365,
        }
        
        return delta.days > policy_days.get(self.expiration_policy, float('inf'))


@dataclass
class RequestContext:
    """Request metadata for tracing (does NOT affect cache key)"""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    post_id: Optional[str] = None
    point_id: Optional[str] = None
    counterpoint_id: Optional[str] = None
    submission_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'request_id': self.request_id,
            'post_id': self.post_id,
            'point_id': self.point_id,
            'counterpoint_id': self.counterpoint_id,
            'submission_id': self.submission_id,
            'timestamp': self.timestamp.isoformat(),
        }


@dataclass
class EvidenceRecord:
    """Evidence supporting or contradicting a fact"""
    source_url: str
    source_id: str
    source_version: Optional[str]
    source_title: str
    snippet: str
    content_hash: str  # SHA256 of retrieved content for drift detection
    retrieved_at: Optional[datetime]
    relevance_score: float
    support_score: float  # [0,1]
    contradiction_score: float  # [0,1]
    selected_rank: int
    evidence_tier: EvidenceTier = EvidenceTier.TIER_3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'source_url': self.source_url,
            'source_id': self.source_id,
            'source_version': self.source_version,
            'source_title': self.source_title,
            'snippet': self.snippet,
            'content_hash': self.content_hash,
            'retrieved_at': self.retrieved_at.isoformat() if self.retrieved_at else None,
            'relevance_score': self.relevance_score,
            'support_score': self.support_score,
            'contradiction_score': self.contradiction_score,
            'selected_rank': self.selected_rank,
            'evidence_tier': self.evidence_tier.value,
        }


@dataclass(frozen=True)
class Subclaim:
    """Deterministic atomic subclaim derived from a larger empirical claim."""
    subclaim_id: str
    claim_text: str
    normalized_claim_text: str
    claim_family: str
    actor: Optional[str] = None
    geography: Optional[str] = None
    time_scope: Optional[str] = None
    quantity: Optional[str] = None
    negated: bool = False
    source_fact_id: Optional[str] = None


@dataclass(frozen=True)
class PlannerDecision:
    """Deterministic routing decision for a subclaim."""
    supported: bool
    claim_family: str
    connector_path: List[str] = field(default_factory=list)
    reason_code: str = "unsupported_claim_family"
    reason: str = ""
    web_corroboration_allowed: bool = False


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
    confidence: float  # confidence in the fact-check quality ∈ [0,1]
    confidence_explanation: Optional[str]
    operationalization: Optional[str] = None
    evidence: List[EvidenceRecord] = field(default_factory=list)
    evidence_tier_counts: Dict[str, int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    invalidated_at: Optional[datetime] = None
    invalidation_reason: Optional[str] = None
    source_count_considered: int = 0
    source_count_retained: int = 0
    algorithm_version: str = "fc-1.0"
    processing_duration_ms: int = 0
    cache_result: Optional[CacheResult] = None
    contains_pii: bool = False
    temporal_context: Optional[TemporalContext] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'claim_text': self.claim_text,
            'normalized_claim_text': self.normalized_claim_text,
            'claim_hash': self.claim_hash,
            'fact_mode': self.fact_mode,
            'allowlist_version': self.allowlist_version,
            'status': self.status.value,
            'verdict': self.verdict.value,
            'factuality_score': self.factuality_score,
            'confidence': self.confidence,
            'confidence_explanation': self.confidence_explanation,
            'operationalization': self.operationalization,
            'evidence': [e.to_dict() for e in self.evidence],
            'evidence_tier_counts': self.evidence_tier_counts,
            'created_at': self.created_at.isoformat(),
            'invalidated_at': self.invalidated_at.isoformat() if self.invalidated_at else None,
            'invalidation_reason': self.invalidation_reason,
            'source_count_considered': self.source_count_considered,
            'source_count_retained': self.source_count_retained,
            'algorithm_version': self.algorithm_version,
            'processing_duration_ms': self.processing_duration_ms,
            'cache_result': self.cache_result.value if self.cache_result else None,
            'contains_pii': self.contains_pii,
            'temporal_context': {
                'is_temporal': self.temporal_context.is_temporal,
                'observation_date': self.temporal_context.observation_date.isoformat() if self.temporal_context and self.temporal_context.observation_date else None,
                'expiration_policy': self.temporal_context.expiration_policy if self.temporal_context else None,
            } if self.temporal_context else None,
            'diagnostics': self.diagnostics,
        }


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a source"""
    requests_per_second: float = 10.0
    requests_per_minute: int = 100
    daily_quota: Optional[int] = None
    queue_max_size: int = 1000
    max_queue_wait_ms: int = 30000


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration"""
    failure_threshold: int = 3
    timeout_minutes: int = 5


@dataclass
class ApprovedSource:
    """An approved source in the allowlist"""
    source_id: str
    domain: str
    endpoint: Optional[str]  # Exact endpoint if applicable
    priority: int = 0  # Higher = more trusted
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    parser_version: str = "v1"
    max_evidence_age_days: int = 365
    
    def matches_url(self, url: str) -> bool:
        """Check if URL matches this source"""
        if self.endpoint:
            return url == self.endpoint
        return self.domain in url


@dataclass
class AllowlistVersion:
    """Versioned allowlist of approved sources"""
    version: str
    approved_sources: List[ApprovedSource]
    retrieval_top_k: int = 10
    evidence_keep_n: int = 3
    parser_version: str = "v1"
    max_evidence_age_days: int = 365
    circuit_breaker_config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    effective_start: datetime = field(default_factory=datetime.now)
    retired: Optional[datetime] = None
    
    def is_active(self) -> bool:
        """Check if this allowlist version is active"""
        now = datetime.now()
        if now < self.effective_start:
            return False
        if self.retired and now > self.retired:
            return False
        return True
    
    def get_source_for_url(self, url: str) -> Optional[ApprovedSource]:
        """Get approved source matching URL"""
        for source in self.approved_sources:
            if source.matches_url(url):
                return source
        return None


@dataclass
class FactCheckJob:
    """A queued fact-check job for async processing"""
    job_id: str
    claim_text: str
    normalized_claim: str
    claim_hash: str
    fact_mode: str
    allowlist_version: str
    temporal_context: Optional[TemporalContext]
    request_context: RequestContext
    contains_pii: bool = False
    status: str = "queued"  # queued, processing, completed, failed
    result: Optional[FactCheckResult] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
