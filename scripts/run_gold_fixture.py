#!/usr/bin/env python3
"""
Run the fact-checking skill against the gold fixture claims.

Usage:
    python scripts/run_gold_fixture.py [mode]

Modes:
    OFFLINE           (default) — no live lookups
    PERFECT           — strict v1 contract with Wikidata snapshot backend
    ONLINE_ALLOWLIST  — experimental async-capable mode
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from skills.fact_checking import (
    FactCheckingSkill,
    FactCheckVerdict,
    WikidataConnector,
)

GOLD_PATH = REPO_ROOT / "skills" / "fact_checking" / "testdata" / "fact_check_gold_v1.jsonl"


def load_gold_cases():
    with open(GOLD_PATH, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def run_gold_cases(mode: str = "OFFLINE"):
    cases = load_gold_cases()
    print(f"Loaded {len(cases)} gold cases")
    print(f"Fact-check mode: {mode}")
    print("-" * 70)

    kwargs = dict(mode=mode, allowlist_version="v1", enable_async=False)
    if mode in ("PERFECT", "PERFECT_CHECKER"):
        kwargs["connectors"] = [WikidataConnector()]

    skill = FactCheckingSkill(**kwargs)

    correct = 0
    wrong = 0
    errors = 0

    try:
        for case in cases:
            claim_id = case["id"]
            claim_text = case["claim_text"]
            expected = case["expected_verdict"]

            try:
                result = skill.check_fact(claim_text)
                actual = result.verdict.value

                status = "✓" if actual == expected else "✗"
                if actual == expected:
                    correct += 1
                else:
                    wrong += 1

                print(
                    f"{status} {claim_id}: {claim_text[:55]:<55} "
                    f"expected={expected:<13} actual={actual:<13} "
                    f"reason={result.diagnostics.get('reason_code', 'N/A')}"
                )
            except Exception as exc:
                errors += 1
                print(f"! {claim_id}: ERROR — {exc}")
    finally:
        skill.shutdown()

    print("-" * 70)
    total = len(cases)
    print(f"Results: {correct}/{total} correct, {wrong} wrong, {errors} errors")
    if total > 0:
        print(f"Accuracy: {correct / total:.1%}")

    return wrong == 0 and errors == 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "OFFLINE"
    ok = run_gold_cases(mode)
    sys.exit(0 if ok else 1)
