# Contributing

## Local setup

```bash
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

## Run tests

```bash
python scripts/dev_workflow.py check
```

or:

```bash
make test
```

## Run server

```bash
python start_server.py --host 127.0.0.1 --port 5000
```

## Branch naming

Use:

- `fix/...`
- `feat/...`
- `docs/...`
- `chore/...`

## Secrets

Never commit `.env`, API keys, database files, or personal credentials.
