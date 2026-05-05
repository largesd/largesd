"""
Configuration for Fact Checking Skill
All thresholds and parameters are versioned
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class FactCheckConfig:
    """
    Versioned configuration for fact checking.
    All values are fixed per algorithm version for determinism.
    """
    
    # Versioning
    algorithm_version: str = "fc-1.0"
    
    # Input constraints
    max_claim_length: int = 500
    
    # Thresholds for verdict determination
    support_threshold: float = 0.70  # Minimum support_score for SUPPORTED
    contradiction_threshold: float = 0.70  # Minimum contradiction_score for CONTRADICTED
    mixed_threshold: float = 0.40  # If both scores exceed this, consider MIXED
    confidence_penalty_threshold: float = 0.30  # For near-threshold confidence penalty
    
    # Retrieval settings
    retrieval_top_k: int = 10
    evidence_keep_n: int = 3
    max_evidence_age_days: int = 365
    source_timeout_ms: int = 5000
    
    # Rate limiting defaults
    default_rate_limit_per_second: float = 10.0
    default_rate_limit_per_minute: int = 100
    circuit_breaker_threshold: int = 3
    circuit_breaker_timeout_minutes: int = 5
    
    # Async queue settings
    async_queue_max_size: int = 1000
    async_max_queue_wait_ms: int = 30000
    async_worker_count: int = 3
    
    # Cache settings
    cache_ttl_seconds: int = 86400 * 30  # 30 days
    
    # v1.5 parallel router settings
    max_connector_workers: int = 4
    connector_timeout_seconds: float = 30.0
    
    # v1.5 circuit breaker settings
    circuit_breaker_threshold: int = 5
    circuit_breaker_recovery_seconds: float = 60.0
    
    # v1.5 fallback chains: primary connector_id -> [fallback connector_ids]
    fallback_chains: Dict[str, List[str]] = field(default_factory=lambda: {
        "bls_statistics_v15": ["curated_rag_v15"],
        "wikidata_entity_v15": ["curated_rag_v15"],
        "crossref_v15": ["curated_rag_v15"],
        "brave_search_v15": ["curated_rag_v15"],
    })
    
    # v1.5 claim-type-specific fallback chains
    claim_type_fallbacks: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FactCheckConfig':
        """Create config from dictionary"""
        return cls(**{
            k: v for k, v in data.items()
            if k in cls.__dataclass_fields__
        })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return {
            'algorithm_version': self.algorithm_version,
            'max_claim_length': self.max_claim_length,
            'support_threshold': self.support_threshold,
            'contradiction_threshold': self.contradiction_threshold,
            'mixed_threshold': self.mixed_threshold,
            'confidence_penalty_threshold': self.confidence_penalty_threshold,
            'retrieval_top_k': self.retrieval_top_k,
            'evidence_keep_n': self.evidence_keep_n,
            'max_evidence_age_days': self.max_evidence_age_days,
            'source_timeout_ms': self.source_timeout_ms,
            'default_rate_limit_per_second': self.default_rate_limit_per_second,
            'default_rate_limit_per_minute': self.default_rate_limit_per_minute,
            'circuit_breaker_threshold': self.circuit_breaker_threshold,
            'circuit_breaker_timeout_minutes': self.circuit_breaker_timeout_minutes,
            'async_queue_max_size': self.async_queue_max_size,
            'async_max_queue_wait_ms': self.async_max_queue_wait_ms,
            'async_worker_count': self.async_worker_count,
            'cache_ttl_seconds': self.cache_ttl_seconds,
        }


# Default configurations by version
CONFIG_VERSIONS = {
    "fc-1.0": FactCheckConfig(algorithm_version="fc-1.0"),
}


def get_config(version: str = "fc-1.0") -> FactCheckConfig:
    """Get configuration for a specific algorithm version"""
    return CONFIG_VERSIONS.get(version, CONFIG_VERSIONS["fc-1.0"])
