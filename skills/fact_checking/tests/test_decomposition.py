"""
Phase 2 decomposition and validation layer tests for LSD Fact-Checking v1.5.
"""

from __future__ import annotations

from skills.fact_checking.decomposition import (
    CanonicalPremise,
    Decomposer,
    decompose_and_synthesize,
    validate_claim_expression,
)
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
    ProvenanceSpan,
    Side,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _premise(
    text: str,
    spans: list[ProvenanceSpan] | None = None,
    frame_info: dict | None = None,
) -> CanonicalPremise:
    return CanonicalPremise(
        premise_id="p1",
        snapshot_id="snap1",
        original_text=text,
        topic_id="t1",
        side=Side.FOR,
        provenance_spans=spans or [],
        frame_info=frame_info,
    )


def _span(span_id: str, post_id: str = "post1") -> ProvenanceSpan:
    return ProvenanceSpan(
        span_id=span_id, post_id=post_id, offsets={"start": 0, "end": 10}, span_text="..."
    )


def _atomic_expr(sid: str) -> ClaimExpression:
    return ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id=sid)


def _evidence(sid: str, tier: int = 1, direction: Direction = Direction.SUPPORTS) -> EvidenceItem:
    return EvidenceItem(
        subclaim_id=sid,
        source_tier=tier,
        direction=direction,
        direction_confidence=1.0,
        relevance_score=1.0,
    )


def _decomp(
    root: ClaimExpression,
    subclaims: list[AtomicSubclaim],
    spans: list[ProvenanceSpan],
) -> PremiseDecomposition:
    return PremiseDecomposition(
        premise_id="p1",
        snapshot_id="snap1",
        original_text="test",
        topic_id="t1",
        side=Side.FOR,
        root_claim_expression=root,
        atomic_subclaims=subclaims,
        provenance_spans=spans,
    )


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------


def test_simple_claim_fallback_atomic():
    premise = _premise("The sky is blue", spans=[_span("s1")])
    decomposer = Decomposer()
    result = decomposer.decompose(premise)
    assert result.validation_result.valid is True
    assert result.root_claim_expression.node_type == NodeType.ATOMIC
    assert len(result.atomic_subclaims) == 1
    assert result.atomic_subclaims[0].text == "The sky is blue"
    assert result.atomic_subclaims[0].provenance_spans == premise.provenance_spans


def test_complex_claim_fallback_invalid():
    premise = _premise("The sky is blue and the grass is green", spans=[_span("s1")])
    decomposer = Decomposer()
    result = decomposer.decompose(premise)
    assert result.validation_result.valid is False
    assert any("decomposition_failure" in e for e in result.validation_result.errors)


# ---------------------------------------------------------------------------
# LLM backend — valid decomposition
# ---------------------------------------------------------------------------


def test_llm_valid_decomposition():
    premise = _premise("A and B", spans=[_span("s1")])

    def backend(p: CanonicalPremise) -> PremiseDecomposition:
        sc_a = AtomicSubclaim(
            subclaim_id="sc_a",
            parent_premise_id="p1",
            text="A",
            claim_type=ClaimType.EMPIRICAL_ATOMIC,
            provenance_spans=[_span("s1")],
        )
        sc_b = AtomicSubclaim(
            subclaim_id="sc_b",
            parent_premise_id="p1",
            text="B",
            claim_type=ClaimType.EMPIRICAL_ATOMIC,
            provenance_spans=[_span("s1")],
        )
        root = ClaimExpression(
            node_type=NodeType.AND,
            children=[_atomic_expr("sc_a"), _atomic_expr("sc_b")],
        )
        return _decomp(root, [sc_a, sc_b], [_span("s1")])

    decomposer = Decomposer(llm_backend=backend)
    result = decomposer.decompose(premise)
    assert result.validation_result.valid is True
    assert result.root_claim_expression.node_type == NodeType.AND


def test_llm_invalid_depth():
    """Depth > 3 should be rejected."""
    premise = _premise("Deep claim", spans=[_span("s1")])

    def backend(p: CanonicalPremise) -> PremiseDecomposition:
        # Build a tree of depth 5 (root depth 0, leaves depth 4)
        e = _atomic_expr("sc1")
        for _ in range(4):
            e = ClaimExpression(node_type=NodeType.AND, children=[e, _atomic_expr("sc1")])
        sc = AtomicSubclaim(
            subclaim_id="sc1",
            parent_premise_id="p1",
            text="Deep claim",
            claim_type=ClaimType.EMPIRICAL_ATOMIC,
            provenance_spans=[_span("s1")],
        )
        return _decomp(e, [sc], [_span("s1")])

    decomposer = Decomposer(llm_backend=backend)
    result = decomposer.decompose(premise)
    assert result.validation_result.valid is False
    assert any("depth" in e.lower() for e in result.validation_result.errors)


def test_llm_missing_provenance_span():
    premise = _premise("A and B", spans=[_span("s1"), _span("s2")])

    def backend(p: CanonicalPremise) -> PremiseDecomposition:
        sc_a = AtomicSubclaim(
            subclaim_id="sc_a",
            parent_premise_id="p1",
            text="A",
            claim_type=ClaimType.EMPIRICAL_ATOMIC,
            provenance_spans=[_span("s1")],  # missing s2
        )
        sc_b = AtomicSubclaim(
            subclaim_id="sc_b",
            parent_premise_id="p1",
            text="B",
            claim_type=ClaimType.EMPIRICAL_ATOMIC,
            provenance_spans=[_span("s1"), _span("s2")],
        )
        root = ClaimExpression(
            node_type=NodeType.AND,
            children=[_atomic_expr("sc_a"), _atomic_expr("sc_b")],
        )
        return _decomp(root, [sc_a, sc_b], [_span("s1"), _span("s2")])

    decomposer = Decomposer(llm_backend=backend)
    result = decomposer.decompose(premise)
    assert result.validation_result.valid is False
    assert any("provenance" in e.lower() for e in result.validation_result.errors)


def test_llm_introduced_claim():
    premise = _premise("The sky is blue", spans=[_span("s1")])

    def backend(p: CanonicalPremise) -> PremiseDecomposition:
        sc = AtomicSubclaim(
            subclaim_id="sc1",
            parent_premise_id="p1",
            text="The ocean is deep",
            claim_type=ClaimType.EMPIRICAL_ATOMIC,
            provenance_spans=[_span("s1")],
        )
        return _decomp(_atomic_expr("sc1"), [sc], [_span("s1")])

    decomposer = Decomposer(llm_backend=backend)
    result = decomposer.decompose(premise)
    assert result.validation_result.valid is False
    assert any(
        "introduces" in e.lower() or "new" in e.lower() for e in result.validation_result.errors
    )


def test_llm_logical_structure_mismatch():
    premise = _premise("A and B", spans=[_span("s1")])

    def backend(p: CanonicalPremise) -> PremiseDecomposition:
        sc_a = AtomicSubclaim(
            subclaim_id="sc_a",
            parent_premise_id="p1",
            text="A",
            claim_type=ClaimType.EMPIRICAL_ATOMIC,
            provenance_spans=[_span("s1")],
        )
        sc_b = AtomicSubclaim(
            subclaim_id="sc_b",
            parent_premise_id="p1",
            text="B",
            claim_type=ClaimType.EMPIRICAL_ATOMIC,
            provenance_spans=[_span("s1")],
        )
        root = ClaimExpression(
            node_type=NodeType.OR,
            children=[_atomic_expr("sc_a"), _atomic_expr("sc_b")],
        )
        return _decomp(root, [sc_a, sc_b], [_span("s1")])

    decomposer = Decomposer(llm_backend=backend)
    result = decomposer.decompose(premise)
    assert result.validation_result.valid is False
    assert any("or" in e.lower() for e in result.validation_result.errors)


# ---------------------------------------------------------------------------
# Pipeline wrapper
# ---------------------------------------------------------------------------


def test_pipeline_invalid_decomposition_returns_insufficient():
    premise = _premise("A and B", spans=[_span("s1")])

    def backend(p: CanonicalPremise) -> PremiseDecomposition:
        sc_a = AtomicSubclaim(
            subclaim_id="sc_a",
            parent_premise_id="p1",
            text="A",
            claim_type=ClaimType.EMPIRICAL_ATOMIC,
            provenance_spans=[_span("s1")],
        )
        sc_b = AtomicSubclaim(
            subclaim_id="sc_b",
            parent_premise_id="p1",
            text="B",
            claim_type=ClaimType.EMPIRICAL_ATOMIC,
            provenance_spans=[_span("s1")],
        )
        root = ClaimExpression(
            node_type=NodeType.OR,
            children=[_atomic_expr("sc_a"), _atomic_expr("sc_b")],
        )
        return _decomp(root, [sc_a, sc_b], [_span("s1")])

    decomposer = Decomposer(llm_backend=backend)
    engine = SynthesisEngine()
    result = decompose_and_synthesize(premise, [], decomposer, engine)
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert HumanReviewFlag.LLM_VALIDATION_FAILURE in result.human_review_flags


def test_pipeline_simple_claim_with_evidence():
    premise = _premise("The sky is blue", spans=[_span("s1")])
    decomposer = Decomposer()
    engine = SynthesisEngine()
    ev = [_evidence("p1_atomic", tier=1, direction=Direction.SUPPORTS)]
    result = decompose_and_synthesize(premise, ev, decomposer, engine)
    assert result.status == "SUPPORTED"
    assert result.p == 1.0


# ---------------------------------------------------------------------------
# Frame independence
# ---------------------------------------------------------------------------


def test_frame_independence_violation():
    premise = _premise(
        "The sky is blue",
        spans=[_span("s1")],
        frame_info={"for_side": "pro"},
    )

    def backend(p: CanonicalPremise) -> PremiseDecomposition:
        sc = AtomicSubclaim(
            subclaim_id="sc1",
            parent_premise_id="p1",
            text="The sky is blue",
            claim_type=ClaimType.EMPIRICAL_ATOMIC,
            provenance_spans=[_span("s1")],
            operationalization_hint="for_side pro",  # references frame term
        )
        return _decomp(_atomic_expr("sc1"), [sc], [_span("s1")])

    decomposer = Decomposer(llm_backend=backend)
    result = decomposer.decompose(premise)
    assert result.validation_result.valid is False
    assert any("frame" in e.lower() for e in result.validation_result.errors)


# ---------------------------------------------------------------------------
# Structural validation — direct unit tests
# ---------------------------------------------------------------------------


def test_validate_claim_expression_max_depth_ok():
    # Depth 4 tree (root 0, leaves 3) is OK
    e = _atomic_expr("sc1")
    for _ in range(3):
        e = ClaimExpression(node_type=NodeType.AND, children=[e, _atomic_expr("sc1")])
    errors = validate_claim_expression(e, {"sc1"})
    assert errors == []


def test_validate_claim_expression_max_depth_exceeded():
    # Depth 5 tree (root 0, leaves 4) exceeds max depth 3
    e = _atomic_expr("sc1")
    for _ in range(4):
        e = ClaimExpression(node_type=NodeType.AND, children=[e, _atomic_expr("sc1")])
    errors = validate_claim_expression(e, {"sc1"})
    assert any("depth" in err.lower() for err in errors)


def test_validate_claim_expression_unknown_subclaim():
    e = _atomic_expr("sc_missing")
    errors = validate_claim_expression(e, {"sc1"})
    assert any("unknown subclaim_id" in err.lower() for err in errors)


# Note: ClaimExpression.__post_init__ enforces child counts and required
# fields for AND/OR/NOT/IF_THEN/COMPARISON/QUANTIFIER, so those cases are
# caught at construction time. The validator focuses on depth, reachability,
# provenance, semantic equivalence, and logical-structure heuristics.
