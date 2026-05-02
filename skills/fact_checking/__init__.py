"""
Fact Checking Agentic Skill

A deterministic, cacheable, auditable skill for evaluating factual claims.
Supports OFFLINE, ONLINE_ALLOWLIST, PERFECT_CHECKER, and PERFECT modes.

Usage:
    from skills.fact_checking import FactCheckingSkill
    
    skill = FactCheckingSkill(mode="PERFECT", allowlist_version="v1")
    
    # For async operation
    job = await skill.check_fact_async(claim_text, request_context={...})
    
    # For sync operation (returns immediately with PENDING if async)
    result = skill.check_fact(claim_text)
"""

from .skill import FactCheckingSkill
from .models import (
    FactCheckResult,
    EvidenceRecord,
    FactCheckVerdict,
    FactCheckStatus,
    AllowlistVersion,
    ApprovedSource,
    CircuitBreakerConfig,
    RateLimitConfig,
    TemporalContext,
    RequestContext,
    CacheResult,
    SourceConfidence,
    SourceResult,
)
from .config import FactCheckConfig
from .connectors import SourceConnector, GroundTruthDB, SimulatedSourceConnector
from .policy import EvidencePolicy, default_policy, strict_policy, apply_policy
from .wikidata_connector import WikidataConnector
from .web_rag_connector import WebRAGConnector, SearchBackend, LLMClient
from .template_adapters import (
    ClaimTypeDetector,
    ClaimAnalysis,
    ClaimType,
    SourceCredibilityAnalyzer,
    MisinformationScanner,
    ConsensusAnalyzer,
)

__all__ = [
    'FactCheckingSkill',
    'FactCheckResult',
    'EvidenceRecord',
    'FactCheckVerdict',
    'FactCheckStatus',
    'AllowlistVersion',
    'ApprovedSource',
    'CircuitBreakerConfig',
    'RateLimitConfig',
    'TemporalContext',
    'RequestContext',
    'CacheResult',
    'FactCheckConfig',
    'SourceConfidence',
    'SourceResult',
    'SourceConnector',
    'GroundTruthDB',
    'SimulatedSourceConnector',
    'EvidencePolicy',
    'default_policy',
    'strict_policy',
    'apply_policy',
    'WikidataConnector',
    'WebRAGConnector',
    'SearchBackend',
    'LLMClient',
    'ClaimTypeDetector',
    'ClaimAnalysis',
    'ClaimType',
    'SourceCredibilityAnalyzer',
    'MisinformationScanner',
    'ConsensusAnalyzer',
]
