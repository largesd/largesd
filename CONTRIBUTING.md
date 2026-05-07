# Contributing

## Local Setup

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

## Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

Hooks run automatically on every commit. To check all files manually:

```bash
pre-commit run --all-files
```

## Run Tests

```bash
make test       # all checks (lint + unit + integration)
make unit       # unit tests only
make fact       # fact-checking tests
make smoke      # API smoke tests
make acceptance # browser acceptance tests
```

## Conventional Commits

Use [Conventional Commits](https://www.conventionalcommits.org/) for all commit messages:

```
feat: add user preference caching
fix: resolve race condition in job queue
docs: update deployment guide with SSL examples
test: add integration tests for proposal blueprint
refactor: extract validation logic into shared helper
chore: bump ruff to v0.15.12
```

Common types:
- `feat` — new feature
- `fix` — bug fix
- `docs` — documentation only
- `test` — adding or correcting tests
- `refactor` — code change that neither fixes a bug nor adds a feature
- `chore` — maintenance tasks (deps, config, etc.)

## Branch Naming

Use prefixes that match the commit type:

- `feat/...`
- `fix/...`
- `docs/...`
- `test/...`
- `refactor/...`
- `chore/...`

## Pull Request Checklist

Before opening a PR:

- [ ] All tests pass: `make test`
- [ ] Lint passes: `pre-commit run --all-files`
- [ ] Type checks pass: `mypy backend/pipeline/ backend/routes/ backend/utils/`
- [ ] Security scan passes: `bandit -r backend/`
- [ ] Documentation updated if behavior changed
- [ ] Commit messages follow Conventional Commits

## Secrets

Never commit `.env`, API keys, database files, or personal credentials.
