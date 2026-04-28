# LSD v1.2 Gap Closure Changelog

Date: 2026-04-28

## Schema

- Added snapshot moderation diagnostics: `borderline_rate`, `suppression_policy_json`, `status`.
- Added canonical fact fields: `fact_type`, `normative_provenance`, `operationalization`, `evidence_tier_counts_json`.
- Added canonical argument `completeness_proxy`.
- Added frame governance fields: `frame_mode`, review cadence, emergency override metadata, governance decision id.
- Added `frame_petitions` table for frame petitions separate from debate proposals.
- Extended incidents with snapshot id, affected outputs, remediation plan, created/resolved timestamps.

## Formula Versions

- Moderation diagnostics: `lsd-3-v1.2.0`.
- Selection formula: `lsd-11-v1.2.0`.
- Topic relevance: `lsd-12-v1.2.0`.
- Component combination: `lsd-16-v1.2.0`.
- Fact-check policy: `lsd-13-policy-v1.2.0`.

## Feature Flags

- `FACT_CHECKER_MODE`: `simulated`, `perfect_checker`, `online_allowlist`.
- `SCORING_FORMULA_MODE`: `legacy_linear`, `v1_2_sqrt`, `v1_2_log`.
- `FRAME_MODE`: `single`, `multi`.
- `COVERAGE_MODE`: `leverage_legacy`, `binary_v1_2`.

## UI/API

- Snapshot and admin surfaces now show borderline rate and suppression policy.
- Governance surfaces now expose frame dossier, cadence, petitions, and incidents.
- Topics and audits expose dominance, concentration, merge sensitivity, integrity indicators, budget adequacy, rarity utilization, and cap effects.
- Verdict and dossier expose formula metadata, replicate metadata, decisive outputs, counterfactuals, insufficiency sensitivity, and unselected-tail summaries.
