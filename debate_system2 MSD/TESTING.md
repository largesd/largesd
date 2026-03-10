# Testing Guide for Blind Debate Adjudicator

This document provides comprehensive testing strategies for the Blind LLM-Adjudicated Debate System based on the Medium Scale Discussion (MSD) specification.

## Quick Start

```bash
cd debate_system

# 1. Run unit tests (no server needed)
python test_debate_system.py

# 2. Start server and run manual tests
./start.sh --v2
# In another terminal:
python test_manual.py server-check
python test_manual.py scenario-ai
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

**Run:**
```bash
python test_debate_system.py
```

### 2. Manual/API Tests (`test_manual.py`)

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
./start.sh --v2

# Terminal 2: Run tests
python test_manual.py scenario-ai
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
python test_manual.py scenario-ai
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
python test_manual.py modulation
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

For development, add to CI/CD:

```yaml
# .github/workflows/test.yml example
test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v2
    - name: Install dependencies
      run: pip install -r requirements.txt
    - name: Run unit tests
      run: python test_debate_system.py
    - name: Start server
      run: |
        python start_server_v2.py &
        sleep 5
    - name: Run API tests
      run: python test_manual.py server-check
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
| Server not responding | Check port 5000, check `./start.sh --v2` output |
| API connection refused | Verify server is running: `python test_manual.py server-check` |
| Mock LLM returns weird results | Expected - mock is deterministic but simplified |

## Test Checklist

Before deploying:

- [ ] All unit tests pass: `python test_debate_system.py`
- [ ] Server starts without errors: `./start.sh --v2`
- [ ] API responds: `python test_manual.py server-check`
- [ ] Scenario completes: `python test_manual.py scenario-ai`
- [ ] Modulation works: `python test_manual.py modulation`
- [ ] Web interface loads at `http://localhost:5000`
- [ ] No identity information visible in UI
- [ ] Template version visible in UI
- [ ] Audit distributions display correctly
- [ ] Snapshot diff works (compare two snapshots)
