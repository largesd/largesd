# Blind Debate Adjudicator (`debate_system`)

`debate_system` is a v3 prototype for identity-blind, auditable debate adjudication.

The application lets users create or propose debates, submit structured FOR/AGAINST argument units, run a moderation and adjudication pipeline, and inspect the resulting snapshots, verdicts, audits, evidence targets, appeals, and governance records without exposing identity or popularity signals in the debate surfaces.

## Current State

The active application path is v3.

Primary entrypoints:

- `start_server.py` - preferred server launcher; delegates to `start_server_v3.py`
- `start_server_v3.py` - configurable local Flask launcher
- `backend/app_v3.py` - Flask app factory and blueprint registration
- `backend/debate_engine_v2.py` - current debate engine implementation

Stable compatibility aliases:

- `backend/app.py` re-exports the v3 Flask app, database, engine, queue, and worker
- `backend/debate_engine.py` re-exports `DebateEngineV2`

Latest implementation status lives in [`docs/current/IMPLEMENTATION_STATUS.md`](docs/current/IMPLEMENTATION_STATUS.md). The most recent handoff records unit and integration tests passing, 81.14 percent API route coverage, no medium/high Bandit findings, and 0 critical accessibility violations. Remaining known gaps are listed in [Known Gaps](#known-gaps).

## What It Implements

- JWT authentication with CSRF protection for mutating API requests
- Per-user, multi-debate session context instead of global debate state
- Debate proposal queue with admin accept/reject flow
- Identity-blind debate views with no likes, reputation, or profile signals
- Versioned moderation templates with draft, apply, and history APIs
- Structured post submission with facts, inference, counter-arguments, side, and topic
- Snapshot pipeline for extraction, canonicalization, fact checking, scoring, audit metadata, and verdict generation
- SQLite-backed async job queue for snapshots and snapshot verification
- Decision dossier, snapshot history, snapshot diffs, evidence targets, and audit bundle export
- Governance surfaces for frames, frame petitions, appeals, judge pool policy, incidents, fairness audits, and emergency overrides
- Optional GitHub publication of consolidated debate results JSON
- Authenticated email submission draft flow using signed v3 email tokens
- Static frontend served by Flask from `frontend/`
- OpenAPI/Swagger docs at `/api/docs`
- Prometheus-style metrics at `/metrics`

## Architecture At A Glance

```text
Users or email submissions
  -> Flask API and frontend
  -> moderation template
  -> span extraction
  -> topic and frame resolution
  -> fact and argument canonicalization
  -> fact-checking layer
  -> multi-judge scoring
  -> immutable snapshot, audits, dossier, verdict
  -> optional GitHub consolidated_results.json publication
```

Core scoring concepts:

- `F`: factuality score from canonical fact truth estimates
- `Reason`: median judge reasoning score
- `Cov`: coverage of opposing leverage
- `Q = (F * Reason * Cov)^(1/3)`
- `D = Overall_FOR - Overall_AGAINST`
- Verdicts are driven by confidence interval behavior and replicate stability

## Quick Start: Local Development

Requirements:

- Python 3.11
- `make`
- Node/npm only if you are running accessibility tooling that depends on `axe-core`

```bash
cd debate_system
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m playwright install chromium

cp .env.example .env
```

For deterministic local development, keep these values in `.env`:

```bash
ENV=development
SECRET_KEY=dev-secret-key-change-in-production
LLM_PROVIDER=mock
FACT_CHECK_MODE=OFFLINE
ALLOWED_ORIGINS=http://localhost:5000,http://localhost:3000
```

Start the app:

```bash
python start_server.py --host 127.0.0.1 --port 5000
```

Or use the workflow wrapper:

```bash
make server
```

Open the app at:

```text
http://127.0.0.1:5000
```

Check health:

```bash
curl http://127.0.0.1:5000/api/health
```

Expected shape:

```json
{
  "status": "healthy",
  "version": "3.0",
  "auth_enabled": true,
  "timestamp": "...",
  "redis": "connected|disconnected|not_configured"
}
```

The first registered user becomes an admin.

## Common Commands

```bash
# Create venv and install runtime dependencies
make bootstrap

# Run the default local verification subset
make test

# Run focused suites used by the workflow helper
make unit
make fact

# Start the v3 development server
make server

# Start a temporary server and run a smoke scenario
make smoke

# Run browser acceptance checks
make acceptance

# Run the accessibility scan helper
python scripts/dev_workflow.py a11y

# Lint and format
make lint
make format
```

Fuller pytest commands:

```bash
python -m pytest tests/unit/ -q
python -m pytest tests/integration/ -q
python -m pytest tests/integration/api/ --cov=backend.routes --cov-report=term-missing --cov-fail-under=70
```

Manual API scenarios can run against an existing server:

```bash
python tests/manual/manual_scenarios.py server-check --base-url http://127.0.0.1:5000
python tests/manual/manual_scenarios.py scenario-ai --base-url http://127.0.0.1:5000
python tests/manual/manual_scenarios.py scenario-energy --base-url http://127.0.0.1:5000
python tests/manual/manual_scenarios.py modulation --base-url http://127.0.0.1:5000
```

See [`docs/guides/TESTING.md`](docs/guides/TESTING.md) for the full testing guide.

## Frontend Modes

The frontend supports two operating modes.

### Live API Mode

Live API mode is the normal local and authenticated mode. Users register or log in, create debates, submit posts, generate snapshots, inspect verdicts, and manage admin/governance workflows through the Flask API.

Write-intent pages, including `frontend/new_debate.html`, require authentication.

### GitHub Cached Mode

GitHub cached mode lets public pages read from a published `consolidated_results.json` file. Configuration is stored in `localStorage` by `frontend/setup.html` and consumed by `frontend/static/js/data_bridge.js`.

This mode is useful for static or read-heavy deployments. Posting still requires either a live authenticated backend or an authenticated email submission draft.

## Email And GitHub Workflow

The old unsigned email submission template endpoint is deprecated. `GET /api/email-submission-template` now returns `410 DEPRECATED`.

The current email flow is:

1. A logged-in user calls `POST /api/debate/email-submission-draft`.
2. The backend returns a structured BDA Submission v3 email body with a signed JWT and payload hash.
3. The user sends the email to the configured processor inbox.
4. `backend.email_processor` polls IMAP, verifies the token and hash, submits the post, regenerates results, and publishes consolidated JSON to GitHub when configured.

Run the processor:

```bash
python -m backend.email_processor --poll-interval 60
```

Important environment variables:

- `PROCESSOR_DEST_EMAIL`
- `EMAIL_SUBMISSION_REQUIRE_AUTH`
- `EMAIL_SUBMISSION_TOKEN_TTL_MINUTES`
- `EMAIL_SUBMISSION_SECRET` or `SECRET_KEY`
- `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`
- `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` for acknowledgments
- `GITHUB_REPO`, `GITHUB_TOKEN`, `GITHUB_BRANCH`, `GITHUB_RESULTS_PATH`

Schema details are in [`docs/schema/email_submission_v3.md`](docs/schema/email_submission_v3.md).

## API Surface

The v3 API is decomposed into Flask blueprints under `backend/routes/`.

| Module | Main route family | Responsibility |
| --- | --- | --- |
| `api_bp.py` | `/api/health`, `/metrics`, static frontend | Health, metrics, static file serving |
| `auth_bp.py` | `/api/auth/*` | Register, login, logout, current user |
| `debate_bp.py` | `/api/debates`, `/api/debate/*` | Debate list/create/read/activate and email draft |
| `posts_bp.py` | `/api/debate/posts` | Post submission and listing |
| `topic_bp.py` | `/api/debate/topics`, evidence, modulation info | Topic and evidence surfaces |
| `snapshot_bp.py` | `/api/debate/snapshot*` | Snapshot generation, jobs, history, diffs |
| `dossier_bp.py` | `/api/debate/verdict`, audits, dossier | Verdict, audits, decision dossier |
| `proposal_bp.py` | `/api/debate-proposals*`, `/api/admin/debate-proposals*` | Proposal submission and admin review |
| `admin_bp.py` | `/api/admin/*`, `/api/audit/export/*` | Moderation templates, snapshot verification, audit export |
| `frame_bp.py` | `/api/governance/frames`, frame cadence, override, changelog | Public frame governance |
| `frame_petition_bp.py` | `/api/debate/<id>/frame-petitions` | Debate frame petitions |
| `appeals_bp.py` | `/api/governance/appeals`, `/api/debate/<id>/appeals`, `/api/admin/appeals` | User and admin appeals |
| `judge_bp.py` | `/api/governance/judge-pool*` | Judge pool policy and records |
| `governance_bp.py` | `/api/governance/fairness-audits`, incidents, summary | Governance summaries and incidents |

OpenAPI docs are available at:

```text
http://127.0.0.1:5000/api/docs
```

## Configuration

Core runtime:

- `ENV`: `development`, `staging`, or `production`
- `SECRET_KEY`: required to be strong outside development
- `JWT_EXPIRATION_HOURS`: default `24`
- `DEBATE_DB_PATH`: default `data/debate_system.db`
- `DATABASE_URL`: optional SQLAlchemy URL; SQLite is the local default and PostgreSQL is supported by the migration path
- `ALLOWED_ORIGINS`: comma-separated CORS allowlist
- `ENABLE_RATE_LIMITER`: default `true`
- `REDIS_URL`: shared rate-limit state; required outside development when rate limiting is enabled

Model and scoring:

- `LLM_PROVIDER`: `mock`, `openai`, `openrouter`, or `openrouter-multi`
- `NUM_JUDGES`: default `5`
- `FACT_CHECK_MODE`: `OFFLINE` or `ONLINE_ALLOWLIST`
- `OPENAI_API_KEY`: required for `openai`
- `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`: required for OpenRouter providers
- `ALLOW_MOCK_FALLBACK`: optional fallback behavior for real providers

Admin access:

- `ADMIN_ACCESS_MODE`: `open`, `authenticated`, or `restricted`
- `ADMIN_USER_EMAILS`: allowlist for restricted mode
- `ADMIN_USER_IDS`: allowlist for restricted mode

## Database And Migrations

Local development defaults to SQLite at `data/debate_system.db`.

Alembic migrations support SQLite and PostgreSQL:

```bash
DATABASE_URL=sqlite:///data/debate_system.db alembic upgrade head
DATABASE_URL=postgresql://user:pass@localhost:5432/bda_db alembic upgrade head
```

Because the project uses raw SQL rather than SQLAlchemy ORM models, migration autogeneration is disabled. Write migration files manually under `alembic/versions/`.

See [`docs/guides/DATABASE_MIGRATIONS.md`](docs/guides/DATABASE_MIGRATIONS.md).

## Docker And Deployment

Docker assets are present:

- `Dockerfile`
- `docker-compose.yml`
- `docs/guides/DEPLOYMENT.md`

The compose stack defines an app container plus Redis for shared rate limiting:

```bash
docker-compose up --build -d
curl http://localhost:5000/api/health
```

Current handoff notes did not include a completed Docker verification run, so validate container startup and health before treating Docker as a release path.

## Known Gaps

Current known gaps:

- UI acceptance suite: 10 of 11 checks fail because the Playwright helper calls CSRF-protected registration without a CSRF token. The app behavior is considered correct; the test helper needs updating.
- Type checks: `venv/bin/python -m mypy backend/pipeline/ backend/routes/ backend/utils/` currently reports 13 errors across `backend/utils/logging.py`, `backend/utils/rate_limits.py`, `backend/email_submission_parser.py`, `backend/email_submission_auth.py`, and `backend/routes/debate_bp.py`.
- Ruff: `venv/bin/python -m ruff check tests/unit/test_email_processor.py` currently reports 6 issues: import ordering plus unused local variables in that test file.
- Dependency audit: `pip-audit` reported package vulnerabilities that should be patched before production.
- Docker verification was skipped in the latest regression handoff.
- `admin_bp.py` and `dossier_bp.py` are still larger than the target route-module size.

See [`docs/current/REMEDIATION_HANDOFF.md`](docs/current/REMEDIATION_HANDOFF.md) for the latest full regression record; the working tree also has active edits beyond that handoff.

## Documentation Map

- [`docs/README.md`](docs/README.md) - docs index
- [`docs/architecture/BLUEPRINT.md`](docs/architecture/BLUEPRINT.md) - backend blueprint/module diagram and data flow
- [`docs/architecture/PRODUCT.md`](docs/architecture/PRODUCT.md) - product purpose and principles
- [`docs/security/auth.md`](docs/security/auth.md) - JWT auth flow
- [`docs/security/csrf.md`](docs/security/csrf.md) - CSRF protection
- [`docs/security/headers.md`](docs/security/headers.md) - CSP and security headers
- [`docs/guides/DEVELOPMENT.md`](docs/guides/DEVELOPMENT.md) - development commands
- [`docs/guides/TESTING.md`](docs/guides/TESTING.md) - test strategy and suites
- [`docs/guides/DEPLOYMENT.md`](docs/guides/DEPLOYMENT.md) - deployment guide
- [`docs/guides/OPENROUTER_SETUP.md`](docs/guides/OPENROUTER_SETUP.md) - OpenRouter setup
- [`docs/guides/V3_MIGRATION_GUIDE.md`](docs/guides/V3_MIGRATION_GUIDE.md) - v3 migration notes
- [`docs/current/IMPLEMENTATION_STATUS.md`](docs/current/IMPLEMENTATION_STATUS.md) - current status summary
- [`docs/current/REMEDIATION_HANDOFF.md`](docs/current/REMEDIATION_HANDOFF.md) - latest regression handoff
- [`docs/schema/email_submission_v3.md`](docs/schema/email_submission_v3.md) - authenticated email schema

## Contributing

Use focused branches and conventional commit messages:

```text
feat: add snapshot export filter
fix: include csrf token in acceptance helper
docs: refresh deployment caveats
test: cover email draft auth failures
refactor: split dossier blueprint helpers
chore: update locked dependencies
```

Before opening a PR, run the relevant checks for your change and update docs when behavior changes. Never commit `.env`, API keys, database files, or personal credentials.
