# Formula Traceability Matrix

| Formula | Version | Code path | API/UI field | Test case |
| --- | --- | --- | --- | --- |
| Borderline rate | `lsd-3-v1.2.0` | `backend/lsd_v1_2.py`, `backend/debate_engine_v2.py` | `/api/debate/snapshot.borderline_rate`, `frontend/snapshot.html` | Route contract in `test_lsd_v1_2_contracts.py` |
| Small-count suppression | `lsd-3-v1.2.0` | `backend/lsd_v1_2.py`, `backend/database.py` | `/api/debate/snapshot.suppression_policy`, `frontend/admin.html` | Route contract in `test_lsd_v1_2_contracts.py` |
| Centrality cap | `lsd-11-v1.2.0` | `backend/selection_engine.py` | `/api/debate/audits.centrality_cap_effect`, `frontend/audits.html` | `test_centrality_cap_fixture` |
| Selection score | `lsd-11-v1.2.0` | `backend/selection_engine.py`, `backend/lsd_v1_2.py` | `/api/debate/audits.selection_transparency`, `frontend/dossier.html` | `test_selection_score_decomposition_fixture` |
| Relevance sqrt/log | `lsd-12-v1.2.0` | `backend/scoring_engine.py`, `backend/lsd_v1_2.py` | `/api/debate/topics.relevance_formula_mode`, `frontend/topics.html` | `test_relevance_sqrt_and_log_fixtures` |
| Q geomean/arithmetic | `lsd-16-v1.2.0` | `backend/scoring_engine.py`, `backend/lsd_v1_2.py` | `/api/debate/verdict.formula_metadata`, `frontend/verdict.html` | `test_q_geomean_arith_and_drop_component_fixture` |
| D distribution/confidence | `lsd-16-v1.2.0` | `backend/scoring_engine.py` | `/api/debate/verdict.d_distribution`, `frontend/verdict.html` | `test_verdict_distribution_confidence_fixture` |
| Insufficiency sensitivity | `lsd-13.1-v1.2.0` | `backend/lsd_v1_2.py`, `backend/debate_engine_v2.py` | `/api/debate/decision-dossier.insufficiency_sensitivity`, `frontend/dossier.html` | Bounded through dossier contract and helper tests |
| Perfect checker policy | `lsd-13-policy-v1.2.0` | `skills/fact_checking/skill.py` | `/api/debate/verdict.factuality`, `/api/debate/decision-dossier.evidence_gaps` | `test_perfect_checker_discrete_outputs` |
