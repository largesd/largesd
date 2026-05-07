"""Input validation helpers for the debate system API."""

import re
from typing import Any

from backend.modulation import ModulationEngine


class ValidationError(Exception):
    pass


def validate_string(
    value: Any,
    name: str,
    min_length: int = 1,
    max_length: int = 10000,
    required: bool = True,
) -> str | None:
    """Validate a string field"""
    if value is None or value == "":
        if required:
            raise ValidationError(f"{name} is required")
        return None

    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string")

    result: str = value.strip()

    if len(result) < min_length:
        raise ValidationError(f"{name} must be at least {min_length} characters")

    if len(result) > max_length:
        raise ValidationError(f"{name} must be no more than {max_length} characters")

    return result


def validate_side(value: Any, required: bool = True) -> str | None:
    """Validate side field"""
    if value is None or value == "":
        if required:
            raise ValidationError("Side is required")
        return None

    side: str = str(value).upper().strip()
    if side not in ["FOR", "AGAINST"]:
        raise ValidationError("Side must be either 'FOR' or 'AGAINST'")

    return side


def validate_topic_id(value: Any, required: bool = True) -> str | None:
    """Validate topic_id field"""
    if value is None or value == "":
        if required:
            raise ValidationError("Topic is required")
        return None

    topic: str = str(value).strip().lower()
    # Allow t1-t9 format or any alphanumeric
    if not re.match(r"^[a-z0-9_-]+$", topic):
        raise ValidationError("Invalid topic ID format")

    return topic


def validate_version_field(value: Any, default_value: str = "1.0.0") -> str:
    raw = str(value).strip() if value is not None else ""
    version = raw or default_value
    if len(version) > 40 or not re.match(r"^[A-Za-z0-9._-]+$", version):
        raise ValidationError("Version must use letters, numbers, dots, underscores, or dashes")
    return version


def to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_list(value: Any, *, separator_pattern: str = r"[,;\n]") -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = re.split(separator_pattern, value)
    else:
        return []

    normalized = []
    seen = set()
    for item in raw_items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return normalized


def merge_dict(defaults: dict[str, Any], incoming: Any) -> dict[str, Any]:
    merged = dict(defaults)
    if isinstance(incoming, dict):
        for key, value in incoming.items():
            merged[key] = value
    return merged


# Re-export for internal use with narrower typing
_merge_dict = merge_dict


def resolve_template_id(raw_template_id: str | None) -> str:
    aliases = {
        "standard": "standard_civility",
        "standard_civility": "standard_civility",
        "academic": "strict",
        "strict": "strict",
        "minimal": "minimal",
        "custom": "standard_civility",
    }
    template_id = aliases.get((raw_template_id or "").strip().lower(), raw_template_id or "")
    if template_id not in ModulationEngine.BUILTIN_TEMPLATES:
        return "standard_civility"
    return template_id


def resolve_template_name(template_id: str, override_name: str | None = None) -> str:
    if override_name and override_name.strip():
        return override_name.strip()
    config: dict[str, Any] = ModulationEngine.BUILTIN_TEMPLATES.get(template_id, {})
    return str(config.get("name", "Custom Moderation Template"))


DEFAULT_MODERATION_SETTINGS: dict[str, Any] = {
    "topic_requirements": {
        "required_keywords": [],
        "relevance_threshold": "moderate",
        "enforce_scope": True,
    },
    "toxicity_settings": {
        "sensitivity_level": 3,
        "block_personal_attacks": True,
        "block_hate_speech": True,
        "block_threats": True,
        "block_sexual_harassment": True,
        "block_mild_profanity": False,
    },
    "pii_settings": {
        "detect_email": True,
        "detect_phone": True,
        "detect_address": True,
        "detect_full_names": False,
        "detect_social_handles": False,
        "action": "block",
    },
    "spam_rate_limit_settings": {
        "min_length": 50,
        "max_length": 5000,
        "flood_threshold_per_hour": 10,
        "duplicate_detection": True,
        "rate_limiting": True,
    },
    "prompt_injection_settings": {
        "enabled": True,
        "block_markdown_hiding": True,
        "custom_patterns": [],
    },
}


def normalize_moderation_template_payload(payload: dict[str, Any]) -> dict[str, Any]:
    base_template_id = resolve_template_id(payload.get("base_template_id"))
    version = validate_version_field(payload.get("version"))
    template_name = resolve_template_name(base_template_id, payload.get("template_name"))
    notes = (
        validate_string(payload.get("notes"), "Notes", min_length=0, max_length=500, required=False)
        or ""
    )

    topic_raw = merge_dict(
        DEFAULT_MODERATION_SETTINGS["topic_requirements"], payload.get("topic_requirements")
    )
    threshold = str(topic_raw.get("relevance_threshold", "moderate")).strip().lower()
    if threshold not in {"strict", "moderate", "permissive"}:
        threshold = "moderate"
    topic_requirements = {
        "required_keywords": normalize_list(topic_raw.get("required_keywords"))[:50],
        "relevance_threshold": threshold,
        "enforce_scope": to_bool(topic_raw.get("enforce_scope"), True),
    }

    toxicity_raw = merge_dict(
        DEFAULT_MODERATION_SETTINGS["toxicity_settings"], payload.get("toxicity_settings")
    )
    sensitivity_level = to_int(toxicity_raw.get("sensitivity_level", 3), 3)
    sensitivity_level = max(1, min(5, sensitivity_level))
    toxicity_settings = {
        "sensitivity_level": sensitivity_level,
        "block_personal_attacks": to_bool(toxicity_raw.get("block_personal_attacks"), True),
        "block_hate_speech": to_bool(toxicity_raw.get("block_hate_speech"), True),
        "block_threats": to_bool(toxicity_raw.get("block_threats"), True),
        "block_sexual_harassment": to_bool(toxicity_raw.get("block_sexual_harassment"), True),
        "block_mild_profanity": to_bool(toxicity_raw.get("block_mild_profanity"), False),
    }

    pii_raw = merge_dict(DEFAULT_MODERATION_SETTINGS["pii_settings"], payload.get("pii_settings"))
    pii_action = str(pii_raw.get("action", "block")).strip().lower()
    if pii_action not in {"block", "redact", "flag"}:
        pii_action = "block"
    pii_settings = {
        "detect_email": to_bool(pii_raw.get("detect_email"), True),
        "detect_phone": to_bool(pii_raw.get("detect_phone"), True),
        "detect_address": to_bool(pii_raw.get("detect_address"), True),
        "detect_full_names": to_bool(pii_raw.get("detect_full_names"), False),
        "detect_social_handles": to_bool(pii_raw.get("detect_social_handles"), False),
        "action": pii_action,
    }

    spam_raw = merge_dict(
        DEFAULT_MODERATION_SETTINGS["spam_rate_limit_settings"],
        payload.get("spam_rate_limit_settings"),
    )
    min_length = max(0, min(20000, to_int(spam_raw.get("min_length", 50), 50)))
    max_length = max(min_length, min(50000, to_int(spam_raw.get("max_length", 5000), 5000)))
    flood_threshold = max(1, min(5000, to_int(spam_raw.get("flood_threshold_per_hour", 10), 10)))
    spam_rate_limit_settings = {
        "min_length": min_length,
        "max_length": max_length,
        "flood_threshold_per_hour": flood_threshold,
        "duplicate_detection": to_bool(spam_raw.get("duplicate_detection"), True),
        "rate_limiting": to_bool(spam_raw.get("rate_limiting"), True),
    }

    prompt_raw = merge_dict(
        DEFAULT_MODERATION_SETTINGS["prompt_injection_settings"],
        payload.get("prompt_injection_settings"),
    )
    prompt_injection_settings = {
        "enabled": to_bool(prompt_raw.get("enabled"), True),
        "block_markdown_hiding": to_bool(prompt_raw.get("block_markdown_hiding"), True),
        "custom_patterns": normalize_list(prompt_raw.get("custom_patterns"))[:50],
    }

    return {
        "base_template_id": base_template_id,
        "template_name": template_name,
        "version": version,
        "notes": notes,
        "topic_requirements": topic_requirements,
        "toxicity_settings": toxicity_settings,
        "pii_settings": pii_settings,
        "spam_rate_limit_settings": spam_rate_limit_settings,
        "prompt_injection_settings": prompt_injection_settings,
    }
