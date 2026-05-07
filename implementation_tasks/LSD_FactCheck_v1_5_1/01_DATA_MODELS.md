# 01 — Data Models

This file defines all schemas, types, enums, and validation rules for the LSD fact-checking system.

---

## Table of Contents

1. ProvenanceSpan
2. VerdictScope
3. ResolvedValue
4. ClaimExpression
5. AtomicSubclaim
6. PremiseDecomposition
7. EvidencePolicy
8. EvidenceItem
9. SubclaimResult
10. FactCheckResult
11. SynthesisLogic
12. HumanReviewFlag & HumanReviewRecord
13. CacheKey
14. Validation Rules

---

## 1. ProvenanceSpan

Traceable text segment from the debate ledger.

```python
ProvenanceSpan:
  span_id: string
  post_id: string
  offsets: object          # {start: int, end: int}
  span_text: string
```

**Rule:** All scored premises MUST cite provenance spans. The fact-check result carries these spans forward for §7 traceability and §17 decisive premises/arguments list.

---

## 2. VerdictScope

Exact interpretation under which a verdict applies.

```python
VerdictScope:
  temporal_scope: string | null       # date, date range, event time
  geographic_scope: string | null    # country, region, jurisdiction
  population_scope: string | null   # affected population, demographic
  measurement_definition: string | null  # metric, unit, denominator
  source_basis: string | null        # source family used
  rounding_tolerance: string | null   # numeric tolerance accepted
```

---

## 3. ResolvedValue

Numeric, statistical, temporal, comparison, and quantifier claims need values, not just statuses.

```python
ResolvedValue:
  value: number | string | boolean | null
  unit: string | null
  value_type: enum {NUMBER, DATE, BOOLEAN, CATEGORY, TEXT, RANGE, UNKNOWN}
  lower_bound: number | null
  upper_bound: number | null
  measurement_definition: string | null
  source_basis: string | null
  verdict_scope: VerdictScope
  rounding_tolerance: string | null
```

**Use cases:**
- unemployment rate = 4.0%
- population = 38,000,000
- law enacted = true
- event date = 2023-09-14
- temperature range = [1.2, 1.5] °C

---

## 4. ClaimExpression

Recursive tree representing the logical form of a parent premise. Belongs to **PremiseDecomposition**, not to AtomicSubclaim.

```python
ClaimExpression:
  node_type: enum {ATOMIC, AND, OR, NOT, IF_THEN, COMPARISON, QUANTIFIER}
  children: list[ClaimExpression]
  subclaim_id: string | null
  operator: string | null
  quantifier: string | null
  quantifier_parameter: string | number | null
  comparison_target: string | null
```

**Validation rules:**
- ATOMIC must have `subclaim_id` and no children.
- AND/OR must have at least two children.
- NOT must have exactly one child.
- IF_THEN must have exactly two children: antecedent, consequent.
- COMPARISON must define `operator` and have comparable operands.
- QUANTIFIER must define `quantifier` and `quantifier_parameter` when needed.
- Max recursion depth: 3.
- Every ATOMIC node must reference an existing AtomicSubclaim.
- Every AtomicSubclaim should be reachable from the root ClaimExpression unless explicitly marked as `contextual_support_only`.

---

## 5. AtomicSubclaim

Leaf-level checkable claim. Does NOT contain its own ClaimExpression tree.

```python
AtomicSubclaim:
  subclaim_id: string
  parent_premise_id: string
  text: string
  claim_type: ClaimType
  secondary_claim_types: list[ClaimType]
  operationalization_hint: string
  verdict_scope_hint: VerdictScope
  provenance_spans: list[ProvenanceSpan]
  decomposition_rationale: string
```

---

## 6. PremiseDecomposition

Top-level output of the decomposer. Contains the root ClaimExpression and all atomic subclaims.

```python
PremiseDecomposition:
  premise_id: string
  snapshot_id: string
  original_text: string
  topic_id: string
  side: enum {FOR, AGAINST}
  root_claim_expression: ClaimExpression
  atomic_subclaims: list[AtomicSubclaim]
  provenance_spans: list[ProvenanceSpan]
  decomposition_model_metadata: ModelMetadata
  decomposition_prompt_hash: string
  validation_result: ValidationResult
```

**Critical rule:** `ClaimExpression` belongs to the parent premise, not to each AtomicSubclaim. The synthesis engine evaluates the root expression once.

---

## 7. EvidencePolicy

Governs acceptable source types per claim type.

```python
EvidencePolicy:
  policy_id: string
  claim_type: ClaimType
  required_source_types: list[SourceType]
  preferred_source_types: list[SourceType]
  minimum_acceptable_tier: int     # Tier N or stronger. Tier 1 and Tier 2 both satisfy minimum_acceptable_tier: 2.
  cross_verification_required: boolean
  cross_verification_minimum_sources: int
  temporal_constraint: {max_age_days: int, require_contemporary: boolean} | null
  verdict_scope_requirements: list[string]
  frame_dependent: boolean        # true only if policy scope depends on Frame
  special_rules: list[string]
```

**Default policies:**

| Claim Type | Min Tier | Cross-verification |
|------------|----------|-------------------|
| NUMERIC_STATISTICAL | 2 | false |
| LEGAL_REGULATORY | 1 | false |
| SCIENTIFIC | 2 | true (for causal/consensus) |
| GEOGRAPHIC_DEMOGRAPHIC | 2 | false |
| CURRENT_EVENT | 2 | true (min 2 independent sources) |
| CAUSAL | 2 | true |

---

## 8. EvidenceItem

Standardized evidence from any connector.

```python
EvidenceItem:
  evidence_id: UUID
  subclaim_id: string
  source_type: enum {OFFICIAL_STAT, GOV_DB, SCIENTIFIC_DB, LEGAL_DB, WIKIDATA, WIKIPEDIA, NEWS, WEB, OTHER}
  source_tier: int                # 1, 2, or 3
  retrieval_path: enum {DIRECT_CONNECTOR, WIKIDATA_REFERENCE, RAG_RETRIEVAL, LIVE_SEARCH_DISCOVERY, MANUAL_UPLOAD}
  source_url: string
  source_title: string
  source_date: ISO8601
  source_authority: string
  quote_or_span: string           # max 1000 chars
  quote_context: string
  verdict_scope: VerdictScope
  relevance_score: float [0,1]
  direction: enum {SUPPORTS, REFUTES, UNCLEAR, NEUTRAL}
  direction_confidence: float [0,1]
  direction_method: enum {DETERMINISTIC_STRUCTURED, LLM_CLASSIFIER, MANUAL}
  retrieval_timestamp: ISO8601
  connector_version: string
  connector_query_hash: string
  source_snapshot_id: string | null
  raw_response_hash: string

  # v1.5 additions
  claimed_value: ResolvedValue | null
  source_value: ResolvedValue | null
  deterministic_comparison_result: enum {MATCH, MISMATCH, NOT_COMPARABLE, NOT_RUN}
  decisive_quote_required: boolean
  decisive_quote_span: string | null
  source_independence_group_id: string | null
  llm_direction_allowed: boolean
  llm_direction_validation_result: ValidationResult | null
```

**Normalization rules:**
- Truncate quotes to 1000 chars max
- Standardize dates to ISO8601
- For structured sources: use deterministic comparison (claimed_value vs source_value)
- For text/RAG/web: LLM classifier with confidence threshold
- If `direction_confidence < 0.7` → `direction = UNCLEAR`
- Reject items with `relevance_score < 0.3`

**Web evidence archiving:**
- MUST store content hash (SHA-256 of normalized page text)
- MUST attempt archive.org permalink generation
- If archive.org fails, MUST store full page content in snapshot storage
- Required for artifact replay verification

---

## 9. SubclaimResult

Result of synthesizing one atomic subclaim.

```python
SubclaimResult:
  subclaim_id: string
  status: enum {SUPPORTED, REFUTED, INSUFFICIENT}
  p: float                         # exactly 1.0, 0.0, or 0.5
  confidence: float [0,1]
  best_evidence_tier: int | null
  limiting_evidence_tier: int | null
  decisive_evidence_tier: int | null
  citations: list[string]           # EvidenceItem.evidence_id values
  operationalization: string
  verdict_scope: VerdictScope
  insufficiency_reason: string | null
  human_review_flags: list[HumanReviewFlag]
  provenance_spans: list[ProvenanceSpan]
  synthesis_logic: SynthesisLogic
  synthesis_rule_engine_version: string
  resolved_value: ResolvedValue | null   # v1.5 addition
```

---

## 10. FactCheckResult

Final result for one premise after evaluating the ClaimExpression tree.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "FactCheckResult",
  "type": "object",
  "required": [
    "premise_id", "snapshot_id", "topic_id", "side",
    "status", "p", "confidence", "best_evidence_tier",
    "limiting_evidence_tier", "decisive_evidence_tier",
    "citations", "operationalization", "verdict_scope", "insufficiency_reason",
    "provenance_spans", "subclaim_results", "insufficiency_sensitivity",
    "audit_metadata"
  ],
  "properties": {
    "premise_id": {"type": "string"},
    "snapshot_id": {"type": "string"},
    "topic_id": {"type": "string"},
    "side": {"enum": ["FOR", "AGAINST"]},
    "status": {"enum": ["SUPPORTED", "REFUTED", "INSUFFICIENT"]},
    "p": {"type": "number", "enum": [0.0, 0.5, 1.0]},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "best_evidence_tier": {"type": ["integer", "null"], "minimum": 1, "maximum": 3},
    "limiting_evidence_tier": {"type": ["integer", "null"], "minimum": 1, "maximum": 3},
    "decisive_evidence_tier": {"type": ["integer", "null"], "minimum": 1, "maximum": 3},
    "citations": {"type": "array", "items": {"type": "string"}},
    "operationalization": {"type": "string"},
    "verdict_scope": {
      "type": "object",
      "properties": {
        "temporal_scope": {"type": ["string", "null"]},
        "geographic_scope": {"type": ["string", "null"]},
        "population_scope": {"type": ["string", "null"]},
        "measurement_definition": {"type": ["string", "null"]},
        "source_basis": {"type": ["string", "null"]},
        "rounding_tolerance": {"type": ["string", "null"]}
      }
    },
    "insufficiency_reason": {"type": ["string", "null"]},
    "human_review_flags": {"type": "array", "items": {"type": "string"}},
    "provenance_spans": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["span_id", "post_id"],
        "properties": {
          "span_id": {"type": "string"},
          "post_id": {"type": "string"},
          "offsets": {"type": "object"},
          "span_text": {"type": "string"}
        }
      }
    },
    "insufficiency_sensitivity": {"type": "object"},
    "decisive_premise_rank": {"type": ["integer", "null"]},
    "subclaim_results": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["subclaim_id", "text", "status", "p", "confidence"],
        "properties": {
          "subclaim_id": {"type": "string"},
          "text": {"type": "string"},
          "claim_type": {"type": "string"},
          "secondary_claim_types": {"type": "array", "items": {"type": "string"}},
          "status": {"enum": ["SUPPORTED", "REFUTED", "INSUFFICIENT"]},
          "p": {"type": "number", "enum": [0.0, 0.5, 1.0]},
          "confidence": {"type": "number"},
          "best_evidence_tier": {"type": ["integer", "null"]},
          "limiting_evidence_tier": {"type": ["integer", "null"]},
          "decisive_evidence_tier": {"type": ["integer", "null"]},
          "citations": {"type": "array", "items": {"type": "string"}},
          "verdict_scope": {"type": "object"},
          "insufficiency_reason": {"type": ["string", "null"]},
          "human_review_flags": {"type": "array", "items": {"type": "string"}},
          "provenance_spans": {"type": "array"},
          "synthesis_logic": {"type": "object"},
          "display_summary": {"type": "object"},
          "resolved_value": {"type": "object"}
        }
      }
    },
    "audit_metadata": {
      "type": "object",
      "required": ["audit_id", "timestamp", "merkle_root"],
      "properties": {
        "audit_id": {"type": "string"},
        "timestamp": {"type": "string", "format": "date-time"},
        "merkle_root": {"type": "string"},
        "decomposition_version": {"type": "string"},
        "evidence_policy_version": {"type": "string"},
        "synthesis_rule_engine_version": {"type": "string"},
        "connector_versions": {"type": "object"}
      }
    }
  }
}
```

---

## 11. SynthesisLogic

Structured, rule-generated proof trace. Authoritative rationale for the fact-check result.

```json
{
  "type": "object",
  "required": ["status_rule_applied", "policy_rule_id", "decisive_evidence", "claim_expression_node_type"],
  "properties": {
    "status_rule_applied": {"type": "string"},
    "policy_rule_id": {"type": "string"},
    "decisive_evidence": {"type": "array", "items": {"type": "string"}},
    "contradictory_evidence": {"type": "array", "items": {"type": "string"}},
    "subclaim_results": {"type": "array"},
    "verdict_scope_applied": {"type": "object"},
    "insufficiency_trigger": {"type": ["string", "null"]},
    "human_review_flags": {"type": "array", "items": {"type": "string"}},
    "authority_ranking_applied": {"type": "boolean"},
    "claim_expression_node_type": {
      "enum": ["ATOMIC", "AND", "OR", "NOT", "IF_THEN", "COMPARISON", "QUANTIFIER"]
    }
  }
}
```

---

## 12. HumanReviewFlag & HumanReviewRecord

### HumanReviewFlag enum

- NONE
- ENTITY_AMBIGUITY
- POLICY_GAP
- CONTRADICTORY_TIER1_EVIDENCE
- HIGH_IMPACT_INSUFFICIENT
- HIGH_IMPACT_LLM_DIRECTION
- CAUSAL_COMPLEXITY
- SCIENTIFIC_SCOPE_OVERCLAIM
- LLM_VALIDATION_FAILURE
- CONNECTOR_FAILURE
- TEMPORAL_SCOPE_AMBIGUITY
- SOURCE_CONFLICT
- SCOPE_MISMATCH

### HumanReviewRecord

Additive, immutable. Never modifies a published snapshot.

```python
HumanReviewRecord:
  review_id: string
  target_audit_id: string
  target_snapshot_id: string
  reviewer_role: string
  review_outcome: enum {REVIEWED_NO_CHANGE, REVIEWED_CORRECTION, REVIEWED_POLICY_GAP, REVIEWED_SOURCE_DISPUTE}
  review_note: string
  review_timestamp: ISO8601
  review_record_hash: string
```

**Rules:**
- Review records are additive and immutable.
- Human review does not silently mutate a published snapshot.
- Corrections require a new incident/correction snapshot.
- Current p remains unchanged unless a new snapshot is published.

---

## 13. CacheKey

Do not cache only by text. Cache must reflect scope, entities, policy, and decomposition.

```python
CacheKey:
  claim_hash: string
  normalized_subclaim_text: string
  claim_type: ClaimType
  resolved_entity_ids_hash: string
  verdict_scope_hash: string
  operationalization_hash: string
  decomposition_version: string
  evidence_policy_version: string
  connector_snapshot_versions_hash: string
  fact_mode: enum {OFFLINE, ONLINE_ALLOWLIST, PERFECT_CHECKER, LIVE_CONNECTORS}
  frame_dependency_key: null | FrameDependencyKey

FrameDependencyKey:
  frame_set_version: string
  frame_id: string
  frame_scope_hash: string
```

**Rules:**
- `frame_dependency_key` is null unless `EvidencePolicy.frame_dependent = true`.
- If Frame context changes decomposition or operationalization, the policy must be marked `frame_dependent`.
- Cached results are immutable and reusable only on exact key match.

---

## 14. Validation Rules

### ClaimExpression validation
- ATOMIC must have `subclaim_id` and no children.
- AND/OR must have at least two children.
- NOT must have exactly one child.
- IF_THEN must have exactly two children.
- COMPARISON must define `operator`.
- QUANTIFIER must define `quantifier`.
- Max recursion depth: 3.
- Every ATOMIC node must reference an existing AtomicSubclaim.

### Decomposition validation
- Reject decompositions that introduce new claims not in premise.
- Reject decompositions that change logical structure (ClaimExpression must be semantically equivalent to original premise).
- Reject `operationalization_hints` that conflict with `EvidencePolicy.verdict_scope_requirements` → flag POLICY_GAP.
- Cross-check `verdict_scope_hint` against `EvidencePolicy.verdict_scope_requirements`; reject mismatches → flag POLICY_GAP.
- All provenance spans from parent premise must be preserved in every AtomicSubclaim.

### EvidenceItem validation
- `relevance_score >= 0.3`
- `direction_confidence >= 0.7` for decisive evidence
- Web evidence MUST have archive permalink, content hash, or full content stored
- `raw_response_hash` is mandatory for all sources
