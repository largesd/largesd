# LSD v1.2 Compliance Report

Source version: `LSD v1.2`

## Summary

- `deferred`: 2
- `pass`: 8

## Criteria

- `LSD-UI-01` User-facing blindness (2.1): **deferred**. Evidence: `acceptance/lsd_v1_2_criteria.json`. Deferral: Out of scope for this implementation run: Phase 3 user-facing blindness hardening remains deferred to v1.3.
- `LSD-UI-02` Visible moderation metadata (3): **pass**. Evidence: `backend/debate_engine_v2.py`, `backend/database.py`, `frontend/snapshot.html`, `frontend/admin.html`, `test_lsd_v1_2_contracts.py`.
- `LSD-UI-03` Immutable snapshot dossier (4): **deferred**. Evidence: `backend/debate_engine_v2.py`, `frontend/snapshot.html`. Deferral: Out of scope for this implementation run: Phases 0.5 and 1 snapshot immutability/replay expansion are tracked separately.
- `LSD-UI-04` Frame transparency (5): **pass**. Evidence: `backend/app_v3.py`, `backend/database.py`, `frontend/governance.html`, `frontend/frame-dossier.html`.
- `LSD-UI-05` Topic diagnostics (6): **pass**. Evidence: `backend/scoring_engine.py`, `backend/lsd_v1_2.py`, `frontend/topics.html`, `frontend/audits.html`.
- `LSD-UI-06` AU completeness proxy (8.1): **pass**. Evidence: `backend/extraction.py`, `backend/selection_engine.py`, `frontend/audits.html`, `test_lsd_v1_2_contracts.py`.
- `LSD-UI-07` Integrity and selection transparency (10 and 11): **pass**. Evidence: `backend/lsd_v1_2.py`, `backend/debate_engine_v2.py`, `frontend/audits.html`, `test_lsd_v1_2_contracts.py`.
- `LSD-UI-08` Decision dossier outputs (13 to 17): **pass**. Evidence: `backend/app_v3.py`, `backend/debate_engine_v2.py`, `frontend/verdict.html`, `frontend/dossier.html`, `test_lsd_v1_2_contracts.py`.
- `LSD-UI-09` Replicates and audits (18 and 19): **pass**. Evidence: `backend/debate_engine_v2.py`, `backend/app_v3.py`, `frontend/audits.html`, `test_lsd_v1_2_contracts.py`.
- `LSD-UI-10` Governance and incident hooks (20): **pass**. Evidence: `backend/governance.py`, `backend/app_v3.py`, `frontend/governance.html`, `frontend/dossier.html`.

## Action Required

No partial or missing criteria remain without a deferral note.
