"""
ClaimExpression evaluator for the LSD Fact-Checking System v1.5.

Implements the logical expression tree used to evaluate compound premises:
- ATOMIC — leaf node referencing an AtomicSubclaim
- AND / OR / NOT — boolean combinators
- IF_THEN — material implication
- COMPARISON — numeric/temporal comparison using ResolvedValue
- QUANTIFIER — placeholder for universal/existential claims

Per 01_DATA_MODELS.md and 02_SYNTHESIS_ENGINE.md.
"""

from __future__ import annotations

from .v15_models import (
    ClaimExpression,
    HumanReviewFlag,
    NodeType,
    ProvenanceSpan,
    ResolvedValue,
    SubclaimResult,
    SynthesisLogic,
    ValueType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mean_float(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _safe_min(tiers: list[int]) -> int | None:
    return min(tiers) if tiers else None


def _safe_max(tiers: list[int]) -> int | None:
    return max(tiers) if tiers else None


def _resolved_values_compatible(a: ResolvedValue, b: ResolvedValue) -> bool:
    """Basic compatibility check for Phase 1."""
    if a.value is None or b.value is None:
        return False
    if a.value_type != b.value_type:
        return False
    if a.unit != b.unit:
        return False
    return True


def _compare_resolved_values(operator: str, a: ResolvedValue, b: ResolvedValue) -> bool:
    """Deterministic comparison for supported types."""
    val_a = a.value
    val_b = b.value

    if val_a is None or val_b is None:
        raise ValueError("Cannot compare None values")

    # Normalize numeric types
    if a.value_type == ValueType.NUMBER:
        num_a = float(val_a)
        num_b = float(val_b)
        if operator == "==":
            return num_a == num_b
        if operator == "!=":
            return num_a != num_b
        if operator == "<":
            return num_a < num_b
        if operator == ">":
            return num_a > num_b
        if operator == "<=":
            return num_a <= num_b
        if operator == ">=":
            return num_a >= num_b
        raise ValueError(f"Unsupported comparison operator: {operator}")

    if a.value_type == ValueType.DATE:
        # Simple string comparison for ISO dates in Phase 1
        str_a = str(val_a)
        str_b = str(val_b)
        if operator == "==":
            return str_a == str_b
        if operator == "!=":
            return str_a != str_b
        if operator == "<":
            return str_a < str_b
        if operator == ">":
            return str_a > str_b
        if operator == "<=":
            return str_a <= str_b
        if operator == ">=":
            return str_a >= str_b
        raise ValueError(f"Unsupported comparison operator: {operator}")

    if a.value_type == ValueType.BOOLEAN:
        bool_a = bool(val_a)
        bool_b = bool(val_b)
        if operator == "==":
            return bool_a == bool_b
        if operator == "!=":
            return bool_a != bool_b
        raise ValueError(f"Unsupported comparison operator for booleans: {operator}")

    if a.value_type == ValueType.TEXT:
        str_a = str(val_a)
        str_b = str(val_b)
        if operator == "==":
            return str_a == str_b
        if operator == "!=":
            return str_a != str_b
        raise ValueError(f"Unsupported comparison operator for text: {operator}")

    raise ValueError(f"Unsupported value type for comparison: {a.value_type}")


def _merge_citations(children: list[SubclaimResult]) -> list[str]:
    seen: set = set()
    out: list[str] = []
    for c in children:
        for cid in c.citations:
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
    return out


def _merge_provenance(children: list[SubclaimResult]) -> list[ProvenanceSpan]:
    seen: set = set()
    out: list[ProvenanceSpan] = []
    for c in children:
        for span in c.provenance_spans:
            key = (span.span_id, span.post_id)
            if key not in seen:
                seen.add(key)
                out.append(span)
    return out


def _merge_flags(children: list[SubclaimResult]) -> list[HumanReviewFlag]:
    seen: set = set()
    out: list[HumanReviewFlag] = []
    for c in children:
        for f in c.human_review_flags:
            if f not in seen:
                seen.add(f)
                out.append(f)
    return out


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def evaluate_expression(
    node: ClaimExpression,
    subclaim_map: dict[str, SubclaimResult],
    depth: int = 0,
) -> SubclaimResult:
    """Recursively evaluate a ClaimExpression and return a synthetic SubclaimResult."""
    if depth > 3:
        raise ValueError("ClaimExpression exceeds maximum recursion depth of 3")

    if node.node_type == NodeType.ATOMIC:
        result = subclaim_map.get(node.subclaim_id)
        if result is None:
            return SubclaimResult(
                subclaim_id=node.subclaim_id or "missing",
                status="INSUFFICIENT",
                p=0.5,
                insufficiency_reason="atomic_subclaim_not_found_in_map",
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="atomic_missing",
                    claim_expression_node_type=NodeType.ATOMIC,
                ),
            )
        # Return a copy so we don't mutate the original
        return SubclaimResult(
            subclaim_id=result.subclaim_id,
            status=result.status,
            p=result.p,
            confidence=result.confidence,
            best_evidence_tier=result.best_evidence_tier,
            limiting_evidence_tier=result.limiting_evidence_tier,
            decisive_evidence_tier=result.decisive_evidence_tier,
            citations=list(result.citations),
            operationalization=result.operationalization,
            verdict_scope=result.verdict_scope,
            insufficiency_reason=result.insufficiency_reason,
            human_review_flags=list(result.human_review_flags),
            provenance_spans=list(result.provenance_spans),
            synthesis_logic=SynthesisLogic(
                status_rule_applied="atomic_lookup",
                policy_rule_id=result.synthesis_logic.policy_rule_id,
                decisive_evidence=list(result.synthesis_logic.decisive_evidence),
                contradictory_evidence=list(result.synthesis_logic.contradictory_evidence),
                claim_expression_node_type=NodeType.ATOMIC,
                authority_ranking_applied=result.synthesis_logic.authority_ranking_applied,
            ),
            resolved_value=result.resolved_value,
        )

    if node.node_type == NodeType.NOT:
        child = evaluate_expression(node.children[0], subclaim_map, depth + 1)
        if child.status == "SUPPORTED":
            return SubclaimResult(
                subclaim_id="expr:NOT",
                status="REFUTED",
                p=0.0,
                confidence=child.confidence,
                best_evidence_tier=child.best_evidence_tier,
                limiting_evidence_tier=child.limiting_evidence_tier,
                decisive_evidence_tier=child.decisive_evidence_tier,
                citations=list(child.citations),
                provenance_spans=list(child.provenance_spans),
                human_review_flags=list(child.human_review_flags),
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="not_inversion",
                    claim_expression_node_type=NodeType.NOT,
                ),
                resolved_value=child.resolved_value,
            )
        if child.status == "REFUTED":
            return SubclaimResult(
                subclaim_id="expr:NOT",
                status="SUPPORTED",
                p=1.0,
                confidence=child.confidence,
                best_evidence_tier=child.best_evidence_tier,
                limiting_evidence_tier=child.limiting_evidence_tier,
                decisive_evidence_tier=child.decisive_evidence_tier,
                citations=list(child.citations),
                provenance_spans=list(child.provenance_spans),
                human_review_flags=list(child.human_review_flags),
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="not_inversion",
                    claim_expression_node_type=NodeType.NOT,
                ),
                resolved_value=child.resolved_value,
            )
        # INSUFFICIENT
        return SubclaimResult(
            subclaim_id="expr:NOT",
            status="INSUFFICIENT",
            p=0.5,
            confidence=child.confidence,
            best_evidence_tier=None,
            limiting_evidence_tier=child.limiting_evidence_tier,
            decisive_evidence_tier=None,
            citations=list(child.citations),
            provenance_spans=list(child.provenance_spans),
            human_review_flags=list(child.human_review_flags),
            synthesis_logic=SynthesisLogic(
                status_rule_applied="not_insufficient",
                claim_expression_node_type=NodeType.NOT,
            ),
            resolved_value=child.resolved_value,
        )

    # Evaluate all children first
    child_results = [evaluate_expression(c, subclaim_map, depth + 1) for c in node.children]
    child_confidences = [c.confidence for c in child_results]
    confidence = _mean_float(child_confidences) if child_confidences else 0.0
    citations = _merge_citations(child_results)
    provenance_spans = _merge_provenance(child_results)
    flags = _merge_flags(child_results)

    def _tiers(attr: str) -> list[int]:
        return [getattr(c, attr) for c in child_results if getattr(c, attr) is not None]

    if node.node_type == NodeType.AND:
        refuted = [c for c in child_results if c.status == "REFUTED"]
        supported = [c for c in child_results if c.status == "SUPPORTED"]
        if refuted:
            decisive_tiers = _tiers("decisive_evidence_tier")
            return SubclaimResult(
                subclaim_id="expr:AND",
                status="REFUTED",
                p=0.0,
                confidence=confidence,
                best_evidence_tier=_safe_min(decisive_tiers),
                limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                decisive_evidence_tier=_safe_min(decisive_tiers),
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="and_any_refuted",
                    claim_expression_node_type=NodeType.AND,
                ),
            )
        if len(supported) == len(child_results):
            best = _safe_min(_tiers("decisive_evidence_tier"))
            return SubclaimResult(
                subclaim_id="expr:AND",
                status="SUPPORTED",
                p=1.0,
                confidence=confidence,
                best_evidence_tier=best,
                limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                decisive_evidence_tier=_safe_min(_tiers("decisive_evidence_tier")),
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="and_all_supported",
                    claim_expression_node_type=NodeType.AND,
                ),
            )
        # Some insufficient
        return SubclaimResult(
            subclaim_id="expr:AND",
            status="INSUFFICIENT",
            p=0.5,
            confidence=confidence,
            best_evidence_tier=None,
            limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
            decisive_evidence_tier=None,
            citations=citations,
            provenance_spans=provenance_spans,
            human_review_flags=flags,
            synthesis_logic=SynthesisLogic(
                status_rule_applied="and_some_insufficient",
                claim_expression_node_type=NodeType.AND,
            ),
        )

    if node.node_type == NodeType.OR:
        supported = [c for c in child_results if c.status == "SUPPORTED"]
        refuted = [c for c in child_results if c.status == "REFUTED"]
        if supported:
            decisive_tiers = [
                c.decisive_evidence_tier for c in supported if c.decisive_evidence_tier is not None
            ]
            return SubclaimResult(
                subclaim_id="expr:OR",
                status="SUPPORTED",
                p=1.0,
                confidence=confidence,
                best_evidence_tier=_safe_min(decisive_tiers),
                limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                decisive_evidence_tier=_safe_min(decisive_tiers),
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="or_any_supported",
                    claim_expression_node_type=NodeType.OR,
                ),
            )
        if len(refuted) == len(child_results):
            decisive_tiers = _tiers("decisive_evidence_tier")
            return SubclaimResult(
                subclaim_id="expr:OR",
                status="REFUTED",
                p=0.0,
                confidence=confidence,
                best_evidence_tier=_safe_min(decisive_tiers),
                limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                decisive_evidence_tier=_safe_min(decisive_tiers),
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="or_all_refuted",
                    claim_expression_node_type=NodeType.OR,
                ),
            )
        # Some insufficient
        return SubclaimResult(
            subclaim_id="expr:OR",
            status="INSUFFICIENT",
            p=0.5,
            confidence=confidence,
            best_evidence_tier=None,
            limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
            decisive_evidence_tier=None,
            citations=citations,
            provenance_spans=provenance_spans,
            human_review_flags=flags,
            synthesis_logic=SynthesisLogic(
                status_rule_applied="or_some_insufficient",
                claim_expression_node_type=NodeType.OR,
            ),
        )

    if node.node_type == NodeType.IF_THEN:
        ant = child_results[0]
        con = child_results[1]
        if ant.status == "REFUTED":
            return SubclaimResult(
                subclaim_id="expr:IF_THEN",
                status="INSUFFICIENT",
                p=0.5,
                confidence=confidence,
                best_evidence_tier=None,
                limiting_evidence_tier=_safe_max(
                    [
                        t
                        for t in [ant.limiting_evidence_tier, con.limiting_evidence_tier]
                        if t is not None
                    ]
                ),
                decisive_evidence_tier=None,
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                insufficiency_reason="antecedent_refuted_conditional_not_substantively_checkable",
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="if_then_antecedent_refuted",
                    insufficiency_trigger="antecedent_refuted_conditional_not_substantively_checkable",
                    claim_expression_node_type=NodeType.IF_THEN,
                ),
            )
        if ant.status == "INSUFFICIENT":
            return SubclaimResult(
                subclaim_id="expr:IF_THEN",
                status="INSUFFICIENT",
                p=0.5,
                confidence=confidence,
                best_evidence_tier=None,
                limiting_evidence_tier=ant.limiting_evidence_tier,
                decisive_evidence_tier=None,
                citations=ant.citations,
                provenance_spans=ant.provenance_spans,
                human_review_flags=flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="if_then_antecedent_insufficient",
                    claim_expression_node_type=NodeType.IF_THEN,
                ),
            )
        # antecedent SUPPORTED
        if con.status == "SUPPORTED":
            return SubclaimResult(
                subclaim_id="expr:IF_THEN",
                status="SUPPORTED",
                p=1.0,
                confidence=confidence,
                best_evidence_tier=_safe_min(
                    [t for t in [ant.best_evidence_tier, con.best_evidence_tier] if t is not None]
                ),
                limiting_evidence_tier=_safe_max(
                    [
                        t
                        for t in [ant.limiting_evidence_tier, con.limiting_evidence_tier]
                        if t is not None
                    ]
                ),
                decisive_evidence_tier=_safe_min(
                    [
                        t
                        for t in [ant.decisive_evidence_tier, con.decisive_evidence_tier]
                        if t is not None
                    ]
                ),
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="if_then_supported_supported",
                    claim_expression_node_type=NodeType.IF_THEN,
                ),
            )
        if con.status == "REFUTED":
            return SubclaimResult(
                subclaim_id="expr:IF_THEN",
                status="REFUTED",
                p=0.0,
                confidence=confidence,
                best_evidence_tier=_safe_min(
                    [t for t in [ant.best_evidence_tier, con.best_evidence_tier] if t is not None]
                ),
                limiting_evidence_tier=_safe_max(
                    [
                        t
                        for t in [ant.limiting_evidence_tier, con.limiting_evidence_tier]
                        if t is not None
                    ]
                ),
                decisive_evidence_tier=_safe_min(
                    [
                        t
                        for t in [ant.decisive_evidence_tier, con.decisive_evidence_tier]
                        if t is not None
                    ]
                ),
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="if_then_supported_refuted",
                    claim_expression_node_type=NodeType.IF_THEN,
                ),
            )
        # con INSUFFICIENT
        return SubclaimResult(
            subclaim_id="expr:IF_THEN",
            status="INSUFFICIENT",
            p=0.5,
            confidence=confidence,
            best_evidence_tier=None,
            limiting_evidence_tier=_safe_max(
                [
                    t
                    for t in [ant.limiting_evidence_tier, con.limiting_evidence_tier]
                    if t is not None
                ]
            ),
            decisive_evidence_tier=None,
            citations=citations,
            provenance_spans=provenance_spans,
            human_review_flags=flags,
            synthesis_logic=SynthesisLogic(
                status_rule_applied="if_then_supported_insufficient",
                claim_expression_node_type=NodeType.IF_THEN,
            ),
        )

    if node.node_type == NodeType.COMPARISON:
        if len(child_results) != 2:
            raise ValueError("COMPARISON must have exactly two children")
        left = child_results[0]
        right = child_results[1]
        if left.resolved_value is None or right.resolved_value is None:
            return SubclaimResult(
                subclaim_id="expr:COMPARISON",
                status="INSUFFICIENT",
                p=0.5,
                confidence=confidence,
                best_evidence_tier=None,
                limiting_evidence_tier=_safe_max(
                    [
                        t
                        for t in [left.limiting_evidence_tier, right.limiting_evidence_tier]
                        if t is not None
                    ]
                ),
                decisive_evidence_tier=None,
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                insufficiency_reason="comparison_missing_resolved_value",
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="comparison_missing_value",
                    claim_expression_node_type=NodeType.COMPARISON,
                ),
            )
        if not _resolved_values_compatible(left.resolved_value, right.resolved_value):
            return SubclaimResult(
                subclaim_id="expr:COMPARISON",
                status="INSUFFICIENT",
                p=0.5,
                confidence=confidence,
                best_evidence_tier=None,
                limiting_evidence_tier=_safe_max(
                    [
                        t
                        for t in [left.limiting_evidence_tier, right.limiting_evidence_tier]
                        if t is not None
                    ]
                ),
                decisive_evidence_tier=None,
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                insufficiency_reason="comparison_incompatible_units_or_types",
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="comparison_incompatible",
                    claim_expression_node_type=NodeType.COMPARISON,
                ),
            )
        try:
            holds = _compare_resolved_values(
                node.operator, left.resolved_value, right.resolved_value
            )
        except Exception:
            return SubclaimResult(
                subclaim_id="expr:COMPARISON",
                status="INSUFFICIENT",
                p=0.5,
                confidence=confidence,
                best_evidence_tier=None,
                limiting_evidence_tier=_safe_max(
                    [
                        t
                        for t in [left.limiting_evidence_tier, right.limiting_evidence_tier]
                        if t is not None
                    ]
                ),
                decisive_evidence_tier=None,
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                insufficiency_reason="comparison_evaluation_error",
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="comparison_error",
                    claim_expression_node_type=NodeType.COMPARISON,
                ),
            )
        if holds:
            decisive_tiers = [
                t
                for t in [left.decisive_evidence_tier, right.decisive_evidence_tier]
                if t is not None
            ]
            return SubclaimResult(
                subclaim_id="expr:COMPARISON",
                status="SUPPORTED",
                p=1.0,
                confidence=confidence,
                best_evidence_tier=_safe_min(decisive_tiers),
                limiting_evidence_tier=_safe_max(decisive_tiers),
                decisive_evidence_tier=_safe_min(decisive_tiers),
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="comparison_holds",
                    claim_expression_node_type=NodeType.COMPARISON,
                ),
                resolved_value=left.resolved_value,  # copy source value up
            )
        else:
            decisive_tiers = [
                t
                for t in [left.decisive_evidence_tier, right.decisive_evidence_tier]
                if t is not None
            ]
            return SubclaimResult(
                subclaim_id="expr:COMPARISON",
                status="REFUTED",
                p=0.0,
                confidence=confidence,
                best_evidence_tier=_safe_min(decisive_tiers),
                limiting_evidence_tier=_safe_max(decisive_tiers),
                decisive_evidence_tier=_safe_min(decisive_tiers),
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="comparison_fails",
                    claim_expression_node_type=NodeType.COMPARISON,
                ),
                resolved_value=left.resolved_value,
            )

    if node.node_type == NodeType.QUANTIFIER:
        quantifier = node.quantifier
        param = node.quantifier_parameter

        # The quantifier applies over a set of child subclaims
        children = child_results

        # Check if set is resolved
        if not children:
            return SubclaimResult(
                subclaim_id="expr:QUANTIFIER",
                status="INSUFFICIENT",
                p=0.5,
                confidence=0.0,
                best_evidence_tier=None,
                limiting_evidence_tier=None,
                decisive_evidence_tier=None,
                citations=[],
                provenance_spans=[],
                human_review_flags=[],
                insufficiency_reason="quantifier_unresolved_set",
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="quantifier_unresolved_set",
                    claim_expression_node_type=NodeType.QUANTIFIER,
                ),
            )

        supported_count = sum(1 for c in children if c.status == "SUPPORTED")
        refuted_count = sum(1 for c in children if c.status == "REFUTED")
        total = len(children)

        if quantifier == "ALL":
            if refuted_count > 0:
                decisive_tiers = _tiers("decisive_evidence_tier")
                return SubclaimResult(
                    subclaim_id="expr:QUANTIFIER",
                    status="REFUTED",
                    p=0.0,
                    confidence=confidence,
                    best_evidence_tier=_safe_min(decisive_tiers),
                    limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                    decisive_evidence_tier=_safe_min(decisive_tiers),
                    citations=citations,
                    provenance_spans=provenance_spans,
                    human_review_flags=flags,
                    synthesis_logic=SynthesisLogic(
                        status_rule_applied="quantifier_all_refuted",
                        claim_expression_node_type=NodeType.QUANTIFIER,
                    ),
                )
            if supported_count == total:
                decisive_tiers = _tiers("decisive_evidence_tier")
                return SubclaimResult(
                    subclaim_id="expr:QUANTIFIER",
                    status="SUPPORTED",
                    p=1.0,
                    confidence=confidence,
                    best_evidence_tier=_safe_min(decisive_tiers),
                    limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                    decisive_evidence_tier=_safe_min(decisive_tiers),
                    citations=citations,
                    provenance_spans=provenance_spans,
                    human_review_flags=flags,
                    synthesis_logic=SynthesisLogic(
                        status_rule_applied="quantifier_all_supported",
                        claim_expression_node_type=NodeType.QUANTIFIER,
                    ),
                )
            return SubclaimResult(
                subclaim_id="expr:QUANTIFIER",
                status="INSUFFICIENT",
                p=0.5,
                confidence=confidence,
                best_evidence_tier=None,
                limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                decisive_evidence_tier=None,
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                insufficiency_reason="quantifier_all_partial",
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="quantifier_all_partial",
                    claim_expression_node_type=NodeType.QUANTIFIER,
                ),
            )

        if quantifier == "EXISTS":
            if supported_count > 0:
                decisive_tiers = [
                    c.decisive_evidence_tier
                    for c in supported
                    if c.decisive_evidence_tier is not None
                ]
                return SubclaimResult(
                    subclaim_id="expr:QUANTIFIER",
                    status="SUPPORTED",
                    p=1.0,
                    confidence=confidence,
                    best_evidence_tier=_safe_min(decisive_tiers),
                    limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                    decisive_evidence_tier=_safe_min(decisive_tiers),
                    citations=citations,
                    provenance_spans=provenance_spans,
                    human_review_flags=flags,
                    synthesis_logic=SynthesisLogic(
                        status_rule_applied="quantifier_exists_supported",
                        claim_expression_node_type=NodeType.QUANTIFIER,
                    ),
                )
            if refuted_count == total:
                decisive_tiers = _tiers("decisive_evidence_tier")
                return SubclaimResult(
                    subclaim_id="expr:QUANTIFIER",
                    status="REFUTED",
                    p=0.0,
                    confidence=confidence,
                    best_evidence_tier=_safe_min(decisive_tiers),
                    limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                    decisive_evidence_tier=_safe_min(decisive_tiers),
                    citations=citations,
                    provenance_spans=provenance_spans,
                    human_review_flags=flags,
                    synthesis_logic=SynthesisLogic(
                        status_rule_applied="quantifier_exists_all_refuted",
                        claim_expression_node_type=NodeType.QUANTIFIER,
                    ),
                )
            return SubclaimResult(
                subclaim_id="expr:QUANTIFIER",
                status="INSUFFICIENT",
                p=0.5,
                confidence=confidence,
                best_evidence_tier=None,
                limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                decisive_evidence_tier=None,
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                insufficiency_reason="quantifier_exists_partial",
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="quantifier_exists_partial",
                    claim_expression_node_type=NodeType.QUANTIFIER,
                ),
            )

        if quantifier == "AT_LEAST" and isinstance(param, int):
            if supported_count >= param:
                decisive_tiers = [
                    c.decisive_evidence_tier
                    for c in supported
                    if c.decisive_evidence_tier is not None
                ]
                return SubclaimResult(
                    subclaim_id="expr:QUANTIFIER",
                    status="SUPPORTED",
                    p=1.0,
                    confidence=confidence,
                    best_evidence_tier=_safe_min(decisive_tiers),
                    limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                    decisive_evidence_tier=_safe_min(decisive_tiers),
                    citations=citations,
                    provenance_spans=provenance_spans,
                    human_review_flags=flags,
                    synthesis_logic=SynthesisLogic(
                        status_rule_applied="quantifier_at_least_supported",
                        claim_expression_node_type=NodeType.QUANTIFIER,
                    ),
                )
            if total - refuted_count < param:
                decisive_tiers = _tiers("decisive_evidence_tier")
                return SubclaimResult(
                    subclaim_id="expr:QUANTIFIER",
                    status="REFUTED",
                    p=0.0,
                    confidence=confidence,
                    best_evidence_tier=_safe_min(decisive_tiers),
                    limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                    decisive_evidence_tier=_safe_min(decisive_tiers),
                    citations=citations,
                    provenance_spans=provenance_spans,
                    human_review_flags=flags,
                    synthesis_logic=SynthesisLogic(
                        status_rule_applied="quantifier_at_least_refuted",
                        claim_expression_node_type=NodeType.QUANTIFIER,
                    ),
                )
            return SubclaimResult(
                subclaim_id="expr:QUANTIFIER",
                status="INSUFFICIENT",
                p=0.5,
                confidence=confidence,
                best_evidence_tier=None,
                limiting_evidence_tier=_safe_max(_tiers("limiting_evidence_tier")),
                decisive_evidence_tier=None,
                citations=citations,
                provenance_spans=provenance_spans,
                human_review_flags=flags,
                insufficiency_reason="quantifier_at_least_partial",
                synthesis_logic=SynthesisLogic(
                    status_rule_applied="quantifier_at_least_partial",
                    claim_expression_node_type=NodeType.QUANTIFIER,
                ),
            )

        # Unknown quantifier
        return SubclaimResult(
            subclaim_id="expr:QUANTIFIER",
            status="INSUFFICIENT",
            p=0.5,
            confidence=0.0,
            best_evidence_tier=None,
            limiting_evidence_tier=None,
            decisive_evidence_tier=None,
            citations=[],
            provenance_spans=[],
            human_review_flags=[],
            insufficiency_reason="unknown_quantifier",
            synthesis_logic=SynthesisLogic(
                status_rule_applied="quantifier_unknown",
                claim_expression_node_type=NodeType.QUANTIFIER,
            ),
        )

    raise ValueError(f"Unsupported node type: {node.node_type}")
