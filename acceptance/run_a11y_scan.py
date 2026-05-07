#!/usr/bin/env python3
"""
Automated accessibility scan for the Blind Debate Adjudicator frontend.

Runs axe-core via Playwright against representative pages and reports
violations at the chosen impact threshold.
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover - helpful runtime message
    raise SystemExit(
        "Playwright is not installed. Run `pip install -r requirements-test.txt` and "
        "`python -m playwright install chromium` first."
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
AXE_PATH = REPO_ROOT / "node_modules" / "axe-core" / "axe.min.js"

DEFAULT_PAGES = [
    "/",
    "/login.html",
    "/register.html",
    "/new_debate.html",
    "/admin.html",
    "/appeals.html",
    "/governance.html",
    "/topics.html",
]


def load_axe_source() -> str:
    if not AXE_PATH.exists():
        raise SystemExit(f"axe-core not found at {AXE_PATH}. Run `npm ci` first.")
    return AXE_PATH.read_text(encoding="utf-8")


def run_axe_on_page(page, axe_source: str, impact_levels: list[str]) -> list[dict]:
    """Inject axe and run it, returning filtered violations."""
    page.evaluate(axe_source)
    # axe.run returns a Promise; evaluate_handle lets us await it properly.
    result = page.evaluate(
        """
        async (impactLevels) => {
            const results = await axe.run(document, {
                resultTypes: ['violations']
            });
            return results.violations.filter(v => impactLevels.includes(v.impact));
        }
        """,
        impact_levels,
    )
    return result


def format_violation(violation: dict) -> str:
    nodes = violation.get("nodes", [])
    targets = []
    for node in nodes[:3]:
        target = node.get("target", [])
        if isinstance(target, list) and target:
            targets.append(str(target[0]))
        else:
            targets.append(str(target))
    if len(nodes) > 3:
        targets.append(f"... and {len(nodes) - 3} more")
    target_str = ", ".join(targets) if targets else "(page)"
    return f"  - {violation['id']} ({violation['impact']}): {violation['help']} — {target_str}"


def scan_page(
    page, base_url: str, path: str, axe_source: str, impact_levels: list[str]
) -> tuple[list[dict], float]:
    url = f"{base_url.rstrip('/')}{path}"
    page.goto(url, wait_until="networkidle")
    # Give a short grace period for any lazy-rendered content.
    page.wait_for_timeout(500)
    violations = run_axe_on_page(page, axe_source, impact_levels)
    return violations, page.evaluate("() => document.title")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Accessibility scan for the Blind Debate Adjudicator frontend.",
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL of the running application (e.g., http://127.0.0.1:5080)",
    )
    parser.add_argument(
        "--impact",
        default="critical",
        help="Comma-separated impact levels to treat as failures (default: critical)",
    )
    parser.add_argument(
        "--pages",
        default=",".join(DEFAULT_PAGES),
        help="Comma-separated list of paths to scan",
    )
    args = parser.parse_args()

    impact_levels = [level.strip().lower() for level in args.impact.split(",")]
    pages = [p.strip() for p in args.pages.split(",") if p.strip()]

    axe_source = load_axe_source()
    total_violations = 0
    results: list[tuple[str, list[dict], str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()

        for path in pages:
            try:
                violations, title = scan_page(page, args.base_url, path, axe_source, impact_levels)
            except Exception as exc:
                print(f"\n[{path}] ERROR: {exc}")
                return 1
            results.append((path, violations, title))
            total_violations += len(violations)

        browser.close()

    # Print concise summary
    for path, violations, title in results:
        status = (
            "PASS"
            if not violations
            else f"FAIL ({len(violations)} violation{'s' if len(violations) != 1 else ''})"
        )
        print(f"\n{path} — {status}")
        if title:
            print(f"  Title: {title}")
        for v in violations:
            print(format_violation(v))

    print(f"\n{'=' * 50}")
    print(f"Total pages scanned: {len(pages)}")
    print(f"Total violations at '{args.impact}' level: {total_violations}")
    print(f"Overall result: {'PASS' if total_violations == 0 else 'FAIL'}")

    return min(total_violations, 255) if total_violations > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
