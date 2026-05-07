# Backend Architecture Blueprint

This document describes the current modular architecture of the `debate_system` backend.

## Overview

The backend is organized around **Flask Blueprints** (route layers), **pipeline stages** (business logic), and **shared utilities** (cross-cutting concerns). Each module is intentionally kept under 400 lines for testability and maintainability.

## High-Level Module Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Flask Application (app_v3.py)                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │   CORS      │  │Rate Limiter │  │   Talisman  │  │  Request Logging    │ │
│  │ (origins)   │  │(Redis/mem)  │  │(sec headers)│  │  (+ request_id)     │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │                             │                             │
   ┌────▼────┐  ┌──────────┐  ┌──────▼──────┐  ┌────────┐  ┌──────▼──────┐
   │  auth   │  │   api    │  │   debate    │  │ topic  │  │  snapshot   │
   │  (JWT)  │  │ (health) │  │  (posts)    │  │(topics)│  │ (generate)  │
   └────┬────┘  └────┬─────┘  └──────┬──────┘  └───┬────┘  └──────┬──────┘
        │            │               │             │              │
   ┌────▼────────────▼───────────────▼─────────────▼──────────────▼──────┐
   │                         Shared Extensions                            │
   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
   │  │      db     │  │debate_engine│  │  job_queue  │  │  limiter   │ │
   │  │(DatabaseV3) │  │(DebateEngV2)│  │(SQLite+worker)│ │(Flask-Lim) │ │
   │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘ │
   └──────────────────────────────────────────────────────────────────────┘
                                      │
   ┌──────────────────────────────────┼──────────────────────────────────┐
   │                                  │                                  │
┌──▼─────────┐  ┌──────────────┐  ┌──▼──────────┐  ┌─────────────────┐  │
│  dossier   │  │  proposal    │  │  governance │  │     admin       │  │
│(frame docs)│  │(debate prop) │  │(appeals/    │  │(moderation/    │  │
│            │  │              │  │ changelog)  │  │  templates)     │  │
└────────────┘  └──────────────┘  └─────────────┘  └─────────────────┘  │
                                                                         │
┌────────────────────────────────────────────────────────────────────────┘
│
│  ┌─────────────────────────────────────────────────────────────────────┐
│  │                    Snapshot Pipeline (backend/pipeline/)             │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐   │
│  │  │ context │ │ extract │ │canonical│ │fact_chk │ │   score     │   │
│  │  │(setup)  │ │(spans)  │ │(dedup)  │ │(offline/ │ │(multi-judge)│   │
│  │  └─────────┘ └─────────┘ └─────────┘ │ online) │ └─────────────┘   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ └─────────┘ ┌─────────────┐   │
│  │  │ persist │ │  audit  │ │replicate│              │  counter-   │   │
│  │  │(save)   │ │(robust) │ │(judge var)             │  factual    │   │
│  │  └─────────┘ └─────────┘ └─────────┘              └─────────────┘   │
│  │  ┌─────────┐ ┌─────────┐                                            │
│  │  │ symmetry│ │orchestrator                                          │
│  │  │(flip tst│ │(runner) │                                            │
│  │  └─────────┘ └─────────┘                                            │
│  └─────────────────────────────────────────────────────────────────────┘
│
│  ┌─────────────────────────────────────────────────────────────────────┐
│  │                    Supporting Services                               │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │  │  llm_client │  │   scoring   │  │   topic     │  │  selection │ │
│  │  │(openrouter/ │  │   engine    │  │   engine    │  │   engine   │ │
│  │  │   mock)     │  │             │  │             │  │            │ │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │  │   email     │  │   github    │  │  published  │  │   frame    │ │
│  │  │  processor  │  │  publisher  │  │   results   │  │  registry  │ │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘ │
│  └─────────────────────────────────────────────────────────────────────┘
│
│  ┌─────────────────────────────────────────────────────────────────────┐
│  │                    Fact-Checking Skill (skills/fact_checking/)       │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐   │
│  │  │  skill  │ │connectors│ │  cache  │ │  queue  │ │   audit     │   │
│  │  │(entry)  │ │(evidence)│ │(multi-l)│ │ (async) │ │  (jsonl)    │   │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────────┘   │
│  └─────────────────────────────────────────────────────────────────────┘
│
│  ┌─────────────────────────────────────────────────────────────────────┐
│  │                    Shared Utilities (backend/utils/)                 │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │  │ middleware  │  │ decorators  │  │ validators  │  │  helpers   │ │
│  │  │(CSRF/log)   │  │(auth/admin) │  │(input/sanit)│  │(serialize) │ │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘ │
│  └─────────────────────────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────────────────────────┘
```

## Blueprints (Route Layers)

| Blueprint | File | Prefix | Responsibility |
|-----------|------|--------|----------------|
| `auth_bp` | `auth_bp.py` | `/api/auth` | Registration, login, logout, JWT issuance |
| `api_bp` | `api_bp.py` | `/api` | Health, metrics, modulation info |
| `debate_bp` | `debate_bp.py` | `/api/debate` | Post submission, debate CRUD, verdict |
| `topic_bp` | `topic_bp.py` | `/api/debate/topics` | Topic listing, detail, geometry |
| `snapshot_bp` | `snapshot_bp.py` | `/api/debate/snapshot` | Snapshot generation (sync + async jobs), diff, verification |
| `dossier_bp` | `dossier_bp.py` | `/api/debate/<id>/dossier` | Decision dossier, frame petitions |
| `proposal_bp` | `proposal_bp.py` | `/api/debate-proposals` | Debate proposal submission, accept/reject |
| `governance_bp` | `governance_bp.py` | `/api/governance` | Appeals, changelogs, fairness, judge pool, emergency override |
| `admin_bp` | `admin_bp.py` | `/api/admin` | Moderation templates, user management, system config |

All blueprints are registered in `app_v3.py:create_app()`.

## Pipeline Stages

The snapshot generation pipeline lives in `backend/pipeline/` and is orchestrated by `orchestrator.py`:

1. **context** — Build `PipelineContext` from debate state
2. **extract** — Span segmentation and fact/argument extraction
3. **canonicalize** — Fact deduplication and argument normalization
4. **fact_check** — Offline or online allowlist fact verification
5. **score** — Multi-judge scoring (Factuality, Reasoning, Coverage, Quality)
6. **persist** — Save snapshot with integrity metadata
7. **audit** — Robustness checks (side-label symmetry, evaluator disagreement, extraction stability)
8. **replicate** — Judge variance and replicate stability
9. **symmetry** — Label-flip audit
10. **counterfactual** — Evidence gap analysis

## Data Flow

```
User / Email
    │
    ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────────┐
│  Blueprint  │───▶│   Engine    │───▶│  Pipeline Stage │
│  (routes)   │    │ (orchestrate)│    │   (business)    │
└─────────────┘    └─────────────┘    └─────────────────┘
                                              │
                                              ▼
                                       ┌─────────────┐
                                       │  Database   │
                                       │(SQLite/PG)  │
                                       └─────────────┘
```

## Extension Lifecycle

`backend/extensions.py` holds singleton references initialized once in `create_app()`:

- `extensions.db` — `Database` instance
- `extensions.debate_engine` — `DebateEngineV2` instance
- `extensions.job_queue` / `extensions.job_worker` — Async job system
- `extensions.limiter` — Flask-Limiter instance
- `extensions.default_moderation_settings` — Default modulation config

## Testing Mapping

| Module | Test Location |
|--------|---------------|
| Blueprints | `tests/integration/api/test_*.py` |
| Pipeline stages | `tests/unit/pipeline/test_*.py` |
| Security middleware | `tests/integration/test_csrf.py`, `test_security_headers.py`, `test_cors.py` |
| Core engine | `tests/integration/test_debate_system.py`, `test_pipeline.py` |
| Fact checking | `tests/unit/test_fact_check_skill.py` |
| LSD contracts | `tests/unit/test_lsd_v1_2_contracts.py` |
| Email processing | `tests/unit/test_email_processor.py` |
| Manual scenarios | `tests/manual/manual_scenarios.py` |
