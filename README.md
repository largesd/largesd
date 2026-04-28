# Blind Debate Adjudicator (`debate_system`)

A v3 prototype for **identity-blind, auditable debate adjudication**.

The system ingests structured arguments, applies visible moderation rules, builds canonical fact/argument layers, scores each side with multi-judge evaluation, and produces immutable snapshots with audits.

## What This Repository Implements

- **Identity-blind public surfaces** (no likes/profiles/reputation signals in debate views)
- **JWT auth + per-user debate session context**
- **Debate proposal workflow** (user submission -> admin accept/reject)
- **Versioned moderation templates** with draft/apply history
- **Snapshot pipeline**:
  - post modulation
  - extraction and canonicalization
  - fact checking (OFFLINE or ONLINE_ALLOWLIST)
  - scoring (Factuality, Reasoning, Coverage, Quality)
  - verdict with confidence interval logic
- **Governance endpoints** (frames, changelog, appeals, judge pool, fairness summaries)
- **Snapshot integrity metadata** (`replay_manifest`, input/output hash roots, recipe versions)
- **Optional GitHub publication** of consolidated results JSON
- **Email ingestion daemon** for processing structured email submissions

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

- `backend/app_v3.py`: Flask API (auth, debates, snapshots, governance, admin)
- `backend/debate_engine_v2.py`: core orchestration pipeline
- `backend/database.py`, `backend/database_v3.py`: SQLite schema + v3 extensions
- `backend/modulation.py`: built-in moderation templates and rule engine
- `backend/scoring_engine.py`: scoring, replicates, verdict logic
- `backend/email_processor.py`: IMAP -> parse -> snapshot -> GitHub publish loop
- `backend/published_results.py`: consolidated JSON bundle builder
- `frontend/`: UI pages and shared JS
- `frontend/static/js/data_bridge.js`: GitHub-cached read mode + email submission bridge
- `acceptance/run_ui_acceptance.py`: browser acceptance suite

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

### 2. Start Server

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

### 3. Validate Health

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
- `OPENROUTER_API_KEY` (if `openrouter` or `openrouter-multi`)

## Admin Access Policy

`ADMIN_ACCESS_MODE` controls admin endpoints:

- `open`: no auth checks
- `authenticated`: any logged-in user
- `restricted`: only users in `ADMIN_USER_EMAILS` / `ADMIN_USER_IDS`

## Testing

### Unit + Fact Check

```bash
python test_debate_system.py
python test_fact_check_skill.py
```

### Manual Scenarios

```bash
python test_manual.py server-check --base-url http://127.0.0.1:5000
python test_manual.py scenario-ai --base-url http://127.0.0.1:5000
```

### UI Acceptance

```bash
python scripts/dev_workflow.py acceptance
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
- Workflow contract: `docs/workflow/WORKFLOW.md`
- Testing guide: `docs/guides/TESTING.md`

## Notes

- `start_server.py` delegates to `start_server_v3.py`.
- Database defaults to `data/debate_system.db`.
- For deterministic local development, `LLM_PROVIDER=mock` and `FACT_CHECK_MODE=OFFLINE` are recommended.
