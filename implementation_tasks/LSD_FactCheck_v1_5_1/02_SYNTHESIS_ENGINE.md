# 02 — Synthesis Engine

This file defines the hard-coded synthesis rules, ClaimExpression evaluation, and tier reporting logic.

---

## Table of Contents

1. Atomic Subclaim Synthesis Rules
2. LLM Evidence-Direction Gating
3. ClaimExpression Evaluation
4. Compound Evidence Tier Reporting
5. Confidence Calculation

---

## 1. Atomic Subclaim Synthesis Rules

For each AtomicSubclaim, apply rules in order. The first matching rule determines the result.

### Rule A — Entity failure
If required entity resolution failed:
- status = INSUFFICIENT
- p = 0.5
- insufficiency_reason = "entity_resolution_failure"

### Rule B — Policy gap
If no EvidencePolicy applies:
- status = INSUFFICIENT
- p = 0.5
- insufficiency_reason = "policy_gap"
- human_review_flags += POLICY_GAP

### Rule C — Scope mismatch
If evidence scope is narrower than claim scope and cannot validly generalize:
- status = INSUFFICIENT
- p = 0.5
- insufficiency_reason = "evidence_scope_narrower_than_claim"
- human_review_flags += SCOPE_MISMATCH

### Rule D — Tier 1 decisive evidence
If Tier 1 evidence directly supports or refutes and no contradictory Tier 1 exists:
- status = SUPPORTED or REFUTED
- p = 1.0 or 0.0
- confidence >= 0.9

### Rule E — Contradictory Tier 1 evidence
If contradictory Tier 1 evidence exists:
- If authority hierarchy clearly ranks one source above the other (e.g., Supreme Court ruling > agency preliminary report; final official stats > preliminary estimate; systematic review > single study):
  - follow higher-authority source
  - authority_ranking_applied = true
- Else:
  - status = INSUFFICIENT
  - p = 0.5
  - human_review_flags += CONTRADICTORY_TIER1_EVIDENCE

### Rule F — Tier 2 decisive evidence
If only Tier 2 evidence is available and cross-verification is satisfied when required:
- status = SUPPORTED or REFUTED
- p = 1.0 or 0.0
- confidence = 0.7 to 0.9

### Rule G — Tier 2 mixed/unclear
If Tier 2 evidence is mixed, unclear, not independent, or insufficient for the policy:
- status = INSUFFICIENT
- p = 0.5
- insufficiency_reason = "tier2_evidence_mixed_or_insufficient"

### Rule H — Tier 3 only
If only Tier 3 evidence exists:
- status = INSUFFICIENT
- p = 0.5
- insufficiency_reason = "only_tier3_evidence"

### Rule I — No evidence
If no evidence is retrieved:
- status = INSUFFICIENT
- p = 0.5
- insufficiency_reason = "no_evidence_retrieved"

### Rule J — Predictive claim
If claim is predictive and not reframed as a checkable claim about an existing projection/source:
- status = INSUFFICIENT
- p = 0.5
- insufficiency_reason = "predictive_claim_not_checkable"

---

## 2. LLM Evidence-Direction Gating

For **structured sources** (APIs, databases, official stats):
- Use deterministic comparison whenever possible.
- Do not use LLM direction classification if `source_value` and `claimed_value` can be compared directly.

For **text/RAG/web evidence**, an LLM direction label may be used only if ALL conditions hold:
1. exact `quote_or_span` is stored
2. `decisive_quote_span` is present for decisive evidence
3. `relevance_score >= configured threshold`
4. `direction_confidence >= configured threshold`
5. source tier satisfies EvidencePolicy
6. evidence scope is compatible with claim scope
7. source independence requirements are satisfied when applicable
8. LLM output passes schema validation

If any condition fails:
- direction = UNCLEAR
- the item **cannot alone determine SUPPORTED or REFUTED**

**High-impact claims:**
- If an LLM-classified text item would be decisive for a high-impact claim (LEGAL_REGULATORY, SCIENTIFIC with causal/consensus scope), add `human_review_flags += HIGH_IMPACT_LLM_DIRECTION` unless there is independent corroboration or deterministic verification.

---

## 3. ClaimExpression Evaluation

After atomic subclaims are synthesized, evaluate the root ClaimExpression recursively.

### ATOMIC
- Return referenced SubclaimResult.

### AND
- If any child REFUTED → REFUTED, p = 0.0
- Else if all children SUPPORTED → SUPPORTED, p = 1.0
- Else → INSUFFICIENT, p = 0.5

### OR
- If any child SUPPORTED → SUPPORTED, p = 1.0
- Else if all children REFUTED → REFUTED, p = 0.0
- Else → INSUFFICIENT, p = 0.5

### NOT
- SUPPORTED becomes REFUTED
- REFUTED becomes SUPPORTED
- INSUFFICIENT remains INSUFFICIENT

### IF_THEN
- If antecedent REFUTED → INSUFFICIENT, p = 0.5, reason = "antecedent_refuted_conditional_not_substantively_checkable"
- If antecedent INSUFFICIENT → INSUFFICIENT, p = 0.5
- If antecedent SUPPORTED and consequent SUPPORTED → SUPPORTED, p = 1.0
- If antecedent SUPPORTED and consequent REFUTED → REFUTED, p = 0.0
- If antecedent SUPPORTED and consequent INSUFFICIENT → INSUFFICIENT, p = 0.5

### COMPARISON
- Children must provide ResolvedValue objects with compatible units and scopes.
- If either value is missing or incompatible → INSUFFICIENT, p = 0.5
- If deterministic comparison holds → SUPPORTED, p = 1.0
- If deterministic comparison fails → REFUTED, p = 0.0
- When `deterministic_comparison_result` is MATCH or MISMATCH, the synthesis engine copies the source ResolvedValue into `SubclaimResult.resolved_value` so parent COMPARISON nodes can evaluate numerically.

### QUANTIFIER
- Quantified set must be resolved.
- Predicate must be checkable.
- Threshold must be explicit.
- If set, predicate, or threshold is unresolved → INSUFFICIENT, p = 0.5
- Otherwise evaluate deterministically.

---

## 4. Compound Evidence Tier Reporting

For compound premises:
- citations = union of child citations
- provenance_spans = union of child provenance_spans
- confidence = mean child confidence unless a stricter policy applies
- **best_evidence_tier** = min child decisive tiers **only when compound is SUPPORTED or REFUTED**
- **If compound is INSUFFICIENT**, best_evidence_tier = null or limiting_evidence_tier (do not report min(child tiers) for INSUFFICIENT compounds)
- limiting_evidence_tier = weakest relevant child tier or null if no evidence
- decisive_evidence_tier = tier of the child/path that determined the root status

---

## 5. Confidence Calculation

```python
base = 1.0 if best_evidence_tier == 1 else 0.8 if best_evidence_tier == 2 else 0.5
cross_penalty = 0.2 if (cross_verification_required and not cross_verification_met) else 0.0
entity_penalty = 0.0 if entity_resolution_quality == 1.0 else 0.3
direction_penalty = 0.0 if direction_consistency == 1.0 else 0.2
confidence = max(0.0, base - cross_penalty - entity_penalty - direction_penalty)
```

**Thresholds:**
- Tier 1 + consistent + resolved → confidence >= 0.9
- Tier 2 + consistent + resolved → confidence 0.7–0.9
- Tier 3 or mixed → confidence <= 0.6
- Entity ambiguity → confidence capped at 0.5
