# Module Map

Generated: 2026-04-11T20:43:54+00:00

## Backend Modules

| File | Role |
| --- | --- |
| backend/__init__.py | No module summary available |
| backend/app.py | Flask API for Blind Debate Adjudicator |
| backend/app_v2.py | Enhanced Flask API for Blind Debate Adjudicator v2 Uses the new debate engine with full MSD compliance |
| backend/database.py | SQLite database layer for debate system persistence |
| backend/debate_engine.py | Debate Engine |
| backend/debate_engine_v2.py | Enhanced Debate Engine v2 Full implementation with span extraction, canonicalization, audits, and persistence |
| backend/evidence_targets.py | "What Evidence Would Change This" Analysis Per MSD §15: |
| backend/extraction.py | Extraction and Canonicalization Engine Handles span extraction, fact/argument canonicalization with traceability Updated to integrate with Fact Checking Skill f |
| backend/fact_checker.py | Fact Checking Skill Implementation Based on the Fact Checking Agentic Skill Design Specification |
| backend/frame_registry.py | Frame Registry Module Implements LSD §5: Frame (Normative Transparency) A Frame defines the evaluative lens through which arguments are assessed |
| backend/job_queue.py | Async Job Queue Module SQLite-backed job queue for long-running operations like snapshot generation |
| backend/llm_client.py | LLM Client for multi-judge evaluation and text processing Supports multiple providers with a unified interface |
| backend/llm_client_openrouter.py | OpenRouter Provider for the Debate System OpenRouter provides unified access to multiple LLM models via an OpenAI-compatible API |
| backend/models.py | Core data models for the Blind LLM-Adjudicated Debate System |
| backend/modulation.py | Template-based Modulation System Per MSD §3: Admin-selectable, versioned templates for content moderation |
| backend/scoring.py | MSD (Medium Scale Discussion) Scoring Engine Implements all formulas from the specification |
| backend/scoring_engine.py | Enhanced MSD Scoring Engine Implements all formulas with real multi-judge evaluation and audits |
| backend/snapshot_diff.py | Snapshot Diff Capability Per MSD §16: Users can compare snapshots via diffs: |
| backend/tokenizer.py | Canonical Tokenizer for the Debate System Per MSD §5: Spans use "char or token offsets in canonical tokenizer" |
| backend/topic_engine.py | Topic Extraction and Management Engine Handles dynamic topic extraction, clustering, and drift detection |

## Scripts

| File | Role |
| --- | --- |
| scripts/agentic_workflow.py | Stateful agentic workflow runner for debate_system |
| scripts/dev_workflow.py | Central development workflow runner for the Blind Debate Adjudicator |

## Tests And Entry Points

| File | Role |
| --- | --- |
| start_server.py | Startup script for Blind Debate Adjudicator Usage: python start_server.py [--port PORT] [--host HOST] |
| start_server_fast.py | Fast startup script |
| start_server_v2.py | Startup script for Blind Debate Adjudicator v2 Enhanced version with full MSD specification compliance |
| test_debate_system.py | Comprehensive Test Suite for Blind LLM-Adjudicated Debate System Tests compliance with Medium Scale Discussion (MSD) specification |
| test_fact_check_skill.py | Test script for the Fact Checking Skill Verifies compliance with both: |
| test_manual.py | Manual Testing Script for Blind Debate Adjudicator Run this to test the system interactively or with predefined scenarios |
| test_slice1.py | Test Suite for LSD v1.2 Slice 1 Implementation Tests: |

## Frontend Pages

| File | Role |
| --- | --- |
| frontend/about.html | about |
| frontend/admin.html | admin |
| frontend/arguments_t1.html | arguments t1 |
| frontend/arguments_t2.html | arguments t2 |
| frontend/arguments_t3.html | arguments t3 |
| frontend/arguments_t4.html | arguments t4 |
| frontend/audits.html | audits |
| frontend/evidence.html | evidence |
| frontend/facts_t1.html | facts t1 |
| frontend/facts_t2.html | facts t2 |
| frontend/facts_t3.html | facts t3 |
| frontend/facts_t4.html | facts t4 |
| frontend/index.html | index |
| frontend/login.html | login |
| frontend/new_debate.html | new debate |
| frontend/register.html | register |
| frontend/snapshot.html | snapshot |
| frontend/topic_t1.html | topic t1 |
| frontend/topic_t2.html | topic t2 |
| frontend/topic_t3.html | topic t3 |
