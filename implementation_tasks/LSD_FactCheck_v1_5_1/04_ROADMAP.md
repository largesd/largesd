# 04 — Roadmap, Gold Tests & LLM Prompts

This file defines the implementation phases, gold test catalog, and specific prompts for Kimi's coding agent.

---

## Table of Contents

1. Package Structure
2. Implementation Roadmap
3. Gold Test Set
4. LLM Implementation Prompts
5. Summary of v1.5 Changes

---

## 1. Package Structure

```
skills/fact_checking/
  __init__.py
  models.py              # all data models from 01_DATA_MODELS.md
  claim_expression.py    # ClaimExpression evaluator
  decomposition.py       # decomposer interface + validation
  policies.py            # EvidencePolicy registry
  connectors.py          # connector interfaces + mock fixtures
  normalizer.py          # EvidenceItem normalizer
  synthesis.py           # SynthesisEngine (hard-coded rules)
  cache.py               # CacheKey + immutable cache
  audit.py               # AuditRecord + canonical hashing
  human_review.py        # HumanReviewFlag + HumanReviewRecord
  scoring_inputs.py      # adapter for scoring/dossier layer
  display_summary.py     # non-authoritative summary generator
  fixtures/              # mock evidence for testing
  tests/                 # gold tests + unit tests
```

---

## 2. Implementation Roadmap

### PHASE 0 — Repository Alignment
**Goal:** Understand current project shape and create stable interfaces.

**Tasks:**
1. Locate existing fact-checking files, tests, data models, DebateEngine integration
2. Identify current FactCheckingSkill API shape
3. Add or update OBJECTIVE.md with v1.5 scope
4. Define package boundaries

**Definition of done:**
- No behavior change yet
- Interfaces documented
- Existing tests still pass

---

### PHASE 1 — Deterministic Core with Mock Evidence
**Goal:** Build the rule engine before live retrieval. **No network access required.**

**Implement:**
1. All data models (see 01_DATA_MODELS.md)
2. ClaimExpression evaluator:
   - ATOMIC, AND, OR, NOT, IF_THEN
   - COMPARISON with ResolvedValue
   - QUANTIFIER placeholder (returns INSUFFICIENT unless deterministic support implemented)
3. Policy-Gated SynthesisEngine:
   - All atomic subclaim synthesis rules (A–J)
   - Compound premise aggregation
   - Tier reporting rules
   - Scope mismatch handling
   - Direction uncertainty handling
4. Mock connector: returns EvidenceItems from fixtures only
5. Initial gold tests (see §3 below)

**Definition of done:**
- Core synthesis works without network access
- Gold tests pass
- No LLM required for Phase 1

---

### PHASE 2 — Decomposition and Validation Layer
**Goal:** Add LLM-assisted decomposition while preserving deterministic validation.

**Implement:**
1. Decomposer interface: input premise → output PremiseDecomposition
2. Validation rules:
   - ClaimExpression structural validation
   - Max depth validation (max 3)
   - All ATOMIC nodes reference known subclaims
   - No unsupported new claims
   - All provenance spans preserved
   - Frame-independent default enforcement
3. Failure behavior:
   - Validation failure → INSUFFICIENT
   - human_review_flags += LLM_VALIDATION_FAILURE
   - Store raw LLM output in audit metadata
4. Deterministic fallback:
   - Single ATOMIC claim expression wrapping original premise if LLM unavailable and claim is simple
   - Otherwise route to INSUFFICIENT with policy_gap or decomposition_failure

**Definition of done:**
- LLM decomposition can be turned off
- Tests cover malformed decomposition outputs
- ClaimExpression stored only at PremiseDecomposition root

---

### PHASE 3 — Evidence Policy, Normalizer, Cache Hardening
**Goal:** Make evidence layer auditable before real connectors.

**Implement:**
1. EvidencePolicy registry (NUMERIC_STATISTICAL, LEGAL_REGULATORY, SCIENTIFIC, GEOGRAPHIC_DEMOGRAPHIC, CURRENT_EVENT, CAUSAL, EMPIRICAL_ATOMIC fallback)
2. Evidence Normalizer:
   - Source metadata normalization
   - VerdictScope extraction
   - ResolvedValue fields
   - Relevance/direction confidence thresholds
   - Deterministic comparison for structured values
   - LLM direction gating fields
3. CacheKey v1.5:
   - Include claim type, entities, scope, operationalization, policy, connectors, decomposition version, optional frame dependency
4. Canonical JSON hashing:
   - Implement canonical serializer
   - Unit test stable hash across key ordering differences

**Definition of done:**
- Same authoritative record produces same hash across runs
- Cache cannot reuse across different scope/entities/policy
- Normalizer rejects unclear/low-confidence decisive evidence

---

### PHASE 4 — Real Connector Layer
**Goal:** Add retrieval without changing synthesis behavior.

**Implement incrementally:**
1. Wikidata entity/static fact connector
2. One official statistics connector or dataset fixture connector
3. One scientific metadata connector (Crossref or PubMed)
4. One Tier 2 curated source connector
5. One Tier 3 search/discovery connector

**Rules:**
- Connectors return EvidenceItems only
- Connectors do not produce final verdicts
- Absence in Wikidata → INSUFFICIENT unless policy defines closed-world source
- Tier 3 cannot alone support/refute
- Source independence group IDs required for cross-verification

**Definition of done:**
- Connector failures produce INSUFFICIENT with connector_failure
- Mock tests still pass unchanged
- Live connector tests separate; can be skipped in CI if credentials unavailable

---

### PHASE 5 — Audit, Replay, Immutable Storage
**Goal:** Make outputs snapshot-compatible.

**Implement:**
1. AuditRecord storage
2. authoritative_result_hash (canonical JSON)
3. display_summary_hash separate from authoritative hash
4. Merkle root over authoritative hashes only
5. ReplayManifest
6. Frozen connector response storage or source snapshot references
7. Web content hash/archive fallback records
8. Additive invalidation records

**Definition of done:**
- Artifact replay reconstructs all authoritative FactCheckResults from frozen records
- Computational rerun labeled diagnostic
- Published hash excludes DisplaySummary

---

### PHASE 6 — Scoring/Dossier Integration
**Goal:** Feed factuality outputs into LSD Loop B.

**Implement scoring adapter:**
1. Group FactCheckResults by topic_id and side
2. Compute F_{t,s}
3. Compute F_supported_only
4. Compute insufficiency_rate
5. Emit tier counts per topic-side
6. Expose inputs for D sensitivity calculation
7. Scoring/dossier layer computes delta_D and DecisivePremiseRanking

**Definition of done:**
- Handles no empirical premises
- Handles all-insufficient premises
- Does not divide by zero
- Does not compute D inside fact-check core

---

### PHASE 7 — Display Summaries and Human Review UI
**Goal:** Add human-readable explanations after authoritative logic is stable.

**Implement:**
1. DisplaySummary generator from SynthesisLogic only
2. Consistency checker:
   - status consistency
   - p consistency
   - tier consistency
   - insufficiency reason consistency
3. Failed display summary fallback (machine-generated template)
4. Human review queue listing
5. Aggregate public counts by review flag with small-count suppression

**Definition of done:**
- Bad display prose cannot alter status or p
- Failed display summary stored but not published as authoritative
- Review queue exists even if dashboard is minimal

---

## 3. Gold Test Set

Build tests before changing production behavior.

### Core Logic Tests (Phase 1)

| # | Test | Expected |
|---|------|----------|
| 1 | SUPPORTED structured entity relation | p=1.0, status=SUPPORTED |
| 2 | REFUTED structured entity relation | p=0.0, status=REFUTED |
| 3 | INSUFFICIENT due to absence in non-closed-world source | p=0.5, reason="no_evidence_retrieved" |
| 4 | Temporal claim with date qualifier | p=1.0 or 0.0 |
| 5 | Numeric statistical claim with official source | p=1.0, tier=1 |
| 6 | Scoped numeric claim requiring geography/date/rounding | p=1.0, verdict_scope set |
| 7 | AND with all supported children | p=1.0 |
| 8 | AND with one refuted child | p=0.0 |
| 9 | AND with one insufficient child | p=0.5 |
| 10 | OR with one supported child | p=1.0 |
| 11 | OR with all refuted children | p=0.0 |
| 12 | OR with insufficient and no supported | p=0.5 |
| 13 | NOT supported → refuted | p=0.0 |
| 14 | NOT refuted → supported | p=1.0 |
| 15 | IF_THEN with refuted antecedent | p=0.5, reason="antecedent_refuted..." |
| 16 | IF_THEN with supported antecedent + refuted consequent | p=0.0 |
| 17 | Nested AND containing OR | Evaluate recursively |
| 18 | Comparison with compatible resolved values → true | p=1.0 |
| 19 | Comparison with compatible resolved values → false | p=0.0 |
| 20 | Comparison with incompatible units | p=0.5 |
| 21 | Quantifier unresolved set | p=0.5 |
| 22 | Ambiguous entity | p=0.5, reason="entity_resolution_failure" |
| 23 | Current-event claim with 2 independent Tier 2 sources | p=1.0 |
| 24 | Current-event claim with 2 non-independent sources | p=0.5 |
| 25 | Scientific study-specific claim | p=1.0, tier=1 or 2 |
| 26 | Scientific broad-consensus overclaim | p=0.5, flag=SCIENTIFIC_SCOPE_OVERCLAIM |
| 27 | Legal claim requiring official source | p=1.0, tier=1 |
| 28 | Predictive claim | p=0.5, reason="predictive_claim_not_checkable" |
| 29 | Normative claim routed out | Not fact-checked |
| 30 | Connector failure | p=0.5, reason="connector_failure" |
| 31 | Contradictory Tier 1 resolved by authority ranking | p=1.0 or 0.0, authority_ranking_applied=true |
| 32 | Contradictory Tier 1 unresolved | p=0.5, flag=CONTRADICTORY_TIER1_EVIDENCE |
| 33 | Tier 3 promotion with registry + independence | Promoted to Tier 2 |
| 34 | Tier 3 non-promotion | p=0.5, reason="only_tier3_evidence" |
| 35 | Provenance span preserved end-to-end | Spans present in FactCheckResult |
| 36 | Scope mismatch | p=0.5, reason="evidence_scope_narrower_than_claim" |
| 37 | Direction confidence below threshold | direction=UNCLEAR, not decisive |
| 38 | LLM decomposition validation failure | p=0.5, flag=LLM_VALIDATION_FAILURE |
| 39 | Cache mismatch due to different verdict scope | Cache miss |
| 40 | Cache mismatch due to different entity ids | Cache miss |
| 41 | Hash stability under reordered JSON keys | Same hash |
| 42 | Empty empirical premise set aggregation | F_{t,s}=null |
| 43 | All-insufficient aggregation | F_{t,s}=0.5, F_supported_only=null |
| 44 | F_supported_only excludes insufficient claims | Correct mean over SUPPORTED/REFUTED only |
| 45 | Display summary contradiction rejected | Fallback to machine-generated template |

---

## 4. LLM Implementation Prompts

### Prompt for Phase 1 (Deterministic Core)

```
You are implementing Phase 1 of the LSD Fact-Checking System v1.5.

Implement only the deterministic core. Do not add live web/API calls, Wikidata, RAG, search, or LLM calls yet.

Read these files first:
- README.md (purpose, principles, acceptance criteria)
- 01_DATA_MODELS.md (all schemas and types)
- 02_SYNTHESIS_ENGINE.md (hard-coded rules and ClaimExpression evaluation)

Create or update the fact-checking package with:

1. Data models:
   - ProvenanceSpan, VerdictScope, ResolvedValue
   - ClaimExpression, AtomicSubclaim, PremiseDecomposition
   - EvidencePolicy, EvidenceItem, SubclaimResult, FactCheckResult
   - SynthesisLogic, HumanReviewFlag, HumanReviewRecord

2. ClaimExpression evaluator:
   - ATOMIC, AND, OR, NOT, IF_THEN
   - COMPARISON using ResolvedValue
   - QUANTIFIER placeholder returning INSUFFICIENT when unresolved

3. Policy-Gated SynthesisEngine:
   - Tier 1 support/refute rules
   - Contradictory Tier 1 handling with authority ranking hook
   - Tier 2 cross-verification rules
   - Tier 3-only → INSUFFICIENT
   - No evidence → INSUFFICIENT
   - Entity failure → INSUFFICIENT
   - Policy gap → INSUFFICIENT
   - Scope mismatch → INSUFFICIENT
   - Low direction confidence → UNCLEAR, not decisive

4. Mock connector/fixture support only.

5. Unit tests for:
   - supported atomic claim
   - refuted atomic claim
   - no evidence → INSUFFICIENT
   - Tier 3 only → INSUFFICIENT
   - contradictory Tier 1 unresolved → INSUFFICIENT
   - contradictory Tier 1 resolved by authority ranking
   - Tier 2 cross-verification satisfied/failed
   - AND/OR/NOT/IF_THEN logic
   - comparison true/false/missing value
   - scope mismatch
   - entity failure
   - all-insufficient aggregation edge case

Important constraints:
- ClaimExpression belongs to PremiseDecomposition.root_claim_expression, not to AtomicSubclaim.
- p must always be exactly 1.0, 0.0, or 0.5.
- LLM-generated prose is not authoritative.
- Do not compute full debate D in the fact-checking core.
- Do not implement real connectors until deterministic tests pass.
```

### Prompt for Phase 2 (Decomposition)

```
You are implementing Phase 2 of the LSD Fact-Checking System v1.5.

Read these files:
- 01_DATA_MODELS.md (ClaimExpression, PremiseDecomposition, AtomicSubclaim)
- 02_SYNTHESIS_ENGINE.md (evaluation rules)
- 03_PIPELINE.md (decomposer interface, validation rules)

Implement:
1. Decomposer interface that takes a canonical premise and outputs PremiseDecomposition.
2. Validation layer:
   - ClaimExpression structural validation (max depth 3, ATOMIC has subclaim_id, etc.)
   - Semantic equivalence check (decomposition must not introduce new claims)
   - Provenance span preservation check
   - Frame-independent default enforcement
3. Deterministic fallback:
   - If LLM decomposition unavailable and claim is simple, wrap in single ATOMIC node
   - Otherwise route to INSUFFICIENT with policy_gap or decomposition_failure
4. Tests for malformed decomposition outputs.

Do not change existing synthesis engine behavior. Add decomposition as a pre-processing step.
```

### Prompt for Phase 3 (Policy, Normalizer, Cache)

```
You are implementing Phase 3 of the LSD Fact-Checking System v1.5.

Read these files:
- 01_DATA_MODELS.md (EvidencePolicy, EvidenceItem, CacheKey)
- 03_PIPELINE.md (normalizer rules, cache key spec, canonical JSON hashing)

Implement:
1. EvidencePolicy registry with default policies for all claim types.
2. Evidence Normalizer:
   - Source metadata normalization
   - VerdictScope extraction
   - ResolvedValue fields
   - Relevance/direction confidence threshold handling
   - Deterministic comparison for structured values
   - LLM direction gating
3. CacheKey v1.5 with full scope/entity/policy/decomposition versioning.
4. Canonical JSON serializer for authoritative hashing.
5. Unit tests:
   - Cache hit on exact key match
   - Cache miss on different scope
   - Cache miss on different entity IDs
   - Hash stability under reordered JSON keys
   - Normalizer rejects low-confidence decisive evidence
```

---

## 5. Summary of v1.5 Changes from v1.4

v1.5 keeps the v1.4 architecture but makes it implementation-safe.

Major changes:
- Replaces per-subclaim ClaimExpression with parent-level PremiseDecomposition.root_claim_expression
- Adds ResolvedValue for numeric, comparison, temporal, and quantifier claims
- Expands CacheKey to prevent reuse across changed scope, entities, operationalization, policy, decomposition version, or connector snapshots
- Clarifies that Frame context is not used in empirical fact checking unless policy-dependent
- Hardens LLM evidence-direction classification with decisive quote, confidence, relevance, tier, scope, and independence gates
- Moves HumanReviewRecord into early implementation
- Moves delta_D responsibility to scoring/dossier layer
- Defines empty and all-insufficient aggregation cases
- Adds canonical JSON hashing requirements
- Reorders roadmap so deterministic core and gold tests are built before live connectors
