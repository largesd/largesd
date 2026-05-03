"""
Evidence policy layer for the fact-checking skill.

The policy does not compute probabilities. It decides whether the observed
evidence is strong enough to admit SUPPORTED or REFUTED; otherwise the caller
must emit INSUFFICIENT and the LSD discrete p-value contract maps that to 0.5.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Set, Tuple

from .models import EvidenceTier, SourceConfidence, SourceResult


@dataclass(frozen=True)
class EvidencePolicy:
    """Configurable evidence gating rules."""

    ground_truth_sufficient: bool = True

    tier1_min_sources: int = 1
    tier1_require_unanimity: bool = True

    tier2_can_resolve: bool = True
    tier2_min_sources: int = 1
    tier2_require_unanimity: bool = True

    max_source_age: Optional[timedelta] = None
    source_independence_prefix_length: int = 0
    strict_mode: bool = False
    tier1_require_second_source: bool = False


def default_policy() -> EvidencePolicy:
    return EvidencePolicy()


def strict_policy() -> EvidencePolicy:
    return EvidencePolicy(
        tier2_can_resolve=False,
        strict_mode=True,
    )


def _is_fresh(result: SourceResult, max_age: Optional[timedelta]) -> bool:
    if max_age is None or result.retrieved_at is None:
        return True
    return (datetime.now() - result.retrieved_at) <= max_age


def _count_independent(results: List[SourceResult], prefix_length: int) -> int:
    if prefix_length <= 0:
        return len(results)
    seen: Set[str] = set()
    for result in results:
        key = (
            result.source_id[:prefix_length]
            if len(result.source_id) >= prefix_length
            else result.source_id
        )
        seen.add(key)
    return len(seen)


def _resolve_tier(
    confirms: List[SourceResult],
    contradicts: List[SourceResult],
    min_sources: int,
    require_unanimity: bool,
    require_second_source: bool,
    prefix_length: int,
    tier_label: str,
) -> Tuple[bool, str, str]:
    if not confirms and not contradicts:
        return False, "INSUFFICIENT", ""

    confirm_count = _count_independent(confirms, prefix_length)
    contradict_count = _count_independent(contradicts, prefix_length)

    if require_unanimity and confirms and contradicts:
        return False, "INSUFFICIENT", f"{tier_label} sources disagree."

    if require_unanimity or not (confirms and contradicts):
        winner_label = "SUPPORTED" if confirms else "REFUTED"
        winner_results = confirms if confirms else contradicts
        winner_count = confirm_count if confirms else contradict_count
        loser_count = contradict_count if confirms else confirm_count
        if loser_count and require_unanimity:
            return False, "INSUFFICIENT", f"{tier_label} sources disagree."
    else:
        if confirm_count == contradict_count:
            return False, "INSUFFICIENT", f"{tier_label} sources are split evenly."
        winner_label = "SUPPORTED" if confirm_count > contradict_count else "REFUTED"
        winner_results = confirms if confirm_count > contradict_count else contradicts
        winner_count = max(confirm_count, contradict_count)

    if winner_count < min_sources:
        return False, "INSUFFICIENT", (
            f"Only {winner_count} independent {tier_label} source(s) support the leading verdict; "
            f"policy requires {min_sources}."
        )

    if require_second_source and winner_count < 2:
        return False, "INSUFFICIENT", (
            f"Only one independent {tier_label} source supports the leading verdict; "
            "policy requires corroboration."
        )

    if not require_unanimity and confirms and contradicts:
        relation = "confirmation" if winner_label == "SUPPORTED" else "contradiction"
        return True, winner_label, f"Majority {tier_label} {relation} under non-unanimous policy."

    relation = "confirmation" if winner_label == "SUPPORTED" else "contradiction"
    return True, winner_label, f"Unanimous {tier_label} {relation}."


def apply_policy(
    source_results: List[SourceResult],
    policy: EvidencePolicy,
    from_ground_truth: bool = False,
) -> Tuple[bool, str, str]:
    if not source_results:
        return False, "INSUFFICIENT", "No approved sources returned information for this claim."

    active = [result for result in source_results if _is_fresh(result, policy.max_source_age)]
    if not active:
        return False, "INSUFFICIENT", "All sources are stale; recency filtering removed them."

    ambiguous = [result for result in active if result.confidence == SourceConfidence.AMBIGUOUS]
    if ambiguous:
        return False, "INSUFFICIENT", "At least one source returned ambiguous information."

    tier1_confirms = [
        result for result in active
        if result.tier == EvidenceTier.TIER_1 and result.confidence == SourceConfidence.CONFIRMS
    ]
    tier1_contradicts = [
        result for result in active
        if result.tier == EvidenceTier.TIER_1 and result.confidence == SourceConfidence.CONTRADICTS
    ]

    if from_ground_truth and policy.ground_truth_sufficient and (tier1_confirms or tier1_contradicts):
        sufficient, verdict_hint, reason = _resolve_tier(
            tier1_confirms,
            tier1_contradicts,
            min_sources=1,
            require_unanimity=policy.tier1_require_unanimity,
            require_second_source=False,
            prefix_length=policy.source_independence_prefix_length,
            tier_label="ground-truth",
        )
        if sufficient:
            return True, verdict_hint, "Curated ground truth is sufficient under policy."

    sufficient, verdict_hint, reason = _resolve_tier(
        tier1_confirms,
        tier1_contradicts,
        min_sources=policy.tier1_min_sources,
        require_unanimity=policy.tier1_require_unanimity,
        require_second_source=policy.tier1_require_second_source,
        prefix_length=policy.source_independence_prefix_length,
        tier_label="Tier-1",
    )
    if sufficient:
        return True, verdict_hint, reason
    if reason:
        return False, "INSUFFICIENT", reason

    lower_confirms = [
        result for result in active
        if result.tier in (EvidenceTier.TIER_2, EvidenceTier.TIER_3)
        and result.confidence == SourceConfidence.CONFIRMS
    ]
    lower_contradicts = [
        result for result in active
        if result.tier in (EvidenceTier.TIER_2, EvidenceTier.TIER_3)
        and result.confidence == SourceConfidence.CONTRADICTS
    ]

    if policy.strict_mode or not policy.tier2_can_resolve:
        return False, "INSUFFICIENT", "No Tier-1 resolution path succeeded and policy prohibits lower-tier resolution."

    sufficient, verdict_hint, reason = _resolve_tier(
        lower_confirms,
        lower_contradicts,
        min_sources=policy.tier2_min_sources,
        require_unanimity=policy.tier2_require_unanimity,
        require_second_source=False,
        prefix_length=policy.source_independence_prefix_length,
        tier_label="lower-tier",
    )
    if sufficient:
        return True, verdict_hint, reason
    if reason:
        return False, "INSUFFICIENT", reason

    return False, "INSUFFICIENT", "All queried sources are silent on this claim."
