#!/usr/bin/env python3
"""
Stateful agentic workflow runner for debate_system.

This layer sits above the lower-level dev executor and adds:
- human checkpoints
- resumable workflow phases
- prompt logging
- scaffold summaries for low-context retrieval
- workflow improvement reviews based on prompt history
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import sys
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / "workflow_state"
SCAFFOLD_DIR = WORKFLOW_DIR / "scaffolding"
PHASE_DIR = WORKFLOW_DIR / "phases"
CURRENT_DIR = WORKFLOW_DIR / "current"
REVIEW_DIR = WORKFLOW_DIR / "reviews"
HUMAN_LOG_DIR = WORKFLOW_DIR / "human_logs"
STATE_PATH = WORKFLOW_DIR / "state.json"
PROMPT_LOG_PATH = WORKFLOW_DIR / "prompt_log.jsonl"
WORKFLOW_DOC = REPO_ROOT / "docs/workflow/WORKFLOW.md"
HUMAN_PROMPTS_PATH = HUMAN_LOG_DIR / "human_prompts.md"
APPROVALS_PATH = HUMAN_LOG_DIR / "approvals.md"
REJECTIONS_PATH = HUMAN_LOG_DIR / "rejections.md"
REQUIREMENT_CHANGES_PATH = HUMAN_LOG_DIR / "requirement_changes.md"
MANUAL_OVERRIDES_PATH = HUMAN_LOG_DIR / "manual_overrides.md"

PHASES: list[dict[str, Any]] = [
    {
        "id": "system-design",
        "title": "System Design",
        "objective": "Define architecture, constraints, success criteria, and the first implementation slice.",
        "human_checkpoint": "Review the system design, validate scope, and approve the module split.",
        "deliverables": [
            "workflow_state/phases/01-system-design.md",
            "Updated open questions when scope is unclear.",
        ],
        "context_files": [
            "docs/workflow/WORKFLOW.md",
            "workflow_state/scaffolding/project_summary.md",
            "workflow_state/scaffolding/module_map.md",
            "workflow_state/scaffolding/human_checkpoints.md",
            "README.md",
            "docs/archive/README_v2.md",
        ],
    },
    {
        "id": "module-breakdown",
        "title": "Module Breakdown",
        "objective": "Break the work into bounded modules with ownership, dependencies, and validation gates.",
        "human_checkpoint": "Approve the module boundaries and the order of execution.",
        "deliverables": [
            "workflow_state/phases/02-module-breakdown.md",
            "Updated retrieval index mapping modules to files.",
        ],
        "context_files": [
            "workflow_state/scaffolding/module_map.md",
            "workflow_state/scaffolding/retrieval_index.md",
            "workflow_state/scaffolding/project_summary.md",
            "backend/",
            "scripts/",
            "test_debate_system.py",
        ],
    },
    {
        "id": "module-design",
        "title": "Module Design",
        "objective": "Design the next module in enough detail to implement safely with minimal backtracking.",
        "human_checkpoint": "Review the design note or prototype before implementation begins.",
        "deliverables": [
            "workflow_state/phases/03-module-design.md",
            "A concise implementation plan for the active slice.",
        ],
        "context_files": [
            "workflow_state/scaffolding/retrieval_index.md",
            "workflow_state/scaffolding/open_questions.md",
            "workflow_state/phases/02-module-breakdown.md",
            "Relevant backend or frontend files for the active module.",
        ],
    },
    {
        "id": "module-implementation",
        "title": "Module Implementation",
        "objective": "Implement the approved module while updating summaries for the next phase.",
        "human_checkpoint": "Review the prototype or patch before broad testing or expansion.",
        "deliverables": [
            "workflow_state/phases/04-module-implementation.md",
            "Code changes for the approved module.",
        ],
        "context_files": [
            "workflow_state/current/next_prompt.md",
            "workflow_state/scaffolding/retrieval_index.md",
            "scripts/dev_workflow.py",
            "Relevant code files for the active module.",
        ],
    },
    {
        "id": "module-testing",
        "title": "Module Testing",
        "objective": "Verify the implementation with focused tests, smoke checks, and issue triage.",
        "human_checkpoint": "Review test results, failures, and risk before broad integration.",
        "deliverables": [
            "workflow_state/phases/05-module-testing.md",
            "Focused verification notes and follow-up fixes.",
        ],
        "context_files": [
            "workflow_state/scaffolding/test_surface.md",
            "scripts/dev_workflow.py",
            "test_debate_system.py",
            "test_fact_check_skill.py",
            "manual_scenarios.py",
        ],
    },
    {
        "id": "integration-testing",
        "title": "Integration Testing",
        "objective": "Run the end-to-end validation path, update CI assumptions, and summarize residual risks.",
        "human_checkpoint": "Approve the integrated result or request another iteration.",
        "deliverables": [
            "workflow_state/phases/06-integration-testing.md",
            "Final summary of validation status and residual risks.",
        ],
        "context_files": [
            "workflow_state/scaffolding/test_surface.md",
            ".github/workflows/ci.yml",
            "scripts/dev_workflow.py",
            "workflow_state/reviews/workflow_improvements.md",
        ],
    },
]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def ensure_dirs() -> None:
    for path in (WORKFLOW_DIR, SCAFFOLD_DIR, PHASE_DIR, CURRENT_DIR, REVIEW_DIR, HUMAN_LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
    ensure_human_log_files()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=False))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        raise RuntimeError('Workflow state not found. Run `./wf bootstrap --goal "..."` first.')
    return read_json(STATE_PATH)


def relative_label(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def module_docstring(path: Path) -> str:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree)
    except (OSError, SyntaxError, UnicodeDecodeError):
        doc = None
    return first_sentence(doc or "No module summary available.")


def first_sentence(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return ""
    for marker in (". ", "\n", " - "):
        if marker in cleaned:
            return cleaned.split(marker, 1)[0].strip().rstrip(".")
    return cleaned[:160].rstrip(".")


def md_table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body_lines = ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return (
        "\n".join([header_line, separator, *body_lines])
        if body_lines
        else "\n".join([header_line, separator])
    )


def ensure_human_log_files() -> None:
    templates = {
        HUMAN_PROMPTS_PATH: (
            "Human Prompts",
            "Faithful summaries of the human instructions received while the workflow is active.",
        ),
        APPROVALS_PATH: (
            "Approvals",
            "Explicit human approvals that allow the workflow to advance to the next phase.",
        ),
        REJECTIONS_PATH: (
            "Rejections",
            "Human checkpoint rejections that keep the workflow in the current phase for revision.",
        ),
        REQUIREMENT_CHANGES_PATH: (
            "Requirement Changes",
            "Requirement changes that must be analyzed and may rewind the workflow to replanning.",
        ),
        MANUAL_OVERRIDES_PATH: (
            "Manual Overrides",
            "Manual workflow overrides that do not fit the normal advance-or-rewind path.",
        ),
    }
    for path, (title, description) in templates.items():
        if path.exists():
            continue
        write_text(
            path,
            "\n".join(
                [
                    f"# {title}",
                    "",
                    description,
                ]
            ),
        )


def active_phase_label(state: dict[str, Any] | None) -> str:
    if not state:
        return "no active workflow"
    return state.get("current_phase") or "no active workflow"


def append_markdown_log(path: Path, heading: str, lines: Iterable[str]) -> None:
    ensure_dirs()
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n\n")
        handle.write(f"## {heading}\n\n")
        for line in lines:
            handle.write(f"- {line}\n")


def log_human_prompt_entry(text: str, state: dict[str, Any] | None, kind: str) -> None:
    append_markdown_log(
        HUMAN_PROMPTS_PATH,
        now_iso(),
        [
            f"Phase: `{active_phase_label(state)}`",
            f"Kind: `{kind}`",
            f"Prompt: {text.strip()}",
        ],
    )


def log_approval_entry(note: str, phase_id: str) -> None:
    append_markdown_log(
        APPROVALS_PATH,
        now_iso(),
        [
            f"Phase: `{phase_id}`",
            f"Approval: {note.strip()}",
        ],
    )


def log_rejection_entry(note: str, phase_id: str) -> None:
    append_markdown_log(
        REJECTIONS_PATH,
        now_iso(),
        [
            f"Phase: `{phase_id}`",
            f"Rejection: {note.strip()}",
        ],
    )


def log_requirement_change_entry(text: str, from_phase: str) -> None:
    append_markdown_log(
        REQUIREMENT_CHANGES_PATH,
        now_iso(),
        [
            f"Previous phase: `{from_phase}`",
            f"Requirement change: {text.strip()}",
        ],
    )


def log_manual_override_entry(text: str, state: dict[str, Any] | None) -> None:
    append_markdown_log(
        MANUAL_OVERRIDES_PATH,
        now_iso(),
        [
            f"Phase: `{active_phase_label(state)}`",
            f"Override: {text.strip()}",
        ],
    )


def append_prompt_log(
    kind: str, text: str, state: dict[str, Any] | None = None, extra: dict[str, Any] | None = None
) -> None:
    ensure_dirs()
    entry: dict[str, Any] = {
        "timestamp": now_iso(),
        "kind": kind,
        "text": text.strip(),
    }
    if state:
        entry["phase"] = state.get("current_phase")
    if extra:
        entry.update(extra)
    with PROMPT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=False) + "\n")


def read_prompt_log() -> list[dict[str, Any]]:
    if not PROMPT_LOG_PATH.exists():
        return []
    entries = []
    for line in PROMPT_LOG_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            entries.append(json.loads(stripped))
    return entries


def discover_key_directories() -> list[list[str]]:
    rows = []
    candidates = [
        ("backend", "Core API, engines, storage, and debate logic."),
        ("frontend", "Static product interface and admin pages."),
        ("skills", "Domain-specific subsystems and the Codex workflow skill bundle."),
        ("scripts", "Automation entry points and workflow runners."),
        ("data", "SQLite persistence and local runtime state."),
        (".github/workflows", "CI automation."),
    ]
    for rel, purpose in candidates:
        path = REPO_ROOT / rel
        if path.exists():
            rows.append([rel, purpose])
    return rows


def discover_python_rows(directory: Path) -> list[list[str]]:
    if not directory.exists():
        return []
    rows = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("__pycache__"):
            continue
        rows.append([relative_label(path), module_docstring(path)])
    return rows


def discover_frontend_rows(directory: Path) -> list[list[str]]:
    if not directory.exists():
        return []
    rows = []
    for path in sorted(directory.glob("*.html")):
        label = path.stem.replace("_", " ")
        rows.append([relative_label(path), label])
    return rows


def scaffold_project_summary(goal: str) -> str:
    lines = [
        "# Project Summary",
        "",
        f"Generated: {now_iso()}",
        f"Workflow goal: {goal}",
        "",
        "## Repo Shape",
        "",
        md_table(["Path", "Purpose"], discover_key_directories()),
        "",
        "## Existing Execution Surfaces",
        "",
        "- `scripts/dev_workflow.py`: low-level executor for setup, tests, server startup, and smoke checks.",
        "- `Makefile`: convenience wrappers around the low-level executor.",
        "- `start_server.py`, `start_server_v2.py`, `start_server_fast.py`: app entry points.",
        "- `test_debate_system.py`, `test_fact_check_skill.py`, `manual_scenarios.py`: verification surfaces.",
        "",
        "## How The Agentic Layer Uses Them",
        "",
        "- The agentic workflow handles phase state, checkpoints, prompt logs, and scaffold files.",
        "- The low-level executor remains the tool used during testing and implementation phases.",
        "- Human review happens between workflow phases instead of only at the end.",
        "",
        "## Recommended Starting Files",
        "",
        "- `docs/workflow/WORKFLOW.md`",
        "- `workflow_state/scaffolding/module_map.md`",
        "- `workflow_state/scaffolding/retrieval_index.md`",
        "- `README.md`",
        "- `docs/archive/README_v2.md`",
    ]
    return "\n".join(lines)


def scaffold_module_map() -> str:
    backend_rows = discover_python_rows(REPO_ROOT / "backend")
    script_rows = discover_python_rows(REPO_ROOT / "scripts")
    test_rows = [
        [path, summary]
        for path, summary in discover_python_rows(REPO_ROOT)
        if path.startswith("test_") or path.startswith("start_server")
    ]
    frontend_rows = discover_frontend_rows(REPO_ROOT / "frontend")

    lines = [
        "# Module Map",
        "",
        f"Generated: {now_iso()}",
        "",
        "## Backend Modules",
        "",
        md_table(["File", "Role"], backend_rows),
        "",
        "## Scripts",
        "",
        md_table(["File", "Role"], script_rows),
        "",
        "## Tests And Entry Points",
        "",
        md_table(["File", "Role"], test_rows),
        "",
        "## Frontend Pages",
        "",
        md_table(["File", "Role"], frontend_rows[:20]),
    ]
    return "\n".join(lines)


def scaffold_test_surface() -> str:
    lines = [
        "# Test Surface",
        "",
        f"Generated: {now_iso()}",
        "",
        "## Primary Commands",
        "",
        "- `python3 scripts/dev_workflow.py check`: run the main Python verification suites.",
        "- `python3 scripts/dev_workflow.py smoke --scenario server-check`: temporary health-check server run.",
        "- `python3 scripts/dev_workflow.py smoke --scenario scenario-ai`: temporary end-to-end scenario run.",
        "- `python3 manual_scenarios.py scenario-ai --base-url http://127.0.0.1:PORT`: deeper manual API scenario.",
        "",
        "## Coverage Areas",
        "",
        md_table(
            ["File", "Coverage"],
            [
                [
                    "test_debate_system.py",
                    "Core system behavior, scoring, pipeline, audits, and identity-blindness checks.",
                ],
                [
                    "test_fact_check_skill.py",
                    "Fact checking logic, caching, queueing, audit logging, and MSD-aligned requirements.",
                ],
                [
                    "manual_scenarios.py",
                    "API-level scenarios, moderation behavior, snapshot generation, verdict retrieval, and evidence endpoints.",
                ],
                [".github/workflows/ci.yml", "Runs `check` and a smoke health-check flow in CI."],
            ],
        ),
        "",
        "## Validation Rule",
        "",
        "- Use focused module tests during implementation.",
        "- Use the smoke flow before claiming the workflow or server path works end to end.",
        "- Use integration testing after module-level approval.",
    ]
    return "\n".join(lines)


def scaffold_retrieval_index() -> str:
    rows = []
    for index, phase in enumerate(PHASES, start=1):
        rows.append(
            [
                f"{index}. {phase['title']}",
                "<br>".join(phase["context_files"]),
                phase["objective"],
            ]
        )
    lines = [
        "# Retrieval Index",
        "",
        f"Generated: {now_iso()}",
        "",
        "Start with scaffold files first. Only open deeper code once the current phase requires it.",
        "",
        md_table(["Phase", "Read First", "Why"], rows),
    ]
    return "\n".join(lines)


def scaffold_open_questions(goal: str) -> str:
    lines = [
        "# Open Questions",
        "",
        f"Generated: {now_iso()}",
        "",
        "These are the default human checkpoints to resolve before or during the workflow.",
        "",
        f"- What concrete outcome would make the goal complete? Current goal: `{goal}`",
        "- Which user-facing behavior is allowed to change, and which behavior must stay stable?",
        "- Which parts of the repo are highest risk: moderation, debate engine, database schema, or UI?",
        "- Should the workflow optimize for local development only, or also for Codex skill reuse and CI handoff?",
        "- What evidence should a human review at each checkpoint: design note, patch, test output, or prototype?",
    ]
    return "\n".join(lines)


def scaffold_human_checkpoints() -> str:
    rows = []
    for index, phase in enumerate(PHASES, start=1):
        rows.append([f"{index}. {phase['title']}", phase["human_checkpoint"]])
    lines = [
        "# Human Checkpoints",
        "",
        f"Generated: {now_iso()}",
        "",
        "Every workflow phase ends at a human checkpoint. The AI should not silently skip these.",
        "",
        md_table(["Phase", "Human Review Required"], rows),
        "",
        "Suggested approval language:",
        "",
        '- `./wf resume --human-note "system design approved"`',
        '- `./wf resume --human-note "module split approved"`',
        '- `./wf change-requirement "..."` when scope changes',
    ]
    return "\n".join(lines)


def phase_file_name(index: int, phase_id: str) -> Path:
    return PHASE_DIR / f"{index:02d}-{phase_id}.md"


def build_phase_brief(phase_index: int, state: dict[str, Any]) -> str:
    phase = PHASES[phase_index]
    lines = [
        f"# {phase_index + 1}. {phase['title']}",
        "",
        f"Workflow goal: {state['goal']}",
        "",
        "## Objective",
        "",
        phase["objective"],
        "",
        "## Human Checkpoint",
        "",
        phase["human_checkpoint"],
        "",
        "## Read First",
        "",
        *[f"- `{item}`" for item in phase["context_files"]],
        "",
        "## Deliverables",
        "",
        *[f"- {item}" for item in phase["deliverables"]],
        "",
        "## Suggested Validation",
        "",
        "- Update scaffold summaries if your understanding of the repo changed.",
        "- Prefer the smallest implementation slice that can be reviewed by a human.",
        "- Use `scripts/dev_workflow.py` only when this phase calls for execution or validation.",
    ]
    return "\n".join(lines)


def render_current_prompt(state: dict[str, Any]) -> str:
    phase = PHASES[state["current_phase_index"]]
    phase_path = relative_label(phase_file_name(state["current_phase_index"] + 1, phase["id"]))
    lines = [
        "# Next Agent Prompt",
        "",
        f"Workflow goal: {state['goal']}",
        f"Current phase: {phase['title']}",
        "",
        "Use the current phase brief and scaffold files before opening broad code context.",
        "",
        "## Read First",
        "",
        f"- `{phase_path}`",
        "- `workflow_state/scaffolding/project_summary.md`",
        "- `workflow_state/scaffolding/retrieval_index.md`",
        "- `workflow_state/scaffolding/open_questions.md`",
        "",
        "## Suggested Prompt",
        "",
        "```text",
        f"You are working on phase `{phase['id']}` of the repo's agentic workflow.",
        f"Goal: {state['goal']}",
        "Start from the scaffold files instead of reading the whole repo.",
        f"Read `{phase_path}` and the listed scaffold files first.",
        "Complete only the work for this phase, update the relevant phase file with results,",
        "and stop at the human checkpoint instead of continuing automatically.",
        'Log new human instructions with `./wf log-human-prompt "..."` before changing course.',
        "```",
        "",
        "## Reminder",
        "",
        f"- Human checkpoint after this phase: {phase['human_checkpoint']}",
        '- If the checkpoint is rejected, use `./wf reject --human-note "..."` and revise the same phase.',
    ]
    if state.get("requirement_changes"):
        latest = state["requirement_changes"][-1]
        lines.extend(
            [
                "",
                "## Latest Requirement Change",
                "",
                f"- {latest['text']}",
            ]
        )
    return "\n".join(lines)


def render_current_checkpoint(state: dict[str, Any]) -> str:
    phase = PHASES[state["current_phase_index"]]
    lines = [
        "# Current Checkpoint",
        "",
        f"Current phase: {phase['title']}",
        "",
        "Before advancing, the human should confirm:",
        "",
        f"- {phase['human_checkpoint']}",
        "- The current phase deliverables are present and understandable.",
        "- Any requirement changes have been logged.",
        "",
        "Advance with:",
        "",
        f"- `./wf resume --human-note \"{phase['title'].lower()} approved\"`",
        "",
        "If scope changed instead:",
        "",
        '- `./wf change-requirement "..."`',
    ]
    return "\n".join(lines)


def render_current_context_files(state: dict[str, Any]) -> str:
    phase = PHASES[state["current_phase_index"]]
    lines = [
        "# Current Context Files",
        "",
        f"Current phase: {phase['title']}",
        "",
        *[f"- `{item}`" for item in phase["context_files"]],
        "",
        "Only move beyond these files when the current phase requires deeper code inspection.",
    ]
    return "\n".join(lines)


def refresh_scaffolding(state: dict[str, Any]) -> None:
    ensure_dirs()
    write_text(SCAFFOLD_DIR / "project_summary.md", scaffold_project_summary(state["goal"]))
    write_text(SCAFFOLD_DIR / "module_map.md", scaffold_module_map())
    write_text(SCAFFOLD_DIR / "test_surface.md", scaffold_test_surface())
    write_text(SCAFFOLD_DIR / "retrieval_index.md", scaffold_retrieval_index())
    write_text(SCAFFOLD_DIR / "open_questions.md", scaffold_open_questions(state["goal"]))
    write_text(SCAFFOLD_DIR / "human_checkpoints.md", scaffold_human_checkpoints())
    for index, phase in enumerate(PHASES):
        write_text(phase_file_name(index + 1, phase["id"]), build_phase_brief(index, state))
    write_text(CURRENT_DIR / "next_prompt.md", render_current_prompt(state))
    write_text(CURRENT_DIR / "checkpoint.md", render_current_checkpoint(state))
    write_text(CURRENT_DIR / "context_files.md", render_current_context_files(state))


def bootstrap(args: argparse.Namespace) -> int:
    if STATE_PATH.exists() and not args.force:
        raise RuntimeError(
            "Workflow already initialized. Use `./wf status` or re-run bootstrap with `--force`."
        )

    if args.force and WORKFLOW_DIR.exists():
        shutil.rmtree(WORKFLOW_DIR)

    goal = (
        args.goal.strip()
        if args.goal
        else "Drive debate_system through a human-AI workflow with explicit checkpoints."
    )
    state = {
        "workflow_name": "agentic-development",
        "version": 1,
        "platform": args.platform,
        "goal": goal,
        "status": "active",
        "current_phase_index": 0,
        "current_phase": PHASES[0]["id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "requirement_changes": [],
        "phase_history": [],
    }

    ensure_dirs()
    write_json(STATE_PATH, state)
    append_prompt_log("bootstrap-goal", goal, state=state)
    log_human_prompt_entry(goal, state, kind="bootstrap-goal")
    refresh_scaffolding(state)
    print(f"Initialized agentic workflow in {relative_label(WORKFLOW_DIR)}")
    print(f"Goal: {goal}")
    print("Next: review `workflow_state/current/next_prompt.md` or run `./wf status`.")
    return 0


def workflow_status(_: argparse.Namespace) -> int:
    ensure_dirs()
    state = require_state()
    phase = PHASES[state["current_phase_index"]]
    print(f"Workflow: {state['workflow_name']}")
    print(f"Goal: {state['goal']}")
    print(f"Status: {state['status']}")
    print(f"Current phase: {state['current_phase_index'] + 1}/{len(PHASES)} - {phase['title']}")
    print(f"Checkpoint: {phase['human_checkpoint']}")
    print(f"Prompt file: {relative_label(CURRENT_DIR / 'next_prompt.md')}")
    print(f"Checkpoint file: {relative_label(CURRENT_DIR / 'checkpoint.md')}")
    print(f"Human logs: {relative_label(HUMAN_LOG_DIR)}")
    if state.get("requirement_changes"):
        print(f"Requirement changes logged: {len(state['requirement_changes'])}")
    return 0


def refresh(args: argparse.Namespace) -> int:
    state = require_state()
    refresh_scaffolding(state)
    if args.note:
        append_prompt_log("refresh", args.note.strip(), state=state)
    print("Workflow scaffolding refreshed from the current state.")
    print(f"Prompt: {relative_label(CURRENT_DIR / 'next_prompt.md')}")
    return 0


def resume(args: argparse.Namespace) -> int:
    state = require_state()
    if state["status"] == "completed":
        print("Workflow already completed.")
        return 0

    current_phase = PHASES[state["current_phase_index"]]
    note = args.human_note.strip() if args.human_note else f"{current_phase['title']} approved"
    append_prompt_log("human-checkpoint", note, state=state)
    log_approval_entry(note, current_phase["id"])
    state["phase_history"].append(
        {
            "phase": current_phase["id"],
            "completed_at": now_iso(),
            "human_note": note,
        }
    )

    if state["current_phase_index"] + 1 >= len(PHASES):
        state["status"] = "completed"
        state["updated_at"] = now_iso()
        write_json(STATE_PATH, state)
        refresh_scaffolding(state)
        print("Workflow completed. Review the final integration artifacts and prompt history.")
        return 0

    state["current_phase_index"] += 1
    state["current_phase"] = PHASES[state["current_phase_index"]]["id"]
    state["updated_at"] = now_iso()
    write_json(STATE_PATH, state)
    refresh_scaffolding(state)
    next_phase = PHASES[state["current_phase_index"]]
    print(f"Advanced to phase {state['current_phase_index'] + 1}: {next_phase['title']}")
    print(f"Prompt: {relative_label(CURRENT_DIR / 'next_prompt.md')}")
    return 0


def reject(args: argparse.Namespace) -> int:
    state = require_state()
    phase = PHASES[state["current_phase_index"]]
    note = args.human_note.strip() if args.human_note else f"{phase['title']} rejected for revision"
    append_prompt_log("checkpoint-rejection", note, state=state)
    log_rejection_entry(note, phase["id"])
    state["updated_at"] = now_iso()
    write_json(STATE_PATH, state)
    refresh_scaffolding(state)
    print(f"Checkpoint rejection logged for phase {phase['title']}.")
    print("Revise the current phase artifacts and stop again at the same checkpoint.")
    return 0


def change_requirement(args: argparse.Namespace) -> int:
    state = require_state()
    text = args.text.strip()
    if not text:
        raise RuntimeError("Requirement change text cannot be empty.")

    entry = {
        "timestamp": now_iso(),
        "text": text,
        "from_phase": state["current_phase"],
    }
    state.setdefault("requirement_changes", []).append(entry)
    state["current_phase_index"] = 0
    state["current_phase"] = PHASES[0]["id"]
    state["status"] = "active"
    state["updated_at"] = now_iso()
    write_json(STATE_PATH, state)
    append_prompt_log(
        "change-requirement", text, state=state, extra={"from_phase": entry["from_phase"]}
    )
    log_requirement_change_entry(text, entry["from_phase"])
    write_text(
        CURRENT_DIR / "requirement_change.md",
        "\n".join(
            [
                "# Requirement Change",
                "",
                f"Logged: {entry['timestamp']}",
                f"Previous phase: {entry['from_phase']}",
                "",
                text,
                "",
                "The workflow has been rewound to system design so the AI can replan with the new requirement.",
            ]
        ),
    )
    refresh_scaffolding(state)
    print("Requirement change logged and workflow rewound to System Design.")
    return 0


def log_human_prompt(args: argparse.Namespace) -> int:
    state = read_json(STATE_PATH) if STATE_PATH.exists() else None
    append_prompt_log(args.kind, args.text, state=state)
    log_human_prompt_entry(args.text, state, kind=args.kind)
    print("Prompt logged.")
    return 0


def manual_override(args: argparse.Namespace) -> int:
    state = read_json(STATE_PATH) if STATE_PATH.exists() else None
    text = args.text.strip()
    if not text:
        raise RuntimeError("Manual override text cannot be empty.")
    append_prompt_log("manual-override", text, state=state)
    log_manual_override_entry(text, state)
    print("Manual override logged.")
    return 0


def review_prompts(_: argparse.Namespace) -> int:
    logs = read_prompt_log()
    if not logs:
        raise RuntimeError("No prompt log entries found.")

    kind_counts = Counter(entry["kind"] for entry in logs)
    word_counter: Counter[str] = Counter()
    for entry in logs:
        for raw_word in entry["text"].lower().replace("/", " ").replace("-", " ").split():
            word = "".join(ch for ch in raw_word if ch.isalpha())
            if len(word) >= 5:
                word_counter[word] += 1

    suggestions = []
    if kind_counts.get("change-requirement", 0) >= 1:
        suggestions.append(
            "- Requirement changes occurred after bootstrap. Keep an explicit human scope confirmation before implementation."
        )
    if kind_counts.get("checkpoint-rejection", 0) >= 1:
        suggestions.append(
            "- One or more checkpoints were rejected. Tighten phase deliverables or make review artifacts easier to skim."
        )
    if kind_counts.get("human-checkpoint", 0) < max(1, len(PHASES) // 2):
        suggestions.append(
            "- Human approvals are sparse relative to the number of phases. Consider pausing more often for review artifacts."
        )
    if kind_counts.get("manual-override", 0) >= 1:
        suggestions.append(
            "- Manual overrides occurred. Consider adding a first-class command or clearer scaffold artifact for that scenario."
        )
    if any(keyword in word_counter for keyword in ("review", "prototype", "approve")):
        suggestions.append(
            "- Human review language appears frequently. Keep checkpoint files concise and easy to skim."
        )
    if any(keyword in word_counter for keyword in ("context", "files", "module")):
        suggestions.append(
            "- Context-navigation prompts appear in the log. Expand scaffold summaries before opening broad code context."
        )
    if not suggestions:
        suggestions.append(
            "- The prompt log looks stable. Keep the current checkpoint cadence and continue collecting examples."
        )

    rows = [[kind, str(count)] for kind, count in sorted(kind_counts.items())]
    top_words = (
        ", ".join(word for word, _ in word_counter.most_common(12))
        or "No recurring words captured."
    )
    content = "\n".join(
        [
            "# Workflow Improvements",
            "",
            f"Generated: {now_iso()}",
            "",
            "## Prompt Categories",
            "",
            md_table(["Kind", "Count"], rows),
            "",
            "## Frequent Signal Words",
            "",
            top_words,
            "",
            "## Suggestions",
            "",
            *suggestions,
            "",
            "## Latest Prompts",
            "",
            *[
                f"- `{entry['timestamp']}` `{entry['kind']}`: {entry['text']}"
                for entry in logs[-10:]
            ],
        ]
    )
    write_text(REVIEW_DIR / "workflow_improvements.md", content)
    print(f"Wrote {relative_label(REVIEW_DIR / 'workflow_improvements.md')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stateful agentic workflow for debate_system.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="Create workflow scaffolding and initialize state."
    )
    bootstrap_parser.add_argument("--goal", default="", help="High-level workflow goal.")
    bootstrap_parser.add_argument(
        "--platform", default="codex", help="Primary agent platform for this workflow."
    )
    bootstrap_parser.add_argument(
        "--force", action="store_true", help="Reinitialize the workflow state and scaffolding."
    )
    bootstrap_parser.set_defaults(func=bootstrap)

    status_parser = subparsers.add_parser(
        "status", help="Show current workflow phase and checkpoint."
    )
    status_parser.set_defaults(func=workflow_status)

    refresh_parser = subparsers.add_parser(
        "refresh", help="Regenerate scaffold files for the current workflow state."
    )
    refresh_parser.add_argument(
        "--note", default="", help="Optional note describing why scaffolding was refreshed."
    )
    refresh_parser.set_defaults(func=refresh)

    resume_parser = subparsers.add_parser(
        "resume", help="Advance to the next phase after a human checkpoint."
    )
    resume_parser.add_argument("--human-note", default="", help="Checkpoint note or approval text.")
    resume_parser.set_defaults(func=resume)

    reject_parser = subparsers.add_parser(
        "reject", help="Log a checkpoint rejection and stay in the current phase."
    )
    reject_parser.add_argument(
        "--human-note", default="", help="Checkpoint rejection or revision note."
    )
    reject_parser.set_defaults(func=reject)

    change_parser = subparsers.add_parser(
        "change-requirement", help="Log a requirement change and rewind to replanning."
    )
    change_parser.add_argument("text", help="Requirement change text.")
    change_parser.set_defaults(func=change_requirement)

    review_parser = subparsers.add_parser(
        "review-prompts", help="Review prompt logs and suggest workflow improvements."
    )
    review_parser.set_defaults(func=review_prompts)

    log_parser = subparsers.add_parser(
        "log-human-prompt", help="Append an arbitrary human prompt to the workflow log."
    )
    log_parser.add_argument("text", help="Prompt text to log.")
    log_parser.add_argument("--kind", default="human-prompt", help="Prompt category.")
    log_parser.set_defaults(func=log_human_prompt)

    override_parser = subparsers.add_parser(
        "manual-override", help="Log a manual workflow override without advancing phases."
    )
    override_parser.add_argument("text", help="Override description.")
    override_parser.set_defaults(func=manual_override)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
