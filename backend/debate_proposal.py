"""
Shared helpers for debate proposal creation, DebateFrame normalization, and storage.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_MODERATION_CRITERIA = (
    "Allow good-faith arguments that engage the motion directly. Block harassment, "
    "hate speech, doxxing, spam, and off-topic content. Prefer concrete evidence, "
    "fair summaries of opposing arguments, and decision-useful comparisons."
)

DEFAULT_FRAME_SUMMARY = (
    "Judge which side most fairly interprets the motion, best captures the core clash, "
    "and most usefully informs a neutral decision-maker."
)

# Backward-compatible alias used by startup helpers and older tests.
DEFAULT_DEBATE_FRAME = DEFAULT_FRAME_SUMMARY

DEFAULT_FRAME_STAGE = "substantive"

DEFAULT_FRAME_SIDES = [
    {
        "side_id": "FOR",
        "label": "FOR",
        "description": "Supports the motion as written.",
    },
    {
        "side_id": "AGAINST",
        "label": "AGAINST",
        "description": "Opposes the motion as written.",
    },
]

DEFAULT_EVALUATION_CRITERIA = [
    "Logical coherence of the argument structure",
    "Strength and relevance of supporting evidence",
    "Fair engagement with the strongest opposing case",
    "Decision usefulness for a neutral evaluator",
]

DEFAULT_DEFINITIONS = [
    {
        "term": "Ordinary meaning",
        "definition": "Use ordinary-language meanings unless this frame defines a term more narrowly.",
    }
]

DEFAULT_SCOPE_CONSTRAINTS = [
    "Stay within the motion, stated definitions, and explicit frame assumptions.",
    "Prioritize arguments that materially affect a neutral decision-maker's conclusion.",
]

REQUIRED_DEBATE_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("motion", "motion"),
    ("moderation_criteria", "moderation criteria"),
    ("frame", "debate frame"),
)


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_list_of_strings(value: Any) -> List[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    if isinstance(value, str):
        items = []
        for line in value.splitlines():
            cleaned = line.strip().lstrip("-").lstrip("*").strip()
            if cleaned:
                items.append(cleaned)
        return items

    return []


def _normalize_side_id(label: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", label.strip().upper()).strip("_")
    return normalized or "SIDE"


def _normalize_sides(value: Any) -> List[Dict[str, str]]:
    if isinstance(value, str):
        raw_items = []
        for line in value.splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            parts = [part.strip() for part in cleaned.split("|", 1)]
            if len(parts) == 2:
                raw_items.append({"label": parts[0], "description": parts[1]})
            else:
                raw_items.append({"label": cleaned, "description": ""})
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    normalized: List[Dict[str, str]] = []
    seen_ids = set()
    for item in raw_items:
        if isinstance(item, str):
            label = _clean_text(item)
            description = ""
            side_id = _normalize_side_id(label)
        elif isinstance(item, dict):
            label = _clean_text(item.get("label") or item.get("name") or item.get("side"))
            description = _clean_text(item.get("description") or item.get("stance"))
            side_id = _clean_text(item.get("side_id") or item.get("id")) or _normalize_side_id(label)
        else:
            continue

        if not label:
            continue

        base_id = side_id
        suffix = 2
        while side_id in seen_ids:
            side_id = f"{base_id}_{suffix}"
            suffix += 1

        seen_ids.add(side_id)
        normalized.append(
            {
                "side_id": side_id,
                "label": label,
                "description": description or f"Arguments advancing the {label} position.",
            }
        )

    return normalized or [dict(side) for side in DEFAULT_FRAME_SIDES]


def _normalize_definitions(value: Any) -> List[Dict[str, str]]:
    if isinstance(value, str):
        raw_items = []
        for line in value.splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            if "::" in cleaned:
                term, definition = cleaned.split("::", 1)
            elif ":" in cleaned:
                term, definition = cleaned.split(":", 1)
            else:
                term, definition = cleaned, ""
            raw_items.append({"term": term.strip(), "definition": definition.strip()})
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    normalized = []
    for item in raw_items:
        if isinstance(item, dict):
            term = _clean_text(item.get("term") or item.get("label"))
            definition = _clean_text(item.get("definition") or item.get("meaning"))
        elif isinstance(item, str):
            term = _clean_text(item)
            definition = ""
        else:
            continue

        if not term:
            continue

        normalized.append(
            {
                "term": term,
                "definition": definition or "Interpret this term according to the frame context and ordinary usage.",
            }
        )

    return normalized or [dict(item) for item in DEFAULT_DEFINITIONS]


def build_frame_summary(frame: Dict[str, Any]) -> str:
    summary = _clean_text(frame.get("frame_summary") or frame.get("summary"))
    if summary:
        return summary

    stage = _clean_text(frame.get("stage")) or DEFAULT_FRAME_STAGE
    side_labels = ", ".join(side["label"] for side in frame.get("sides", []))
    criteria = frame.get("evaluation_criteria", [])
    top_criteria = "; ".join(criteria[:2]) if criteria else "balanced decision-usefulness"
    return (
        f"{DEFAULT_FRAME_SUMMARY} Stage: {stage}. "
        f"Sides under evaluation: {side_labels}. "
        f"Primary criteria: {top_criteria}."
    )


def build_internal_scope(
    motion: str,
    moderation_criteria: str,
    frame: Dict[str, Any],
) -> str:
    """Compose the evaluation context used by extraction, scoring, and audits."""
    sides_text = "; ".join(
        f"{side['label']} ({side['side_id']}): {side.get('description', '').strip()}"
        for side in frame.get("sides", [])
    )
    criteria_text = "; ".join(frame.get("evaluation_criteria", []))
    definitions_text = "; ".join(
        f"{item['term']} = {item['definition']}" for item in frame.get("definitions", [])
    )
    scope_text = "; ".join(frame.get("scope_constraints", []))
    frame_summary = build_frame_summary(frame)
    return (
        f"Motion: {motion}\n"
        f"Frame stage: {frame.get('stage', DEFAULT_FRAME_STAGE)}\n"
        f"Frame summary: {frame_summary}\n"
        f"Sides: {sides_text}\n"
        f"Evaluation criteria: {criteria_text}\n"
        f"Definitions: {definitions_text}\n"
        f"Scope constraints: {scope_text}\n"
        f"Moderation criteria: {moderation_criteria}\n"
        "Evaluate arguments only within this active frame. Do not retroactively apply a different "
        "set of definitions, sides, or criteria."
    )


def _normalize_frame_payload(
    payload: Dict[str, Any],
    motion: str,
    prior_frame: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    prior_frame = prior_frame or {}

    explicit_frame = payload.get("frame")
    if isinstance(payload.get("debate_frame"), dict):
        explicit_frame = payload.get("debate_frame")

    frame_source: Dict[str, Any] = explicit_frame if isinstance(explicit_frame, dict) else {}

    stage = _clean_text(
        frame_source.get("stage")
        or payload.get("frame_stage")
        or prior_frame.get("stage")
        or DEFAULT_FRAME_STAGE
    ).lower()
    if stage not in {"frame-setting", "substantive"}:
        stage = DEFAULT_FRAME_STAGE

    sides = _normalize_sides(
        frame_source.get("sides")
        or payload.get("frame_sides")
        or prior_frame.get("sides")
        or DEFAULT_FRAME_SIDES
    )
    evaluation_criteria = _clean_list_of_strings(
        frame_source.get("evaluation_criteria")
        or payload.get("frame_evaluation_criteria")
        or prior_frame.get("evaluation_criteria")
        or DEFAULT_EVALUATION_CRITERIA
    )
    if not evaluation_criteria:
        evaluation_criteria = list(DEFAULT_EVALUATION_CRITERIA)

    definitions = _normalize_definitions(
        frame_source.get("definitions")
        or payload.get("frame_definitions")
        or prior_frame.get("definitions")
        or DEFAULT_DEFINITIONS
    )
    scope_constraints = _clean_list_of_strings(
        frame_source.get("scope_constraints")
        or payload.get("frame_scope_constraints")
        or prior_frame.get("scope_constraints")
        or DEFAULT_SCOPE_CONSTRAINTS
    )
    if not scope_constraints:
        scope_constraints = list(DEFAULT_SCOPE_CONSTRAINTS)

    notes = _clean_text(
        frame_source.get("notes")
        or payload.get("frame_notes")
        or prior_frame.get("notes")
    )
    frame_summary = _clean_text(
        frame_source.get("frame_summary")
        or frame_source.get("summary")
        or payload.get("debate_frame")
        or payload.get("frame_summary")
        or prior_frame.get("frame_summary")
    )

    frame = {
        "stage": stage,
        "label": _clean_text(frame_source.get("label") or payload.get("frame_label") or prior_frame.get("label")),
        "motion": motion,
        "frame_summary": frame_summary,
        "sides": sides,
        "evaluation_criteria": evaluation_criteria,
        "definitions": definitions,
        "scope_constraints": scope_constraints,
        "notes": notes,
        "framing_debate_id": _clean_text(
            frame_source.get("framing_debate_id")
            or payload.get("framing_debate_id")
            or prior_frame.get("framing_debate_id")
        ),
    }
    frame["frame_summary"] = build_frame_summary(frame)
    return frame


def serialize_frame_record(frame: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "frame_id": frame.get("frame_id"),
        "debate_id": frame.get("debate_id"),
        "version": int(frame.get("version", 1) or 1),
        "stage": _clean_text(frame.get("stage") or DEFAULT_FRAME_STAGE),
        "label": _clean_text(frame.get("label")),
        "motion": _clean_text(frame.get("motion")),
        "frame_summary": build_frame_summary(frame),
        "sides": json.dumps(frame.get("sides", [])),
        "evaluation_criteria": json.dumps(frame.get("evaluation_criteria", [])),
        "definitions": json.dumps(frame.get("definitions", [])),
        "scope_constraints": json.dumps(frame.get("scope_constraints", [])),
        "notes": _clean_text(frame.get("notes")),
        "supersedes_frame_id": _clean_text(frame.get("supersedes_frame_id")),
        "framing_debate_id": _clean_text(frame.get("framing_debate_id")),
        "created_at": frame.get("created_at"),
        "is_active": 1 if frame.get("is_active", True) else 0,
    }


def hydrate_frame_record(record: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if record is None:
        return None

    hydrated = dict(record)
    for key, default in (
        ("sides", []),
        ("evaluation_criteria", []),
        ("definitions", []),
        ("scope_constraints", []),
    ):
        value = hydrated.get(key)
        if isinstance(value, str):
            try:
                hydrated[key] = json.loads(value) if value else list(default)
            except json.JSONDecodeError:
                hydrated[key] = list(default)

    hydrated["frame_summary"] = build_frame_summary(hydrated)
    hydrated["is_active"] = bool(hydrated.get("is_active", True))
    return hydrated


def parse_debate_proposal_payload(
    payload: Dict[str, Any] | None,
    prior_frame: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Parse a user-supplied debate proposal payload.

    Returns a normalized proposal dictionary plus a list of human-readable missing fields.
    """
    data = payload or {}
    motion = _clean_text(data.get("motion") or data.get("resolution") or prior_frame and prior_frame.get("motion"))
    moderation_criteria = _clean_text(data.get("moderation_criteria")) or (
        prior_frame.get("moderation_criteria") if prior_frame else ""
    )
    has_frame_input = bool(
        prior_frame
        or _clean_text(data.get("debate_frame"))
        or data.get("frame")
        or data.get("frame_sides")
        or data.get("frame_evaluation_criteria")
        or data.get("frame_definitions")
        or data.get("frame_scope_constraints")
    )
    frame = _normalize_frame_payload(data, motion, prior_frame=prior_frame)

    missing_fields = [
        label
        for key, label in REQUIRED_DEBATE_FIELDS
        if not {
            "motion": motion,
            "moderation_criteria": moderation_criteria,
            "frame": frame.get("frame_summary") if has_frame_input else "",
        }[key]
    ]

    proposal = {
        "motion": motion,
        "resolution": motion,
        "moderation_criteria": moderation_criteria,
        "debate_frame": frame["frame_summary"],
        "scope": build_internal_scope(motion, moderation_criteria, frame)
        if motion and moderation_criteria and frame.get("frame_summary")
        else "",
        "active_frame": frame,
    }
    return proposal, missing_fields


def hydrate_debate_record(record: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Fill compatibility aliases on a debate record loaded from storage."""
    if record is None:
        return None

    hydrated = dict(record)
    motion = _clean_text(hydrated.get("motion") or hydrated.get("resolution"))
    moderation_criteria = _clean_text(hydrated.get("moderation_criteria"))
    scope = _clean_text(hydrated.get("scope"))
    active_frame = hydrate_frame_record(hydrated.get("active_frame"))

    if active_frame:
        active_frame["motion"] = motion or active_frame.get("motion", "")
        active_frame["moderation_criteria"] = moderation_criteria

    hydrated["motion"] = motion
    hydrated["resolution"] = motion
    hydrated["moderation_criteria"] = moderation_criteria
    hydrated["debate_frame"] = (
        active_frame.get("frame_summary")
        if active_frame
        else _clean_text(hydrated.get("debate_frame"))
    )
    hydrated["active_frame"] = active_frame

    if not scope and motion and moderation_criteria:
        frame_for_scope = active_frame or _normalize_frame_payload(
            {
                "debate_frame": hydrated.get("debate_frame"),
            },
            motion,
        )
        hydrated["scope"] = build_internal_scope(motion, moderation_criteria, frame_for_scope)

    return hydrated
