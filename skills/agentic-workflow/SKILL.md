---
name: agentic-workflow
description: Use this skill when the user wants to bootstrap, resume, inspect, or change the repo's stateful development workflow with human checkpoints, prompt logging, scaffold summaries, or workflow-review artifacts. This skill is for the debate_system repo's agentic `wf` workflow and should be used instead of the older semi-automatic command flow when coordinating development phases.
---

# Agentic Workflow

Use this skill for requests about the repo's `wf` workflow.

## Start Here

1. Read `WORKFLOW.md`.
2. If `workflow_state/state.json` exists, read it plus:
   - `workflow_state/current/next_prompt.md`
   - `workflow_state/current/checkpoint.md`
   - `workflow_state/current/context_files.md`
3. Prefer scaffold files in `workflow_state/scaffolding/` before opening broad code context.

## Prompt Logging

Whenever this workflow is active, log the user's instruction with:

```bash
./wf log-human-prompt "short summary of the user's latest instruction"
```

Use a short faithful summary, not a rewritten plan.

## Commands

- Initialize workflow:

```bash
./wf bootstrap --goal "..."
```

- Inspect current phase:

```bash
./wf status
```

- Advance after a human checkpoint:

```bash
./wf resume --human-note "approved"
```

- Rewind because requirements changed:

```bash
./wf change-requirement "..."
```

- Review prompt history for workflow improvements:

```bash
./wf review-prompts
```

## Working Style

- Treat one phase as the AI's work between two human checkpoints.
- Stop at the checkpoint instead of rolling into the next phase automatically.
- Keep context small by reading scaffold files first.
- Use `scripts/dev_workflow.py` only as the execution layer for validation and testing phases.
- If the user asks for a workflow improvement, update both the workflow artifacts and the underlying implementation when needed.

## Extra Reference

If you need a map of the workflow files, read `references/workflow-files.md`.
