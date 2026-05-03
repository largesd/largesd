# Testing Guide for Blind Debate Adjudicator

This document provides comprehensive testing strategies for the Blind LLM-Adjudicated Debate System based on the Medium Scale Discussion (MSD) specification.

## Quick Start

```bash
cd debate_system
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium

# 1. Run unit tests (no server needed)
python test_debate_system.py
python test_lsd_v1_2_contracts.py
python test_fact_check_skill.py

# 2. Run workflow check (unit + fact + lint)
python scripts/dev_workflow.py check

# 3. Start server and run manual tests
python start_server.py --host 127.0.0.1 --port 5000
# In another terminal:
source venv/bin/activate
python manual_scenarios.py server-check --base-url http://127.0.0.1:5000
python manual_scenarios.py scenario-ai --base-url http://127.0.0.1:5000

# 4. Run browser acceptance checks against a temporary v3 server
python scripts/dev_workflow.py acceptance
```

## Test Coverage

### 1. Unit Tests (`test_debate_system.py`)

Tests individual components against MSD requirements:

| Test | MSD Section | Description |
|------|-------------|-------------|
| `test_modulation_system` | §3 | Content moderation with visible templates |
| `test_span_extraction` | §5 | Traceability primitives |
| `test_fact_canonicalization` | §7.2 | Fact deduplication |
| `test_scoring_formulas` | §10 | F, Reason, Cov, Q calculations |
| `test_verdict_computation` | §13 | Statistical separability |
| `test_full_pipeline` | Full | End-to-end integration |
| `test_topic_geometry` | §4.5 | Topic drift, coherence, lineage |
| `test_side_label_symmetry` | §14.A | Label flip audit |
| `test_relevance_sensitivity` | §14.D | Weight perturbation audit |
| `test_identity_blindness` | §2.A | No identity fields in models |
| `test_snapshot_immutability` | §2.C | Snapshot preservation |
| `test_visible_modulation` | §2.B | Template versioning |
| `test_admin_template_persistence_and_engine_sync` | Step 2 hardening | Persisted admin draft/apply syncs into runtime moderation |
| `test_api_auth_session_and_admin_access_consistency` | Step 5 hardening | Verifies 401/403 behavior, active debate session isolation, and restricted admin access |

**Run:**
```bash
python test_debate_system.py
```

### 2. Manual/API Tests (`manual_scenarios.py`)

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
python start_server.py

# Terminal 2: Run tests
python manual_scenarios.py scenario-ai
```

### 3. Fact Checking Tests (`test_fact_check_skill.py`)

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
python test_fact_check_skill.py
```

### 4. OpenRouter Smoke Tests

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
python start_server.py
# In another terminal:
python manual_scenarios.py scenario-ai --base-url http://127.0.0.1:5000
```

**Verification checklist:**
- [ ] Direct `generate()` returns valid JSON with correct model id
- [ ] Snapshot completes without timeout (async pipeline)
- [ ] Snapshot metadata shows `provider: openrouter` and actual model id
- [ ] Token usage is tracked in `provider_metadata`
- [ ] Invalid API key produces explicit error (no silent mock fallback)

### 4. UI Acceptance Tests (`acceptance/run_ui_acceptance.py`)

Tests the system end to end through the browser UI against named acceptance criteria:

- `AC-1`: Create a debate from the UI
- `AC-2`: Submit opposing posts from the UI
- `AC-3`: Generate a snapshot from the UI
- `AC-4`: Inspect topics and verdict pages after snapshot generation
- `AC-5`: Save and reload admin moderation template draft persistence
- `AC-6`: Verify evidence, dossier, and governance pages render from live APIs
- `AC-7`: Verify register/login/logout UI flows and session persistence behavior
- `AC-8`: Verify snapshot history + latest diff rendering after multiple snapshots

The source of truth for the criteria lives in `acceptance/ui_debate_flow.json`.

**Run:**
```bash
python -m playwright install chromium
python scripts/dev_workflow.py acceptance
```

**Artifacts:**
```bash
artifacts/acceptance/ui_acceptance_report.json
artifacts/acceptance/ui_acceptance_report.md
artifacts/acceptance/screenshots/
```

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
python manual_scenarios.py scenario-ai
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
python manual_scenarios.py modulation
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

- Python checks
- API smoke verification
- Browser-based UI acceptance checks with Playwright

For local development, the equivalent browser command is:

```bash
python scripts/dev_workflow.py acceptance
```

Example CI shape:

```yaml
# .github/workflows/test.yml example
test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v2
    - name: Install dependencies
      run: pip install -r requirements.txt
    - name: Install browser
      run: python -m playwright install --with-deps chromium
    - name: Run unit tests
      run: python test_debate_system.py
    - name: Run UI acceptance tests
      run: python scripts/dev_workflow.py acceptance
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
| Server not responding | Check port 5000, check `python start_server.py` output |
| API connection refused | Verify server is running: `python manual_scenarios.py server-check` |
| Mock LLM returns weird results | Expected - mock is deterministic but simplified |

## Test Checklist

Before deploying:

- [ ] All unit tests pass: `python test_debate_system.py`
- [ ] Server starts without errors: `python start_server.py`
- [ ] API responds: `python manual_scenarios.py server-check`
- [ ] Scenario completes: `python manual_scenarios.py scenario-ai`
- [ ] UI acceptance passes: `python scripts/dev_workflow.py acceptance`
- [ ] Modulation works: `python manual_scenarios.py modulation`
- [ ] Web interface loads at `http://localhost:5000`
- [ ] No identity information visible in UI
- [ ] Template version visible in UI
- [ ] Audit distributions display correctly
- [ ] Snapshot diff works (compare two snapshots)
