#!/usr/bin/env python3
"""
Browser-driven acceptance verification for the Blind Debate Adjudicator.

The suite is intentionally organized around named acceptance criteria so the
report reads like a pass/fail checklist instead of a raw test log.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Callable, Dict, List

try:
    from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, expect, sync_playwright
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


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_markdown(path: Path, lines: List[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def open_new_debate_page(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/new_debate.html", wait_until="networkidle")
    expect(page.get_by_test_id("create-debate-section")).to_be_visible()


def create_debate(page: Page, base_url: str) -> Dict[str, str]:
    open_new_debate_page(page, base_url)

    resolution = f"Resolved: External AI audits should be mandatory ({unique_suffix()})."
    scope = (
        "Whether mandatory external audits improve safety, accountability, and "
        "public trust enough to justify the operational burden."
    )

    page.get_by_test_id("debate-resolution-input").fill(resolution)
    page.get_by_test_id("debate-scope-input").fill(scope)
    page.get_by_test_id("create-debate-button").click()

    expect(page.get_by_test_id("status-message")).to_contain_text("Debate created")
    expect(page.get_by_test_id("active-debate-resolution")).to_contain_text(resolution)

    return {"resolution": resolution, "scope": scope}


def submit_post(page: Page, side: str, topic_id: str, facts: str, inference: str) -> None:
    page.locator(f'input[name="side"][value="{side}"]').check(force=True)
    page.locator("#argument-topic").select_option(topic_id)
    page.locator("#facts-input").fill(facts)
    page.locator("#inference-input").fill(inference)
    page.locator("#counter-input").fill("")
    page.get_by_test_id("submit-post-button").click()
    expect(page.get_by_test_id("status-message")).to_contain_text("Post submitted and allowed")


def generate_snapshot(page: Page) -> Dict[str, str]:
    page.get_by_test_id("generate-snapshot-button").click()
    expect(page.get_by_test_id("status-message")).to_contain_text("generated", timeout=SNAPSHOT_TIMEOUT_MS)
    expect(page.get_by_test_id("pending-count")).to_have_text("0", timeout=SNAPSHOT_TIMEOUT_MS)

    snapshot_id = (page.locator("#header-snapshot").text_content() or "").strip()
    verdict = (page.locator("#header-verdict").text_content() or "").strip()

    if not snapshot_id or snapshot_id == "-":
        raise AssertionError("Snapshot id did not populate after generation.")
    if verdict not in {"FOR", "AGAINST", "NO VERDICT"}:
        raise AssertionError(f"Unexpected verdict value: {verdict!r}")

    return {"snapshot_id": snapshot_id, "verdict": verdict}


def criterion_ac1(page: Page, base_url: str) -> List[str]:
    open_new_debate_page(page, base_url)
    expect(page.get_by_test_id("create-debate-state")).to_contain_text("No active debate")
    expect(page.get_by_test_id("runtime-mode")).to_contain_text("Guest posting")

    debate = create_debate(page, base_url)
    expect(page.get_by_test_id("post-access-hint")).to_contain_text("Guest posting is enabled")

    return [
        f"Created debate via the browser: {debate['resolution']}",
        "Posting unlocked after debate creation.",
    ]


def criterion_ac2(page: Page, base_url: str) -> List[str]:
    create_debate(page, base_url)

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

    expect(page.get_by_test_id("pending-count")).to_have_text("2")
    expect(page.get_by_test_id("posts-list")).to_contain_text("FOR")
    expect(page.get_by_test_id("posts-list")).to_contain_text("AGAINST")

    return [
        "Submitted one FOR post and one AGAINST post.",
        "Pending post list and counter updated to 2.",
    ]


def criterion_ac3(page: Page, base_url: str) -> List[str]:
    create_debate(page, base_url)

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

    snapshot = generate_snapshot(page)

    return [
        f"Generated snapshot {snapshot['snapshot_id']}.",
        f"Verdict banner updated to {snapshot['verdict']}.",
    ]


def criterion_ac4(page: Page, base_url: str) -> List[str]:
    create_debate(page, base_url)

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

    snapshot = generate_snapshot(page)

    page.goto(f"{base_url}/topics.html", wait_until="networkidle")
    topic_rows = page.locator('[data-testid^="topic-row-"]')
    expect(topic_rows.first).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    topic_count = topic_rows.count()
    if topic_count < 1:
        raise AssertionError("Topics page did not render any topic rows.")

    page.goto(f"{base_url}/verdict.html", wait_until="networkidle")
    expect(page.get_by_test_id("verdict-pill")).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)
    expect(page.get_by_test_id("contributions-tbody").locator("tr").first).to_be_visible(timeout=SNAPSHOT_TIMEOUT_MS)

    overall_for = float((page.get_by_test_id("overall-for").text_content() or "0").strip())
    overall_against = float((page.get_by_test_id("overall-against").text_content() or "0").strip())

    return [
        f"Snapshot {snapshot['snapshot_id']} produced {topic_count} topic rows.",
        f"Verdict page rendered overall scores FOR={overall_for:.2f}, AGAINST={overall_against:.2f}.",
    ]


CRITERION_RUNNERS: Dict[str, Callable[[Page, str], List[str]]] = {
    "AC-1": criterion_ac1,
    "AC-2": criterion_ac2,
    "AC-3": criterion_ac3,
    "AC-4": criterion_ac4,
}


def run_criterion(page: Page, base_url: str, criterion: Dict, screenshots_dir: Path) -> Dict:
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


def build_markdown_report(spec: Dict, report: Dict) -> List[str]:
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
