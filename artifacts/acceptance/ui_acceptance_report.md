# UI Acceptance Report

Task: Verify the core blind-debate experience through the real browser UI.
Base URL: http://127.0.0.1:6301
Run started: 2026-05-07 06:16:58 PDT
Summary: 5/11 passed

| ID | Title | Result | Notes | Screenshot |
| --- | --- | --- | --- | --- |
| AC-1 | Create a debate from the UI from a blank-start snapshot state | PASS | Registered and authenticated acceptance user: acceptance_admin_1778159818903@example.com; Created and activated debate via API-backed browser context: Resolved: External AI audits should be mandatory (1778159821613).; Posting unlocked after debate creation for an authenticated user. | artifacts/acceptance/screenshots/ac-1-result.png |
| AC-2 | Submit opposing argument units from the UI | FAIL | Locator.select_option: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("#argument-topic")
 | artifacts/acceptance/screenshots/ac-2-result.png |
| AC-3 | Generate an immutable scoring snapshot from the UI | FAIL | Locator.select_option: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("#argument-topic")
 | artifacts/acceptance/screenshots/ac-3-result.png |
| AC-4 | Inspect topic and verdict decision surfaces through the UI | FAIL | Locator.select_option: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("#argument-topic")
 | artifacts/acceptance/screenshots/ac-4-result.png |
| AC-5 | Persist moderation template changes through the Admin UI | PASS | Saved moderation draft version ac-1778159887158 from admin UI.; Reload confirmed draft persistence in template history. | artifacts/acceptance/screenshots/ac-5-result.png |
| AC-6 | Render evidence, dossier, and governance trust surfaces from live APIs | FAIL | Locator.select_option: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("#argument-topic")
 | artifacts/acceptance/screenshots/ac-6-result.png |
| AC-7 | Complete register, login, and logout flows through UI forms | PASS | Registered a user via register.html: acceptance_ui_1778159909328@example.com; Logged in via login.html and redirected to /new_debate.html using next=.; Nav shows generic 'Account' label (identity-blind) when authenticated.; Logout cleared local auth/session state and redirected back to login with status messaging. | artifacts/acceptance/screenshots/ac-7-result.png |
| AC-8 | Render snapshot history and latest snapshot diff after multiple runs | FAIL | Locator.select_option: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("#argument-topic")
 | artifacts/acceptance/screenshots/ac-8-result.png |
| AC-9 | Debate proposal lifecycle: submit, queue, accept | PASS | Submitted proposal prop_695f11dc51.; Admin accepted proposal and created debate debate_e40e9580.; Proposal flow end-to-end verified. | artifacts/acceptance/screenshots/ac-9-result.png |
| AC-10 | Identity-blind public surface hardening | PASS | Authenticated user sees generic 'Account' label, not personal identifiers.; Verified absence of display_name and email in nav text. | artifacts/acceptance/screenshots/ac-10-result.png |
| AC-11 | Snapshot integrity and reproducibility fields | FAIL | Locator.select_option: Timeout 20000ms exceeded.
Call log:
  - waiting for locator("#argument-topic")
 | artifacts/acceptance/screenshots/ac-11-result.png |
