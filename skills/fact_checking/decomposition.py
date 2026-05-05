"""
Decomposer interface and PremiseDecomposition validation for v1.5.

Responsibilities:
- Accept a canonical premise and output a PremiseDecomposition
- Validate ClaimExpression structural integrity (max depth 3, ATOMIC nodes valid)
- Preserve provenance spans end-to-end
- Enforce frame-independent default unless policy declares frame_dependent=true
- Route validation failures to INSUFFICIENT with LLM_VALIDATION_FAILURE flag

Per 01_DATA_MODELS.md and 03_PIPELINE.md §decomposer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from .policies import get_default_policy
from .synthesis import SynthesisEngine
from .v15_models import (
    AtomicSubclaim,
    ClaimExpression,
    ClaimType,
    EvidenceItem,
    FactCheckResult,
    HumanReviewFlag,
    NodeType,
    PremiseDecomposition,
    ProvenanceSpan,
    Side,
    ValidationResult,
)

# ---------------------------------------------------------------------------
# Stopwords for semantic equivalence heuristic
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "to",
    "of",
    "and",
    "in",
    "that",
    "have",
    "it",
    "for",
    "on",
    "with",
    "as",
    "this",
    "by",
    "from",
    "they",
    "we",
    "say",
    "her",
    "she",
    "or",
    "an",
    "will",
    "my",
    "one",
    "all",
    "would",
    "there",
    "their",
    "what",
    "so",
    "up",
    "out",
    "if",
    "about",
    "who",
    "get",
    "which",
    "go",
    "me",
    "when",
    "make",
    "can",
    "like",
    "time",
    "no",
    "just",
    "him",
    "know",
    "take",
    "people",
    "into",
    "year",
    "your",
    "good",
    "some",
    "could",
    "them",
    "see",
    "other",
    "than",
    "then",
    "now",
    "look",
    "only",
    "come",
    "its",
    "over",
    "think",
    "also",
    "back",
    "after",
    "use",
    "two",
    "how",
    "our",
    "work",
    "first",
    "well",
    "way",
    "even",
    "new",
    "want",
    "because",
    "any",
    "these",
    "give",
    "day",
    "most",
    "us",
}

# ---------------------------------------------------------------------------
# CanonicalPremise input model
# ---------------------------------------------------------------------------


@dataclass
class CanonicalPremise:
    premise_id: str
    snapshot_id: str
    original_text: str
    topic_id: str
    side: Side
    provenance_spans: List[ProvenanceSpan] = field(default_factory=list)
    claim_type: ClaimType = ClaimType.EMPIRICAL_ATOMIC
    frame_info: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _significant_words(text: str) -> Set[str]:
    return {
        w.lower()
        for w in re.findall(r"[a-zA-Z]+", text)
        if w.lower() not in _STOPWORDS
    }


def _is_simple_claim(text: str) -> bool:
    """Heuristic: claim is simple if it lacks obvious logical connectives."""
    lowered = text.lower()
    # Semicolons usually separate distinct clauses
    if ";" in lowered:
        return False
    compound_keywords = [
        " and ",
        " or ",
        " if ",
        " while ",
        " all ",
        " every ",
        " some ",
        " at least ",
        " most ",
        " compare ",
        " versus ",
        " vs ",
        " greater than ",
        " less than ",
        " equal to ",
    ]
    return not any(k in lowered for k in compound_keywords)


def validate_claim_expression(
    expr: ClaimExpression,
    subclaim_ids: Set[str],
    depth: int = 0,
) -> List[str]:
    """Structural validation for a ClaimExpression tree."""
    errors: List[str] = []
    if depth > 3:
        errors.append(f"ClaimExpression exceeds max depth of 3 (depth={depth})")

    if expr.node_type == NodeType.ATOMIC:
        if not expr.subclaim_id:
            errors.append("ATOMIC node missing subclaim_id")
        elif expr.subclaim_id not in subclaim_ids:
            errors.append(f"ATOMIC node references unknown subclaim_id: {expr.subclaim_id}")
        if expr.children:
            errors.append("ATOMIC node must have no children")
    elif expr.node_type in (NodeType.AND, NodeType.OR):
        if len(expr.children) < 2:
            errors.append(f"{expr.node_type.value} must have at least 2 children")
    elif expr.node_type == NodeType.NOT:
        if len(expr.children) != 1:
            errors.append("NOT must have exactly 1 child")
    elif expr.node_type == NodeType.IF_THEN:
        if len(expr.children) != 2:
            errors.append("IF_THEN must have exactly 2 children")
    elif expr.node_type == NodeType.COMPARISON:
        if not expr.operator:
            errors.append("COMPARISON must define operator")
        if len(expr.children) != 2:
            errors.append("COMPARISON must have exactly 2 children")
    elif expr.node_type == NodeType.QUANTIFIER:
        if not expr.quantifier:
            errors.append("QUANTIFIER must define quantifier")

    for child in expr.children:
        errors.extend(validate_claim_expression(child, subclaim_ids, depth + 1))
    return errors


def validate_provenance_spans(
    decomposition: PremiseDecomposition,
    premise: CanonicalPremise,
) -> List[str]:
    errors: List[str] = []
    parent_keys = {(s.span_id, s.post_id) for s in premise.provenance_spans}
    for subclaim in decomposition.atomic_subclaims:
        subclaim_keys = {(s.span_id, s.post_id) for s in subclaim.provenance_spans}
        missing = parent_keys - subclaim_keys
        if missing:
            errors.append(
                f"Subclaim {subclaim.subclaim_id} missing provenance spans: {missing}"
            )
    return errors


def validate_semantic_equivalence(
    decomposition: PremiseDecomposition,
    premise: CanonicalPremise,
) -> List[str]:
    """Lightweight deterministic check that no new claims are introduced."""
    errors: List[str] = []
    original_words = _significant_words(premise.original_text)
    for subclaim in decomposition.atomic_subclaims:
        subclaim_words = _significant_words(subclaim.text)
        new_words = subclaim_words - original_words
        if new_words:
            errors.append(
                f"Subclaim {subclaim.subclaim_id} introduces new significant words: {new_words}"
            )
    return errors


def validate_logical_structure(
    decomposition: PremiseDecomposition,
    premise: CanonicalPremise,
) -> List[str]:
    """Heuristic check that root node type matches obvious logical connectives."""
    errors: List[str] = []
    text_lower = premise.original_text.lower()
    root = decomposition.root_claim_expression.node_type

    has_and = " and " in text_lower or " while " in text_lower or ";" in text_lower
    has_or = " or " in text_lower
    has_if_then = " if " in text_lower and (
        " then " in text_lower or " else " in text_lower
    )

    if has_and and root not in (NodeType.AND, NodeType.ATOMIC):
        errors.append("Original premise contains compound 'and' but root is not AND")
    if has_or and root not in (NodeType.OR, NodeType.ATOMIC):
        errors.append("Original premise contains compound 'or' but root is not OR")
    if has_if_then and root not in (NodeType.IF_THEN, NodeType.ATOMIC):
        errors.append("Original premise contains conditional but root is not IF_THEN")

    if root == NodeType.AND and not has_and:
        errors.append("Root is AND but original premise lacks obvious 'and' connective")
    if root == NodeType.OR and not has_or:
        errors.append("Root is OR but original premise lacks obvious 'or' connective")
    if root == NodeType.IF_THEN and not has_if_then:
        errors.append(
            "Root is IF_THEN but original premise lacks obvious conditional connective"
        )

    return errors


def validate_frame_independence(
    decomposition: PremiseDecomposition,
    premise: CanonicalPremise,
) -> List[str]:
    errors: List[str] = []
    if premise.frame_info:
        for subclaim in decomposition.atomic_subclaims:
            policy = get_default_policy(subclaim.claim_type)
            if policy and not policy.frame_dependent:
                for key in premise.frame_info:
                    key_lower = key.lower()
                    if (
                        key_lower in subclaim.text.lower()
                        or key_lower in subclaim.operationalization_hint.lower()
                    ):
                        errors.append(
                            f"Subclaim {subclaim.subclaim_id} references frame term '{key}' "
                            f"but policy {policy.policy_id} is not frame_dependent"
                        )
    return errors


def validate_decomposition(
    decomposition: PremiseDecomposition,
    premise: CanonicalPremise,
) -> ValidationResult:
    """Run the full validation suite on a PremiseDecomposition."""
    errors: List[str] = []
    subclaim_ids = {sc.subclaim_id for sc in decomposition.atomic_subclaims}

    errors.extend(
        validate_claim_expression(decomposition.root_claim_expression, subclaim_ids)
    )
    errors.extend(validate_provenance_spans(decomposition, premise))
    errors.extend(validate_semantic_equivalence(decomposition, premise))
    errors.extend(validate_logical_structure(decomposition, premise))
    errors.extend(validate_frame_independence(decomposition, premise))

    # Reachability rule: every AtomicSubclaim must be reachable from root
    reachable_ids: Set[str] = set()

    def _collect_atomic_ids(expr: ClaimExpression) -> None:
        if expr.node_type == NodeType.ATOMIC and expr.subclaim_id:
            reachable_ids.add(expr.subclaim_id)
        for child in expr.children:
            _collect_atomic_ids(child)

    _collect_atomic_ids(decomposition.root_claim_expression)
    unreachable = subclaim_ids - reachable_ids
    if unreachable:
        errors.append(f"AtomicSubclaims unreachable from root: {unreachable}")

    return ValidationResult(valid=(len(errors) == 0), errors=errors)


# ---------------------------------------------------------------------------
# Decomposer
# ---------------------------------------------------------------------------


class Decomposer:
    """LLM-assisted decomposer with deterministic validation and fallback."""

    def __init__(
        self,
        llm_backend: Optional[
            Callable[[CanonicalPremise], PremiseDecomposition]
        ] = None,
    ):
        self.llm_backend = llm_backend

    def decompose(self, premise: CanonicalPremise) -> PremiseDecomposition:
        """Decompose a canonical premise into a PremiseDecomposition."""
        if self.llm_backend is not None:
            try:
                decomposition = self.llm_backend(premise)
                decomposition.validation_result = validate_decomposition(
                    decomposition, premise
                )
                # Return the decomposition even if invalid so the pipeline
                # can route validation failures to INSUFFICIENT with the
                # appropriate audit metadata and flags.
                return decomposition
            except Exception:
                # LLM backend raised — fall through to deterministic fallback
                pass

        return self._fallback(premise)

    def _fallback(self, premise: CanonicalPremise) -> PremiseDecomposition:
        if _is_simple_claim(premise.original_text):
            # Wrap in a single ATOMIC node
            subclaim_id = f"{premise.premise_id}_atomic"
            atomic = AtomicSubclaim(
                subclaim_id=subclaim_id,
                parent_premise_id=premise.premise_id,
                text=premise.original_text,
                claim_type=premise.claim_type,
                provenance_spans=list(premise.provenance_spans),
            )
            root = ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id=subclaim_id)
            return PremiseDecomposition(
                premise_id=premise.premise_id,
                snapshot_id=premise.snapshot_id,
                original_text=premise.original_text,
                topic_id=premise.topic_id,
                side=premise.side,
                root_claim_expression=root,
                atomic_subclaims=[atomic],
                provenance_spans=list(premise.provenance_spans),
                validation_result=ValidationResult(valid=True, errors=[]),
            )

        # Complex claim without LLM — route to INSUFFICIENT via invalid decomposition
        subclaim_id = f"{premise.premise_id}_failed"
        atomic = AtomicSubclaim(
            subclaim_id=subclaim_id,
            parent_premise_id=premise.premise_id,
            text=premise.original_text,
            claim_type=premise.claim_type,
            provenance_spans=list(premise.provenance_spans),
        )
        root = ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id=subclaim_id)
        return PremiseDecomposition(
            premise_id=premise.premise_id,
            snapshot_id=premise.snapshot_id,
            original_text=premise.original_text,
            topic_id=premise.topic_id,
            side=premise.side,
            root_claim_expression=root,
            atomic_subclaims=[atomic],
            provenance_spans=list(premise.provenance_spans),
            validation_result=ValidationResult(
                valid=False,
                errors=[
                    "decomposition_failure: complex claim and LLM decomposition unavailable"
                ],
            ),
        )


# ---------------------------------------------------------------------------
# Pipeline wrapper
# ---------------------------------------------------------------------------


def _is_normative(text: str) -> bool:
    """Heuristic: detect normative claims that should be routed out."""
    lowered = text.lower()
    normative_indicators = [
        "should ",
        "ought to ",
        "must ",
        "it is right",
        "it is wrong",
        "it is immoral",
        "it is moral",
        "unjust",
        "just ",
        "fair ",
        "unfair ",
        "better to ",
        "worse to ",
    ]
    return any(ind in lowered for ind in normative_indicators)


def decompose_and_synthesize(
    premise: CanonicalPremise,
    evidence_items: List[EvidenceItem],
    decomposer: Decomposer,
    engine: SynthesisEngine,
    **synthesize_kwargs,
) -> FactCheckResult:
    """
    Pre-processing step: decompose, validate, then synthesize.
    If validation fails, return an authoritative INSUFFICIENT result.
    """
    # Normative claim routing (Gold test #29)
    if premise.claim_type == ClaimType.EMPIRICAL_ATOMIC and _is_normative(premise.original_text):
        return FactCheckResult(
            premise_id=premise.premise_id,
            snapshot_id=premise.snapshot_id,
            topic_id=premise.topic_id,
            side=premise.side,
            status="INSUFFICIENT",
            p=0.5,
            confidence=0.5,
            insufficiency_reason="normative_claim_routed_out",
            provenance_spans=list(premise.provenance_spans),
            subclaim_results=[],
            audit_metadata={
                "decomposition_version": "v1.5-phase2",
                "normative_routed": True,
            },
        )

    decomposition = decomposer.decompose(premise)

    if not decomposition.validation_result.valid:
        reason = "decomposition_failure"
        errors = decomposition.validation_result.errors
        if any("policy_gap" in e for e in errors):
            reason = "policy_gap"
        return FactCheckResult(
            premise_id=premise.premise_id,
            snapshot_id=premise.snapshot_id,
            topic_id=premise.topic_id,
            side=premise.side,
            status="INSUFFICIENT",
            p=0.5,
            confidence=0.5,
            insufficiency_reason=reason,
            human_review_flags=[HumanReviewFlag.LLM_VALIDATION_FAILURE],
            provenance_spans=list(premise.provenance_spans),
            subclaim_results=[],
            audit_metadata={
                "decomposition_version": "v1.5-phase2",
                "validation_errors": errors,
            },
        )

    return engine.synthesize(decomposition, evidence_items, **synthesize_kwargs)


# ---------------------------------------------------------------------------
# Audited pipeline wrapper (Phase 5)
# ---------------------------------------------------------------------------


def decompose_synthesize_and_audit(
    premise: CanonicalPremise,
    evidence_items: List[EvidenceItem],
    decomposer: Decomposer,
    engine: SynthesisEngine,
    audit_store: "AuditStore",
    evidence_policy_version: str = "",
    connector_versions: Optional[Dict[str, str]] = None,
    display_summary: Optional[Any] = None,
    **synthesize_kwargs,
) -> "Tuple[FactCheckResult, Any]":
    """
    Full pipeline: decompose, validate, synthesize, and create an AuditRecord.

    Returns (FactCheckResult, AuditRecord).
    """
    from .v15_audit import AuditStore, build_audit_record

    # Run decomposition first so we have the decomposition for the audit record
    decomposition = decomposer.decompose(premise)

    # Run synthesis
    fact_check_result = decompose_and_synthesize(premise, evidence_items, decomposer, engine, **synthesize_kwargs)

    # Build evidence retrieval manifest
    evidence_retrieval_manifest: List[Dict[str, Any]] = []
    connector_counts: Dict[str, int] = {}
    for item in evidence_items:
        connector_counts[item.connector_version] = connector_counts.get(item.connector_version, 0) + 1
    for connector, count in connector_counts.items():
        evidence_retrieval_manifest.append({
            "connector": connector,
            "query_hash": "",  # Would be populated by real connectors
            "item_count": count,
        })

    # Get previous audit hash for tamper chain
    previous_hash = audit_store.get_latest_audit_hash(premise.snapshot_id)

    # Build audit record
    audit_record = build_audit_record(
        fact_check_result=fact_check_result,
        input_premise_text=premise.original_text,
        input_frame_id=premise.frame_info.get("frame_id", "") if premise.frame_info else "",
        input_provenance_spans=list(premise.provenance_spans),
        root_claim_expression=decomposition.root_claim_expression,
        atomic_subclaims=decomposition.atomic_subclaims,
        evidence_items=evidence_items,
        evidence_retrieval_manifest=evidence_retrieval_manifest,
        decomposition_version=fact_check_result.audit_metadata.get("decomposition_version", "v1.5"),
        evidence_policy_version=evidence_policy_version,
        connector_versions=connector_versions or {},
        display_summary=display_summary,
        previous_audit_hash=previous_hash,
        synthesis_rule_engine_version=fact_check_result.audit_metadata.get(
            "synthesis_rule_engine_version", "v1.5"
        ),
    )

    # Store immutably
    audit_store.store(audit_record)

    return fact_check_result, audit_record
