# Implementation Status

## Current active version

The active application path is v3.

Primary entrypoints:

- `start_server.py`
- `start_server_v3.py`
- `backend/app_v3.py`
- `backend/debate_engine_v2.py`

## Stable areas

- Debate creation
- Post submission
- Modulation
- Snapshot generation
- Published results bundle
- GitHub cached frontend mode
- Email ingestion workflow
- API route coverage (81%)
- CSRF protection and security headers
- Accessibility (0 critical violations)

## Areas under active development

- Fact-checking connectors
- Gold fact-check test set
- Evidence target analysis
- Snapshot diff compatibility
- Frontend/backend schema convergence

## Post-remediation status (Tasks 01–11)

See `docs/current/REMEDIATION_HANDOFF.md` for the full regression report.

- **Unit & integration tests**: passing
- **API route coverage**: 81.14% (threshold: 70%)
- **Security scan (bandit)**: no medium/high issues
- **Accessibility scan**: 0 critical violations
- **Pre-commit**: 2 pre-existing ruff warnings in test files
- **Type checks**: 4 minor annotation gaps in `backend/utils/`
- **UI acceptance tests**: 1/11 passing (AC-7 UI registration); 10 fail on API registration due to CSRF token requirement in `authenticate_browser_user` helper — test infrastructure issue, not a regression
