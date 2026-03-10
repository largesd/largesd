"""
Fact Checking Agentic Skill

A deterministic, cacheable, auditable skill for evaluating factual claims.
Supports OFFLINE and ONLINE_ALLOWLIST modes.

Usage:
    from debate_system.skills.fact_checking import FactCheckingSkill
    
    skill = FactCheckingSkill(mode="ONLINE_ALLOWLIST", allowlist_version="v1")
    
    # For async operation
    result = await skill.check_fact_async(claim_text, request_context={...})
    
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
)
from .config import FactCheckConfig

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
]
