"""
Non-authoritative DisplaySummary generator for the LSD Fact-Checking System v1.5.

Responsibilities:
- Generate human-readable explanations from SynthesisLogic only
- Consistency checker: status, p, tier, and insufficiency_reason must align
- Failed display summary fallback to machine-generated template
- Display summary hash separate from authoritative_result_hash
- Bad display prose must never alter status or p

Per 03_PIPELINE.md §display and 04_ROADMAP.md Phase 7.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .v15_audit import DisplaySummary
from .v15_models import (
    FactCheckResult,
    HumanReviewFlag,
    SubclaimResult,
)

# ---------------------------------------------------------------------------
# Consistency check result
# ---------------------------------------------------------------------------


@dataclass
class ConsistencyCheckResult:
    """Result of a display-summary consistency check."""

    passed: bool
    violations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Templates for machine-generated fallback
# ---------------------------------------------------------------------------

_STATUS_VERDICT_TEMPLATES = {
    "SUPPORTED": "The claim is supported by the available evidence.",
    "REFUTED": "The claim is refuted by the available evidence.",
    "INSUFFICIENT": "The available evidence is insufficient to determine the claim's accuracy.",
}

_INSUFFICIENCY_REASON_EXPLANATIONS = {
    "entity_resolution_failure": "Required entities could not be resolved.",
    "policy_gap": "No evidence policy applies to this claim type.",
    "evidence_scope_narrower_than_claim": "The evidence scope is narrower than the claim scope.",
    "no_evidence_retrieved": "No evidence was retrieved for this claim.",
    "connector_failure": "A connector failure prevented evidence retrieval.",
    "connector_offline_placeholder": "Connectors are offline; no live evidence was retrieved.",
    "only_tier3_evidence": "Only Tier 3 (search/discovery) evidence is available, which is insufficient alone.",
    "tier2_evidence_mixed_or_insufficient": "Tier 2 evidence is mixed, unclear, or fails cross-verification requirements.",
    "predictive_claim_not_checkable": "Predictive claims cannot be fact-checked until the predicted event occurs or fails to occur.",
    "contradictory_tier1_evidence": "Contradictory Tier 1 evidence could not be resolved by authority ranking.",
    "antecedent_refuted_conditional_not_substantively_checkable": "The conditional claim cannot be checked because its antecedent is refuted.",
}

_REVIEW_FLAG_EXPLANATIONS = {
    HumanReviewFlag.ENTITY_AMBIGUITY: "Entity ambiguity detected.",
    HumanReviewFlag.POLICY_GAP: "A policy gap was identified.",
    HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE: "Contradictory Tier 1 evidence requires human review.",
    HumanReviewFlag.HIGH_IMPACT_INSUFFICIENT: "High-impact claim marked insufficient.",
    HumanReviewFlag.HIGH_IMPACT_LLM_DIRECTION: "High-impact claim with LLM-classified direction flagged for review.",
    HumanReviewFlag.CAUSAL_COMPLEXITY: "Causal complexity flagged for review.",
    HumanReviewFlag.SCIENTIFIC_SCOPE_OVERCLAIM: "Scientific scope overclaim detected.",
    HumanReviewFlag.LLM_VALIDATION_FAILURE: "LLM decomposition validation failure.",
    HumanReviewFlag.CONNECTOR_FAILURE: "Connector failure flagged.",
    HumanReviewFlag.TEMPORAL_SCOPE_AMBIGUITY: "Temporal scope ambiguity detected.",
    HumanReviewFlag.SOURCE_CONFLICT: "Source conflict flagged.",
    HumanReviewFlag.SCOPE_MISMATCH: "Scope mismatch detected.",
}


# ---------------------------------------------------------------------------
# DisplaySummaryGenerator
# ---------------------------------------------------------------------------


class DisplaySummaryGenerator:
    """
    Generate DisplaySummary objects from SynthesisLogic only.

    - Authoritative fields (status, p, tier, insufficiency_reason) are never
      altered by display generation.
    - Consistency checker validates that prose aligns with authoritative data.
    - On failure, falls back to a deterministic machine-generated template.
    """

    def __init__(self, strict: bool = True):
        self.strict = strict

    def generate(
        self,
        result: FactCheckResult,
        custom_summary_text: str | None = None,
        custom_explanation: str | None = None,
    ) -> tuple[DisplaySummary, ConsistencyCheckResult]:
        """
        Generate a DisplaySummary for a FactCheckResult.

        If custom_summary_text / custom_explanation are provided, they are
        validated for consistency.  If they fail validation (or are omitted),
        a machine-generated template is used instead.

        Returns (DisplaySummary, ConsistencyCheckResult).
        The DisplaySummary is always non-authoritative and safe to store.
        """
        # Build candidate summary from custom text or synthesis logic
        candidate = self._build_candidate(
            result=result,
            custom_summary_text=custom_summary_text,
            custom_explanation=custom_explanation,
        )

        # Run consistency check
        consistency = check_summary_consistency(candidate, result)

        if not consistency.passed:
            # Fallback to machine-generated template
            candidate = _generate_template_summary(result)
            # Re-check; template should always pass
            consistency = check_summary_consistency(candidate, result)
            if not consistency.passed:
                # Defensive: if template itself fails, force a minimal safe text
                candidate = _generate_minimal_safe_summary(result)
                consistency = ConsistencyCheckResult(passed=True, violations=[])

        # Populate generated-at timestamp and generation model info
        candidate.generated_at = datetime.now(UTC).isoformat()
        candidate.generation_model = "synthesis_logic_template_v1"

        return candidate, consistency

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_candidate(
        self,
        result: FactCheckResult,
        custom_summary_text: str | None,
        custom_explanation: str | None,
    ) -> DisplaySummary:
        """Build a candidate DisplaySummary."""
        if custom_summary_text is not None or custom_explanation is not None:
            return DisplaySummary(
                summary_text=custom_summary_text or "",
                explanation=custom_explanation or "",
                citations_formatted=list(result.citations),
                confidence_statement=_confidence_statement(result.confidence),
            )

        # No custom text: generate from synthesis logic
        return _generate_from_synthesis_logic(result)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_display_summary(
    result: FactCheckResult,
    custom_summary_text: str | None = None,
    custom_explanation: str | None = None,
    strict: bool = True,
) -> tuple[DisplaySummary, ConsistencyCheckResult]:
    """
    Convenience function: generate and validate a DisplaySummary.

    Returns (display_summary, consistency_check_result).
    """
    generator = DisplaySummaryGenerator(strict=strict)
    return generator.generate(
        result=result,
        custom_summary_text=custom_summary_text,
        custom_explanation=custom_explanation,
    )


# ---------------------------------------------------------------------------
# Consistency checker
# ---------------------------------------------------------------------------


def check_summary_consistency(
    display_summary: DisplaySummary,
    result: FactCheckResult,
) -> ConsistencyCheckResult:
    """
    Check that display_summary prose is consistent with authoritative fields.

    Checks:
    - status consistency (on summary_text only, to allow subclaim detail in explanation)
    - p consistency (on summary_text only, to allow subclaim p-values in explanation)
    - tier consistency
    - insufficiency_reason consistency
    """
    violations: list[str] = []
    summary_text = display_summary.summary_text.lower()
    full_text = (display_summary.summary_text + " " + display_summary.explanation).lower()

    # --- Status consistency (summary only) ---
    status = result.status
    status_violation = _check_status_in_text(status, summary_text)
    if status_violation:
        violations.append(status_violation)

    # --- p consistency (summary only) ---
    # Explanation may contain subclaim p-values; only check the headline summary.
    p_violation = _check_p_in_text(result.p, summary_text)
    if p_violation:
        violations.append(p_violation)

    # --- Tier consistency (full text) ---
    tier_violation = _check_tier_in_text(result.best_evidence_tier, full_text)
    if tier_violation:
        violations.append(tier_violation)

    # --- Insufficiency reason consistency (full text) ---
    reason_violation = _check_insufficiency_reason_in_text(result.insufficiency_reason, full_text)
    if reason_violation:
        violations.append(reason_violation)

    return ConsistencyCheckResult(
        passed=len(violations) == 0,
        violations=violations,
    )


def _check_status_in_text(status: str, text: str) -> str | None:
    """Detect contradictions between status and summary text."""
    # Use word-boundary regex to avoid flagging phrases like "true or false"
    # Strong verdict words that clearly imply a status
    supported_words = ["supported", "confirmed", "verified"]
    refuted_words = ["refuted", "incorrect", "debunked"]

    def _has_word(words: list[str]) -> str | None:
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", text):
                return w
        return None

    if status == "SUPPORTED":
        found = _has_word(refuted_words)
        if found:
            return f"status_inconsistency: result is SUPPORTED but text contains '{found}'"
        # Also flag standalone "is false" as a direct verdict
        if re.search(r"\bis false\b", text):
            return "status_inconsistency: result is SUPPORTED but text contains 'is false'"
    elif status == "REFUTED":
        found = _has_word(supported_words)
        if found:
            return f"status_inconsistency: result is REFUTED but text contains '{found}'"
        if re.search(r"\bis true\b", text):
            return "status_inconsistency: result is REFUTED but text contains 'is true'"
    elif status == "INSUFFICIENT":
        found_supported = _has_word(supported_words)
        if found_supported:
            return f"status_inconsistency: result is INSUFFICIENT but text contains '{found_supported}'"
        found_refuted = _has_word(refuted_words)
        if found_refuted:
            return (
                f"status_inconsistency: result is INSUFFICIENT but text contains '{found_refuted}'"
            )
        # Also flag direct verdict phrases that clearly assert truth/falsity
        if re.search(r"\bis false\b", text):
            return "status_inconsistency: result is INSUFFICIENT but text contains 'is false'"
        if re.search(r"\bis true\b", text):
            return "status_inconsistency: result is INSUFFICIENT but text contains 'is true'"
    return None


def _check_p_in_text(p: float, text: str) -> str | None:
    """Detect contradictions between p and summary text."""
    # Look for explicit probability mentions like "p=0.0", "p value is 0.0", etc.
    # This is a best-effort heuristic.
    patterns = [
        r"p\s*=\s*([0-9.]+)",
        r"p\s+value\s+(?:is\s+)?([0-9.]+)",
        r"probability\s+(?:is\s+)?([0-9.]+)",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            try:
                stated_p = float(m)
                if abs(stated_p - p) > 0.01:
                    return f"p_inconsistency: text states p={stated_p} but result p={p}"
            except ValueError:
                continue

    # Look for percentage mentions that map to p values
    # e.g. "100%" for p=1.0, "0%" for p=0.0, "50%" for p=0.5
    pct_pattern = r"([0-9]+)\s*%"
    pct_matches = re.findall(pct_pattern, text)
    for m in pct_matches:
        try:
            stated_pct = int(m)
            # Only flag extreme mismatches (e.g., 100% when p=0.0)
            expected_pct = int(p * 100)
            if abs(stated_pct - expected_pct) > 25:
                return (
                    f"p_inconsistency: text states {stated_pct}% but result p={p} ({expected_pct}%)"
                )
        except ValueError:
            continue

    return None


def _check_tier_in_text(tier: int | None, text: str) -> str | None:
    """Detect contradictions between best_evidence_tier and summary text."""
    if tier is None:
        return None

    # Look for "tier 1", "tier 2", "tier 3"
    for t in (1, 2, 3):
        if f"tier {t}" in text or f"tier-{t}" in text:
            if t != tier:
                return f"tier_inconsistency: text mentions tier {t} but result best_evidence_tier={tier}"
    return None


def _check_insufficiency_reason_in_text(reason: str | None, text: str) -> str | None:
    """Detect contradictions between insufficiency_reason and summary text."""
    if reason is None:
        # If there's no reason, text should not mention specific reasons
        # (except generic ones)
        return None

    # If reason exists, check that text doesn't state a *different* specific reason
    # This is best-effort: map known reasons to keyword sets
    reason_keywords: dict[str, list[str]] = {
        "entity_resolution_failure": ["entity resolution", "ambiguous entity"],
        "policy_gap": ["policy gap", "no policy"],
        "evidence_scope_narrower_than_claim": ["scope narrower", "narrower scope"],
        "no_evidence_retrieved": [
            "no evidence was retrieved",
            "no evidence retrieved",
            "no evidence found",
        ],
        "connector_failure": ["connector failure"],
        "connector_offline_placeholder": ["offline"],
        "only_tier3_evidence": ["only tier 3", "tier 3 only"],
        "tier2_evidence_mixed_or_insufficient": ["tier 2 mixed", "cross-verification"],
        "predictive_claim_not_checkable": ["predictive", "future"],
        "contradictory_tier1_evidence": ["contradictory tier 1"],
        "antecedent_refuted_conditional_not_substantively_checkable": ["antecedent refuted"],
    }

    for known_reason, keywords in reason_keywords.items():
        if known_reason == reason:
            continue
        for kw in keywords:
            if kw in text:
                # If text mentions a specific reason that is NOT the actual reason,
                # flag it.  Be lenient: only flag if the actual reason is different.
                if reason != known_reason:
                    return (
                        f"reason_inconsistency: text implies '{known_reason}' "
                        f"but actual insufficiency_reason='{reason}'"
                    )
    return None


# ---------------------------------------------------------------------------
# Machine-generated template (fallback)
# ---------------------------------------------------------------------------


def _generate_template_summary(result: FactCheckResult) -> DisplaySummary:
    """
    Generate a deterministic, machine-generated DisplaySummary from
    authoritative fields.  This is the fallback when custom text fails
    consistency checks.
    """
    status = result.status
    p = result.p
    tier = result.best_evidence_tier
    reason = result.insufficiency_reason
    flags = result.human_review_flags

    # Summary line
    summary_text = _STATUS_VERDICT_TEMPLATES.get(status, "Verdict unavailable.")

    # Explanation paragraphs
    explanation_parts: list[str] = []

    # p value statement
    explanation_parts.append(_p_statement(status, p))

    # Tier statement
    if tier is not None:
        explanation_parts.append(_tier_statement(tier))

    # Insufficiency reason
    if reason:
        reason_explanation = _INSUFFICIENCY_REASON_EXPLANATIONS.get(reason, f"Reason: {reason}.")
        explanation_parts.append(reason_explanation)

    # Human review flags
    if flags:
        flag_notes = [
            _REVIEW_FLAG_EXPLANATIONS.get(f, str(f)) for f in flags if f != HumanReviewFlag.NONE
        ]
        if flag_notes:
            explanation_parts.append("Review flags: " + "; ".join(flag_notes))

    # Subclaim breakdown for compound premises
    if len(result.subclaim_results) > 1:
        explanation_parts.append(_subclaim_breakdown(result.subclaim_results))

    explanation = " ".join(explanation_parts)

    return DisplaySummary(
        summary_text=summary_text,
        explanation=explanation,
        citations_formatted=list(result.citations),
        confidence_statement=_confidence_statement(result.confidence),
    )


def _generate_minimal_safe_summary(result: FactCheckResult) -> DisplaySummary:
    """Ultra-minimal safe summary guaranteed to pass consistency."""
    return DisplaySummary(
        summary_text=f"Verdict: {result.status}.",
        explanation=f"p = {result.p}; confidence = {result.confidence:.2f}.",
        citations_formatted=list(result.citations),
        confidence_statement=_confidence_statement(result.confidence),
    )


def _generate_from_synthesis_logic(result: FactCheckResult) -> DisplaySummary:
    """
    Generate a DisplaySummary directly from SynthesisLogic fields.
    This is the default path when no custom text is provided.
    """
    # In practice, this generates the same template summary because
    # SynthesisLogic fields (status_rule_applied, insufficiency_trigger, etc.)
    # are the authoritative sources we trust.  We map them to human prose.
    return _generate_template_summary(result)


def _p_statement(status: str, p: float) -> str:
    if status == "SUPPORTED":
        return f"The factuality score is {p:.1f} (fully supported)."
    if status == "REFUTED":
        return f"The factuality score is {p:.1f} (fully refuted)."
    return f"The factuality score is {p:.1f} (insufficient evidence)."


def _tier_statement(tier: int) -> str:
    if tier == 1:
        return "Best evidence tier: Tier 1 (official / primary source)."
    if tier == 2:
        return "Best evidence tier: Tier 2 (curated / secondary source)."
    return "Best evidence tier: Tier 3 (search / discovery)."


def _confidence_statement(confidence: float) -> str:
    if confidence >= 0.9:
        return f"High confidence ({confidence:.2f})."
    if confidence >= 0.7:
        return f"Moderate confidence ({confidence:.2f})."
    if confidence >= 0.5:
        return f"Low confidence ({confidence:.2f})."
    return f"Very low confidence ({confidence:.2f})."


def _subclaim_breakdown(subclaim_results: list[SubclaimResult]) -> str:
    parts: list[str] = []
    for sr in subclaim_results:
        parts.append(f"{sr.subclaim_id}: {sr.status} (p={sr.p})")
    return "Subclaim breakdown: " + "; ".join(parts) + "."
