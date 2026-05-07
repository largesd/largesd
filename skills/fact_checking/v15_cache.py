"""
CacheKey v1.5 and canonical JSON serializer for the LSD Fact-Checking System.

Implements:
- CacheKey construction with full scope/entity/policy/decomposition versioning
- Canonical JSON serializer for authoritative hashing
- Simple immutable in-memory cache for testing and deterministic replay

Per 01_DATA_MODELS.md §13 and 03_PIPELINE.md §5.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict
from typing import Any

from .v15_models import (
    AtomicSubclaim,
    CacheKey,
    EvidencePolicy,
    FactMode,
    FrameDependencyKey,
    VerdictScope,
)

# ---------------------------------------------------------------------------
# Canonical JSON serializer
# ---------------------------------------------------------------------------


def canonical_json_serialize(obj: Any) -> str:
    """
    Deterministic canonical JSON serializer for authoritative hashing.

    Rules (per 03_PIPELINE.md §6):
    - UTF-8 encoding
    - Sorted object keys (recursively)
    - Normalized Unicode (NFC)
    - No insignificant whitespace
    - Stable list ordering (caller must sort if order-independent)
    - Stable float formatting (%.6f)
    - Explicit nulls for nullable fields
    - No timestamps inside hashes unless timestamp is part of authoritative record
    """

    def _serialize(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            formatted = f"{value:.6f}"
            return float(formatted)
        if isinstance(value, str):
            return unicodedata.normalize("NFC", value)
        if isinstance(value, list):
            return [_serialize(v) for v in value]
        if isinstance(value, dict):
            return {k: _serialize(v) for k, v in sorted(value.items())}
        # Handle dataclasses
        if hasattr(value, "__dataclass_fields__"):
            d = asdict(value)  # type: ignore[arg-type]
            return {k: _serialize(v) for k, v in sorted(d.items())}
        # Handle enums
        if hasattr(value, "value"):
            return value.value
        raise ValueError(f"Unsupported type for canonical JSON: {type(value)}")

    canonical = _serialize(obj)
    return json.dumps(canonical, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def canonical_json_hash(obj: Any) -> str:
    """SHA-256 of the canonical JSON representation."""
    canonical = canonical_json_serialize(obj)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Claim hash (identity normalization)
# ---------------------------------------------------------------------------


def _standardize_numbers(text: str) -> str:
    """
    Best-effort number standardization for claim identity hashing.
    - Remove comma thousands separators
    - Normalize percentage signs
    - Normalize common currency symbols to words
    - Normalize common date separators
    """
    # Remove commas in numbers (e.g., 38,000,000 -> 38000000)
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    # Normalize percentage
    text = re.sub(r"%", " percent", text)
    text = re.sub(r"\bpercent\b", "percent", text)
    # Normalize currency symbols to words
    text = re.sub(r"\$", "USD ", text)
    text = re.sub(r"€", "EUR ", text)
    text = re.sub(r"£", "GBP ", text)
    # Normalize date separators
    text = re.sub(r"(?<=\d)/(?=\d)", "-", text)
    text = re.sub(r"(?<=\d)\.(?=\d{2,4})", "-", text)
    return text


def compute_claim_hash(text: str) -> str:
    """
    Compute claim_hash per 03_PIPELINE.md §5:
    claim_hash = SHA256(lowercase(trimmed_text_with_standardized_numbers))
    Stopwords are NOT removed.
    """
    normalized = text.lower().strip()
    normalized = _standardize_numbers(normalized)
    normalized = unicodedata.normalize("NFC", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# CacheKey builder
# ---------------------------------------------------------------------------


def compute_verdict_scope_hash(scope: VerdictScope) -> str:
    return canonical_json_hash(scope)


def compute_operationalization_hash(operationalization: str) -> str:
    return hashlib.sha256(operationalization.lower().strip().encode("utf-8")).hexdigest()


def compute_entity_ids_hash(entity_ids: list[str]) -> str:
    """Hash a list of resolved entity IDs (e.g., Wikidata QIDs)."""
    sorted_ids = sorted(unicodedata.normalize("NFC", eid) for eid in entity_ids)
    payload = json.dumps(sorted_ids, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_connector_snapshot_versions_hash(versions: dict[str, str]) -> str:
    return canonical_json_hash(versions)


def build_cache_key(
    subclaim: AtomicSubclaim,
    resolved_entity_ids: list[str],
    evidence_policy: EvidencePolicy,
    decomposition_version: str,
    connector_snapshot_versions: dict[str, str],
    fact_mode: FactMode = FactMode.OFFLINE,
    frame_dependency_key: FrameDependencyKey | None = None,
) -> CacheKey:
    """
    Build a full CacheKey v1.5 for an AtomicSubclaim.

    The key includes:
    - claim_hash (from subclaim text)
    - normalized_subclaim_text
    - claim_type
    - resolved_entity_ids_hash
    - verdict_scope_hash (from subclaim.verdict_scope_hint)
    - operationalization_hash
    - decomposition_version
    - evidence_policy_version (from policy.policy_id)
    - connector_snapshot_versions_hash
    - fact_mode
    - frame_dependency_key (only if policy.frame_dependent)
    """
    claim_hash = compute_claim_hash(subclaim.text)
    normalized_text = subclaim.text.lower().strip()
    normalized_text = unicodedata.normalize("NFC", normalized_text)

    entity_hash = compute_entity_ids_hash(resolved_entity_ids)
    scope_hash = compute_verdict_scope_hash(subclaim.verdict_scope_hint)
    op_hash = compute_operationalization_hash(subclaim.operationalization_hint)
    connector_hash = compute_connector_snapshot_versions_hash(connector_snapshot_versions)

    frame_key = frame_dependency_key if evidence_policy.frame_dependent else None

    return CacheKey(
        claim_hash=claim_hash,
        normalized_subclaim_text=normalized_text,
        claim_type=subclaim.claim_type,
        resolved_entity_ids_hash=entity_hash,
        verdict_scope_hash=scope_hash,
        operationalization_hash=op_hash,
        decomposition_version=decomposition_version,
        evidence_policy_version=evidence_policy.policy_id,
        connector_snapshot_versions_hash=connector_hash,
        fact_mode=fact_mode,
        frame_dependency_key=frame_key,
    )


def cache_key_to_string(key: CacheKey) -> str:
    """Serialize a CacheKey to a flat string for use as a cache lookup key."""
    # Use canonical JSON for the full key serialization
    return canonical_json_hash(key)


# ---------------------------------------------------------------------------
# Immutable in-memory cache (testing / deterministic replay)
# ---------------------------------------------------------------------------


class ImmutableMemoryCache:
    """
    Simple immutable cache that stores authoritative results keyed by CacheKey.

    - Exact match only
    - No expiration (immutable records)
    - Thread-safe via dict semantics (CPython GIL)
    """

    def __init__(self):
        self._store: dict[str, Any] = {}

    def get(self, key: CacheKey) -> Any | None:
        """Return the stored result for an exact CacheKey match, or None."""
        key_str = cache_key_to_string(key)
        # Return a copy to prevent accidental mutation
        result = self._store.get(key_str)
        if result is not None:
            import copy

            return copy.deepcopy(result)
        return None

    def set(self, key: CacheKey, result: Any) -> None:
        """Store an authoritative result keyed by CacheKey."""
        key_str = cache_key_to_string(key)
        import copy

        self._store[key_str] = copy.deepcopy(result)

    def invalidate(self, key: CacheKey) -> None:
        key_str = cache_key_to_string(key)
        self._store.pop(key_str, None)

    def clear(self) -> None:
        self._store.clear()

    def size(self) -> int:
        return len(self._store)
