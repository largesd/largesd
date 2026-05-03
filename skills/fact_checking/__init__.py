"""
Fact checking skill package.

The v1 support contract is intentionally narrow: only atomic empirical
identity/date/status/location claims about notable public entities with a
clear authoritative source path may resolve decisively in PERFECT mode.
Unsupported, compound, stale, or poorly scoped claims should remain
INSUFFICIENT with diagnostics explaining why.
"""

from .skill import FactCheckingSkill
from .models import (
    FactCheckResult,
    EvidenceRecord,
    EvidenceTier,
    FactCheckVerdict,
    FactCheckStatus,
    AllowlistVersion,
    ApprovedSource,
    CircuitBreakerConfig,
    RateLimitConfig,
    TemporalContext,
    RequestContext,
    CacheResult,
    PlannerDecision,
    SourceConfidence,
    SourceResult,
    Subclaim,
)
from .config import FactCheckConfig
from .connectors import SourceConnector, GroundTruthDB, SimulatedSourceConnector
from .decomposer import ClaimDecomposer
from .policy import EvidencePolicy, default_policy, strict_policy, apply_policy
from .planner import ConnectorPlanner
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
    'EvidenceTier',
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
    'PlannerDecision',
    'SourceConfidence',
    'SourceResult',
    'Subclaim',
    'SourceConnector',
    'GroundTruthDB',
    'SimulatedSourceConnector',
    'ClaimDecomposer',
    'EvidencePolicy',
    'default_policy',
    'strict_policy',
    'apply_policy',
    'ConnectorPlanner',
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
