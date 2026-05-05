"""Regression tests for the fact-checking gold corpus.

Place this file next to the existing ``test_fact_check_skill.py`` and keep the
corpus stable. When connector or policy behavior changes, this suite tells you
which known edge cases changed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import pytest

from tests.gold_fact_check_cases import GOLD_FACT_CHECK_CASES
from skills.fact_checking.skill import FactCheckingSkill

try:  # SourceConfidence may live in models or connectors depending on revision.
    from skills.fact_checking.models import EvidenceTier, SourceConfidence, SourceResult
except ImportError:  # pragma: no cover - compatibility for older layout
    from skills.fact_checking.connectors import SourceConfidence, SourceResult
    from skills.fact_checking.models import EvidenceTier

try:
    from skills.fact_checking.policy import strict_policy
except ImportError:  # pragma: no cover - older branches may not have policy.py yet
    strict_policy = None


def _enum_value(enum_cls: Any, name: str) -> Any:
    """Return enum member by name or value, tolerant of lowercase string enums."""
    if hasattr(enum_cls, name):
        return getattr(enum_cls, name)
    lowered = name.lower()
    for member in enum_cls:
        if str(getattr(member, "name", "")).upper() == name:
            return member
        if str(getattr(member, "value", "")).lower() == lowered:
            return member
    raise AssertionError(f"Could not find {name!r} in {enum_cls!r}")


def _normalize_verdict(verdict: Any) -> str:
    raw = getattr(verdict, "name", verdict)
    raw = getattr(raw, "value", raw)
    return str(raw).upper()


def _normalize_score(result: Any) -> float:
    if hasattr(result, "factuality_score"):
        return float(result.factuality_score)
    if hasattr(result, "score"):
        return float(result.score)
    raise AssertionError(f"Result has no factuality score field: {result!r}")


class FixtureConnector:
    """One deterministic connector result used by one gold test case."""

    def __init__(self, spec: Dict[str, Any]) -> None:
        self._spec = spec
        self._source_id = spec["source_id"]
        self._tier = _enum_value(EvidenceTier, spec.get("tier", "TIER_1"))

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def tier(self) -> Any:
        return self._tier

    def query(self, normalized_claim: str, claim_hash: str) -> Optional[Any]:
        confidence_name = self._spec.get("confidence", "SILENT")
        if confidence_name == "SILENT":
            return None

        confidence = _enum_value(SourceConfidence, confidence_name)
        kwargs = dict(
            source_id=self.source_id,
            source_url=f"fixture://gold/{self.source_id}/{claim_hash[:12]}",
            source_title=f"Gold fixture {self.source_id}",
            confidence=confidence,
            excerpt=self._spec.get("excerpt", "Gold fixture evidence."),
            content_hash=f"gold-{self.source_id}-{claim_hash[:16]}",
            retrieved_at=datetime.now(timezone.utc),
        )

        # Support both `tier=` and older/newer `evidence_tier=` field names.
        try:
            return SourceResult(**kwargs, tier=self.tier)
        except TypeError:
            return SourceResult(**kwargs, evidence_tier=self.tier)


def _make_skill(source_specs: Iterable[Dict[str, Any]]) -> FactCheckingSkill:
    connectors = [FixtureConnector(spec) for spec in source_specs]
    kwargs: Dict[str, Any] = {"mode": "PERFECT", "connectors": connectors}
    if strict_policy is not None:
        kwargs["policy"] = strict_policy()

    try:
        return FactCheckingSkill(**kwargs)
    except TypeError:
        # Compatibility with older branches that used PERFECT_CHECKER naming.
        kwargs["mode"] = "PERFECT_CHECKER"
        return FactCheckingSkill(**kwargs)


def _run_check(skill: FactCheckingSkill, claim: str) -> Any:
    if hasattr(skill, "check_fact"):
        return skill.check_fact(claim)
    if hasattr(skill, "check_fact_async"):
        return asyncio.run(skill.check_fact_async(claim))
    raise AssertionError("FactCheckingSkill exposes neither check_fact nor check_fact_async")


def test_gold_corpus_shape_and_coverage() -> None:
    assert 50 <= len(GOLD_FACT_CHECK_CASES) <= 100

    ids = [case["id"] for case in GOLD_FACT_CHECK_CASES]
    assert len(ids) == len(set(ids)), "Gold case IDs must be unique"

    verdicts = {case["expected_verdict"] for case in GOLD_FACT_CHECK_CASES}
    assert {"SUPPORTED", "REFUTED", "INSUFFICIENT"}.issubset(verdicts)

    all_edges = {edge for case in GOLD_FACT_CHECK_CASES for edge in case["edge_cases"]}
    required_edges = {
        "supported",
        "refuted",
        "insufficient",
        "temporal",
        "scoped",
        "compound",
        "conflict",
        "weak_source",
        "future",
        "missing_date",
    }
    assert required_edges.issubset(all_edges)

    for case in GOLD_FACT_CHECK_CASES:
        assert case["claim"].strip()
        assert case["source_types"], case["id"]
        assert case["edge_cases"], case["id"]
        assert case["source_specs"], case["id"]
        assert case["expected_score"] in {0.0, 0.5, 1.0}


@pytest.mark.parametrize("case", GOLD_FACT_CHECK_CASES, ids=lambda c: c["id"])
def test_gold_corpus_against_fact_check_skill(case: Dict[str, Any]) -> None:
    skill = _make_skill(case["source_specs"])
    result = _run_check(skill, case["claim"])

    assert _normalize_verdict(result.verdict) == case["expected_verdict"]
    assert _normalize_score(result) == pytest.approx(case["expected_score"])


def test_gold_cases_document_source_types() -> None:
    source_types = {source_type for case in GOLD_FACT_CHECK_CASES for source_type in case["source_types"]}
    assert {
        "TIER_1_PRIMARY",
        "TIER_2_SECONDARY",
        "TIER_3_CONTEXTUAL",
        "CONFLICTING_TIER_1",
        "NO_RELEVANT_SOURCE",
        "PARTIAL_EVIDENCE",
    }.issubset(source_types)
