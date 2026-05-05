# Next Agent Prompt

Workflow goal: Fulfill LSD v1.2 requirements through checkpointed vertical slices, starting with frame transparency, snapshot dossier metadata, and decision dossier outputs.
Current phase: Module Design

Use the current phase brief and scaffold files before opening broad code context.

## Read First

- `workflow_state/phases/03-module-design.md`
- `workflow_state/scaffolding/project_summary.md`
- `workflow_state/scaffolding/retrieval_index.md`
- `workflow_state/scaffolding/open_questions.md`

## Suggested Prompt

```text
You are working on phase `module-design` of the repo's agentic workflow.
Goal: Fulfill LSD v1.2 requirements through checkpointed vertical slices, starting with frame transparency, snapshot dossier metadata, and decision dossier outputs.
Start from the scaffold files instead of reading the whole repo.
Read `workflow_state/phases/03-module-design.md` and the listed scaffold files first.
Complete only the work for this phase, update the relevant phase file with results,
and stop at the human checkpoint instead of continuing automatically.
Log the user's latest workflow-related instruction first with `./wf log-human-prompt --dedupe "..."`.
```

## Reminder

- Human checkpoint after this phase: Review the design note or prototype before implementation begins.
- If the checkpoint is rejected, use `./wf reject --human-note "..."` and revise the same phase.
