---
name: agentic-workflow
description: Use this skill when the user wants to run the debate_system repo's stateful `wf` development workflow, especially for prompts like `$wf bootstrap`, `$wf resume`, `$wf reject`, `$wf change requirement: ...`, or `$wf review prompts`. Use it instead of the older semi-automatic command flow when coordinating checkpointed development phases.
---

# Agentic Workflow

Use this skill for requests about the repo's `wf` workflow.

This is the Codex-facing wrapper around the repository's platform-independent workflow contract in `WORKFLOW.md`.

## Start Here

1. Read `WORKFLOW.md`.
2. If `workflow_state/state.json` exists, read it plus:
   - `workflow_state/current/next_prompt.md`
   - `workflow_state/current/checkpoint.md`
   - `workflow_state/current/context_files.md`
   - `workflow_state/human_logs/human_prompts.md`
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

- Reject the checkpoint and stay in the same phase:

```bash
./wf reject --human-note "needs revision"
```

- Rewind because requirements changed:

```bash
./wf change-requirement "..."
```

- Log a manual workflow exception:

```bash
./wf manual-override "..."
```

- Review prompt history for workflow improvements:

```bash
./wf review-prompts
```

- Refresh scaffold files without changing phase:

```bash
./wf refresh
```

## Working Style

- Treat one phase as the AI's work between two human checkpoints.
- Stop at the checkpoint instead of rolling into the next phase automatically.
- Keep context small by reading scaffold files first.
- Use the skim-friendly logs in `workflow_state/human_logs/` when checkpoint history matters.
- Use `scripts/dev_workflow.py` only as the execution layer for validation and testing phases.
- If the user asks for a workflow improvement, update both the workflow artifacts and the underlying implementation when needed.
- For prompts that begin with `$wf`, interpret them as workflow commands first, then perform any phase work the command implies.

## Extra Reference

If you need a map of the workflow files, read `references/workflow-files.md`.
