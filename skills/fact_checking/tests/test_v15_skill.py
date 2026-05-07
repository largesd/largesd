"""
Unit tests for the v1.5 production bridge skill (V15FactCheckingSkill).

Covers:
- OFFLINE mode returns deterministic INSUFFICIENT
- PERFECT_CHECKER mode with mock connectors
- Result mapping: v1.5 status → legacy verdict + factuality_score
- Diagnostics enrichment with v1.5 fields
- Async interface delegation
"""

from __future__ import annotations

import pytest

from skills.fact_checking.models import (
    FactCheckStatus,
    FactCheckVerdict,
    RequestContext,
)
from skills.fact_checking.v15_models import (
    Direction,
    EvidenceItem,
)
from skills.fact_checking.v15_skill import V15FactCheckingSkill

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connector_with_tier_direction(tier: int, direction):
    """Create a mock connector that returns evidence matching the subclaim_id."""

    class _MockConn:
        @property
        def connector_id(self):
            return "mock"

        @property
        def connector_version(self):
            return "1.0.0"

        def retrieve(self, subclaim):
            return [
                EvidenceItem(
                    subclaim_id=subclaim.subclaim_id,
                    source_tier=tier,
                    direction=direction,
                    direction_confidence=1.0,
                    relevance_score=1.0,
                )
            ]

    return _MockConn()


def _make_connector_returning(evidence_items):
    """Create a mock connector that returns the given evidence (subclaim_id must match)."""

    class _MockConn:
        @property
        def connector_id(self):
            return "mock"

        @property
        def connector_version(self):
            return "1.0.0"

        def retrieve(self, subclaim):
            return evidence_items

    return _MockConn()


# ---------------------------------------------------------------------------
# OFFLINE mode
# ---------------------------------------------------------------------------


def test_offline_returns_insufficient():
    skill = V15FactCheckingSkill(mode="OFFLINE")
    result = skill.check_fact("The capital of France is Paris.")

    assert result.factuality_score == 0.5
    assert result.verdict == FactCheckVerdict.INSUFFICIENT
    assert result.status == FactCheckStatus.UNVERIFIED_OFFLINE
    assert result.fact_mode == "OFFLINE"
    assert result.algorithm_version == "fc-1.5"
    assert result.diagnostics["v15_status"] == "INSUFFICIENT"
    assert result.diagnostics["v15_p"] == 0.5
    assert result.diagnostics["v15_insufficiency_reason"] == "offline_mode"


def test_offline_with_request_context():
    skill = V15FactCheckingSkill(mode="OFFLINE")
    ctx = RequestContext(post_id="post_123")
    result = skill.check_fact("Test claim.", request_context=ctx)
    assert result.factuality_score == 0.5


# ---------------------------------------------------------------------------
# PERFECT_CHECKER mode with mock evidence
# ---------------------------------------------------------------------------


def test_perfect_checker_supported():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[_make_connector_with_tier_direction(1, Direction.SUPPORTS)],
    )
    result = skill.check_fact("The capital of France is Paris.")

    assert result.factuality_score == 1.0
    assert result.verdict == FactCheckVerdict.SUPPORTED
    assert result.status == FactCheckStatus.CHECKED
    assert result.algorithm_version == "fc-1.5"
    assert result.diagnostics["v15_status"] == "SUPPORTED"
    assert result.diagnostics["v15_p"] == 1.0
    assert result.diagnostics["v15_best_evidence_tier"] == 1
    assert result.evidence_tier_counts == {"TIER_1": 1, "TIER_2": 0, "TIER_3": 0}


def test_perfect_checker_refuted():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[_make_connector_with_tier_direction(1, Direction.REFUTES)],
    )
    result = skill.check_fact("The moon is made of cheese.")

    assert result.factuality_score == 0.0
    assert result.verdict == FactCheckVerdict.REFUTED
    assert result.status == FactCheckStatus.CHECKED
    assert result.diagnostics["v15_status"] == "REFUTED"
    assert result.diagnostics["v15_p"] == 0.0


def test_perfect_checker_insufficient_no_evidence():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[_make_connector_returning([])],
    )
    result = skill.check_fact("Some unverifiable claim about xyzabc123.")

    assert result.factuality_score == 0.5
    assert result.verdict == FactCheckVerdict.INSUFFICIENT
    assert result.diagnostics["v15_status"] == "INSUFFICIENT"
    assert result.diagnostics["v15_insufficiency_reason"] == "no_evidence_retrieved"


def test_perfect_checker_tier3_only_insufficient():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[_make_connector_with_tier_direction(3, Direction.SUPPORTS)],
    )
    result = skill.check_fact("Some claim with only weak evidence.")

    assert result.factuality_score == 0.5
    assert result.verdict == FactCheckVerdict.INSUFFICIENT
    assert result.diagnostics["v15_status"] == "INSUFFICIENT"
    assert result.diagnostics["v15_insufficiency_reason"] == "only_tier3_evidence"
    # Tier counts may be all-zero for INSUFFICIENT per v1.5 spec
    # (best_evidence_tier is null for INSUFFICIENT results)


# ---------------------------------------------------------------------------
# Result mapping diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_include_synthesis_logic():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[_make_connector_with_tier_direction(1, Direction.SUPPORTS)],
    )
    result = skill.check_fact("Test.")

    assert "v15_synthesis_logic" in result.diagnostics
    sl = result.diagnostics["v15_synthesis_logic"]
    assert "status_rule_applied" in sl
    assert "claim_expression_node_type" in sl


def test_diagnostics_include_subclaim_summaries():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[_make_connector_with_tier_direction(1, Direction.SUPPORTS)],
    )
    result = skill.check_fact("Test.")

    assert "v15_subclaim_summaries" in result.diagnostics
    summaries = result.diagnostics["v15_subclaim_summaries"]
    assert len(summaries) >= 1
    assert "subclaim_id" in summaries[0]
    assert "status" in summaries[0]


# ---------------------------------------------------------------------------
# Async interface
# ---------------------------------------------------------------------------


def test_async_disabled_raises():
    skill = V15FactCheckingSkill(mode="OFFLINE", enable_async=False)
    with pytest.raises(RuntimeError):
        skill.check_fact_async("Test.")


def test_async_returns_completed_job():
    skill = V15FactCheckingSkill(mode="ONLINE_ALLOWLIST", enable_async=True)
    job = skill.check_fact_async("Test claim.")
    assert job.status == "completed"
    assert job.result is not None
    assert job.result.factuality_score == 0.5  # OFFLINE behavior (no connectors wired)


def test_get_job_result_returns_none():
    skill = V15FactCheckingSkill(mode="OFFLINE")
    assert skill.get_job_result("any_id") is None


def test_get_job_status_returns_none():
    skill = V15FactCheckingSkill(mode="OFFLINE")
    assert skill.get_job_status("any_id") is None


# ---------------------------------------------------------------------------
# Mode aliases
# ---------------------------------------------------------------------------


def test_mode_aliases():
    skill = V15FactCheckingSkill(mode="simulated")
    assert skill.mode == "OFFLINE"

    skill2 = V15FactCheckingSkill(mode="perfect_checker")
    assert skill2.mode == "PERFECT_CHECKER"

    skill3 = V15FactCheckingSkill(mode="live_connectors")
    assert skill3.mode == "LIVE_CONNECTORS"


# ---------------------------------------------------------------------------
# Claim truncation
# ---------------------------------------------------------------------------


def test_long_claim_truncated():
    from skills.fact_checking.config import FactCheckConfig

    cfg = FactCheckConfig(max_claim_length=500)
    skill = V15FactCheckingSkill(mode="OFFLINE", config=cfg)
    long_claim = "A" * 600
    result = skill.check_fact(long_claim)
    assert len(result.claim_text) <= 500
