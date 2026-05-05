# Human Checkpoints

Generated: 2026-04-11T20:43:54+00:00

Every workflow phase ends at a human checkpoint. The AI should not silently skip these.

| Phase | Human Review Required |
| --- | --- |
| 1. System Design | Review the system design, validate scope, and approve the module split. |
| 2. Module Breakdown | Approve the module boundaries and the order of execution. |
| 3. Module Design | Review the design note or prototype before implementation begins. |
| 4. Module Implementation | Review the prototype or patch before broad testing or expansion. |
| 5. Module Testing | Review test results, failures, and risk before broad integration. |
| 6. Integration Testing | Approve the integrated result or request another iteration. |

Suggested approval language:

- `./wf resume --human-note "system design approved"`
- `./wf resume --human-note "module split approved"`
- `./wf change-requirement "..."` when scope changes
