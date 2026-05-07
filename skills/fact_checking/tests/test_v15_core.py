"""
Phase 1 deterministic core unit tests for the LSD Fact-Checking System v1.5.

Covers:
- supported / refuted atomic claims
- no evidence → INSUFFICIENT
- Tier 3 only → INSUFFICIENT
- contradictory Tier 1 unresolved / resolved by authority ranking
- Tier 2 cross-verification satisfied / failed
- AND / OR / NOT / IF_THEN logic
- comparison true / false / missing value
- scope mismatch
- entity failure
- all-insufficient aggregation edge case
"""

from __future__ import annotations

from skills.fact_checking.synthesis import SynthesisEngine
from skills.fact_checking.v15_models import (
    AtomicSubclaim,
    ClaimExpression,
    ClaimType,
    Direction,
    EvidenceItem,
    HumanReviewFlag,
    NodeType,
    PremiseDecomposition,
    ResolvedValue,
    Side,
    ValueType,
    VerdictScope,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subclaim(sid: str, claim_type: ClaimType = ClaimType.EMPIRICAL_ATOMIC) -> AtomicSubclaim:
    return AtomicSubclaim(
        subclaim_id=sid,
        parent_premise_id="p1",
        text=f"claim {sid}",
        claim_type=claim_type,
        operationalization_hint="test",
        verdict_scope_hint=VerdictScope(),
    )


def _evidence(
    sid: str,
    tier: int,
    direction: Direction,
    direction_confidence: float = 1.0,
    relevance_score: float = 1.0,
    authority: str = "",
    group_id: str | None = None,
    source_value: ResolvedValue | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        subclaim_id=sid,
        source_tier=tier,
        direction=direction,
        direction_confidence=direction_confidence,
        relevance_score=relevance_score,
        source_authority=authority,
        source_independence_group_id=group_id,
        source_value=source_value,
    )


def _decomposition(root: ClaimExpression, subclaims: list[AtomicSubclaim]) -> PremiseDecomposition:
    return PremiseDecomposition(
        premise_id="p1",
        snapshot_id="snap1",
        original_text="test premise",
        topic_id="t1",
        side=Side.FOR,
        root_claim_expression=root,
        atomic_subclaims=subclaims,
    )


def _atomic_expr(sid: str) -> ClaimExpression:
    return ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id=sid)


# ---------------------------------------------------------------------------
# Atomic synthesis tests
# ---------------------------------------------------------------------------


def test_supported_atomic_claim():
    sc = _subclaim("sc1")
    root = _atomic_expr("sc1")
    dec = _decomposition(root, [sc])
    ev = [_evidence("sc1", tier=1, direction=Direction.SUPPORTS)]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "SUPPORTED"
    assert result.p == 1.0
    assert result.best_evidence_tier == 1
    assert result.confidence >= 0.9


def test_refuted_atomic_claim():
    sc = _subclaim("sc1")
    root = _atomic_expr("sc1")
    dec = _decomposition(root, [sc])
    ev = [_evidence("sc1", tier=1, direction=Direction.REFUTES)]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "REFUTED"
    assert result.p == 0.0
    assert result.best_evidence_tier == 1
    assert result.confidence >= 0.9


def test_no_evidence_insufficient():
    sc = _subclaim("sc1")
    root = _atomic_expr("sc1")
    dec = _decomposition(root, [sc])
    engine = SynthesisEngine()
    result = engine.synthesize(dec, [])
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert result.insufficiency_reason == "no_evidence_retrieved"


def test_tier3_only_insufficient():
    sc = _subclaim("sc1")
    root = _atomic_expr("sc1")
    dec = _decomposition(root, [sc])
    ev = [_evidence("sc1", tier=3, direction=Direction.SUPPORTS)]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert result.insufficiency_reason == "only_tier3_evidence"


def test_contradictory_tier1_unresolved():
    sc = _subclaim("sc1")
    root = _atomic_expr("sc1")
    dec = _decomposition(root, [sc])
    ev = [
        _evidence("sc1", tier=1, direction=Direction.SUPPORTS, authority="Preliminary"),
        _evidence("sc1", tier=1, direction=Direction.REFUTES, authority="Preliminary"),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert result.insufficiency_reason == "contradictory_tier1_evidence"
    assert HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE in result.human_review_flags


def test_contradictory_tier1_resolved_by_authority():
    sc = _subclaim("sc1")
    root = _atomic_expr("sc1")
    dec = _decomposition(root, [sc])
    ev = [
        _evidence("sc1", tier=1, direction=Direction.SUPPORTS, authority="Supreme Court"),
        _evidence(
            "sc1", tier=1, direction=Direction.REFUTES, authority="Agency preliminary report"
        ),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "SUPPORTED"
    assert result.p == 1.0
    # Check authority ranking applied flag propagated through subclaim result
    sub = result.subclaim_results[0]
    assert sub.synthesis_logic.authority_ranking_applied is True


def test_tier2_cross_verification_satisfied():
    sc = _subclaim("sc1", claim_type=ClaimType.CURRENT_EVENT)
    root = _atomic_expr("sc1")
    dec = _decomposition(root, [sc])
    ev = [
        _evidence("sc1", tier=2, direction=Direction.SUPPORTS, group_id="news_a"),
        _evidence("sc1", tier=2, direction=Direction.SUPPORTS, group_id="news_b"),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "SUPPORTED"
    assert result.p == 1.0
    assert result.best_evidence_tier == 2


def test_tier2_cross_verification_failed():
    sc = _subclaim("sc1", claim_type=ClaimType.CURRENT_EVENT)
    root = _atomic_expr("sc1")
    dec = _decomposition(root, [sc])
    ev = [
        _evidence("sc1", tier=2, direction=Direction.SUPPORTS, group_id="news_a"),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert result.insufficiency_reason == "tier2_evidence_mixed_or_insufficient"


# ---------------------------------------------------------------------------
# ClaimExpression logic tests
# ---------------------------------------------------------------------------


def test_and_all_supported():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.AND,
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    ev = [
        _evidence("sc1", tier=1, direction=Direction.SUPPORTS),
        _evidence("sc2", tier=1, direction=Direction.SUPPORTS),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "SUPPORTED"
    assert result.p == 1.0


def test_and_one_refuted():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.AND,
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    ev = [
        _evidence("sc1", tier=1, direction=Direction.SUPPORTS),
        _evidence("sc2", tier=1, direction=Direction.REFUTES),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "REFUTED"
    assert result.p == 0.0


def test_and_one_insufficient():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.AND,
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    ev = [
        _evidence("sc1", tier=1, direction=Direction.SUPPORTS),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5


def test_or_one_supported():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.OR,
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    ev = [
        _evidence("sc1", tier=1, direction=Direction.SUPPORTS),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "SUPPORTED"
    assert result.p == 1.0


def test_or_all_refuted():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.OR,
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    ev = [
        _evidence("sc1", tier=1, direction=Direction.REFUTES),
        _evidence("sc2", tier=1, direction=Direction.REFUTES),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "REFUTED"
    assert result.p == 0.0


def test_or_insufficient_no_supported():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.OR,
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    ev = [
        _evidence("sc1", tier=1, direction=Direction.SUPPORTS),
        _evidence("sc2", tier=3, direction=Direction.SUPPORTS),
    ]
    # sc2 is tier3 only -> insufficient; sc1 is supported -> OR should be supported
    # Wait, we need OR with insufficient and no supported. Let's make sc1 insufficient (no evidence) and sc2 insufficient (tier3)
    ev = [
        _evidence("sc2", tier=3, direction=Direction.SUPPORTS),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5


def test_not_supported_becomes_refuted():
    sc = _subclaim("sc1")
    root = ClaimExpression(
        node_type=NodeType.NOT,
        children=[_atomic_expr("sc1")],
    )
    dec = _decomposition(root, [sc])
    ev = [_evidence("sc1", tier=1, direction=Direction.SUPPORTS)]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "REFUTED"
    assert result.p == 0.0


def test_not_refuted_becomes_supported():
    sc = _subclaim("sc1")
    root = ClaimExpression(
        node_type=NodeType.NOT,
        children=[_atomic_expr("sc1")],
    )
    dec = _decomposition(root, [sc])
    ev = [_evidence("sc1", tier=1, direction=Direction.REFUTES)]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "SUPPORTED"
    assert result.p == 1.0


def test_if_then_refuted_antecedent():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.IF_THEN,
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    ev = [
        _evidence("sc1", tier=1, direction=Direction.REFUTES),
        _evidence("sc2", tier=1, direction=Direction.SUPPORTS),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert (
        result.insufficiency_reason == "antecedent_refuted_conditional_not_substantively_checkable"
    )


def test_if_then_supported_refuted():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.IF_THEN,
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    ev = [
        _evidence("sc1", tier=1, direction=Direction.SUPPORTS),
        _evidence("sc2", tier=1, direction=Direction.REFUTES),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "REFUTED"
    assert result.p == 0.0


# ---------------------------------------------------------------------------
# Comparison tests
# ---------------------------------------------------------------------------


def test_comparison_true():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.COMPARISON,
        operator="==",
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    ev = [
        _evidence(
            "sc1",
            tier=1,
            direction=Direction.SUPPORTS,
            source_value=ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="count"),
        ),
        _evidence(
            "sc2",
            tier=1,
            direction=Direction.SUPPORTS,
            source_value=ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="count"),
        ),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "SUPPORTED"
    assert result.p == 1.0


def test_comparison_false():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.COMPARISON,
        operator="==",
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    ev = [
        _evidence(
            "sc1",
            tier=1,
            direction=Direction.SUPPORTS,
            source_value=ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="count"),
        ),
        _evidence(
            "sc2",
            tier=1,
            direction=Direction.SUPPORTS,
            source_value=ResolvedValue(value=99, value_type=ValueType.NUMBER, unit="count"),
        ),
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "REFUTED"
    assert result.p == 0.0


def test_comparison_missing_value():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.COMPARISON,
        operator="==",
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    ev = [
        _evidence(
            "sc1",
            tier=1,
            direction=Direction.SUPPORTS,
            source_value=ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="count"),
        ),
        _evidence("sc2", tier=1, direction=Direction.SUPPORTS),  # no source_value
    ]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev)
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


def test_scope_mismatch():
    sc = _subclaim("sc1")
    root = _atomic_expr("sc1")
    dec = _decomposition(root, [sc])
    ev = [_evidence("sc1", tier=1, direction=Direction.SUPPORTS)]
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev, scope_mismatch_subclaim_ids={"sc1"})
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert result.insufficiency_reason == "evidence_scope_narrower_than_claim"
    assert HumanReviewFlag.SCOPE_MISMATCH in result.human_review_flags


def test_entity_failure():
    sc = _subclaim("sc1")
    root = _atomic_expr("sc1")
    dec = _decomposition(root, [sc])
    ev = []
    engine = SynthesisEngine()
    result = engine.synthesize(dec, ev, entity_failure_subclaim_ids={"sc1"})
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert result.insufficiency_reason == "entity_resolution_failure"


def test_all_insufficient_aggregation():
    sc1 = _subclaim("sc1")
    sc2 = _subclaim("sc2")
    root = ClaimExpression(
        node_type=NodeType.AND,
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec = _decomposition(root, [sc1, sc2])
    # No evidence for either -> both insufficient
    engine = SynthesisEngine()
    result = engine.synthesize(dec, [])
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    # Also test OR
    root_or = ClaimExpression(
        node_type=NodeType.OR,
        children=[_atomic_expr("sc1"), _atomic_expr("sc2")],
    )
    dec_or = _decomposition(root_or, [sc1, sc2])
    result_or = engine.synthesize(dec_or, [])
    assert result_or.status == "INSUFFICIENT"
    assert result_or.p == 0.5


# ---------------------------------------------------------------------------
# p-value invariant
# ---------------------------------------------------------------------------


def test_p_values_are_exact():
    """p must always be exactly 1.0, 0.0, or 0.5 across all results."""
    sc = _subclaim("sc1")
    root = _atomic_expr("sc1")
    dec = _decomposition(root, [sc])
    engine = SynthesisEngine()
    for ev, expected_status in [
        ([_evidence("sc1", tier=1, direction=Direction.SUPPORTS)], "SUPPORTED"),
        ([_evidence("sc1", tier=1, direction=Direction.REFUTES)], "REFUTED"),
        ([], "INSUFFICIENT"),
        ([_evidence("sc1", tier=3, direction=Direction.SUPPORTS)], "INSUFFICIENT"),
    ]:
        result = engine.synthesize(dec, ev)
        assert result.p in (1.0, 0.0, 0.5)
        assert result.status == expected_status
