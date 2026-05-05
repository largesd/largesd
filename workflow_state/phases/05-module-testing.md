# 5. Module Testing

Workflow goal: Fulfill LSD v1.2 requirements through checkpointed vertical slices, starting with frame transparency, snapshot dossier metadata, and decision dossier outputs.

## Objective

Verify the implementation with focused tests, smoke checks, and issue triage.

## Human Checkpoint

Review test results, failures, and risk before broad integration.

## Read First

- `workflow_state/scaffolding/test_surface.md`
- `scripts/dev_workflow.py`
- `test_debate_system.py`
- `test_fact_check_skill.py`
- `test_manual.py`

## Deliverables

- workflow_state/phases/05-module-testing.md
- Focused verification notes and follow-up fixes.

## Suggested Validation

- Update scaffold summaries if your understanding of the repo changed.
- Prefer the smallest implementation slice that can be reviewed by a human.
- Use `scripts/dev_workflow.py` only when this phase calls for execution or validation.
