# Blind Debate Adjudicator

A fully functional prototype of the **Blind LLM-Adjudicated Debate System** based on the Medium Scale Discussion (MSD) specification.

> **📢 Version 2 Available!** See [README_v2.md](README_v2.md) for the enhanced implementation with:
> - Dynamic topic extraction
> - Real span extraction with traceability
> - FACT and ARGUMENT canonicalization
> - Real multi-judge LLM evaluation
> - Full audit suite (extraction stability, side-label symmetry, relevance sensitivity)
> - SQLite persistence
>
> Run v2: `./start.sh --v2`

## Features

### Core System
- **Identity Blindness**: No usernames, profiles, likes, or social signals
- **Visible Modulation**: Transparent, versioned moderation rules
- **FACT Layer**: Atomic facts with P(true) from agentic fact-checking
- **ARGUMENT Layer**: Structured arguments (Facts → Inference)
- **Canonicalization**: Deduplication of facts and arguments
- **Topic Geometry**: Bounded topics with neutrality enforcement

### Scoring System
- **Factuality (F)**: Mean P(fact true) across canonical facts
- **Reasoning (Reason)**: Median strength of inferences
- **Coverage (Cov)**: Weighted proportion of opposing arguments addressed
- **Quality (Q)**: Geometric mean of F × Reason × Cov
- **Overall Score**: Topic-relevance-weighted sum
- **Margin (D)**: FOR − AGAINST difference
- **Verdict**: Statistical separability from replicates

### Fact Checking
Two modes per specification:
- **OFFLINE**: Neutral results (p=0.5, confidence=0)
- **ONLINE_ALLOWLIST**: Deterministic fact-checking with simulated evidence

Features:
- SHA256 claim normalization
- Immutable caching
- Versioned thresholds
- Deterministic verdict mapping

## Quick Start

### Installation

```bash
# Navigate to the project directory
cd debate_system

# Install dependencies
pip install -r requirements.txt
```

### Start the Server

```bash
# Start with default settings (mock LLM - no API key needed)
python start_server.py

# Or with custom options
python start_server.py --port 8080 --fact-mode ONLINE_ALLOWLIST

# With OpenRouter (requires API key)
export LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY=sk-or-v1-xxxxxxxx
python start_server.py
```

The server will start at `http://localhost:5000`

### LLM Provider Configuration

The system supports multiple LLM providers:

| Provider | Description | API Key Required |
|----------|-------------|------------------|
| `mock` | Deterministic mock responses (default) | No |
| `openai` | OpenAI API | `OPENAI_API_KEY` |
| `openrouter` | OpenRouter (single model) | `OPENROUTER_API_KEY` |
| `openrouter-multi` | OpenRouter (multi-model judges) | `OPENROUTER_API_KEY` |

**Multi-Model Judges (`openrouter-multi`):**
Instead of using temperature variations on a single model, this uses different models for each judge:
- Judge 1: Claude 3.5 Sonnet
- Judge 2: GPT-4o Mini
- Judge 3: Gemini Flash 1.5
- Judge 4: Llama 3.1 70B
- Judge 5: Mistral Large

This provides **true evaluator diversity** per MSD §14.B.

Get an OpenRouter API key at: https://openrouter.ai/keys

### Access the Web Interface

Open your browser and navigate to:
- **Home**: http://localhost:5000/
- **New Debate/Post**: http://localhost:5000/new_debate.html
- **Topics**: http://localhost:5000/topics.html
- **Verdict**: http://localhost:5000/verdict.html
- **Audits**: http://localhost:5000/audits.html
- **Admin**: http://localhost:5000/admin.html
- **Spec**: http://localhost:5000/about.html

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/debate` | GET | Get current debate info |
| `/api/debate` | POST | Create new debate |
| `/api/debate/posts` | POST | Submit a post |
| `/api/debate/snapshot` | GET | Get current snapshot |
| `/api/debate/snapshot` | POST | Generate new snapshot |
| `/api/debate/snapshot-history` | GET | Get all snapshots (MSD §16) |
| `/api/debate/snapshot-diff` | GET | Compare snapshots (MSD §16) |
| `/api/debate/topics` | GET | Get all topics with scores |
| `/api/debate/topics/{id}/facts` | GET | Get facts for a topic |
| `/api/debate/topics/{id}/arguments` | GET | Get arguments for a topic |
| `/api/debate/topic-lineage` | GET | Topic evolution history |
| `/api/debate/verdict` | GET | Get verdict data |
| `/api/debate/audits` | GET | Get audit reports |
| `/api/debate/evidence-targets` | GET | "What would change this" (MSD §15) |
| `/api/debate/evidence` | GET | Legacy evidence targets |
| `/api/debate/modulation-info` | GET | Current modulation template (MSD §3) |
| `/api/debate/modulation-templates` | GET | List available templates |
| `/api/debate/audits` | GET | Get audit data |
| `/api/debate/evidence` | GET | Get evidence targets |

## Project Structure

```
debate_system/
├── backend/
│   ├── app.py              # Flask API server
│   ├── models.py           # Data models
│   ├── fact_checker.py     # Fact checking skill
│   ├── scoring.py          # MSD scoring engine
│   └── debate_engine.py    # Main orchestration
├── frontend/
│   ├── assets/styles.css   # UI styling
│   ├── index.html          # Home page
│   ├── topics.html         # Topics listing
│   ├── topic_t*.html       # Individual topic pages
│   ├── facts_t*.html       # Fact layer pages
│   ├── arguments_t*.html   # Argument layer pages
│   ├── verdict.html        # Verdict display
│   ├── audits.html         # Audit reports
│   ├── new_debate.html     # Post submission
│   ├── admin.html          # Admin configuration
│   ├── evidence.html       # Evidence targets
│   └── about.html          # Specification
├── requirements.txt        # Python dependencies
├── start_server.py         # Startup script
└── README.md              # This file
```

## How to Use

### 1. View Current Debate
Navigate to the home page to see:
- Current verdict and confidence
- Overall FOR/AGAINST scores
- Snapshot information
- Moderation template

### 2. Submit a Post
Go to "New Debate / Post Point":
1. Select your position (FOR or AGAINST)
2. Choose a topic area
3. Enter factual premises (one per line)
4. State your inference/conclusion
5. Optionally identify counter-arguments addressed
6. Click "Submit Post"

Your post will be evaluated by the modulation system and either:
- **Allowed**: Included in the next snapshot
- **Blocked**: Excluded with reason

### 3. Generate a Snapshot
After submitting posts, click "Generate New Snapshot" to:
- Extract and canonicalize facts
- Run fact-checking
- Compute all scores
- Update the verdict

### 4. Explore Results
- **Topics**: View all topics with geometry metrics
- **Verdict**: See detailed scoring and D distribution
- **Audits**: Check robustness and stability
- **Evidence**: See what evidence would change the verdict

## Scoring Formulas

### Per Topic-Side:
```
F_{t,s} = (1/K) × Σ p_k                 # Factuality
Reason_{t,s} = median_a(Reason_{t,s,a}) # Reasoning
Cov_{t,s} = Σ(addressed) / Σ(all)       # Coverage
Q_{t,s} = (F × Reason × Cov)^(1/3)      # Quality
```

### Debate Level:
```
Overall_s = Σ_t (Rel_t × Q_{t,s})       # Weighted sum
D = Overall_FOR − Overall_AGAINST       # Margin
```

### Verdict:
```
If CI(D) entirely > 0: FOR wins
If CI(D) entirely < 0: AGAINST wins
Else: NO VERDICT
```

## Requirements Compliance

This implementation meets all requirements from the specification:

- ✅ **Identity-blind**: No usernames, likes, or popularity metrics
- ✅ **Visible modulation**: Template + version displayed
- ✅ **Snapshot immutability**: Each snapshot frozen after creation
- ✅ **Topic geometry audit**: Lineage, drift, coherence, distinctness
- ✅ **FACT layer**: P(true) and provenance tracking
- ✅ **ARGUMENT layer**: Reasoning scores and coverage
- ✅ **Replicate-based verdict**: D distribution + CI(D)
- ✅ **"What evidence would change this"**: High-leverage targets
- ✅ **Side-label symmetry audit**: Label flip detection
- ✅ **Extraction stability reporting**: Overlap distributions
- ✅ **Evaluator disagreement**: IQR display

## License

This is a prototype implementation for demonstration purposes.
