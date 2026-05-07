"""
Fact checking skill package.

The v1 support contract is intentionally narrow: only atomic empirical
identity/date/status/location claims about notable public entities with a
clear authoritative source path may resolve decisively in PERFECT mode.
Unsupported, compound, stale, or poorly scoped claims should remain
INSUFFICIENT with diagnostics explaining why.
"""

from .config import FactCheckConfig
from .connectors import GroundTruthDB, SimulatedSourceConnector, SourceConnector
from .decomposer import ClaimDecomposer
from .models import (
    AllowlistVersion,
    ApprovedSource,
    CacheResult,
    CircuitBreakerConfig,
    EvidenceRecord,
    EvidenceTier,
    FactCheckResult,
    FactCheckStatus,
    FactCheckVerdict,
    PlannerDecision,
    RateLimitConfig,
    RequestContext,
    SourceConfidence,
    SourceResult,
    Subclaim,
    TemporalContext,
)
from .planner import ConnectorPlanner
from .policy import EvidencePolicy, apply_policy, default_policy, strict_policy
from .scoring_inputs import (
    ScoringAdapter,
    TopicSideScore,
    compute_scoring_inputs,
)
from .skill import FactCheckingSkill
from .template_adapters import (
    ClaimAnalysis,
    ClaimType,
    ClaimTypeDetector,
    ConsensusAnalyzer,
    MisinformationScanner,
    SourceCredibilityAnalyzer,
)
from .v15_connectors import (
    BaseEvidenceConnector,
    BLSStatisticsConnector,
    BraveSearchConnector,
    ConnectorRegistry,
    CrossrefConnector,
    CuratedRAGConnector,
    EvidenceConnector,
    WikidataEntityConnector,
)
from .v15_skill import V15FactCheckingSkill
from .web_rag_connector import LLMClient, SearchBackend, WebRAGConnector
from .wikidata_connector import WikidataConnector

__all__ = [
    "FactCheckingSkill",
    "V15FactCheckingSkill",
    "FactCheckResult",
    "EvidenceRecord",
    "EvidenceTier",
    "FactCheckVerdict",
    "FactCheckStatus",
    "AllowlistVersion",
    "ApprovedSource",
    "CircuitBreakerConfig",
    "RateLimitConfig",
    "TemporalContext",
    "RequestContext",
    "CacheResult",
    "FactCheckConfig",
    "PlannerDecision",
    "SourceConfidence",
    "SourceResult",
    "Subclaim",
    "SourceConnector",
    "GroundTruthDB",
    "SimulatedSourceConnector",
    "ClaimDecomposer",
    "EvidencePolicy",
    "default_policy",
    "strict_policy",
    "apply_policy",
    "ConnectorPlanner",
    "WikidataConnector",
    "WebRAGConnector",
    "SearchBackend",
    "LLMClient",
    "WikidataEntityConnector",
    "BLSStatisticsConnector",
    "CrossrefConnector",
    "CuratedRAGConnector",
    "BraveSearchConnector",
    "ConnectorRegistry",
    "EvidenceConnector",
    "BaseEvidenceConnector",
    "ScoringAdapter",
    "TopicSideScore",
    "compute_scoring_inputs",
    "ClaimTypeDetector",
    "ClaimAnalysis",
    "ClaimType",
    "SourceCredibilityAnalyzer",
    "MisinformationScanner",
    "ConsensusAnalyzer",
]
