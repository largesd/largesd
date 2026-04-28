# Sleep Agent Workflow

This repo now has the minimum scaffolding for a practical "agent while I sleep" loop.

The important split is:

- GitHub Actions runs the verifier on a schedule.
- A coding agent works from a queue of small, acceptance-based GitHub issues.

Do not try to hand the entire LSD v1.2 document to one overnight run. Turn it into small vertical slices.

## 1. Queue work as agent-ready issues

Use the `LSD Acceptance Slice` issue template.

Each issue should contain:

- one narrow task
- explicit acceptance criteria
- verification commands
- out-of-scope notes

Good examples:

- add explicit identity-blindness checks on public pages
- show evidence-gap summaries on the verdict page
- expose snapshot replay-manifest metadata
- add budget-adequacy diagnostics to audits

Bad examples:

- implement all remaining LSD requirements
- redesign the whole system around multi-frame adjudication

## 2. Keep a builder/verifier/judge split

Use separate roles:

- Builder: writes code for exactly one issue.
- Verifier: runs acceptance and unit checks.
- Judge: decides whether the issue is done or needs human review.

If one agent both writes the code and declares success, you are back in self-approval mode.

## 3. Builder prompt

Use this prompt for the overnight coding run:

```text
Pick the oldest open GitHub issue labeled agent-ready.
Work only on that issue.
Create a branch from main.
Implement the requested change exactly to the issue acceptance criteria.
Do not expand scope beyond the issue.

Before finishing, run:
- python3 test_debate_system.py
- python3 scripts/dev_workflow.py acceptance --port 5080 --timeout 60

If both commands pass:
- commit the changes
- push the branch
- open a draft PR to main

If either command fails:
- do not open a PR
- summarize the failing criteria
- attach or reference the acceptance artifacts

Stop after one issue.
```

## 4. Verifier inputs

The verifier should read:

- the GitHub issue acceptance criteria
- `acceptance/ui_debate_flow.json`
- `acceptance/lsd_v1_2_criteria.json`

The verifier should prefer observable behavior:

- browser behavior
- API responses
- rendered text
- acceptance reports

## 5. Nightly schedule

The repo includes `.github/workflows/nightly-acceptance.yml`.

What it does:

- runs nightly
- installs dependencies and Playwright
- runs the browser acceptance suite
- uploads artifacts
- opens a GitHub issue on failure

What it does not do:

- it does not write code by itself
- it does not select or complete GitHub issues

That coding step still needs an external agent runner such as Codex automation, Claude Code headless, or another scheduled agent process.

## 6. Morning review loop

When you wake up:

1. Check new draft PRs created from `agent-ready` issues.
2. Read acceptance failures first, not diffs first.
3. Merge only the slices whose acceptance criteria passed.
4. Move the next LSD requirement into a new `agent-ready` issue.

## 7. Suggested rollout

Start with these slices first:

1. Identity-blindness assertions across public pages
2. Snapshot dossier metadata expansion
3. Evidence-gap summary on verdict/evidence pages
4. Audit expansion for budget adequacy and centrality-cap effects

Do multi-frame adjudication only after the existing single-frame decision dossier is stable.
