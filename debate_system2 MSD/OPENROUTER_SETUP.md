# OpenRouter Integration Guide

## Overview

The Blind Debate Adjudicator uses **multi-judge evaluation** per the MSD specification. This means each scoring decision involves multiple independent LLM evaluations that are aggregated (via median) for robustness.

## Architecture

### Not a "Single AI Agent"

The system is explicitly designed to **avoid** single-evaluator bias:

```
Single Post Evaluation Flow:
┌────────────────────────────────────────────────────────────┐
│ Argument to Evaluate                                       │
└────────────────────┬───────────────────────────────────────┘
                     │
        ┌────────────┼────────────┬────────────┬────────────┐
        ▼            ▼            ▼            ▼            ▼
   ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
   │ Judge 1 │  │ Judge 2 │  │ Judge 3 │  │ Judge 4 │  │ Judge 5 │
   │ (T=0.3) │  │ (T=0.5) │  │ (T=0.6) │  │ (T=0.7) │  │ (T=0.9) │
   └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘
        │            │            │            │            │
        │  Score:    │  Score:    │  Score:    │  Score:    │  Score:
        │  0.72      │  0.68      │  0.75      │  0.71      │  0.69
        └────────────┴────────────┴────────────┴────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Aggregate (Median) │
                    │  Final Score: 0.71  │
                    └─────────────────────┘
```

**Cost Implication:** If you set `NUM_JUDGES=5`, each argument evaluation triggers **5 separate API calls**.

## Setup Options

### Option 1: Single Model (Cheaper)

Uses one model with temperature variation for diversity.

```bash
export LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY=sk-or-v1-xxxxxxxx
export NUM_JUDGES=5
python start_server.py
```

**Recommended models:**
- `anthropic/claude-3.5-sonnet` (best quality, higher cost)
- `openai/gpt-4o` (good balance)
- `meta-llama/llama-3.1-70b-instruct` (cheaper, decent quality)

### Option 2: Multi-Model (Better Diversity, More Expensive)

Uses different models for each judge — true evaluator diversity.

```bash
export LLM_PROVIDER=openrouter-multi
export OPENROUTER_API_KEY=sk-or-v1-xxxxxxxx
export NUM_JUDGES=5
python start_server.py
```

**Models used:**
1. Claude 3.5 Sonnet (Anthropic)
2. GPT-4o Mini (OpenAI)
3. Gemini Flash 1.5 (Google)
4. Llama 3.1 70B (Meta)
5. Mistral Large (Mistral)

## Cost Estimation

### Per-Snapshot Costs

A "snapshot" involves evaluating:
- All canonical facts (fact-checking)
- All canonical arguments (reasoning evaluation)
- All coverage determinations (opposing argument addressing)

**Example calculation** (5 judges, 10 arguments, 20 facts):

| Component | Calls | Tokens/Call | Cost per Call | Subtotal |
|-----------|-------|-------------|---------------|----------|
| Fact checks | 20 × 5 | ~1K prompt | ~$0.003 | ~$0.30 |
| Reasoning evals | 10 × 5 | ~2K prompt | ~$0.006 | ~$0.30 |
| Coverage evals | 10 × 5 | ~3K prompt | ~$0.009 | ~$0.45 |
| **Total** | **200 calls** | | | **~$1.05** |

**Ways to reduce costs:**
1. Use `NUM_JUDGES=3` instead of 5
2. Use cheaper models (Llama 3.1 70B, GPT-4o Mini)
3. Use single-model mode instead of multi-model
4. Stay in `mock` mode for development

## Quick Start

### 1. Get API Key

1. Visit https://openrouter.ai/keys
2. Create an account
3. Generate an API key
4. (Optional) Add credits ($5-10 is plenty for testing)

### 2. Run Setup Script

```bash
cd debate_system
python setup_openrouter.py
```

This interactive script will:
- Ask for your API key
- Let you choose single vs multi-model
- Configure number of judges
- Show cost estimates
- Create a `.env` file

### 3. Install Dependency

```bash
pip install python-dotenv
```

### 4. Start Server

```bash
# The .env file will be loaded automatically
python start_server.py
```

Or explicitly:

```bash
export $(cat .env | xargs)
python start_server.py
```

## Verifying Setup

### Check Health

```bash
curl http://localhost:5000/api/health
```

Expected:
```json
{"status": "healthy", "version": "2.0", ...}
```

### Check Modulation Info

```bash
curl http://localhost:5000/api/debate/modulation-info
```

This confirms the system is running and shows the current moderation template.

### Submit a Test Post

```bash
curl -X POST http://localhost:5000/api/debate/posts \
  -H "Content-Type: application/json" \
  -d '{
    "side": "FOR",
    "facts": "Studies show AI can improve medical diagnosis accuracy by 15%.",
    "inference": "Therefore, AI should not be banned in healthcare applications."
  }'
```

Watch the server logs — you should see API calls being made to OpenRouter.

## Troubleshooting

### "No API key found"

Make sure `OPENROUTER_API_KEY` is set:
```bash
echo $OPENROUTER_API_KEY
```

If using `.env` file, ensure `python-dotenv` is installed and the file is in the correct directory.

### "Rate limit exceeded"

OpenRouter has rate limits. If you're running many evaluations:
1. Reduce `NUM_JUDGES`
2. Add delays between snapshots
3. Contact OpenRouter to increase limits

### High costs

Monitor usage at https://openrouter.ai/settings/activity

To reduce costs:
- Switch to `LLM_PROVIDER=mock` for development
- Use `NUM_JUDGES=3`
- Use cheaper models

### Inconsistent responses

This is expected! The system is designed to use temperature variation and/or different models to get diverse evaluations. The **median** aggregation is robust to outliers.

## Configuration Reference

| Environment Variable | Options | Default | Description |
|---------------------|---------|---------|-------------|
| `LLM_PROVIDER` | `mock`, `openai`, `openrouter`, `openrouter-multi` | `mock` | Which LLM provider to use |
| `OPENROUTER_API_KEY` | Your API key | None | Required for OpenRouter |
| `NUM_JUDGES` | 1-10 | 5 | Number of judges per evaluation |
| `FACT_CHECK_MODE` | `OFFLINE`, `ONLINE_ALLOWLIST` | `OFFLINE` | Fact checking mode |
| `SITE_URL` | Your site URL | None | For OpenRouter rankings |
| `SITE_NAME` | Your site name | None | For OpenRouter rankings |

## Model Recommendations

### Budget Option (~$0.20-0.40 per snapshot)
```bash
LLM_PROVIDER=openrouter
NUM_JUDGES=3
# Uses default model (Claude 3.5 Sonnet)
```

### Balanced Option (~$0.80-1.50 per snapshot)
```bash
LLM_PROVIDER=openrouter
NUM_JUDGES=5
# Uses default model (Claude 3.5 Sonnet)
```

### Maximum Diversity (~$1.00-2.00 per snapshot)
```bash
LLM_PROVIDER=openrouter-multi
NUM_JUDGES=5
# Uses 5 different models
```

### Ultra-Budget Option (Free-ish)
```bash
LLM_PROVIDER=openrouter
NUM_JUDGES=3
# Model: meta-llama/llama-3.1-8b-instruct (very cheap)
```

Note: You'd need to modify `llm_client_openrouter.py` to change the default model.

## Security Notes

1. **Never commit `.env` files** — add to `.gitignore`
2. **Rotate API keys** regularly
3. **Monitor usage** on OpenRouter dashboard
4. **Set spending limits** on OpenRouter to prevent runaway costs
