# 03 — Pipeline & Infrastructure

This file defines the high-level architecture, connector rules, normalizer, cache, audit, and scoring boundary.

---

## Table of Contents

1. High-Level Architecture
2. Entity / Concept Linking
3. Evidence Router
4. Evidence Normalizer
5. Cache & Identity
6. Audit & Immutable Storage
7. Scoring/Dossier Boundary
8. Aggregation Edge Cases

---

## 1. High-Level Architecture

Input from LSD Loop A and selection system:
- selected canonical empirical premise
- premise_id, topic_id, side, snapshot_id
- provenance_spans, selection metadata

**Pipeline steps:**

1. **Premise Decomposer**
   - Input: selected canonical empirical premise
   - Output: PremiseDecomposition (root_claim_expression + atomic_subclaims)

2. **Entity / Concept Linking**
   - Resolve entities to stable identifiers (Wikidata QIDs, DOIs, etc.)
   - Unresolved or ambiguous entities trigger INSUFFICIENT if required for verdict

3. **Claim Identity + Cache Lookup**
   - Compute expanded cache key (includes resolved_entity_ids_hash from step 2)
   - Reuse only exact matching immutable records

4. **Evidence Policy Resolver**
   - Choose policy by claim type, scope, source needs, optional frame dependency

5. **Evidence Router**
   - Route to mock connectors first, then real connectors in later phases
   - All connectors return EvidenceItems

6. **Evidence Normalizer**
   - Normalize source metadata, direction, scope, quotes, resolved values, hashes

7. **Policy-Gated Synthesis Engine**
   - Evaluate each atomic subclaim from EvidenceItems using hard-coded rules
   - Evaluate root ClaimExpression to produce premise-level FactCheckResult

8. **Audit + Immutable Storage**
   - Store frozen evidence, normalized records, synthesis logic, hashes, replay metadata

9. **Scoring/Dossier Integration**
   - Fact-check subsystem emits p/status and impact inputs
   - Scoring subsystem computes F_{t,s}, delta_D, decisive ranking

10. **Display Summary Generator**
    - Optional, non-authoritative
    - Generated only after authoritative result exists

---

## 2. Entity / Concept Linking

**Purpose:** Canonicalize entities to stable identifiers for cross-snapshot consistency.

**Output:** EntityLink objects:
- entity_id, mention_span, canonical_id, canonical_type, canonical_label
- linking_confidence [0,1], ambiguity_flag, ambiguity_candidates

**Wikidata integration:**
- Use Wikidata API (wbsearchentities) for candidates
- Use LLM disambiguation with context window
- Store QIDs for persons, organizations, locations, events, concepts
- Wikidata is NOT used for truth verification at this stage

**Unresolved entities:**
- If linking confidence < 0.7 or ambiguity_candidates > 1
- Flag as AMBIGUOUS in subclaim
- Route to INSUFFICIENT with reason "entity_resolution_failure"

---

## 3. Evidence Router

**Connectors:**

### Tier 1 Official / Primary
- Government statistics APIs (BLS, Census, Eurostat)
- Scientific databases (PubMed, arXiv, Crossref)
- Legal databases (court APIs, legislation APIs)
- Official organization APIs (UN, WHO, World Bank)

### Structured KB (Wikidata)
- SPARQL endpoint queries using linked QIDs/PIDs
- Used for: static factual anchors (dates, geography, demographics)
- NOT used for: causal claims, current events, policy evaluations, predictive claims
- Tier assignment:
  - No reference → Tier 3
  - Secondary/reputable reference → Tier 2
  - Primary/official reference → treat Wikidata as retrieval path, attribute to underlying source with retrieval_path = WIKIDATA_REFERENCE

### Tier 2 Curated RAG
- Vector database of Wikipedia, curated news archives, academic reviews
- Dense passage retrieval (DPR) + cross-encoder re-ranking
- Max 10 documents per subclaim
- Date filter: exclude sources older than policy temporal constraint

### Tier 3 Live Search
- Web search APIs (Brave, Bing, Google Custom Search)
- News APIs (NewsAPI, GDELT)
- Used for: source discovery, freshness checks
- **Tier 3 evidence CANNOT alone support SUPPORTED/REFUTED**

**Source Reputation Registry (Tier 3 Promotion):**
- Maintain allowlist of domains/publications qualifying as Tier 2
- Promotion requires: (a) registry match AND (b) independence verification AND (c) policy approval

**Source Independence Definition:**
Independent sources must not be:
- Syndicated copies of the same wire article
- Articles citing only the same original report
- Same publisher group without editorial independence
- Rewritten versions of the same press release
- Sources whose only basis is each other
- Bot-generated or content-farm variants

**Routing logic:**
1. Query all applicable connectors in parallel
2. Apply policy filters (source type, temporal constraints)
3. Collect EvidenceItems
4. If minimum acceptable tier not met → early INSUFFICIENT flag
5. If cross-verification required but insufficient independent sources → INSUFFICIENT

**Connector fallback chain:**
- Configurable per connector type in published fallback table
- Example: BLS API → Census API → Tier 2 RAG (statistical claims)
- Fallback triggers: HTTP error, timeout, schema mismatch, empty result set

---

## 4. Evidence Normalizer

Transforms heterogeneous connector outputs into standardized EvidenceItems.

**Key normalization rules:**
- Truncate quotes to 1000 chars max
- Standardize dates to ISO8601
- For structured sources: deterministic comparison (claimed_value vs source_value)
- For text/RAG/web: LLM classifier with confidence threshold
- If direction_confidence < 0.7 → direction = UNCLEAR
- Reject items with relevance_score < 0.3

**Web evidence archiving (hardened):**
- MUST store content hash (SHA-256 of normalized page text)
- MUST attempt archive.org permalink generation
- If archive.org fails, MUST store full page content in snapshot storage
- Required for artifact replay verification

---

## 5. Cache & Identity

**Normalization:**
- claim_hash = SHA256(lowercase(trimmed_text_with_standardized_numbers))
- Stopwords are NOT removed
- Standardized numbers: consistent formatting for commas, decimals, percentages, currency, common date formats

**CacheKey:**
```python
CacheKey:
  claim_hash: string
  normalized_subclaim_text: string
  claim_type: ClaimType
  resolved_entity_ids_hash: string      # from entity linking
  verdict_scope_hash: string
  operationalization_hash: string
  decomposition_version: string
  evidence_policy_version: string
  connector_snapshot_versions_hash: string
  fact_mode: enum {OFFLINE, ONLINE_ALLOWLIST, PERFECT_CHECKER, LIVE_CONNECTORS}
  frame_dependency_key: null | FrameDependencyKey
```

**Frame dependency rule:**
- `frame_dependency_key` is null unless `EvidencePolicy.frame_dependent = true`
- If Frame context changes decomposition or operationalization, policy must be marked frame_dependent
- Cached results immutable; reusable only on exact key match

**Invalidation authority:**
- AUTOMATED: connector health monitor detects API schema change
- GOVERNANCE: published rule change or incident declaration
- APPEAL: via appeal pathway
- All invalidations logged with timestamp, authority type, rationale

---

## 6. Audit & Immutable Storage

**AuditRecord:**
```python
AuditRecord:
  audit_id: UUID
  premise_id: string
  snapshot_id: string
  timestamp: ISO8601

  # Input provenance
  input_premise_text: string
  input_topic_id: string
  input_frame_id: string
  input_provenance_spans: list[ProvenanceSpan]

  # Processing provenance
  decomposition_version: string
  decomposition_prompt_hash: string
  linking_queries: list[{query, hash, response_hash}]
  evidence_policy_version: string
  connector_versions: dict[connector_name -> version]

  # Evidence provenance
  evidence_items: list[EvidenceItem]
  evidence_retrieval_manifest: list[{connector, query_hash, item_count}]

  # Synthesis provenance
  synthesis_rule_engine_version: string
  synthesis_logic: SynthesisLogic
  display_summary: DisplaySummary | null

  # Output
  result: SubclaimResult

  # Tamper evidence
  authoritative_result_hash: string     # SHA-256 of authoritative components only
  display_summary_hash: string | null    # separate hash for non-authoritative content
  previous_audit_hash: string
```

**Canonical JSON hashing rules:**
- UTF-8 encoding
- Sorted object keys
- Normalized Unicode (NFC)
- No insignificant whitespace
- Stable list ordering
- Stable float formatting (e.g., %.6f)
- Explicit nulls for nullable fields
- No timestamps inside hashes unless timestamp is part of authoritative record

**AuthoritativeResultHash includes:**
- Input premise id/text hash
- Root ClaimExpression
- Atomic subclaims
- Evidence policy version
- Normalized EvidenceItems used by synthesis
- SynthesisLogic
- FactCheckResult authoritative fields
- Connector/source snapshot IDs

**AuthoritativeResultHash excludes:**
- display_summary
- Free-form LLM explanation prose
- UI formatting
- Transient latency/debug logs

**Merkle tree:**
- Built ONLY over authoritative_result_hash values
- display_summary_hash is NOT included in public Merkle root
- full_audit_log_hash (optional internal) may include DisplaySummary for internal traceability

**Replay manifest:**
```python
ReplayManifest:
  manifest_id: string
  snapshot_id: string
  parameter_pack: {
    decomposition_prompt_template_version: string
    decomposition_model: string
    decomposition_temperature: float
    linking_api_versions: dict
    evidence_policy_version: string
    connector_versions: dict
    synthesis_rule_engine_version: string
    random_seeds: dict
  }
  input_hashes: dict[premise_id -> hash]
  authoritative_output_hashes: dict[premise_id -> authoritative_result_hash]
  merkle_root: string
```

**Replay modes:**
- **Artifact replay:** reconstructs published batch from frozen records and authoritative hashes. Authoritative mode.
- **Computational rerun:** re-executes connectors and model steps from manifest. Diagnostic only.

---

## 7. Scoring/Dossier Boundary

**Fact-check subsystem emits:**
- FactCheckResult
- status, p, confidence
- citations, verdict_scope, insufficiency_reason
- human_review_flags, evidence tier fields
- operationalization, provenance_spans

**Scoring/dossier subsystem computes:**
- F_{t,s} = mean(p) over selected empirical premises
- F_supported_only = mean(p) over SUPPORTED/REFUTED only
- insufficiency_rate = count(INSUFFICIENT) / count(total)
- D_{r,Frame} = Overall_FOR - Overall_AGAINST
- delta_D_true, delta_D_false
- max_abs_delta_D
- DecisivePremiseRanking

**Critical rule:** The fact-check core does not compute full debate D. It provides inputs; the scoring layer computes deltas.

---

## 8. Aggregation Edge Cases

**No selected empirical premises in a topic-side:**
- F_{t,s} = null
- Empirical component omitted from geometric mean
- insufficiency_rate = null
- F_supported_only = null

**All selected empirical premises are INSUFFICIENT:**
- F_{t,s} = 0.5
- F_supported_only = null
- insufficiency_rate = 1.0

**Mixed SUPPORTED/REFUTED/INSUFFICIENT:**
- F_{t,s} = mean(p) over all selected empirical premises
- F_supported_only = mean(p) over only SUPPORTED/REFUTED premises
- insufficiency_rate = count(INSUFFICIENT) / count(total)

**No SUPPORTED/REFUTED premises:**
- F_supported_only = null (not 0.5)
