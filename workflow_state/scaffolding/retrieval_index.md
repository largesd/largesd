# Retrieval Index

Generated: 2026-04-11T20:43:54+00:00

Start with scaffold files first. Only open deeper code once the current phase requires it.

| Phase | Read First | Why |
| --- | --- | --- |
| 1. System Design | WORKFLOW.md<br>workflow_state/scaffolding/project_summary.md<br>workflow_state/scaffolding/module_map.md<br>workflow_state/scaffolding/human_checkpoints.md<br>README.md<br>README_v2.md | Define architecture, constraints, success criteria, and the first implementation slice. |
| 2. Module Breakdown | workflow_state/scaffolding/module_map.md<br>workflow_state/scaffolding/retrieval_index.md<br>workflow_state/scaffolding/project_summary.md<br>backend/<br>scripts/<br>test_debate_system.py | Break the work into bounded modules with ownership, dependencies, and validation gates. |
| 3. Module Design | workflow_state/scaffolding/retrieval_index.md<br>workflow_state/scaffolding/open_questions.md<br>workflow_state/phases/02-module-breakdown.md<br>Relevant backend or frontend files for the active module. | Design the next module in enough detail to implement safely with minimal backtracking. |
| 4. Module Implementation | workflow_state/current/next_prompt.md<br>workflow_state/scaffolding/retrieval_index.md<br>scripts/dev_workflow.py<br>Relevant code files for the active module. | Implement the approved module while updating summaries for the next phase. |
| 5. Module Testing | workflow_state/scaffolding/test_surface.md<br>scripts/dev_workflow.py<br>test_debate_system.py<br>test_fact_check_skill.py<br>test_manual.py | Verify the implementation with focused tests, smoke checks, and issue triage. |
| 6. Integration Testing | workflow_state/scaffolding/test_surface.md<br>.github/workflows/ci.yml<br>scripts/dev_workflow.py<br>workflow_state/reviews/workflow_improvements.md | Run the end-to-end validation path, update CI assumptions, and summarize residual risks. |
