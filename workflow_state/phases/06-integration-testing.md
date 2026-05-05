# 6. Integration Testing

Workflow goal: Fulfill LSD v1.2 requirements through checkpointed vertical slices, starting with frame transparency, snapshot dossier metadata, and decision dossier outputs.

## Objective

Run the end-to-end validation path, update CI assumptions, and summarize residual risks.

## Human Checkpoint

Approve the integrated result or request another iteration.

## Read First

- `workflow_state/scaffolding/test_surface.md`
- `.github/workflows/ci.yml`
- `scripts/dev_workflow.py`
- `workflow_state/reviews/workflow_improvements.md`

## Deliverables

- workflow_state/phases/06-integration-testing.md
- Final summary of validation status and residual risks.

## Suggested Validation

- Update scaffold summaries if your understanding of the repo changed.
- Prefer the smallest implementation slice that can be reviewed by a human.
- Use `scripts/dev_workflow.py` only when this phase calls for execution or validation.
