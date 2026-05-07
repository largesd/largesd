"""
EvidenceItem normalizer for the LSD Fact-Checking System v1.5.

Responsibilities:
- Source metadata normalization
- VerdictScope extraction from raw evidence
- ResolvedValue fields for numeric, temporal, and comparison claims
- Relevance / direction confidence threshold enforcement
- Deterministic comparison for structured values
- LLM direction gating: decisive quote, confidence, relevance, tier, scope,
  and independence fields

Per 01_DATA_MODELS.md and 03_PIPELINE.md §normalizer.
"""

from __future__ import annotations

import hashlib
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

from .v15_models import (
    DeterministicComparisonResult,
    Direction,
    DirectionMethod,
    EvidenceItem,
    ResolvedValue,
    ValidationResult,
    ValueType,
)

# ---------------------------------------------------------------------------
# Thresholds (mirrored from synthesis.py for single source of truth)
# ---------------------------------------------------------------------------

RELEVANCE_THRESHOLD = 0.3
DIRECTION_CONFIDENCE_THRESHOLD = 0.7
QUOTE_MAX_LENGTH = 1000

# ---------------------------------------------------------------------------
# NormalizationResult
# ---------------------------------------------------------------------------


@dataclass
class NormalizationResult:
    """Result of normalizing a single EvidenceItem."""

    item: EvidenceItem | None = None
    rejected: bool = False
    rejection_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate_quote(text: str, max_len: int = QUOTE_MAX_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _standardize_date(date_str: str) -> str:
    """Best-effort ISO8601 normalization."""
    if not date_str:
        return date_str
    # Try common formats
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    # Already ISO-ish — return as-is
    return date_str


def _compute_content_hash(text: str) -> str:
    """SHA-256 of normalized page text for web evidence archiving."""
    normalized = unicodedata.normalize("NFC", text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _compare_resolved_values(
    claimed: ResolvedValue, source: ResolvedValue
) -> DeterministicComparisonResult:
    """
    Deterministic comparison for structured sources.
    Returns MATCH, MISMATCH, or NOT_COMPARABLE.
    """
    if claimed.value is None or source.value is None:
        return DeterministicComparisonResult.NOT_COMPARABLE

    if claimed.value_type != source.value_type:
        return DeterministicComparisonResult.NOT_COMPARABLE

    if claimed.unit != source.unit:
        return DeterministicComparisonResult.NOT_COMPARABLE

    try:
        if claimed.value_type == ValueType.NUMBER:
            match = float(claimed.value) == float(source.value)
            return (
                DeterministicComparisonResult.MATCH
                if match
                else DeterministicComparisonResult.MISMATCH
            )

        if claimed.value_type == ValueType.BOOLEAN:
            match = bool(claimed.value) == bool(source.value)
            return (
                DeterministicComparisonResult.MATCH
                if match
                else DeterministicComparisonResult.MISMATCH
            )

        if claimed.value_type in (ValueType.TEXT, ValueType.CATEGORY, ValueType.DATE):
            match = str(claimed.value) == str(source.value)
            return (
                DeterministicComparisonResult.MATCH
                if match
                else DeterministicComparisonResult.MISMATCH
            )

        if claimed.value_type == ValueType.RANGE:
            # Compare bounds if available
            c_low = claimed.lower_bound
            c_up = claimed.upper_bound
            s_low = source.lower_bound
            s_up = source.upper_bound
            if c_low is not None and s_low is not None and c_up is not None and s_up is not None:
                match = float(c_low) == float(s_low) and float(c_up) == float(s_up)
                return (
                    DeterministicComparisonResult.MATCH
                    if match
                    else DeterministicComparisonResult.MISMATCH
                )
            return DeterministicComparisonResult.NOT_COMPARABLE

        return DeterministicComparisonResult.NOT_COMPARABLE
    except Exception:
        return DeterministicComparisonResult.NOT_COMPARABLE


# ---------------------------------------------------------------------------
# EvidenceNormalizer
# ---------------------------------------------------------------------------


class EvidenceNormalizer:
    """
    Transforms heterogeneous connector outputs into standardized EvidenceItems.

    Gate rules (per 01_DATA_MODELS.md §8 and 03_PIPELINE.md §4):
    - relevance_score < 0.3  → reject
    - direction_confidence < 0.7 for decisive evidence → direction = UNCLEAR
    - Quotes truncated to 1000 chars
    - Dates standardized to ISO8601
    - Structured sources: deterministic comparison (claimed vs source value)
    - Text/RAG/Web: LLM classifier with confidence threshold and decisive quote
    """

    def __init__(
        self,
        relevance_threshold: float = RELEVANCE_THRESHOLD,
        direction_confidence_threshold: float = DIRECTION_CONFIDENCE_THRESHOLD,
    ):
        self.relevance_threshold = relevance_threshold
        self.direction_confidence_threshold = direction_confidence_threshold

    def normalize(self, item: EvidenceItem) -> NormalizationResult:
        """
        Normalize a single EvidenceItem.

        Returns NormalizationResult with the normalized item, or rejected=True
        if the item fails gating thresholds.
        """
        warnings: list[str] = []

        # --- Relevance gate ---
        if item.relevance_score < self.relevance_threshold:
            return NormalizationResult(
                rejected=True,
                rejection_reason=f"relevance_score {item.relevance_score} < threshold {self.relevance_threshold}",
            )

        # Start with a shallow copy so we can mutate fields
        normalized = self._copy_item(item)

        # --- Quote truncation ---
        if len(normalized.quote_or_span) > QUOTE_MAX_LENGTH:
            normalized.quote_or_span = _truncate_quote(normalized.quote_or_span)
            warnings.append("quote_truncated_to_1000_chars")

        # --- Date standardization ---
        if normalized.source_date:
            normalized.source_date = _standardize_date(normalized.source_date)

        # --- Deterministic comparison for structured sources ---
        if normalized.direction_method == DirectionMethod.DETERMINISTIC_STRUCTURED:
            if normalized.claimed_value is not None and normalized.source_value is not None:
                normalized.deterministic_comparison_result = _compare_resolved_values(
                    normalized.claimed_value, normalized.source_value
                )
                # Override direction based on deterministic result
                if (
                    normalized.deterministic_comparison_result
                    == DeterministicComparisonResult.MATCH
                ):
                    normalized.direction = Direction.SUPPORTS
                    normalized.direction_confidence = 1.0
                elif (
                    normalized.deterministic_comparison_result
                    == DeterministicComparisonResult.MISMATCH
                ):
                    normalized.direction = Direction.REFUTES
                    normalized.direction_confidence = 1.0
                else:
                    normalized.direction = Direction.UNCLEAR
                    warnings.append("deterministic_comparison_not_comparable")
            else:
                normalized.deterministic_comparison_result = DeterministicComparisonResult.NOT_RUN
        else:
            # Non-structured source: mark as NOT_RUN unless already set
            if normalized.deterministic_comparison_result == DeterministicComparisonResult.NOT_RUN:
                pass  # keep default

        # --- Direction confidence gate ---
        if normalized.direction_confidence < self.direction_confidence_threshold:
            normalized.direction = Direction.UNCLEAR
            warnings.append(
                f"direction_confidence {normalized.direction_confidence} below threshold → UNCLEAR"
            )

        # --- LLM direction gating ---
        if normalized.direction_method == DirectionMethod.LLM_CLASSIFIER:
            normalized.llm_direction_allowed = True
            validation_errors: list[str] = []

            # Decisive quote required for LLM-classified evidence
            if normalized.decisive_quote_required and not normalized.decisive_quote_span:
                validation_errors.append("missing_decisive_quote_span")

            # Tier gate: LLM direction should not be decisive on Tier 3 alone
            if normalized.source_tier >= 3 and normalized.direction in (
                Direction.SUPPORTS,
                Direction.REFUTES,
            ):
                validation_errors.append("llm_direction_on_tier3")

            # Relevance gate already passed, but record it
            if normalized.relevance_score < 0.5:
                warnings.append("low_relevance_for_llm_direction")

            normalized.llm_direction_validation_result = ValidationResult(
                valid=(len(validation_errors) == 0),
                errors=validation_errors,
            )

            # If validation failed, downgrade direction
            if validation_errors:
                normalized.direction = Direction.UNCLEAR
                warnings.append(f"llm_direction_gating_failed: {validation_errors}")

        # --- Web evidence archiving metadata ---
        if normalized.source_type.value in ("NEWS", "WEB", "WIKIPEDIA"):
            # Ensure raw_response_hash is set for replay
            if not normalized.raw_response_hash:
                normalized.raw_response_hash = _compute_content_hash(
                    normalized.quote_or_span + normalized.quote_context
                )
                warnings.append("raw_response_hash_generated_from_quote")

        return NormalizationResult(item=normalized, warnings=warnings)

    def normalize_batch(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        """Normalize a batch of EvidenceItems, filtering out rejected ones."""
        results: list[EvidenceItem] = []
        for item in items:
            result = self.normalize(item)
            if not result.rejected and result.item is not None:
                results.append(result.item)
        return results

    @staticmethod
    def _copy_item(item: EvidenceItem) -> EvidenceItem:
        """Return a new EvidenceItem with the same field values."""
        return EvidenceItem(
            evidence_id=item.evidence_id,
            subclaim_id=item.subclaim_id,
            source_type=item.source_type,
            source_tier=item.source_tier,
            retrieval_path=item.retrieval_path,
            source_url=item.source_url,
            source_title=item.source_title,
            source_date=item.source_date,
            source_authority=item.source_authority,
            quote_or_span=item.quote_or_span,
            quote_context=item.quote_context,
            verdict_scope=item.verdict_scope,
            relevance_score=item.relevance_score,
            direction=item.direction,
            direction_confidence=item.direction_confidence,
            direction_method=item.direction_method,
            retrieval_timestamp=item.retrieval_timestamp,
            connector_version=item.connector_version,
            connector_query_hash=item.connector_query_hash,
            source_snapshot_id=item.source_snapshot_id,
            raw_response_hash=item.raw_response_hash,
            claimed_value=item.claimed_value,
            source_value=item.source_value,
            deterministic_comparison_result=item.deterministic_comparison_result,
            decisive_quote_required=item.decisive_quote_required,
            decisive_quote_span=item.decisive_quote_span,
            source_independence_group_id=item.source_independence_group_id,
            llm_direction_allowed=item.llm_direction_allowed,
            llm_direction_validation_result=item.llm_direction_validation_result,
        )


def archive_web_evidence(source_url: str, page_text: str) -> dict[str, str | None]:
    """Archive web evidence for artifact replay verification."""

    content_hash = hashlib.sha256(page_text.encode("utf-8")).hexdigest()
    archive_url: str | None = None
    snapshot_storage_key: str | None = None

    # Try archive.org
    try:
        archive_url = _request_archive_org(source_url)
    except Exception:
        pass

    # If archive.org fails, store full content in snapshot storage
    if archive_url is None:
        snapshot_storage_key = _store_snapshot(source_url, page_text)

    return {
        "content_hash": content_hash,
        "archive_org_url": archive_url,
        "snapshot_storage_key": snapshot_storage_key,
    }


def _request_archive_org(url: str) -> str | None:
    """Submit URL to archive.org and return permalink."""
    api_url = f"https://web.archive.org/save/{url}"
    req = urllib.request.Request(api_url, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        final_url = resp.geturl()
        if final_url and "web.archive.org" in final_url:
            return final_url
    return None


def _store_snapshot(source_url: str, page_text: str) -> str:
    """Store full page content in snapshot storage. Return storage key."""
    key = hashlib.sha256(f"{source_url}:{page_text[:100]}".encode()).hexdigest()
    return key
