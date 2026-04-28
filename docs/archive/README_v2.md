# Blind Debate Adjudicator v2

Enhanced implementation of the **Blind LLM-Adjudicated Debate System** with full Medium Scale Discussion (MSD) specification compliance.

## What's New in v2

### Core Improvements

| Feature | v1 | v2 |
|---------|-----|-----|
| **Span Extraction** | ❌ Not implemented | ✅ LLM-based span extraction with offsets |
| **FACT Canonicalization** | ❌ Hard-coded facts | ✅ Dynamic clustering & deduplication |
| **ARGUMENT Canonicalization** | ❌ Bypassed | ✅ Proper AU → canonical argument flow |
| **Topic Extraction** | ❌ Static topics | ✅ Dynamic extraction from posts |
| **Multi-Judge Evaluation** | ❌ Simulated with noise | ✅ Real LLM judge calls |
| **Extraction Stability Audit** | ❌ Mock data | ✅ Actual double-run comparison |
| **Side-Label Symmetry Audit** | ❌ Mock data | ✅ Real label-swap test |
| **Relevance Sensitivity Audit** | ❌ Not implemented | ✅ Perturbation analysis |
| **Topic Drift Detection** | ❌ Static values | ✅ Cross-snapshot comparison |
| **Database Persistence** | ❌ In-memory only | ✅ SQLite with full history |
| **Steelman Summaries** | ❌ Hard-coded | ✅ LLM-generated from canonical args |

## Architecture

```
debate_system/
├── backend/
│   ├── app_v2.py                 # Flask API (v2)
│   ├── database.py               # SQLite persistence
│   ├── llm_client.py             # Multi-provider LLM client
│   ├── extraction.py             # Span extraction & canonicalization
│   ├── topic_engine.py           # Dynamic topic extraction
│   ├── scoring_engine.py         # Enhanced scoring with real judges
│   ├── debate_engine_v2.py       # Main orchestration
│   ├── fact_checker.py           # Fact checking (unchanged)
│   └── models.py                 # Data models (legacy)
├── frontend/                     # Same UI (compatible)
├── data/                         # SQLite database
├── start_server_v2.py            # v2 startup script
└── README_v2.md                  # This file
```

## Quick Start

### Option 1: Using Mock LLM (No API Key Required)

```bash
cd debate_system
./start.sh --v2
```

The mock provider simulates LLM responses deterministically for testing.

### Option 2: Using OpenAI (Requires API Key)

```bash
export OPENAI_API_KEY="your-api-key"
./start.sh --v2 --llm-provider openai
```

### Option 3: Custom Configuration

```bash
./start.sh --v2 \
    --port 8080 \
    --llm-provider openai \
    --fact-mode ONLINE_ALLOWLIST \
    --num-judges 7 \
    --db-path data/my_debate.db
```

## Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `--port` | Server port | 5000 |
| `--host` | Bind host | 0.0.0.0 |
| `--llm-provider` | LLM backend (mock/openai) | mock |
| `--fact-mode` | Fact checking mode | OFFLINE |
| `--num-judges` | Judges for multi-judge eval | 5 |
| `--db-path` | SQLite database path | data/debate_system.db |
| `--debug` | Enable debug mode | false |

## API Endpoints (v2)

All v1 endpoints are supported. New v2-specific endpoints:

| Endpoint | Description |
|----------|-------------|
| `GET /api/debate/topic-lineage` | Topic evolution across snapshots |
| `GET /api/debate/audits` | Full audit data (real, not mock) |

## Pipeline Flow

```
Posts
  ↓
Modulation (allow/block) → Saved to DB
  ↓ (for allowed posts)
Span Extraction (LLM) → Spans saved with offsets
  ↓
Fact Extraction from Spans
  ↓
FACT Canonicalization (clustering) → Deduplicated facts
  ↓
Argument Unit Construction
  ↓
ARGUMENT Canonicalization → Deduplicated arguments
  ↓
Topic Extraction / Update (dynamic)
  ↓
Fact-Checking → P(true) for each canonical fact
  ↓
Steelman Summary Generation (per topic, per side)
  ↓
Multi-Judge Scoring
  - Reasoning evaluation (real LLM judges)
  - Coverage evaluation (real LLM judges)
  ↓
Debate Aggregation
  ↓
Replicate-Based Verdict
  ↓
Audit Generation
  - Extraction stability (2-run comparison)
  - Side-label symmetry (swap test)
  - Relevance sensitivity (perturbation)
  - Topic drift (cross-snapshot)
  ↓
Snapshot Saved to DB
```

## Audit Details

### 1. Extraction Stability
Runs the extraction pipeline twice independently and measures:
- **Fact overlap**: Jaccard similarity of canonical facts
- **Argument overlap**: Jaccard similarity of canonical arguments
- **Mismatch report**: Facts/arguments appearing in only one run

### 2. Side-Label Symmetry
Runs the full pipeline with FOR/AGAINST labels swapped:
- If perfectly symmetric: D should flip sign but have same magnitude
- Measures asymmetry as |D_original - (-D_swapped)|
- Flags potential bias in evaluation

### 3. Relevance Sensitivity
Perturbs topic relevance weights via resampling:
- Tests verdict stability under weight variations
- Reports distribution of D across perturbations
- High variance indicates unstable verdict

### 4. Topic Drift
Compares current topics to previous snapshot:
- Matches topics by name/scope similarity
- Computes drift score per topic
- Tracks operations: created, merged, split, renamed, unchanged

## Database Schema

### Key Tables

- **debates**: Debate metadata
- **posts**: All submitted posts with modulation outcomes
- **spans**: Traceable text segments with offsets
- **topics**: Dynamic topics with geometry metrics
- **canonical_facts**: Deduplicated facts with P(true)
- **canonical_arguments**: Deduplicated arguments
- **snapshots**: Immutable debate states
- **audit_records**: Audit results per snapshot

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key (required for openai provider) |
| `LLM_PROVIDER` | Default LLM provider (mock/openai) |
| `FACT_CHECK_MODE` | Default fact check mode (OFFLINE/ONLINE_ALLOWLIST) |
| `NUM_JUDGES` | Default number of judges |

## Comparison with Specification

| Spec Section | Implementation Status |
|--------------|----------------------|
| 1. Core Principles | ✅ Fully implemented |
| 2. Pipeline | ✅ Full pipeline |
| 3. Modulation | ✅ With DB persistence |
| 4. Topic Consolidation | ✅ Dynamic extraction |
| 5. Spans | ✅ Full traceability |
| 6. Argument Units | ✅ Proper AU construction |
| 7. FACT Layer | ✅ With canonicalization |
| 8. ARGUMENT Layer | ✅ With canonicalization |
| 9. Extraction Stability | ✅ Real audit |
| 10. Topic Scoring | ✅ Real multi-judge |
| 11. Topic Relevance | ✅ Content mass based |
| 12. Debate Aggregation | ✅ Weighted sum |
| 13. Verdict | ✅ Statistical separability |
| 14. Robustness Checks | ✅ All 5 audits |
| 15. Evidence Targets | ✅ Uncertain facts |
| 16. Snapshots | ✅ Full versioning |
| 17. UI | ✅ Compatible with v1 |

## Performance Considerations

With real LLM calls:
- **Span extraction**: ~1s per post
- **Canonicalization**: ~2s per topic
- **Multi-judge scoring**: ~5s per topic (num_judges × API calls)
- **Full snapshot**: ~30-60s depending on posts

For faster testing, use `--llm-provider mock`.

## Upgrading from v1

1. v1 and v2 can run side-by-side (different ports)
2. v2 database is separate from v1 (no migration needed)
3. Frontend is compatible with both versions
4. API responses are backward-compatible

## Known Limitations

1. **Mixed stance posts**: Not yet implemented (posts have single side)
2. **Online fact checking**: Requires allowlist configuration
3. **Topic splitting**: Basic implementation (adds generic topics)
4. **Embedding-based clustering**: Uses LLM instead of embeddings (simpler but slower)

## License

Prototype implementation for demonstration purposes.
