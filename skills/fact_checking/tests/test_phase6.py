"""
Phase 6 unit tests for the LSD Fact-Checking System v1.5.

Covers:
- Empty premise set aggregation → F_ts=null
- All-insufficient aggregation → F_ts=0.5, F_supported_only=null
- Mixed SUPPORTED/REFUTED/INSUFFICIENT aggregation
- F_supported_only excludes insufficient claims
- No SUPPORTED/REFUTED premises → F_supported_only=null (not 0.5)
- Tier counts per topic-side
- Multiple topic-side groups
- ScoringAdapter API surface
- Does not compute D or delta_D
"""

from __future__ import annotations

from skills.fact_checking.scoring_inputs import (
    ScoringAdapter,
    TopicSideScore,
    _compute_topic_side_score,
    compute_scoring_inputs,
)
from skills.fact_checking.v15_models import FactCheckResult, Side

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    premise_id: str = "p1",
    topic_id: str = "t1",
    side: Side = Side.FOR,
    status: str = "SUPPORTED",
    p: float = 1.0,
    best_evidence_tier: int | None = 1,
) -> FactCheckResult:
    return FactCheckResult(
        premise_id=premise_id,
        snapshot_id="snap1",
        topic_id=topic_id,
        side=side,
        status=status,
        p=p,
        confidence=1.0,
        best_evidence_tier=best_evidence_tier,
        citations=["ev1"],
        operationalization="test_op",
    )


# ---------------------------------------------------------------------------
# Edge case tests per 03_PIPELINE.md §8
# ---------------------------------------------------------------------------


def test_empty_premise_set():
    """No selected empirical premises → all metrics null. (Gold test #42)"""
    score = _compute_topic_side_score("t1", Side.FOR, [])
    assert score.F_ts is None
    assert score.F_supported_only is None
    assert score.insufficiency_rate is None
    assert score.premise_count == 0


def test_empty_via_adapter():
    """Adapter with empty input returns empty scores dict."""
    adapter = ScoringAdapter([])
    scores = adapter.compute_scores()
    assert scores == {}
    assert adapter.get_score("t1", Side.FOR) is None


def test_all_insufficient():
    """All selected empirical premises are INSUFFICIENT → F_ts=0.5,
    F_supported_only=null, insufficiency_rate=1.0. (Gold test #43)"""
    results = [
        _result(premise_id="p1", status="INSUFFICIENT", p=0.5, best_evidence_tier=None),
        _result(premise_id="p2", status="INSUFFICIENT", p=0.5, best_evidence_tier=None),
    ]
    score = _compute_topic_side_score("t1", Side.FOR, results)
    assert score.F_ts == 0.5
    assert score.F_supported_only is None
    assert score.insufficiency_rate == 1.0
    assert score.premise_count == 2
    assert score.supported_count == 0
    assert score.refuted_count == 0
    assert score.insufficient_count == 2


def test_mixed_supported_refuted_insufficient():
    """Mixed SUPPORTED/REFUTED/INSUFFICIENT → standard means. (Gold test #44)"""
    results = [
        _result(premise_id="p1", status="SUPPORTED", p=1.0, best_evidence_tier=1),
        _result(premise_id="p2", status="REFUTED", p=0.0, best_evidence_tier=1),
        _result(premise_id="p3", status="INSUFFICIENT", p=0.5, best_evidence_tier=None),
    ]
    score = _compute_topic_side_score("t1", Side.FOR, results)
    # F_ts = mean(1.0, 0.0, 0.5) = 1.5 / 3 = 0.5
    assert score.F_ts == 0.5
    # F_supported_only = mean(1.0, 0.0) = 0.5
    assert score.F_supported_only == 0.5
    assert score.insufficiency_rate == 1 / 3
    assert score.premise_count == 3
    assert score.supported_count == 1
    assert score.refuted_count == 1
    assert score.insufficient_count == 1


def test_all_supported():
    """All SUPPORTED → F_ts=1.0, F_supported_only=1.0, insufficiency_rate=0.0."""
    results = [
        _result(premise_id="p1", status="SUPPORTED", p=1.0, best_evidence_tier=1),
        _result(premise_id="p2", status="SUPPORTED", p=1.0, best_evidence_tier=2),
    ]
    score = _compute_topic_side_score("t1", Side.FOR, results)
    assert score.F_ts == 1.0
    assert score.F_supported_only == 1.0
    assert score.insufficiency_rate == 0.0
    assert score.supported_count == 2
    assert score.refuted_count == 0
    assert score.insufficient_count == 0


def test_all_refuted():
    """All REFUTED → F_ts=0.0, F_supported_only=0.0, insufficiency_rate=0.0."""
    results = [
        _result(premise_id="p1", status="REFUTED", p=0.0, best_evidence_tier=1),
        _result(premise_id="p2", status="REFUTED", p=0.0, best_evidence_tier=1),
    ]
    score = _compute_topic_side_score("t1", Side.FOR, results)
    assert score.F_ts == 0.0
    assert score.F_supported_only == 0.0
    assert score.insufficiency_rate == 0.0
    assert score.supported_count == 0
    assert score.refuted_count == 2
    assert score.insufficient_count == 0


def test_no_supported_refuted_premises():
    """No SUPPORTED/REFUTED premises → F_supported_only=null (not 0.5)."""
    results = [
        _result(premise_id="p1", status="INSUFFICIENT", p=0.5, best_evidence_tier=None),
    ]
    score = _compute_topic_side_score("t1", Side.FOR, results)
    assert score.F_ts == 0.5
    assert score.F_supported_only is None
    assert score.insufficiency_rate == 1.0


def test_single_premise():
    """Single premise aggregates correctly."""
    results = [_result(premise_id="p1", status="SUPPORTED", p=1.0, best_evidence_tier=1)]
    score = _compute_topic_side_score("t1", Side.FOR, results)
    assert score.F_ts == 1.0
    assert score.F_supported_only == 1.0
    assert score.insufficiency_rate == 0.0
    assert score.premise_count == 1


# ---------------------------------------------------------------------------
# Tier counts
# ---------------------------------------------------------------------------


def test_tier_counts():
    """Tier counts aggregate best_evidence_tier per premise."""
    results = [
        _result(premise_id="p1", status="SUPPORTED", p=1.0, best_evidence_tier=1),
        _result(premise_id="p2", status="SUPPORTED", p=1.0, best_evidence_tier=1),
        _result(premise_id="p3", status="SUPPORTED", p=1.0, best_evidence_tier=2),
        _result(premise_id="p4", status="INSUFFICIENT", p=0.5, best_evidence_tier=None),
    ]
    score = _compute_topic_side_score("t1", Side.FOR, results)
    assert score.tier_counts == {1: 2, 2: 1}


def test_tier_counts_all_none():
    """When all best_evidence_tier are None, tier_counts is empty."""
    results = [
        _result(premise_id="p1", status="INSUFFICIENT", p=0.5, best_evidence_tier=None),
    ]
    score = _compute_topic_side_score("t1", Side.FOR, results)
    assert score.tier_counts == {}


# ---------------------------------------------------------------------------
# Multi-group / adapter API
# ---------------------------------------------------------------------------


def test_multiple_topic_side_groups():
    """Adapter correctly separates results by (topic_id, side)."""
    results = [
        _result(premise_id="p1", topic_id="t1", side=Side.FOR, status="SUPPORTED", p=1.0),
        _result(premise_id="p2", topic_id="t1", side=Side.FOR, status="REFUTED", p=0.0),
        _result(premise_id="p3", topic_id="t1", side=Side.AGAINST, status="SUPPORTED", p=1.0),
        _result(premise_id="p4", topic_id="t2", side=Side.FOR, status="INSUFFICIENT", p=0.5),
    ]
    adapter = ScoringAdapter(results)
    scores = adapter.compute_scores()

    assert len(scores) == 3

    # t1/FOR: mean(1.0, 0.0) = 0.5
    s_t1_for = scores[("t1", Side.FOR)]
    assert s_t1_for.F_ts == 0.5
    assert s_t1_for.F_supported_only == 0.5
    assert s_t1_for.premise_count == 2

    # t1/AGAINST: mean(1.0) = 1.0
    s_t1_against = scores[("t1", Side.AGAINST)]
    assert s_t1_against.F_ts == 1.0
    assert s_t1_against.F_supported_only == 1.0
    assert s_t1_against.premise_count == 1

    # t2/FOR: all insufficient
    s_t2_for = scores[("t2", Side.FOR)]
    assert s_t2_for.F_ts == 0.5
    assert s_t2_for.F_supported_only is None
    assert s_t2_for.insufficiency_rate == 1.0
    assert s_t2_for.premise_count == 1


def test_adapter_get_score():
    """get_score returns correct score or None."""
    results = [
        _result(premise_id="p1", topic_id="t1", side=Side.FOR, status="SUPPORTED", p=1.0),
    ]
    adapter = ScoringAdapter(results)
    score = adapter.get_score("t1", Side.FOR)
    assert score is not None
    assert score.F_ts == 1.0
    assert adapter.get_score("t1", Side.AGAINST) is None
    assert adapter.get_score("missing", Side.FOR) is None


def test_adapter_topic_and_side_lists():
    """all_topic_ids and all_sides return correct collections."""
    results = [
        _result(premise_id="p1", topic_id="t2", side=Side.FOR),
        _result(premise_id="p2", topic_id="t1", side=Side.AGAINST),
        _result(premise_id="p3", topic_id="t1", side=Side.FOR),
    ]
    adapter = ScoringAdapter(results)
    assert adapter.all_topic_ids() == ["t1", "t2"]
    assert adapter.all_sides("t1") == [Side.AGAINST, Side.FOR]
    assert adapter.all_sides("t2") == [Side.FOR]
    assert adapter.all_sides("missing") == []


def test_compute_scoring_inputs_convenience():
    """compute_scoring_inputs is a convenience wrapper returning same data."""
    results = [
        _result(premise_id="p1", topic_id="t1", side=Side.FOR, status="SUPPORTED", p=1.0),
        _result(premise_id="p2", topic_id="t1", side=Side.FOR, status="REFUTED", p=0.0),
    ]
    scores = compute_scoring_inputs(results)
    assert len(scores) == 1
    score = scores[("t1", Side.FOR)]
    assert score.F_ts == 0.5
    assert score.F_supported_only == 0.5


# ---------------------------------------------------------------------------
# Raw inputs exposed for D sensitivity
# ---------------------------------------------------------------------------


def test_raw_inputs_exposed():
    """TopicSideScore exposes raw p_values, statuses, premise_ids for dossier layer."""
    results = [
        _result(premise_id="p1", status="SUPPORTED", p=1.0, best_evidence_tier=1),
        _result(premise_id="p2", status="INSUFFICIENT", p=0.5, best_evidence_tier=None),
    ]
    score = _compute_topic_side_score("t1", Side.FOR, results)
    assert score.premise_ids == ["p1", "p2"]
    assert score.p_values == [1.0, 0.5]
    assert score.statuses == ["SUPPORTED", "INSUFFICIENT"]
    assert score.best_evidence_tiers == [1, None]


# ---------------------------------------------------------------------------
# Scoring boundary: adapter does NOT compute D or delta_D
# ---------------------------------------------------------------------------


def test_no_d_computation():
    """The adapter and TopicSideScore must not contain D, delta_D, or
    DecisivePremiseRanking fields. (Per 03_PIPELINE.md §7 critical rule)"""
    score = TopicSideScore(topic_id="t1", side=Side.FOR)
    # Ensure these fields are absent from the dataclass
    forbidden = {
        "D",
        "delta_D",
        "delta_D_true",
        "delta_D_false",
        "max_abs_delta_D",
        "decisive_premise_ranking",
        "overall_for",
        "overall_against",
    }
    actual_fields = {f.name for f in score.__dataclass_fields__.values()}
    assert actual_fields.isdisjoint(
        forbidden
    ), f"TopicSideScore must not contain dossier-computed fields: {actual_fields & forbidden}"
