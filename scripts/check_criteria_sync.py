#!/usr/bin/env python3
"""Lightweight doc-sync guard-rail for criteria vs acceptance drift."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

CRITERIA_TO_ACCEPTANCE = {
    "LSD-UI-01": ["AC-10"],
    "LSD-UI-03": ["AC-11"],
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check criteria JSON and acceptance report for doc drift."
    )
    parser.add_argument(
        "--criteria",
        default="acceptance/lsd_v1_2_criteria.json",
        help="Path to criteria JSON file",
    )
    parser.add_argument(
        "--report",
        default="artifacts/acceptance/ui_acceptance_report.json",
        help="Path to UI acceptance report JSON",
    )
    parser.add_argument(
        "--max-review-age-days",
        type=int,
        default=7,
        help="Maximum age of last_reviewed before warning",
    )
    parser.add_argument(
        "--fail-on-stale-review",
        action="store_true",
        help="Treat stale last_reviewed as a failure",
    )
    args = parser.parse_args()

    has_error = False
    has_stale_warning = False

    # 1. Load criteria JSON
    criteria_path = Path(args.criteria)
    if not criteria_path.exists():
        print(f"ERROR: Criteria file not found: {criteria_path}", file=sys.stdout)
        return 1

    with criteria_path.open("r", encoding="utf-8") as f:
        criteria_data = json.load(f)

    criteria_list = criteria_data.get("criteria")
    if not isinstance(criteria_list, list):
        print("ERROR: Top-level 'criteria' key is missing or not a list", file=sys.stdout)
        return 1

    status_counts: dict[str, int] = {}
    for c in criteria_list:
        status = c.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    counts_str = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()))
    print(f"INFO: Criteria status counts: {counts_str}")

    # 2. Check last_reviewed
    last_reviewed = criteria_data.get("last_reviewed")
    max_age = args.max_review_age_days
    if last_reviewed:
        try:
            reviewed_date = datetime.strptime(last_reviewed, "%Y-%m-%d").date()
            age_days = (datetime.now().date() - reviewed_date).days
            if age_days > max_age:
                print(
                    f"WARNING: last_reviewed ({last_reviewed}) is stale or missing "
                    f"(older than {max_age} days)"
                )
                has_stale_warning = True
            else:
                print(f"INFO: last_reviewed ({last_reviewed}) is within {max_age} days")
        except ValueError:
            print(
                f"WARNING: last_reviewed ({last_reviewed}) is stale or missing "
                f"(older than {max_age} days)"
            )
            has_stale_warning = True
    else:
        print(
            f"WARNING: last_reviewed (missing) is stale or missing " f"(older than {max_age} days)"
        )
        has_stale_warning = True

    # 3. Load acceptance report
    report_path = Path(args.report)
    result_by_id: dict[str, dict] = {}
    if report_path.exists():
        with report_path.open("r", encoding="utf-8") as f:
            report = json.load(f)

        total_count = report.get("total_count")
        passed_count = report.get("passed_count")
        results = report.get("results")
        started_at = report.get("started_at", "unknown")

        if total_count is None or passed_count is None or not isinstance(results, list):
            print("ERROR: Acceptance report missing required fields", file=sys.stdout)
            has_error = True
        else:
            print(
                f"INFO: Acceptance report: {passed_count}/{total_count} passed " f"({started_at})"
            )
            for r in results:
                ac_id = r.get("id")
                if ac_id:
                    result_by_id[ac_id] = r
    else:
        print("INFO: Acceptance report not found; skipping acceptance sync checks.")

    # 4. Check mappings
    criteria_by_id = {c["id"]: c for c in criteria_list if "id" in c}
    for criterion_id, ac_ids in CRITERIA_TO_ACCEPTANCE.items():
        criterion = criteria_by_id.get(criterion_id)
        if criterion is None:
            print(f"WARNING: Criterion {criterion_id} not found in criteria list")
            continue

        status = criterion.get("status", "unknown")
        for ac_id in ac_ids:
            ac_result = result_by_id.get(ac_id)
            if ac_result is None:
                print(
                    f"WARNING: Mapped acceptance {ac_id} for {criterion_id} " f"not found in report"
                )
                continue

            passed = ac_result.get("passed", False)
            if status == "deferred" and passed:
                print(f"ERROR: {criterion_id} is deferred but mapped acceptance {ac_id} passed")
                has_error = True
            elif status == "pass" and not passed:
                print(f"ERROR: {criterion_id} is pass but mapped acceptance {ac_id} failed")
                has_error = True

    # 6. Exit code
    if has_error:
        return 1
    if args.fail_on_stale_review and has_stale_warning:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
