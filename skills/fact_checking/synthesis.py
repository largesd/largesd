"""
SynthesisEngine with hard-coded rules for the LSD Fact-Checking System v1.5.

Responsibilities:
- Atomic subclaim synthesis rules (A–J) per 02_SYNTHESIS_ENGINE.md
- Compound premise aggregation (AND, OR, NOT, IF_THEN)
- Tier reporting rules (Tier 3-only → INSUFFICIENT)
- Scope mismatch handling
- Direction uncertainty handling (low-confidence → UNCLEAR, not decisive)
- Contradictory Tier 1 resolution with authority ranking hook
- No evidence → INSUFFICIENT
- Entity failure → INSUFFICIENT
- Policy gap → INSUFFICIENT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from .claim_expression import evaluate_expression
from .policies import get_default_policy
from .v15_models import (
    AtomicSubclaim,
    ClaimExpression,
    ClaimType,
    Direction,
    DirectionMethod,
    EvidenceItem,
    EvidencePolicy,
    FactCheckResult,
    HumanReviewFlag,
    NodeType,
    PremiseDecomposition,
    ProvenanceSpan,
    ResolvedValue,
    RetrievalPath,
    Side,
    SubclaimResult,
    SynthesisLogic,
    VerdictScope,
)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

RELEVANCE_THRESHOLD = 0.3
DIRECTION_CONFIDENCE_THRESHOLD = 0.7


def _default_authority_rank(item: EvidenceItem) -> int:
    """Simple hard-coded authority ranking for Phase 1 testing."""
    authority = (item.source_authority or "").lower()
    if "supreme court" in authority:
        return 100
    if "final official" in authority or "official stat" in authority:
        return 90
    if "systematic review" in authority:
        return 80
    if "agency" in authority:
        return 50
    if "preliminary" in authority or "estimate" in authority:
        return 20
    if "single study" in authority:
        return 10
    return 0


def _confidence_for_tiers(best_tier: Optional[int], cross_met: bool, entity_ok: bool, direction_ok: bool) -> float:
    base = 1.0 if best_tier == 1 else 0.80 if best_tier == 2 else 0.5
    cross_penalty = 0.2 if not cross_met else 0.0
    entity_penalty = 0.0 if entity_ok else 0.3
    direction_penalty = 0.0 if direction_ok else 0.2
    return max(0.0, base - cross_penalty - entity_penalty - direction_penalty)


def _independence_key(item: EvidenceItem) -> str:
    return item.source_independence_group_id or item.source_url or item.evidence_id


def _distinct_independent_count(items: List[EvidenceItem]) -> int:
    return len({_independence_key(i) for i in items})


def _filter_evidence(items: List[EvidenceItem]) -> List[EvidenceItem]:
    """Apply Phase 1 normalization gates.

    - Relevance below threshold → reject entirely.
    - Direction confidence below threshold → demote to UNCLEAR (non-decisive)
      but keep in the audit trail.
    """
    from dataclasses import replace

    filtered: List[EvidenceItem] = []
    for item in items:
        if item.relevance_score < RELEVANCE_THRESHOLD:
            # Too irrelevant to keep even as non-decisive
            continue
        if item.direction_confidence < DIRECTION_CONFIDENCE_THRESHOLD:
            # Keep but mark as non-decisive (UNCLEAR)
            demoted = replace(item, direction=Direction.UNCLEAR)
            filtered.append(demoted)
        else:
            filtered.append(item)
    return filtered


def _items_by_tier_and_direction(items: List[EvidenceItem]):
    """Split decisive items into tier/direction buckets."""
    t1_supports = []
    t1_refutes = []
    t2_supports = []
    t2_refutes = []
    t3_supports = []
    t3_refutes = []
    for item in items:
        if item.direction == Direction.SUPPORTS:
            if item.source_tier == 1:
                t1_supports.append(item)
            elif item.source_tier == 2:
                t2_supports.append(item)
            elif item.source_tier == 3:
                t3_supports.append(item)
        elif item.direction == Direction.REFUTES:
            if item.source_tier == 1:
                t1_refutes.append(item)
            elif item.source_tier == 2:
                t2_refutes.append(item)
            elif item.source_tier == 3:
                t3_refutes.append(item)
    return t1_supports, t1_refutes, t2_supports, t2_refutes, t3_supports, t3_refutes


# ---------------------------------------------------------------------------
# SynthesisEngine
# ---------------------------------------------------------------------------

class SynthesisEngine:
    def __init__(
        self,
        authority_ranking_hook: Optional[Callable[[EvidenceItem], int]] = None,
    ):
        self.authority_ranking_hook = authority_ranking_hook or _default_authority_rank

    def _check_high_impact_llm(
        self,
        subclaim: AtomicSubclaim,
        filtered_evidence: List[EvidenceItem],
    ) -> bool:
        """Check if HIGH_IMPACT_LLM_DIRECTION flag should be added.

        Per 02_SYNTHESIS_ENGINE.md §2: if an LLM-classified item would be
        decisive for a high-impact claim, flag unless there is independent
        deterministic corroboration.
        """
        high_impact = subclaim.claim_type in (
            ClaimType.LEGAL_REGULATORY,
            ClaimType.SCIENTIFIC,
        )
        if not high_impact:
            return False

        for item in filtered_evidence:
            if (
                item.direction_method == DirectionMethod.LLM_CLASSIFIER
                and item.direction in (Direction.SUPPORTS, Direction.REFUTES)
            ):
                has_deterministic = any(
                    i.direction_method == DirectionMethod.DETERMINISTIC_STRUCTURED
                    and i.direction == item.direction
                    for i in filtered_evidence
                )
                if not has_deterministic:
                    return True
        return False

    def synthesize(
        self,
        decomposition: PremiseDecomposition,
        evidence_items: List[EvidenceItem],
        entity_failure_subclaim_ids: Optional[Set[str]] = None,
        scope_mismatch_subclaim_ids: Optional[Set[str]] = None,
        predictive_subclaim_ids: Optional[Set[str]] = None,
        connector_failure_subclaim_ids: Optional[Set[str]] = None,
        policy: Optional[EvidencePolicy] = None,
    ) -> FactCheckResult:
        """Run the full synthesis pipeline for a premise."""
        entity_failure_subclaim_ids = entity_failure_subclaim_ids or set()
        scope_mismatch_subclaim_ids = scope_mismatch_subclaim_ids or set()
        predictive_subclaim_ids = predictive_subclaim_ids or set()
        connector_failure_subclaim_ids = connector_failure_subclaim_ids or set()

        # Group evidence by subclaim_id
        evidence_by_subclaim: Dict[str, List[EvidenceItem]] = {}
        for item in evidence_items:
            evidence_by_subclaim.setdefault(item.subclaim_id, []).append(item)

        subclaim_results: Dict[str, SubclaimResult] = {}
        for subclaim in decomposition.atomic_subclaims:
            result = self._synthesize_atomic(
                subclaim=subclaim,
                evidence=evidence_by_subclaim.get(subclaim.subclaim_id, []),
                entity_failure=subclaim.subclaim_id in entity_failure_subclaim_ids,
                scope_mismatch=subclaim.subclaim_id in scope_mismatch_subclaim_ids,
                predictive=subclaim.subclaim_id in predictive_subclaim_ids,
                connector_failure=subclaim.subclaim_id in connector_failure_subclaim_ids,
                policy=policy,
            )
            subclaim_results[subclaim.subclaim_id] = result

        # Evaluate root claim expression
        root_result = evaluate_expression(decomposition.root_claim_expression, subclaim_results)

        # Build final FactCheckResult
        return self._build_fact_check_result(decomposition, root_result, list(subclaim_results.values()))

    def _synthesize_atomic(
        self,
        subclaim: AtomicSubclaim,
        evidence: List[EvidenceItem],
        entity_failure: bool,
        scope_mismatch: bool,
        predictive: bool,
        connector_failure: bool,
        policy: Optional[EvidencePolicy] = None,
    ) -> SubclaimResult:
        # Rule A — Entity failure
        if entity_failure:
            return SubclaimResult(
                subclaim_id=subclaim.subclaim_id,
                status="INSUFFICIENT",
                p=0.5,
                confidence=0.5,
                insufficiency_reason="entity_resolution_failure",
                operationalization=subclaim.operationalization_hint,
                verdict_scope=subclaim.verdict_scope_hint,
                provenance_spans=list(subclaim.provenance_spans),
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="rule_a_entity_failure",
                    insufficiency_trigger="entity_resolution_failure",
                    claim_expression_node_type=NodeType.ATOMIC,
                ),
            )

        # Rule B — Policy gap
        if policy is None:
            policy = get_default_policy(subclaim.claim_type)
        if policy is None:
            return SubclaimResult(
                subclaim_id=subclaim.subclaim_id,
                status="INSUFFICIENT",
                p=0.5,
                confidence=0.5,
                insufficiency_reason="policy_gap",
                operationalization=subclaim.operationalization_hint,
                verdict_scope=subclaim.verdict_scope_hint,
                provenance_spans=list(subclaim.provenance_spans),
                human_review_flags=[HumanReviewFlag.POLICY_GAP],
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="rule_b_policy_gap",
                    insufficiency_trigger="policy_gap",
                    claim_expression_node_type=NodeType.ATOMIC,
                ),
            )

        # Rule J — Predictive claim
        if predictive:
            return SubclaimResult(
                subclaim_id=subclaim.subclaim_id,
                status="INSUFFICIENT",
                p=0.5,
                confidence=0.5,
                insufficiency_reason="predictive_claim_not_checkable",
                operationalization=subclaim.operationalization_hint,
                verdict_scope=subclaim.verdict_scope_hint,
                provenance_spans=list(subclaim.provenance_spans),
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="rule_j_predictive",
                    insufficiency_trigger="predictive_claim_not_checkable",
                    claim_expression_node_type=NodeType.ATOMIC,
                ),
            )

        # Normalize / gate evidence
        filtered = _filter_evidence(evidence)

        # Determine if high-impact LLM direction flag applies
        extra_flags = (
            [HumanReviewFlag.HIGH_IMPACT_LLM_DIRECTION]
            if self._check_high_impact_llm(subclaim, filtered)
            else []
        )

        # Rule I — No evidence (and connector failure variant)
        if not filtered:
            reason = "connector_failure" if connector_failure else "no_evidence_retrieved"
            return SubclaimResult(
                subclaim_id=subclaim.subclaim_id,
                status="INSUFFICIENT",
                p=0.5,
                confidence=0.5,
                insufficiency_reason=reason,
                operationalization=subclaim.operationalization_hint,
                verdict_scope=subclaim.verdict_scope_hint,
                provenance_spans=list(subclaim.provenance_spans),
                human_review_flags=([HumanReviewFlag.CONNECTOR_FAILURE] if connector_failure else []) + extra_flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="rule_i_no_evidence",
                    insufficiency_trigger=reason,
                    claim_expression_node_type=NodeType.ATOMIC,
                ),
            )

        # Rule I-b — Placeholder-only evidence
        if all(item.retrieval_path == RetrievalPath.OFFLINE_PLACEHOLDER for item in evidence):
            return SubclaimResult(
                subclaim_id=subclaim.subclaim_id,
                status="INSUFFICIENT",
                p=0.5,
                confidence=0.5,
                best_evidence_tier=1,
                insufficiency_reason="connector_offline_placeholder",
                operationalization=subclaim.operationalization_hint,
                verdict_scope=subclaim.verdict_scope_hint,
                provenance_spans=list(subclaim.provenance_spans),
                human_review_flags=[HumanReviewFlag.CONNECTOR_FAILURE] + extra_flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="rule_i_placeholder_only",
                    insufficiency_trigger="connector_offline_placeholder",
                    claim_expression_node_type=NodeType.ATOMIC,
                ),
            )

        # Rule C — Scope mismatch
        if scope_mismatch:
            return SubclaimResult(
                subclaim_id=subclaim.subclaim_id,
                status="INSUFFICIENT",
                p=0.5,
                confidence=0.5,
                insufficiency_reason="evidence_scope_narrower_than_claim",
                operationalization=subclaim.operationalization_hint,
                verdict_scope=subclaim.verdict_scope_hint,
                provenance_spans=list(subclaim.provenance_spans),
                human_review_flags=[HumanReviewFlag.SCOPE_MISMATCH] + extra_flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="rule_c_scope_mismatch",
                    insufficiency_trigger="evidence_scope_narrower_than_claim",
                    claim_expression_node_type=NodeType.ATOMIC,
                ),
            )

        # Classify by tier and direction
        t1s, t1r, t2s, t2r, t3s, t3r = _items_by_tier_and_direction(filtered)

        # Tier 1 decisive / contradictory
        if t1s or t1r:
            return self._resolve_tier1(
                subclaim=subclaim,
                supports=t1s,
                refutes=t1r,
                policy=policy,
                extra_flags=extra_flags,
            )

        # Tier 2 decisive / mixed
        if t2s or t2r:
            return self._resolve_tier2(
                subclaim=subclaim,
                supports=t2s,
                refutes=t2r,
                policy=policy,
                extra_flags=extra_flags,
            )

        # Tier 3 only
        if t3s or t3r:
            return SubclaimResult(
                subclaim_id=subclaim.subclaim_id,
                status="INSUFFICIENT",
                p=0.5,
                confidence=0.5,
                insufficiency_reason="only_tier3_evidence",
                operationalization=subclaim.operationalization_hint,
                verdict_scope=subclaim.verdict_scope_hint,
                provenance_spans=list(subclaim.provenance_spans),
                human_review_flags=extra_flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="rule_h_tier3_only",
                    insufficiency_trigger="only_tier3_evidence",
                    claim_expression_node_type=NodeType.ATOMIC,
                ),
            )

        # No decisive evidence after gating
        return SubclaimResult(
            subclaim_id=subclaim.subclaim_id,
            status="INSUFFICIENT",
            p=0.5,
            confidence=0.5,
            insufficiency_reason="no_evidence_retrieved",
            operationalization=subclaim.operationalization_hint,
            verdict_scope=subclaim.verdict_scope_hint,
            provenance_spans=list(subclaim.provenance_spans),
            human_review_flags=extra_flags,
            synthesis_logic=SynthesisLogic(
                status_rule_applied="rule_i_no_evidence",
                insufficiency_trigger="no_evidence_retrieved",
                claim_expression_node_type=NodeType.ATOMIC,
            ),
        )

    def _resolve_tier1(
        self,
        subclaim: AtomicSubclaim,
        supports: List[EvidenceItem],
        refutes: List[EvidenceItem],
        policy: EvidencePolicy,
        extra_flags: Optional[List[HumanReviewFlag]] = None,
    ) -> SubclaimResult:
        # If both directions present, handle contradictory Tier 1
        if supports and refutes:
            top_support = max(supports, key=self.authority_ranking_hook)
            top_refute = max(refutes, key=self.authority_ranking_hook)
            rank_support = self.authority_ranking_hook(top_support)
            rank_refute = self.authority_ranking_hook(top_refute)
            if rank_support > rank_refute:
                return self._make_decisive_result(
                    subclaim=subclaim,
                    status="SUPPORTED",
                    p=1.0,
                    tier=1,
                    citations=[top_support.evidence_id],
                    provenance_spans=list(subclaim.provenance_spans),
                    authority_ranking_applied=True,
                    resolved_value=top_support.source_value,
                    extra_flags=extra_flags,
                )
            if rank_refute > rank_support:
                return self._make_decisive_result(
                    subclaim=subclaim,
                    status="REFUTED",
                    p=0.0,
                    tier=1,
                    citations=[top_refute.evidence_id],
                    provenance_spans=list(subclaim.provenance_spans),
                    authority_ranking_applied=True,
                    resolved_value=top_refute.source_value,
                    extra_flags=extra_flags,
                )
            # Unresolvable contradiction
            return SubclaimResult(
                subclaim_id=subclaim.subclaim_id,
                status="INSUFFICIENT",
                p=0.5,
                confidence=0.5,
                insufficiency_reason="contradictory_tier1_evidence",
                operationalization=subclaim.operationalization_hint,
                verdict_scope=subclaim.verdict_scope_hint,
                provenance_spans=list(subclaim.provenance_spans),
                human_review_flags=[HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE] + (extra_flags or []),
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="rule_e_contradictory_tier1_unresolved",
                    insufficiency_trigger="contradictory_tier1_evidence",
                    claim_expression_node_type=NodeType.ATOMIC,
                ),
            )

        # Single direction
        if supports:
            best = supports[0]
            return self._make_decisive_result(
                subclaim=subclaim,
                status="SUPPORTED",
                p=1.0,
                tier=1,
                citations=[i.evidence_id for i in supports],
                provenance_spans=list(subclaim.provenance_spans),
                resolved_value=best.source_value,
                extra_flags=extra_flags,
            )
        if refutes:
            best = refutes[0]
            return self._make_decisive_result(
                subclaim=subclaim,
                status="REFUTED",
                p=0.0,
                tier=1,
                citations=[i.evidence_id for i in refutes],
                provenance_spans=list(subclaim.provenance_spans),
                resolved_value=best.source_value,
                extra_flags=extra_flags,
            )

        # Fallback (should not reach here)
        return SubclaimResult(
            subclaim_id=subclaim.subclaim_id,
            status="INSUFFICIENT",
            p=0.5,
            confidence=0.5,
            insufficiency_reason="tier1_resolution_fallback",
            operationalization=subclaim.operationalization_hint,
            verdict_scope=subclaim.verdict_scope_hint,
            provenance_spans=list(subclaim.provenance_spans),
            synthesis_logic=SynthesisLogic(
                status_rule_applied="rule_d_tier1_fallback",
                claim_expression_node_type=NodeType.ATOMIC,
            ),
        )

    def _resolve_tier2(
        self,
        subclaim: AtomicSubclaim,
        supports: List[EvidenceItem],
        refutes: List[EvidenceItem],
        policy: EvidencePolicy,
        extra_flags: Optional[List[HumanReviewFlag]] = None,
    ) -> SubclaimResult:
        cross_required = policy.cross_verification_required
        min_sources = policy.cross_verification_minimum_sources

        # Check independence for each direction
        support_independent = _distinct_independent_count(supports)
        refute_independent = _distinct_independent_count(refutes)

        cross_met_support = support_independent >= min_sources if cross_required else True
        cross_met_refute = refute_independent >= min_sources if cross_required else True

        # If both directions have decisive evidence after cross-check
        if supports and refutes:
            # If cross-verification not met for either side, it's insufficient
            if not cross_met_support or not cross_met_refute:
                return SubclaimResult(
                    subclaim_id=subclaim.subclaim_id,
                    status="INSUFFICIENT",
                    p=0.5,
                    confidence=0.5,
                    insufficiency_reason="tier2_evidence_mixed_or_insufficient",
                    operationalization=subclaim.operationalization_hint,
                    verdict_scope=subclaim.verdict_scope_hint,
                    provenance_spans=list(subclaim.provenance_spans),
                    human_review_flags=extra_flags or [],
                    synthesis_logic=SynthesisLogic(
                        status_rule_applied="rule_g_tier2_mixed",
                        insufficiency_trigger="tier2_evidence_mixed_or_insufficient",
                        claim_expression_node_type=NodeType.ATOMIC,
                    ),
                )
            # Both sides cross-verified but contradictory -> mixed
            return SubclaimResult(
                subclaim_id=subclaim.subclaim_id,
                status="INSUFFICIENT",
                p=0.5,
                confidence=0.5,
                insufficiency_reason="tier2_evidence_mixed_or_insufficient",
                operationalization=subclaim.operationalization_hint,
                verdict_scope=subclaim.verdict_scope_hint,
                provenance_spans=list(subclaim.provenance_spans),
                human_review_flags=extra_flags or [],
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="rule_g_tier2_mixed",
                    insufficiency_trigger="tier2_evidence_mixed_or_insufficient",
                    claim_expression_node_type=NodeType.ATOMIC,
                ),
            )

        # Only supports
        if supports:
            if not cross_met_support:
                return SubclaimResult(
                    subclaim_id=subclaim.subclaim_id,
                    status="INSUFFICIENT",
                    p=0.5,
                    confidence=0.5,
                    insufficiency_reason="tier2_evidence_mixed_or_insufficient",
                    operationalization=subclaim.operationalization_hint,
                    verdict_scope=subclaim.verdict_scope_hint,
                    provenance_spans=list(subclaim.provenance_spans),
                    human_review_flags=extra_flags or [],
                    synthesis_logic=SynthesisLogic(
                        status_rule_applied="rule_g_tier2_cross_failed",
                        insufficiency_trigger="tier2_evidence_mixed_or_insufficient",
                        claim_expression_node_type=NodeType.ATOMIC,
                    ),
                )
            best = supports[0]
            confidence = _confidence_for_tiers(
                best_tier=2,
                cross_met=True,
                entity_ok=True,
                direction_ok=True,
            )
            return self._make_decisive_result(
                subclaim=subclaim,
                status="SUPPORTED",
                p=1.0,
                tier=2,
                citations=[i.evidence_id for i in supports],
                provenance_spans=list(subclaim.provenance_spans),
                confidence=confidence,
                resolved_value=best.source_value,
                extra_flags=extra_flags,
            )

        # Only refutes
        if refutes:
            if not cross_met_refute:
                return SubclaimResult(
                    subclaim_id=subclaim.subclaim_id,
                    status="INSUFFICIENT",
                    p=0.5,
                    confidence=0.5,
                    insufficiency_reason="tier2_evidence_mixed_or_insufficient",
                    operationalization=subclaim.operationalization_hint,
                    verdict_scope=subclaim.verdict_scope_hint,
                    provenance_spans=list(subclaim.provenance_spans),
                    human_review_flags=extra_flags or [],
                    synthesis_logic=SynthesisLogic(
                        status_rule_applied="rule_g_tier2_cross_failed",
                        insufficiency_trigger="tier2_evidence_mixed_or_insufficient",
                        claim_expression_node_type=NodeType.ATOMIC,
                    ),
                )
            best = refutes[0]
            confidence = _confidence_for_tiers(
                best_tier=2,
                cross_met=True,
                entity_ok=True,
                direction_ok=True,
            )
            return self._make_decisive_result(
                subclaim=subclaim,
                status="REFUTED",
                p=0.0,
                tier=2,
                citations=[i.evidence_id for i in refutes],
                provenance_spans=list(subclaim.provenance_spans),
                confidence=confidence,
                resolved_value=best.source_value,
                extra_flags=extra_flags,
            )

        # Fallback
        return SubclaimResult(
            subclaim_id=subclaim.subclaim_id,
            status="INSUFFICIENT",
            p=0.5,
            confidence=0.5,
            insufficiency_reason="tier2_evidence_mixed_or_insufficient",
            operationalization=subclaim.operationalization_hint,
            verdict_scope=subclaim.verdict_scope_hint,
            provenance_spans=list(subclaim.provenance_spans),
            synthesis_logic=SynthesisLogic(
                status_rule_applied="rule_g_tier2_fallback",
                claim_expression_node_type=NodeType.ATOMIC,
            ),
        )

    def _make_decisive_result(
        self,
        subclaim: AtomicSubclaim,
        status: str,
        p: float,
        tier: int,
        citations: List[str],
        provenance_spans: List[ProvenanceSpan],
        confidence: Optional[float] = None,
        authority_ranking_applied: bool = False,
        resolved_value: Optional[ResolvedValue] = None,
        extra_flags: Optional[List[HumanReviewFlag]] = None,
    ) -> SubclaimResult:
        if confidence is None:
            confidence = _confidence_for_tiers(
                best_tier=tier,
                cross_met=True,
                entity_ok=True,
                direction_ok=True,
            )
        flags = list(extra_flags) if extra_flags else []
        return SubclaimResult(
            subclaim_id=subclaim.subclaim_id,
            status=status,
            p=p,
            confidence=confidence,
            best_evidence_tier=tier,
            limiting_evidence_tier=tier,
            decisive_evidence_tier=tier,
            citations=citations,
            operationalization=subclaim.operationalization_hint,
            verdict_scope=subclaim.verdict_scope_hint,
            provenance_spans=provenance_spans,
            human_review_flags=flags,
            synthesis_logic=SynthesisLogic(
                status_rule_applied="rule_d_tier1_decisive" if tier == 1 else "rule_f_tier2_decisive",
                claim_expression_node_type=NodeType.ATOMIC,
                authority_ranking_applied=authority_ranking_applied,
            ),
            resolved_value=resolved_value,
        )

    def _build_fact_check_result(
        self,
        decomposition: PremiseDecomposition,
        root_result: SubclaimResult,
        atomic_results: List[SubclaimResult],
    ) -> FactCheckResult:
        # Synthesize operationalization from subclaim results
        if root_result.status == "SUPPORTED":
            op = (
                "To refute: provide a primary source that directly contradicts "
                "the claim or shows the cited source is out of scope."
            )
        elif root_result.status == "REFUTED":
            op = (
                "To overturn: provide a primary source that supersedes "
                "the contradicting record."
            )
        else:  # INSUFFICIENT
            if not atomic_results:
                op = "To resolve: locate a primary source that directly addresses this claim."
            else:
                tiers_present = {
                    r.best_evidence_tier for r in atomic_results if r.best_evidence_tier
                }
                if 1 in tiers_present:
                    op = (
                        "To resolve: identify whether the mismatch is caused by "
                        "time scope, geography, or definitional drift."
                    )
                else:
                    op = (
                        "To resolve: locate a primary source; lower-tier "
                        "corroboration alone is not decisive."
                    )

        # Compute insufficiency sensitivity if there are insufficient subclaims
        insufficiency_sensitivity: Dict[str, float] = {}
        if any(r.status == "INSUFFICIENT" for r in atomic_results):
            from .scoring_inputs import compute_insufficiency_sensitivity

            # Wrap atomic results as mini FactCheckResults for sensitivity
            mini_results = []
            for r in atomic_results:
                mini_results.append(
                    FactCheckResult(
                        premise_id=r.subclaim_id,
                        snapshot_id=decomposition.snapshot_id,
                        topic_id=decomposition.topic_id,
                        side=decomposition.side,
                        status=r.status,
                        p=r.p,
                        confidence=r.confidence,
                        best_evidence_tier=r.best_evidence_tier,
                    )
                )
            insufficiency_sensitivity = compute_insufficiency_sensitivity(mini_results)

        return FactCheckResult(
            premise_id=decomposition.premise_id,
            snapshot_id=decomposition.snapshot_id,
            topic_id=decomposition.topic_id,
            side=decomposition.side,
            status=root_result.status,
            p=root_result.p,
            confidence=root_result.confidence,
            best_evidence_tier=root_result.best_evidence_tier,
            limiting_evidence_tier=root_result.limiting_evidence_tier,
            decisive_evidence_tier=root_result.decisive_evidence_tier,
            citations=list(root_result.citations),
            operationalization=op,
            verdict_scope=root_result.verdict_scope,
            insufficiency_reason=root_result.insufficiency_reason,
            human_review_flags=list(root_result.human_review_flags),
            provenance_spans=list(root_result.provenance_spans),
            subclaim_results=atomic_results,
            insufficiency_sensitivity=insufficiency_sensitivity,
            audit_metadata={
                "decomposition_version": decomposition.decomposition_prompt_hash or "v1.5",
                "synthesis_rule_engine_version": "v1.5",
            },
        )
