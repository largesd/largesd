# Implementation Plan: LSD v1.2 Slice 1

## Goal

Ship the first LSD v1.2 vertical slice with three visible outcomes:

1. A published frame dossier in single-frame mode.
2. Richer immutable snapshot metadata for replay and auditability.
3. Initial decision-dossier outputs on the verdict surface.

## Planned Changes

### Backend

- Add a frame registry module with a versioned public frame dossier.
- Extend snapshot persistence with JSON metadata columns and lightweight migrations.
- Generate replay manifest, deterministic recipe metadata, tamper-evident hash roots, moderation transparency fields, replicate summary, and topic counterfactuals during snapshot creation.
- Expose the new data through snapshot, verdict, and frame endpoints.

### Frontend

- Surface frame mode/version and moderation transparency on the home page.
- Make the snapshot page load live dossier data instead of static placeholders.
- Add remove-topic counterfactuals and evidence-gap summaries to the verdict page.

### Tests

- Assert frame registry and snapshot dossier metadata exist in generated snapshots.
- Assert verdict responses include counterfactual and evidence-gap structures.

## File Targets

| File | Purpose |
| --- | --- |
| `backend/frame_registry.py` | New public frame registry |
| `backend/database.py` | Snapshot schema + migrations |
| `backend/debate_engine_v2.py` | Dossier assembly during snapshot generation |
| `backend/app_v2.py` | API exposure |
| `frontend/index.html` | Home-page snapshot/frame summary |
| `frontend/snapshot.html` | Live snapshot dossier |
| `frontend/verdict.html` | Decision-dossier additions |
| `test_debate_system.py` | Regression coverage |

## Acceptance Goal for This Slice

- The user can generate a snapshot and then see:
  - which frame governed the run
  - how to replay the run at a metadata level
  - which topics are most decisive
  - what topic removal or evidence changes could alter the result
