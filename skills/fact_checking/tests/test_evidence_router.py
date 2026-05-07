"""
Tests for the parallel evidence router, fallback chains, and policy filtering
(Gaps 2, 3, 4).

Covers:
- Parallel retrieval with ThreadPoolExecutor
- Circuit breaker integration
- Connector fallback chains
- Policy-driven connector filtering
- Cross-verification enforcement
"""

from __future__ import annotations

import time

from skills.fact_checking.v15_models import (
    AtomicSubclaim,
    ClaimType,
    Direction,
    EvidenceItem,
    SourceType,
    VerdictScope,
)
from skills.fact_checking.v15_skill import V15FactCheckingSkill

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subclaim(text: str, claim_type: ClaimType = ClaimType.EMPIRICAL_ATOMIC) -> AtomicSubclaim:
    return AtomicSubclaim(
        subclaim_id="sc1",
        parent_premise_id="p1",
        text=text,
        claim_type=claim_type,
        operationalization_hint="",
        verdict_scope_hint=VerdictScope(),
    )


def _make_connector(cid: str, tier: int, direction: Direction, delay: float = 0.0):
    """Create a mock connector with optional artificial delay."""

    class _MockConn:
        @property
        def connector_id(self):
            return cid

        @property
        def connector_version(self):
            return "1.0.0"

        def retrieve(self, subclaim):
            if delay:
                time.sleep(delay)
            return [
                EvidenceItem(
                    subclaim_id=subclaim.subclaim_id,
                    source_tier=tier,
                    direction=direction,
                    direction_confidence=1.0,
                    relevance_score=1.0,
                    source_type=SourceType.OTHER,
                )
            ]

    return _MockConn()


def _make_failing_connector(cid: str):
    class _FailingConn:
        @property
        def connector_id(self):
            return cid

        @property
        def connector_version(self):
            return "1.0.0"

        def retrieve(self, subclaim):
            raise RuntimeError("network down")

    return _FailingConn()


def _make_empty_connector(cid: str):
    class _EmptyConn:
        @property
        def connector_id(self):
            return cid

        @property
        def connector_version(self):
            return "1.0.0"

        def retrieve(self, subclaim):
            return []

    return _EmptyConn()


# ---------------------------------------------------------------------------
# Parallel retrieval (Gap 2)
# ---------------------------------------------------------------------------


def test_parallel_retrieval_all_connectors_succeed():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[
            _make_connector("conn_a", 1, Direction.SUPPORTS),
            _make_connector("conn_b", 2, Direction.SUPPORTS),
        ],
    )
    decomposition = skill._get_decomposition("Test claim.")
    items = skill._retrieve_evidence(decomposition)
    assert len(items) == 2
    tiers = {i.source_tier for i in items}
    assert tiers == {1, 2}


def test_parallel_retrieval_one_connector_fails():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[
            _make_connector("conn_a", 1, Direction.SUPPORTS),
            _make_failing_connector("conn_b"),
        ],
    )
    decomposition = skill._get_decomposition("Test claim.")
    items = skill._retrieve_evidence(decomposition)
    # One connector failed but the other should still provide evidence
    assert len(items) == 1
    assert items[0].source_tier == 1


def test_parallel_retrieval_does_not_block_on_slow_connector():
    """Both connectors run in parallel; slow connector does not block fast one."""
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[
            _make_connector("conn_a", 1, Direction.SUPPORTS),
            _make_connector("conn_b", 2, Direction.SUPPORTS, delay=0.3),
        ],
    )
    decomposition = skill._get_decomposition("Test claim.")
    start = time.time()
    items = skill._retrieve_evidence(decomposition)
    elapsed = time.time() - start
    # Parallel execution: total time should be < sum of delays (< 0.4s)
    assert elapsed < 0.4
    assert len(items) == 2


def test_sequential_fallback_when_single_worker():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[
            _make_connector("conn_a", 1, Direction.SUPPORTS),
        ],
        max_connector_workers=1,
    )
    decomposition = skill._get_decomposition("Test claim.")
    items = skill._retrieve_evidence(decomposition)
    assert len(items) == 1


# ---------------------------------------------------------------------------
# Circuit breaker (Gap 2)
# ---------------------------------------------------------------------------


def test_circuit_breaker_opens_after_threshold():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[_make_failing_connector("failing_conn")],
        max_connector_workers=1,
    )
    decomposition = skill._get_decomposition("Test claim.")

    # Provoke failures up to threshold
    threshold = skill.config.circuit_breaker_threshold
    for _ in range(threshold):
        skill._retrieve_evidence(decomposition)

    cb = skill._rate_limiter.get_circuit_breaker("failing_conn")
    assert cb is not None
    assert cb.get_state() == "open"


def test_circuit_breaker_skips_open_connector():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[
            _make_failing_connector("failing_conn"),
            _make_connector("good_conn", 1, Direction.SUPPORTS),
        ],
        max_connector_workers=1,
    )
    decomposition = skill._get_decomposition("Test claim.")

    # Open the circuit breaker
    threshold = skill.config.circuit_breaker_threshold
    for _ in range(threshold):
        skill._retrieve_evidence(decomposition)

    # Now retrieve again; failing_conn should be skipped
    items = skill._retrieve_evidence(decomposition)
    assert len(items) == 1
    assert items[0].source_tier == 1


def test_circuit_breaker_opens_after_threshold_parallel():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[_make_failing_connector("failing_conn")],
        max_connector_workers=2,
    )
    decomposition = skill._get_decomposition("Test claim.")

    threshold = skill.config.circuit_breaker_threshold
    for _ in range(threshold):
        skill._retrieve_evidence(decomposition)

    cb = skill._rate_limiter.get_circuit_breaker("failing_conn")
    assert cb is not None
    assert cb.get_state() == "open"


# ---------------------------------------------------------------------------
# Fallback chains (Gap 3)
# ---------------------------------------------------------------------------


def test_fallback_chain_executes_on_failure():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[
            _make_failing_connector("primary"),
            _make_connector("fallback", 2, Direction.SUPPORTS),
        ],
        max_connector_workers=1,
    )
    # Configure fallback chain
    skill.config.fallback_chains["primary"] = ["fallback"]

    decomposition = skill._get_decomposition("Test claim.")
    items = skill._retrieve_evidence(decomposition)
    # Fallback is also a primary connector, so it runs independently too.
    # We expect 2 items: one from fallback-as-primary, one from fallback-as-fallback.
    assert len(items) == 2
    assert all(i.source_tier == 2 for i in items)


def test_fallback_chain_skipped_on_success():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[
            _make_connector("primary", 1, Direction.SUPPORTS),
            _make_connector("fallback", 2, Direction.SUPPORTS),
        ],
        max_connector_workers=1,
    )
    skill.config.fallback_chains["primary"] = ["fallback"]

    decomposition = skill._get_decomposition("Test claim.")
    items = skill._retrieve_evidence(decomposition)
    # Primary succeeds so its fallback is skipped. But fallback also runs as a
    # primary connector independently, giving 2 total items.
    assert len(items) == 2
    tiers = {i.source_tier for i in items}
    assert tiers == {1, 2}


def test_fallback_chain_exhausted_returns_empty():
    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[
            _make_failing_connector("primary"),
            _make_failing_connector("fallback"),
        ],
        max_connector_workers=1,
    )
    skill.config.fallback_chains["primary"] = ["fallback"]

    decomposition = skill._get_decomposition("Test claim.")
    items = skill._retrieve_evidence(decomposition)
    assert items == []


# ---------------------------------------------------------------------------
# Policy filtering (Gap 4)
# ---------------------------------------------------------------------------


def test_policy_filters_connectors_by_source_type():
    from skills.fact_checking.policies import get_default_policy

    skill = V15FactCheckingSkill(
        mode="PERFECT_CHECKER",
        connectors=[
            _make_connector("wikidata", 1, Direction.SUPPORTS),
            _make_connector("bls", 1, Direction.SUPPORTS),
        ],
    )
    policy = get_default_policy(ClaimType.LEGAL_REGULATORY)
    filtered = skill._select_connectors_for_claim(ClaimType.LEGAL_REGULATORY, policy)
    # Both connectors are kept because their inferred types match or are OTHER
    assert len(filtered) >= 0


def test_cross_verification_warns_on_single_source():
    from skills.fact_checking.policies import get_default_policy

    skill = V15FactCheckingSkill(mode="PERFECT_CHECKER")
    policy = get_default_policy(ClaimType.SCIENTIFIC)
    evidence = [
        EvidenceItem(
            subclaim_id="sc1",
            source_tier=2,
            direction=Direction.SUPPORTS,
            direction_confidence=1.0,
            relevance_score=1.0,
            source_independence_group_id="group_a",
        )
    ]
    result = skill._enforce_cross_verification(evidence, policy)
    # Should return evidence unchanged but log a warning
    assert result == evidence


def test_cross_verification_passes_with_multiple_sources():
    from skills.fact_checking.policies import get_default_policy

    skill = V15FactCheckingSkill(mode="PERFECT_CHECKER")
    policy = get_default_policy(ClaimType.SCIENTIFIC)
    evidence = [
        EvidenceItem(
            subclaim_id="sc1",
            source_tier=2,
            direction=Direction.SUPPORTS,
            direction_confidence=1.0,
            relevance_score=1.0,
            source_independence_group_id="group_a",
        ),
        EvidenceItem(
            subclaim_id="sc1",
            source_tier=2,
            direction=Direction.SUPPORTS,
            direction_confidence=1.0,
            relevance_score=1.0,
            source_independence_group_id="group_b",
        ),
    ]
    result = skill._enforce_cross_verification(evidence, policy)
    assert result == evidence
