# Agentic Workflow

This repository uses a stateful human-AI workflow for development work.

The workflow is generic and platform-independent. It defines how work progresses between human checkpoints, how state is persisted, and how context is reduced through scaffolding artifacts.

Platform-specific wrappers, including Codex skill instructions, should preserve these workflow semantics.

## Core Model

The workflow proceeds as follows:

1. Human defines or updates the goal.
2. AI works within one bounded phase.
3. AI produces the required artifacts for that phase.
4. Human reviews the output at a checkpoint.
5. The workflow either advances, stays in the same phase for revision, or rewinds because requirements changed.

One workflow phase is the AI's work between two human checkpoints.

The workflow is iterative, not purely linear.

## Roles

### Human

- defines the project goal
- changes requirements when needed
- reviews outputs at checkpoints
- approves or rejects phase completion
- makes final product and design decisions
- uses workflow artifacts instead of re-explaining the whole repository every time

### AI

- works only on the current phase
- consults scaffold summaries before broad repository reads
- generates the required artifacts for the current phase
- generates the next-step prompt for the following phase
- logs all human prompts and workflow interventions on disk
- stops at defined checkpoints instead of silently continuing across phases
- reviews prompt history to suggest workflow improvements

## Workflow Invariants

The following rules should always hold:

- Only one workflow phase may be active at a time.
- AI may only act within the current active phase.
- No phase transition may occur without a workflow state update.
- No phase may be considered complete without producing its required artifacts.
- No advancement may occur without an explicit human checkpoint.
- Requirement changes must be logged explicitly and trigger replanning.
- AI should consult scaffold summaries before opening broad code context.
- Human interventions should be logged in both machine-readable and skim-friendly formats.

## Canonical Phases

1. System design
2. Module breakdown
3. Module design
4. Module implementation
5. Module testing
6. Integration testing

Projects may add sub-phases, but should preserve the checkpointed structure.

## Commands

The core engine is cross-platform Python:

```bash
python3 scripts/agentic_workflow.py bootstrap --goal "..."
python3 scripts/agentic_workflow.py status
python3 scripts/agentic_workflow.py refresh
python3 scripts/agentic_workflow.py log-human-prompt "..."
python3 scripts/agentic_workflow.py resume --human-note "approved"
python3 scripts/agentic_workflow.py reject --human-note "needs revision"
python3 scripts/agentic_workflow.py change-requirement "..."
python3 scripts/agentic_workflow.py manual-override "..."
python3 scripts/agentic_workflow.py review-prompts
```

For convenience on Unix-like systems, the repo also provides:

```bash
./wf bootstrap --goal "..."
./wf status
./wf refresh
./wf log-human-prompt "..."
./wf resume --human-note "approved"
./wf reject --human-note "needs revision"
./wf change-requirement "..."
./wf manual-override "..."
./wf review-prompts
```

## Bootstrap

`bootstrap` creates the workflow scaffolding in `workflow_state/`.

That scaffolding includes:

- `state.json`: canonical workflow phase and status
- `prompt_log.jsonl`: machine-readable event history
- `human_logs/`: skim-friendly logs for prompts, approvals, rejections, requirement changes, and manual overrides
- `scaffolding/`: project summaries for low-context retrieval
- `phases/`: one file per workflow phase
- `current/`: the current prompt, checkpoint, and context-file list
- `reviews/`: workflow-improvement reports

Bootstrap is the right time to set a concrete project goal, for example:

```bash
./wf bootstrap --goal "Ship the next debate_system slice through explicit human checkpoints"
```

## Resume, Reject, And Rewind

Use `resume` only after a human approves the current phase:

```bash
./wf resume --human-note "system design approved"
```

If the human wants revisions but not a full rewind, reject the checkpoint and stay in the same phase:

```bash
./wf reject --human-note "module split is too broad; revise the boundaries"
```

If the requirements changed, log them explicitly and rewind to replanning:

```bash
./wf change-requirement "Support a second deployment target"
```

## Prompt Logging

When the workflow is active, log the human's new instruction before branching into new work:

```bash
./wf log-human-prompt "asked to narrow the implementation slice to the fact-checking queue"
```

This keeps a faithful prompt history in both `prompt_log.jsonl` and `workflow_state/human_logs/`.

## Prompt Review

`review-prompts` reads `prompt_log.jsonl` and creates a workflow-improvement report in `workflow_state/reviews/`.

Use it when the team wants to tighten checkpoints, reduce ambiguity, or improve the scaffold files.

## Relationship To The Low-Level Executor

This workflow is the planning and checkpoint layer.

The lower-level executor still exists:

- `scripts/dev_workflow.py`
- `Makefile`
- `.github/workflows/ci.yml`

Those remain the execution and verification surfaces used during implementation and testing phases.
