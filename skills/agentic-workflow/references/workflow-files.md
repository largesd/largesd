# Workflow Files

Use this reference when the `agentic-workflow` skill triggers and you need to know which repo files matter.

## Primary Files

- `docs/workflow/WORKFLOW.md`: generic workflow contract and command semantics
- `scripts/agentic_workflow.py`: stateful workflow engine
- `wf`: convenience launcher
- `workflow_state/state.json`: current workflow state after bootstrap
- `workflow_state/current/next_prompt.md`: next bounded AI task
- `workflow_state/current/checkpoint.md`: human approval checkpoint
- `workflow_state/scaffolding/*.md`: low-context summaries

## Execution Layer

- `scripts/dev_workflow.py`: low-level setup, check, server, and smoke runner
- `Makefile`: convenience wrappers
- `.github/workflows/ci.yml`: CI verification path

## Verification Files

- `test_debate_system.py`
- `test_fact_check_skill.py`
- `test_manual.py`

## Repo Hotspots

- `backend/app_v2.py`
- `backend/debate_engine_v2.py`
- `backend/database.py`
- `backend/modulation.py`
- `backend/scoring_engine.py`
- `skills/fact_checking/`
