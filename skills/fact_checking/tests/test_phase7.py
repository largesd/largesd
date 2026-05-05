"""
Phase 7 unit tests for the LSD Fact-Checking System v1.5.

Covers:
- DisplaySummary generator from SynthesisLogic only
- Consistency checker: status, p, tier, insufficiency_reason
- Failed display summary fallback to machine-generated template
- Bad display prose cannot alter status or p
- Human review queue listing
- Aggregate public counts by review flag with small-count suppression
- Gold test #45: Display summary contradiction rejected
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List

import pytest

from skills.fact_checking.display_summary import (
    ConsistencyCheckResult,
    DisplaySummaryGenerator,
    _check_insufficiency_reason_in_text,
    _check_p_in_text,
    _check_status_in_text,
    _check_tier_in_text,
    _generate_minimal_safe_summary,
    _generate_template_summary,
    check_summary_consistency,
    generate_display_summary,
)
from skills.fact_checking.human_review import (
    HumanReviewQueue,
    QueuedReviewItem,
    compute_aggregate_counts,
)
from skills.fact_checking.v15_audit import DisplaySummary
from skills.fact_checking.v15_models import (
    FactCheckResult,
    HumanReviewFlag,
    NodeType,
    ProvenanceSpan,
    Side,
    SubclaimResult,
    SynthesisLogic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    premise_id: str = "p1",
    status: str = "SUPPORTED",
    p: float = 1.0,
    confidence: float = 1.0,
    best_evidence_tier: int | None = 1,
    insufficiency_reason: str | None = None,
    human_review_flags: List[HumanReviewFlag] | None = None,
    subclaim_results: List[SubclaimResult] | None = None,
    citations: List[str] | None = None,
) -> FactCheckResult:
    return FactCheckResult(
        premise_id=premise_id,
        snapshot_id="snap1",
        topic_id="topic1",
        side=Side.FOR,
        status=status,
        p=p,
        confidence=confidence,
        best_evidence_tier=best_evidence_tier,
        limiting_evidence_tier=best_evidence_tier,
        decisive_evidence_tier=best_evidence_tier,
        citations=citations or ["ev1"],
        operationalization="test_op",
        insufficiency_reason=insufficiency_reason,
        human_review_flags=human_review_flags or [],
        subclaim_results=subclaim_results or [],
    )


def _subclaim(
    subclaim_id: str = "sc1",
    status: str = "SUPPORTED",
    p: float = 1.0,
    tier: int | None = 1,
) -> SubclaimResult:
    return SubclaimResult(
        subclaim_id=subclaim_id,
        status=status,
        p=p,
        confidence=1.0,
        best_evidence_tier=tier,
        citations=["ev1"],
        operationalization="test_op",
        synthesis_logic=SynthesisLogic(
            status_rule_applied="rule_d_tier1_decisive",
            claim_expression_node_type=NodeType.ATOMIC,
        ),
    )


# ---------------------------------------------------------------------------
# DisplaySummary generation from SynthesisLogic
# ---------------------------------------------------------------------------


def test_generate_from_synthesis_logic_supported():
    """Generator produces a DisplaySummary for a SUPPORTED result."""
    result = _result(status="SUPPORTED", p=1.0, best_evidence_tier=1)
    ds, consistency = generate_display_summary(result)

    assert ds.summary_text != ""
    assert "supported" in ds.summary_text.lower() or "supported" in ds.explanation.lower()
    assert consistency.passed is True
    assert ds.generated_at != ""


def test_generate_from_synthesis_logic_refuted():
    """Generator produces a DisplaySummary for a REFUTED result."""
    result = _result(status="REFUTED", p=0.0, best_evidence_tier=1)
    ds, consistency = generate_display_summary(result)

    assert "refuted" in ds.summary_text.lower() or "refuted" in ds.explanation.lower()
    assert consistency.passed is True


def test_generate_from_synthesis_logic_insufficient():
    """Generator produces a DisplaySummary for an INSUFFICIENT result."""
    result = _result(
        status="INSUFFICIENT",
        p=0.5,
        best_evidence_tier=None,
        insufficiency_reason="no_evidence_retrieved",
    )
    ds, consistency = generate_display_summary(result)

    assert "insufficient" in ds.summary_text.lower() or "insufficient" in ds.explanation.lower()
    assert consistency.passed is True
    assert "no evidence" in ds.explanation.lower() or "insufficient" in ds.explanation.lower()


# ---------------------------------------------------------------------------
# Consistency checker — status
# ---------------------------------------------------------------------------


def test_status_consistency_supported_vs_refuted_text():
    """Text saying 'refuted' when status=SUPPORTED is a violation."""
    text = "this claim is refuted by all evidence"
    assert _check_status_in_text("SUPPORTED", text) is not None


def test_status_consistency_supported_ok():
    """Text saying 'supported' when status=SUPPORTED is fine."""
    text = "this claim is supported by evidence"
    assert _check_status_in_text("SUPPORTED", text) is None


def test_status_consistency_refuted_vs_supported_text():
    """Text saying 'supported' when status=REFUTED is a violation."""
    text = "this claim is supported"
    assert _check_status_in_text("REFUTED", text) is not None


def test_status_consistency_insufficient_vs_supported_text():
    """Text saying 'supported' when status=INSUFFICIENT is a violation."""
    text = "this claim is supported"
    assert _check_status_in_text("INSUFFICIENT", text) is not None


def test_status_consistency_insufficient_vs_refuted_text():
    """Text saying 'false' when status=INSUFFICIENT is a violation."""
    text = "this claim is false"
    assert _check_status_in_text("INSUFFICIENT", text) is not None


# ---------------------------------------------------------------------------
# Consistency checker — p
# ---------------------------------------------------------------------------


def test_p_consistency_mismatch():
    """Text stating p=0.0 when result p=1.0 is a violation."""
    text = "the p value is 0.0"
    assert _check_p_in_text(1.0, text) is not None


def test_p_consistency_match():
    """Text stating p=1.0 when result p=1.0 is fine."""
    text = "the p value is 1.0"
    assert _check_p_in_text(1.0, text) is None


def test_p_consistency_percentage_mismatch():
    """Text saying 0% when p=1.0 is a violation."""
    text = "the claim has 0% support"
    assert _check_p_in_text(1.0, text) is not None


def test_p_consistency_percentage_match():
    """Text saying 100% when p=1.0 is fine."""
    text = "the claim has 100% support"
    assert _check_p_in_text(1.0, text) is None


# ---------------------------------------------------------------------------
# Consistency checker — tier
# ---------------------------------------------------------------------------


def test_tier_consistency_mismatch():
    """Text saying 'tier 2' when best_evidence_tier=1 is a violation."""
    text = "evidence is tier 2"
    assert _check_tier_in_text(1, text) is not None


def test_tier_consistency_match():
    """Text saying 'tier 1' when best_evidence_tier=1 is fine."""
    text = "evidence is tier 1"
    assert _check_tier_in_text(1, text) is None


def test_tier_consistency_none():
    """When tier is None, no tier check is performed."""
    text = "evidence is tier 1"
    assert _check_tier_in_text(None, text) is None


# ---------------------------------------------------------------------------
# Consistency checker — insufficiency_reason
# ---------------------------------------------------------------------------


def test_reason_consistency_wrong_reason():
    """Text implying 'connector_failure' when actual reason is 'no_evidence_retrieved'."""
    text = "a connector failure prevented retrieval"
    assert _check_insufficiency_reason_in_text("no_evidence_retrieved", text) is not None


def test_reason_consistency_correct_reason():
    """Text matching actual reason is fine."""
    text = "no evidence was retrieved for this claim"
    assert _check_insufficiency_reason_in_text("no_evidence_retrieved", text) is None


def test_reason_consistency_none():
    """When reason is None, any text is fine."""
    text = "any text here"
    assert _check_insufficiency_reason_in_text(None, text) is None


# ---------------------------------------------------------------------------
# Full consistency check integration
# ---------------------------------------------------------------------------


def test_full_consistency_pass():
    """A template-generated summary should always pass consistency."""
    result = _result(status="SUPPORTED", p=1.0, best_evidence_tier=1)
    ds = _generate_template_summary(result)
    consistency = check_summary_consistency(ds, result)
    assert consistency.passed is True
    assert consistency.violations == []


def test_full_consistency_fail_bad_custom_text():
    """Custom text that contradicts status should fail."""
    result = _result(status="SUPPORTED", p=1.0, best_evidence_tier=1)
    bad_summary = DisplaySummary(
        summary_text="This claim is refuted.",
        explanation="",
    )
    consistency = check_summary_consistency(bad_summary, result)
    assert consistency.passed is False
    assert any("status_inconsistency" in v for v in consistency.violations)


# ---------------------------------------------------------------------------
# Fallback to machine-generated template (Gold test #45)
# ---------------------------------------------------------------------------


def test_display_summary_contradiction_rejected_fallback():
    """
    Gold test #45: Display summary contradiction rejected →
    Fallback to machine-generated template.
    """
    result = _result(status="SUPPORTED", p=1.0, best_evidence_tier=1)

    # Provide custom text that contradicts the authoritative result
    ds, consistency = generate_display_summary(
        result=result,
        custom_summary_text="This claim is refuted by all available evidence.",
        custom_explanation="p = 0.0; the claim is false.",
    )

    # The generator should have rejected the custom text and fallen back
    assert "refuted" not in ds.summary_text.lower() or "refuted" not in ds.explanation.lower()
    assert "supported" in ds.summary_text.lower() or "supported" in ds.explanation.lower()
    assert consistency.passed is True


def test_fallback_generates_valid_display_summary():
    """Even with completely wrong input, fallback yields a valid summary."""
    result = _result(
        status="INSUFFICIENT",
        p=0.5,
        best_evidence_tier=None,
        insufficiency_reason="predictive_claim_not_checkable",
    )

    ds, consistency = generate_display_summary(
        result=result,
        custom_summary_text="100% true and verified!!!",
        custom_explanation="Tier 1 official source confirms p=1.0",
    )

    assert consistency.passed is True
    assert "insufficient" in ds.summary_text.lower() or "insufficient" in ds.explanation.lower()


# ---------------------------------------------------------------------------
# Minimal safe summary
# ---------------------------------------------------------------------------


def test_minimal_safe_summary_always_consistent():
    """The minimal safe summary must always pass consistency."""
    for status, p, tier in [
        ("SUPPORTED", 1.0, 1),
        ("REFUTED", 0.0, 1),
        ("INSUFFICIENT", 0.5, None),
    ]:
        result = _result(status=status, p=p, best_evidence_tier=tier)
        ds = _generate_minimal_safe_summary(result)
        consistency = check_summary_consistency(ds, result)
        assert consistency.passed is True, f"Failed for status={status}"


# ---------------------------------------------------------------------------
# Compound premise display summaries
# ---------------------------------------------------------------------------


def test_compound_premise_subclaim_breakdown():
    """A compound premise includes subclaim breakdown in the explanation."""
    subclaims = [
        _subclaim("sc1", "SUPPORTED", 1.0, 1),
        _subclaim("sc2", "REFUTED", 0.0, 1),
    ]
    result = _result(
        status="REFUTED",
        p=0.0,
        best_evidence_tier=1,
        subclaim_results=subclaims,
    )
    ds, consistency = generate_display_summary(result)
    assert consistency.passed is True
    assert "sc1" in ds.explanation or "sc2" in ds.explanation


# ---------------------------------------------------------------------------
# Human review queue listing
# ---------------------------------------------------------------------------


def test_review_queue_listing():
    """Queue can list pending items."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "queue.db")
        queue = HumanReviewQueue(db_path=db_path)

        queue.enqueue(
            audit_id="audit_1",
            premise_id="p1",
            snapshot_id="snap1",
            premise_text="Test premise one",
            flags=[HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE],
        )
        queue.enqueue(
            audit_id="audit_2",
            premise_id="p2",
            snapshot_id="snap1",
            premise_text="Test premise two",
            flags=[HumanReviewFlag.POLICY_GAP],
        )
        queue.enqueue(
            audit_id="audit_3",
            premise_id="p3",
            snapshot_id="snap2",
            premise_text="Test premise three",
            flags=[HumanReviewFlag.SCOPE_MISMATCH],
        )

        # List all pending
        all_pending = queue.list_pending()
        assert len(all_pending) == 3

        # Filter by snapshot
        snap1_pending = queue.list_pending(snapshot_id="snap1")
        assert len(snap1_pending) == 2
        assert all(item.snapshot_id == "snap1" for item in snap1_pending)


def test_review_queue_assign_and_complete():
    """Items can be assigned and completed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "queue.db")
        queue = HumanReviewQueue(db_path=db_path)

        queue.enqueue(
            audit_id="audit_1",
            premise_id="p1",
            snapshot_id="snap1",
            premise_text="Test premise",
            flags=[HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE],
        )

        pending_before = queue.list_pending()
        assert len(pending_before) == 1

        # Assign
        assert queue.assign("queue_audit_1", "reviewer_a") is True
        pending_after_assign = queue.list_pending()
        assert len(pending_after_assign) == 0

        # Complete
        from skills.fact_checking.v15_models import ReviewOutcome
        assert queue.complete("queue_audit_1", ReviewOutcome.REVIEWED_NO_CHANGE) is True


# ---------------------------------------------------------------------------
# Aggregate counts with small-count suppression
# ---------------------------------------------------------------------------


def test_aggregate_counts_suppress_small():
    """Counts below threshold are suppressed to 0 with a note."""

    class FakeRecord:
        def __init__(self, flags):
            self.human_review_flags = flags

    records = [
        FakeRecord([HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE]),
        FakeRecord([HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE]),
        FakeRecord([HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE]),
        FakeRecord([HumanReviewFlag.POLICY_GAP]),
        FakeRecord([HumanReviewFlag.SCOPE_MISMATCH]),
        FakeRecord([HumanReviewFlag.SCOPE_MISMATCH]),
    ]

    result = compute_aggregate_counts(records, small_count_threshold=3)
    assert result["total_records"] == 6
    assert result["flag_counts"]["CONTRADICTORY_TIER1_EVIDENCE"] == 3
    # POLICY_GAP (1) and SCOPE_MISMATCH (2) are below threshold=3
    assert result["flag_counts"]["POLICY_GAP"] == 0
    assert result["flag_counts"]["SCOPE_MISMATCH"] == 0
    assert len(result["suppression_notes"]) == 2


def test_aggregate_counts_no_suppression():
    """When all counts are above threshold, nothing is suppressed."""

    class FakeRecord:
        def __init__(self, flags):
            self.human_review_flags = flags

    records = [
        FakeRecord([HumanReviewFlag.POLICY_GAP]),
        FakeRecord([HumanReviewFlag.POLICY_GAP]),
        FakeRecord([HumanReviewFlag.POLICY_GAP]),
    ]

    result = compute_aggregate_counts(records, small_count_threshold=2)
    assert result["flag_counts"]["POLICY_GAP"] == 3
    assert result["suppression_notes"] == []


# ---------------------------------------------------------------------------
# Bad display prose cannot alter status or p
# ---------------------------------------------------------------------------


def test_bad_display_prose_does_not_alter_result():
    """
    Even if custom text is completely wrong, the returned FactCheckResult
    fields (status, p) are unchanged; only the DisplaySummary is regenerated.
    """
    result = _result(status="SUPPORTED", p=1.0, best_evidence_tier=1)
    original_status = result.status
    original_p = result.p

    ds, consistency = generate_display_summary(
        result=result,
        custom_summary_text="This is completely false and refuted.",
    )

    # Result fields unchanged
    assert result.status == original_status
    assert result.p == original_p
    # Fallback summary is consistent
    assert consistency.passed is True


# ---------------------------------------------------------------------------
# Review queue exists even if dashboard is minimal
# ---------------------------------------------------------------------------


def test_minimal_queue_always_initializes():
    """HumanReviewQueue initializes and can list even when empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "queue.db")
        queue = HumanReviewQueue(db_path=db_path)
        pending = queue.list_pending()
        assert pending == []


# ---------------------------------------------------------------------------
# Tier and flag display in generated summaries
# ---------------------------------------------------------------------------


def test_tier_displayed_in_summary():
    """Tier 1 results mention Tier 1 in the explanation."""
    result = _result(status="SUPPORTED", p=1.0, best_evidence_tier=1)
    ds, _ = generate_display_summary(result)
    assert "tier 1" in ds.explanation.lower() or "tier 1" in ds.summary_text.lower()


def test_human_review_flags_displayed():
    """Summaries include human review flags when present."""
    result = _result(
        status="INSUFFICIENT",
        p=0.5,
        best_evidence_tier=None,
        insufficiency_reason="policy_gap",
        human_review_flags=[HumanReviewFlag.POLICY_GAP],
    )
    ds, consistency = generate_display_summary(result)
    assert consistency.passed is True
    assert "policy gap" in ds.explanation.lower()
