# 3. Module Design

Workflow goal: Fulfill LSD v1.2 requirements through checkpointed vertical slices, starting with frame transparency, snapshot dossier metadata, and decision dossier outputs.

## Objective

Design the next module in enough detail to implement safely with minimal backtracking.

## Human Checkpoint

Review the design note or prototype before implementation begins.

## Read First

- `workflow_state/scaffolding/retrieval_index.md`
- `workflow_state/scaffolding/open_questions.md`
- `workflow_state/phases/02-module-breakdown.md`
- `Relevant backend or frontend files for the active module.`

## Deliverables

- workflow_state/phases/03-module-design.md
- A concise implementation plan for the active slice.

## Suggested Validation

- Update scaffold summaries if your understanding of the repo changed.
- Prefer the smallest implementation slice that can be reviewed by a human.
- Use `scripts/dev_workflow.py` only when this phase calls for execution or validation.
