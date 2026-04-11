"""
Shared helpers for debate proposal creation and storage.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


DEFAULT_MODERATION_CRITERIA = (
    "Allow good-faith arguments that engage the motion directly. Block harassment, "
    "hate speech, doxxing, spam, and off-topic content. Prefer concrete evidence, "
    "fair summaries of opposing arguments, and decision-useful comparisons."
)

DEFAULT_DEBATE_FRAME = (
    "Judge which side most fairly interprets the motion, best captures the core clash, "
    "and most usefully informs a neutral decision-maker balancing safety, rights, "
    "innovation, and governance trade-offs."
)

REQUIRED_DEBATE_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("motion", "motion"),
    ("moderation_criteria", "moderation criteria"),
    ("debate_frame", "debate frame"),
)


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def build_internal_scope(motion: str, moderation_criteria: str, debate_frame: str) -> str:
    """Compose the internal scope string used by the existing topic pipeline."""
    return (
        f"Motion: {motion}\n"
        f"Debate frame: {debate_frame}\n"
        f"Moderation criteria: {moderation_criteria}\n"
        "Keep extracted topics relevant to the motion, consistent with the stated frame, "
        "and balanced enough to support a decision-useful debate."
    )


def parse_debate_proposal_payload(payload: Dict[str, Any] | None) -> Tuple[Dict[str, str], List[str]]:
    """
    Parse a user-supplied debate proposal payload.

    Returns a normalized proposal dictionary plus a list of human-readable missing fields.
    """
    data = payload or {}
    motion = _clean_text(data.get("motion") or data.get("resolution"))
    moderation_criteria = _clean_text(data.get("moderation_criteria"))
    debate_frame = _clean_text(data.get("debate_frame"))

    missing_fields = [
        label for key, label in REQUIRED_DEBATE_FIELDS
        if not {
            "motion": motion,
            "moderation_criteria": moderation_criteria,
            "debate_frame": debate_frame,
        }[key]
    ]

    proposal = {
        "motion": motion,
        "resolution": motion,
        "moderation_criteria": moderation_criteria,
        "debate_frame": debate_frame,
        "scope": build_internal_scope(motion, moderation_criteria, debate_frame)
        if motion and moderation_criteria and debate_frame
        else "",
    }
    return proposal, missing_fields


def hydrate_debate_record(record: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Fill compatibility aliases on a debate record loaded from storage."""
    if record is None:
        return None

    hydrated = dict(record)
    motion = _clean_text(hydrated.get("motion") or hydrated.get("resolution"))
    moderation_criteria = _clean_text(hydrated.get("moderation_criteria"))
    debate_frame = _clean_text(hydrated.get("debate_frame"))
    scope = _clean_text(hydrated.get("scope"))

    hydrated["motion"] = motion
    hydrated["resolution"] = motion
    hydrated["moderation_criteria"] = moderation_criteria
    hydrated["debate_frame"] = debate_frame

    if not scope and motion and moderation_criteria and debate_frame:
        hydrated["scope"] = build_internal_scope(motion, moderation_criteria, debate_frame)

    return hydrated
