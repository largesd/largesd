"""
Evidence policy layer for LSD §13 Perfect Fact Checker.

Defines when evidence is sufficient for SUPPORTED or REFUTED,
when conflict forces INSUFFICIENT, and temporal / independence rules.

The policy is the single source of truth for adjudication gating.
It does not compute p-values; it decides whether a verdict is admissible.
When admissible, LSD assigns p ∈ {1.0, 0.0}.
When inadmissible, LSD assigns p = 0.5 (INSUFFICIENT).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Set
from .models import SourceResult, SourceConfidence, EvidenceTier


@dataclass(frozen=True)
class EvidencePolicy:
    """
    Configurable evidence policy.

    Defaults are backward-compatible (Tier-1 unanimous and Tier-2/3 unanimous
    both sufficient).  Use ``strict_policy()`` for debate production where
    only ground-truth and verified Tier-1 structured matches may resolve.
    """

    # Ground-truth entries are always sufficient (human-curated).
    ground_truth_sufficient: bool = True

    # Tier 1 -----------------------------------------------------------
    tier1_min_sources: int = 1
    tier1_require_unanimity: bool = True

    # Tier 2 / Tier 3 --------------------------------------------------
    tier2_can_resolve: bool = True
    tier2_min_sources: int = 1
    tier2_require_unanimity: bool = True

    # Temporal freshness: sources older than this are ignored.
    # None = no age limit.
    max_source_age: Optional[timedelta] = None

    # Independence: sources whose IDs share this prefix length are
    # treated as the same origin and counted once.
    # 0 = every source_id is independent.
    source_independence_prefix_length: int = 0

    # Strict mode: if True, Tier-2/3 can never produce SUPPORTED/REFUTED.
    strict_mode: bool = False

    # When a single Tier-1 source speaks and no conflict exists,
    # require a second independent Tier-1 source before SUPPORTED/REFUTED.
    # This is the safest setting for live connectors.
    tier1_require_second_source: bool = False


# ---------------------------------------------------------------------------
# Pre-defined policies
# ---------------------------------------------------------------------------

def default_policy() -> EvidencePolicy:
    """Legacy-compatible policy."""
    return EvidencePolicy()


def strict_policy() -> EvidencePolicy:
    """
    Conservative policy recommended for production debates.
    Only Tier-1 (and ground-truth) may resolve; Tier-2/3 always INSUFFICIENT.
    Tier-1 requires 2 independent agreeing sources.
    """
    return EvidencePolicy(
        tier2_can_resolve=False,
        strict_mode=True,
        tier1_require_second_source=True,
    )


# ---------------------------------------------------------------------------
# Policy application helpers
# ---------------------------------------------------------------------------

def _is_fresh(result: SourceResult, max_age: Optional[timedelta]) -> bool:
    """Return False if the source result is older than max_age."""
    if max_age is None:
        return True
    if result.retrieved_at is None:
        return True
    age = datetime.now() - result.retrieved_at
    return age <= max_age


def _count_independent(
    results: List[SourceResult],
    prefix_length: int,
) -> int:
    """Count distinct origins after grouping by source_id prefix."""
    if prefix_length <= 0:
        return len(results)
    seen: Set[str] = set()
    for r in results:
        key = r.source_id[:prefix_length] if len(r.source_id) >= prefix_length else r.source_id
        seen.add(key)
    return len(seen)


def apply_policy(
    source_results: List[SourceResult],
    policy: EvidencePolicy,
    from_ground_truth: bool = False,
) -> tuple:
    """
    Apply evidence policy to source results.

    Returns (is_sufficient, verdict_hint, reason) where:
    - is_sufficient: bool — whether policy permits SUPPORTED/REFUTED
    - verdict_hint: "SUPPORTED" | "REFUTED" | "INSUFFICIENT" | None
    - reason: human-readable explanation

    The caller (``_adjudicate``) maps verdict_hint to the actual
    ``FactCheckVerdict`` and p-value per LSD §13.
    """
    if not source_results:
        return False, "INSUFFICIENT", "No approved sources returned information for this claim."

    # 1. Filter stale sources
    active = [r for r in source_results if _is_fresh(r, policy.max_source_age)]
    if not active:
        return False, "INSUFFICIENT", "All sources are stale; recency filter removed them."

    # 2. Split by tier and confidence
    confirms_t1 = [r for r in active
                   if r.confidence == SourceConfidence.CONFIRMS and r.tier == EvidenceTier.TIER_1]
    contradicts_t1 = [r for r in active
                      if r.confidence == SourceConfidence.CONTRADICTS and r.tier == EvidenceTier.TIER_1]
    ambiguous = [r for r in active if r.confidence == SourceConfidence.AMBIGUOUS]

    if ambiguous:
        return False, "INSUFFICIENT", "At least one source returned ambiguous information."

    # 3. Tier-1 conflict → always INSUFFICIENT
    if confirms_t1 and contradicts_t1:
        return False, "INSUFFICIENT", "Primary sources disagree: some confirm, some contradict."

    # 4. Tier-1 unanimous confirm
    if confirms_t1 and not contradicts_t1:
        if from_ground_truth and policy.ground_truth_sufficient:
            return True, "SUPPORTED", "Ground-truth entry confirms."

        indep = _count_independent(confirms_t1, policy.source_independence_prefix_length)
        if indep < policy.tier1_min_sources:
            return False, "INSUFFICIENT", (
                f"Only {indep} independent Tier-1 source(s) confirm; "
                f"policy requires {policy.tier1_min_sources}."
            )
        if policy.tier1_require_second_source and indep < 2:
            return False, "INSUFFICIENT", (
                "Only one independent Tier-1 source confirms; "
                "policy requires corroboration."
            )
        return True, "SUPPORTED", "Unanimous confirmation from primary sources."

    # 5. Tier-1 unanimous contradict
    if contradicts_t1 and not confirms_t1:
        if from_ground_truth and policy.ground_truth_sufficient:
            return True, "REFUTED", "Ground-truth entry contradicts."

        indep = _count_independent(contradicts_t1, policy.source_independence_prefix_length)
        if indep < policy.tier1_min_sources:
            return False, "INSUFFICIENT", (
                f"Only {indep} independent Tier-1 source(s) contradict; "
                f"policy requires {policy.tier1_min_sources}."
            )
        if policy.tier1_require_second_source and indep < 2:
            return False, "INSUFFICIENT", (
                "Only one independent Tier-1 source contradicts; "
                "policy requires corroboration."
            )
        return True, "REFUTED", "Unanimous contradiction from primary sources."

    # 6. No Tier-1; evaluate Tier-2/3
    confirms_lower = [r for r in active if r.confidence == SourceConfidence.CONFIRMS]
    contradicts_lower = [r for r in active if r.confidence == SourceConfidence.CONTRADICTS]

    if policy.strict_mode or not policy.tier2_can_resolve:
        return False, "INSUFFICIENT", (
            "No Tier-1 sources available and policy prohibits Tier-2/3 resolution."
        )

    if confirms_lower and contradicts_lower:
        return False, "INSUFFICIENT", "Secondary/tertiary sources disagree."

    if confirms_lower:
        indep = _count_independent(confirms_lower, policy.source_independence_prefix_length)
        if indep < policy.tier2_min_sources:
            return False, "INSUFFICIENT", (
                f"Only {indep} independent lower-tier source(s) confirm; "
                f"policy requires {policy.tier2_min_sources}."
            )
        return True, "SUPPORTED", "Confirmed by secondary/tertiary sources (no primary available)."

    if contradicts_lower:
        indep = _count_independent(contradicts_lower, policy.source_independence_prefix_length)
        if indep < policy.tier2_min_sources:
            return False, "INSUFFICIENT", (
                f"Only {indep} independent lower-tier source(s) contradict; "
                f"policy requires {policy.tier2_min_sources}."
            )
        return True, "REFUTED", "Contradicted by secondary/tertiary sources (no primary available)."

    return False, "INSUFFICIENT", "All queried sources are silent on this claim."
