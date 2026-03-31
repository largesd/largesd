# LSD v1.2 Traceability

Source document: `/Users/jonathanleung/Documents/C++/LSD req.txt`

This file maps the large design spec onto the current repo so we can be honest about two things at once:

1. Which criteria are already represented in the product and can be enforced in browser CI now.
2. Which criteria still require new implementation before they should be turned into failing acceptance gates.

## Browser-enforced now

- `AC-1` Blank-start debate creation through the UI.
- `AC-2` Opposing argument submission through the UI.
- `AC-3` Snapshot generation through the UI.
- `AC-4` Topic and verdict decision surfaces render after snapshot creation.

These live in `acceptance/ui_debate_flow.json` and are executed by `acceptance/run_ui_acceptance.py`.

## Good next browser criteria

- Explicit identity-blindness checks on public debate pages.
- Snapshot metadata checks for moderation version, trigger, and immutable snapshot identity.
- Decision dossier checks for evidence-gap summaries and decisive-premise outputs once implemented.
- Audit-page checks for merge sensitivity, budget adequacy, and centrality-cap diagnostics once implemented.

## Criteria that need implementation first

### Frames
The LSD spec makes frames a first-class public artifact.
Current status:
- no frame mode selector
- no frame justification dossier
- no frame petition/review workflow

### Snapshot reproducibility
The LSD spec expects a replay manifest and tamper-evident hashes.
Current status:
- snapshot id, timestamp, and trigger exist
- replay manifest and Merkle/hash outputs do not

### Integrity and selection transparency
The LSD spec expects capped centrality, rarity-slice diagnostics, budget adequacy indicators, and aggregate manipulation indicators.
Current status:
- not surfaced in APIs or UI yet

### Decision dossier completeness
The LSD spec expects remove-topic counterfactuals, decisive premises, evidence-gap summaries, and frame-sensitive verdicts.
Current status:
- topic contributions and evidence-target basics exist
- most dossier outputs remain to be built

### Governance and incidents
The LSD spec expects changelogs, fairness audits, appeal pathways, judge-pool governance, and additive incident snapshots.
Current status:
- not implemented in current UI

## Recommended rollout

1. Keep the current passing browser suite as the baseline regression gate.
2. Use `acceptance/lsd_v1_2_criteria.json` as the source-of-truth backlog for design acceptance.
3. Implement the missing LSD sections in vertical slices.
4. Promote each slice from `missing` or `partial` into browser-enforced CI only after the user-facing surface exists.
