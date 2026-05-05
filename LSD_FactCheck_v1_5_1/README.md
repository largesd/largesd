# LSD Fact-Checking System — Implementation Plan v1.5.1

**Purpose:** Convert the v1.5 fact-checking design into an implementation-ready plan for Kimi's coding agent. Preserves LSD v1.2 requirements and v1.5 architecture.

**Created:** 2026-05-03

---

## Requirement Target

The fact-checking subsystem must satisfy the LSD empirical fact-checking contract:

- **status** ∈ {SUPPORTED, REFUTED, INSUFFICIENT}
- **p** ∈ {1.0, 0.0, 0.5}
- SUPPORTED = sufficient evidence under declared evidence policy
- REFUTED = sufficient evidence refutes under declared evidence policy
- INSUFFICIENT = unavailable, undecidable, ambiguous, scope-narrow, policy-invalid, or connector/entity failure
- Outputs include citations or explicit insufficiency reason
- Outputs include operationalization (what would confirm/refute)
- Outputs include evidence tier information
- Aggregate outputs include tier counts, insufficiency_rate, F_supported_only, and sensitivity to assuming insufficient claims true/false

The fact-checking system feeds the empirical factuality component `F_{t,s}` into the larger Loop B adjudication system. It does not decide the whole debate.

---

## Implementation Principles

### 1. Rule outputs are authoritative
The LLM may help produce structured candidates, but it must not directly produce the final authoritative verdict.

**Authoritative:** status, p, decisive citations, insufficiency_reason, verdict_scope, evidence tier fields, synthesis_logic, authoritative_result_hash

**Non-authoritative:** display_summary prose, decomposition_rationale prose, LLM evidence-direction explanation, user-facing simplified explanation

### 2. Artifact replay is authoritative
- **Artifact replay:** reconstructs exact published result from frozen records, evidence items, model outputs, synthesis logic, and hashes. Must be deterministic.
- **Computational rerun:** reruns connectors and LLM steps from manifest. Diagnostic only. May differ because live APIs/web pages/hosted LLMs change.

### 3. Empirical fact checks should not normally depend on Frames
By default, empirical fact checking is Frame-independent. Frame information may be used only when:
- the evidence policy explicitly declares `frame_dependent = true`, or
- the claim itself is scoped by the Frame in a material way

If Frame information affects decomposition, operationalization, scope, or source policy, then `frame_scope_hash` must be included in the cache key.

### 4. LLMs are allowed only behind validation gates
The LLM may be used for candidate generation (decomposition, classification, disambiguation, direction, display summary). Every LLM output must be validated before use. Failed validation routes to INSUFFICIENT or human review, not to a guessed verdict.

### 5. Build deterministic core before live connectors
The first working version must use mock evidence fixtures. Do not implement live Wikidata, RAG, search, or official APIs until the core rule engine passes the gold tests.

---

## File Index

| File | Contents | Read for Phase |
|------|----------|----------------|
| `01_DATA_MODELS.md` | All schemas, types, enums, validation rules | 1, 2, 3 |
| `02_SYNTHESIS_ENGINE.md` | Hard-coded synthesis rules, ClaimExpression evaluation, tier reporting | 1, 2 |
| `03_PIPELINE.md` | Architecture, connectors, normalizer, cache, audit, scoring boundary | 2, 3, 4, 5 |
| `04_ROADMAP.md` | Implementation phases, gold tests, LLM prompts | All |

**Cross-file references:** When a file references another file (e.g., "see §5.3"), the section number refers to that file's own internal numbering. Use the file index above to locate the correct file.

---

## Acceptance Criteria

1. All authoritative p values are exactly 1.0, 0.0, or 0.5.
2. LLM prose cannot change status or p.
3. ClaimExpression is rooted at PremiseDecomposition, not AtomicSubclaim.
4. Numeric and comparison claims support ResolvedValue.
5. Cache keys include entities, scope, operationalization, policy, decomposition version, connector snapshot versions, and optional frame dependency.
6. Frame context is ignored by empirical fact checking unless explicitly policy-dependent.
7. Tier 3-only evidence cannot support/refute.
8. Low-confidence direction labels cannot be decisive.
9. HumanReviewRecord exists and is immutable/additive.
10. Audit hashes are canonical and stable.
11. Artifact replay works without rerunning live APIs or LLMs.
12. Scoring integration handles empty and all-insufficient cases.
13. Gold tests run in CI.
14. Connector tests are isolated from deterministic unit tests.
15. Old snapshots are never silently modified.
