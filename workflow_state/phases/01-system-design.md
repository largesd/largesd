# 1. System Design

Workflow goal: Fulfill LSD v1.2 requirements through checkpointed vertical slices, starting with frame transparency, snapshot dossier metadata, and decision dossier outputs.

## Objective

Define architecture, constraints, success criteria, and the first implementation slice.

## Human Checkpoint

Review the system design, validate scope, and approve the module split.

## Read First

- `WORKFLOW.md`
- `workflow_state/scaffolding/project_summary.md`
- `workflow_state/scaffolding/module_map.md`
- `workflow_state/scaffolding/human_checkpoints.md`
- `README.md`
- `README_v2.md`

## Deliverables

- workflow_state/phases/01-system-design.md
- Updated open questions when scope is unclear.

## Suggested Validation

- Update scaffold summaries if your understanding of the repo changed.
- Prefer the smallest implementation slice that can be reviewed by a human.
- Use `scripts/dev_workflow.py` only when this phase calls for execution or validation.
