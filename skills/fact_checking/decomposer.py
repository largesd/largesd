"""
Deterministic claim decomposition for fact checking v1.

The v1 contract stays intentionally narrow. We split simple compound claims
for diagnostics and routing, but we keep the decomposition rule-based so the
runtime remains inspectable and testable.
"""

import re

from .models import Subclaim
from .normalization import ClaimNormalizer

_COMPOUND_RE = re.compile(r"\s+(?:and|while)\s+")
_TRAILING_SCOPE_RE = re.compile(
    r"^(?P<body>.+?)(?P<suffix>(?:\s+(?:in|on|during|as of)\s+[^,;]+)+)$"
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_DATE_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},\s+\d{4}\b"
)
_QUANTITY_RE = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_NEGATION_RE = re.compile(r"\b(?:not|no longer|never|didn't|doesn't|isn't|wasn't|aren't|weren't)\b")


class ClaimDecomposer:
    """Rule-based decomposition for empirical claims."""

    SUPPORTED_FAMILIES = {
        "office_holder",
        "inception_date",
        "headquarters_location",
        "location",
        "birth_date",
        "death_date",
        "life_status",
    }

    @classmethod
    def decompose(cls, claim_text: str, source_fact_id: str | None = None) -> list[Subclaim]:
        normalized = ClaimNormalizer.normalize(claim_text)
        clauses = cls._split_compound(normalized)
        subclaims: list[Subclaim] = []

        for clause in clauses:
            clean_clause = clause.strip()
            if not clean_clause:
                continue
            family = cls.classify_claim_family(clean_clause)
            subclaims.append(
                Subclaim(
                    subclaim_id=ClaimNormalizer.compute_hash(clean_clause)[:12],
                    claim_text=clean_clause,
                    normalized_claim_text=clean_clause,
                    claim_family=family,
                    actor=cls._extract_actor(clean_clause, family),
                    geography=cls._extract_geography(clean_clause),
                    time_scope=cls._extract_time_scope(clean_clause),
                    quantity=cls._extract_quantity(clean_clause),
                    negated=bool(_NEGATION_RE.search(clean_clause)),
                    source_fact_id=source_fact_id,
                )
            )

        return subclaims or [
            Subclaim(
                subclaim_id=ClaimNormalizer.compute_hash(normalized)[:12],
                claim_text=normalized,
                normalized_claim_text=normalized,
                claim_family=cls.classify_claim_family(normalized),
                actor=cls._extract_actor(normalized, cls.classify_claim_family(normalized)),
                geography=cls._extract_geography(normalized),
                time_scope=cls._extract_time_scope(normalized),
                quantity=cls._extract_quantity(normalized),
                negated=bool(_NEGATION_RE.search(normalized)),
                source_fact_id=source_fact_id,
            )
        ]

    @classmethod
    def classify_claim_family(cls, normalized_claim: str) -> str:
        if re.search(
            r"\b(?:is|was) (?:the )?(?:ceo|chief executive officer|prime minister|president|mayor|governor) of\b",
            normalized_claim,
        ):
            return "office_holder"
        if re.search(r"\bwas founded (?:in|on)\b|\bfounded in\b", normalized_claim):
            return "inception_date"
        if re.search(r"\bis headquartered in\b", normalized_claim):
            return "headquarters_location"
        if re.search(r"\bis (?:located )?in\b", normalized_claim):
            return "location"
        if re.search(r"\bwas born (?:in|on)\b", normalized_claim):
            return "birth_date"
        if re.search(r"\bdied (?:in|on)\b", normalized_claim):
            return "death_date"
        if re.search(r"\b(?:is|was) (?:alive|dead)\b", normalized_claim):
            return "life_status"
        return "unsupported"

    @classmethod
    def _split_compound(cls, normalized_claim: str) -> list[str]:
        semicolon_parts = [part.strip() for part in normalized_claim.split(";") if part.strip()]
        parts = semicolon_parts or [normalized_claim]
        decomposed: list[str] = []

        for part in parts:
            if not _COMPOUND_RE.search(part):
                decomposed.append(part)
                continue

            segments = _COMPOUND_RE.split(part)
            if len(segments) != 2:
                decomposed.append(part)
                continue

            left, right = segments[0].strip(), segments[1].strip()
            right_body, suffix = cls._extract_trailing_scope(right)

            if suffix and not cls._has_trailing_scope(left):
                decomposed.append(f"{left}{suffix}".strip())
                decomposed.append(f"{right_body}{suffix}".strip())
            else:
                decomposed.extend([left, right])

        return decomposed

    @staticmethod
    def _extract_trailing_scope(text: str) -> tuple[str, str]:
        match = _TRAILING_SCOPE_RE.match(text)
        if not match:
            return text, ""
        return match.group("body").strip(), match.group("suffix")

    @staticmethod
    def _has_trailing_scope(text: str) -> bool:
        return bool(_TRAILING_SCOPE_RE.match(text))

    @staticmethod
    def _extract_actor(text: str, family: str) -> str | None:
        patterns = {
            "office_holder": r"^(?P<actor>.+?)\s+(?:is|was)\s+(?:the )?(?:ceo|chief executive officer|prime minister|president|mayor|governor)\s+of\b",
            "inception_date": r"^(?P<actor>.+?)\s+was founded\b",
            "headquarters_location": r"^(?P<actor>.+?)\s+is headquartered\b",
            "location": r"^(?P<actor>.+?)\s+is (?:located )?in\b",
            "birth_date": r"^(?P<actor>.+?)\s+was born\b",
            "death_date": r"^(?P<actor>.+?)\s+died\b",
            "life_status": r"^(?P<actor>.+?)\s+(?:is|was)\s+(?:alive|dead)\b",
        }
        pattern = patterns.get(family)
        if not pattern:
            return None
        match = re.match(pattern, text)
        return match.group("actor").strip() if match else None

    @staticmethod
    def _extract_geography(text: str) -> str | None:
        match = re.search(
            r"\b(?:in|of)\s+([a-z][a-z\s.\-]+?)(?:\s+(?:in|on)\s+(?:19|20)\d{2}\b|$)", text
        )
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_time_scope(text: str) -> str | None:
        match = _DATE_RE.search(text) or _YEAR_RE.search(text)
        return match.group(0) if match else None

    @staticmethod
    def _extract_quantity(text: str) -> str | None:
        match = _QUANTITY_RE.search(text)
        return match.group(0) if match else None
