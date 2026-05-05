# Project Summary

Generated: 2026-04-11T20:43:54+00:00
Workflow goal: Fulfill LSD v1.2 requirements through checkpointed vertical slices, starting with frame transparency, snapshot dossier metadata, and decision dossier outputs.

## Repo Shape

| Path | Purpose |
| --- | --- |
| backend | Core API, engines, storage, and debate logic. |
| frontend | Static product interface and admin pages. |
| skills | Domain-specific subsystems and the Codex workflow skill bundle. |
| scripts | Automation entry points and workflow runners. |
| data | SQLite persistence and local runtime state. |
| .github/workflows | CI automation. |

## Existing Execution Surfaces

- `scripts/dev_workflow.py`: low-level executor for setup, tests, server startup, and smoke checks.
- `Makefile`: convenience wrappers around the low-level executor.
- `start_server.py`, `start_server_v2.py`, `start_server_fast.py`: app entry points.
- `test_debate_system.py`, `test_fact_check_skill.py`, `test_manual.py`: verification surfaces.

## How The Agentic Layer Uses Them

- The agentic workflow handles phase state, checkpoints, prompt logs, and scaffold files.
- The low-level executor remains the tool used during testing and implementation phases.
- Human review happens between workflow phases instead of only at the end.

## Recommended Starting Files

- `WORKFLOW.md`
- `workflow_state/scaffolding/module_map.md`
- `workflow_state/scaffolding/retrieval_index.md`
- `README.md`
- `README_v2.md`
