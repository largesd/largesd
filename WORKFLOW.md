# Agentic Workflow

This repository uses a stateful human-AI workflow for development work.

The workflow is generic:

1. Human defines or updates the goal.
2. AI works within one bounded phase.
3. Human reviews the phase output at a checkpoint.
4. The workflow either resumes to the next phase or rewinds if requirements changed.

One workflow phase is the AI's work between two human checkpoints.

## Roles

### Human

- Sets the goal and changes requirements when needed.
- Reviews outputs at checkpoints.
- Approves moving to the next phase.
- Uses the workflow artifacts instead of re-explaining the whole project each time.

### AI

- Works only on the current phase.
- Uses scaffold summaries before reading large amounts of code.
- Produces the next-step prompt and checkpoint artifacts.
- Logs human prompts and requirement changes.
- Reviews prompt history to suggest workflow improvements.

## Canonical Phases

1. System design
2. Module breakdown
3. Module design
4. Module implementation
5. Module testing
6. Integration testing

The workflow is iterative. A requirement change can rewind the workflow to system design or another earlier checkpoint before work continues.

## Commands

The core engine is cross-platform Python:

```bash
python3 scripts/agentic_workflow.py bootstrap --goal "..."
python3 scripts/agentic_workflow.py status
python3 scripts/agentic_workflow.py resume --human-note "approved"
python3 scripts/agentic_workflow.py change-requirement "..."
python3 scripts/agentic_workflow.py review-prompts
```

For convenience on Unix-like systems, this repo also provides:

```bash
./wf bootstrap --goal "..."
./wf status
./wf resume --human-note "approved"
./wf change-requirement "..."
./wf review-prompts
```

## Bootstrap

`bootstrap` creates the workflow scaffolding in `workflow_state/`.

That scaffolding includes:

- `state.json`: workflow phase and status
- `prompt_log.jsonl`: logged human prompts and approvals
- `scaffolding/`: project summaries for low-context retrieval
- `phases/`: one file per workflow phase
- `current/`: the current prompt, checkpoint, and context-file list
- `reviews/`: workflow-improvement reports

## Resume

`resume` moves from the current phase to the next one.

It should be used after a human checkpoint, usually with a note like:

```bash
./wf resume --human-note "system design approved"
```

## Requirement Changes

If the requirements change, log them explicitly:

```bash
./wf change-requirement "Support a second deployment target"
```

This rewinds the workflow to replanning instead of silently continuing with stale assumptions.

## Prompt Review

`review-prompts` reads `prompt_log.jsonl` and creates a workflow-improvement report in `workflow_state/reviews/`.

Use it when the team wants to tighten checkpoints, reduce ambiguity, or improve the scaffold files.

## Relationship To The Low-Level Executor

This workflow replaces the old semi-automatic flow as the primary development process.

The lower-level executor still exists:

- `scripts/dev_workflow.py`
- `Makefile`
- `.github/workflows/ci.yml`

Those remain the execution and verification layer used during implementation and testing phases.
