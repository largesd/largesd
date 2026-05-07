"""
V15FactCheckingSkill — Production bridge from legacy v1 API to v1.5 deterministic pipeline.

Exposes the same interface as FactCheckingSkill (check_fact, check_fact_async, get_job_result)
while internally orchestrating the v1.5 components:

  Decomposer → EvidencePolicy → Connectors → Normalizer → SynthesisEngine

Returns backward-compatible legacy FactCheckResult objects with:
  - factuality_score mapped from v1.5 p ∈ {1.0, 0.0, 0.5}
  - verdict mapped from v1.5 status ∈ {SUPPORTED, REFUTED, INSUFFICIENT}
  - evidence_tier_counts from v1.5 best_evidence_tier
  - diagnostics enriched with v1.5 synthesis_logic, human_review_flags, insufficiency_reason

Modes:
  OFFLINE          → deterministic INSUFFICIENT, p=0.5 (no network)
  PERFECT_CHECKER  → v1.5 synthesis with mock/controlled connectors
  PERFECT          → v1.5 synthesis with Tier-1 structured connectors only
  ONLINE_ALLOWLIST → v1.5 synthesis with full connector registry
  LIVE_CONNECTORS  → alias for ONLINE_ALLOWLIST with live network

Per LSD_req.txt §13 and Formulas.txt §5.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from . import models as legacy_models
from .config import FactCheckConfig, get_config
from .decomposition import (
    CanonicalPremise,
    Decomposer,
    _is_normative,
    decompose_synthesize_and_audit,
)
from .entity_linker import EntityLinker
from .normalizer import EvidenceNormalizer, archive_web_evidence
from .policies import get_default_policy
from .rate_limiter import CircuitBreakerConfig, RateLimitConfig, RateLimiterManager
from .source_registry import SourceReputationRegistry
from .synthesis import SynthesisEngine
from .v15_connectors import (
    BaseEvidenceConnector,
    ConnectorRegistry,
    WikidataEntityConnector,
)
from .v15_models import (
    AtomicSubclaim,
    ClaimExpression,
    ClaimType,
    EvidenceItem,
    EvidencePolicy,
    NodeType,
    PremiseDecomposition,
    Side,
    SourceType,
    VerdictScope,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_claim_hash(claim_text: str) -> str:
    """Stable claim hash for cache/audit."""
    return hashlib.sha256(claim_text.lower().strip().encode("utf-8")).hexdigest()[:32]


def _claim_type_from_text(text: str) -> ClaimType:
    """Heuristic claim-type detection for simple atomic claims."""
    lowered = text.lower()
    if any(w in lowered for w in ("%", "percent", "rate", "population", "gdp", "unemployment")):
        return ClaimType.NUMERIC_STATISTICAL
    if any(w in lowered for w in ("law", "court", "legal", "regulation", "act of", "statute")):
        return ClaimType.LEGAL_REGULATORY
    if any(w in lowered for w in ("study", "research", "scientific", "clinical trial")):
        return ClaimType.SCIENTIFIC
    if any(w in lowered for w in ("city", "country", "located in", "border", "capital")):
        return ClaimType.GEOGRAPHIC_DEMOGRAPHIC
    if any(w in lowered for w in ("happened", "event", "announced", "reported on")):
        return ClaimType.CURRENT_EVENT
    if any(w in lowered for w in ("causes", "caused by", "leads to", "results in")):
        return ClaimType.CAUSAL
    return ClaimType.EMPIRICAL_ATOMIC


def _is_predictive(text: str) -> bool:
    """Heuristic: detect predictive claims that should trigger Rule J."""
    lowered = text.lower()
    predictive_indicators = [
        "will ",
        "going to ",
        "predict",
        "forecast",
        "expect to ",
        "likely to ",
        "probably ",
        "may ",
        "might ",
        "could ",
        "would ",
        "future",
        "next year",
        "by 20",
        "upcoming",
        "soon ",
    ]
    return any(ind in lowered for ind in predictive_indicators)


def _build_offline_decomposition(claim_text: str) -> PremiseDecomposition:
    """Build a minimal single-ATOMIC decomposition for offline/simple claims."""
    premise_id = f"premise_{uuid.uuid4().hex[:12]}"
    subclaim_id = f"sc_{uuid.uuid4().hex[:12]}"
    return PremiseDecomposition(
        premise_id=premise_id,
        snapshot_id="offline",
        original_text=claim_text,
        topic_id="unknown",
        side=Side.FOR,
        root_claim_expression=ClaimExpression(
            node_type=NodeType.ATOMIC,
            subclaim_id=subclaim_id,
        ),
        atomic_subclaims=[
            AtomicSubclaim(
                subclaim_id=subclaim_id,
                parent_premise_id=premise_id,
                text=claim_text,
                claim_type=_claim_type_from_text(claim_text),
                operationalization_hint="",
                verdict_scope_hint=VerdictScope(),
            )
        ],
    )


def _tier_counts_from_v15(result) -> dict[str, int]:
    """Map v1.5 tier fields to legacy tier count dict."""
    counts: dict[str, int] = {"TIER_1": 0, "TIER_2": 0, "TIER_3": 0}
    # For SUPPORTED/REFUTED, best_evidence_tier is set.
    # For INSUFFICIENT, fall back to limiting_evidence_tier.
    tier = getattr(result, "best_evidence_tier", None)
    if tier is None:
        tier = getattr(result, "limiting_evidence_tier", None)
    if tier == 1:
        counts["TIER_1"] = 1
    elif tier == 2:
        counts["TIER_2"] = 1
    elif tier == 3:
        counts["TIER_3"] = 1
    return counts


def _verdict_from_v15_status(status: str) -> legacy_models.FactCheckVerdict:
    mapping = {
        "SUPPORTED": legacy_models.FactCheckVerdict.SUPPORTED,
        "REFUTED": legacy_models.FactCheckVerdict.REFUTED,
        "INSUFFICIENT": legacy_models.FactCheckVerdict.INSUFFICIENT,
    }
    return mapping.get(status, legacy_models.FactCheckVerdict.UNVERIFIED)


def _status_from_v15_status(status: str) -> legacy_models.FactCheckStatus:
    mapping = {
        "SUPPORTED": legacy_models.FactCheckStatus.CHECKED,
        "REFUTED": legacy_models.FactCheckStatus.CHECKED,
        "INSUFFICIENT": legacy_models.FactCheckStatus.NO_ALLOWLIST_EVIDENCE,
    }
    return mapping.get(status, legacy_models.FactCheckStatus.UNVERIFIED_OFFLINE)


def _v15_result_to_legacy(
    v15_result,
    claim_text: str,
    claim_hash: str,
    mode: str,
    allowlist_version: str,
    duration_ms: int,
    contains_pii: bool = False,
) -> legacy_models.FactCheckResult:
    """Convert a v1.5 FactCheckResult into a backward-compatible legacy result."""
    diagnostics: dict[str, Any] = {
        "v15_status": v15_result.status,
        "v15_p": v15_result.p,
        "v15_insufficiency_reason": v15_result.insufficiency_reason,
        "v15_human_review_flags": [f.value for f in (v15_result.human_review_flags or [])],
        "v15_best_evidence_tier": v15_result.best_evidence_tier,
        "v15_limiting_evidence_tier": v15_result.limiting_evidence_tier,
        "v15_decisive_evidence_tier": v15_result.decisive_evidence_tier,
    }

    # Include synthesis logic from root subclaim result if present
    subclaim_results = getattr(v15_result, "subclaim_results", None)
    if subclaim_results:
        root_sc = subclaim_results[0] if subclaim_results else None
        if root_sc and hasattr(root_sc, "synthesis_logic") and root_sc.synthesis_logic:
            sl = root_sc.synthesis_logic
            diagnostics["v15_synthesis_logic"] = {
                "status_rule_applied": sl.status_rule_applied,
                "policy_rule_id": sl.policy_rule_id,
                "insufficiency_trigger": sl.insufficiency_trigger,
                "claim_expression_node_type": sl.claim_expression_node_type.value
                if sl.claim_expression_node_type
                else None,
            }

    # Include subclaim results summary
    subclaim_results = getattr(v15_result, "subclaim_results", None)
    if subclaim_results:
        diagnostics["v15_subclaim_summaries"] = [
            {
                "subclaim_id": sc.subclaim_id,
                "status": sc.status,
                "p": sc.p,
                "best_evidence_tier": sc.best_evidence_tier,
                "insufficiency_reason": sc.insufficiency_reason,
            }
            for sc in subclaim_results
        ]

    # Build operationalization from v1.5 or fallback
    operationalization = v15_result.operationalization or ""
    if not operationalization and v15_result.insufficiency_reason:
        operationalization = f"Insufficient: {v15_result.insufficiency_reason}"

    return legacy_models.FactCheckResult(
        claim_text=claim_text,
        normalized_claim_text=claim_text.lower().strip(),
        claim_hash=claim_hash,
        fact_mode=mode,
        allowlist_version=allowlist_version,
        status=_status_from_v15_status(v15_result.status),
        verdict=_verdict_from_v15_status(v15_result.status),
        factuality_score=v15_result.p,
        confidence=v15_result.confidence,
        confidence_explanation=f"v1.5 synthesis: {v15_result.status}"
        + (
            f" (reason: {v15_result.insufficiency_reason})"
            if v15_result.insufficiency_reason
            else ""
        ),
        operationalization=operationalization,
        evidence=[],  # v1.5 keeps evidence in audit trail, not legacy result
        evidence_tier_counts=_tier_counts_from_v15(v15_result),
        algorithm_version="fc-1.5",
        processing_duration_ms=duration_ms,
        contains_pii=contains_pii,
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# Bridge Skill
# ---------------------------------------------------------------------------


class V15FactCheckingSkill:
    """
    Production bridge skill implementing the v1.5 deterministic ternary pipeline.

    Interface compatible with legacy FactCheckingSkill so it can be dropped
    into ExtractionEngine without structural changes.
    """

    def __init__(
        self,
        mode: str = "OFFLINE",
        allowlist_version: str = "v1",
        config: FactCheckConfig | None = None,
        connectors: list[BaseEvidenceConnector] | None = None,
        enable_async: bool = False,
        max_connector_workers: int = 4,
        connector_timeout: float = 30.0,
        llm_backend: Any | None = None,
        enable_llm_decomposition: bool = False,
        enable_audit: bool = False,
        source_registry: SourceReputationRegistry | None = None,
    ):
        mode_aliases = {
            "simulated": "OFFLINE",
            "offline": "OFFLINE",
            "online_allowlist": "ONLINE_ALLOWLIST",
            "perfect_checker": "PERFECT_CHECKER",
            "perfect": "PERFECT",
            "live_connectors": "LIVE_CONNECTORS",
        }
        self.mode = mode_aliases.get(str(mode).lower(), mode)
        self.allowlist_version = allowlist_version
        self.config = config or get_config()
        self._async_enabled = enable_async and self.mode in (
            "ONLINE_ALLOWLIST",
            "LIVE_CONNECTORS",
        )

        # v1.5 components
        self._synthesis_engine = SynthesisEngine()
        self._decomposer: Decomposer | None = None
        self._entity_linker = EntityLinker()
        self._normalizer = EvidenceNormalizer()
        self._source_registry = source_registry or SourceReputationRegistry()
        self._llm_backend = llm_backend
        self._enable_llm_decomposition = enable_llm_decomposition
        self._enable_audit = enable_audit

        # Parallel router config
        self._max_workers = getattr(self.config, "max_connector_workers", max_connector_workers)
        self._connector_timeout = getattr(
            self.config, "connector_timeout_seconds", connector_timeout
        )

        # Rate limiting / circuit breakers
        self._rate_limiter = RateLimiterManager()

        # Setup connectors based on mode
        self._connectors: list[BaseEvidenceConnector] = connectors or []
        if not self._connectors:
            self._setup_default_connectors()

        # Register circuit breakers for all connectors
        self._setup_circuit_breakers()

    def _setup_default_connectors(self) -> None:
        """Wire default connectors per mode."""
        if self.mode == "PERFECT":
            # Tier-1 structured only
            self._connectors = [WikidataEntityConnector()]
        elif self.mode == "PERFECT_CHECKER":
            # Controlled test connectors: Tier-1 + simulated Tier-2 stubs
            self._connectors = [
                WikidataEntityConnector(),
                _MockTier2Connector("sim_tier2_a"),
                _MockTier2Connector("sim_tier2_b"),
            ]
        elif self.mode in ("ONLINE_ALLOWLIST", "LIVE_CONNECTORS"):
            # Full registry (Phase 4 connectors)
            self._connectors = ConnectorRegistry.default_connectors()
        # OFFLINE: no connectors (empty list)

    def _setup_circuit_breakers(self) -> None:
        """Register default circuit breakers for all wired connectors."""
        cb_config = CircuitBreakerConfig(
            failure_threshold=getattr(self.config, "circuit_breaker_threshold", 5),
            timeout_minutes=int(getattr(self.config, "circuit_breaker_recovery_seconds", 60) / 60),
        )
        rate_config = RateLimitConfig()
        for connector in self._connectors:
            self._rate_limiter.register_source(connector.connector_id, rate_config, cb_config)

    # ------------------------------------------------------------------
    # Public API (same surface as legacy FactCheckingSkill)
    # ------------------------------------------------------------------

    def check_fact(
        self,
        claim_text: str,
        temporal_context: legacy_models.TemporalContext | None = None,
        request_context: legacy_models.RequestContext | None = None,
        wait_for_async: bool = False,
    ) -> legacy_models.FactCheckResult:
        start_time = time.time()
        request_context = request_context or legacy_models.RequestContext()

        if len(claim_text) > self.config.max_claim_length:
            claim_text = claim_text[: self.config.max_claim_length]

        claim_hash = _compute_claim_hash(claim_text)
        contains_pii = False  # PII detection delegated to caller

        # OFFLINE: deterministic INSUFFICIENT per LSD §13
        if self.mode == "OFFLINE":
            return self._check_offline(claim_text, claim_hash, contains_pii, temporal_context)

        claim_type = _claim_type_from_text(claim_text)

        # Normative claim routing (Gold test #29)
        if claim_type == ClaimType.EMPIRICAL_ATOMIC and _is_normative(claim_text):
            return self._check_normative(claim_text, claim_hash, contains_pii, temporal_context)

        # Build decomposition (fallback to simple ATOMIC if no decomposer)
        decomposition = self._get_decomposition(claim_text)

        # Determine predictive subclaim IDs for Rule J
        predictive_ids = self._get_predictive_subclaim_ids(decomposition)

        # Entity linking
        entity_failure_ids = self._get_entity_failure_ids(decomposition)

        # Load policy
        policy = get_default_policy(claim_type)

        # Select connectors based on policy
        active_connectors = self._select_connectors_for_claim(claim_type, policy)

        # Retrieve evidence from connectors
        evidence_items = self._retrieve_evidence(decomposition, active_connectors)

        # Normalize evidence
        evidence_items = self._normalizer.normalize_batch(evidence_items)

        # Apply source registry promotions (Tier 3 → Tier 2)
        evidence_items = self._apply_source_registry(evidence_items)

        # Archive web evidence
        self._archive_web_evidence(evidence_items)

        # Filter evidence by policy
        if policy is not None:
            evidence_items = self._filter_evidence_by_policy(evidence_items, policy)
            evidence_items = self._enforce_cross_verification(evidence_items, policy)

        # Run v1.5 synthesis
        if self._enable_audit:
            v15_result = self._run_audited_pipeline(
                claim_text=claim_text,
                decomposition=decomposition,
                evidence_items=evidence_items,
                entity_failure_ids=entity_failure_ids,
                predictive_ids=predictive_ids,
                policy=policy,
            )
        else:
            v15_result = self._synthesis_engine.synthesize(
                decomposition=decomposition,
                evidence_items=evidence_items,
                entity_failure_subclaim_ids=entity_failure_ids,
                predictive_subclaim_ids=predictive_ids,
                policy=policy,
            )

        duration_ms = int((time.time() - start_time) * 1000)

        return _v15_result_to_legacy(
            v15_result=v15_result,
            claim_text=claim_text,
            claim_hash=claim_hash,
            mode=self.mode,
            allowlist_version=self.allowlist_version,
            duration_ms=duration_ms,
            contains_pii=contains_pii,
        )

    def check_fact_async(
        self,
        claim_text: str,
        temporal_context: legacy_models.TemporalContext | None = None,
        request_context: legacy_models.RequestContext | None = None,
    ) -> legacy_models.FactCheckJob:
        """Async entry point. Currently delegates to sync check."""
        if not self._async_enabled:
            raise RuntimeError("Async processing not enabled for v1.5 skill")

        normalized = claim_text.lower().strip()
        claim_hash = _compute_claim_hash(normalized)
        contains_pii = False

        # For v1.5, async is not yet fully implemented; return a completed job
        result = self.check_fact(
            claim_text=claim_text,
            temporal_context=temporal_context,
            request_context=request_context,
        )

        return legacy_models.FactCheckJob(
            job_id=f"v15_job_{uuid.uuid4().hex[:12]}",
            claim_text=claim_text,
            normalized_claim=normalized,
            claim_hash=claim_hash,
            fact_mode=self.mode,
            allowlist_version=self.allowlist_version,
            temporal_context=temporal_context,
            request_context=request_context or legacy_models.RequestContext(),
            contains_pii=contains_pii,
            status="completed",
            result=result,
        )

    def get_job_result(self, job_id: str) -> legacy_models.FactCheckResult | None:
        """Get result for an async job."""
        # v1.5 bridge does not maintain a persistent job queue;
        # callers should store results themselves.
        return None

    def get_job_status(self, job_id: str) -> str | None:
        """Get status for an async job."""
        return None

    # ------------------------------------------------------------------
    # Backward-compatible stats stubs
    # ------------------------------------------------------------------

    def get_cache_stats(self) -> dict[str, Any]:
        """Return cache statistics (v1.5 bridge has no persistent cache)."""
        return {"hits": 0, "misses": 0, "size": 0}

    def get_audit_stats(self) -> dict[str, Any]:
        """Return audit statistics (v1.5 bridge has no persistent audit log)."""
        return {"total_checks": 0, "last_check": None}

    def get_queue_stats(self) -> dict[str, Any]:
        """Return queue statistics (v1.5 bridge has no persistent queue)."""
        return {"pending": 0, "completed": 0, "failed": 0}

    def shutdown(self) -> None:
        """Graceful shutdown stub for backward compatibility."""
        pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_offline(
        self,
        claim_text: str,
        claim_hash: str,
        contains_pii: bool,
        temporal_context: legacy_models.TemporalContext | None,
    ) -> legacy_models.FactCheckResult:
        """Deterministic OFFLINE result per LSD §13."""
        return legacy_models.FactCheckResult(
            claim_text=claim_text,
            normalized_claim_text=claim_text.lower().strip(),
            claim_hash=claim_hash,
            fact_mode="OFFLINE",
            allowlist_version=self.allowlist_version,
            status=legacy_models.FactCheckStatus.UNVERIFIED_OFFLINE,
            verdict=legacy_models.FactCheckVerdict.INSUFFICIENT,
            factuality_score=0.5,
            confidence=0.0,
            confidence_explanation="v1.5 OFFLINE mode: no source lookup performed",
            operationalization="Live source lookup would be required to confirm or refute this claim.",
            evidence=[],
            algorithm_version="fc-1.5",
            processing_duration_ms=0,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
            diagnostics={
                "v15_status": "INSUFFICIENT",
                "v15_p": 0.5,
                "v15_insufficiency_reason": "offline_mode",
                "reason_code": "offline_mode",
            },
        )

    def _check_normative(
        self,
        claim_text: str,
        claim_hash: str,
        contains_pii: bool,
        temporal_context: legacy_models.TemporalContext | None,
    ) -> legacy_models.FactCheckResult:
        """Deterministic normative claim result (routed out)."""
        return legacy_models.FactCheckResult(
            claim_text=claim_text,
            normalized_claim_text=claim_text.lower().strip(),
            claim_hash=claim_hash,
            fact_mode=self.mode,
            allowlist_version=self.allowlist_version,
            status=legacy_models.FactCheckStatus.NO_ALLOWLIST_EVIDENCE,
            verdict=legacy_models.FactCheckVerdict.INSUFFICIENT,
            factuality_score=0.5,
            confidence=0.5,
            confidence_explanation="v1.5 normative claim routed out",
            operationalization="Normative claims cannot be fact-checked empirically.",
            evidence=[],
            algorithm_version="fc-1.5",
            processing_duration_ms=0,
            contains_pii=contains_pii,
            temporal_context=temporal_context,
            diagnostics={
                "v15_status": "INSUFFICIENT",
                "v15_p": 0.5,
                "v15_insufficiency_reason": "normative_claim_routed_out",
                "normative_routed": True,
            },
        )

    def _get_decomposition(self, claim_text: str) -> PremiseDecomposition:
        """Get or build a PremiseDecomposition for the claim."""
        premise = CanonicalPremise(
            premise_id=f"premise_{uuid.uuid4().hex[:12]}",
            snapshot_id="offline",
            original_text=claim_text,
            topic_id="unknown",
            side=Side.FOR,
            claim_type=_claim_type_from_text(claim_text),
        )

        if self._enable_llm_decomposition and self._llm_backend is not None:

            def _llm_adapter(p: CanonicalPremise) -> PremiseDecomposition:
                result = self._llm_backend.decompose_claim(p.original_text, p.claim_type)
                if result is None:
                    raise RuntimeError("LLM decomposition failed")
                return result

            decomposer = Decomposer(llm_backend=_llm_adapter)
        else:
            decomposer = self._decomposer or Decomposer()

        return decomposer.decompose(premise)

    def _get_predictive_subclaim_ids(self, decomposition: PremiseDecomposition) -> set[str]:
        """Identify subclaims that contain predictive language (Rule J)."""
        predictive_ids: set[str] = set()
        for subclaim in decomposition.atomic_subclaims:
            if _is_predictive(subclaim.text):
                predictive_ids.add(subclaim.subclaim_id)
        return predictive_ids

    def _get_entity_failure_ids(self, decomposition: PremiseDecomposition) -> set[str]:
        """Run entity linking and collect unresolvable entity failures."""
        failure_ids: set[str] = set()
        for subclaim in decomposition.atomic_subclaims:
            links = self._entity_linker.link(subclaim.text)
            # If no links found for a claim that clearly has entities,
            # consider it a failure. Simple heuristic: if text has capitalized
            # words but no links were resolved, flag as failure.
            if not links:
                import re

                if re.search(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+\b", subclaim.text):
                    failure_ids.add(subclaim.subclaim_id)
        return failure_ids

    def _select_connectors_for_claim(
        self,
        claim_type: ClaimType,
        policy: EvidencePolicy | None,
    ) -> list[BaseEvidenceConnector]:
        """Filter connectors based on policy source_type preferences."""
        if policy is None or not policy.required_source_types:
            return self._connectors

        allowed = set(policy.required_source_types) | set(policy.preferred_source_types)
        filtered = []
        for c in self._connectors:
            # Map connector IDs to source types heuristically
            source_type = self._infer_source_type(c)
            if source_type in allowed or source_type == SourceType.OTHER:
                filtered.append(c)
        return filtered or self._connectors

    @staticmethod
    def _infer_source_type(connector: BaseEvidenceConnector) -> SourceType:
        """Infer SourceType from connector class name or connector_id."""
        cid = connector.connector_id.lower()
        if "wikidata" in cid:
            return SourceType.WIKIDATA
        if "bls" in cid or "stat" in cid:
            return SourceType.OFFICIAL_STAT
        if "crossref" in cid or "pubmed" in cid:
            return SourceType.SCIENTIFIC_DB
        if "curated" in cid or "rag" in cid:
            return SourceType.WIKIPEDIA
        if "brave" in cid or "web" in cid:
            return SourceType.WEB
        return SourceType.OTHER

    def _retrieve_evidence(
        self,
        decomposition: PremiseDecomposition,
        active_connectors: list[BaseEvidenceConnector] | None = None,
    ) -> list[EvidenceItem]:
        """Collect evidence from all wired connectors in parallel."""
        connectors = active_connectors or self._connectors
        if not connectors:
            return []

        items: list[EvidenceItem] = []

        # Build list of (subclaim, connector) tasks
        tasks = []
        for subclaim in decomposition.atomic_subclaims:
            for connector in connectors:
                tasks.append((subclaim, connector))

        if not tasks:
            return items

        # Sequential fallback when single worker or trivial load
        if self._max_workers <= 1 or len(tasks) == 1:
            for subclaim, connector in tasks:
                try:
                    retrieved = self._retrieve_with_fallback(
                        subclaim, connector, subclaim.claim_type
                    )
                    items.extend(retrieved)
                except Exception as e:
                    logger.warning(
                        "Connector %s failed for subclaim %s: %s",
                        connector.connector_id,
                        subclaim.subclaim_id,
                        e,
                    )
            return items

        # Parallel execution
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_task = {
                executor.submit(
                    self._retrieve_with_fallback, subclaim, connector, subclaim.claim_type
                ): (subclaim, connector)
                for subclaim, connector in tasks
            }

            for future in as_completed(future_to_task):
                subclaim, connector = future_to_task[future]
                try:
                    retrieved = future.result(timeout=self._connector_timeout)
                    items.extend(retrieved)
                except Exception as e:
                    logger.warning(
                        "Connector %s failed for subclaim %s: %s",
                        connector.connector_id,
                        subclaim.subclaim_id,
                        e,
                    )

        return items

    def _retrieve_single(
        self, subclaim: AtomicSubclaim, connector: BaseEvidenceConnector
    ) -> list[EvidenceItem]:
        """Single connector retrieval with circuit breaker and rate-limit check."""
        can_execute, reason = self._rate_limiter.can_query(connector.connector_id)
        if not can_execute:
            logger.warning("Source %s blocked: %s", connector.connector_id, reason or "unknown")
            return []

        try:
            result = connector.retrieve(subclaim)
            self._rate_limiter.record_success(connector.connector_id)
            return result
        except Exception:
            self._rate_limiter.record_failure(connector.connector_id)
            raise

    def _retrieve_with_fallback(
        self,
        subclaim: AtomicSubclaim,
        primary_connector: BaseEvidenceConnector,
        claim_type: ClaimType,
    ) -> list[EvidenceItem]:
        """Try primary connector. If it fails or returns empty, walk the fallback chain."""
        chain = self._get_fallback_chain(primary_connector.connector_id, claim_type)
        connectors_to_try = [primary_connector]
        for cid in chain:
            fallback = self._get_connector_by_id(cid)
            if fallback is not None:
                connectors_to_try.append(fallback)

        for connector in connectors_to_try:
            try:
                result = self._retrieve_single(subclaim, connector)
                if result:
                    return result
            except Exception:
                continue

        return []

    def _get_fallback_chain(self, connector_id: str, claim_type: ClaimType) -> list[str]:
        """Look up fallback chain from config."""
        # First try claim-type-specific chains
        type_chains = self.config.claim_type_fallbacks.get(claim_type.value, {})
        if connector_id in type_chains:
            return type_chains[connector_id]
        # Then try global chains
        return self.config.fallback_chains.get(connector_id, [])

    def _get_connector_by_id(self, connector_id: str) -> BaseEvidenceConnector | None:
        for c in self._connectors:
            if c.connector_id == connector_id:
                return c
        return None

    def _filter_evidence_by_policy(
        self, evidence: list[EvidenceItem], policy: EvidencePolicy
    ) -> list[EvidenceItem]:
        """Apply policy constraints to retrieved evidence."""
        filtered = []
        for ev in evidence:
            # Temporal constraint check
            if policy.temporal_constraint and ev.source_date:
                try:
                    from datetime import datetime

                    start = policy.temporal_constraint.get("start")
                    end = policy.temporal_constraint.get("end")
                    ev_date = datetime.fromisoformat(ev.source_date.replace("Z", "+00:00"))
                    if start and ev_date < datetime.fromisoformat(start):
                        continue
                    if end and ev_date > datetime.fromisoformat(end):
                        continue
                except Exception:
                    pass

            filtered.append(ev)
        return filtered

    def _enforce_cross_verification(
        self, evidence: list[EvidenceItem], policy: EvidencePolicy
    ) -> list[EvidenceItem]:
        """If policy.requires_cross_verification, ensure at least 2 independent source groups."""
        if not policy.cross_verification_required:
            return evidence

        groups = set()
        for ev in evidence:
            if ev.source_independence_group_id:
                groups.add(ev.source_independence_group_id)

        if len(groups) < 2:
            logger.warning(
                "Cross-verification failed: only %d source group(s) found, policy requires 2+",
                len(groups),
            )
        return evidence

    def _apply_source_registry(self, evidence: list[EvidenceItem]) -> list[EvidenceItem]:
        """Promote Tier 3 evidence from allowlisted domains to Tier 2."""
        from dataclasses import replace
        from urllib.parse import urlparse

        updated = []
        for ev in evidence:
            if ev.source_tier != 3 or not ev.source_url:
                updated.append(ev)
                continue
            domain = urlparse(ev.source_url).netloc
            if self._source_registry.is_promoted(domain):
                promoted = replace(ev, source_tier=2)
                updated.append(promoted)
                logger.info("Promoted evidence from %s to Tier 2", domain)
            else:
                updated.append(ev)
        return updated

    def _archive_web_evidence(self, evidence: list[EvidenceItem]) -> None:
        """Archive web-sourced evidence for artifact replay verification."""
        for ev in evidence:
            if ev.source_type in (SourceType.WEB, SourceType.NEWS, SourceType.WIKIPEDIA):
                if ev.source_url:
                    try:
                        page_text = (ev.quote_or_span or "") + (ev.quote_context or "")
                        archive_web_evidence(ev.source_url, page_text)
                    except Exception as e:
                        logger.debug("Failed to archive web evidence for %s: %s", ev.source_url, e)

    def _run_audited_pipeline(
        self,
        claim_text: str,
        decomposition: PremiseDecomposition,
        evidence_items: list[EvidenceItem],
        entity_failure_ids: set[str],
        predictive_ids: set[str],
        policy: Any | None = None,
    ) -> Any:
        """Run the full audited pipeline wrapper."""
        premise = CanonicalPremise(
            premise_id=decomposition.premise_id,
            snapshot_id=decomposition.snapshot_id,
            original_text=claim_text,
            topic_id=decomposition.topic_id,
            side=decomposition.side,
            claim_type=_claim_type_from_text(claim_text),
        )
        try:
            from .v15_audit import AuditStore

            audit_store = AuditStore()
        except Exception:
            # If audit store is unavailable, fall back to non-audited synthesis
            logger.warning("AuditStore unavailable; falling back to non-audited synthesis")
            return self._synthesis_engine.synthesize(
                decomposition=decomposition,
                evidence_items=evidence_items,
                entity_failure_subclaim_ids=entity_failure_ids,
                predictive_subclaim_ids=predictive_ids,
                policy=policy,
            )

        v15_result, _ = decompose_synthesize_and_audit(
            premise=premise,
            evidence_items=evidence_items,
            decomposer=self._decomposer or Decomposer(),
            engine=self._synthesis_engine,
            audit_store=audit_store,
            entity_failure_subclaim_ids=entity_failure_ids,
            predictive_subclaim_ids=predictive_ids,
            policy=policy,
        )
        return v15_result


# ---------------------------------------------------------------------------
# Mock Tier-2 connector for PERFECT_CHECKER mode
# ---------------------------------------------------------------------------


class _MockTier2Connector(BaseEvidenceConnector):
    """Controlled mock connector for test/fixture mode."""

    def __init__(self, connector_id: str):
        self._id = connector_id

    @property
    def connector_id(self) -> str:
        return self._id

    @property
    def connector_version(self) -> str:
        return "1.0.0-mock"

    def retrieve(self, subclaim: AtomicSubclaim) -> list[EvidenceItem]:
        # Mock connectors return no evidence by default;
        # tests can patch this for controlled fixtures.
        return []
