# LSD Fact-Checking System v1.5 — OBJECTIVE

**Package:** `skills.fact_checking`
**Target version:** v1.5
**Created:** 2026-05-03
**Phase:** 6–7 Complete — v1.5 Production Integration

---

## Scope

This package implements the empirical fact-checking subsystem for the Loop B adjudication engine. It feeds the empirical factuality component `F_{t,s}` into the larger debate scoring system. It does **not** decide the whole debate.

### Requirement Target (LSD v1.2 Contract)

- **status** ∈ {SUPPORTED, REFUTED, INSUFFICIENT}
- **p** ∈ {1.0, 0.0, 0.5}
- SUPPORTED = sufficient evidence under declared evidence policy
- REFUTED = sufficient evidence refutes under declared evidence policy
- INSUFFICIENT = unavailable, undecidable, ambiguous, scope-narrow, policy-invalid, or connector/entity failure
- Outputs include citations or explicit insufficiency reason
- Outputs include operationalization (what would confirm/refute)
- Outputs include evidence tier information
- Aggregate outputs include tier counts, insufficiency_rate, F_supported_only, and sensitivity to assuming insufficient claims true/false

### Implementation Principles

1. **Rule outputs are authoritative** — LLMs may produce structured candidates, but must not directly produce the final verdict.
2. **Artifact replay is authoritative** — Reconstructs exact published result from frozen records deterministically.
3. **Empirical fact checks are Frame-independent by default** — Frame information may be used only when policy explicitly declares `frame_dependent = true`.
4. **LLMs are allowed only behind validation gates** — Every LLM output must be validated; failure routes to INSUFFICIENT or human review.
5. **Build deterministic core before live connectors** — First working version uses mock evidence fixtures only.

---

## Current State

The package already contains a working v1 implementation with the following modules:

| File | Status | Notes |
|------|--------|-------|
| `__init__.py` | ✅ existing | Exports v1 API surface |
| `skill.py` | ✅ existing | `FactCheckingSkill` class (main entry point) |
| `models.py` | ✅ existing | v1 data models (`FactCheckResult`, `EvidenceRecord`, etc.) |
| `config.py` | ✅ existing | `FactCheckConfig` |
| `connectors.py` | ✅ existing | `SourceConnector`, `GroundTruthDB`, `SimulatedSourceConnector` |
| `decomposer.py` | ✅ existing | `ClaimDecomposer` (rule-based, v1 contract) |
| `planner.py` | ✅ existing | `ConnectorPlanner` (connector routing) |
| `policy.py` | ✅ existing | `EvidencePolicy`, `apply_policy` (singular filename) |
| `cache.py` | ✅ existing | `MultiLayerCache`, `MemoryCache`, `SQLiteCache` |
| `audit.py` | ✅ existing | `AuditLogger`, `AuditLogEntry` |
| `normalization.py` | ✅ existing | `ClaimNormalizer` (singular filename) |
| `pii.py` | ✅ existing | `PIIDetector` |
| `fc_queue.py` | ✅ existing | `FactCheckQueue` (async job queue) |
| `rate_limiter.py` | ✅ existing | Rate limiting utilities |
| `sources.py` | ✅ existing | Source management |
| `template_adapters.py` | ✅ existing | `ClaimTypeDetector`, etc. |
| `web_rag_connector.py` | ✅ existing | `WebRAGConnector` |
| `wikidata_connector.py` | ✅ existing | `WikidataConnector` |
| `testdata/` | ✅ existing | Mock evidence fixtures (`fact_check_gold_v1.jsonl`) |

**Tests:**
- `tests/unit/test_fact_check_skill.py` — 26 passing behavioral tests
- `fact_check_gold_tests/tests/test_fact_check_gold_corpus.py` — Gold corpus regression tests
- `fact_check_gold_tests/tests/gold_fact_check_cases.py` — Gold case definitions

**DebateEngine integration:**
- `backend/debate_engine_v2.py` — Uses `V15FactCheckingSkill` by default (feature flag `FACT_CHECKER_VERSION=v1.5`).
  Falls back to legacy `FactCheckingSkill` when `FACT_CHECKER_VERSION=v1`.
- `backend/extraction.py` — Extracts facts and routes empirical claims through the active fact checker.
- `backend/scoring_engine.py` — Consumes v1.5 outputs with proper null edge cases per §8.
- `backend/fact_checker.py` — Legacy `FactChecker` class (older, simpler implementation)

---

## Target Package Structure (v1.5)

Per `04_ROADMAP.md` §1, the v1.5 package will contain:

```
skills/fact_checking/
  __init__.py              ✅ existing
  models.py                ✅ existing — will be expanded for v1.5 schemas
  claim_expression.py      🆕 ClaimExpression evaluator (ATOMIC, AND, OR, NOT, IF_THEN, COMPARISON, QUANTIFIER)
  decomposition.py         🆕 Decomposer interface + PremiseDecomposition validation
  policies.py              🆕 EvidencePolicy registry (plural filename; distinct from v1 policy.py)
  connectors.py            ✅ existing — will be extended with mock fixture fixtures
  normalizer.py            🆕 EvidenceItem normalizer (distinct from v1 normalization.py)
  synthesis.py             🆕 SynthesisEngine with hard-coded rules A–J
  cache.py                 ✅ existing — will be hardened for CacheKey v1.5
  audit.py                 ✅ existing — will be hardened for canonical hashing
  human_review.py          🆕 HumanReviewFlag + HumanReviewRecord
  scoring_inputs.py        🆕 Adapter for scoring/dossier layer (F_{t,s}, F_supported_only, insufficiency_rate)
  display_summary.py       🆕 Non-authoritative summary generator
  fixtures/                ✅ existing (testdata/) — mock evidence for testing
  tests/                   🆕 Gold tests + unit tests co-located in package
```

### v1.5 Production Bridge Skill

`v15_skill.py` exposes the same interface as `FactCheckingSkill` while internally orchestrating the v1.5 pipeline:

```python
class V15FactCheckingSkill:
    def __init__(self, mode="OFFLINE", allowlist_version="v1", ...)
    def check_fact(self, claim_text, ...) -> FactCheckResult  # backward-compatible
    def check_fact_async(self, claim_text, ...) -> FactCheckJob
    def get_job_result(self, job_id) -> Optional[FactCheckResult]
    def get_job_status(self, job_id) -> Optional[str]
    def get_cache_stats(self) -> Dict[str, Any]
    def get_audit_stats(self) -> Dict[str, Any]
    def get_queue_stats(self) -> Dict[str, Any]
    def shutdown(self) -> None
```

Result mapping:
- v1.5 `p` ∈ {1.0, 0.0, 0.5} → legacy `factuality_score`
- v1.5 `status` ∈ {SUPPORTED, REFUTED, INSUFFICIENT} → legacy `verdict` + `status`
- v1.5 `best_evidence_tier` → legacy `evidence_tier_counts`
- v1.5 `synthesis_logic`, `human_review_flags`, `insufficiency_reason` → `diagnostics`

---

## Current FactCheckingSkill API Shape

```python
class FactCheckingSkill:
    def __init__(
        self,
        mode: str = "OFFLINE",
        allowlist_version: str = "v1",
        config: Optional[FactCheckConfig] = None,
        source_registry: Optional[Any] = None,
        enable_async: bool = True,
        async_worker_count: int = 3,
        connectors: Optional[List[SourceConnector]] = None,
        ground_truth_db: Optional[GroundTruthDB] = None,
        cache_ttl_seconds: Optional[int] = None,
        policy: Optional[EvidencePolicy] = None,
    )

    def check_fact(
        self,
        claim_text: str,
        temporal_context: Optional[TemporalContext] = None,
        request_context: Optional[RequestContext] = None,
        wait_for_async: bool = False,
    ) -> FactCheckResult

    def check_fact_async(
        self,
        claim_text: str,
        temporal_context: Optional[TemporalContext] = None,
        request_context: Optional[RequestContext] = None,
    ) -> FactCheckJob

    def get_job_result(self, job_id: str) -> Optional[FactCheckResult]
    def get_job_status(self, job_id: str) -> Optional[str]
    def invalidate_cache(self, claim_hash: str, reason: str) -> None
    def get_cache_stats(self) -> Dict[str, Any]
    def get_audit_stats(self) -> Dict[str, Any]
    def get_queue_stats(self) -> Optional[Dict[str, Any]]
    def shutdown(self) -> None
```

**Key return type:** `FactCheckResult`
- `claim_text`, `normalized_claim_text`, `claim_hash`
- `fact_mode`, `allowlist_version`
- `status` ∈ {UNVERIFIED_OFFLINE, CHECKED, NO_ALLOWLIST_EVIDENCE, ERROR_RECOVERED, PENDING, STALE}
- `verdict` ∈ {SUPPORTED, REFUTED, INSUFFICIENT, UNVERIFIED}
- `factuality_score` ∈ [0, 1] (v1 uses continuous; v1.5 will restrict to {1.0, 0.0, 0.5})
- `confidence`, `confidence_explanation`, `operationalization`
- `evidence: List[EvidenceRecord]`
- `evidence_tier_counts: Dict[str, int]`
- `diagnostics: Dict[str, Any]`

---

## Integration Definition of Done

- [x] `V15FactCheckingSkill` created with backward-compatible legacy API
- [x] v1.5 deterministic ternary pipeline wired into `DebateEngineV2`
- [x] Feature flag `FACT_CHECKER_VERSION` (v1 / v1.5) controls pipeline selection
- [x] `ScoringEngine` handles null edge cases per v1.5 §8
- [x] `SnapshotDiff` handles None factuality values
- [x] Database schema extended with v1.5 columns
- [x] Formula registry documents deterministic ternary contract
- [x] All 199 v1.5 unit tests pass
- [x] All 104 backend unit+integration tests pass
- [x] Legacy `FactCheckingSkill` remains fully functional

---

## Roadmap Preview

| Phase | Goal | Key Deliverables |
|-------|------|------------------|
| 0 | Repository Alignment | This document + empty module scaffold |
| 1 | Deterministic Core with Mock Evidence | Data models, ClaimExpression, SynthesisEngine, mock connector, gold tests |
| 2 | Decomposition and Validation Layer | LLM-assisted decomposition with deterministic validation |
| 3 | Policy, Normalizer, Cache Hardening | EvidencePolicy registry, normalizer, CacheKey v1.5, canonical hashing |
| 4 | Real Connector Layer | Wikidata, statistics, scientific, curated, search connectors |
| 5 | Audit, Replay, Immutable Storage | AuditRecord, authoritative_result_hash, ReplayManifest |
| 6 | Scoring/Dossier Integration | F_{t,s}, F_supported_only, insufficiency_rate, tier counts |
| 7 | Display Summaries and Human Review UI | DisplaySummary generator, consistency checker, review queue |
