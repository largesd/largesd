# Development Workflow

This file now describes the lower-level execution layer that sits under the repo's primary agentic workflow in [WORKFLOW.md](WORKFLOW.md).

This project already had the pieces for a good dev loop:

- `start_server.py`, `start_server_v2.py`, and `start_server_fast.py`
- `test_debate_system.py` for unit and integration-style checks
- `test_fact_check_skill.py` for the fact-checking subsystem
- `manual_scenarios.py` for API scenarios
- `.env.example` and `setup_openrouter.py` for provider setup

The new stateful workflow in `./wf` sits above these commands. This document covers the lower-level executor that phase implementations and CI still rely on.

## Execution Loop

1. Bootstrap once:

```bash
make bootstrap
```

2. Run the default verification suite before or after a change:

```bash
make check
```

3. Start the main development server in mock mode:

```bash
make server
```

4. Run a quick smoke test without keeping a second terminal open:

```bash
make smoke
```

5. Run a deeper end-to-end scenario when you change the debate pipeline:

```bash
make e2e
```

## Command Reference

You can use either `make` or the Python runner directly.

```bash
python3 scripts/dev_workflow.py bootstrap
python3 scripts/dev_workflow.py check
python3 scripts/dev_workflow.py server --version v2
python3 scripts/dev_workflow.py smoke --scenario scenario-ai
python3 scripts/dev_workflow.py manual modulation --base-url http://127.0.0.1:5000
```

## Workflow Decisions

- The workflow defaults to `v2`, because the repo docs describe it as the enhanced implementation.
- Smoke tests use `mock` + `OFFLINE` so they stay cheap and deterministic.
- The runner reads `.env` when present, which makes `setup_openrouter.py` output useful during local development.
- Manual scenarios now accept `--base-url`, so automated checks can use a temporary port without clashing with your normal server.

## CI

The repo now includes [`.github/workflows/ci.yml`](.github/workflows/ci.yml), which mirrors the local loop:

1. Install dependencies
2. Run `python scripts/dev_workflow.py check`
3. Run `python scripts/dev_workflow.py smoke --scenario server-check`

That gives you one consistent workflow locally and in GitHub Actions.
