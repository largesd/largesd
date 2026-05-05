# Test Surface

Generated: 2026-04-11T20:43:54+00:00

## Primary Commands

- `python3 scripts/dev_workflow.py check`: run the main Python verification suites.
- `python3 scripts/dev_workflow.py smoke --scenario server-check`: temporary health-check server run.
- `python3 scripts/dev_workflow.py smoke --scenario scenario-ai`: temporary end-to-end scenario run.
- `python3 test_manual.py scenario-ai --base-url http://127.0.0.1:PORT`: deeper manual API scenario.

## Coverage Areas

| File | Coverage |
| --- | --- |
| test_debate_system.py | Core system behavior, scoring, pipeline, audits, and identity-blindness checks. |
| test_fact_check_skill.py | Fact checking logic, caching, queueing, audit logging, and MSD-aligned requirements. |
| test_manual.py | API-level scenarios, moderation behavior, snapshot generation, verdict retrieval, and evidence endpoints. |
| .github/workflows/ci.yml | Runs `check` and a smoke health-check flow in CI. |

## Validation Rule

- Use focused module tests during implementation.
- Use the smoke flow before claiming the workflow or server path works end to end.
- Use integration testing after module-level approval.
