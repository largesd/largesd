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

## Project Layout

### Backend (`backend/`)

- `app.py` — stable Flask API alias (currently wraps `app_v3.py`)
- `app_v3.py` — Flask API (auth, debates, snapshots, governance, admin, metrics)
- `debate_engine.py` — stable engine alias (currently wraps `debate_engine_v2.py`)
- `debate_engine_v2.py` — core orchestration pipeline
- `database.py` (legacy), `database_v3.py` — active SQLite schema with bcrypt hashing + v3 extensions (async jobs, judge pools)
- `models.py` — dataclasses (Post, Snapshot, Fact, ArgumentUnit, DebateFrame, User, etc.)
- `modulation.py` — built-in moderation templates and rule engine
- `extraction.py` — span extraction, fact/argument canonicalization
- `topic_engine.py` — topic clustering, drift, coherence
- `scoring_engine.py` — multi-judge scoring, replicates, verdict logic
- `scoring.py` — scoring utilities and helpers
- `selection_engine.py` — argument selection with centrality/rarity logic
- `fact_checker.py` — thin wrapper around the fact-checking skill
- `debate_proposal.py` — debate proposal submission and review logic
- `tokenizer.py` — text tokenization utilities
- `skills/fact_checking/` — full fact-checking subsystem (at project root):
  - `skill.py` — main entry point
  - `connectors.py`, `wikidata_connector.py`, `web_rag_connector.py` — evidence sources
  - `policy.py`, `template_adapters.py` — rule and template logic
  - `pii.py`, `normalization.py`, `sources.py` — preprocessing
  - `decomposer.py`, `planner.py` — claim decomposition and planning
  - `cache.py`, `fc_queue.py`, `audit.py` — async queue, caching, audit logging
  - `rate_limiter.py`, `models.py`, `config.py` — rate limiting, internal models, configuration
- `governance.py` — appeals, changelogs, fairness audits, judge pool governance, incidents
- `frame_registry.py` — LSD §5 epistemic frame registry with content hashing
- `lsd_v1_2.py` — formula constants, feature flags, diagnostic helpers, formula registry
- `job_queue.py` — SQLite-backed async job queue with background worker thread
- `email_processor.py` — IMAP → parse → snapshot → GitHub publish loop
- `email_submission_parser.py` — structured email body parser (`BDA Submission v1`)
- `published_results.py` — consolidated JSON bundle builder
- `github_publisher.py` — GitHub Contents API publisher
- `llm_client.py` / `llm_client_openrouter.py` — LLM provider abstraction
- `snapshot_diff.py` — immutable snapshot comparison
- `evidence_targets.py` — evidence gap analysis

### Frontend (`frontend/`)

| Page | Purpose |
|------|---------|
| `index.html` | Home / debate overview |
| `new_debate.html` | Create debate + submit posts |
| `topic.html` / `topics.html` | Dynamic topic detail + listing |
| `verdict.html` | Scoring verdict display |
| `audits.html` | Robustness audit distributions |
| `snapshot.html` | Snapshot history + diff |
| `evidence.html` | Evidence targets / gaps |
| `dossier.html` / `frame-dossier.html` | Decision dossier + frame transparency |
| `governance.html` | Governance summary |
| `appeals.html` | Appeal submission + status |
| `admin.html` | Moderation template management |
| `login.html` / `register.html` | Auth flows |
| `setup.html` | GitHub DataBridge configuration |
| `about.html` | About / specification |
| `propose.html` | Debate proposal submission |

**Shared Frontend Infrastructure**

- `static/js/common.js` — Core `BDA` object: API wrapper, state management, shared component injection
- `static/js/auth.js` — JWT auth, session management, user menu
- `static/js/data_bridge.js` — GitHub-cached mode: fetches `consolidated_results.json`, localStorage caching, `mailto:` link generation for email submissions
- `static/js/index.js` — Home page logic and dynamic content loading
- `assets/styles.css` — Design system with WCAG 2.1 AA compliance
- `components/` — Reusable HTML components (help panels, footer, back-to-top)

### Other Key Files

- `start_server.py` — primary server entrypoint (delegates to `start_server_v3.py`)
- `start_server_v3.py` — v3 server implementation with CLI args
- `Makefile` — 20+ dev targets (`bootstrap`, `acceptance`, `smoke`, `server`, etc.)
- `Dockerfile` / `docker-compose.yml` — containerized deployment (Flask app + Redis)
- `alembic.ini` / `alembic/` — database migrations (PostgreSQL + SQLite)
- `tests/integration/test_debate_system.py`, `tests/unit/test_fact_check_skill.py`, `tests/manual/manual_scenarios.py`, `test_email_processor.py`, `test_lsd_v1_2_contracts.py`, `test_perfect_skill.py`, `test_slice4.py` — test suites
- `acceptance/run_ui_acceptance.py` — Playwright browser acceptance suite
- `acceptance/ui_debate_flow.json` — acceptance criteria definitions
- `scripts/dev_workflow.py` — orchestrated dev commands
- `scripts/agentic_workflow.py` — agentic workflow orchestration
- `scripts/generate_lsd_compliance_report.py` — LSD compliance report generator
- `scripts/cleanup_debates_without_user.py` — data cleanup utility
- `scripts/run_migrations.sh` — migration runner shell script
- `setup_openrouter.py` — interactive OpenRouter configuration helper
- `corrected_implementation_plan.md` — UX & trust hardening plan
- `.agents/` — agent skill definitions (design system skill)
- `archive/` — legacy server versions (v1, v2)
- `workflow_state/` — agentic workflow state tracking
- `.github/ISSUE_TEMPLATE/` — GitHub issue templates

## Quick Start (Local API Development)

### 1. Install

```bash
cd debate_system
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env and set at minimum:
#   SECRET_KEY=your-strong-random-key
#   LLM_PROVIDER=mock   # or openrouter with OPENROUTER_API_KEY
```

### 3. Start Server

```bash
python start_server.py --host 127.0.0.1 --port 5000
```

Or with explicit runtime options:

```bash
python start_server.py \
  --host 127.0.0.1 \
  --port 5000 \
  --fact-mode OFFLINE \
  --llm-provider mock \
  --num-judges 5
```

Or use Make:

```bash
make server        # default v3 server
make server-fast   # gunicorn production-like
```

### Docker Quick Start

```bash
cp .env.example .env
# Edit .env with production values
docker-compose up --build -d
```

Services: Flask app (port 5000) + Redis.

### 4. Validate Health

```bash
curl http://127.0.0.1:5000/api/health
```

Expected shape:

```json
{
  "status": "healthy",
  "version": "3.0",
  "auth_enabled": true,
  "timestamp": "..."
}
```

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
- `authenticated`: any logged-in user
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

## Testing

### Unit + Fact Check

```bash
python -m pytest tests/integration/test_debate_system.py
python -m pytest tests/unit/test_fact_check_skill.py
python test_lsd_v1_2_contracts.py
python test_email_processor.py
python test_perfect_skill.py
python test_slice4.py
```

Or via Make:

```bash
make unit
make fact
```

### Manual Scenarios

```bash
python manual_scenarios.py server-check --base-url http://127.0.0.1:5000
python manual_scenarios.py scenario-ai --base-url http://127.0.0.1:5000
```

Or via Make:

```bash
make manual-ai
```

### Smoke Tests

```bash
make smoke
```

### UI Acceptance

```bash
python scripts/dev_workflow.py acceptance
# or
make acceptance
```

Artifacts:

- `artifacts/acceptance/ui_acceptance_report.json`
- `artifacts/acceptance/ui_acceptance_report.md`
- `artifacts/acceptance/screenshots/`

## Core Scoring Concepts

Per topic-side:

- `F`: factuality from canonical fact `p_true`
- `Reason`: median judge reasoning score
- `Cov`: how well arguments address opposing leverage
- `Q = (F * Reason * Cov)^(1/3)`

Debate-level margin:

- `D = Overall_FOR - Overall_AGAINST`
- Verdict is driven by confidence interval behavior and replicate stability.

## Documentation

- Full docs index: `docs/README.md`
- Architecture: `docs/architecture/` — design documents and product spec
- Workflow: `docs/workflow/` — workflow contracts and development workflows
- Guides: `docs/guides/` — testing, deployment, database migrations, OpenRouter setup, privacy, WCAG audit
- Current status: `docs/current/` — implementation status
- Archive: `docs/archive/` — older implementation plans and handoffs
- Compliance: `docs/compliance/` — formula traceability matrix, LSD v1.2 compliance reports and changelog
- Requirements: `docs/requirements/` — LSD requirements and change requests
- Schema: `docs/schema/` — email submission schema
- Archive: `docs/archive/` — previous README versions
- V3 migration guide: `docs/V3_MIGRATION_GUIDE.md`

## Notes

- `start_server.py` is the recommended primary startup command. It delegates to `start_server_v3.py` internally.
- Current stable backend modules: `backend/app.py` and `backend/debate_engine.py` (wrap v3/v2 internals).
- Database defaults to `data/debate_system.db`.
- Passwords are hashed with **bcrypt** (not PBKDF2).
- For deterministic local development, `LLM_PROVIDER=mock` and `FACT_CHECK_MODE=OFFLINE` are recommended.
- The backend has deeper functionality than the UI currently exposes — see governance and judge-pool endpoints for advanced features.
