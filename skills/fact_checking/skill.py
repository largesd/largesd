"""
Main Fact Checking Skill Implementation

Ties together all components:
- Normalization and hashing
- Multi-layer caching
- PII detection
- Source retrieval with rate limiting
- Audit logging
- Async queue processing
"""
import time
from typing import Optional, Dict, Any
from datetime import datetime

from .models import (
    FactCheckResult, FactCheckVerdict, FactCheckStatus, EvidenceTier,
    TemporalContext, RequestContext, CacheResult,
    FactCheckJob
)
from .config import FactCheckConfig, get_config
from .normalization import ClaimNormalizer
from .cache import MultiLayerCache
from .pii import PIIDetector
from .sources import SourceRegistry, EvidenceRetriever, get_default_registry
from .audit import AuditLogger
from .fc_queue import FactCheckQueue, get_global_queue


class FactCheckingSkill:
    """
    Agentic Fact Checking Skill
    
    Supports two modes:
    - OFFLINE: No live source lookup, returns neutral results
    - ONLINE_ALLOWLIST: Queries approved sources, async by default
    
    Usage:
        skill = FactCheckingSkill(mode="ONLINE_ALLOWLIST", allowlist_version="v1")
        
        # Synchronous (waits for result)
        result = skill.check_fact("GDP grew 3% in 2023")
        
        # Asynchronous (returns PENDING, processes in background)
        job = skill.check_fact_async("GDP grew 3% in 2023", request_context={...})
        # Later...
        result = skill.get_job_result(job.job_id)
    """
    
    def __init__(self, 
                 mode: str = "OFFLINE",
                 allowlist_version: str = "v1",
                 config: Optional[FactCheckConfig] = None,
                 source_registry: Optional[SourceRegistry] = None,
                 enable_async: bool = True,
                 async_worker_count: int = 3):
        """
        Initialize the fact checking skill.
        
        Args:
            mode: "OFFLINE" or "ONLINE_ALLOWLIST"
            allowlist_version: Version of source allowlist to use
            config: Configuration (uses default if not provided)
            source_registry: Source registry (uses default if not provided)
            enable_async: Whether to enable async processing
            async_worker_count: Number of background workers
        """
        mode_aliases = {
            "simulated": "OFFLINE",
            "offline": "OFFLINE",
            "online_allowlist": "ONLINE_ALLOWLIST",
            "perfect_checker": "PERFECT_CHECKER",
        }
        self.mode = mode_aliases.get(str(mode).lower(), mode)
        self.allowlist_version = allowlist_version
        self.config = config or get_config()
        self.source_registry = source_registry or get_default_registry()
        
        # Initialize components
        self._cache = MultiLayerCache(
            ttl_seconds=self.config.cache_ttl_seconds
        )
        self._audit = AuditLogger()
        self._evidence_retriever = EvidenceRetriever(self.source_registry)
        
        # Initialize async queue if enabled
        self._async_enabled = enable_async and self.mode == "ONLINE_ALLOWLIST"
        self._queue: Optional[FactCheckQueue] = None
        
        if self._async_enabled:
            self._queue = get_global_queue(
                max_size=self.config.async_queue_max_size
            )
            self._queue.set_processor(self._process_job)
            self._queue.start_workers(async_worker_count)
    
    def check_fact(self, 
                   claim_text: str,
                   temporal_context: Optional[TemporalContext] = None,
                   request_context: Optional[RequestContext] = None,
                   wait_for_async: bool = False) -> FactCheckResult:
        """
        Check a factual claim.
        
        In OFFLINE mode: Returns immediately with neutral result.
        In ONLINE_ALLOWLIST mode: 
            - If cache hit: Returns cached result
            - If cache miss and async enabled: Returns PENDING, queues for processing
            - If cache miss and async disabled: Processes synchronously
        
        Args:
            claim_text: The claim to check
            temporal_context: Optional temporal context for time-sensitive claims
            request_context: Optional request metadata for tracing
            wait_for_async: If True and async enabled, wait for result
            
        Returns:
            FactCheckResult
        """
        start_time = time.time()
        
        # Create default request context if not provided
        if request_context is None:
            request_context = RequestContext()
        
        # Validate input
        if len(claim_text) > self.config.max_claim_length:
            claim_text = claim_text[:self.config.max_claim_length]
        
        # Normalize and hash
        normalized = ClaimNormalizer.normalize(claim_text)
        claim_hash = ClaimNormalizer.compute_hash(normalized)
        
        # Check for PII
        pii_result = PIIDetector.detect(claim_text)
        contains_pii = pii_result.contains_pii
        
        # Check cache
        cache_key = self._cache.build_key(claim_hash, self.mode, self.allowlist_version)
        cached_result, cache_layer = self._cache.get(cache_key)
        
        if cached_result:
            cached_result.cache_result = cache_layer
            return cached_result
        
        # Check if there's a pending async job for this claim
        if self._async_enabled and self._queue:
            pending_job = self._queue.get_pending_result(
                claim_hash, self.mode, self.allowlist_version
            )
            if pending_job:
                # Return PENDING result pointing to existing job
                return FactCheckResult(
                    claim_text=claim_text,
                    normalized_claim_text=normalized,
                    claim_hash=claim_hash,
                    fact_mode=self.mode,
                    allowlist_version=self.allowlist_version,
                    status=FactCheckStatus.PENDING,
                    verdict=FactCheckVerdict.UNVERIFIED,
                    factuality_score=0.5,
                    confidence=0.0,
                    confidence_explanation=f"Fact check in progress (job: {pending_job.job_id})",
                    algorithm_version=self.config.algorithm_version,
                    processing_duration_ms=0,
                    cache_result=CacheResult.MISS,
                    contains_pii=contains_pii,
                    temporal_context=temporal_context,
                )
        
        # Perform fact check based on mode
        if self.mode == "OFFLINE":
            result = self._check_offline(
                claim_text, normalized, claim_hash, 
                contains_pii, temporal_context
            )
        elif self.mode == "PERFECT_CHECKER":
            result = self._check_perfect_checker(
                claim_text, normalized, claim_hash,
                contains_pii, temporal_context
            )
        else:  # ONLINE_ALLOWLIST
            if self._async_enabled and self._queue and not wait_for_async:
                # Queue for async processing
                job = self._queue.submit(
                    claim_text=claim_text,
                    normalized_claim=normalized,
                    claim_hash=claim_hash,
                    fact_mode=self.mode,
                    allowlist_version=self.allowlist_version,
                    temporal_context=temporal_context,
                    request_context=request_context,
                )
                
                # Return PENDING result
                result = FactCheckResult(
                    claim_text=claim_text,
                    normalized_claim_text=normalized,
                    claim_hash=claim_hash,
                    fact_mode=self.mode,
                    allowlist_version=self.allowlist_version,
                    status=FactCheckStatus.PENDING,
                    verdict=FactCheckVerdict.UNVERIFIED,
                    factuality_score=0.5,
                    confidence=0.0,
                    confidence_explanation=f"Fact check queued (job: {job.job_id})",
                    algorithm_version=self.config.algorithm_version,
                    processing_duration_ms=int((time.time() - start_time) * 1000),
                    cache_result=CacheResult.MISS,
                    contains_pii=contains_pii,
                    temporal_context=temporal_context,
                )
            else:
                # Process synchronously
                result = self._check_online_allowlist(
                    claim_text, normalized, claim_hash,
                    contains_pii, temporal_context
                )
        
        # Store in cache (except PENDING results)
        if result.status != FactCheckStatus.PENDING:
            self._cache.set(cache_key, result)
        
        # Log to audit log
        self._audit.log_check(
            result=result,
            request_context=request_context,
            evidence_candidates_count=result.source_count_considered,
        )
        
        return result
    
    def check_fact_async(self, 
                        claim_text: str,
                        temporal_context: Optional[TemporalContext] = None,
                        request_context: Optional[RequestContext] = None) -> FactCheckJob:
        """
        Submit a fact check for async processing.
        
        Args:
            claim_text: The claim to check
            temporal_context: Optional temporal context
            request_context: Optional request metadata
            
        Returns:
            FactCheckJob that can be queried for result
        """
        if not self._async_enabled or not self._queue:
            raise RuntimeError("Async processing not enabled")
        
        # Validate input
        if len(claim_text) > self.config.max_claim_length:
            claim_text = claim_text[:self.config.max_claim_length]
        
        # Normalize and hash
        normalized = ClaimNormalizer.normalize(claim_text)
        claim_hash = ClaimNormalizer.compute_hash(normalized)

        # Check for PII so async jobs preserve the same query-sanitization guarantees as sync checks
        pii_result = PIIDetector.detect(claim_text)
        contains_pii = pii_result.contains_pii
        
        # Create default request context
        if request_context is None:
            request_context = RequestContext()
        
        # Submit to queue
        job = self._queue.submit(
            claim_text=claim_text,
            normalized_claim=normalized,
            claim_hash=claim_hash,
            fact_mode=self.mode,
            allowlist_version=self.allowlist_version,
            temporal_context=temporal_context,
            request_context=request_context,
            contains_pii=contains_pii,
        )
        
        return job
    
    def get_job_result(self, job_id: str) -> Optional[FactCheckResult]:
        """Get result for an async job"""
        if not self._queue:
            return None
        
        job = self._queue.get_job(job_id)
        if job and job.result:
            return job.result
        return None
    
    def get_job_status(self, job_id: str) -> Optional[str]:
        """Get status of an async job"""
        if not self._queue:
            return None
        
        job = self._queue.get_job(job_id)
        return job.status if job else None
    
    def _process_job(self, job: FactCheckJob) -> FactCheckResult:
        """Process a queued job (called by worker threads)"""
        # Check if already cached (deduplication)
        cache_key = self._cache.build_key(
            job.claim_hash, job.fact_mode, job.allowlist_version
        )
        cached, _ = self._cache.get(cache_key)
        if cached:
            return cached
        
        # Perform the check
        result = self._check_online_allowlist(
            job.claim_text,
            job.normalized_claim,
            job.claim_hash,
            job.contains_pii,
            job.temporal_context,
        )
        
        # Store in cache
        self._cache.set(cache_key, result)
        
        # Log to audit
        self._audit.log_check(
            result=result,
            request_context=job.request_context,
            evidence_candidates_count=result.source_count_considered,
        )
        
        return result
    
    def _check_offline(self, claim_text: str, normalized_claim: str,
                      claim_hash: str, contains_pii: bool,
                      temporal_context: Optional[TemporalContext]) -> FactCheckResult:
        """OFFLINE mode: Return neutral result per LSD §13"""
        return FactCheckResult(
            claim_text=claim_text,
            normalized_claim_text=normalized_claim,
            claim_hash=claim_hash,
            fact_mode="OFFLINE",
            allowlist_version=self.allowlist_version,
            status=FactCheckStatus.UNVERIFIED_OFFLINE,
            verdict=FactCheckVerdict.INSUFFICIENT,
            factuality_score=0.5,
            confidence=0.0,
            confidence_explanation="OFFLINE mode: no source lookup performed",
            operationalization="Live source lookup would be required to confirm or refute this claim.",
            evidence=[],
            algorithm_version=self.config.algorithm_version,
            cache_result=CacheResult.MISS,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
        )

    def _check_perfect_checker(self, claim_text: str, normalized_claim: str,
                               claim_hash: str, contains_pii: bool,
                               temporal_context: Optional[TemporalContext]) -> FactCheckResult:
        """PERFECT_CHECKER mode: deterministic discrete p values per LSD §13."""
        lowered = normalized_claim.lower()
        if any(marker in lowered for marker in ("refuted", "false", "contradicted")):
            verdict = FactCheckVerdict.REFUTED
            factuality_score = 0.0
            explanation = "Perfect checker fixture marked the claim as refuted."
        elif any(marker in lowered for marker in ("insufficient", "unknown", "unavailable")):
            verdict = FactCheckVerdict.INSUFFICIENT
            factuality_score = 0.5
            explanation = "Perfect checker fixture marked evidence as unavailable."
        else:
            verdict = FactCheckVerdict.SUPPORTED
            factuality_score = 1.0
            explanation = "Perfect checker fixture marked the claim as supported."

        return FactCheckResult(
            claim_text=claim_text,
            normalized_claim_text=normalized_claim,
            claim_hash=claim_hash,
            fact_mode="PERFECT_CHECKER",
            allowlist_version=self.allowlist_version,
            status=FactCheckStatus.CHECKED,
            verdict=verdict,
            factuality_score=factuality_score,
            confidence=1.0 if verdict != FactCheckVerdict.INSUFFICIENT else 0.0,
            confidence_explanation=explanation,
            operationalization="A perfect checker fixture directly determines support, refutation, or insufficiency.",
            evidence=[],
            evidence_tier_counts={"TIER_1": 1 if verdict != FactCheckVerdict.INSUFFICIENT else 0, "TIER_2": 0, "TIER_3": 0},
            algorithm_version="fc-perfect-v1.2",
            cache_result=CacheResult.MISS,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
        )
    
    def _check_online_allowlist(self, claim_text: str, normalized_claim: str,
                               claim_hash: str, contains_pii: bool,
                               temporal_context: Optional[TemporalContext]) -> FactCheckResult:
        """ONLINE_ALLOWLIST mode: Query approved sources per LSD §13"""
        start_time = time.time()
        
        # Check temporal expiration
        if temporal_context and temporal_context.is_expired():
            return FactCheckResult(
                claim_text=claim_text,
                normalized_claim_text=normalized_claim,
                claim_hash=claim_hash,
                fact_mode="ONLINE_ALLOWLIST",
                allowlist_version=self.allowlist_version,
                status=FactCheckStatus.STALE,
                verdict=FactCheckVerdict.INSUFFICIENT,
                factuality_score=0.5,
                confidence=0.0,
                confidence_explanation="Temporal claim expired; recheck required",
                operationalization="Updated temporal data would be required to evaluate this claim.",
                evidence=[],
                algorithm_version=self.config.algorithm_version,
                cache_result=CacheResult.MISS,
                contains_pii=contains_pii,
                temporal_context=temporal_context,
            )
        
        # Sanitize claim for external query if it contains PII
        query_claim = normalized_claim
        if contains_pii:
            query_claim = PIIDetector.sanitize_for_external_query(normalized_claim)
        
        # Retrieve evidence
        evidence, sources_considered = self._evidence_retriever.retrieve_evidence(
            query_claim, claim_hash, self.allowlist_version
        )
        
        # Assign evidence tiers based on source priority
        for ev in evidence:
            ev.evidence_tier = self._determine_evidence_tier(ev.source_id)
        
        tier_counts = {
            "TIER_1": sum(1 for e in evidence if e.evidence_tier == EvidenceTier.TIER_1),
            "TIER_2": sum(1 for e in evidence if e.evidence_tier == EvidenceTier.TIER_2),
            "TIER_3": sum(1 for e in evidence if e.evidence_tier == EvidenceTier.TIER_3),
        }
        
        # Calculate scores
        if evidence:
            # Average support/contradiction from top evidence
            top_evidence = evidence[:self.config.evidence_keep_n]
            avg_support = sum(e.support_score for e in top_evidence) / len(top_evidence)
            avg_contradiction = sum(e.contradiction_score for e in top_evidence) / len(top_evidence)
            
            # Determine verdict
            verdict = self._determine_verdict(avg_support, avg_contradiction)
            
            # LSD §13: p ∈ {1,0} for SUPPORTED/REFUTED, p=0.5 for INSUFFICIENT
            if verdict == FactCheckVerdict.SUPPORTED:
                factuality_score = 1.0
            elif verdict == FactCheckVerdict.REFUTED:
                factuality_score = 0.0
            else:
                factuality_score = 0.5
            
            # Calculate confidence
            confidence = self._calculate_confidence(
                avg_support, avg_contradiction, len(evidence)
            )
            
            status = FactCheckStatus.CHECKED
            operationalization = "To refute: provide primary evidence contradicting the claim. To confirm: provide additional independent primary sources."
        else:
            # No evidence found
            factuality_score = 0.5
            avg_support = 0.0
            avg_contradiction = 0.0
            verdict = FactCheckVerdict.INSUFFICIENT
            confidence = 0.0
            status = FactCheckStatus.NO_ALLOWLIST_EVIDENCE
            operationalization = "Live retrieval from primary or reputable secondary sources would be required to evaluate this claim."
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return FactCheckResult(
            claim_text=claim_text,
            normalized_claim_text=normalized_claim,
            claim_hash=claim_hash,
            fact_mode="ONLINE_ALLOWLIST",
            allowlist_version=self.allowlist_version,
            status=status,
            verdict=verdict,
            factuality_score=round(factuality_score, 2),
            confidence=round(confidence, 2),
            confidence_explanation=f"Support: {avg_support:.2f}, Contradiction: {avg_contradiction:.2f}",
            operationalization=operationalization,
            evidence=evidence,
            evidence_tier_counts=tier_counts,
            source_count_considered=sources_considered,
            source_count_retained=len(evidence),
            algorithm_version=self.config.algorithm_version,
            processing_duration_ms=duration_ms,
            cache_result=CacheResult.MISS,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
        )
    
    def _determine_verdict(self, support: float, contradiction: float) -> FactCheckVerdict:
        """
        Determine verdict based on support and contradiction scores.
        LSD §13 vocabulary: SUPPORTED, REFUTED, INSUFFICIENT.
        """
        # Check for SUPPORTED
        if support > self.config.support_threshold and contradiction < 0.3:
            return FactCheckVerdict.SUPPORTED
        
        # Check for REFUTED
        if contradiction > self.config.contradiction_threshold and support < 0.3:
            return FactCheckVerdict.REFUTED
        
        # Mixed or weak signals → INSUFFICIENT
        return FactCheckVerdict.INSUFFICIENT
    
    def _determine_evidence_tier(self, source_id: str) -> EvidenceTier:
        """Assign evidence tier based on source priority (LSD §13)."""
        source = self.source_registry.get_source(source_id)
        if source:
            if source.priority >= 8:
                return EvidenceTier.TIER_1
            elif source.priority >= 4:
                return EvidenceTier.TIER_2
        return EvidenceTier.TIER_3
    
    def _calculate_confidence(self, support: float, contradiction: float,
                             evidence_count: int) -> float:
        """Calculate confidence score"""
        # Base confidence from evidence availability
        base_confidence = min(0.9, 0.3 + evidence_count * 0.15)
        
        # Reduce confidence if support and contradiction are close
        if abs(support - contradiction) < self.config.confidence_penalty_threshold:
            base_confidence *= 0.75
        
        return min(1.0, max(0.0, base_confidence))
    
    def invalidate_cache(self, claim_hash: str, reason: str):
        """Explicitly invalidate a cached fact check"""
        self._cache.invalidate_by_claim(claim_hash, self.mode, self.allowlist_version)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return self._cache.get_stats()
    
    def get_audit_stats(self) -> Dict[str, Any]:
        """Get audit log statistics"""
        return self._audit.get_stats()
    
    def get_queue_stats(self) -> Optional[Dict[str, Any]]:
        """Get queue statistics if async is enabled"""
        if self._queue:
            stats = self._queue.get_stats()
            return {
                'queued': stats.queued,
                'processing': stats.processing,
                'completed': stats.completed,
                'failed': stats.failed,
                'total_processed': stats.total_processed,
            }
        return None
    
    def shutdown(self):
        """Shutdown the skill and its workers"""
        if self._queue:
            self._queue.shutdown(wait=True)
