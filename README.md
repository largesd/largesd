# Blind Debate Adjudicator (`debate_system`)

A v3 prototype for **identity-blind, auditable debate adjudication**.

The system ingests structured arguments, applies visible moderation rules, builds canonical fact/argument layers, scores each side with multi-judge evaluation, and produces immutable snapshots with audits.

## What This Repository Implements

- **Identity-blind public surfaces** (no likes/profiles/reputation signals in debate views)
- **JWT auth + per-user debate session context**
- **Debate proposal workflow** (user submission → admin accept/reject)
- **Versioned moderation templates** with draft/apply history
- **Snapshot pipeline**:
  - post modulation
  - extraction and canonicalization
  - fact checking (OFFLINE or ONLINE_ALLOWLIST)
  - scoring (Factuality, Reasoning, Coverage, Quality)
  - verdict with confidence interval logic
- **Governance endpoints** (frames, changelog, appeals, judge pool, fairness summaries, emergency override)
- **Snapshot integrity metadata** (`replay_manifest`, input/output hash roots, recipe versions)
- **Optional GitHub publication** of consolidated results JSON
- **Email ingestion daemon** for processing structured email submissions
- **Decision dossier** with frame transparency and audit trail
- **Rate limiting** and structured metrics (`/metrics`)

## Quick Start

### Docker Compose (Recommended)

```bash
# 1. Clone and enter the repo
cd debate_system

# 2. Copy environment template
cp .env.example .env

# 3. Edit .env and set at minimum:
#    SECRET_KEY=$(openssl rand -hex 32)
#    ENV=development
#    LLM_PROVIDER=mock

# 4. Start services
docker-compose up --build -d

# 5. Verify health
curl http://localhost:5000/api/health
```

### Local Development (No Docker)

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m playwright install chromium

# 3. Configure environment
cp .env.example .env
# Edit .env and set at minimum:
#   SECRET_KEY=your-strong-random-key
#   LLM_PROVIDER=mock   # or openrouter with OPENROUTER_API_KEY

# 4. Start server
python start_server.py --host 127.0.0.1 --port 5000

# 5. Verify health
curl http://127.0.0.1:5000/api/health
```

**Expected health response:**

```json
{
  "status": "healthy",
  "version": "3.0",
  "auth_enabled": true,
  "timestamp": "..."
}
```

## Running Tests

```bash
# Run all checks (lint + unit + integration)
make test

# Run specific suites
make unit        # unit tests
make fact        # fact-checking tests
make smoke       # API smoke tests
make acceptance  # browser acceptance tests (requires Playwright)

# Or with pytest directly
python -m pytest tests/unit/ -v
python -m pytest tests/integration/ -v
python -m pytest tests/integration/api/ -v
```

See [`docs/guides/TESTING.md`](docs/guides/TESTING.md) for the full testing guide.

## Architecture At A Glance

```
Participants -> Post Submission (API or Email)
             -> Modulation Engine (versioned template)
             -> Extraction + Canonicalization
             -> Fact Check Layer
             -> Multi-judge Scoring
             -> Immutable Snapshot + Audits
             -> Optional GitHub publish (consolidated_results.json)
             -> Frontend reads live API and/or GitHub cache
```

### Backend Blueprints

The API is decomposed into Flask blueprints for testability:

| Blueprint | Prefix | Responsibility |
|-----------|--------|----------------|
| `auth` | `/api/auth` | JWT registration, login, logout |
| `api` | `/api` | Health, metrics, modulation info |
| `debate` | `/api/debate` | Posts, debates, verdicts |
| `topic` | `/api/debate/topics` | Topic geometry |
| `snapshot` | `/api/debate/snapshot` | Snapshot generation (sync + async) |
| `dossier` | `/api/debate/<id>/dossier` | Decision dossier |
| `proposal` | `/api/debate-proposals` | Debate proposals |
| `governance` | `/api/governance` | Appeals, changelogs, judge pool |
| `admin` | `/api/admin` | Moderation templates, system config |

See [`docs/architecture/BLUEPRINT.md`](docs/architecture/BLUEPRINT.md) for the full architecture.

### Project Layout

- `backend/` — Flask API, debate engine, scoring, governance, email processing
- `frontend/` — HTML/JS/CSS frontend pages
- `skills/fact_checking/` — Fact-checking subsystem
- `tests/` — Test suites (integration, unit, manual)
- `scripts/` — Development workflow and utility scripts
- `docs/` — Architecture, guides, compliance, and security docs

## Auth + Debate Flow (API)

1. Register: `POST /api/auth/register`
2. Login: `POST /api/auth/login`
3. Submit proposal: `POST /api/debate-proposals`
4. Admin accepts proposal: `POST /api/admin/debate-proposals/{proposal_id}/accept`
5. Submit posts: `POST /api/debate/posts`
6. Generate snapshot: `POST /api/debate/snapshot`
7. Inspect results:
   - `GET /api/debate/verdict`
   - `GET /api/debate/topics`
   - `GET /api/debate/audits`
   - `GET /api/debate/evidence-targets`
   - `GET /api/debate/dossier`

## Frontend Operating Modes

### Mode A: Live API mode (backend-first)

Use local API endpoints for authenticated actions and dynamic state.

### Mode B: GitHub cached mode (DataBridge)

Frontend can read debate state from a published JSON file (`consolidated_results.json`) and generate **email-based** submissions via `mailto:`.

Setup page:

- `frontend/setup.html`
- Requires:
  - Raw GitHub URL for consolidated results JSON
  - Destination email for submissions

## Email + GitHub Publication Workflow

The email processor supports asynchronous ingestion:

1. Poll IMAP inbox
2. Parse structured submission body (`BDA Submission v1`)
3. Submit to debate engine
4. Generate snapshot
5. Publish updated consolidated JSON to GitHub

Run:

```bash
python -m backend.email_processor --poll-interval 60
```

Key env vars for this workflow:

- `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`
- `GITHUB_REPO`, `GITHUB_TOKEN`
- Optional: `GITHUB_BRANCH`, `GITHUB_RESULTS_PATH`
- Optional: `PROCESSOR_DEST_EMAIL`, `SENDER_WHITELIST`

## LLM and Fact-Check Configuration

From `.env.example`:

- `LLM_PROVIDER`: `mock`, `openai`, `openrouter`, `openrouter-multi`
- `NUM_JUDGES`: judge count for evaluation replicates
- `FACT_CHECK_MODE`: `OFFLINE` or `ONLINE_ALLOWLIST`
- `OPENAI_API_KEY` (if `openai`)
- `OPENROUTER_API_KEY` (required if provider is `openrouter`)
- `OPENROUTER_MODEL` (required if provider is `openrouter`, e.g. `anthropic/claude-3.5-sonnet`)
- `OPENROUTER_TIMEOUT_SECONDS` (optional, default 60)
- `ALLOW_MOCK_FALLBACK` (optional, default `false`)
- `SITE_URL` / `SITE_NAME` (optional, for OpenRouter rankings)

### OpenRouter Setup

```bash
python setup_openrouter.py
```

This interactive script will prompt for your API key, model, and judge count, then write a `.env` file.

## Async Snapshot Pipeline

Snapshot generation is now asynchronous to avoid HTTP timeouts during long-running evaluations:

1. `POST /api/debate/snapshot` returns immediately with a `job_id`
2. Poll `GET /api/debate/snapshot-jobs/<job_id>` for progress
3. On completion, the job result includes `snapshot_summary`

The background worker is started automatically when the server boots.

## Governance, Dossier, and Appeals

The system includes a governance layer beyond simple scoring:

- **Decision dossier** (`/api/debate/<id>/dossier`): frame transparency, scoring rationale, and audit trail
- **Frame petitions** (`/api/debate/<id>/frame-petitions`): users can petition for frame changes; admins can accept/reject
- **Emergency override** (`/api/governance/emergency-override`): admin-triggered override with published reasoning
- **Judge pool governance** (`/api/governance/judge-pool`): composition, rotation policy, calibration protocol, conflict-of-interest checks
- **Appeals** (`/api/governance/appeals`): structured appeal submission and status tracking
- **Fairness summaries** and **incident logging** for auditability

## Admin Access Policy

`ADMIN_ACCESS_MODE` controls admin endpoints:

- `open`: no auth checks
- `authenticated`: any logged-in user with `is_admin=True`
- `restricted`: only users in `ADMIN_USER_EMAILS` / `ADMIN_USER_IDS`

## Rate Limiting and Metrics

- **Rate limiting** is enforced via `flask-limiter` on key endpoints.
- **Metrics** are available at `GET /metrics` as structured JSON for monitoring.
- **Security headers** (including HSTS in production) are applied automatically.
- Startup env validation fails loudly in production if required variables are missing.

## Database Migrations

Alembic is configured for schema migrations:

```bash
alembic upgrade head          # apply all migrations
alembic revision --autogenerate -m "description"  # create new migration
```

Migrations support both PostgreSQL and SQLite backends.

## Core Scoring Concepts

Per topic-side:

- `F`: factuality from canonical fact `p_true`
- `Reason`: median judge reasoning score
- `Cov`: how well arguments address opposing leverage
- `Q = (F * Reason * Cov)^(1/3)`

Debate-level margin:

- `D = Overall_FOR - Overall_AGAINST`
- Verdict is driven by confidence interval behavior and replicate stability.

## Contributing

We welcome contributions! Please follow these guidelines:

### Setup

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

### Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

Hooks run automatically on every commit. To check all files manually:

```bash
pre-commit run --all-files
```

### Conventional Commits

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

### Branch Naming

Use prefixes that match the commit type:

- `feat/...`
- `fix/...`
- `docs/...`
- `test/...`
- `refactor/...`
- `chore/...`

### Pull Request Checklist

Before opening a PR:

- [ ] All tests pass: `make test`
- [ ] Lint passes: `pre-commit run --all-files`
- [ ] Type checks pass: `mypy backend/pipeline/ backend/routes/ backend/utils/`
- [ ] Security scan passes: `bandit -r backend/`
- [ ] Documentation updated if behavior changed
- [ ] Commit messages follow Conventional Commits

### Secrets

Never commit `.env`, API keys, database files, or personal credentials.

## Documentation

- Full docs index: [`docs/README.md`](docs/README.md)
- Architecture: [`docs/architecture/`](docs/architecture/) — blueprints, design system, product spec
- Security: [`docs/security/`](docs/security/) — headers, auth, CSRF
- Workflow: [`docs/workflow/`](docs/workflow/) — workflow contracts and development workflows
- Guides: [`docs/guides/`](docs/guides/) — testing, deployment, database migrations, OpenRouter setup, privacy, WCAG audit
- Current status: [`docs/current/`](docs/current/) — implementation status
- Compliance: [`docs/compliance/`](docs/compliance/) — formula traceability matrix, LSD v1.2 compliance reports and changelog
- Requirements: [`docs/requirements/`](docs/requirements/) — LSD requirements and change requests
- Schema: [`docs/schema/`](docs/schema/) — email submission schema
- Archive: [`docs/archive/`](docs/archive/) — previous README versions
- V3 migration guide: [`docs/guides/V3_MIGRATION_GUIDE.md`](docs/guides/V3_MIGRATION_GUIDE.md)

## Notes

- `start_server.py` is the recommended primary startup command. It delegates to `start_server_v3.py` internally.
- Current stable backend modules: `backend/app.py` and `backend/debate_engine.py` (wrap v3/v2 internals).
- Database defaults to `data/debate_system.db`.
- Passwords are hashed with **bcrypt** (not PBKDF2).
- For deterministic local development, `LLM_PROVIDER=mock` and `FACT_CHECK_MODE=OFFLINE` are recommended.
- The backend has deeper functionality than the UI currently exposes — see governance and judge-pool endpoints for advanced features.
