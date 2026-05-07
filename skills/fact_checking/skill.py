"""
Fact checking skill implementing the frozen v1 contract.

V1 supports only atomic empirical identity/date/status/location claims about
notable public entities that have an authoritative structured source path.
Unsupported, compound, badly scoped, conflicting, stale, or otherwise
non-decisive claims must return INSUFFICIENT rather than a heuristic verdict.
"""

import hashlib
import json
import time
from dataclasses import asdict
from typing import Any

from .audit import AuditLogger
from .cache import MultiLayerCache
from .config import FactCheckConfig, get_config
from .connectors import GroundTruthDB, SimulatedSourceConnector, SourceConnector
from .decomposer import ClaimDecomposer
from .fc_queue import FactCheckQueue
from .models import (
    CacheResult,
    EvidenceRecord,
    EvidenceTier,
    FactCheckJob,
    FactCheckResult,
    FactCheckStatus,
    FactCheckVerdict,
    PlannerDecision,
    RequestContext,
    SourceConfidence,
    SourceResult,
    Subclaim,
    TemporalContext,
)
from .normalization import ClaimNormalizer
from .pii import PIIDetector
from .planner import ConnectorPlanner
from .policy import EvidencePolicy, apply_policy, default_policy, strict_policy


class _EvidenceRetrieverProxy:
    """
    Backward-compatible proxy that exposes the old retrieve_evidence() hook.

    Tests patch this object directly, so it remains part of the skill surface
    even though the stricter PERFECT path now uses planner-driven connector
    selection internally.
    """

    def __init__(self, skill: "FactCheckingSkill"):
        self._skill = skill

    def retrieve_evidence(
        self,
        normalized_claim: str,
        claim_hash: str,
        allowlist_version: str,
    ) -> tuple[list[EvidenceRecord], int, list[str]]:
        source_results, sources_considered, connector_errors = self._skill._query_connectors(
            normalized_claim,
            claim_hash,
            self._skill.connectors,
        )
        return (
            self._skill._to_evidence_records(source_results),
            sources_considered,
            connector_errors,
        )


class FactCheckingSkill:
    """
    Deterministic fact checker for the debate system.

    Frozen mode semantics:
    - OFFLINE: always neutral, no retrieval, p_true=0.5.
    - ONLINE_ALLOWLIST: experimental async-capable integration mode that may use
      simulated or non-production connectors.
    - PERFECT_CHECKER: deterministic fixture/test mode for controlled connectors,
      ground truth, and legacy keyword fixtures.
    - PERFECT: strict production mode for the narrow v1 supported claim family
      only; unsupported or non-decisive claims remain INSUFFICIENT.
    """

    def __init__(
        self,
        mode: str = "OFFLINE",
        allowlist_version: str = "v1",
        config: FactCheckConfig | None = None,
        source_registry: Any | None = None,  # kept for backward compat
        enable_async: bool = True,
        async_worker_count: int = 3,
        connectors: list[SourceConnector] | None = None,
        ground_truth_db: GroundTruthDB | None = None,
        cache_ttl_seconds: int | None = None,
        policy: EvidencePolicy | None = None,
        v15_connectors: Any | None = None,
    ):
        del source_registry

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

        ttl = cache_ttl_seconds or self.config.cache_ttl_seconds
        self._cache = MultiLayerCache(ttl_seconds=ttl)
        self._audit = AuditLogger()

        self.policy = policy or (strict_policy() if self.mode == "PERFECT" else default_policy())
        self.ground_truth = ground_truth_db or GroundTruthDB()

        self.connectors: list[SourceConnector] = connectors or []
        if self.mode == "ONLINE_ALLOWLIST" and not self.connectors:
            self.connectors = [
                SimulatedSourceConnector("wikidata_sim", "wikidata.org", priority=10),
                SimulatedSourceConnector("arxiv_sim", "arxiv.org", priority=8),
            ]

        self._cache_runtime_signature = self._build_runtime_signature()
        self._evidence_retriever = _EvidenceRetrieverProxy(self)

        self._async_enabled = enable_async and self.mode == "ONLINE_ALLOWLIST"
        self._queue: FactCheckQueue | None = None
        if self._async_enabled:
            self._queue = FactCheckQueue(
                max_size=self.config.async_queue_max_size,
                label=f"{self.mode.lower()}-{id(self) & 0xffff:x}",
            )
            self._queue.set_processor(self._process_job)
            self._queue.start_workers(async_worker_count)

        # v1.5 delegation path
        self._v15_skill: Any | None = None
        if v15_connectors is not None:
            from .v15_skill import V15FactCheckingSkill

            self._v15_skill = V15FactCheckingSkill(
                mode=self.mode,
                allowlist_version=self.allowlist_version,
                enable_async=False,  # async handled at v1 layer
                v15_connectors=v15_connectors,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_fact(
        self,
        claim_text: str,
        temporal_context: TemporalContext | None = None,
        request_context: RequestContext | None = None,
        wait_for_async: bool = False,
    ) -> FactCheckResult:
        start_time = time.time()
        request_context = request_context or RequestContext()

        claim_truncated = False
        if len(claim_text) > self.config.max_claim_length:
            claim_text = claim_text[: self.config.max_claim_length]
            claim_truncated = True

        normalized = ClaimNormalizer.normalize(claim_text)
        claim_hash = ClaimNormalizer.compute_hash(normalized)
        contains_pii = PIIDetector.detect(claim_text).contains_pii
        cache_key = self._build_cache_key(claim_hash)

        cached_result, cache_layer = self._cache.get(cache_key)
        if cached_result:
            cached_result.cache_result = cache_layer
            return cached_result

        if self._async_enabled and self._queue:
            pending_job = self._queue.get_pending_result(
                claim_hash,
                self.mode,
                self.allowlist_version,
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
                    diagnostics={"reason_code": "pending_async_job"},
                )

        # v1.5 path: delegate to V15FactCheckingSkill if available
        if self._v15_skill is not None:
            result = self._v15_skill.check_fact(
                claim_text,
                temporal_context=temporal_context,
                request_context=request_context,
            )
            # v15_skill already returns v1-compatible FactCheckResult
            if result.status != FactCheckStatus.PENDING:
                self._cache.set(cache_key, result)
                self._audit.log_check(
                    result=result,
                    request_context=request_context,
                    evidence_candidates_count=len(result.evidence),
                )
            return result

        if self.mode == "OFFLINE":
            result = self._check_offline(
                claim_text,
                normalized,
                claim_hash,
                contains_pii,
                temporal_context,
                claim_truncated=claim_truncated,
            )
        elif self.mode in ("PERFECT_CHECKER", "PERFECT"):
            result = self._check_perfect(
                claim_text,
                normalized,
                claim_hash,
                contains_pii,
                temporal_context,
                claim_truncated=claim_truncated,
            )
        else:
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
                    diagnostics={"reason_code": "queued_async_job"},
                )
            else:
                result = self._check_online_allowlist(
                    claim_text,
                    normalized,
                    claim_hash,
                    contains_pii,
                    temporal_context,
                    claim_truncated=claim_truncated,
                )

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
        temporal_context: TemporalContext | None = None,
        request_context: RequestContext | None = None,
    ) -> FactCheckJob:
        if not self._async_enabled or not self._queue:
            raise RuntimeError("Async processing not enabled")

        if len(claim_text) > self.config.max_claim_length:
            claim_text = claim_text[: self.config.max_claim_length]

        normalized = ClaimNormalizer.normalize(claim_text)
        claim_hash = ClaimNormalizer.compute_hash(normalized)
        contains_pii = PIIDetector.detect(claim_text).contains_pii

        return self._queue.submit(
            claim_text=claim_text,
            normalized_claim=normalized,
            claim_hash=claim_hash,
            fact_mode=self.mode,
            allowlist_version=self.allowlist_version,
            temporal_context=temporal_context,
            request_context=request_context or RequestContext(),
            contains_pii=contains_pii,
        )

    def get_job_result(self, job_id: str) -> FactCheckResult | None:
        if not self._queue:
            return None
        job = self._queue.get_job(job_id)
        return job.result if job and job.result else None

    def get_job_status(self, job_id: str) -> str | None:
        if not self._queue:
            return None
        job = self._queue.get_job(job_id)
        return job.status if job else None

    # ------------------------------------------------------------------
    # Internal check implementations
    # ------------------------------------------------------------------

    def _check_offline(
        self,
        claim_text: str,
        normalized_claim: str,
        claim_hash: str,
        contains_pii: bool,
        temporal_context: TemporalContext | None,
        claim_truncated: bool = False,
    ) -> FactCheckResult:
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
            diagnostics={"reason_code": "offline_mode", "claim_truncated": claim_truncated},
        )

    def _check_perfect(
        self,
        claim_text: str,
        normalized_claim: str,
        claim_hash: str,
        contains_pii: bool,
        temporal_context: TemporalContext | None,
        claim_truncated: bool = False,
    ) -> FactCheckResult:
        ground_truth_entry = self.ground_truth.lookup(claim_hash)

        if (
            ground_truth_entry
            and str(ground_truth_entry.get("verdict")) == FactCheckVerdict.INSUFFICIENT.value
        ):
            return self._build_result_from_ground_truth(
                claim_text,
                normalized_claim,
                claim_hash,
                ground_truth_entry,
                contains_pii,
                temporal_context,
                fact_mode=self.mode,
            )

        if not self.connectors and self.mode == "PERFECT_CHECKER" and ground_truth_entry is None:
            return self._check_perfect_checker_fixture(
                claim_text,
                normalized_claim,
                claim_hash,
                contains_pii,
                temporal_context,
            )

        if not self.connectors and self.mode == "PERFECT" and ground_truth_entry is None:
            return self._insufficient_result(
                claim_text,
                normalized_claim,
                claim_hash,
                contains_pii,
                temporal_context,
                explanation="No Tier-1 connector is configured for PERFECT mode.",
                operationalization="Configure a Tier-1 connector for the supported v1 claim family before enabling PERFECT mode.",
                fact_mode="PERFECT",
                diagnostics={"reason_code": "no_tier1_source"},
            )

        return self._perfect_check(
            claim_text,
            normalized_claim,
            claim_hash,
            contains_pii,
            temporal_context,
            fact_mode=self.mode,
            ground_truth_entry=ground_truth_entry,
            enforce_contract=self.mode == "PERFECT",
            claim_truncated=claim_truncated,
        )

    def _check_online_allowlist(
        self,
        claim_text: str,
        normalized_claim: str,
        claim_hash: str,
        contains_pii: bool,
        temporal_context: TemporalContext | None,
        claim_truncated: bool = False,
    ) -> FactCheckResult:
        return self._perfect_check(
            claim_text,
            normalized_claim,
            claim_hash,
            contains_pii,
            temporal_context,
            fact_mode="ONLINE_ALLOWLIST",
            ground_truth_entry=None,
            enforce_contract=False,
            claim_truncated=claim_truncated,
        )

    def _process_job(self, job: FactCheckJob) -> FactCheckResult:
        cache_key = self._build_cache_key(job.claim_hash, fact_mode=job.fact_mode)
        cached, _ = self._cache.get(cache_key)
        if cached:
            return cached

        if self._v15_skill is not None:
            result = self._v15_skill.check_fact(
                job.claim_text,
                temporal_context=job.temporal_context,
                request_context=job.request_context,
            )
            self._cache.set(cache_key, result)
            self._audit.log_check(
                result=result,
                request_context=job.request_context,
                evidence_candidates_count=len(result.evidence),
            )
            return result

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
        self,
        claim_text: str,
        normalized: str,
        claim_hash: str,
        contains_pii: bool,
        temporal_context: TemporalContext | None,
        fact_mode: str,
        ground_truth_entry: dict[str, Any] | None,
        enforce_contract: bool,
        claim_truncated: bool = False,
    ) -> FactCheckResult:
        start_time = time.time()

        if temporal_context and temporal_context.is_expired():
            return self._insufficient_result(
                claim_text,
                normalized,
                claim_hash,
                contains_pii,
                temporal_context,
                status=FactCheckStatus.STALE,
                explanation="Temporal claim expired; recheck required.",
                operationalization="Updated temporal data would be required to evaluate this claim.",
                fact_mode=fact_mode,
                diagnostics={"reason_code": "temporal_staleness"},
            )

        query_claim = normalized
        if contains_pii:
            query_claim = PIIDetector.sanitize_for_external_query(normalized)

        subclaims = ClaimDecomposer.decompose(query_claim, source_fact_id=claim_hash)
        decisions = ConnectorPlanner.plan_claim(subclaims, self.connectors, fact_mode)
        diagnostics = self._build_diagnostics(subclaims, decisions, fact_mode, claim_truncated)

        ground_truth_results: list[SourceResult] = []
        if ground_truth_entry and str(ground_truth_entry.get("verdict")) in {
            FactCheckVerdict.SUPPORTED.value,
            FactCheckVerdict.REFUTED.value,
        }:
            ground_truth_results = GroundTruthDB.entry_to_source_results(ground_truth_entry)
            if ground_truth_results:
                gt_verdict = self._adjudicate(
                    ground_truth_results,
                    normalized,
                    from_ground_truth=True,
                )
                if gt_verdict[0] != FactCheckVerdict.INSUFFICIENT or not self.connectors:
                    diagnostics["reason_code"] = "ground_truth_resolution"
                    diagnostics["ground_truth"] = True
                    return self._finalize_result(
                        claim_text=claim_text,
                        normalized=normalized,
                        claim_hash=claim_hash,
                        fact_mode=fact_mode,
                        contains_pii=contains_pii,
                        temporal_context=temporal_context,
                        verdict_bundle=gt_verdict,
                        source_count_considered=len(ground_truth_results),
                        source_count_retained=len(ground_truth_results),
                        duration_ms=int((time.time() - start_time) * 1000),
                        diagnostics=diagnostics,
                        algorithm_version="fc-perfect-gt-v1.2",
                    )

        if enforce_contract and len(subclaims) > 1:
            diagnostics["reason_code"] = "compound_claim"
            return self._insufficient_result(
                claim_text,
                normalized,
                claim_hash,
                contains_pii,
                temporal_context,
                explanation="Compound claims are outside the supported v1 contract.",
                operationalization="Split the claim into atomic subclaims and resolve each independently.",
                fact_mode=fact_mode,
                diagnostics=diagnostics,
            )

        if enforce_contract:
            unsupported = next((decision for decision in decisions if not decision.supported), None)
            if unsupported is not None:
                diagnostics["reason_code"] = unsupported.reason_code
                return self._insufficient_result(
                    claim_text,
                    normalized,
                    claim_hash,
                    contains_pii,
                    temporal_context,
                    explanation=unsupported.reason,
                    operationalization="Reframe the claim as an atomic identity/date/status/location claim about a notable public entity.",
                    fact_mode=fact_mode,
                    diagnostics=diagnostics,
                )

        connectors_to_query = self.connectors
        if enforce_contract and decisions:
            connector_path = decisions[0].connector_path
            if connector_path:
                allowed = set(connector_path)
                connectors_to_query = [
                    connector for connector in self.connectors if connector.source_id in allowed
                ]

        if not enforce_contract and fact_mode == "ONLINE_ALLOWLIST":
            evidence, sources_considered, connector_errors = (
                self._evidence_retriever.retrieve_evidence(
                    query_claim,
                    claim_hash,
                    self.allowlist_version,
                )
            )
            source_results = self._evidence_to_source_results(evidence)
            diagnostics["connector_errors"] = connector_errors
        else:
            source_results, sources_considered, connector_errors = self._query_connectors(
                query_claim,
                claim_hash,
                connectors_to_query,
            )
            if connector_errors:
                diagnostics["connector_errors"] = connector_errors
        combined_results = ground_truth_results + source_results
        verdict_bundle = self._adjudicate(
            combined_results,
            normalized,
            from_ground_truth=bool(ground_truth_results),
        )

        return self._finalize_result(
            claim_text=claim_text,
            normalized=normalized,
            claim_hash=claim_hash,
            fact_mode=fact_mode,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
            verdict_bundle=verdict_bundle,
            source_count_considered=sources_considered + len(ground_truth_results),
            source_count_retained=len(combined_results),
            duration_ms=int((time.time() - start_time) * 1000),
            diagnostics=diagnostics,
            algorithm_version="fc-perfect-v1.2",
        )

    def _build_runtime_signature(self) -> str:
        payload = {
            "connectors": [
                {
                    "source_id": connector.source_id,
                    "tier": getattr(connector, "tier", None).value
                    if getattr(connector, "tier", None) is not None
                    else None,
                    "class": connector.__class__.__name__,
                }
                for connector in self.connectors
            ],
            "policy": asdict(self.policy),
            "ground_truth_path": getattr(self.ground_truth, "db_path", None),
            "mode": self.mode,
            "allowlist_version": self.allowlist_version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]

    def _build_cache_key(
        self,
        claim_hash: str,
        fact_mode: str | None = None,
        allowlist_version: str | None = None,
    ) -> str:
        scoped_claim_hash = f"{claim_hash}:{self._cache_runtime_signature}"
        return self._cache.build_key(
            scoped_claim_hash,
            fact_mode or self.mode,
            allowlist_version or self.allowlist_version,
        )

    def _query_connectors(
        self,
        normalized_claim: str,
        claim_hash: str,
        connectors: list[SourceConnector],
    ) -> tuple[list[SourceResult], int, list[str]]:
        results: list[SourceResult] = []
        connector_errors: list[str] = []
        for connector in connectors:
            try:
                source_result = connector.query(normalized_claim, claim_hash)
            except Exception as exc:
                error_msg = f"Connector {connector.source_id} failed: {exc}"
                print(error_msg)
                connector_errors.append(error_msg)
                continue
            if source_result:
                results.append(source_result)
        return results, len(connectors), connector_errors

    def _build_diagnostics(
        self,
        subclaims: list[Subclaim],
        decisions: list[PlannerDecision],
        fact_mode: str,
        claim_truncated: bool = False,
    ) -> dict[str, Any]:
        return {
            "fact_mode": fact_mode,
            "subclaim_count": len(subclaims),
            "claim_families": [subclaim.claim_family for subclaim in subclaims],
            "connector_path": decisions[0].connector_path if decisions else [],
            "unsupported_family": any(not decision.supported for decision in decisions),
            "compound": len(subclaims) > 1,
            "reason_code": decisions[0].reason_code if decisions else "no_planner_decision",
            "claim_truncated": claim_truncated,
        }

    def _finalize_result(
        self,
        claim_text: str,
        normalized: str,
        claim_hash: str,
        fact_mode: str,
        contains_pii: bool,
        temporal_context: TemporalContext | None,
        verdict_bundle: tuple[
            FactCheckVerdict, float, str, str, list[EvidenceRecord], dict[str, int]
        ],
        source_count_considered: int,
        source_count_retained: int,
        duration_ms: int,
        diagnostics: dict[str, Any],
        algorithm_version: str,
    ) -> FactCheckResult:
        verdict, p_true, explanation, operationalization, evidence, tier_counts = verdict_bundle
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
            source_count_considered=source_count_considered,
            source_count_retained=source_count_retained,
            algorithm_version=algorithm_version,
            processing_duration_ms=duration_ms,
            cache_result=CacheResult.MISS,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
            diagnostics=diagnostics,
        )

    def _adjudicate(
        self,
        source_results: list[SourceResult],
        normalized_claim: str,
        from_ground_truth: bool = False,
    ) -> tuple[FactCheckVerdict, float, str, str, list[EvidenceRecord], dict[str, int]]:
        is_sufficient, verdict_hint, reason = apply_policy(
            source_results,
            self.policy,
            from_ground_truth=from_ground_truth,
        )

        if not is_sufficient:
            operationalization = self._generate_operationalization(
                FactCheckVerdict.INSUFFICIENT,
                source_results,
                0.5,
            )
            return self._build_insufficient(reason, operationalization, source_results)

        if verdict_hint == FactCheckVerdict.SUPPORTED.value:
            return self._build_verdict(
                FactCheckVerdict.SUPPORTED,
                1.0,
                reason,
                source_results,
            )

        if verdict_hint == FactCheckVerdict.REFUTED.value:
            return self._build_verdict(
                FactCheckVerdict.REFUTED,
                0.0,
                reason,
                source_results,
            )

        operationalization = self._generate_operationalization(
            FactCheckVerdict.INSUFFICIENT,
            source_results,
            0.5,
        )
        return self._build_insufficient(reason, operationalization, source_results)

    @staticmethod
    def _evidence_to_source_results(evidence: list[EvidenceRecord]) -> list[SourceResult]:
        source_results: list[SourceResult] = []
        for record in evidence:
            if record.support_score >= 0.9 and record.contradiction_score <= 0.1:
                confidence = SourceConfidence.CONFIRMS
            elif record.contradiction_score >= 0.9 and record.support_score <= 0.1:
                confidence = SourceConfidence.CONTRADICTS
            elif record.support_score == 0.0 and record.contradiction_score == 0.0:
                confidence = SourceConfidence.SILENT
            else:
                confidence = SourceConfidence.AMBIGUOUS
            source_results.append(
                SourceResult(
                    source_id=record.source_id,
                    source_url=record.source_url,
                    source_title=record.source_title,
                    confidence=confidence,
                    excerpt=record.snippet,
                    content_hash=record.content_hash,
                    retrieved_at=record.retrieved_at,
                    tier=record.evidence_tier,
                )
            )
        return source_results

    def _build_verdict(
        self,
        verdict: FactCheckVerdict,
        p_true: float,
        explanation: str,
        source_results: list[SourceResult],
    ) -> tuple[FactCheckVerdict, float, str, str, list[EvidenceRecord], dict[str, int]]:
        evidence = self._to_evidence_records(source_results)
        tier_counts = self._count_tiers(evidence)
        operationalization = self._generate_operationalization(verdict, source_results, p_true)
        return verdict, p_true, explanation, operationalization, evidence, tier_counts

    def _build_insufficient(
        self,
        explanation: str,
        operationalization: str,
        source_results: list[SourceResult],
    ) -> tuple[FactCheckVerdict, float, str, str, list[EvidenceRecord], dict[str, int]]:
        evidence = self._to_evidence_records(source_results)
        tier_counts = self._count_tiers(evidence)
        return (
            FactCheckVerdict.INSUFFICIENT,
            0.5,
            explanation,
            operationalization,
            evidence,
            tier_counts,
        )

    def _insufficient_result(
        self,
        claim_text: str,
        normalized: str,
        claim_hash: str,
        contains_pii: bool,
        temporal_context: TemporalContext | None,
        status: FactCheckStatus = FactCheckStatus.CHECKED,
        explanation: str = "",
        operationalization: str = "",
        fact_mode: str = "PERFECT",
        diagnostics: dict[str, Any] | None = None,
    ) -> FactCheckResult:
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
            diagnostics=diagnostics or {},
        )

    def _to_evidence_records(self, source_results: list[SourceResult]) -> list[EvidenceRecord]:
        evidence: list[EvidenceRecord] = []
        for index, result in enumerate(source_results):
            evidence.append(
                EvidenceRecord(
                    source_url=result.source_url,
                    source_id=result.source_id,
                    source_version="v1",
                    source_title=result.source_title,
                    snippet=result.excerpt,
                    content_hash=result.content_hash,
                    retrieved_at=result.retrieved_at,
                    relevance_score=0.9
                    if result.confidence
                    in (SourceConfidence.CONFIRMS, SourceConfidence.CONTRADICTS)
                    else 0.5,
                    support_score=1.0 if result.confidence == SourceConfidence.CONFIRMS else 0.0,
                    contradiction_score=1.0
                    if result.confidence == SourceConfidence.CONTRADICTS
                    else 0.0,
                    selected_rank=index + 1,
                    evidence_tier=result.tier,
                )
            )
        return evidence

    @staticmethod
    def _count_tiers(evidence: list[EvidenceRecord]) -> dict[str, int]:
        return {
            "TIER_1": sum(1 for item in evidence if item.evidence_tier == EvidenceTier.TIER_1),
            "TIER_2": sum(1 for item in evidence if item.evidence_tier == EvidenceTier.TIER_2),
            "TIER_3": sum(1 for item in evidence if item.evidence_tier == EvidenceTier.TIER_3),
        }

    def _generate_operationalization(
        self,
        verdict: FactCheckVerdict,
        source_results: list[SourceResult],
        p_true: float,
    ) -> str:
        del p_true
        if verdict == FactCheckVerdict.INSUFFICIENT:
            if not source_results:
                return "To resolve: locate a primary source that directly addresses this claim."
            tiers_present = {result.tier for result in source_results}
            if EvidenceTier.TIER_1 in tiers_present:
                return "To resolve: identify whether the mismatch is caused by time scope, geography, or definitional drift."
            return "To resolve: locate a primary source; lower-tier corroboration alone is not decisive in v1."

        if verdict == FactCheckVerdict.SUPPORTED:
            return "To refute: provide a primary source that directly contradicts the claim or shows the cited source is out of scope."

        if verdict == FactCheckVerdict.REFUTED:
            return "To overturn: provide a primary source that supersedes the contradicting record."

        return "Operationalization unavailable."

    def _build_result_from_ground_truth(
        self,
        claim_text: str,
        normalized: str,
        claim_hash: str,
        ground_truth_entry: dict[str, Any],
        contains_pii: bool,
        temporal_context: TemporalContext | None,
        fact_mode: str,
    ) -> FactCheckResult:
        verdict = FactCheckVerdict(
            ground_truth_entry.get("verdict", FactCheckVerdict.INSUFFICIENT.value)
        )
        p_true = float(ground_truth_entry.get("p_true", 0.5))
        evidence = GroundTruthDB.entry_to_evidence_records(ground_truth_entry)
        tier_counts = ground_truth_entry.get("tier_counts") or self._count_tiers(evidence)

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
            confidence_explanation="Resolved from curated ground truth.",
            operationalization=ground_truth_entry.get(
                "operationalization", "See curated ground-truth entry."
            ),
            evidence=evidence,
            evidence_tier_counts=tier_counts,
            algorithm_version="fc-perfect-gt-v1.2",
            cache_result=CacheResult.MISS,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
            diagnostics={"reason_code": "ground_truth_curated", "ground_truth": True},
        )

    # ------------------------------------------------------------------
    # Backward-compatibility helpers
    # ------------------------------------------------------------------

    def _check_perfect_checker_fixture(
        self,
        claim_text: str,
        normalized_claim: str,
        claim_hash: str,
        contains_pii: bool,
        temporal_context: TemporalContext | None,
    ) -> FactCheckResult:
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
            operationalization="A perfect-checker fixture directly determines support, refutation, or insufficiency.",
            evidence=[],
            evidence_tier_counts={
                "TIER_1": 1 if verdict != FactCheckVerdict.INSUFFICIENT else 0,
                "TIER_2": 0,
                "TIER_3": 0,
            },
            algorithm_version="fc-perfect-v1.2",
            cache_result=CacheResult.MISS,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
            diagnostics={"reason_code": "perfect_checker_fixture"},
        )

    def _determine_verdict(self, support: float, contradiction: float) -> FactCheckVerdict:
        if support > self.config.support_threshold and contradiction < 0.3:
            return FactCheckVerdict.SUPPORTED
        if contradiction > self.config.contradiction_threshold and support < 0.3:
            return FactCheckVerdict.REFUTED
        return FactCheckVerdict.INSUFFICIENT

    def _calculate_confidence(
        self, support: float, contradiction: float, evidence_count: int
    ) -> float:
        base_confidence = min(0.9, 0.3 + evidence_count * 0.15)
        if abs(support - contradiction) < self.config.confidence_penalty_threshold:
            base_confidence *= 0.75
        return min(1.0, max(0.0, base_confidence))

    # ------------------------------------------------------------------
    # Utility / stats
    # ------------------------------------------------------------------

    def invalidate_cache(self, claim_hash: str, reason: str):
        del reason
        self._cache.invalidate_by_claim(claim_hash, self.mode, self.allowlist_version)

    def get_cache_stats(self) -> dict[str, Any]:
        return self._cache.get_stats()

    def get_audit_stats(self) -> dict[str, Any]:
        return self._audit.get_stats()

    def get_queue_stats(self) -> dict[str, Any] | None:
        if not self._queue:
            return None
        stats = self._queue.get_stats()
        return {
            "queued": stats.queued,
            "processing": stats.processing,
            "completed": stats.completed,
            "failed": stats.failed,
            "total_processed": stats.total_processed,
        }

    def shutdown(self):
        if self._queue:
            self._queue.shutdown(wait=True)
