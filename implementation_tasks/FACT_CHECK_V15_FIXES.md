# LSD Fact-Checking System v1.5 — Comprehensive Fix Instructions

**Generated:** 2026-05-03
**Scope:** All bugs, gaps, and integration issues identified in the v1.5 implementation audit.
**Estimated effort:** 2–3 weeks for P0+P1 items; 1–2 additional weeks for P2+P3.

---

## Table of Contents

1. [P0 Critical Fixes](#p0-critical-fixes)
   1.1 [Fix Merkle Tree Sibling Ordering](#p0-1-fix-merkle-tree)
   1.2 [Fix Authoritative Hash Incompleteness](#p0-2-fix-authoritative-hash)
   1.3 [Build v1.5 → v1 Adapter in skill.py](#p0-3-build-adapter)
   1.4 [Populate insufficiency_sensitivity](#p0-4-populate-insufficiency-sensitivity)
2. [P1 High-Priority Fixes](#p1-high-priority-fixes)
   2.1 [Fix Evidence Filtering (Keep Low-Confidence as UNCLEAR)](#p1-1-fix-evidence-filtering)
   2.2 [Fix Compound best_evidence_tier Bug](#p1-2-fix-compound-tier)
   2.3 [Implement operationalization on FactCheckResult](#p1-3-implement-operationalization)
   2.4 [Add Persistent HumanReviewRecord Storage](#p1-4-add-review-storage)
   2.5 [Expand Gold Test Coverage (14 Missing Tests)](#p1-5-expand-gold-tests)
   2.6 [Implement HIGH_IMPACT_LLM_DIRECTION Flag](#p1-6-implement-high-impact-flag)
   2.7 [Fix Scoring Engine REFUTED Semantics](#p1-7-fix-scoring-semantics)
3. [P2 Medium-Priority Fixes](#p2-medium-priority-fixes)
   3.1 [Fix Float Formatting in Canonical JSON](#p2-1-fix-float-formatting)
   3.2 [Implement Entity/Concept Linking](#p2-2-implement-entity-linking)
   3.3 [Implement QUANTIFIER Evaluation](#p2-3-implement-quantifier)
   3.4 [Implement Web Evidence Archiving](#p2-4-implement-web-archiving)
   3.5 [Implement Source Reputation Registry](#p2-5-implement-source-registry)
   3.6 [Implement Connector Fallback Chains](#p2-6-implement-fallback-chains)
   3.7 [Implement Computational Rerun Mode](#p2-7-implement-computational-rerun)
   3.8 [Fix BLS Connector Direction](#p2-8-fix-bls-direction)
   3.9 [Fix CuratedRAG DirectionMethod Label](#p2-9-fix-rag-label)
4. [P3 Lower-Priority Improvements](#p3-lower-priority-improvements)
   4.1 [Implement Drop-Component Sensitivity](#p3-1-drop-component)
   4.2 [Implement Frame Sensitivity Computation](#p3-2-frame-sensitivity)
   4.3 [Implement Normative Claim Routing](#p3-3-normative-routing)
   4.4 [Update Database Schema for v1.5](#p3-4-database-schema)
   4.5 [Add Frontend Fact-Check Detail Panels](#p3-5-frontend-panels)
5. [Integration Instructions](#integration-instructions)
   5.1 [Wire v1.5 into DebateEngineV2](#integration-debate-engine)
   5.2 [Update Extraction Layer](#integration-extraction)
   5.3 [Migration Path: Adapter → Native](#integration-migration)
6. [Testing Strategy](#testing-strategy)
7. [Verification Checklist](#verification-checklist)

---

## P0 Critical Fixes

### P0.1 Fix Merkle Tree Sibling Ordering

**File:** `skills/fact_checking/v15_audit.py`
**Bug:** `_hash_pair` sorts the two hash strings before concatenating. Standard Merkle trees concatenate in tree order (`left || right`). Sorting produces Merkle roots that are incompatible with standard verification tools.
**Impact:** Tamper-evident hashes cannot be verified by external tools.

**Current code (approx line in `_hash_pair`):**
```python
def _hash_pair(left: str, right: str) -> str:
    combined = "".join(sorted([left, right]))
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
```

**Fix:**
```python
def _hash_pair(left: str, right: str) -> str:
    combined = left + right
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
```

**Test update:** In `test_phase5.py`, update `test_merkle_tree_deterministic` and any test that hard-codes an expected Merkle root hash. The root will change after this fix.

**After fixing, verify:**
```bash
python -m pytest skills/fact_checking/tests/test_phase5.py -v -k merkle
```

---

### P0.2 Fix Authoritative Hash Incompleteness

**File:** `skills/fact_checking/v15_audit.py`
**Bug:** `compute_authoritative_result_hash` takes `root_claim_expression`, `atomic_subclaims`, and `evidence_items` as **optional** parameters. When `decompose_synthesize_and_audit` (in `decomposition.py`) calls it, it omits these parameters, producing an incomplete hash. Replay verification will fail because the hash doesn't cover the claim expression or evidence.

**Current signature:**
```python
def compute_authoritative_result_hash(
    premise_id: str,
    premise_text: str,
    status: str,
    p: float,
    subclaim_results: List[SubclaimResult],
    root_claim_expression: Optional[ClaimExpression] = None,
    atomic_subclaims: Optional[List[AtomicSubclaim]] = None,
    evidence_items: Optional[List[EvidenceItem]] = None,
    ...
) -> str:
```

**Fix:** Make the three parameters **required**:
```python
def compute_authoritative_result_hash(
    premise_id: str,
    premise_text: str,
    status: str,
    p: float,
    subclaim_results: List[SubclaimResult],
    root_claim_expression: ClaimExpression,
    atomic_subclaims: List[AtomicSubclaim],
    evidence_items: List[EvidenceItem],
    ...
) -> str:
```

Then update `build_audit_record` and `decompose_synthesize_and_audit` to pass these values through.

**In `decomposition.py`, `decompose_synthesize_and_audit`:**
After calling `decompose_and_synthesize`, pass `decomposition.root_claim_expression`, `decomposition.atomic_subclaims`, and `evidence_items` to `build_audit_record`.

**Test update:** In `test_phase5.py`, `test_hash_chain_detects_tampering` should verify that modifying `root_claim_expression` or `evidence_items` changes the hash.

---

### P0.3 Build v1.5 → v1 Adapter in skill.py

**File:** `skills/fact_checking/skill.py`
**Problem:** The v1.5 pipeline exists but is not called from `skill.py`. `check_fact()` still routes through legacy v1 code (`_check_perfect`, `_check_offline`). The debate engine and extraction layer expect v1 `FactCheckResult` shapes.

**Strategy:** Add a v1.5 execution path inside `skill.py` and a converter to v1 format. Keep the public API (`check_fact`, `check_fact_async`) unchanged.

**Step 1 — Add imports at top of `skill.py`:**
```python
from .decomposition import CanonicalPremise, Decomposer, decompose_and_synthesize
from .synthesis import SynthesisEngine
from .v15_connectors import ConnectorRegistry, BaseEvidenceConnector
from .v15_models import (
    Side,
    ClaimType,
    FactMode,
    EvidenceItem,
    ProvenanceSpan as V15ProvenanceSpan,
)
```

**Step 2 — Update `__init__`:**
Replace the v1-only initialization with v1.5:
```python
def __init__(
    self,
    mode: str = "OFFLINE",
    allowlist_version: str = "v1",
    config: Optional[FactCheckConfig] = None,
    source_registry: Optional[Any] = None,
    enable_async: bool = True,
    async_worker_count: int = 3,
    v15_connectors: Optional[List[BaseEvidenceConnector]] = None,
    cache_ttl_seconds: Optional[int] = None,
):
    del source_registry

    mode_aliases = { ... }  # keep existing
    self.mode = mode_aliases.get(str(mode).lower(), mode)
    self.allowlist_version = allowlist_version
    self.config = config or get_config()

    ttl = cache_ttl_seconds or self.config.cache_ttl_seconds
    self._cache = MultiLayerCache(ttl_seconds=ttl)
    self._audit = AuditLogger()

    # v1.5 components
    self._v15_connectors = v15_connectors or ConnectorRegistry.offline_connectors()
    self._decomposer = Decomposer()
    self._synthesis_engine = SynthesisEngine()

    self._cache_runtime_signature = self._build_runtime_signature()
    # Remove _evidence_retriever — not needed for v1.5

    self._async_enabled = enable_async and self.mode == "ONLINE_ALLOWLIST"
    self._queue: Optional[FactCheckQueue] = None
    if self._async_enabled:
        self._queue = FactCheckQueue(
            max_size=self.config.async_queue_max_size,
            label=f"{self.mode.lower()}-{id(self) & 0xffff:x}",
        )
        self._queue.set_processor(self._process_job)
        self._queue.start_workers(async_worker_count)
```

**Step 3 — Implement `_check_v15`:**
```python
def _check_v15(
    self,
    claim_text: str,
    normalized: str,
    claim_hash: str,
    contains_pii: bool,
    temporal_context: Optional[TemporalContext],
    request_context: Optional[RequestContext] = None,
    claim_truncated: bool = False,
) -> FactCheckResult:
    """Run the v1.5 fact-check pipeline and convert result to v1 format."""
    from .v15_models import FactCheckResult as V15FactCheckResult

    request_context = request_context or RequestContext()

    # Build CanonicalPremise from v1 inputs
    premise = CanonicalPremise(
        premise_id=request_context.point_id or claim_hash,
        snapshot_id=request_context.post_id or "",
        original_text=claim_text,
        topic_id="",
        side=Side.FOR,
        provenance_spans=[],
        claim_type=ClaimType.EMPIRICAL_ATOMIC,
    )

    # Decompose
    decomposition = self._decomposer.decompose(premise)

    # Gather evidence
    evidence_items: List[EvidenceItem] = []
    connector_errors: List[str] = []
    if decomposition.validation_result.valid:
        for subclaim in decomposition.atomic_subclaims:
            for connector in self._v15_connectors:
                try:
                    items = connector.retrieve(subclaim)
                    evidence_items.extend(items)
                except Exception as exc:
                    error_msg = f"Connector {connector.connector_id} failed: {exc}"
                    connector_errors.append(error_msg)

    # Synthesize
    result_v15 = self._synthesis_engine.synthesize(
        decomposition,
        evidence_items,
        connector_failure_subclaim_ids=set(),  # TODO: track which subclaims had connector failures
    )

    # Convert to v1 format
    return self._v15_to_v1_result(
        result_v15,
        claim_text=claim_text,
        normalized=normalized,
        claim_hash=claim_hash,
        contains_pii=contains_pii,
        temporal_context=temporal_context,
        claim_truncated=claim_truncated,
        connector_errors=connector_errors,
    )
```

**Step 4 — Implement `_v15_to_v1_result` converter:**
```python
def _v15_to_v1_result(
    self,
    v15: "V15FactCheckResult",
    claim_text: str,
    normalized: str,
    claim_hash: str,
    contains_pii: bool,
    temporal_context: Optional[TemporalContext],
    claim_truncated: bool = False,
    connector_errors: Optional[List[str]] = None,
) -> FactCheckResult:
    """Convert a v1.5 FactCheckResult to the legacy v1 FactCheckResult shape."""
    from .models import (
        FactCheckResult as V1FactCheckResult,
        FactCheckStatus,
        FactCheckVerdict,
        EvidenceRecord,
        EvidenceTier,
        CacheResult,
    )

    # Map v1.5 status string to v1 verdict enum
    status_map = {
        "SUPPORTED": FactCheckVerdict.SUPPORTED,
        "REFUTED": FactCheckVerdict.REFUTED,
        "INSUFFICIENT": FactCheckVerdict.INSUFFICIENT,
    }
    verdict = status_map.get(v15.status, FactCheckVerdict.INSUFFICIENT)
    status = FactCheckStatus.CHECKED if v15.status != "INSUFFICIENT" else FactCheckStatus.CHECKED

    # Map v1.5 p to v1 factuality_score
    factuality_score = v15.p

    # Build evidence_tier_counts from subclaim_results
    tier_counts: Dict[str, int] = {"TIER_1": 0, "TIER_2": 0, "TIER_3": 0}
    for sr in v15.subclaim_results:
        tier = sr.best_evidence_tier
        if tier == 1:
            tier_counts["TIER_1"] += 1
        elif tier == 2:
            tier_counts["TIER_2"] += 1
        elif tier == 3:
            tier_counts["TIER_3"] += 1

    # Build evidence list from subclaim_results citations
    evidence: List[EvidenceRecord] = []
    for sr in v15.subclaim_results:
        for citation in sr.citations:
            evidence.append(
                EvidenceRecord(
                    source_url="",
                    source_id=citation,
                    source_version="v1.5",
                    source_title="",
                    snippet="",
                    content_hash="",
                    retrieved_at=None,
                    relevance_score=1.0,
                    support_score=1.0 if sr.status == "SUPPORTED" else 0.0,
                    contradiction_score=1.0 if sr.status == "REFUTED" else 0.0,
                    selected_rank=1,
                    evidence_tier=EvidenceTier.TIER_1 if sr.best_evidence_tier == 1
                        else EvidenceTier.TIER_2 if sr.best_evidence_tier == 2
                        else EvidenceTier.TIER_3,
                )
            )

    # Build diagnostics from v1.5 richness
    diagnostics: Dict[str, Any] = {
        "reason_code": v15.insufficiency_reason or "v1.5_synthesis",
        "claim_truncated": claim_truncated,
        "subclaim_results": [
            {
                "subclaim_id": sr.subclaim_id,
                "status": sr.status,
                "p": sr.p,
                "best_evidence_tier": sr.best_evidence_tier,
                "insufficiency_reason": sr.insufficiency_reason,
                "human_review_flags": [f.value for f in sr.human_review_flags],
            }
            for sr in v15.subclaim_results
        ],
        "human_review_flags": [f.value for f in v15.human_review_flags],
        "insufficiency_reason": v15.insufficiency_reason,
        "synthesis_rule_engine_version": v15.audit_metadata.get("synthesis_rule_engine_version", "v1.5"),
    }
    if connector_errors:
        diagnostics["connector_errors"] = connector_errors

    # Operationalization: prefer synthesis-generated, fall back to original text
    operationalization = v15.operationalization or "See subclaim breakdown in diagnostics."

    return V1FactCheckResult(
        claim_text=claim_text,
        normalized_claim_text=normalized,
        claim_hash=claim_hash,
        fact_mode=self.mode,
        allowlist_version=self.allowlist_version,
        status=status,
        verdict=verdict,
        factuality_score=factuality_score,
        confidence=v15.confidence,
        confidence_explanation=v15.insufficiency_reason or f"v1.5 synthesis: {v15.status}",
        operationalization=operationalization,
        evidence=evidence,
        evidence_tier_counts=tier_counts,
        algorithm_version="fc-v1.5",
        processing_duration_ms=0,  # TODO: measure duration
        cache_result=CacheResult.MISS,
        contains_pii=contains_pii,
        temporal_context=temporal_context,
        diagnostics=diagnostics,
    )
```

**Step 5 — Update `check_fact` dispatch:**
Replace the mode-based dispatch with a single v1.5 call:
```python
def check_fact(self, claim_text, temporal_context=None, request_context=None, wait_for_async=False):
    start_time = time.time()
    request_context = request_context or RequestContext()

    # Truncation, normalization, PII (keep existing)
    claim_truncated = False
    if len(claim_text) > self.config.max_claim_length:
        claim_text = claim_text[:self.config.max_claim_length]
        claim_truncated = True

    normalized = ClaimNormalizer.normalize(claim_text)
    claim_hash = ClaimNormalizer.compute_hash(normalized)
    contains_pii = PIIDetector.detect(claim_text).contains_pii
    cache_key = self._build_cache_key(claim_hash)

    # Cache check (keep existing)
    cached_result, cache_layer = self._cache.get(cache_key)
    if cached_result:
        cached_result.cache_result = cache_layer
        return cached_result

    # Async handling (keep existing logic)
    if self._async_enabled and self._queue:
        pending_job = self._queue.get_pending_result(claim_hash, self.mode, self.allowlist_version)
        if pending_job:
            return FactCheckResult(
                claim_text=claim_text,
                normalized_claim_text=normalized,
                claim_hash=claim_hash,
                fact_mode=self.mode,
                allowlist_version=self.allowlist_version,
                status=FactCheckStatus.PENDING,
                verdict=FactCheckVerdict.UNVERIFIED,
                factuality_score=0.5,
                confidence=0.0,
                confidence_explanation=f"Fact check in progress (job: {pending_job.job_id})",
                algorithm_version=self.config.algorithm_version,
                processing_duration_ms=0,
                cache_result=CacheResult.MISS,
                contains_pii=contains_pii,
                temporal_context=temporal_context,
                diagnostics={"reason_code": "pending_async_job"},
            )

    # === NEW: Always use v1.5 path ===
    result = self._check_v15(
        claim_text,
        normalized,
        claim_hash,
        contains_pii,
        temporal_context,
        request_context,
        claim_truncated=claim_truncated,
    )

    if result.status != FactCheckStatus.PENDING:
        self._cache.set(cache_key, result)
        self._audit.log_check(
            result=result,
            request_context=request_context,
            evidence_candidates_count=len(result.evidence),
        )

    return result
```

**Step 6 — Update `_process_job`:**
```python
def _process_job(self, job: FactCheckJob) -> FactCheckResult:
    cache_key = self._build_cache_key(job.claim_hash, fact_mode=job.fact_mode)
    cached, _ = self._cache.get(cache_key)
    if cached:
        return cached

    result = self._check_v15(
        job.claim_text,
        job.normalized_claim,
        job.claim_hash,
        job.contains_pii,
        job.temporal_context,
        job.request_context,
    )

    self._cache.set(cache_key, result)
    self._audit.log_check(
        result=result,
        request_context=job.request_context,
        evidence_candidates_count=len(result.evidence),
    )
    return result
```

**Step 7 — Remove dead v1 code (after tests pass):**
- `_check_offline`, `_check_perfect`, `_check_online_allowlist`, `_perfect_check`
- `_adjudicate`, `_build_verdict`, `_build_insufficient`, `_finalize_result`
- `_query_connectors`, `_evidence_to_source_results`, `_to_evidence_records`
- `_check_perfect_checker_fixture`, `_build_result_from_ground_truth`
- `_generate_operationalization` (v1 version)
- `_EvidenceRetrieverProxy`

---

### P0.4 Populate insufficiency_sensitivity

**Files:** `skills/fact_checking/scoring_inputs.py`, `skills/fact_checking/synthesis.py`
**Problem:** The LSD spec §13.1 requires publishing: *"If INSUFFICIENT assumed true/false, D changes by …"*. The `FactCheckResult.insufficiency_sensitivity` field exists but is **never populated**.

**What to compute:**
For a set of fact-check results, compute how the overall score D changes if all INSUFFICIENT premises were assumed true (p=1.0) vs. assumed false (p=0.0).

**Step 1 — Add function in `scoring_inputs.py`:**
```python
def compute_insufficiency_sensitivity(
    results: List[FactCheckResult],
) -> Dict[str, float]:
    """
    Compute how F_ts changes if all INSUFFICIENT premises were
    assumed true (p=1.0) or assumed false (p=0.0).

    Returns {"delta_true": float, "delta_false": float, "max_abs_delta": float}
    """
    insufficient_results = [r for r in results if r.status == "INSUFFICIENT"]
    if not insufficient_results:
        return {"delta_true": 0.0, "delta_false": 0.0, "max_abs_delta": 0.0}

    # Current F_ts
    current = _compute_topic_side_score("", Side.FOR, results).F_ts or 0.5

    # Assume all insufficient → true (p=1.0)
    true_assumed = []
    for r in results:
        if r.status == "INSUFFICIENT":
            # Create a copy with p=1.0
            copy = FactCheckResult(
                premise_id=r.premise_id,
                snapshot_id=r.snapshot_id,
                topic_id=r.topic_id,
                side=r.side,
                status="SUPPORTED",
                p=1.0,
                confidence=r.confidence,
                best_evidence_tier=r.best_evidence_tier,
            )
            true_assumed.append(copy)
        else:
            true_assumed.append(r)

    f_true = _compute_topic_side_score("", Side.FOR, true_assumed).F_ts or current

    # Assume all insufficient → false (p=0.0)
    false_assumed = []
    for r in results:
        if r.status == "INSUFFICIENT":
            copy = FactCheckResult(
                premise_id=r.premise_id,
                snapshot_id=r.snapshot_id,
                topic_id=r.topic_id,
                side=r.side,
                status="REFUTED",
                p=0.0,
                confidence=r.confidence,
                best_evidence_tier=r.best_evidence_tier,
            )
            false_assumed.append(copy)
        else:
            false_assumed.append(r)

    f_false = _compute_topic_side_score("", Side.FOR, false_assumed).F_ts or current

    delta_true = f_true - current
    delta_false = f_false - current
    max_abs_delta = max(abs(delta_true), abs(delta_false))

    return {
        "delta_true": delta_true,
        "delta_false": delta_false,
        "max_abs_delta": max_abs_delta,
    }
```

**Step 2 — Populate in `_build_fact_check_result` (`synthesis.py`):**
```python
def _build_fact_check_result(...):
    # After building the result, compute sensitivity if there are insufficient subclaims
    insufficiency_sensitivity = {}
    if any(r.status == "INSUFFICIENT" for r in atomic_results):
        from .scoring_inputs import compute_insufficiency_sensitivity
        # Wrap subclaim_results as mini FactCheckResults for sensitivity computation
        # OR refactor compute_insufficiency_sensitivity to work on SubclaimResults
        ...

    return FactCheckResult(
        ...
        insufficiency_sensitivity=insufficiency_sensitivity,
    )
```

**Alternative (simpler):** Compute sensitivity at the scoring layer only, not per-fact-check. The spec says "publish sensitivity" which could mean at the dossier level. In that case, add it to `TopicSideScore`:
```python
@dataclass
class TopicSideScore:
    ...
    insufficiency_sensitivity: Dict[str, float] = field(default_factory=dict)
```

And populate it in `_compute_topic_side_score` using the function above.

---

## P1 High-Priority Fixes

### P1.1 Fix Evidence Filtering (Keep Low-Confidence as UNCLEAR)

**File:** `skills/fact_checking/synthesis.py`
**Bug:** `_filter_evidence` completely removes items with `relevance_score < 0.3` or `direction_confidence < 0.7`. The spec says they should remain with `direction = UNCLEAR` and be treated as non-decisive. This preserves evidence trails in the audit log.

**Current code:**
```python
def _filter_evidence(items: List[EvidenceItem]) -> List[EvidenceItem]:
    filtered: List[EvidenceItem] = []
    for item in items:
        if item.relevance_score < RELEVANCE_THRESHOLD:
            continue
        if item.direction_confidence < DIRECTION_CONFIDENCE_THRESHOLD:
            continue
        filtered.append(item)
    return filtered
```

**Fix:**
```python
def _filter_evidence(items: List[EvidenceItem]) -> List[EvidenceItem]:
    filtered: List[EvidenceItem] = []
    for item in items:
        if item.relevance_score < RELEVANCE_THRESHOLD:
            # Reject entirely — too irrelevant to keep even as non-decisive
            continue
        if item.direction_confidence < DIRECTION_CONFIDENCE_THRESHOLD:
            # Keep but mark as non-decisive (UNCLEAR)
            # Create a copy to avoid mutating the original audit record
            from dataclasses import replace
            demoted = replace(item, direction=Direction.UNCLEAR)
            filtered.append(demoted)
        else:
            filtered.append(item)
    return filtered
```

**Why this matters:** If an item is dropped entirely, the audit log shows no evidence was retrieved for that subclaim (Rule I: "no evidence"). But evidence *was* retrieved — it just wasn't decisive. The demotion preserves the trail.

**Test update:** In `test_v15_core.py` or `test_phase3.py`, add a test that:
1. Creates an evidence item with `direction_confidence=0.5`
2. Runs synthesis
3. Asserts the result is `INSUFFICIENT` (because no decisive evidence)
4. Asserts the audit metadata or diagnostics reference the demoted item

---

### P1.2 Fix Compound best_evidence_tier Bug

**File:** `skills/fact_checking/claim_expression.py`
**Bug:** For `AND` all-supported and `OR` all-refuted, `best_evidence_tier` uses `_tiers("best_evidence_tier")` instead of `_tiers("decisive_evidence_tier")`. The spec says: *"best_evidence_tier = min child decisive tiers only when compound is SUPPORTED or REFUTED"*.

**Current code (in `_and_result` or similar):**
```python
best_tier = min(_tiers("best_evidence_tier")) if child_results else None
```

**Fix:**
```python
best_tier = min(_tiers("decisive_evidence_tier")) if child_results else None
```

Apply the same fix to `OR` all-refuted case.

**Test update:** In `test_v15_core.py`, add:
```python
def test_and_best_tier_uses_decisive_tier():
    # Create a compound where one child has best_tier=1 but decisive_tier=2
    # Assert the AND result's best_evidence_tier = 2 (the decisive tier)
```

---

### P1.3 Implement operationalization on FactCheckResult

**File:** `skills/fact_checking/synthesis.py`
**Problem:** `FactCheckResult.operationalization` is currently set to `decomposition.original_text` in `_build_fact_check_result`. It should be a synthesis-generated string describing what would confirm/refute the premise.

**Fix in `_build_fact_check_result`:**
```python
def _build_fact_check_result(...):
    # Synthesize operationalization from subclaim results
    if root_result.status == "SUPPORTED":
        op = "To refute: provide a primary source that directly contradicts the claim or shows the cited source is out of scope."
    elif root_result.status == "REFUTED":
        op = "To overturn: provide a primary source that supersedes the contradicting record."
    else:  # INSUFFICIENT
        if not atomic_results:
            op = "To resolve: locate a primary source that directly addresses this claim."
        else:
            tiers_present = {r.best_evidence_tier for r in atomic_results if r.best_evidence_tier}
            if 1 in tiers_present:
                op = "To resolve: identify whether the mismatch is caused by time scope, geography, or definitional drift."
            else:
                op = "To resolve: locate a primary source; lower-tier corroboration alone is not decisive."

    return FactCheckResult(
        ...
        operationalization=op,
    )
```

---

### P1.4 Add Persistent HumanReviewRecord Storage

**File:** `skills/fact_checking/human_review.py`
**Problem:** `create_human_review_record` builds a `HumanReviewRecord` object and computes its hash, but there is **no SQLite table or store** for it. The `HumanReviewQueue` only tracks queue status.

**Step 1 — Add a `ReviewRecordStore` class in `human_review.py`:**
```python
class ReviewRecordStore:
    """Append-only immutable storage for HumanReviewRecord."""

    def __init__(self, db_path: str = ".fact_check_review_records.db"):
        self._db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_records (
                    review_id TEXT PRIMARY KEY,
                    target_audit_id TEXT NOT NULL,
                    target_snapshot_id TEXT NOT NULL,
                    reviewer_role TEXT NOT NULL,
                    review_outcome TEXT NOT NULL,
                    review_note TEXT,
                    review_timestamp TEXT NOT NULL,
                    review_record_hash TEXT NOT NULL
                )
            """)
            conn.commit()

    def store(self, record: HumanReviewRecord) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO review_records
                (review_id, target_audit_id, target_snapshot_id, reviewer_role,
                 review_outcome, review_note, review_timestamp, review_record_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.review_id,
                    record.target_audit_id,
                    record.target_snapshot_id,
                    record.reviewer_role,
                    record.review_outcome.value,
                    record.review_note,
                    record.review_timestamp,
                    record.review_record_hash,
                ),
            )
            conn.commit()

    def get_by_audit(self, audit_id: str) -> List[HumanReviewRecord]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM review_records WHERE target_audit_id = ?",
                (audit_id,)
            ).fetchall()
            return [self._row_to_record(r) for r in rows]

    def _row_to_record(self, row) -> HumanReviewRecord:
        return HumanReviewRecord(
            review_id=row[0],
            target_audit_id=row[1],
            target_snapshot_id=row[2],
            reviewer_role=row[3],
            review_outcome=ReviewOutcome(row[4]),
            review_note=row[5],
            review_timestamp=row[6],
            review_record_hash=row[7],
        )
```

**Step 2 — Integrate into `HumanReviewQueue`:**
```python
class HumanReviewQueue:
    def __init__(self, db_path: str = ".fact_check_review_queue.db"):
        ...
        self._record_store = ReviewRecordStore()

    def complete_review(self, review_id: str, outcome: ReviewOutcome, note: str = "") -> Optional[HumanReviewRecord]:
        # After updating queue status, persist the record
        record = create_human_review_record(review_id, outcome, note)
        if record:
            self._record_store.store(record)
        return record
```

---

### P1.5 Expand Gold Test Coverage (14 Missing Tests)

**File:** `skills/fact_checking/tests/test_v15_core.py` (and new test files)

Add tests for these missing gold scenarios:

| # | Test | Where to Add |
|---|------|--------------|
| #4 | Temporal claim with date qualifier | `test_v15_core.py` |
| #5 | Numeric statistical claim with official source | `test_phase4.py` |
| #6 | Scoped numeric claim (geography/date/rounding) | `test_v15_core.py` |
| #17 | Nested AND containing OR | `test_v15_core.py` |
| #20 | Comparison with incompatible units | `test_v15_core.py` |
| #21 | Quantifier unresolved set | `test_v15_core.py` |
| #23 | Current-event claim with 2 independent Tier 2 sources | `test_v15_core.py` |
| #24 | Current-event claim with 2 non-independent sources | `test_v15_core.py` |
| #25 | Scientific study-specific claim | `test_phase4.py` |
| #26 | Scientific broad-consensus overclaim | `test_v15_core.py` |
| #27 | Legal claim requiring official source | `test_v15_core.py` |
| #28 | Predictive claim | `test_v15_core.py` |
| #29 | Normative claim routed out | `test_decomposition.py` |
| #30 | Connector failure → INSUFFICIENT with connector_failure reason | Integration test |
| #33 | Tier 3 promotion with registry + independence | `test_phase4.py` |
| #35 | Provenance span preserved end-to-end | Integration test |

**Example test for #28 (Predictive claim):**
```python
def test_predictive_claim_returns_insufficient():
    subclaim = AtomicSubclaim(
        subclaim_id="sc1",
        parent_premise_id="p1",
        text="The stock market will crash next year.",
        claim_type=ClaimType.EMPIRICAL_ATOMIC,
    )
    decomposition = PremiseDecomposition(
        premise_id="p1",
        snapshot_id="snap1",
        original_text="The stock market will crash next year.",
        topic_id="t1",
        side=Side.FOR,
        root_claim_expression=ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id="sc1"),
        atomic_subclaims=[subclaim],
    )
    engine = SynthesisEngine()
    result = engine.synthesize(
        decomposition,
        evidence_items=[],
        predictive_subclaim_ids={"sc1"},
    )
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert result.insufficiency_reason == "predictive_claim_not_checkable"
```

---

### P1.6 Implement HIGH_IMPACT_LLM_DIRECTION Flag

**File:** `skills/fact_checking/synthesis.py`
**Spec:** §2 of 02_SYNTHESIS_ENGINE.md: *"If an LLM-classified text item would be decisive for a high-impact claim (LEGAL_REGULATORY, SCIENTIFIC with causal/consensus scope), add human_review_flags += HIGH_IMPACT_LLM_DIRECTION unless there is independent corroboration or deterministic verification."*

**Implementation:** In `_synthesize_atomic`, after resolving Tier 2 evidence, check:
```python
def _synthesize_atomic(...):
    ...
    # After classifying by tier and direction
    t1s, t1r, t2s, t2r, t3s, t3r = _items_by_tier_and_direction(filtered)

    # Check for high-impact LLM direction
    high_impact = subclaim.claim_type in (ClaimType.LEGAL_REGULATORY, ClaimType.SCIENTIFIC)
    if high_impact:
        for item in (t2s + t2r):
            if item.direction_method == DirectionMethod.LLM_CLASSIFIER:
                # Flag unless there is deterministic corroboration
                has_deterministic = any(
                    i.direction_method == DirectionMethod.DETERMINISTIC_STRUCTURED
                    and i.direction == item.direction
                    for i in filtered
                )
                if not has_deterministic:
                    # Add flag to the result (will be added later)
                    pass
```

Then in `_make_decisive_result` and the INSUFFICIENT paths, append `HumanReviewFlag.HIGH_IMPACT_LLM_DIRECTION` to `human_review_flags` when this condition is met.

---

### P1.7 Fix Scoring Engine REFUTED Semantics

**File:** `backend/scoring_engine.py`
**Problem:** The scoring engine computes "decisiveness" as `abs(p_true - 0.5)`. With v1.5 ternary values:
- SUPPORTED (1.0): decisiveness = 0.5 ✅
- REFUTED (0.0): decisiveness = 0.5 ✅ (accidentally correct)
- INSUFFICIENT (0.5): decisiveness = 0.0 ✅

But the semantics are inverted for REFUTED: the old system treated low p_true as "low confidence," while v1.5 treats 0.0 as "decisively refuted." The coverage/rebuttal leverage computation should treat REFUTED as high-leverage (it strongly contradicts the opposing side).

**Fix:** Add an explicit mapping:
```python
# In compute_coverage or wherever decisiveness is used
def _decisiveness_v15(p_true: float, verdict: str) -> float:
    """v1.5 ternary decisiveness: SUPPORTED and REFUTED are equally decisive."""
    if verdict in ("SUPPORTED", "REFUTED"):
        return 1.0
    return 0.0  # INSUFFICIENT
```

Update `compute_factuality_diagnostics` to distinguish:
```python
# Old:
is_insufficient = abs(p_true - 0.5) < epsilon

# New:
from skills.fact_checking.v15_models import FactCheckResult as V15Result
# If result is v1.5 shape:
is_insufficient = result.status == "INSUFFICIENT"
is_refuted = result.status == "REFUTED"
is_supported = result.status == "SUPPORTED"
```

---

## P2 Medium-Priority Fixes

### P2.1 Fix Float Formatting in Canonical JSON

**File:** `skills/fact_checking/v15_cache.py`
**Bug:** `round(x, 6)` can produce scientific notation (e.g., `1e-07`), breaking hash stability.

**Fix:**
```python
# Old:
if isinstance(value, float):
    return round(value, 6)

# New:
if isinstance(value, float):
    return f"{value:.6f}"
```

Wait — this returns a string, which changes the JSON type. Better fix:
```python
if isinstance(value, float):
    formatted = f"{value:.6f}"
    # Parse back to float to preserve type, but with fixed formatting
    return float(formatted)
```

Actually, the cleanest fix is to format as string in the JSON output but keep floats as floats in Python. Since `json.dumps` is called at the end, we need a custom encoder:

```python
class _CanonicalEncoder(json.JSONEncoder):
    def encode(self, obj):
        # Override to format floats with %.6f
        def _format(obj):
            if isinstance(obj, float):
                return f"{obj:.6f}"
            if isinstance(obj, list):
                return [_format(v) for v in obj]
            if isinstance(obj, dict):
                return {k: _format(v) for k, v in sorted(obj.items())}
            return obj
        return super().encode(_format(obj))
```

Then use this encoder in `canonical_json_serialize`.

---

### P2.2 Implement Entity/Concept Linking

**New file:** `skills/fact_checking/entity_linker.py`
**Spec:** 03_PIPELINE.md §2

**Implementation sketch:**
```python
"""
Entity / Concept Linking for v1.5.

Resolves entities in subclaim text to stable identifiers (Wikidata QIDs, DOIs, etc.).
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class EntityLink:
    entity_id: str
    mention_span: str
    canonical_id: str
    canonical_type: str
    canonical_label: str
    linking_confidence: float
    ambiguity_flag: bool
    ambiguity_candidates: List[str]


class EntityLinker:
    """Stub implementation. In production, this would:
    1. Use Wikidata API (wbsearchentities) for candidates
    2. Use LLM disambiguation with context window
    3. Store QIDs for persons, organizations, locations, events, concepts
    """

    def link(self, subclaim_text: str) -> List[EntityLink]:
        # Placeholder: return empty links
        # TODO: Implement NER + Wikidata search + LLM disambiguation
        return []
```

Then wire into the pipeline in `skill.py` or `decomposition.py`:
```python
# In _check_v15:
linker = EntityLinker()
for subclaim in decomposition.atomic_subclaims:
    links = linker.link(subclaim.text)
    ambiguous = [l for l in links if l.ambiguity_flag or l.linking_confidence < 0.7]
    if ambiguous:
        entity_failure_subclaim_ids.add(subclaim.subclaim_id)
```

---

### P2.3 Implement QUANTIFIER Evaluation

**File:** `skills/fact_checking/claim_expression.py`
**Current:** QUANTIFIER is a hard-coded placeholder returning INSUFFICIENT.

**Spec:** 02_SYNTHESIS_ENGINE.md §3: *"Quantified set must be resolved. Predicate must be checkable. Threshold must be explicit. If set, predicate, or threshold is unresolved → INSUFFICIENT. Otherwise evaluate deterministically."*

**Implementation:**
```python
def _evaluate_quantifier(expr, subclaim_results):
    quantifier = expr.quantifier  # e.g., "ALL", "EXISTS", "AT_LEAST"
    param = expr.quantifier_parameter  # e.g., 3 for "at least 3"

    # The quantifier applies over a set of child subclaims
    children = [_evaluate_expression(child, subclaim_results) for child in expr.children]

    # Check if set is resolved
    if not children:
        return SubclaimResult(
            subclaim_id="quantifier",
            status="INSUFFICIENT",
            p=0.5,
            insufficiency_reason="quantifier_unresolved_set",
        )

    supported_count = sum(1 for c in children if c.status == "SUPPORTED")
    refuted_count = sum(1 for c in children if c.status == "REFUTED")
    total = len(children)

    if quantifier == "ALL":
        if refuted_count > 0:
            return _make_result("REFUTED", 0.0)
        if supported_count == total:
            return _make_result("SUPPORTED", 1.0)
        return _make_result("INSUFFICIENT", 0.5)

    if quantifier == "EXISTS":
        if supported_count > 0:
            return _make_result("SUPPORTED", 1.0)
        if refuted_count == total:
            return _make_result("REFUTED", 0.0)
        return _make_result("INSUFFICIENT", 0.5)

    if quantifier == "AT_LEAST" and isinstance(param, int):
        if supported_count >= param:
            return _make_result("SUPPORTED", 1.0)
        if total - refuted_count < param:
            return _make_result("REFUTED", 0.0)
        return _make_result("INSUFFICIENT", 0.5)

    # Unknown quantifier
    return _make_result("INSUFFICIENT", 0.5, "unknown_quantifier")
```

---

### P2.4 Implement Web Evidence Archiving

**File:** `skills/fact_checking/normalizer.py`
**Spec:** 01_DATA_MODELS.md §8 and 03_PIPELINE.md §4: *"MUST store content hash (SHA-256 of normalized page text), MUST attempt archive.org permalink generation, MUST store full page content in snapshot storage if archive.org fails."*

**Implementation:**
```python
import hashlib
import urllib.request
from typing import Optional


def archive_web_evidence(source_url: str, page_text: str) -> Dict[str, Optional[str]]:
    """Archive web evidence for artifact replay verification."""
    content_hash = hashlib.sha256(page_text.encode("utf-8")).hexdigest()
    archive_url: Optional[str] = None
    snapshot_storage_key: Optional[str] = None

    # Try archive.org
    try:
        archive_url = _request_archive_org(source_url)
    except Exception:
        pass

    # If archive.org fails, store full content in snapshot storage
    if archive_url is None:
        snapshot_storage_key = _store_snapshot(source_url, page_text)

    return {
        "content_hash": content_hash,
        "archive_org_url": archive_url,
        "snapshot_storage_key": snapshot_storage_key,
    }


def _request_archive_org(url: str) -> Optional[str]:
    """Submit URL to archive.org and return permalink."""
    api_url = f"https://web.archive.org/save/{url}"
    req = urllib.request.Request(api_url, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        # Archive.org returns the snapshot URL in the response
        final_url = resp.geturl()
        if final_url and "web.archive.org" in final_url:
            return final_url
    return None


def _store_snapshot(source_url: str, page_text: str) -> str:
    """Store full page content in snapshot storage. Return storage key."""
    # This would integrate with FrozenConnectorStorage
    key = hashlib.sha256(f"{source_url}:{page_text[:100]}".encode()).hexdigest()
    # Store in a designated directory or SQLite blob
    return key
```

Then update `EvidenceItem` creation in connectors to include these fields, and update the normalizer to call `archive_web_evidence`.

---

### P2.5 Implement Source Reputation Registry

**New file:** `skills/fact_checking/source_registry.py`
**Spec:** 03_PIPELINE.md §3: *"Maintain allowlist of domains/publications qualifying as Tier 2. Promotion requires: (a) registry match AND (b) independence verification AND (c) policy approval."*

**Implementation sketch:**
```python
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ReputationEntry:
    domain: str
    publication_name: str
    tier: int  # promoted tier
    approved_by: str
    approval_date: str


class SourceReputationRegistry:
    """Allowlist of Tier 3 sources that can be promoted to Tier 2."""

    def __init__(self, entries: Optional[List[ReputationEntry]] = None):
        self._entries = entries or []
        self._domain_index = {e.domain: e for e in self._entries}

    def is_promoted(self, domain: str) -> bool:
        return domain in self._domain_index

    def get_promoted_tier(self, domain: str) -> Optional[int]:
        entry = self._domain_index.get(domain)
        return entry.tier if entry else None

    def promote(self, domain: str, publication_name: str, approved_by: str) -> ReputationEntry:
        entry = ReputationEntry(
            domain=domain,
            publication_name=publication_name,
            tier=2,
            approved_by=approved_by,
            approval_date=datetime.now().isoformat(),
        )
        self._entries.append(entry)
        self._domain_index[domain] = entry
        return entry
```

Then update `SynthesisEngine._resolve_tier2` or `normalizer.py` to check the registry before assigning Tier 3.

---

### P2.6 Implement Connector Fallback Chains

**File:** `skills/fact_checking/v15_connectors.py`
**Spec:** 03_PIPELINE.md §3: *"Configurable per connector type in published fallback table. Example: BLS API → Census API → Tier 2 RAG (statistical claims). Fallback triggers: HTTP error, timeout, schema mismatch, empty result set."*

**Implementation:**
```python
class ConnectorFallbackChain:
    """Ordered list of connectors for a claim type, with fallback triggers."""

    def __init__(self, connectors: List[BaseEvidenceConnector]):
        self._connectors = connectors

    def retrieve(self, subclaim: AtomicSubclaim) -> List[EvidenceItem]:
        for connector in self._connectors:
            try:
                items = connector.retrieve(subclaim)
                if items:
                    return items
            except Exception:
                continue
        return []
```

Define fallback tables per claim type:
```python
FALLBACK_TABLES = {
    ClaimType.NUMERIC_STATISTICAL: [
        BLSStatisticsConnector(),
        # CensusConnector(),  # TODO: implement
        CuratedRAGConnector(),
    ],
    ClaimType.SCIENTIFIC: [
        CrossrefConnector(),
        CuratedRAGConnector(),
    ],
}
```

---

### P2.7 Implement Computational Rerun Mode

**File:** `skills/fact_checking/v15_audit.py`
**Spec:** 03_PIPELINE.md §6: *"Computational rerun: re-executes connectors and model steps from manifest. Diagnostic only."*

**Implementation:**
```python
class ComputationalRerunner:
    """Diagnostic-only rerun of a fact-check from a ReplayManifest."""

    def __init__(self, manifest: ReplayManifest):
        self._manifest = manifest

    def rerun(self, premise_id: str) -> Tuple[FactCheckResult, Dict[str, Any]]:
        """Rerun the fact-check for a premise. Returns (result, diagnostics).

        NOTE: This is diagnostic only. Results may differ because live APIs,
        web pages, and hosted LLMs change over time.
        """
        params = self._manifest.parameter_pack

        # Reconstruct connectors from versions
        connectors = self._rebuild_connectors(params.connector_versions)

        # Rebuild decomposer with same model/temperature
        decomposer = Decomposer(
            llm_backend=self._rebuild_llm_backend(params)
        )

        # Rebuild synthesis engine
        engine = SynthesisEngine()

        # Run pipeline
        # ...

        diagnostics = {
            "rerun_type": "computational_rerun",
            "warning": "Results may differ from original due to live API changes.",
            "manifest_id": self._manifest.manifest_id,
        }

        return result, diagnostics
```

---

### P2.8 Fix BLS Connector Direction

**File:** `skills/fact_checking/v15_connectors.py`
**Bug:** `BLSStatisticsConnector._query_live_api` returns `Direction.NEUTRAL` with no `claimed_value`, making deterministic comparison impossible.

**Fix:** Parse the claimed value from the subclaim text and populate `claimed_value`:
```python
def _query_live_api(self, subclaim, series_keyword):
    ...
    # Extract claimed value from subclaim text using regex/heuristic
    claimed_value = self._extract_claimed_value(subclaim.text)

    item = self._make_item(
        ...
        direction=Direction.NEUTRAL,  # Still neutral; synthesis does comparison
        claimed_value=claimed_value,
        source_value=source_val,
        deterministic_comparison_result=self._compare_values(claimed_value, source_val),
    )
    return [item]
```

---

### P2.9 Fix CuratedRAG DirectionMethod Label

**File:** `skills/fact_checking/v15_connectors.py`
**Bug:** `CuratedRAGConnector._classify_direction` uses `DirectionMethod.LLM_CLASSIFIER` even though classification is deterministic keyword matching.

**Fix:**
```python
# Change from:
direction_method=DirectionMethod.LLM_CLASSIFIER

# To:
direction_method=DirectionMethod.DETERMINISTIC_STRUCTURED
```

---

## P3 Lower-Priority Improvements

### P3.1 Implement Drop-Component Sensitivity

**File:** `skills/fact_checking/scoring_inputs.py`
**Spec:** LSD §16: *"Drop-component sensitivity (diagnostic): recompute Q with each component removed one-at-a-time to show dominance."*

Add to `TopicSideScore`:
```python
drop_component_sensitivity: Dict[str, Optional[float]] = field(default_factory=dict)
"""Q recomputed with each component removed. Keys: 'empirical', 'normative', 'reasoning', 'coverage'."""
```

---

### P3.2 Implement Frame Sensitivity Computation

**File:** New or `scoring_inputs.py`
**Spec:** LSD §19: *"Frame sensitivity (multi-frame) → agenda-capture resistance"*

For multi-frame mode, compute q per frame and frame dispersion. This is a dossier-level computation, not a fact-check core computation.

---

### P3.3 Implement Normative Claim Routing

**File:** `skills/fact_checking/decomposition.py` or `skill.py`
**Spec:** Gold test #29: *"Normative claim routed out — Not fact-checked"*

In `Decomposer.decompose` or in `_check_v15`:
```python
if premise.claim_type == ClaimType.EMPIRICAL_ATOMIC and _is_normative(premise.original_text):
    # Return a special result indicating this was routed out
    return FactCheckResult(
        ...
        status="NOT_FACT_CHECKED",
        p=0.5,
        insufficiency_reason="normative_claim_routed_out",
    )
```

Note: `ClaimType` currently doesn't have a `NORMATIVE` value. Add it or handle at the decomposition layer.

---

### P3.4 Update Database Schema for v1.5

**File:** `backend/database.py`
Add columns to `canonical_facts`:
```sql
ALTER TABLE canonical_facts ADD COLUMN subclaim_results_json TEXT;
ALTER TABLE canonical_facts ADD COLUMN human_review_flags_json TEXT;
ALTER TABLE canonical_facts ADD COLUMN insufficiency_reason TEXT;
ALTER TABLE canonical_facts ADD COLUMN best_evidence_tier INTEGER;
ALTER TABLE canonical_facts ADD COLUMN limiting_evidence_tier INTEGER;
ALTER TABLE canonical_facts ADD COLUMN decisive_evidence_tier INTEGER;
ALTER TABLE canonical_facts ADD COLUMN citations_json TEXT;
ALTER TABLE canonical_facts ADD COLUMN synthesis_logic_json TEXT;
```

Add new table for evidence items:
```sql
CREATE TABLE fact_check_evidence_items (
    evidence_id TEXT PRIMARY KEY,
    canon_fact_id TEXT NOT NULL,
    source_type TEXT,
    source_tier INTEGER,
    source_url TEXT,
    source_title TEXT,
    quote_or_span TEXT,
    direction TEXT,
    direction_confidence REAL,
    relevance_score REAL,
    FOREIGN KEY (canon_fact_id) REFERENCES canonical_facts(canon_fact_id)
);
```

---

### P3.5 Add Frontend Fact-Check Detail Panels

**Files:** `frontend/topic.html`, `frontend/dossier.html`
Add expandable sections showing:
- Subclaim decomposition tree (if compound)
- Evidence items with source links and quotes
- Tier badges (T1/T2/T3)
- Human review flags (warning badges)
- Synthesis logic summary

Example HTML structure:
```html
<div class="fact-check-details">
  <details>
    <summary>Fact Check Details</summary>
    <div class="subclaim-tree">
      <!-- Render ClaimExpression tree -->
    </div>
    <div class="evidence-items">
      <!-- Render EvidenceItem list with source links -->
    </div>
    <div class="review-flags">
      <!-- Render human_review_flags as warning badges -->
    </div>
  </details>
</div>
```

---

## Integration Instructions

### Integration: Wire v1.5 into DebateEngineV2

**File:** `backend/debate_engine_v2.py`

**Step 1 — Update imports:**
```python
from skills.fact_checking import (
    FactCheckingSkill,
    ConnectorRegistry,
)
```

**Step 2 — Update `__init__`:**
```python
if self._fact_check_mode == "PERFECT":
    self.fact_checker = FactCheckingSkill(
        mode=self._fact_check_mode,
        v15_connectors=ConnectorRegistry.default_connectors(),
        enable_async=False,
    )
elif self._fact_check_mode == "OFFLINE":
    self.fact_checker = FactCheckingSkill(
        mode=self._fact_check_mode,
        v15_connectors=ConnectorRegistry.offline_connectors(),
        enable_async=False,
    )
else:
    self.fact_checker = FactCheckingSkill(
        mode=self._fact_check_mode,
        v15_connectors=ConnectorRegistry.default_connectors(),
        enable_async=self._async_enabled,
    )
```

### Integration: Update Extraction Layer

**File:** `backend/extraction.py`

No changes needed if the adapter (P0.3) is implemented correctly. The v1 `FactCheckResult` shape will be preserved.

However, to expose v1.5 richness, optionally update `ExtractedFact`:
```python
@dataclass
class ExtractedFact:
    ...
    # v1.5-native fields (optional enrichment)
    subclaim_results: List[Dict] = field(default_factory=list)
    human_review_flags: List[str] = field(default_factory=list)
    insufficiency_reason: str = ""
    best_evidence_tier: Optional[int] = None
```

And populate them in `extract_facts_from_spans`:
```python
fact.subclaim_results = result.diagnostics.get("subclaim_results", [])
fact.human_review_flags = result.diagnostics.get("human_review_flags", [])
fact.insufficiency_reason = result.diagnostics.get("insufficiency_reason", "")
```

### Integration: Migration Path

**Phase 1 (Immediate):** Adapter layer
- v1.5 runs internally, v1 shape exposed externally
- All existing tests pass
- Debate engine uses v1.5 connectors

**Phase 2 (Week 2):** Database schema update
- Add v1.5 columns to `canonical_facts`
- Store subclaim_results, evidence items, flags

**Phase 3 (Week 3):** API enrichment
- Add `/api/debate/fact-check-diagnostics/<fact_id>` endpoint
- Expose decomposition tree, evidence items, review flags

**Phase 4 (Week 4):** Frontend update
- Add detail panels to topic.html and dossier.html
- Show evidence sources, tier badges, review flags

---

## Testing Strategy

1. **Unit tests:** Run all 185 v1.5 tests + 26 legacy tests after each fix
2. **Integration tests:** Create `tests/integration/test_v15_integration.py` with:
   - End-to-end fact check through `FactCheckingSkill.check_fact()`
   - Debate engine snapshot generation with v1.5 fact checker
   - Database round-trip for v1.5 fields
3. **Regression tests:** Run the full pytest suite:
   ```bash
   python -m pytest tests/ -v
   ```
4. **Manual verification:** Submit a post to a debate, generate snapshot, verify fact-check results in the database

---

## Verification Checklist

After all fixes are applied, verify:

- [ ] `python -m pytest skills/fact_checking/tests/ -v` passes (185+ tests)
- [ ] `python -m pytest tests/unit/test_fact_check_skill.py -v` passes (26 tests)
- [ ] Merkle root is deterministic and verifiable by external tools
- [ ] Authoritative hash changes when any input field changes
- [ ] `check_fact()` returns v1-compatible `FactCheckResult`
- [ ] `insufficiency_sensitivity` is populated for mixed results
- [ ] Low-confidence evidence is kept as `UNCLEAR` (not dropped)
- [ ] Compound `best_evidence_tier` uses decisive tiers
- [ ] All 45 gold tests are covered
- [ ] Database schema supports v1.5 fields
- [ ] Frontend displays fact-check details
- [ ] Debate engine initializes with v1.5 connectors
- [ ] Async queue works with v1.5 pipeline

---

*End of fix instructions.*
