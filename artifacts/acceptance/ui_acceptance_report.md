# UI Acceptance Report

Task: Verify the core blind-debate experience through the real browser UI.
Base URL: http://127.0.0.1:5001
Run started: 2026-05-02 00:23:02 PDT
Summary: 2/11 passed

| ID | Title | Result | Notes | Screenshot |
| --- | --- | --- | --- | --- |
| AC-1 | Create a debate from the UI from a blank-start snapshot state | FAIL | Locator expected to contain text 'Posting is available'
Actual value: Create or select a debate to start posting. 
Call log:
  - Expect "to_contain_text" with timeout 5000ms
  - waiting for locator("#post-access-hint")
    9 × locator resolved to <small id="post-access-hint">Create or select a debate to start posting.</small>
      - unexpected value "Create or select a debate to start posting."
 | artifacts/acceptance/screenshots/ac-1-result.png |
| AC-2 | Submit opposing argument units from the UI | FAIL | Locator.check: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("input[name=\"side\"][value=\"FOR\"]")
 | artifacts/acceptance/screenshots/ac-2-result.png |
| AC-3 | Generate an immutable scoring snapshot from the UI | FAIL | Locator.check: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("input[name=\"side\"][value=\"FOR\"]")
 | artifacts/acceptance/screenshots/ac-3-result.png |
| AC-4 | Inspect topic and verdict decision surfaces through the UI | FAIL | Locator.check: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("input[name=\"side\"][value=\"FOR\"]")
 | artifacts/acceptance/screenshots/ac-4-result.png |
| AC-5 | Persist moderation template changes through the Admin UI | PASS | Saved moderation draft version ac-1777706656273 from admin UI.; Reload confirmed draft persistence in template history. | artifacts/acceptance/screenshots/ac-5-result.png |
| AC-6 | Render evidence, dossier, and governance trust surfaces from live APIs | FAIL | Locator.check: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("input[name=\"side\"][value=\"FOR\"]")
 | artifacts/acceptance/screenshots/ac-6-result.png |
| AC-7 | Complete register, login, and logout flows through UI forms | FAIL | Locator expected to be visible
Actual value: None
Error: element(s) not found 
Call log:
  - Expect "to_be_visible" with timeout 45000ms
  - waiting for locator("#register-form")
 | artifacts/acceptance/screenshots/ac-7-result.png |
| AC-8 | Render snapshot history and latest snapshot diff after multiple runs | FAIL | Locator.check: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("input[name=\"side\"][value=\"FOR\"]")
 | artifacts/acceptance/screenshots/ac-8-result.png |
| AC-9 | Debate proposal lifecycle: submit, queue, accept | PASS | Submitted proposal prop_cbf0f7deb6.; Admin accepted proposal and created debate debate_f26a66ac.; Proposal flow end-to-end verified. | artifacts/acceptance/screenshots/ac-9-result.png |
| AC-10 | Identity-blind public surface hardening | FAIL | Locator expected to be visible
Actual value: None
Error: element(s) not found 
Call log:
  - Expect "to_be_visible" with timeout 5000ms
  - waiting for locator(".navlinks")
 | artifacts/acceptance/screenshots/ac-10-result.png |
| AC-11 | Snapshot integrity and reproducibility fields | FAIL | Locator.check: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("input[name=\"side\"][value=\"FOR\"]")
 | artifacts/acceptance/screenshots/ac-11-result.png |
