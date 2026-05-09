# Testing Guide for Blind Debate Adjudicator

This document provides comprehensive testing strategies for the Blind LLM-Adjudicated Debate System based on the Medium Scale Discussion (MSD) specification.

## Quick Start

```bash
cd debate_system
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m playwright install chromium

# 1. Run all checks (lint + unit + integration)
make test

# 2. Run specific suites
make unit
make fact
make smoke
make acceptance

# 3. Start server and run manual tests
make server
# In another terminal:
python tests/manual/manual_scenarios.py server-check --base-url http://127.0.0.1:5000
python tests/manual/manual_scenarios.py scenario-ai --base-url http://127.0.0.1:5000
```

## Test Organization

```
tests/
├── integration/
│   ├── api/
│   │   ├── test_admin.py
│   │   ├── test_api_misc.py
│   │   ├── test_auth.py
│   │   ├── test_debates.py
│   │   ├── test_dossier.py
│   │   ├── test_governance.py
│   │   ├── test_moderation.py
│   │   ├── test_openapi.py
│   │   ├── test_proposals.py
│   │   ├── test_redis_rate_limit.py
│   │   ├── test_request_id_tracing.py
│   │   ├── test_snapshots.py
│   │   └── test_topics.py
│   ├── test_cors.py
│   ├── test_csrf.py
│   ├── test_debate_system.py
│   ├── test_pipeline.py
│   ├── test_security_headers.py
│   └── test_slice4.py
├── unit/
│   ├── pipeline/
│   │   ├── test_audit.py
│   │   ├── test_canonicalize.py
│   │   ├── test_counterfactual.py
│   │   ├── test_extract.py
│   │   ├── test_fact_check.py
│   │   ├── test_persist.py
│   │   ├── test_replicate.py
│   │   ├── test_score.py
│   │   └── test_symmetry.py
│   ├── test_email_processor.py
│   ├── test_fact_check_skill.py
│   ├── test_job_queue.py
│   ├── test_lsd_v1_2_contracts.py
│   ├── test_perfect_skill.py
│   ├── test_request_id.py
│   └── test_sanitize.py
└── manual/
    └── manual_scenarios.py
```

| Suite | Location | Run Command |
|-------|----------|-------------|
| Integration (API routes) | `tests/integration/api/` | `python -m pytest tests/integration/api/ -v` |
| Integration (security) | `tests/integration/test_csrf.py`, `test_cors.py`, `test_security_headers.py` | `python -m pytest tests/integration/test_csrf.py -v` |
| Integration (end-to-end) | `tests/integration/test_debate_system.py`, `test_pipeline.py` | `python -m pytest tests/integration/test_debate_system.py -v` |
| Unit (pipeline stages) | `tests/unit/pipeline/` | `python -m pytest tests/unit/pipeline/ -v` |
| Unit (skills + utils) | `tests/unit/test_*.py` | `make unit` |
| Fact checking | `tests/unit/test_fact_check_skill.py` | `make fact` |
| Manual scenarios | `tests/manual/manual_scenarios.py` | `python tests/manual/manual_scenarios.py scenario-ai` |
| UI acceptance | `acceptance/run_ui_acceptance.py` | `make acceptance` |

## Unit Tests

### Pipeline Tests (`tests/unit/pipeline/`)

Each pipeline stage has dedicated unit tests:

| Test File | Stage | MSD Section |
|-----------|-------|-------------|
| `test_extract.py` | Span extraction | §5 |
| `test_canonicalize.py` | Fact/argument canonicalization | §7.2 |
| `test_fact_check.py` | Fact checking | §8 |
| `test_score.py` | Scoring (F, Reason, Cov, Q) | §10 |
| `test_replicate.py` | Judge replication | §11 |
| `test_audit.py` | Robustness audits | §14 |
| `test_symmetry.py` | Side-label symmetry | §14.A |
| `test_counterfactual.py` | Counterfactual analysis | — |
| `test_persist.py` | Snapshot persistence | §2.C |

### Core Unit Tests (`tests/unit/`)

| Test File | Coverage |
|-----------|----------|
| `test_sanitize.py` | HTML sanitization (XSS prevention) |
| `test_request_id.py` | Request ID tracing |
| `test_job_queue.py` | Async job queue and worker |
| `test_email_processor.py` | Email ingestion and parsing |
| `test_lsd_v1_2_contracts.py` | Formula contracts and invariants |
| `test_perfect_skill.py` | Perfect skill behavior |
| `test_fact_check_skill.py` | Fact-checking skill (offline, online, cache, PII) |

## Integration Tests

### API Route Tests (`tests/integration/api/`)

Every blueprint has dedicated route tests:

| Test File | Blueprint | Coverage |
|-----------|-----------|----------|
| `test_auth.py` | `auth_bp` | Register, login, logout, token validation, admin modes |
| `test_debates.py` | `debate_bp` | Create debate, submit posts, verdict |
| `test_topics.py` | `topic_bp` | Topic listing, detail, geometry |
| `test_snapshots.py` | `snapshot_bp` | Sync/async snapshot, diff, jobs |
| `test_dossier.py` | `dossier_bp` | Dossier, frame petitions |
| `test_proposals.py` | `proposal_bp` | Submit, accept, reject proposals |
| `test_governance.py` | `governance_bp` | Appeals, changelogs, judge pool |
| `test_admin.py` | `admin_bp` | Moderation templates, access control |
| `test_moderation.py` | `debate_bp` | Content moderation rules |
| `test_api_misc.py` | `api_bp` | Health, metrics |
| `test_openapi.py` | — | Swagger/OpenAPI spec validation |
| `test_redis_rate_limit.py` | — | Rate limiter with Redis backend |
| `test_request_id_tracing.py` | — | Request ID propagation |

### API Route Coverage Gate

A minimum 70 % coverage of `backend.routes` is enforced for the integration API test suite:

```bash
python -m pytest tests/integration/api/ \
  --cov=backend.routes \
  --cov-report=term-missing \
  --cov-fail-under=70
```

This command runs automatically in CI after the default checks. If the threshold is not met, the build fails and the `term-missing` report shows which lines are uncovered.

### Security Integration Tests

| Test File | Coverage |
|-----------|----------|
| `test_csrf.py` | Double-submit cookie pattern, exemptions |
| `test_cors.py` | Origin restriction, preflight |
| `test_security_headers.py` | CSP, HSTS, X-Frame-Options, Referrer-Policy |

### End-to-End Integration Tests

| Test File | Coverage |
|-----------|----------|
| `test_debate_system.py` | Full MSD pipeline with MSD § assertions |
| `test_pipeline.py` | Pipeline orchestrator end-to-end |
| `test_slice4.py` | Slice-4 acceptance criteria |

## Manual/API Tests (`tests/manual/manual_scenarios.py`)

Tests the system through the REST API with realistic scenarios:

| Command | Purpose |
|---------|---------|
| `server-check` | Verify server is running |
| `scenario-ai` | AI regulation debate with 4 posts |
| `scenario-energy` | Renewable energy debate with 4 posts |
| `modulation` | Content moderation edge cases |

**Run:**
```bash
# Terminal 1: Start server
make server

# Terminal 2: Run tests
python tests/manual/manual_scenarios.py scenario-ai
```

## Fact Checking Tests (`tests/unit/test_fact_check_skill.py`)

Tests the fact-checking skill specifically:

- OFFLINE mode (neutral results)
- ONLINE_ALLOWLIST mode
- Claim normalization
- Multi-layer caching
- PII detection
- Async processing
- Audit logging

**Run:**
```bash
make fact
```

## OpenRouter Smoke Tests

To validate real LLM integration (requires an OpenRouter API key):

```bash
# 1. Configure environment
export LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY=sk-or-v1-...
export OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
export NUM_JUDGES=1
export ALLOW_MOCK_FALLBACK=false

# 2. Run a single direct generation test
python -c "
from backend.llm_client_openrouter import OpenRouterProvider
p = OpenRouterProvider()
r = p.generate('Say hello in one word.')
print('Model:', r.model)
print('Tokens:', r.usage)
"

# 3. Run end-to-end manual scenario
make server
# In another terminal:
python tests/manual/manual_scenarios.py scenario-ai --base-url http://127.0.0.1:5000
```

**Verification checklist:**
- [ ] Direct `generate()` returns valid JSON with correct model id
- [ ] Snapshot completes without timeout (async pipeline)
- [ ] Snapshot metadata shows `provider: openrouter` and actual model id
- [ ] Token usage is tracked in `provider_metadata`
- [ ] Invalid API key produces explicit error (no silent mock fallback)

## UI Acceptance Tests (`acceptance/run_ui_acceptance.py`)

Tests the system end to end through the browser UI against named acceptance criteria:

- `AC-1`: Create a debate from the UI
- `AC-2`: Submit opposing posts from the UI
- `AC-3`: Generate a snapshot from the UI
- `AC-4`: Inspect topics and verdict pages after snapshot generation
- `AC-5`: Save and reload admin moderation template draft persistence
- `AC-6`: Verify evidence, dossier, and governance pages render from live APIs
- `AC-7`: Verify register/login/logout UI flows and session persistence behavior
- `AC-8`: Verify snapshot history + latest diff rendering after multiple snapshots
- `AC-9`: Debate proposal lifecycle: submit, queue, accept
- `AC-10`: Identity-blind public surface hardening
- `AC-11`: Snapshot integrity and reproducibility fields

The source of truth for the criteria lives in `acceptance/ui_debate_flow.json`.

**Run:**
```bash
python -m playwright install chromium
make acceptance
```

**Artifacts:**
```bash
artifacts/acceptance/ui_acceptance_report.json
artifacts/acceptance/ui_acceptance_report.md
artifacts/acceptance/screenshots/
```

A criteria sync check is also available to detect when acceptance results and
criteria statuses diverge:

```bash
python scripts/check_criteria_sync.py
```

## Accessibility Scan (`acceptance/run_a11y_scan.py`)

Runs an automated axe-core accessibility scan against representative frontend pages using Playwright.

**Prerequisites:**
```bash
npm ci
python -m playwright install chromium
```

**Run against an already-running server:**
```bash
python acceptance/run_a11y_scan.py --base-url http://127.0.0.1:5000
```

**Run with the dev workflow (starts a temporary server):**
```bash
python scripts/dev_workflow.py a11y --port 5080 --timeout 60
```

**Threshold:** The scan defaults to `critical` impact only. To include `serious`:
```bash
python acceptance/run_a11y_scan.py --base-url http://127.0.0.1:5000 --impact critical,serious
```

**Pages scanned:**
- `/`
- `/login.html`
- `/register.html`
- `/new_debate.html`
- `/admin.html`
- `/appeals.html`
- `/governance.html`
- `/topics.html`

The script exits with a nonzero code when violations are found at the chosen threshold.

## Testing Requirements Compliance

### Core Principles (MSD §1-2)

| Requirement | Test | How to Verify |
|-------------|------|---------------|
| Identity Blindness | `test_identity_blindness` | Check Post/Span/Fact models have no username/user_id fields |
| Visible Modulation | `test_visible_modulation` | Verify template has name, version, visible rules |
| Snapshot Stability | `test_snapshot_immutability` | Create snapshots, verify they don't change on retrieval |
| Robustness | `test_side_label_symmetry`, `test_relevance_sensitivity` | Check audit outputs show distributions |

### Pipeline Tests (MSD §2)

```
Posts → Modulation → Topic Consolidation → Span Segmentation →
Argument Units → FACT/ARG Extraction → Canonicalization →
Fact-Check → Scoring → Verdict → Audits
```

**Integration Test:**
```bash
python tests/manual/manual_scenarios.py scenario-ai
```

This tests the full pipeline with realistic inputs.

### Scoring Verification (MSD §10-13)

Formulas to verify:

```
F_{t,s} = (1/K) × Σ p_k                          # Factuality
Reason_{t,s} = median_a(Reason_{t,s,a})          # Reasoning
Cov_{t,s} = Σ(addressed × leverage) / Σ(leverage) # Coverage
Q_{t,s} = (F × Reason × Cov)^(1/3)               # Quality
Rel_t = Mass_t / Σ_t Mass_t                       # Topic Relevance
Overall_s = Σ_t (Rel_t × Q_{t,s})                # Overall Score
D = Overall_FOR − Overall_AGAINST                # Margin
```

**Verify with:**
```bash
python -c "
from backend.scoring_engine import ScoringEngine
engine = ScoringEngine(num_judges=3)

# Test factuality
facts = [{'p_true': 0.9}, {'p_true': 0.7}]
F = engine.compute_factuality(facts)
print(f'F = {F} (expected: 0.8)')

# Test quality
Q = engine.compute_quality(0.8, 0.7, 0.6)
print(f'Q = {Q} (expected: {(0.8*0.7*0.6)**(1/3):.4f})')
"
```

## Scenario-Based Testing

### Scenario 1: Clear FOR Win

Expected outcome: Verdict = "FOR", high confidence

```python
# Submit 3 strong FOR posts with high P(true) facts
# Submit 1 weak AGAINST post with uncertain facts
# Expected: FOR wins with confidence > 0.8
```

### Scenario 2: Balanced Debate (NO VERDICT)

Expected outcome: Verdict = "NO VERDICT", low confidence

```python
# Submit equal quality posts on both sides
# Expected: CI(D) crosses zero, no clear winner
```

### Scenario 3: Content Moderation

Expected: Harassment/spam blocked, valid content allowed

```bash
python tests/manual/manual_scenarios.py modulation
```

## Audit Verification

### Side-Label Symmetry (MSD §14.A)

Swap FOR/AGAINST labels, verify scores swap accordingly.

```bash
# Check in audit output
python -c "
import requests
r = requests.get('http://localhost:5000/api/debate/audits')
data = r.json()
print(data['audits']['side_label_symmetry'])
"
```

### Extraction Stability (MSD §9, §14.C)

Re-run extraction, check overlap distributions.

Look for in audit:
- `fact_overlap_distribution`
- `argument_overlap_distribution`
- `mismatch_report`

### Evaluator Disagreement (MSD §14.B)

Check IQR values in topic scores.

Look for:
- `reasoning_iqr` per topic-side
- `coverage_iqr` per topic-side
- Judge disagreement levels (low/moderate/high)

## Web Interface Testing

Manual testing through browser:

1. **Home Page** (`/`): View current verdict and scores
2. **New Debate** (`/new_debate.html`): Submit posts
3. **Topics** (`/topics.html`): View topic geometry
4. **Verdict** (`/verdict.html`): View detailed scoring
5. **Audits** (`/audits.html`): View robustness checks
6. **Evidence** (`/evidence.html`): View "what would change this"

**Check for:**
- No usernames displayed anywhere
- Template name/version visible
- All scores present with formulas
- Audit distributions (not pass/fail)
- Traceability links (span IDs, provenance)

## Load Testing

Test system with many posts:

```python
import requests

# Create debate
r = requests.post('http://localhost:5000/api/debate', json={
    'resolution': 'Load test debate',
    'scope': 'Testing with many posts'
})
debate_id = r.json()['debate_id']

# Submit 50 posts
for i in range(50):
    requests.post('http://localhost:5000/api/debate/posts', json={
        'debate_id': debate_id,
        'side': 'FOR' if i % 2 == 0 else 'AGAINST',
        'facts': f'Fact {i}: This is test fact number {i}.',
        'inference': f'Therefore, conclusion {i} follows.'
    })

# Generate snapshot
r = requests.post('http://localhost:5000/api/debate/snapshot', json={
    'debate_id': debate_id,
    'trigger_type': 'manual'
})
print(f"Processed {r.json()['allowed_count']} posts")
```

## Debugging Tests

### Check Database State

```bash
sqlite3 data/debate_system.db ".tables"
sqlite3 data/debate_system.db "SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 1;"
```

### Check Modulation

```bash
curl http://localhost:5000/api/debate/modulation-info
```

### Check Fact Check Stats

```bash
curl http://localhost:5000/api/debate/fact-check-stats
```

## Continuous Testing

This repo's GitHub Actions workflow now runs:

- Python lint and format checks (ruff, pre-commit)
- Type checks (mypy)
- Unit and integration tests
- API smoke verification
- Security scan (bandit)
- Browser-based UI acceptance checks with Playwright
- Accessibility scan with axe-core and Playwright

For local development, the equivalent commands are:

```bash
make test       # lint + unit + integration
make smoke      # API smoke test
make acceptance # browser acceptance
```

Example CI shape:

```yaml
# .github/workflows/test.yml example
test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements-test.txt
    - name: Install browser
      run: python -m playwright install --with-deps chromium
    - name: Run lint
      run: pre-commit run --all-files
    - name: Run type checks
      run: mypy backend/pipeline/ backend/routes/ backend/utils/
    - name: Run unit tests
      run: python -m pytest tests/unit/ -v
    - name: Run integration tests
      run: python -m pytest tests/integration/ -v
    - name: Run UI acceptance tests
      run: make acceptance
    - name: Run accessibility scan
      run: |
        npm ci
        python acceptance/run_a11y_scan.py --base-url http://127.0.0.1:5000 --impact critical
```

## Expected Test Outputs

### Successful Unit Test
```
=== Testing Modulation System (MSD §3) ===
✓ Valid post allowed through modulation
✓ Harassment blocked correctly
✓ Modulation audit info: Standard Civility v1.0
```

### Successful Scenario Test
```
[Creating Debate]
  Resolution: Should advanced AI development be paused for safety reasons?
✓ Created debate: debate_a1b2c3d4

[Submitting Post - FOR]
✓ Post post_xxx: ALLOWED
...
[Generating Snapshot]
✓ Generated snapshot: snap_20240310_120000
  Verdict: FOR
  Confidence: 0.85
  Margin D: 0.25
```

### Failed Test (Example)
```
=== Testing Scoring Formulas (MSD §10) ===
✓ Factuality F = 0.800 (mean of P(true) values)
✓ Empty facts return neutral 0.5
✗ FAILED: Quality should be geometric mean
  Expected: 0.6794, Got: 0.7000
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Import errors | Run from `debate_system` directory, check `sys.path` |
| Database locked | Stop server, delete `data/debate_system.db`, restart |
| Server not responding | Check port 5000, check `make server` output |
| API connection refused | Verify server is running: `python tests/manual/manual_scenarios.py server-check` |
| Mock LLM returns weird results | Expected - mock is deterministic but simplified |
| Redis connection error | Start Redis with `docker-compose up redis` or set `ENABLE_RATE_LIMITER=false` |

## Test Checklist

Before deploying:

- [ ] All unit tests pass: `make unit`
- [ ] All integration tests pass: `python -m pytest tests/integration/ -v`
- [ ] Server starts without errors: `make server`
- [ ] API responds: `python tests/manual/manual_scenarios.py server-check`
- [ ] Scenario completes: `python tests/manual/manual_scenarios.py scenario-ai`
- [ ] UI acceptance passes: `make acceptance`
- [ ] Accessibility scan passes: `python scripts/dev_workflow.py a11y`
- [ ] Modulation works: `python tests/manual/manual_scenarios.py modulation`
- [ ] Web interface loads at `http://localhost:5000`
- [ ] No identity information visible in UI
- [ ] Template version visible in UI
- [ ] Audit distributions display correctly
- [ ] Snapshot diff works (compare two snapshots)
- [ ] Security scan passes: `bandit -r backend/`
