#!/usr/bin/env python3
"""Generate LSD v1.2 compliance artifacts from acceptance criteria."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CRITERIA_PATH = ROOT / "acceptance" / "lsd_v1_2_criteria.json"
OUT_DIR = ROOT / "docs" / "compliance"
REPORT_MD = OUT_DIR / "LSD_v1_2_compliance_report.md"
REPORT_JSON = OUT_DIR / "LSD_v1_2_compliance_report.json"


EVIDENCE_LINKS = {
    "LSD-UI-01": ["acceptance/lsd_v1_2_criteria.json"],
    "LSD-UI-02": ["backend/debate_engine_v2.py", "frontend/snapshot.html", "frontend/admin.html"],
    "LSD-UI-03": ["backend/debate_engine_v2.py", "frontend/snapshot.html"],
    "LSD-UI-04": ["backend/app_v3.py", "frontend/governance.html", "frontend/frame-dossier.html"],
    "LSD-UI-05": ["backend/scoring_engine.py", "frontend/topics.html", "frontend/audits.html"],
    "LSD-UI-06": ["backend/extraction.py", "backend/selection_engine.py", "frontend/audits.html"],
    "LSD-UI-07": ["backend/lsd_v1_2.py", "backend/debate_engine_v2.py", "frontend/audits.html"],
    "LSD-UI-08": ["backend/app_v3.py", "frontend/verdict.html", "frontend/dossier.html"],
    "LSD-UI-09": ["backend/debate_engine_v2.py", "frontend/audits.html", "test_lsd_v1_2_contracts.py"],
    "LSD-UI-10": ["backend/governance.py", "frontend/governance.html", "frontend/dossier.html"],
}


def main() -> int:
    criteria_doc = json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))
    criteria = criteria_doc.get("criteria", [])
    counts = Counter(item.get("status", "unknown") for item in criteria)

    rows = []
    undocumented = []
    for item in criteria:
        status = item.get("status", "unknown")
        cid = item.get("id", "")
        evidence = item.get("evidence_links") or EVIDENCE_LINKS.get(cid, [])
        if status in {"partial", "missing"} and not item.get("deferral"):
            undocumented.append(cid)
        rows.append({
            "id": cid,
            "title": item.get("title", ""),
            "section": item.get("section", ""),
            "status": status,
            "evidence_links": evidence,
            "deferral": item.get("deferral"),
        })

    report = {
        "source_version": criteria_doc.get("source_version", "LSD v1.2"),
        "summary": dict(counts),
        "undocumented_partial_or_missing": undocumented,
        "criteria": rows,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# LSD v1.2 Compliance Report",
        "",
        f"Source version: `{report['source_version']}`",
        "",
        "## Summary",
        "",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Criteria", ""])
    for row in rows:
        evidence = ", ".join(f"`{path}`" for path in row["evidence_links"]) or "No evidence link"
        deferral = f" Deferral: {row['deferral']['rationale']}" if row.get("deferral") else ""
        lines.append(
            f"- `{row['id']}` {row['title']} ({row['section']}): **{row['status']}**. Evidence: {evidence}.{deferral}"
        )
    if undocumented:
        lines.extend(["", "## Action Required", "", f"Undocumented partial/missing criteria: {', '.join(undocumented)}"])
    else:
        lines.extend(["", "## Action Required", "", "No partial or missing criteria remain without a deferral note."])

    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT_MD}")
    print(f"Wrote {REPORT_JSON}")
    return 1 if undocumented else 0


if __name__ == "__main__":
    raise SystemExit(main())
