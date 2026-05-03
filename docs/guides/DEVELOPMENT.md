# Development Guide

## Project structure

- `backend/` — Flask API, debate engine, scoring, governance, email processing
- `frontend/` — HTML/JS/CSS frontend pages
- `skills/fact_checking/` — Fact-checking subsystem
- `tests/` — Test suites (integration, unit, manual)
- `scripts/` — Development workflow and utility scripts
- `docs/` — Architecture, guides, compliance, and archive docs

## Common commands

```bash
# Bootstrap dependencies
make bootstrap

# Run all checks
make test

# Run specific test suites
make unit
make fact

# Start the development server
make server

# Run smoke tests against a temporary server
make smoke

# Run browser acceptance tests
make acceptance

# Lint and format
make lint
make format
```

## Environment

Copy `.env.example` to `.env` and configure your local settings:

- `LLM_PROVIDER` — `mock`, `openai`, `openrouter`, or `openrouter-multi`
- `FACT_CHECK_MODE` — `OFFLINE` or `ONLINE_ALLOWLIST`
- `OPENROUTER_API_KEY` — required when using OpenRouter providers

## Testing

Unit and integration tests are run with pytest:

```bash
python -m pytest
```

Manual API scenarios can be run against a running server:

```bash
python tests/manual/manual_scenarios.py server-check --base-url http://127.0.0.1:5000
```

## Stable entrypoints

- `start_server.py` — primary server startup
- `backend/app.py` — stable Flask app alias
- `backend/debate_engine.py` — stable debate engine alias

These aliases wrap the current v3/v2 implementations and will remain stable even when internal versions change.
