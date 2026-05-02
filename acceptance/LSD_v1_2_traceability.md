# LSD v1.2 Traceability

Source document: `/Users/jonathanleung/Documents/C++/LSD req.txt`

Implementation run: `2026-04-28`, covering Phase 2 and Phases 4-10 from `LSD_v1_2_gap_closure_plan.txt`.

## Final Status

| Criterion | Status | Evidence |
| --- | --- | --- |
| `LSD-UI-01` User-facing blindness | Deferred | Phase 3 is outside this run; tracked in `acceptance/lsd_v1_2_criteria.json`. |
| `LSD-UI-02` Moderation metadata | Pass | `backend/debate_engine_v2.py`, `backend/database.py`, `frontend/snapshot.html`, `frontend/admin.html` |
| `LSD-UI-03` Immutable snapshot dossier | Deferred | Phases 0.5 and 1 are outside this run; existing hash/replay fields remain visible in `frontend/snapshot.html`. |
| `LSD-UI-04` Frame transparency | Pass | `backend/app_v3.py`, `backend/database.py`, `frontend/governance.html`, `frontend/frame-dossier.html` |
| `LSD-UI-05` Topic diagnostics | Pass | `backend/scoring_engine.py`, `backend/lsd_v1_2.py`, `frontend/topics.html`, `frontend/audits.html` |
| `LSD-UI-06` AU completeness proxy | Pass | `backend/extraction.py`, `backend/selection_engine.py`, `frontend/audits.html`, `test_lsd_v1_2_contracts.py` |
| `LSD-UI-07` Integrity and selection transparency | Pass | `backend/debate_engine_v2.py`, `backend/lsd_v1_2.py`, `frontend/audits.html` |
| `LSD-UI-08` Decision dossier outputs | Pass | `backend/app_v3.py`, `backend/debate_engine_v2.py`, `frontend/verdict.html`, `frontend/dossier.html` |
| `LSD-UI-09` Replicates and audits | Pass | `backend/debate_engine_v2.py`, `backend/app_v3.py`, `frontend/audits.html`, `test_lsd_v1_2_contracts.py` |
| `LSD-UI-10` Governance and incident hooks | Pass | `backend/governance.py`, `backend/app_v3.py`, `frontend/governance.html`, `frontend/dossier.html` |

## Formula Traceability

| Formula | Code path | Test |
| --- | --- | --- |
| Borderline rate and suppression `k=5` | `backend/lsd_v1_2.py`, `backend/debate_engine_v2.py` | API contract checks in `test_lsd_v1_2_contracts.py` |
| Selection score `S_i = w1*centrality + w2*log(1+support) + w3*quality` | `backend/selection_engine.py`, `backend/lsd_v1_2.py` | `test_selection_score_decomposition_fixture` |
| P95 centrality cap | `backend/selection_engine.py` | `test_centrality_cap_fixture` |
| Topic relevance sqrt/log | `backend/scoring_engine.py`, `backend/lsd_v1_2.py` | `test_relevance_sqrt_and_log_fixtures` |
| Q geomean and arithmetic sensitivity | `backend/scoring_engine.py`, `backend/lsd_v1_2.py` | `test_q_geomean_arith_and_drop_component_fixture` |
| D distribution and confidence | `backend/scoring_engine.py` | `test_verdict_distribution_confidence_fixture` |
| Perfect checker discrete `p` outputs | `skills/fact_checking/skill.py` | `test_perfect_checker_discrete_outputs` |

## Newly Implemented (2026-04-30)

| Criterion | Status | Evidence |
| --- | --- | --- |
| `LSD-§14` Normative Symmetry Tests | Pass | `backend/scoring_engine.py::run_symmetry_tests`, `backend/debate_engine_v2.py` |
| `LSD-§15.1` Rebuttal-Type Tagging (Judge Coverage) | Pass | `backend/llm_client.py::judge_coverage`, `backend/scoring_engine.py::_aggregate_rebuttal_types` |
| `LSD-§18` Replicates with Extraction Reruns | Pass | `backend/scoring_engine.py::run_replicates` (extraction_reruns=2, bootstrap=True) |
| `LSD-§20.1` Judge Pool Governance Persistence | Pass | `backend/governance.py` (composition, rotation, COI log, calibration), `backend/app_v3.py` |

## Deferred Scope

Phases 0, 0.5, 1, and 3 are explicitly outside this implementation run. Their criteria are marked `deferred` with rationale and target version in `acceptance/lsd_v1_2_criteria.json`.
