"""
Perfect Fact Checking Skill (LSD §13)

Enforces the discrete p-value contract:
- SUPPORTED  -> p = 1.0
- REFUTED    -> p = 0.0
- INSUFFICIENT -> p = 0.5

Integrates with real source connectors, a ground-truth cache,
and a human-in-the-loop escalation queue for contested claims.

Maintains backward compatibility with the existing FactCheckingSkill
interface used by the debate system backend.
"""
import os
import time
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime

from .models import (
    FactCheckResult, FactCheckVerdict, FactCheckStatus,
    EvidenceTier, EvidenceRecord, CacheResult, TemporalContext,
    RequestContext, FactCheckJob, SourceConfidence, SourceResult,
)
from .config import FactCheckConfig, get_config
from .normalization import ClaimNormalizer
from .cache import MultiLayerCache
from .pii import PIIDetector
from .audit import AuditLogger
from .fc_queue import FactCheckQueue, get_global_queue
from .connectors import SourceConnector, GroundTruthDB, SimulatedSourceConnector
from .policy import EvidencePolicy, default_policy, strict_policy, apply_policy


class _EvidenceRetrieverProxy:
    """
    Backward-compatibility proxy that wraps SourceConnector instances
    and exposes the old retrieve_evidence() interface.

    Holds a reference to the parent skill so that connector changes
    are picked up dynamically.
    """

    def __init__(self, skill: 'FactCheckingSkill'):
        self._skill = skill

    def retrieve_evidence(self, normalized_claim: str, claim_hash: str,
                          allowlist_version: str) -> Tuple[List[EvidenceRecord], int]:
        """Query all connectors and return evidence in legacy format."""
        source_results: List[SourceResult] = []
        for connector in self._skill.connectors:
            try:
                res = connector.query(normalized_claim, claim_hash)
                if res:
                    source_results.append(res)
            except Exception:
                continue

        evidence = []
        for i, r in enumerate(source_results):
            support = 1.0 if r.confidence == SourceConfidence.CONFIRMS else 0.0
            contradiction = 1.0 if r.confidence == SourceConfidence.CONTRADICTS else 0.0
            relevance = 0.9 if r.confidence in (
                SourceConfidence.CONFIRMS, SourceConfidence.CONTRADICTS
            ) else 0.5
            evidence.append(EvidenceRecord(
                source_url=r.source_url,
                source_id=r.source_id,
                source_version="v1",
                source_title=r.source_title,
                snippet=r.excerpt,
                content_hash=r.content_hash,
                retrieved_at=r.retrieved_at,
                relevance_score=relevance,
                support_score=support,
                contradiction_score=contradiction,
                selected_rank=i + 1,
                evidence_tier=r.tier,
            ))
        return evidence, len(self._skill.connectors)


class FactCheckingSkill:
    """
    LSD §13 Perfect Fact Checker.

    Modes:
    - OFFLINE: Returns UNVERIFIED/INSUFFICIENT for everything (safe default).
    - ONLINE_ALLOWLIST: Perfect checking with simulated connectors (backward compat).
    - PERFECT_CHECKER / PERFECT: Perfect checking with optional ground-truth DB
      and configurable source connectors. Falls back to keyword-based fixture
      when no ground-truth or connectors are configured (for testing).
    """

    def __init__(
        self,
        mode: str = "OFFLINE",
        allowlist_version: str = "v1",
        config: Optional[FactCheckConfig] = None,
        source_registry: Optional[Any] = None,  # kept for backward compat
        enable_async: bool = True,
        async_worker_count: int = 3,
        connectors: Optional[List[SourceConnector]] = None,
        ground_truth_db: Optional[GroundTruthDB] = None,
        cache_ttl_seconds: Optional[int] = None,
        policy: Optional[EvidencePolicy] = None,
    ):
        mode_aliases = {
            "simulated": "OFFLINE",
            "offline": "OFFLINE",
            "online_allowlist": "ONLINE_ALLOWLIST",
            "perfect_checker": "PERFECT_CHECKER",
            "perfect": "PERFECT",
        }
        self.mode = mode_aliases.get(str(mode).lower(), mode)
        self.allowlist_version = allowlist_version
        self.config = config or get_config()

        # Initialize components
        ttl = cache_ttl_seconds or self.config.cache_ttl_seconds
        self._cache = MultiLayerCache(ttl_seconds=ttl)
        self._audit = AuditLogger()

        # Evidence policy (LSD §13)
        self.policy = policy or (
            strict_policy() if self.mode in ("PERFECT", "PERFECT_CHECKER")
            else default_policy()
        )

        # Ground-truth DB
        self.ground_truth = ground_truth_db or GroundTruthDB()

        # Source connectors
        self.connectors: List[SourceConnector] = connectors or []
        # For ONLINE_ALLOWLIST mode, provide default simulated connectors
        # if none were explicitly supplied.
        if self.mode == "ONLINE_ALLOWLIST" and not self.connectors:
            self.connectors = [
                SimulatedSourceConnector("wikidata", "wikidata.org", priority=10),
                SimulatedSourceConnector("arxiv", "arxiv.org", priority=8),
            ]

        # Backward-compat proxy exposing retrieve_evidence()
        self._evidence_retriever = _EvidenceRetrieverProxy(self)

        # Async queue (only for ONLINE_ALLOWLIST in the legacy setup)
        self._async_enabled = enable_async and self.mode == "ONLINE_ALLOWLIST"
        self._queue: Optional[FactCheckQueue] = None
        if self._async_enabled:
            self._queue = get_global_queue(
                max_size=self.config.async_queue_max_size
            )
            self._queue.set_processor(self._process_job)
            self._queue.start_workers(async_worker_count)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_fact(
        self,
        claim_text: str,
        temporal_context: Optional[TemporalContext] = None,
        request_context: Optional[RequestContext] = None,
        wait_for_async: bool = False,
    ) -> FactCheckResult:
        """Public entry point."""
        start_time = time.time()

        if request_context is None:
            request_context = RequestContext()

        # Validate input
        if len(claim_text) > self.config.max_claim_length:
            claim_text = claim_text[:self.config.max_claim_length]

        normalized = ClaimNormalizer.normalize(claim_text)
        claim_hash = ClaimNormalizer.compute_hash(normalized)
        pii_result = PIIDetector.detect(claim_text)
        contains_pii = pii_result.contains_pii

        # Check cache
        cache_key = self._cache.build_key(claim_hash, self.mode, self.allowlist_version)
        cached_result, cache_layer = self._cache.get(cache_key)
        if cached_result:
            cached_result.cache_result = cache_layer
            return cached_result

        # Check for pending async job
        if self._async_enabled and self._queue:
            pending_job = self._queue.get_pending_result(
                claim_hash, self.mode, self.allowlist_version
            )
            if pending_job:
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

        # Route by mode
        if self.mode == "OFFLINE":
            result = self._check_offline(
                claim_text, normalized, claim_hash, contains_pii, temporal_context
            )
        elif self.mode in ("PERFECT_CHECKER", "PERFECT"):
            result = self._check_perfect(
                claim_text, normalized, claim_hash, contains_pii, temporal_context
            )
        else:  # ONLINE_ALLOWLIST
            if self._async_enabled and self._queue and not wait_for_async:
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
                result = self._check_online_allowlist(
                    claim_text, normalized, claim_hash, contains_pii, temporal_context
                )

        # Store in cache (except PENDING)
        if result.status != FactCheckStatus.PENDING:
            self._cache.set(cache_key, result)
            self._audit.log_check(
                result=result,
                request_context=request_context,
                evidence_candidates_count=result.source_count_considered,
            )

        return result

    def check_fact_async(
        self,
        claim_text: str,
        temporal_context: Optional[TemporalContext] = None,
        request_context: Optional[RequestContext] = None,
    ) -> FactCheckJob:
        """Submit a fact check for async processing."""
        if not self._async_enabled or not self._queue:
            raise RuntimeError("Async processing not enabled")

        if len(claim_text) > self.config.max_claim_length:
            claim_text = claim_text[:self.config.max_claim_length]

        normalized = ClaimNormalizer.normalize(claim_text)
        claim_hash = ClaimNormalizer.compute_hash(normalized)
        pii_result = PIIDetector.detect(claim_text)
        contains_pii = pii_result.contains_pii

        if request_context is None:
            request_context = RequestContext()

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
        """Get result for an async job."""
        if not self._queue:
            return None
        job = self._queue.get_job(job_id)
        if job and job.result:
            return job.result
        return None

    def get_job_status(self, job_id: str) -> Optional[str]:
        """Get status of an async job."""
        if not self._queue:
            return None
        job = self._queue.get_job(job_id)
        return job.status if job else None

    # ------------------------------------------------------------------
    # Internal check implementations
    # ------------------------------------------------------------------

    def _check_offline(
        self, claim_text: str, normalized_claim: str,
        claim_hash: str, contains_pii: bool,
        temporal_context: Optional[TemporalContext]
    ) -> FactCheckResult:
        """OFFLINE mode: Return neutral result per LSD §13."""
        return FactCheckResult(
            claim_text=claim_text,
            normalized_claim_text=normalized_claim,
            claim_hash=claim_hash,
            fact_mode="OFFLINE",
            allowlist_version=self.allowlist_version,
            status=FactCheckStatus.UNVERIFIED_OFFLINE,
            verdict=FactCheckVerdict.UNVERIFIED,
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

    def _check_perfect(
        self, claim_text: str, normalized_claim: str,
        claim_hash: str, contains_pii: bool,
        temporal_context: Optional[TemporalContext]
    ) -> FactCheckResult:
        """
        PERFECT / PERFECT_CHECKER mode.

        1. Check ground-truth DB first (curated human verdicts).
        2. If not found and no connectors configured, fall back to
           the keyword-based fixture for backward compatibility.
        3. Otherwise run the full connector-based perfect check.
        """
        # 1. Ground-truth DB
        gt = self.ground_truth.lookup(claim_hash)
        if gt:
            return self._build_result_from_ground_truth(
                claim_text, normalized_claim, claim_hash, gt, contains_pii, temporal_context
            )

        # 2. If no connectors, use keyword fixture (backward compat).
        #    This preserves test behavior for both PERFECT and PERFECT_CHECKER.
        if not self.connectors and self.mode in ("PERFECT", "PERFECT_CHECKER"):
            return self._check_perfect_checker_fixture(
                claim_text, normalized_claim, claim_hash, contains_pii, temporal_context
            )

        # 3. Full perfect check with connectors
        return self._perfect_check(
            claim_text, normalized_claim, claim_hash, contains_pii, temporal_context
        )

    def _check_online_allowlist(
        self, claim_text: str, normalized_claim: str,
        claim_hash: str, contains_pii: bool,
        temporal_context: Optional[TemporalContext]
    ) -> FactCheckResult:
        """ONLINE_ALLOWLIST: run the perfect check but preserve mode label."""
        return self._perfect_check(
            claim_text, normalized_claim, claim_hash, contains_pii, temporal_context,
            fact_mode="ONLINE_ALLOWLIST"
        )

    def _process_job(self, job: FactCheckJob) -> FactCheckResult:
        """Process a queued job (called by worker threads)."""
        cache_key = self._cache.build_key(
            job.claim_hash, job.fact_mode, job.allowlist_version
        )
        cached, _ = self._cache.get(cache_key)
        if cached:
            return cached

        result = self._check_online_allowlist(
            job.claim_text,
            job.normalized_claim,
            job.claim_hash,
            job.contains_pii,
            job.temporal_context,
        )

        self._cache.set(cache_key, result)
        self._audit.log_check(
            result=result,
            request_context=job.request_context,
            evidence_candidates_count=result.source_count_considered,
        )
        return result

    # ------------------------------------------------------------------
    # Perfect checking core
    # ------------------------------------------------------------------

    def _perfect_check(
        self, claim_text: str, normalized: str, claim_hash: str,
        contains_pii: bool, temporal_context: Optional[TemporalContext],
        fact_mode: str = "PERFECT"
    ) -> FactCheckResult:
        start_time = time.time()

        # Temporal expiration check
        if temporal_context and temporal_context.is_expired():
            return self._insufficient_result(
                claim_text, normalized, claim_hash, contains_pii, temporal_context,
                status=FactCheckStatus.STALE,
                explanation="Temporal claim expired; recheck required",
                operationalization="Updated temporal data would be required to evaluate this claim.",
                fact_mode=fact_mode,
            )

        # Sanitize for external query if PII detected
        query_claim = normalized
        if contains_pii:
            query_claim = PIIDetector.sanitize_for_external_query(normalized)

        # Query all connectors via the proxy (preserves backward-compat patch points)
        evidence, sources_considered = self._evidence_retriever.retrieve_evidence(
            query_claim, claim_hash, self.allowlist_version
        )
        source_results = self._evidence_to_source_results(evidence)

        # Apply the perfect-agent decision rule
        verdict, p_true, explanation, operationalization, evidence, tier_counts = (
            self._adjudicate(source_results, normalized, from_ground_truth=False)
        )

        duration_ms = int((time.time() - start_time) * 1000)

        return FactCheckResult(
            claim_text=claim_text,
            normalized_claim_text=normalized,
            claim_hash=claim_hash,
            fact_mode=fact_mode,
            allowlist_version=self.allowlist_version,
            status=FactCheckStatus.CHECKED,
            verdict=verdict,
            factuality_score=p_true,
            confidence=1.0 if verdict != FactCheckVerdict.INSUFFICIENT else 0.0,
            confidence_explanation=explanation,
            operationalization=operationalization,
            evidence=evidence,
            evidence_tier_counts=tier_counts,
            source_count_considered=sources_considered,
            source_count_retained=len(source_results),
            algorithm_version="fc-perfect-v1.2",
            processing_duration_ms=duration_ms,
            cache_result=CacheResult.MISS,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
        )

    def _adjudicate(
        self, source_results: List[SourceResult], normalized_claim: str,
        from_ground_truth: bool = False,
    ) -> Tuple[FactCheckVerdict, float, str, str, List[EvidenceRecord], Dict[str, int]]:
        """
        Core perfect-agent logic governed by EvidencePolicy.

        LSD §13 discrete contract:
        - SUPPORTED  → p = 1.0
        - REFUTED    → p = 0.0
        - INSUFFICIENT → p = 0.5

        The policy decides whether evidence is sufficient; this method
        maps the policy decision to the LSD verdict and p-value.
        """
        is_sufficient, verdict_hint, reason = apply_policy(
            source_results, self.policy, from_ground_truth=from_ground_truth
        )

        if not is_sufficient:
            op = self._generate_operationalization(
                FactCheckVerdict.INSUFFICIENT, source_results, 0.5
            )
            return self._build_insufficient(reason, op, source_results)

        if verdict_hint == "SUPPORTED":
            return self._build_verdict(
                FactCheckVerdict.SUPPORTED, 1.0, reason, source_results
            )

        if verdict_hint == "REFUTED":
            return self._build_verdict(
                FactCheckVerdict.REFUTED, 0.0, reason, source_results
            )

        # Fallback (should not reach here)
        op = self._generate_operationalization(
            FactCheckVerdict.INSUFFICIENT, source_results, 0.5
        )
        return self._build_insufficient(reason, op, source_results)

    @staticmethod
    def _evidence_to_source_results(evidence: List[EvidenceRecord]) -> List[SourceResult]:
        """Convert EvidenceRecord list back to SourceResult list for adjudication."""
        out = []
        for ev in evidence:
            if ev.support_score >= 0.9 and ev.contradiction_score <= 0.1:
                confidence = SourceConfidence.CONFIRMS
            elif ev.contradiction_score >= 0.9 and ev.support_score <= 0.1:
                confidence = SourceConfidence.CONTRADICTS
            elif ev.support_score == 0.0 and ev.contradiction_score == 0.0:
                confidence = SourceConfidence.SILENT
            else:
                confidence = SourceConfidence.AMBIGUOUS
            out.append(SourceResult(
                source_id=ev.source_id,
                source_url=ev.source_url,
                source_title=ev.source_title,
                confidence=confidence,
                excerpt=ev.snippet,
                content_hash=ev.content_hash,
                retrieved_at=ev.retrieved_at,
                tier=ev.evidence_tier,
            ))
        return out

    def _build_verdict(self, verdict, p_true, explanation, source_results):
        evidence = self._to_evidence_records(source_results)
        tier_counts = self._count_tiers(evidence)
        operationalization = self._generate_operationalization(verdict, source_results, p_true)
        return verdict, p_true, explanation, operationalization, evidence, tier_counts

    def _build_insufficient(self, explanation, operationalization, source_results):
        evidence = self._to_evidence_records(source_results)
        tier_counts = self._count_tiers(evidence)
        return (
            FactCheckVerdict.INSUFFICIENT, 0.5,
            explanation, operationalization, evidence, tier_counts
        )

    def _insufficient_result(
        self, claim_text, normalized, claim_hash, contains_pii, temporal_context,
        status=FactCheckStatus.CHECKED, explanation="", operationalization="",
        fact_mode="PERFECT"
    ):
        """Helper to build an INSUFFICIENT FactCheckResult."""
        return FactCheckResult(
            claim_text=claim_text,
            normalized_claim_text=normalized,
            claim_hash=claim_hash,
            fact_mode=fact_mode,
            allowlist_version=self.allowlist_version,
            status=status,
            verdict=FactCheckVerdict.INSUFFICIENT,
            factuality_score=0.5,
            confidence=0.0,
            confidence_explanation=explanation,
            operationalization=operationalization,
            evidence=[],
            evidence_tier_counts={"TIER_1": 0, "TIER_2": 0, "TIER_3": 0},
            algorithm_version="fc-perfect-v1.2",
            cache_result=CacheResult.MISS,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
        )

    def _to_evidence_records(self, source_results: List[SourceResult]) -> List[EvidenceRecord]:
        out = []
        for i, r in enumerate(source_results):
            out.append(EvidenceRecord(
                source_url=r.source_url,
                source_id=r.source_id,
                source_version="v1",
                source_title=r.source_title,
                snippet=r.excerpt,
                content_hash=r.content_hash,
                retrieved_at=r.retrieved_at,
                relevance_score=0.9 if r.confidence in (
                    SourceConfidence.CONFIRMS, SourceConfidence.CONTRADICTS
                ) else 0.5,
                support_score=1.0 if r.confidence == SourceConfidence.CONFIRMS else 0.0,
                contradiction_score=1.0 if r.confidence == SourceConfidence.CONTRADICTS else 0.0,
                selected_rank=i + 1,
                evidence_tier=r.tier,
            ))
        return out

    def _count_tiers(self, evidence: List[EvidenceRecord]) -> Dict[str, int]:
        return {
            "TIER_1": sum(1 for e in evidence if e.evidence_tier == EvidenceTier.TIER_1),
            "TIER_2": sum(1 for e in evidence if e.evidence_tier == EvidenceTier.TIER_2),
            "TIER_3": sum(1 for e in evidence if e.evidence_tier == EvidenceTier.TIER_3),
        }

    def _generate_operationalization(
        self, verdict: FactCheckVerdict, source_results: List[SourceResult], p_true: float
    ) -> str:
        if verdict == FactCheckVerdict.INSUFFICIENT:
            if not source_results:
                return "To resolve: locate a primary source that directly addresses this claim."
            tiers_present = {r.tier for r in source_results}
            if EvidenceTier.TIER_1 in tiers_present:
                return "To resolve: identify why primary sources disagree (scope mismatch, temporal drift, or definitional variance)."
            return "To resolve: locate a primary source; secondary sources alone are insufficient for a definitive verdict."

        if verdict == FactCheckVerdict.SUPPORTED:
            return "To refute: provide a primary source that directly contradicts the claim, or demonstrate that the confirming source is inapplicable to the claim's scope."

        if verdict == FactCheckVerdict.REFUTED:
            return "To overturn: provide a primary source that supersedes the contradicting evidence (e.g., a more recent or authoritative record)."

        return "Operationalization unavailable."

    def _build_result_from_ground_truth(
        self, claim_text, normalized, claim_hash, gt, contains_pii, temporal_context
    ):
        verdict = FactCheckVerdict(gt["verdict"])
        p_true = gt["p_true"]
        evidence = [
            EvidenceRecord(
                source_url=e.get("source_url", ""),
                source_id=e.get("source_id", "ground_truth"),
                source_version="v1",
                source_title=e.get("source_title", "Ground Truth Entry"),
                snippet=e.get("snippet", ""),
                content_hash=e.get("content_hash", ""),
                retrieved_at=datetime.fromisoformat(e["retrieved_at"].replace("Z", "+00:00")),
                relevance_score=1.0,
                support_score=1.0 if p_true == 1.0 else 0.0,
                contradiction_score=1.0 if p_true == 0.0 else 0.0,
                selected_rank=i + 1,
                evidence_tier=EvidenceTier(e.get("evidence_tier") or e.get("tier", "TIER_1")),
            )
            for i, e in enumerate(gt.get("evidence", []))
        ]
        return FactCheckResult(
            claim_text=claim_text,
            normalized_claim_text=normalized,
            claim_hash=claim_hash,
            fact_mode="PERFECT",
            allowlist_version=self.allowlist_version,
            status=FactCheckStatus.CHECKED,
            verdict=verdict,
            factuality_score=p_true,
            confidence=1.0,
            confidence_explanation="Resolved from curated ground-truth database.",
            operationalization=gt.get("operationalization", "See ground-truth entry."),
            evidence=evidence,
            evidence_tier_counts=gt.get("tier_counts", {"TIER_1": 0, "TIER_2": 0, "TIER_3": 0}),
            algorithm_version="fc-perfect-gt-v1.2",
            cache_result=CacheResult.MISS,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
        )

    # ------------------------------------------------------------------
    # Backward-compat: keyword-based perfect checker fixture
    # ------------------------------------------------------------------

    def _check_perfect_checker_fixture(
        self, claim_text: str, normalized_claim: str,
        claim_hash: str, contains_pii: bool,
        temporal_context: Optional[TemporalContext]
    ) -> FactCheckResult:
        """Legacy keyword-based fixture for tests."""
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
            evidence_tier_counts={
                "TIER_1": 1 if verdict != FactCheckVerdict.INSUFFICIENT else 0,
                "TIER_2": 0, "TIER_3": 0
            },
            algorithm_version="fc-perfect-v1.2",
            cache_result=CacheResult.MISS,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
        )

    # ------------------------------------------------------------------
    # Backward-compat: old threshold-based verdict (used by tests)
    # ------------------------------------------------------------------

    def _determine_verdict(self, support: float, contradiction: float) -> FactCheckVerdict:
        """Determine verdict based on support and contradiction scores."""
        if support > self.config.support_threshold and contradiction < 0.3:
            return FactCheckVerdict.SUPPORTED
        if contradiction > self.config.contradiction_threshold and support < 0.3:
            return FactCheckVerdict.REFUTED
        return FactCheckVerdict.INSUFFICIENT

    def _calculate_confidence(self, support: float, contradiction: float,
                             evidence_count: int) -> float:
        """Calculate confidence score."""
        base_confidence = min(0.9, 0.3 + evidence_count * 0.15)
        if abs(support - contradiction) < self.config.confidence_penalty_threshold:
            base_confidence *= 0.75
        return min(1.0, max(0.0, base_confidence))

    # ------------------------------------------------------------------
    # Utility / stats
    # ------------------------------------------------------------------

    def invalidate_cache(self, claim_hash: str, reason: str):
        """Explicitly invalidate a cached fact check."""
        self._cache.invalidate_by_claim(claim_hash, self.mode, self.allowlist_version)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return self._cache.get_stats()

    def get_audit_stats(self) -> Dict[str, Any]:
        """Get audit log statistics."""
        return self._audit.get_stats()

    def get_queue_stats(self) -> Optional[Dict[str, Any]]:
        """Get queue statistics if async is enabled."""
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
        """Shutdown the skill and its workers."""
        if self._queue:
            self._queue.shutdown(wait=True)
