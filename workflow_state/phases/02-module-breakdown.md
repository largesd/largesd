# 2. Module Breakdown

Workflow goal: Fulfill LSD v1.2 requirements through checkpointed vertical slices, starting with frame transparency, snapshot dossier metadata, and decision dossier outputs.

## Objective

Break the work into bounded modules with ownership, dependencies, and validation gates.

## Human Checkpoint

Approve the module boundaries and the order of execution.

## Read First

- `workflow_state/scaffolding/module_map.md`
- `workflow_state/scaffolding/retrieval_index.md`
- `workflow_state/scaffolding/project_summary.md`
- `backend/`
- `scripts/`
- `test_debate_system.py`

## Deliverables

- workflow_state/phases/02-module-breakdown.md
- Updated retrieval index mapping modules to files.

## Suggested Validation

- Update scaffold summaries if your understanding of the repo changed.
- Prefer the smallest implementation slice that can be reviewed by a human.
- Use `scripts/dev_workflow.py` only when this phase calls for execution or validation.
