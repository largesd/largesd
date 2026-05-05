"""
Scoring/dossier adapter for the LSD Fact-Checking System v1.5 (Phase 6).

Responsibilities:
- Group FactCheckResults by topic_id and side
- Compute empirical factuality component F_{t,s}
- Compute F_supported_only (mean over SUPPORTED/REFUTED only)
- Compute insufficiency_rate
- Emit tier counts per topic-side
- Expose inputs for D sensitivity calculation (delta_D computed by dossier layer)
- Handle edge cases: empty premise set → F_{t,s}=null; all-insufficient → 0.5

Per 03_PIPELINE.md §7 (Scoring/Dossier Boundary) and §8 (Aggregation Edge Cases).
Critical rule: The fact-check core does not compute full debate D.
It provides inputs; the scoring layer computes deltas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from skills.fact_checking.v15_models import FactCheckResult, Side


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TopicSideScore:
    """Aggregated factuality scores for a single (topic, side) pair."""

    topic_id: str
    side: Side

    # Core factuality metrics (per 03_PIPELINE.md §7–8)
    F_ts: Optional[float] = None
    """F_{t,s} = mean(p) over selected empirical premises for this topic-side.
    Null when no selected empirical premises exist in the topic-side."""

    F_supported_only: Optional[float] = None
    """Mean(p) over SUPPORTED/REFUTED premises only.
    Null when no SUPPORTED/REFUTED premises exist (including all-insufficient)."""

    insufficiency_rate: Optional[float] = None
    """count(INSUFFICIENT) / count(total selected empirical premises).
    Null when no selected empirical premises exist."""

    # Counts
    premise_count: int = 0
    supported_count: int = 0
    refuted_count: int = 0
    insufficient_count: int = 0

    # Tier distribution (from best_evidence_tier of each premise)
    tier_counts: Dict[int, int] = field(default_factory=dict)

    # Raw inputs exposed for downstream D / delta_D calculation
    # The dossier layer uses these; this adapter does NOT compute D or delta_D.
    premise_ids: List[str] = field(default_factory=list)
    p_values: List[float] = field(default_factory=list)
    statuses: List[str] = field(default_factory=list)
    best_evidence_tiers: List[Optional[int]] = field(default_factory=list)

    insufficiency_sensitivity: Dict[str, float] = field(default_factory=dict)
    """If INSUFFICIENT assumed true/false, F_ts changes by delta_true/delta_false."""

    drop_component_sensitivity: Dict[str, Optional[float]] = field(default_factory=dict)
    """Q recomputed with each component removed. Keys: 'empirical', 'normative', 'reasoning', 'coverage'."""


def _compute_topic_side_score(
    topic_id: str,
    side: Side,
    results: List[FactCheckResult],
) -> TopicSideScore:
    """Compute aggregation metrics for a single (topic, side) group.

    Implements edge cases per 03_PIPELINE.md §8:
    - No selected empirical premises → F_ts=null, F_supported_only=null,
      insufficiency_rate=null
    - All selected empirical premises are INSUFFICIENT → F_ts=0.5,
      F_supported_only=null, insufficiency_rate=1.0
    - Mixed SUPPORTED/REFUTED/INSUFFICIENT → standard means
    - No SUPPORTED/REFUTED premises → F_supported_only=null (not 0.5)
    """
    if not results:
        return TopicSideScore(topic_id=topic_id, side=side)

    premise_count = len(results)
    supported_count = sum(1 for r in results if r.status == "SUPPORTED")
    refuted_count = sum(1 for r in results if r.status == "REFUTED")
    insufficient_count = sum(1 for r in results if r.status == "INSUFFICIENT")

    # Tier counts from best_evidence_tier (skip None)
    tier_counts: Dict[int, int] = {}
    for r in results:
        tier = r.best_evidence_tier
        if tier is not None:
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

    # Collect raw inputs for downstream D sensitivity
    premise_ids = [r.premise_id for r in results]
    p_values = [r.p for r in results]
    statuses = [r.status for r in results]
    best_evidence_tiers = [r.best_evidence_tier for r in results]

    # F_{t,s}: mean(p) over ALL selected empirical premises
    F_ts = sum(p_values) / premise_count

    # F_supported_only: mean(p) over SUPPORTED/REFUTED only
    supported_refuted_p = [r.p for r in results if r.status in ("SUPPORTED", "REFUTED")]
    if supported_refuted_p:
        F_supported_only = sum(supported_refuted_p) / len(supported_refuted_p)
    else:
        F_supported_only = None

    # insufficiency_rate
    insufficiency_rate = insufficient_count / premise_count

    return TopicSideScore(
        topic_id=topic_id,
        side=side,
        F_ts=F_ts,
        F_supported_only=F_supported_only,
        insufficiency_rate=insufficiency_rate,
        premise_count=premise_count,
        supported_count=supported_count,
        refuted_count=refuted_count,
        insufficient_count=insufficient_count,
        tier_counts=tier_counts,
        premise_ids=premise_ids,
        p_values=p_values,
        statuses=statuses,
        best_evidence_tiers=best_evidence_tiers,
    )


class ScoringAdapter:
    """Adapter that groups FactCheckResults by topic/side and computes
    factuality aggregates for the dossier/scoring layer.

    Does NOT compute D, delta_D, or DecisivePremiseRanking.
    Those belong to the dossier layer per the scoring boundary.
    """

    def __init__(self, results: List[FactCheckResult]) -> None:
        self.results = results
        self._grouped: Optional[Dict[Tuple[str, Side], List[FactCheckResult]]] = None
        self._scores: Optional[Dict[Tuple[str, Side], TopicSideScore]] = None

    def _group_by_topic_side(
        self,
    ) -> Dict[Tuple[str, Side], List[FactCheckResult]]:
        """Group FactCheckResults by (topic_id, side)."""
        grouped: Dict[Tuple[str, Side], List[FactCheckResult]] = {}
        for result in self.results:
            key = (result.topic_id, result.side)
            grouped.setdefault(key, []).append(result)
        return grouped

    def compute_scores(self) -> Dict[Tuple[str, Side], TopicSideScore]:
        """Compute TopicSideScore for every (topic_id, side) present in results.

        Returns a dict keyed by (topic_id, Side). Empty input yields empty dict.
        """
        if self._scores is not None:
            return self._scores

        grouped = self._group_by_topic_side()
        scores: Dict[Tuple[str, Side], TopicSideScore] = {}
        for (topic_id, side), results in grouped.items():
            scores[(topic_id, side)] = _compute_topic_side_score(
                topic_id=topic_id, side=side, results=results
            )
        self._scores = scores
        return scores

    def get_score(self, topic_id: str, side: Side) -> Optional[TopicSideScore]:
        """Get the computed score for a specific topic-side, or None."""
        scores = self.compute_scores()
        return scores.get((topic_id, side))

    def all_topic_ids(self) -> List[str]:
        """Return sorted list of unique topic_ids in the input results."""
        return sorted({r.topic_id for r in self.results})

    def all_sides(self, topic_id: str) -> List[Side]:
        """Return list of sides present for a given topic_id."""
        return sorted(
            {r.side for r in self.results if r.topic_id == topic_id},
            key=lambda s: s.value,
        )


def compute_insufficiency_sensitivity(
    results: List[FactCheckResult],
) -> Dict[str, float]:
    """
    Compute how F_ts changes if all INSUFFICIENT premises were
    assumed true (p=1.0) or assumed false (p=0.0).

    Returns {"delta_true": float, "delta_false": float, "max_abs_delta": float}
    """
    insufficient_results = [r for r in results if r.status == "INSUFFICIENT"]
    if not insufficient_results:
        return {"delta_true": 0.0, "delta_false": 0.0, "max_abs_delta": 0.0}

    # Current F_ts
    current = _compute_topic_side_score("", Side.FOR, results).F_ts or 0.5

    # Assume all insufficient → true (p=1.0)
    true_assumed = []
    for r in results:
        if r.status == "INSUFFICIENT":
            copy = FactCheckResult(
                premise_id=r.premise_id,
                snapshot_id=r.snapshot_id,
                topic_id=r.topic_id,
                side=r.side,
                status="SUPPORTED",
                p=1.0,
                confidence=r.confidence,
                best_evidence_tier=r.best_evidence_tier,
            )
            true_assumed.append(copy)
        else:
            true_assumed.append(r)

    f_true = _compute_topic_side_score("", Side.FOR, true_assumed).F_ts or current

    # Assume all insufficient → false (p=0.0)
    false_assumed = []
    for r in results:
        if r.status == "INSUFFICIENT":
            copy = FactCheckResult(
                premise_id=r.premise_id,
                snapshot_id=r.snapshot_id,
                topic_id=r.topic_id,
                side=r.side,
                status="REFUTED",
                p=0.0,
                confidence=r.confidence,
                best_evidence_tier=r.best_evidence_tier,
            )
            false_assumed.append(copy)
        else:
            false_assumed.append(r)

    f_false = _compute_topic_side_score("", Side.FOR, false_assumed).F_ts or current

    delta_true = f_true - current
    delta_false = f_false - current
    max_abs_delta = max(abs(delta_true), abs(delta_false))

    return {
        "delta_true": delta_true,
        "delta_false": delta_false,
        "max_abs_delta": max_abs_delta,
    }


def compute_scoring_inputs(
    results: List[FactCheckResult],
) -> Dict[Tuple[str, Side], TopicSideScore]:
    """Convenience function: compute all topic-side scores in one call.

    Example:
        scores = compute_scoring_inputs(fact_check_results)
        for (topic_id, side), score in scores.items():
            print(f"{topic_id}/{side.value}: F_ts={score.F_ts}")
    """
    adapter = ScoringAdapter(results)
    return adapter.compute_scores()
