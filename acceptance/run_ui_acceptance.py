#!/usr/bin/env python3
"""
Browser-driven acceptance verification for the Blind Debate Adjudicator.

The suite is intentionally organized around named acceptance criteria so the
report reads like a pass/fail checklist instead of a raw test log.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Callable
from pathlib import Path

try:
    from playwright.sync_api import Browser, Page, expect, sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
except ImportError as exc:  # pragma: no cover - helpful runtime message
    raise SystemExit(
        "Playwright is not installed. Run `pip install -r requirements.txt` and "
        "`python -m playwright install chromium` first."
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC_PATH = REPO_ROOT / "acceptance" / "ui_debate_flow.json"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "artifacts" / "acceptance"
DEFAULT_TIMEOUT_MS = 20_000
SNAPSHOT_TIMEOUT_MS = 45_000


def unique_suffix() -> str:
    return str(int(time.time() * 1000))


ACCEPTANCE_RUN_SUFFIX = unique_suffix()
ACCEPTANCE_ADMIN_EMAIL = f"acceptance_admin_{ACCEPTANCE_RUN_SUFFIX}@example.com"
ACCEPTANCE_ADMIN_PASSWORD = "AcceptancePass123"
ACCEPTANCE_ADMIN_DISPLAY_NAME = f"Acceptance Admin {ACCEPTANCE_RUN_SUFFIX[-6:]}"

ACCEPTANCE_ADMIN_AUTH: dict[str, object] | None = None


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_markdown(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def get_csrf_token(page: Page, base_url: str) -> str:
    """Prime the Playwright context by loading an HTML page and read the csrf_token cookie."""
    page.goto(f"{base_url}/login.html", wait_until="networkidle")
    cookies = page.context.cookies(base_url)
    token = next((c["value"] for c in cookies if c["name"] == "csrf_token"), "")
    if not token:
        raise AssertionError("Could not obtain csrf_token cookie from login.html.")
    return token


def response_debug(response) -> object:
    """Return JSON body if available, otherwise the raw text."""
    try:
        return response.json()
    except Exception:
        return response.text()


def open_new_debate_page(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/new_debate.html", wait_until="networkidle")
    expect(page.locator("#debate-section")).to_be_visible()


def register_or_login_admin(page: Page, base_url: str) -> dict:
    """Register or log in the acceptance admin user using CSRF-aware direct API calls."""
    csrf = get_csrf_token(page, base_url)
    headers = {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
    }

    register_payload = {
        "email": ACCEPTANCE_ADMIN_EMAIL,
        "password": ACCEPTANCE_ADMIN_PASSWORD,
        "display_name": ACCEPTANCE_ADMIN_DISPLAY_NAME,
    }
    register_response = page.request.post(
        f"{base_url}/api/auth/register",
        headers=headers,
        data=json.dumps(register_payload),
    )

    if register_response.status in {200, 201}:
        auth_data = register_response.json()
    elif register_response.status == 409:
        login_response = page.request.post(
            f"{base_url}/api/auth/login",
            headers=headers,
            data=json.dumps({"email": ACCEPTANCE_ADMIN_EMAIL, "password": ACCEPTANCE_ADMIN_PASSWORD}),
        )
        if not login_response.ok:
            raise AssertionError(
                "Failed to log in acceptance admin after register conflict: "
                f"HTTP {login_response.status}: {response_debug(login_response)}"
            )
        auth_data = login_response.json()
    else:
        raise AssertionError(
            f"Failed to register acceptance admin: HTTP {register_response.status}: "
            f"{response_debug(register_response)}"
        )

    if not auth_data.get("access_token"):
        raise AssertionError("Admin authentication response did not include access_token.")

    return auth_data


def seed_acceptance_admin(browser: Browser, base_url: str) -> dict[str, object]:
    """Seed exactly one per-run admin user before criteria execute."""
    global ACCEPTANCE_ADMIN_AUTH

    context = browser.new_context(viewport={"width": 1440, "height": 1200})
    page = context.new_page()
    page.set_default_timeout(DEFAULT_TIMEOUT_MS)

    try:
        auth_data = register_or_login_admin(page, base_url)

        admin_auth = {
            "access_token": auth_data["access_token"],
            "user_id": auth_data.get("user_id", ""),
            "email": auth_data.get("email", ACCEPTANCE_ADMIN_EMAIL),
            "display_name": auth_data.get("display_name", ACCEPTANCE_ADMIN_DISPLAY_NAME),
            "is_admin": auth_data.get("is_admin", False),
        }

        if admin_auth.get("is_admin") is not True:
            raise AssertionError(
                "Seeded acceptance admin user is not admin. "
                f"Auth payload: {admin_auth}"
            )

        ACCEPTANCE_ADMIN_AUTH = admin_auth
        return admin_auth
    finally:
        context.close()


def authenticate_browser_user(page: Page, base_url: str) -> dict[str, str]:
    if ACCEPTANCE_ADMIN_AUTH is None:
        raise AssertionError(
            "ACCEPTANCE_ADMIN_AUTH is not seeded. "
            "Call seed_acceptance_admin before running criteria."
        )

    admin_auth = ACCEPTANCE_ADMIN_AUTH

    page.goto(f"{base_url}/index.html", wait_until="networkidle")
    page.evaluate(
        """(auth) => {
            localStorage.setItem("access_token", auth.access_token);
            localStorage.setItem("user", JSON.stringify({
                user_id: auth.user_id,
                email: auth.email,
                display_name: auth.display_name,
                is_admin: auth.is_admin,
            }));
        }""",
        admin_auth,
    )
    return {
        "user_id": admin_auth["user_id"],
        "email": admin_auth["email"],
        "display_name": admin_auth["display_name"],
    }


def create_debate_via_api(page: Page, base_url: str, token: str) -> dict[str, str]:
    """Create a debate via admin API (default admin access mode allows authenticated users)."""
    motion = f"Resolved: External AI audits should be mandatory ({unique_suffix()})."
    debate_scope = (
        "Judge which side best balances safety, accountability, operational burden, "
        "and public trust for a neutral policymaker."
    )
    response = page.request.post(
        f"{base_url}/api/debates",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        data=json.dumps({"resolution": motion, "scope": debate_scope}),
    )
    if not response.ok:
        raise AssertionError(f"Failed to create debate via API: HTTP {response.status}")
    data = response.json()
    # Activate the debate
    activate_response = page.request.post(
        f"{base_url}/api/debate/{data['debate_id']}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    if not activate_response.ok:
        raise AssertionError(
            "Failed to activate debate via API: "
            f"HTTP {activate_response.status}: {response_debug(activate_response)}"
        )
    return {
        "motion": motion,
        "debate_scope": debate_scope,
        "debate_id": data["debate_id"],
    }


def create_debate(page: Page, base_url: str) -> dict[str, str]:
    # Acceptance user is authenticated; default admin mode allows direct creation.
    token = page.evaluate("() => localStorage.getItem('access_token')") or ""
    return create_debate_via_api(page, base_url, token)


def create_active_debate_and_open_posting(page: Page, base_url: str) -> dict[str, str]:
    debate = create_debate(page, base_url)
    open_new_debate_page(page, base_url)
    expect(page.locator("#display-resolution")).to_contain_text(debate["motion"])
    expect(page.locator("#post-access-hint")).to_contain_text("Posting is available")
    return debate


def submit_post(page: Page, side: str, topic_id: str, facts: str, inference: str) -> None:
    page.locator(f'input[name="side"][value="{side}"]').check(force=True)
    page.locator("#argument-topic").select_option(topic_id)
    page.locator("#facts-input").fill(facts)
    page.locator("#inference-input").fill(inference)
    page.locator("#counter-input").fill("")
    page.locator("#submit-post-button").click()
    expect(page.locator("#status-message")).to_contain_text(
        re.compile(r"Email generated|Argument submitted")
    )


def generate_snapshot(page: Page, base_url: str) -> dict[str, str]:
    page.goto(f"{base_url}/index.html", wait_until="networkidle")

    generate_button = page.locator("#generate-snapshot-btn")
    expect(generate_button).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    expect(generate_button).to_be_enabled(timeout=SNAPSHOT_TIMEOUT_MS)
    generate_button.click()

    expect(page.locator("#api-status")).to_contain_text(
        "Snapshot ready", timeout=SNAPSHOT_TIMEOUT_MS
    )

    snapshot_id = (page.locator("#badge-snapshot-id").text_content() or "").strip()
    verdict = (page.locator("#verdict-display").text_content() or "").strip()

    if not snapshot_id or snapshot_id == "-" or not snapshot_id.startswith("snap_"):
        raise AssertionError("Snapshot id did not populate after generation.")
    if verdict not in {"FOR", "AGAINST", "NO VERDICT"}:
        raise AssertionError(f"Unexpected verdict value: {verdict!r}")

    open_new_debate_page(page, base_url)
    expect(page.locator("#header-snapshot")).to_contain_text(
        snapshot_id, timeout=SNAPSHOT_TIMEOUT_MS
    )

    return {"snapshot_id": snapshot_id, "verdict": verdict}


def criterion_ac1(page: Page, base_url: str) -> list[str]:
    user = authenticate_browser_user(page, base_url)
    open_new_debate_page(page, base_url)
    expect(page.locator("#display-resolution")).to_contain_text("No active debate")
    expect(page.locator("#post-access-hint")).to_contain_text("No active debate")

    debate = create_debate(page, base_url)
    open_new_debate_page(page, base_url)
    expect(page.locator("#display-resolution")).to_contain_text(debate["motion"])
    expect(page.locator("#post-access-hint")).to_contain_text("Posting is available")

    return [
        f"Registered and authenticated acceptance user: {user['email']}",
        f"Created and activated debate via API-backed browser context: {debate['motion']}",
        "Posting unlocked after debate creation for an authenticated user.",
    ]


def criterion_ac2(page: Page, base_url: str) -> list[str]:
    authenticate_browser_user(page, base_url)
    create_active_debate_and_open_posting(page, base_url)

    submit_post(
        page,
        "FOR",
        "t1",
        "Frontier AI systems can scale harmful mistakes quickly.\nIndependent audits can catch deployment risks before release.",
        "Therefore mandatory audits can reduce high-severity misuse risk.",
    )
    submit_post(
        page,
        "AGAINST",
        "t3",
        "Jurisdictions regulate AI differently across borders.\nBlanket mandates can slow beneficial deployment unevenly.",
        "Therefore mandatory audits can create enforcement gaps and coordination costs.",
    )

    pending_section = page.locator("#pending-posts")
    if pending_section.is_visible():
        expect(page.locator("#pending-count")).to_have_text("2")
        expect(page.locator("#posts-list")).to_contain_text("FOR")
        expect(page.locator("#posts-list")).to_contain_text("AGAINST")
        evidence = "Pending email post list and counter updated to 2."
    else:
        expect(page.locator("#pending-count")).to_have_text("0")
        evidence = "Live API mode submitted posts directly; pending email list stayed hidden."

    return [
        "Submitted one FOR post and one AGAINST post.",
        evidence,
    ]


def criterion_ac3(page: Page, base_url: str) -> list[str]:
    authenticate_browser_user(page, base_url)
    create_active_debate_and_open_posting(page, base_url)

    submit_post(
        page,
        "FOR",
        "t1",
        "External audits can identify safety failures before deployment.\nPublished audit findings improve accountability.",
        "Therefore mandatory audits can improve public safety outcomes.",
    )
    submit_post(
        page,
        "AGAINST",
        "t4",
        "Compliance burdens can fall hardest on smaller teams.\nOverly rigid rules can slow experimentation.",
        "Therefore blanket audit mandates can reduce innovation and competition.",
    )

    snapshot = generate_snapshot(page, base_url)

    return [
        f"Generated snapshot {snapshot['snapshot_id']}.",
        f"Verdict banner updated to {snapshot['verdict']}.",
    ]


def criterion_ac4(page: Page, base_url: str) -> list[str]:
    authenticate_browser_user(page, base_url)
    create_active_debate_and_open_posting(page, base_url)

    submit_post(
        page,
        "FOR",
        "t2",
        "Major incidents can impose costs across entire markets.\nThird-party checks can improve institutional trust.",
        "Therefore external audits can produce economic benefits that justify the overhead.",
    )
    submit_post(
        page,
        "AGAINST",
        "t3",
        "Audit standards can vary across governments.\nCompliance duplication increases coordination costs.",
        "Therefore mandatory audits can add friction without global consistency.",
    )

    snapshot = generate_snapshot(page, base_url)

    page.goto(f"{base_url}/topics.html", wait_until="networkidle")
    topic_rows = page.locator('[data-testid^="topic-row-"]')
    expect(topic_rows.first).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    topic_count = topic_rows.count()
    if topic_count < 1:
        raise AssertionError("Topics page did not render any topic rows.")

    page.goto(f"{base_url}/verdict.html", wait_until="networkidle")
    expect(page.locator("#verdict-pill")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    expect(page.locator("#contributions-tbody tr").first).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)

    overall_for = float((page.locator("#overall-for").text_content() or "0").strip())
    overall_against = float((page.locator("#overall-against").text_content() or "0").strip())

    return [
        f"Snapshot {snapshot['snapshot_id']} produced {topic_count} topic rows.",
        f"Verdict page rendered overall scores FOR={overall_for:.2f}, AGAINST={overall_against:.2f}.",
    ]


def criterion_ac5(page: Page, base_url: str) -> list[str]:
    authenticate_browser_user(page, base_url)
    create_debate(page, base_url)

    page.goto(f"{base_url}/admin.html", wait_until="networkidle")
    expect(page.locator("#template-base")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)

    version = f"ac-{unique_suffix()}"
    page.locator("#template-version").fill(version)
    page.locator("#template-base").select_option("minimal")
    page.locator("#save-draft-btn").click()
    expect(page.locator("#admin-action-feedback")).to_contain_text(
        "Draft saved", timeout=SNAPSHOT_TIMEOUT_MS
    )

    page.reload(wait_until="networkidle")
    expect(page.locator("#template-history-tbody")).to_contain_text(
        version, timeout=SNAPSHOT_TIMEOUT_MS
    )

    return [
        f"Saved moderation draft version {version} from admin UI.",
        "Reload confirmed draft persistence in template history.",
    ]


def criterion_ac6(page: Page, base_url: str) -> list[str]:
    authenticate_browser_user(page, base_url)
    create_active_debate_and_open_posting(page, base_url)

    submit_post(
        page,
        "FOR",
        "t1",
        "Independent evaluation can catch unsafe deployment assumptions before public release.",
        "Therefore mandatory auditing can reduce catastrophic deployment risk.",
    )
    submit_post(
        page,
        "AGAINST",
        "t3",
        "Rigid compliance checks can slow beneficial deployment and increase costs.",
        "Therefore mandatory audits can create implementation burdens.",
    )
    snapshot = generate_snapshot(page, base_url)

    page.goto(f"{base_url}/evidence.html", wait_until="networkidle")
    expect(page.locator("#evidence-summary")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)

    page.goto(f"{base_url}/dossier.html", wait_until="networkidle")
    expect(page.locator("#dossier-content")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    expect(page.locator("#dossier-snapshot-id")).to_contain_text(
        "snap_", timeout=SNAPSHOT_TIMEOUT_MS
    )

    page.goto(f"{base_url}/governance.html", wait_until="networkidle")
    expect(page.locator("#governance-content")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    expect(page.locator("#gov-health-tbody tr").first).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)

    return [
        f"Snapshot {snapshot['snapshot_id']} enabled evidence, dossier, and governance surfaces.",
        "Evidence summary, dossier metadata, and governance metrics all rendered from API-backed pages.",
    ]


def _safe_error_text(page: Page) -> str:
    """Return the text of #error-alert if visible, or an empty string."""
    try:
        return (page.locator("#error-alert").text_content(timeout=1000) or "").strip()
    except PlaywrightTimeoutError:
        return ""


def register_user_via_ui(page: Page, base_url: str) -> dict[str, str]:
    suffix = unique_suffix()
    email = f"acceptance_ui_{suffix}@example.com"
    password = "AcceptancePass123"
    display_name = f"UI User {suffix[-6:]}"

    page.goto(f"{base_url}/register.html", wait_until="networkidle")
    expect(page.locator("#register-form")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)

    page.locator("#display_name").fill(display_name)
    page.locator("#email").fill(email)
    page.locator("#password").fill(password)
    page.locator("#confirm_password").fill(password)

    expect(page.locator("#submit-btn")).to_be_enabled(timeout=SNAPSHOT_TIMEOUT_MS)
    with page.expect_response(
        lambda r: "/api/auth/register" in r.url and r.request.method == "POST"
    ) as response_info:
        page.locator("#submit-btn").click()
    response = response_info.value

    if response.status not in {200, 201}:
        error_text = _safe_error_text(page)
        raise AssertionError(
            f"UI registration failed: HTTP {response.status}: "
            f"{response_debug(response)}; error alert={error_text!r}"
        )

    expect(page.locator("#success-alert")).to_contain_text(
        "Account created", timeout=SNAPSHOT_TIMEOUT_MS
    )
    page.wait_for_url(f"{base_url}/index.html*", timeout=SNAPSHOT_TIMEOUT_MS)

    token = page.evaluate("() => localStorage.getItem('access_token')")
    if not token:
        raise AssertionError("Register flow did not persist access_token in localStorage.")

    raw_user = page.evaluate("() => localStorage.getItem('user')")
    if not raw_user or raw_user == "undefined":
        raise AssertionError("Register flow did not persist a valid user payload in localStorage.")

    user = json.loads(raw_user)
    if user.get("email") != email:
        raise AssertionError("Persisted register user payload does not match the created account.")

    return {
        "email": email,
        "password": password,
        "display_name": display_name,
    }


def login_user_via_ui(page: Page, base_url: str, email: str, password: str) -> None:
    page.goto(f"{base_url}/login.html?next=%2Fnew_debate.html", wait_until="networkidle")
    expect(page.locator("#login-form")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    page.locator("#email").fill(email)
    page.locator("#password").fill(password)

    expect(page.locator("#submit-btn")).to_be_enabled(timeout=SNAPSHOT_TIMEOUT_MS)
    with page.expect_response(
        lambda r: "/api/auth/login" in r.url and r.request.method == "POST"
    ) as response_info:
        page.locator("#submit-btn").click()
    response = response_info.value

    if response.status != 200:
        error_text = _safe_error_text(page)
        raise AssertionError(
            f"UI login failed: HTTP {response.status}: "
            f"{response_debug(response)}; error alert={error_text!r}"
        )

    expect(page.locator("#success-alert")).to_contain_text(
        "Login successful", timeout=SNAPSHOT_TIMEOUT_MS
    )
    page.wait_for_url(f"{base_url}/new_debate.html*", timeout=SNAPSHOT_TIMEOUT_MS)

    token = page.evaluate("() => localStorage.getItem('access_token')")
    if not token:
        raise AssertionError("Login flow did not persist access_token in localStorage.")


def criterion_ac7(page: Page, base_url: str) -> list[str]:
    creds = register_user_via_ui(page, base_url)

    # Force a fresh login path after successful registration.
    page.evaluate("() => localStorage.clear()")

    login_user_via_ui(page, base_url, creds["email"], creds["password"])
    # Phase 3: nav shows generic "Account" instead of display_name
    expect(page.locator(".auth-link button")).to_contain_text(
        "Account", timeout=SNAPSHOT_TIMEOUT_MS
    )

    # Validate logout behavior from authenticated UI state.
    page.evaluate("() => Auth.logout()")
    page.wait_for_url(f"{base_url}/login.html?*", timeout=SNAPSHOT_TIMEOUT_MS)
    expect(page.locator("#error-alert")).to_contain_text("logged out", timeout=SNAPSHOT_TIMEOUT_MS)

    token_after_logout = page.evaluate("() => localStorage.getItem('access_token')")
    if token_after_logout:
        raise AssertionError("Logout should clear access_token from localStorage.")

    return [
        f"Registered a user via register.html: {creds['email']}",
        "Logged in via login.html and redirected to /new_debate.html using next=.",
        "Nav shows generic 'Account' label (identity-blind) when authenticated.",
        "Logout cleared local auth/session state and redirected back to login with status messaging.",
    ]


def criterion_ac8(page: Page, base_url: str) -> list[str]:
    authenticate_browser_user(page, base_url)
    create_active_debate_and_open_posting(page, base_url)

    submit_post(
        page,
        "FOR",
        "t1",
        "External model evaluations can detect high-risk failure modes before production rollout.",
        "Therefore mandatory audits can reduce severe deployment incidents.",
    )
    submit_post(
        page,
        "AGAINST",
        "t3",
        "Audit requirements can create uneven burdens across smaller developers.",
        "Therefore universal mandates can reduce competition and slow iteration.",
    )
    snapshot_one = generate_snapshot(page, base_url)

    submit_post(
        page,
        "FOR",
        "t2",
        "Transparent audit disclosures improve institutional accountability and incident response.",
        "Therefore audits can increase trust and reduce downstream remediation costs.",
    )
    snapshot_two = generate_snapshot(page, base_url)

    page.goto(f"{base_url}/snapshot.html", wait_until="networkidle")
    expect(page.locator("#snapshot-content")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    expect(page.locator("#history-tbody tr").first).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    history_rows = page.locator("#history-tbody tr").count()
    if history_rows < 2:
        raise AssertionError(f"Expected at least 2 snapshot history rows, found {history_rows}.")

    expect(page.locator("#diff-content")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    old_id = (page.locator("#diff-old-id").text_content() or "").strip()
    new_id = (page.locator("#diff-new-id").text_content() or "").strip()
    if not old_id.startswith("snap_") or not new_id.startswith("snap_"):
        raise AssertionError(
            "Snapshot diff ids were not populated with expected snapshot identifiers."
        )
    if old_id == new_id:
        raise AssertionError("Snapshot diff old/new ids should differ when two snapshots exist.")

    summary_items = page.locator("#diff-summary-list li").count()
    if summary_items < 3:
        raise AssertionError("Snapshot diff summary did not render enough detail items.")

    return [
        f"Generated two snapshots ({snapshot_one['snapshot_id']}, {snapshot_two['snapshot_id']}) in one debate.",
        f"Snapshot history rendered {history_rows} rows.",
        f"Snapshot diff rendered old/new ids ({old_id} -> {new_id}) with summary list entries.",
    ]


def criterion_ac9(page: Page, base_url: str) -> list[str]:
    """Proposal lifecycle: submit, admin queue, accept."""
    authenticate_browser_user(page, base_url)

    # Submit a proposal via API
    token = page.evaluate("() => localStorage.getItem('access_token')") or ""
    motion = f"Resolved: Test proposal acceptance flow ({unique_suffix()})."
    proposal_response = page.request.post(
        f"{base_url}/api/debate-proposals",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        data=json.dumps(
            {
                "motion": motion,
                "moderation_criteria": "Allow on-topic arguments. Block spam.",
                "debate_frame": "Judge which side presents the stronger case.",
            }
        ),
    )
    if not proposal_response.ok:
        raise AssertionError(f"Proposal submission failed: HTTP {proposal_response.status}")
    proposal_data = proposal_response.json()
    proposal_id = proposal_data["proposal_id"]

    # Verify it appears in my proposals
    mine_response = page.request.get(
        f"{base_url}/api/debate-proposals/mine",
        headers={"Authorization": f"Bearer {token}"},
    )
    if not mine_response.ok:
        raise AssertionError(f"My proposals fetch failed: HTTP {mine_response.status}")
    mine_data = mine_response.json()
    if not any(p["proposal_id"] == proposal_id for p in mine_data.get("proposals", [])):
        raise AssertionError("Submitted proposal did not appear in /mine.")

    # Admin accepts the proposal
    accept_response = page.request.post(
        f"{base_url}/api/admin/debate-proposals/{proposal_id}/accept",
        headers={"Authorization": f"Bearer {token}"},
    )
    if not accept_response.ok:
        raise AssertionError(f"Proposal accept failed: HTTP {accept_response.status}")
    accept_data = accept_response.json()
    debate_id = accept_data["debate_id"]

    # Verify proposal status updated
    proposal_check = page.request.get(
        f"{base_url}/api/admin/debate-proposals",
        headers={"Authorization": f"Bearer {token}"},
    )
    proposals = proposal_check.json().get("proposals", [])
    match = next((p for p in proposals if p["proposal_id"] == proposal_id), None)
    if not match or match["status"] != "accepted":
        raise AssertionError("Proposal status was not updated to accepted.")

    return [
        f"Submitted proposal {proposal_id}.",
        f"Admin accepted proposal and created debate {debate_id}.",
        "Proposal flow end-to-end verified.",
    ]


def criterion_ac10(page: Page, base_url: str) -> list[str]:
    """Identity-blind public surface: no display_name or email in nav."""
    user = authenticate_browser_user(page, base_url)

    page.goto(f"{base_url}/index.html", wait_until="networkidle")
    nav = page.locator(".navlinks")
    expect(nav).to_be_visible()

    nav_text = (nav.text_content() or "").strip()
    if user["display_name"] in nav_text:
        raise AssertionError("Nav should not reveal display_name in public blind mode.")
    if user["email"] in nav_text:
        raise AssertionError("Nav should not reveal email in public blind mode.")

    # Generic "Account" indicator should be present
    if "Account" not in nav_text:
        raise AssertionError("Nav should show generic 'Account' indicator when authenticated.")

    return [
        "Authenticated user sees generic 'Account' label, not personal identifiers.",
        "Verified absence of display_name and email in nav text.",
    ]


def criterion_ac11(page: Page, base_url: str) -> list[str]:
    """Snapshot integrity fields visible in UI."""
    authenticate_browser_user(page, base_url)
    create_active_debate_and_open_posting(page, base_url)

    submit_post(
        page,
        "FOR",
        "t1",
        "External audits improve safety.",
        "Therefore mandatory audits reduce risk.",
    )
    submit_post(
        page,
        "AGAINST",
        "t3",
        "Audits add compliance burden.",
        "Therefore mandates slow innovation.",
    )
    snapshot = generate_snapshot(page, base_url)

    page.goto(f"{base_url}/snapshot.html", wait_until="networkidle")
    expect(page.locator("#snapshot-content")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    expect(page.locator("#integrity-input-hash")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    expect(page.locator("#integrity-output-hash")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    expect(page.locator("#integrity-recipe-versions")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)

    input_hash = (page.locator("#integrity-input-hash").text_content() or "").strip()
    if input_hash == "-" or len(input_hash) < 16:
        raise AssertionError("Input hash root should be populated with a hash value.")

    return [
        "Snapshot page renders integrity fields.",
        f"Input hash root populated: {input_hash[:16]}…",
    ]


CRITERION_RUNNERS: dict[str, Callable[[Page, str], list[str]]] = {
    "AC-1": criterion_ac1,
    "AC-2": criterion_ac2,
    "AC-3": criterion_ac3,
    "AC-4": criterion_ac4,
    "AC-5": criterion_ac5,
    "AC-6": criterion_ac6,
    "AC-7": criterion_ac7,
    "AC-8": criterion_ac8,
    "AC-9": criterion_ac9,
    "AC-10": criterion_ac10,
    "AC-11": criterion_ac11,
}


def run_criterion(page: Page, base_url: str, criterion: dict, screenshots_dir: Path) -> dict:
    criterion_id = criterion["id"]
    runner = CRITERION_RUNNERS.get(criterion_id)
    if runner is None:
        raise KeyError(f"No browser runner is defined for acceptance criterion {criterion_id}.")

    started_at = time.time()
    screenshot_path = screenshots_dir / f"{criterion_id.lower()}-result.png"

    try:
        evidence = runner(page, base_url)
        page.screenshot(path=str(screenshot_path), full_page=True)
        return {
            "id": criterion_id,
            "title": criterion["title"],
            "passed": True,
            "duration_ms": round((time.time() - started_at) * 1000),
            "evidence": evidence,
            "screenshot": str(screenshot_path.relative_to(REPO_ROOT)),
        }
    except (AssertionError, PlaywrightTimeoutError) as exc:
        page.screenshot(path=str(screenshot_path), full_page=True)
        return {
            "id": criterion_id,
            "title": criterion["title"],
            "passed": False,
            "duration_ms": round((time.time() - started_at) * 1000),
            "error": str(exc),
            "screenshot": str(screenshot_path.relative_to(REPO_ROOT)),
        }
    except Exception as exc:
        page.screenshot(path=str(screenshot_path), full_page=True)
        return {
            "id": criterion_id,
            "title": criterion["title"],
            "passed": False,
            "duration_ms": round((time.time() - started_at) * 1000),
            "error": str(exc),
            "screenshot": str(screenshot_path.relative_to(REPO_ROOT)),
        }


def build_markdown_report(spec: dict, report: dict) -> list[str]:
    lines = [
        "# UI Acceptance Report",
        "",
        f"Task: {spec['task']}",
        f"Base URL: {report['base_url']}",
        f"Run started: {report['started_at']}",
        f"Summary: {report['passed_count']}/{report['total_count']} passed",
        "",
        "| ID | Title | Result | Notes | Screenshot |",
        "| --- | --- | --- | --- | --- |",
    ]

    for result in report["results"]:
        notes = "; ".join(result.get("evidence", [])) or result.get("error", "")
        screenshot = result.get("screenshot", "")
        outcome = "PASS" if result["passed"] else "FAIL"
        lines.append(f"| {result['id']} | {result['title']} | {outcome} | {notes} | {screenshot} |")

    return lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run browser-driven acceptance checks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5080")
    parser.add_argument("--spec", default=str(DEFAULT_SPEC_PATH))
    parser.add_argument("--artifacts-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--headed", action="store_true", help="Run Chromium with a visible UI.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec)
    artifacts_dir = Path(args.artifacts_dir)
    screenshots_dir = artifacts_dir / "screenshots"

    ensure_dir(artifacts_dir)
    ensure_dir(screenshots_dir)

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    started_at = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)

        try:
            seed_acceptance_admin(browser, args.base_url)

            for criterion in spec["criteria"]:
                context = browser.new_context(viewport={"width": 1440, "height": 1200})
                page = context.new_page()
                page.set_default_timeout(DEFAULT_TIMEOUT_MS)
                results.append(run_criterion(page, args.base_url, criterion, screenshots_dir))
                context.close()
        finally:
            browser.close()

    passed_count = sum(1 for result in results if result["passed"])
    report = {
        "feature": spec["feature"],
        "task": spec["task"],
        "base_url": args.base_url,
        "started_at": started_at,
        "total_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "results": results,
    }

    write_json(artifacts_dir / "ui_acceptance_report.json", report)
    write_markdown(artifacts_dir / "ui_acceptance_report.md", build_markdown_report(spec, report))

    if passed_count != len(results):
        return 1

    print(f"UI acceptance passed: {passed_count}/{len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
