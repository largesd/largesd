# Fact Checking Implementation Task Plan

This document turns the roadmap into an execution-ready plan for `debate_system`. It assumes `EXECUTION_SPEC.md` is the product contract and this file is the implementation playbook.

## Release Objective

Ship a v1 fact-checking system that is safe, deterministic, and honest about uncertainty.

In practical terms, that means:

1. `PERFECT` can decisively resolve one narrow supported claim family using real Tier-1 evidence.
2. Unsupported, compound, badly scoped, conflicting, or stale claims return `INSUFFICIENT`.
3. `ONLINE_ALLOWLIST` remains an experimental integration mode, not a production truth mode.
4. Async behavior, policy behavior, and ground-truth behavior are all test-covered and predictable.

## Non-Goals For V1

The following should explicitly not block v1:

- broad coverage of arbitrary factual claims
- causal or comparative reasoning
- multi-hop synthesis across many sources
- web-only decisive adjudication
- fully automated moderator tooling beyond a minimum review/promotion loop
- a polished UI for every diagnostic before the backend contract is stable

## Working Definition Of "Done"

The subsystem should only be called "working" when all of the following are true:

1. it handles new empirical claims without async cross-instance corruption
2. policy semantics are real and test-covered
3. ground-truth reads are robust across legacy and current data
4. one narrow v1 claim family can be resolved using a real Tier-1 connector
5. `PERFECT` returns `SUPPORTED` or `REFUTED` only for supported claim families with decisive evidence
6. unsupported, badly scoped, temporal, or compound cases cleanly return `INSUFFICIENT`
7. diagnostics explain why a claim was unresolved

## Suggested Delivery Slices

This is the recommended pull-request order. Each slice should stay reviewable on its own and leave the tree green.

1. Contract slice
   - v1 support contract
   - frozen mode semantics
   - naming cleanup in docs, comments, and tests
2. Evaluation slice
   - gold set fixture
   - test harness and reporting helpers
3. Runtime hardening slice
   - async queue isolation
   - policy flag truthfulness
   - ground-truth routing and migration safety
4. Retrieval architecture slice
   - claim decomposition
   - connector planner
   - diagnostic reason codes
5. First real capability slice
   - narrow Tier-1 connector
   - `PERFECT` rewiring
   - corroborative web connector wiring
6. Productization slice
   - review loop persistence
   - evidence and dossier diagnostics
   - release gates

## Shared Implementation Rules

These rules apply across every phase:

1. Do not expand the claim family while the system contract is still moving.
2. If a public flag exists, a test must prove toggling it changes runtime behavior.
3. If a mode name exists, comments, code paths, and tests must all describe it the same way.
4. If a claim cannot be decisively resolved under the v1 contract, prefer `INSUFFICIENT` over heuristics.
5. Do not let simulated or web-only evidence become decisive in `PERFECT`.
6. Preserve the LSD discrete output contract:
   - `SUPPORTED` -> `p_true = 1.0`
   - `REFUTED` -> `p_true = 0.0`
   - `INSUFFICIENT` -> `p_true = 0.5`

## Recommended New Artifacts

These are the most useful new files to add during implementation:

- `skills/fact_checking/testdata/fact_check_gold_v1.jsonl`
- `skills/fact_checking/decomposer.py`
- `skills/fact_checking/planner.py`
- `skills/fact_checking/diagnostics.py` if reason codes and connector-path metadata need a dedicated home

## Verification Backbone

The baseline verification command should stay constant through the project:

```bash
pytest -q test_fact_check_skill.py test_debate_system.py test_lsd_v1_2_contracts.py
```

After the gold set lands, every meaningful change should also run the gold-set evaluation harness.

## Phase 0: Define Exact V1 Support

### Goal

Lock the v1 product scope before adding more capability.

### Why This Comes First

The current code and docs still imply broader support than the system can honestly provide. If the team starts adding connectors or policy behavior before freezing scope, later tests and docs will drift again.

### Concrete Work

1. Adopt the v1 support contract in `EXECUTION_SPEC.md` as the canonical scope statement.
2. Mirror that contract into live comments/docstrings in:
   - `skills/fact_checking/skill.py`
   - `backend/debate_engine_v2.py`
3. Update any stale docs that still imply general factual coverage:
   - `docs/implementation/FACT_CHECK_SKILL_IMPLEMENTATION.md`
   - `docs/fact_checking_handoff/README.md`
4. Ensure the contract names both supported and unsupported claim families.
5. Add one single paragraph that a reviewer can quote verbatim during release review.

### Files

- `skills/fact_checking/skill.py`
- `backend/debate_engine_v2.py`
- `docs/fact_checking_handoff/README.md`
- `docs/implementation/FACT_CHECK_SKILL_IMPLEMENTATION.md`

### Verification

1. Read the top-level docstrings and confirm they match `EXECUTION_SPEC.md`.
2. Ensure no public-facing doc still says or implies "all factual claims".

### Exit Criteria

- A one-paragraph v1 claim-support contract exists in docs and the main runtime files.

## Phase 1: Freeze Mode Semantics

### Goal

Make the meaning of each mode explicit and stable.

### Dependencies

- Phase 0

### Concrete Work

1. Adopt the frozen mode semantics from `EXECUTION_SPEC.md`.
2. Update docstrings, comments, and tests so each mode has one meaning:
   - `OFFLINE`
   - `ONLINE_ALLOWLIST`
   - `PERFECT_CHECKER`
   - `PERFECT`
3. Remove contradictory wording such as:
   - `PERFECT` behaving like fixture mode in comments
   - `ONLINE_ALLOWLIST` being described as production-safe
   - `PERFECT_CHECKER` being described as live truth
4. Make sure mode aliases normalize to the product names without changing the semantics behind the names.
5. Review top-level exports and comments in `skills/fact_checking/__init__.py`.

### Files

- `skills/fact_checking/skill.py`
- `backend/debate_engine_v2.py`
- `skills/fact_checking/__init__.py`
- `test_fact_check_skill.py`
- `test_lsd_v1_2_contracts.py`

### Verification

1. Add or update tests that assert mode labels are preserved in outputs.
2. Confirm that the default behavior for each mode matches its written contract.

### Exit Criteria

- A new agent can describe each mode in one sentence and the code/test naming supports that description.

## Phase 2: Build The Gold Test Set

### Goal

Create a stable evaluation set before major behavior changes.

### Dependencies

- Phases 0-1

### Concrete Work

1. Create a 50-100 claim gold set using the schema in `EXECUTION_SPEC.md`.
2. Store it in a stable fixture path, preferably `skills/fact_checking/testdata/fact_check_gold_v1.jsonl`.
3. Include:
   - supported
   - refuted
   - insufficient
   - temporal
   - scoped
   - compound
4. Add fields for:
   - expected verdict
   - claim family
   - authoritative source type
   - temporal/scoped/compound booleans
   - notes or rationale
5. Build a small loader helper in tests so later phases can reuse the same harness.
6. Separate fixture-only cases from real-connector cases so test mode and production mode can both be evaluated honestly.

### Files

- `skills/fact_checking/testdata/fact_check_gold_v1.jsonl`
- `test_fact_check_skill.py`
- optionally `test_perfect_skill.py` if that file becomes the better home for gold-set assertions

### Verification

1. Add a focused test that validates the fixture schema and required field coverage.
2. Add a summary assertion that category counts meet the minimum coverage targets.

### Exit Criteria

- Every later connector and policy change can be measured against the same claim set.

## Phase 3: Fix Async Architecture

### Goal

Eliminate cross-instance job processing and shutdown coupling.

### Dependencies

- Phase 2 should land first so behavior changes can be measured, but this phase can start once Phases 0-1 are stable.

### Current Risk

`FactCheckingSkill` currently points `ONLINE_ALLOWLIST` instances at a singleton queue and overwrites the queue processor from the newest skill instance. That can cross connectors, cache state, and shutdown behavior between independent runtimes.

### Concrete Work

1. Remove the global singleton queue pattern from `skills/fact_checking/fc_queue.py`.
2. Give each `FactCheckingSkill` instance its own queue instance and worker lifecycle.
3. Keep per-job context on the job object rather than relying on mutable singleton state.
4. Ensure `shutdown()` only shuts down the current skill's workers.
5. Preserve current async API shapes if possible:
   - `check_fact_async`
   - `get_job_status`
   - `get_job_result`
   - `get_queue_stats`
6. Add regression coverage for:
   - two skill instances with different connectors
   - two skill instances with different shutdown timing
   - duplicate claims submitted to different skill instances

### Files

- `skills/fact_checking/fc_queue.py`
- `skills/fact_checking/skill.py`
- `test_fact_check_skill.py`

### Verification

1. Add a two-instance test that proves job A cannot be processed by skill B.
2. Add a shutdown test that proves one instance can shut down without killing another.
3. Re-run the existing async tests and remove any need for `reset_global_queue()`.

### Exit Criteria

- Two `FactCheckingSkill` instances can run concurrently without crossing connectors, cache, or shutdown behavior.

## Phase 4: Make Policy Surface Truthful

### Goal

Ensure all public policy flags have real behavior.

### Dependencies

- Phase 3

### Current Risk

`EvidencePolicy` exposes flags such as `tier1_require_unanimity`, `tier2_require_unanimity`, and `ground_truth_sufficient`, but not all of them currently change adjudication behavior.

### Concrete Work

1. Decide flag-by-flag whether to:
   - implement it
   - delete it
2. For each surviving flag, add a direct behavioral test that toggles only that flag and changes the result.
3. Avoid shadow semantics where two flags partly overlap without one clear owner.
4. Reconcile `strict_mode`, `tier2_can_resolve`, and unanimity settings so the policy matrix is understandable.
5. Update `strict_policy()` and `default_policy()` only after the flag behaviors are explicit.

### Files

- `skills/fact_checking/policy.py`
- `skills/fact_checking/skill.py`
- `test_fact_check_skill.py`

### Verification

1. One dedicated test per public policy flag.
2. A policy matrix test that covers:
   - single Tier-1 confirm
   - conflicting Tier-1 evidence
   - unanimous Tier-2 evidence
   - ambiguous evidence

### Exit Criteria

- Every public policy flag has a real effect and a dedicated test proves it.

## Phase 5: Unify Ground Truth With Policy

### Goal

Make ground-truth behavior intentional, documented, and policy-governed.

### Dependencies

- Phase 4

### Current Risk

Ground truth is currently treated partly as a fast-path bypass and partly as policy-aware evidence. That makes it difficult to reason about whether a curated entry should still respect policy settings.

### Concrete Work

1. Adopt the ground-truth model from `EXECUTION_SPEC.md`:
   - curated Tier-1 evidence
   - still routed through `apply_policy(..., from_ground_truth=True)`
2. Refactor `_check_perfect()` and `_build_result_from_ground_truth()` so ground truth does not bypass the intended adjudication contract.
3. Ensure `ground_truth_sufficient` truly governs whether a single curated entry is enough.
4. Preserve evidence rendering and diagnostics for curated entries.
5. Add explicit tests for:
   - `ground_truth_sufficient=True`
   - `ground_truth_sufficient=False`

### Files

- `skills/fact_checking/skill.py`
- `skills/fact_checking/policy.py`
- `skills/fact_checking/connectors.py`
- `test_fact_check_skill.py`

### Verification

1. A curated entry should follow the same verdict mapping path as connector evidence.
2. Toggling `ground_truth_sufficient` should change at least one test outcome.

### Exit Criteria

- Ground truth is no longer a vague special case and its behavior is test-covered.

## Phase 6: Harden Ground-Truth Schema And Migration

### Goal

Ensure legacy, current, and empty ground-truth data all load safely.

### Dependencies

- Phase 5

### Current Risk

Legacy entries can still fail at read time when optional evidence fields are missing, and ground-truth results currently overwrite the caller's mode label with `PERFECT`.

### Concrete Work

1. Make missing `retrieved_at` safe when building `EvidenceRecord`.
2. Treat missing optional evidence fields as absent metadata, not fatal schema errors.
3. Preserve the caller mode label on ground-truth hits:
   - `PERFECT` stays `PERFECT`
   - `PERFECT_CHECKER` stays `PERFECT_CHECKER`
4. Confirm empty or malformed ground-truth files degrade to an empty store instead of crashing.
5. Add migration-safe readers before considering any schema version bump.

### Files

- `skills/fact_checking/connectors.py`
- `skills/fact_checking/skill.py`
- `test_fact_check_skill.py`

### Verification

Add tests for:

1. legacy entries without `retrieved_at`
2. legacy entries without review metadata
3. new entries with all fields present
4. empty ground-truth files
5. malformed evidence rows that should be skipped or defaulted safely

### Exit Criteria

- Old entries, new entries, and empty files all load safely.

## Phase 7: Add Claim Decomposition

### Goal

Split compound claims into atomic subclaims before retrieval.

### Dependencies

- Phase 2
- Phases 4-6 should be stable before this work feeds decisive retrieval

### Concrete Work

1. Add a decomposer module under `skills/fact_checking/`, preferably `decomposer.py`.
2. Implement the `Subclaim`-style structure from `EXECUTION_SPEC.md`.
3. Support minimum extraction for:
   - conjunction splitting
   - explicit dates or years
   - explicit geography
   - actor/entity
   - quantity
   - negation
4. Keep the decomposition deterministic and rule-based first; do not make it LLM-dependent in v1.
5. Update `backend/extraction.py` so empirical claims are decomposed before connector lookup.
6. Decide how the parent fact should aggregate subclaim results:
   - all supported -> supported
   - any refuted with direct scope match -> likely refuted
   - otherwise insufficient
7. Record decomposition diagnostics so downstream views can explain compound failures.

### Files

- `skills/fact_checking/decomposer.py`
- `skills/fact_checking/skill.py`
- `backend/extraction.py`
- `skills/fact_checking/models.py` if subclaims need first-class schema
- `test_fact_check_skill.py`
- `test_debate_system.py`

### Verification

1. Add decomposition unit tests with expected subclaim lists.
2. Add an integration test showing a compound fact yields multiple subclaim lookups.

### Exit Criteria

- A claim like "GDP rose and unemployment fell in Canada in 2024" becomes separate queryable subclaims.

## Phase 8: Add Connector Planner

### Goal

Stop querying everything blindly.

### Dependencies

- Phase 7

### Concrete Work

1. Add claim-family classification for each subclaim.
2. Build a simple routing layer, preferably `planner.py`, that selects:
   - Tier-1 structured connector first for supported families
   - Tier-2 web corroboration second
   - `INSUFFICIENT` if no authoritative path exists
3. Record planner outputs:
   - chosen connector path
   - why it was chosen
   - whether the claim family is unsupported
4. Keep planner decisions deterministic and inspectable in logs/tests.
5. Do not let the planner silently broaden scope beyond the v1 contract.

### Files

- `skills/fact_checking/planner.py`
- `skills/fact_checking/skill.py`
- `skills/fact_checking/models.py`
- `backend/extraction.py`
- `test_fact_check_skill.py`

### Verification

1. Add unit tests that map example claims to expected planner choices.
2. Add a failure-path test where the planner explicitly returns unsupported-family diagnostics.

### Exit Criteria

- The system can explain why it chose a connector, not just what it returned.

## Phase 9: Implement One Real Tier-1 Connector

### Goal

Support one narrow real claim family with decisive evidence.

### Dependencies

- Phase 8

### Recommended Scope

Use the first supported claim family from `EXECUTION_SPEC.md`:

- atomic identity/date/status claims about notable public entities in Wikidata

### Concrete Work

1. Narrow `skills/fact_checking/wikidata_connector.py` to a real production-safe subset instead of a general prototype.
2. Enforce a strict property whitelist:
   - office held / office holder
   - founded / inception date
   - headquarters location
   - country / located in administrative entity
   - birth date / death date
3. Require high-confidence entity resolution.
4. Return `SILENT` for:
   - ambiguous entity matches
   - weak property matches
   - unsupported claim families
5. Add stable tests for both supported and refuted outcomes in this family.
6. Make sure uncached claims can resolve without relying on ground-truth fixtures.

### Files

- `skills/fact_checking/wikidata_connector.py`
- `skills/fact_checking/skill.py`
- `skills/fact_checking/models.py`
- `test_fact_check_skill.py`
- `skills/fact_checking/testdata/fact_check_gold_v1.jsonl`

### Verification

1. Add connector unit tests for entity resolution and property matching.
2. Add end-to-end tests where `PERFECT` resolves supported-family claims without ground-truth help.

### Exit Criteria

- Uncached claims in the supported family can genuinely produce `SUPPORTED` or `REFUTED` under `PERFECT`.

## Phase 10: Keep Web Retrieval As Corroboration

### Goal

Prevent web retrieval from becoming a decisive source by accident.

### Dependencies

- Phase 8
- Can land before or alongside Phase 9, but must not weaken the `PERFECT` contract

### Concrete Work

1. Wire a real `SearchBackend` and `LLMClient` into `skills/fact_checking/web_rag_connector.py`.
2. Keep the connector Tier-2 in v1.
3. Ensure web evidence cannot alone produce `SUPPORTED` or `REFUTED` in `PERFECT`.
4. Use web evidence only for:
   - explanation enrichment
   - citations
   - corroboration metadata
5. Add explicit tests proving that web-only evidence yields `INSUFFICIENT` under strict production policy.

### Files

- `skills/fact_checking/web_rag_connector.py`
- `skills/fact_checking/policy.py`
- `skills/fact_checking/skill.py`
- `test_fact_check_skill.py`

### Verification

1. Add a test with only Tier-2 evidence in `PERFECT` and expect `INSUFFICIENT`.
2. Add a test showing web citations still appear in diagnostics/explanations.

### Exit Criteria

- Web evidence improves explanations and citations without manufacturing certainty.

## Phase 11: Rewire `PERFECT` Mode

### Goal

Make `PERFECT` use the real Tier-1 connector path.

### Dependencies

- Phases 8-10

### Concrete Work

1. Update `backend/debate_engine_v2.py` to inject the real Tier-1 connector set for `PERFECT`.
2. Leave simulated connectors only in fixture or non-production modes:
   - `ONLINE_ALLOWLIST`
   - `PERFECT_CHECKER`
3. Keep strict policy defaults for `PERFECT`.
4. Confirm the debate engine does not accidentally enable decisive simulated connectors in production wiring.
5. Re-run both direct fact-checking tests and debate-engine integration tests.

### Files

- `backend/debate_engine_v2.py`
- `skills/fact_checking/skill.py`
- `test_fact_check_skill.py`
- `test_debate_system.py`

### Verification

1. Add a test proving `PERFECT` can resolve an in-scope claim without ground truth.
2. Add a test proving an unsupported family still returns `INSUFFICIENT`.

### Exit Criteria

- `PERFECT` is no longer effectively ground-truth only.

## Phase 12: Build The Human Review Loop

### Goal

Turn hard unresolved cases into curated future wins.

### Dependencies

- Phases 5-6
- Best added after the first real Tier-1 path exists

### Concrete Work

1. Extend ground-truth storage or move it to a more structured persistence path.
2. Store:
   - reviewer
   - review timestamp
   - rationale
   - evidence snapshot
   - stored verdict
   - claim hash
   - schema version
3. Add a promotion path from unresolved claim to curated ground truth.
4. Make sure stored evidence is durable enough for later audit review.
5. Keep the write path explicit and moderator-driven; do not auto-promote low-confidence retrieval.

### Files

- `skills/fact_checking/connectors.py`
- `skills/fact_checking/skill.py`
- `backend/database.py` if ground truth moves out of JSON
- `backend/app_v3.py` if an API surface is needed
- `test_fact_check_skill.py`

### Verification

1. Add tests that store a reviewed entry and then reuse it on the next identical claim.
2. Add tests that preserve reviewer metadata.

### Exit Criteria

- A moderator can resolve an important claim once and have future identical claims reuse that resolution.

## Phase 13: Surface Diagnostics Into The Debate Product

### Goal

Make unresolved claims understandable to downstream users.

### Dependencies

- Phases 7-12

### Concrete Work

1. Persist subclaim and insufficiency diagnostics in the extracted/canonical fact pipeline.
2. Publish tier counts, connector path, and insufficiency reasons into:
   - evidence flows
   - dossier flows
   - published-result payloads if appropriate
3. Distinguish at least these failure modes:
   - compound claim failure
   - source conflict
   - unsupported family
   - no Tier-1 source
   - temporal staleness
   - scope mismatch
4. Ensure the UI can render the extra diagnostics without breaking existing consumers that only expect `p_true`.

### Files

- `backend/extraction.py`
- `backend/debate_engine_v2.py`
- `backend/database.py`
- `backend/app_v3.py`
- `backend/published_results.py`
- `frontend/dossier.html`
- `frontend/topic.html`
- `test_debate_system.py`

### Verification

1. Add payload-level tests for new diagnostics fields.
2. Add UI smoke checks or fixture rendering checks if those views are covered.

### Exit Criteria

- A user can tell why a fact failed instead of only seeing `p_true = 0.5`.

## Phase 14: Add End-To-End Evaluation Gates

### Goal

Make `PERFECT` rollout a release decision rather than a guess.

### Dependencies

- All prior phases

### Concrete Work

1. Run the gold set on every meaningful change.
2. Record at least:
   - total accuracy on supported-family cases
   - false decisive rate on unsupported families
   - async isolation regressions
   - ground-truth load regressions
3. Define release criteria:
   - zero async cross-instance failures
   - zero ground-truth load crashes
   - policy toggle tests passing
   - accuracy target met for the supported v1 claim family
   - unsupported claim families reliably return `INSUFFICIENT`
4. Make enablement of `PERFECT` a conscious release gate, not just a code path that happens to exist.
5. Document the current readiness state in the handoff docs after each milestone.

### Files

- `test_fact_check_skill.py`
- `test_debate_system.py`
- `docs/fact_checking_handoff/README.md`
- optionally a small evaluation summary artifact under `artifacts/` or `docs/fact_checking_handoff/`

### Verification

1. Add a single place where pass/fail rollout criteria are listed and checked.
2. Keep the release gate human-readable enough for a product or moderation owner to sign off.

### Exit Criteria

- Switching `PERFECT` on is a release decision backed by evidence.

## Final Rollout Checklist

Before enabling `PERFECT` for real debates, confirm all of the following:

1. Phase 3 async isolation tests are green.
2. Phase 4 policy toggle tests are green.
3. Phase 6 legacy ground-truth tests are green.
4. Phase 9 real Tier-1 connector tests are green.
5. Phase 10 web-only decisiveness tests are green.
6. Phase 11 `PERFECT` wiring tests are green.
7. Phase 13 diagnostics are visible in downstream payloads.
8. Phase 14 evaluation gates meet the agreed thresholds.

If any item above is false, `PERFECT` should still be treated as not ready for broad real-world use.
