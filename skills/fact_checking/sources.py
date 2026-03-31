"""
Source allowlist management and evidence retrieval
"""
import hashlib
import time
from typing import List, Dict, Optional, Any
from datetime import datetime
from dataclasses import dataclass
import random

from .models import (
    AllowlistVersion, ApprovedSource, EvidenceRecord, 
    CircuitBreakerConfig, RateLimitConfig
)
from .rate_limiter import SourceManager


# Built-in default allowlist for demonstration
DEFAULT_ALLOWLIST = AllowlistVersion(
    version="v1",
    approved_sources=[
        ApprovedSource(
            source_id="wikidata",
            domain="wikidata.org",
            endpoint="https://query.wikidata.org/sparql",
            priority=10,
            rate_limit=RateLimitConfig(
                requests_per_second=5.0,
                requests_per_minute=50,
                daily_quota=1000,
            ),
            parser_version="v1",
            max_evidence_age_days=365,
        ),
        ApprovedSource(
            source_id="arxiv",
            domain="arxiv.org",
            endpoint=None,  # Any arxiv.org URL
            priority=8,
            rate_limit=RateLimitConfig(
                requests_per_second=3.0,
                requests_per_minute=30,
            ),
            parser_version="v1",
            max_evidence_age_days=730,
        ),
    ],
    retrieval_top_k=10,
    evidence_keep_n=3,
    circuit_breaker_config=CircuitBreakerConfig(
        failure_threshold=3,
        timeout_minutes=5,
    ),
)


class SourceRegistry:
    """Registry of source allowlists"""
    
    def __init__(self):
        self._allowlists: Dict[str, AllowlistVersion] = {
            "v1": DEFAULT_ALLOWLIST,
        }
        self._source_manager = SourceManager()
        self._init_source_managers()
    
    def _init_source_managers(self):
        """Initialize rate limiters and circuit breakers for all sources"""
        for allowlist in self._allowlists.values():
            for source in allowlist.approved_sources:
                self._source_manager.register_source(
                    source.source_id,
                    source.rate_limit,
                    allowlist.circuit_breaker_config
                )
    
    def get_allowlist(self, version: str) -> Optional[AllowlistVersion]:
        """Get allowlist by version"""
        return self._allowlists.get(version)
    
    def register_allowlist(self, allowlist: AllowlistVersion):
        """Register a new allowlist version"""
        self._allowlists[allowlist.version] = allowlist
        # Register sources
        for source in allowlist.approved_sources:
            self._source_manager.register_source(
                source.source_id,
                source.rate_limit,
                allowlist.circuit_breaker_config
            )
    
    def get_source_manager(self) -> SourceManager:
        """Get the source manager"""
        return self._source_manager


class EvidenceRetriever:
    """
    Retrieves evidence from approved sources.
    
    For the prototype, this simulates deterministic evidence retrieval.
    In production, this would make actual HTTP requests to approved sources.
    """
    
    def __init__(self, source_registry: SourceRegistry):
        self._registry = source_registry
    
    def retrieve_evidence(self, normalized_claim: str, claim_hash: str,
                         allowlist_version: str) -> tuple[List[EvidenceRecord], int]:
        """
        Retrieve evidence for a claim from approved sources.
        
        Args:
            normalized_claim: Normalized claim text
            claim_hash: Hash of normalized claim
            allowlist_version: Version of allowlist to use
            
        Returns:
            Tuple of (evidence_records, sources_considered)
        """
        allowlist = self._registry.get_allowlist(allowlist_version)
        if not allowlist:
            return [], 0
        
        source_manager = self._registry.get_source_manager()
        evidence_candidates = []
        sources_considered = 0
        
        # Try each approved source
        for source in allowlist.approved_sources:
            sources_considered += 1
            
            # Check if source can be queried
            can_query, reason = source_manager.can_query(source.source_id)
            if not can_query:
                continue
            
            try:
                # Simulate retrieval (in production: actual HTTP request)
                source_evidence = self._query_source(
                    source, normalized_claim, claim_hash
                )
                
                if source_evidence:
                    evidence_candidates.extend(source_evidence)
                    source_manager.record_success(source.source_id)
                else:
                    # No evidence found is not a failure
                    pass
                    
            except Exception as e:
                # Record failure for circuit breaker
                source_manager.record_failure(source.source_id)
                continue
        
        # Sort and select top evidence deterministically
        selected_evidence = self._select_evidence(
            evidence_candidates, 
            allowlist.evidence_keep_n
        )
        
        return selected_evidence, sources_considered
    
    def _query_source(self, source: ApprovedSource, 
                     normalized_claim: str, claim_hash: str) -> List[EvidenceRecord]:
        """
        Query a single source for evidence.
        
        For prototype: generates deterministic simulated evidence.
        In production: makes actual API calls.
        """
        # Use claim hash to generate deterministic "evidence"
        hash_int = int(claim_hash[:16], 16)
        
        # Determine if this source has relevant evidence
        # (simulated based on hash for determinism)
        has_evidence = (hash_int % 100) > 30  # 70% chance
        
        if not has_evidence:
            return []
        
        # Generate simulated evidence
        evidence_list = []
        
        # Determine support level deterministically
        support_level = (hash_int % 100) / 100.0
        
        # Create 1-2 evidence records
        num_records = 1 + (hash_int % 2)
        
        for i in range(num_records):
            # Vary support slightly per record
            record_support = max(0.0, min(1.0, support_level + (i * 0.1 - 0.05)))
            record_contradiction = 1.0 - record_support
            
            # Simulate content hash for drift detection
            content = f"{source.source_id}:{normalized_claim}:{i}"
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
            
            evidence = EvidenceRecord(
                source_url=f"https://{source.domain}/evidence/{claim_hash[:16]}",
                source_id=source.source_id,
                source_version="v1",
                source_title=f"Reference from {source.source_id}",
                snippet=f"Evidence related to claim: {normalized_claim[:50]}...",
                content_hash=content_hash,
                retrieved_at=datetime.now(),
                relevance_score=0.7 + (i * 0.1),
                support_score=round(record_support, 2),
                contradiction_score=round(record_contradiction, 2),
                selected_rank=i + 1,
            )
            evidence_list.append(evidence)
        
        return evidence_list
    
    def _select_evidence(self, candidates: List[EvidenceRecord], 
                        keep_n: int) -> List[EvidenceRecord]:
        """
        Select top N evidence deterministically.
        
        Sorting order (per spec):
        1. relevance_score DESC
        2. source_url ASC (lexicographic)
        3. source_version ASC (nulls first)
        4. source_id ASC
        """
        # Sort with deterministic tie-breakers
        sorted_evidence = sorted(
            candidates,
            key=lambda e: (
                -e.relevance_score,  # DESC
                e.source_url,         # ASC
                e.source_version or "",  # ASC, nulls as empty
                e.source_id,          # ASC
            )
        )
        
        # Assign ranks and keep top N
        selected = []
        for i, evidence in enumerate(sorted_evidence[:keep_n]):
            evidence.selected_rank = i + 1
            selected.append(evidence)
        
        return selected


def get_default_registry() -> SourceRegistry:
    """Get default source registry with built-in allowlist"""
    return SourceRegistry()
