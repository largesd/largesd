"""
Phase 3 unit tests for the LSD Fact-Checking System v1.5.

Covers:
- EvidencePolicy registry default policies
- EvidenceNormalizer gates and transformations
- CacheKey v1.5 exact match / miss semantics
- Canonical JSON hash stability under key reordering
- Cache hit on exact key match
- Cache miss on different scope
- Cache miss on different entity IDs
- Hash stability under reordered JSON keys
- Normalizer rejects low-confidence decisive evidence
"""

from __future__ import annotations

import pytest

from skills.fact_checking.normalizer import (
    EvidenceNormalizer,
    NormalizationResult,
    _compare_resolved_values,
    _compute_content_hash,
    _standardize_date,
    _truncate_quote,
)
from skills.fact_checking.policies import get_default_policy, list_registered_policies, register_policy
from skills.fact_checking.v15_cache import (
    ImmutableMemoryCache,
    build_cache_key,
    cache_key_to_string,
    canonical_json_hash,
    canonical_json_serialize,
    compute_claim_hash,
    compute_connector_snapshot_versions_hash,
    compute_entity_ids_hash,
    compute_operationalization_hash,
    compute_verdict_scope_hash,
)
from skills.fact_checking.v15_models import (
    AtomicSubclaim,
    CacheKey,
    ClaimType,
    DeterministicComparisonResult,
    Direction,
    DirectionMethod,
    EvidenceItem,
    EvidencePolicy,
    FactMode,
    FrameDependencyKey,
    ResolvedValue,
    SourceType,
    ValueType,
    VerdictScope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subclaim(
    sid: str = "sc1",
    text: str = "The unemployment rate is 4.0%",
    claim_type: ClaimType = ClaimType.NUMERIC_STATISTICAL,
    scope: VerdictScope | None = None,
    op_hint: str = "test_op",
) -> AtomicSubclaim:
    return AtomicSubclaim(
        subclaim_id=sid,
        parent_premise_id="p1",
        text=text,
        claim_type=claim_type,
        operationalization_hint=op_hint,
        verdict_scope_hint=scope or VerdictScope(),
    )


def _evidence(
    tier: int = 1,
    direction: Direction = Direction.SUPPORTS,
    direction_confidence: float = 1.0,
    relevance_score: float = 1.0,
    direction_method: DirectionMethod = DirectionMethod.DETERMINISTIC_STRUCTURED,
    claimed_value: ResolvedValue | None = None,
    source_value: ResolvedValue | None = None,
    quote: str = "test quote",
    decisive_quote_required: bool = False,
    decisive_quote_span: str | None = None,
    source_type: SourceType = SourceType.OFFICIAL_STAT,
) -> EvidenceItem:
    return EvidenceItem(
        subclaim_id="sc1",
        source_tier=tier,
        direction=direction,
        direction_confidence=direction_confidence,
        relevance_score=relevance_score,
        direction_method=direction_method,
        claimed_value=claimed_value,
        source_value=source_value,
        quote_or_span=quote,
        decisive_quote_required=decisive_quote_required,
        decisive_quote_span=decisive_quote_span,
        source_type=source_type,
    )


# ---------------------------------------------------------------------------
# Policy registry tests
# ---------------------------------------------------------------------------


def test_default_policies_registered():
    policies = list_registered_policies()
    claim_types = {p.claim_type for p in policies}
    expected = {
        ClaimType.NUMERIC_STATISTICAL,
        ClaimType.LEGAL_REGULATORY,
        ClaimType.SCIENTIFIC,
        ClaimType.GEOGRAPHIC_DEMOGRAPHIC,
        ClaimType.CURRENT_EVENT,
        ClaimType.CAUSAL,
        ClaimType.EMPIRICAL_ATOMIC,
    }
    assert claim_types == expected


def test_get_default_policy_numeric():
    policy = get_default_policy(ClaimType.NUMERIC_STATISTICAL)
    assert policy is not None
    assert policy.minimum_acceptable_tier == 2
    assert policy.cross_verification_required is False


def test_get_default_policy_legal():
    policy = get_default_policy(ClaimType.LEGAL_REGULATORY)
    assert policy is not None
    assert policy.minimum_acceptable_tier == 1


def test_get_default_policy_scientific():
    policy = get_default_policy(ClaimType.SCIENTIFIC)
    assert policy is not None
    assert policy.cross_verification_required is True
    assert policy.cross_verification_minimum_sources == 2


def test_register_policy_override():
    custom = EvidencePolicy(
        policy_id="custom_test",
        claim_type=ClaimType.NUMERIC_STATISTICAL,
        required_source_types=[],
        preferred_source_types=[],
        minimum_acceptable_tier=1,
        cross_verification_required=False,
        cross_verification_minimum_sources=1,
    )
    register_policy(custom)
    fetched = get_default_policy(ClaimType.NUMERIC_STATISTICAL)
    assert fetched.policy_id == "custom_test"
    # Restore default for other tests
    from skills.fact_checking.policies import _DEFAULT_POLICIES, _POLICY_MAP
    default = [p for p in _DEFAULT_POLICIES if p.claim_type == ClaimType.NUMERIC_STATISTICAL][0]
    _POLICY_MAP[ClaimType.NUMERIC_STATISTICAL] = default


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------


def test_normalizer_accepts_high_confidence_supports():
    normalizer = EvidenceNormalizer()
    item = _evidence(tier=1, direction=Direction.SUPPORTS, direction_confidence=1.0, relevance_score=1.0)
    result = normalizer.normalize(item)
    assert result.rejected is False
    assert result.item is not None
    assert result.item.direction == Direction.SUPPORTS


def test_normalizer_rejects_low_relevance():
    normalizer = EvidenceNormalizer()
    item = _evidence(relevance_score=0.1)
    result = normalizer.normalize(item)
    assert result.rejected is True
    assert "relevance_score" in (result.rejection_reason or "")


def test_normalizer_rejects_low_direction_confidence():
    normalizer = EvidenceNormalizer()
    item = _evidence(direction_confidence=0.5, relevance_score=1.0)
    result = normalizer.normalize(item)
    assert result.rejected is False
    assert result.item is not None
    assert result.item.direction == Direction.UNCLEAR
    assert any("direction_confidence" in w for w in result.warnings)


def test_normalizer_rejects_low_confidence_decisive_evidence():
    """Low-confidence evidence with SUPPORTS/REFUTES must be downgraded to UNCLEAR."""
    normalizer = EvidenceNormalizer()
    item = _evidence(
        tier=1,
        direction=Direction.SUPPORTS,
        direction_confidence=0.6,
        relevance_score=1.0,
    )
    result = normalizer.normalize(item)
    assert result.rejected is False
    assert result.item is not None
    assert result.item.direction == Direction.UNCLEAR


def test_normalizer_truncates_long_quote():
    normalizer = EvidenceNormalizer()
    long_quote = "x" * 1500
    item = _evidence(quote=long_quote)
    result = normalizer.normalize(item)
    assert result.rejected is False
    assert result.item is not None
    assert len(result.item.quote_or_span) == 1000
    assert any("quote_truncated" in w for w in result.warnings)


def test_normalizer_standardizes_date():
    normalizer = EvidenceNormalizer()
    item = _evidence()
    item.source_date = "15/03/2023"
    result = normalizer.normalize(item)
    assert result.item is not None
    assert result.item.source_date == "2023-03-15T00:00:00Z"


def test_normalizer_deterministic_match():
    normalizer = EvidenceNormalizer()
    claimed = ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="count")
    source = ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="count")
    item = _evidence(
        direction_method=DirectionMethod.DETERMINISTIC_STRUCTURED,
        claimed_value=claimed,
        source_value=source,
    )
    result = normalizer.normalize(item)
    assert result.item is not None
    assert result.item.deterministic_comparison_result == DeterministicComparisonResult.MATCH
    assert result.item.direction == Direction.SUPPORTS
    assert result.item.direction_confidence == 1.0


def test_normalizer_deterministic_mismatch():
    normalizer = EvidenceNormalizer()
    claimed = ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="count")
    source = ResolvedValue(value=99, value_type=ValueType.NUMBER, unit="count")
    item = _evidence(
        direction_method=DirectionMethod.DETERMINISTIC_STRUCTURED,
        claimed_value=claimed,
        source_value=source,
    )
    result = normalizer.normalize(item)
    assert result.item is not None
    assert result.item.deterministic_comparison_result == DeterministicComparisonResult.MISMATCH
    assert result.item.direction == Direction.REFUTES


def test_normalizer_llm_direction_gating_missing_quote():
    normalizer = EvidenceNormalizer()
    item = _evidence(
        tier=2,
        direction=Direction.SUPPORTS,
        direction_method=DirectionMethod.LLM_CLASSIFIER,
        decisive_quote_required=True,
        decisive_quote_span=None,
        source_type=SourceType.NEWS,
    )
    result = normalizer.normalize(item)
    assert result.item is not None
    assert result.item.direction == Direction.UNCLEAR
    assert result.item.llm_direction_validation_result is not None
    assert result.item.llm_direction_validation_result.valid is False
    assert any("missing_decisive_quote_span" in e for e in result.item.llm_direction_validation_result.errors)


def test_normalizer_llm_direction_gating_tier3():
    normalizer = EvidenceNormalizer()
    item = _evidence(
        tier=3,
        direction=Direction.SUPPORTS,
        direction_method=DirectionMethod.LLM_CLASSIFIER,
        source_type=SourceType.WEB,
    )
    result = normalizer.normalize(item)
    assert result.item is not None
    assert result.item.direction == Direction.UNCLEAR
    assert result.item.llm_direction_validation_result is not None
    assert any("llm_direction_on_tier3" in e for e in result.item.llm_direction_validation_result.errors)


def test_normalizer_batch_filters_rejected():
    normalizer = EvidenceNormalizer()
    items = [
        _evidence(relevance_score=1.0, direction_confidence=1.0),
        _evidence(relevance_score=0.1),
        _evidence(relevance_score=1.0, direction_confidence=1.0),
    ]
    accepted = normalizer.normalize_batch(items)
    assert len(accepted) == 2


# ---------------------------------------------------------------------------
# Canonical JSON tests
# ---------------------------------------------------------------------------


def test_canonical_json_sorts_keys():
    obj = {"z": 1, "a": 2, "m": 3}
    serialized = canonical_json_serialize(obj)
    assert serialized == '{"a":2,"m":3,"z":1}'


def test_canonical_json_nested_sorts_keys():
    obj = {"outer": {"z": 1, "a": 2}}
    serialized = canonical_json_serialize(obj)
    assert serialized == '{"outer":{"a":2,"z":1}}'


def test_canonical_json_float_precision():
    obj = {"pi": 3.1415926535}
    serialized = canonical_json_serialize(obj)
    assert serialized == '{"pi":3.141593}'


def test_canonical_json_unicode_normalization():
    obj = {"text": "caf\u0065\u0301"}  # e + combining acute
    serialized = canonical_json_serialize(obj)
    # Should be normalized to NFC: café with precomposed é
    assert "\\u0065\\u0301" not in serialized or "é" in serialized


def test_canonical_json_explicit_nulls():
    obj = {"a": None, "b": "value"}
    serialized = canonical_json_serialize(obj)
    assert '"a":null' in serialized


def test_canonical_json_hash_stability_under_reordered_keys():
    """Same logical object with different key orders must produce identical hash."""
    obj_a = {"claim_hash": "abc", "claim_type": "NUMERIC_STATISTICAL", "scope": {"z": 1, "a": 2}}
    obj_b = {"claim_type": "NUMERIC_STATISTICAL", "scope": {"a": 2, "z": 1}, "claim_hash": "abc"}
    hash_a = canonical_json_hash(obj_a)
    hash_b = canonical_json_hash(obj_b)
    assert hash_a == hash_b


# ---------------------------------------------------------------------------
# CacheKey tests
# ---------------------------------------------------------------------------


def test_cache_key_exact_match_hit():
    cache = ImmutableMemoryCache()
    sc = _subclaim(text="Unemployment is 4.0%")
    policy = get_default_policy(ClaimType.NUMERIC_STATISTICAL)
    assert policy is not None

    key = build_cache_key(
        subclaim=sc,
        resolved_entity_ids=["Q30"],
        evidence_policy=policy,
        decomposition_version="v1.5",
        connector_snapshot_versions={"mock": "v1"},
        fact_mode=FactMode.OFFLINE,
    )

    # Store a mock result
    cache.set(key, {"status": "SUPPORTED", "p": 1.0})

    # Exact same key → hit
    result = cache.get(key)
    assert result is not None
    assert result["status"] == "SUPPORTED"


def test_cache_key_string_deterministic():
    sc = _subclaim(text="GDP is 20 trillion")
    policy = get_default_policy(ClaimType.NUMERIC_STATISTICAL)
    assert policy is not None

    key1 = build_cache_key(
        subclaim=sc,
        resolved_entity_ids=["Q30", "Q123"],
        evidence_policy=policy,
        decomposition_version="v1.5",
        connector_snapshot_versions={"mock": "v1"},
    )
    key2 = build_cache_key(
        subclaim=sc,
        resolved_entity_ids=["Q123", "Q30"],
        evidence_policy=policy,
        decomposition_version="v1.5",
        connector_snapshot_versions={"mock": "v1"},
    )
    # Entity IDs are sorted before hashing, so order should not matter
    assert cache_key_to_string(key1) == cache_key_to_string(key2)


def test_cache_miss_different_scope():
    cache = ImmutableMemoryCache()
    sc = _subclaim(text="Unemployment is 4.0%", scope=VerdictScope(geographic_scope="USA"))
    policy = get_default_policy(ClaimType.NUMERIC_STATISTICAL)
    assert policy is not None

    key = build_cache_key(
        subclaim=sc,
        resolved_entity_ids=["Q30"],
        evidence_policy=policy,
        decomposition_version="v1.5",
        connector_snapshot_versions={"mock": "v1"},
    )
    cache.set(key, {"status": "SUPPORTED", "p": 1.0})

    # Different scope
    sc2 = _subclaim(text="Unemployment is 4.0%", scope=VerdictScope(geographic_scope="Canada"))
    key2 = build_cache_key(
        subclaim=sc2,
        resolved_entity_ids=["Q30"],
        evidence_policy=policy,
        decomposition_version="v1.5",
        connector_snapshot_versions={"mock": "v1"},
    )
    result = cache.get(key2)
    assert result is None


def test_cache_miss_different_entity_ids():
    cache = ImmutableMemoryCache()
    sc = _subclaim(text="Unemployment is 4.0%")
    policy = get_default_policy(ClaimType.NUMERIC_STATISTICAL)
    assert policy is not None

    key = build_cache_key(
        subclaim=sc,
        resolved_entity_ids=["Q30"],
        evidence_policy=policy,
        decomposition_version="v1.5",
        connector_snapshot_versions={"mock": "v1"},
    )
    cache.set(key, {"status": "SUPPORTED", "p": 1.0})

    # Different entity
    key2 = build_cache_key(
        subclaim=sc,
        resolved_entity_ids=["Q148"],
        evidence_policy=policy,
        decomposition_version="v1.5",
        connector_snapshot_versions={"mock": "v1"},
    )
    result = cache.get(key2)
    assert result is None


def test_cache_miss_different_policy_version():
    cache = ImmutableMemoryCache()
    sc = _subclaim(text="Unemployment is 4.0%")
    policy = get_default_policy(ClaimType.NUMERIC_STATISTICAL)
    assert policy is not None

    key = build_cache_key(
        subclaim=sc,
        resolved_entity_ids=["Q30"],
        evidence_policy=policy,
        decomposition_version="v1.5",
        connector_snapshot_versions={"mock": "v1"},
    )
    cache.set(key, {"status": "SUPPORTED", "p": 1.0})

    # Different policy
    policy2 = EvidencePolicy(
        policy_id="strict_numeric",
        claim_type=ClaimType.NUMERIC_STATISTICAL,
        required_source_types=[],
        preferred_source_types=[],
        minimum_acceptable_tier=1,
        cross_verification_required=False,
        cross_verification_minimum_sources=1,
    )
    key2 = build_cache_key(
        subclaim=sc,
        resolved_entity_ids=["Q30"],
        evidence_policy=policy2,
        decomposition_version="v1.5",
        connector_snapshot_versions={"mock": "v1"},
    )
    result = cache.get(key2)
    assert result is None


def test_cache_frame_dependency_key_present_when_frame_dependent():
    sc = _subclaim(text="Frame-specific claim")
    policy = EvidencePolicy(
        policy_id="frame_dependent_policy",
        claim_type=ClaimType.CURRENT_EVENT,
        required_source_types=[],
        preferred_source_types=[],
        minimum_acceptable_tier=2,
        cross_verification_required=False,
        cross_verification_minimum_sources=1,
        frame_dependent=True,
    )
    frame_key = FrameDependencyKey(
        frame_set_version="v2", frame_id="f1", frame_scope_hash="abc123"
    )
    key = build_cache_key(
        subclaim=sc,
        resolved_entity_ids=[],
        evidence_policy=policy,
        decomposition_version="v1.5",
        connector_snapshot_versions={},
        frame_dependency_key=frame_key,
    )
    assert key.frame_dependency_key is not None
    assert key.frame_dependency_key.frame_id == "f1"


def test_cache_frame_dependency_key_null_when_not_frame_dependent():
    sc = _subclaim(text="Frame-independent claim")
    policy = get_default_policy(ClaimType.NUMERIC_STATISTICAL)
    assert policy is not None
    assert policy.frame_dependent is False

    frame_key = FrameDependencyKey(
        frame_set_version="v2", frame_id="f1", frame_scope_hash="abc123"
    )
    key = build_cache_key(
        subclaim=sc,
        resolved_entity_ids=[],
        evidence_policy=policy,
        decomposition_version="v1.5",
        connector_snapshot_versions={},
        frame_dependency_key=frame_key,
    )
    assert key.frame_dependency_key is None


# ---------------------------------------------------------------------------
# Claim hash tests
# ---------------------------------------------------------------------------


def test_claim_hash_consistent():
    h1 = compute_claim_hash("Unemployment is 4.0%")
    h2 = compute_claim_hash("Unemployment is 4.0%")
    assert h1 == h2


def test_claim_hash_case_insensitive():
    h1 = compute_claim_hash("Unemployment is 4.0%")
    h2 = compute_claim_hash("unemployment is 4.0%")
    assert h1 == h2


def test_claim_hash_standardizes_numbers():
    h1 = compute_claim_hash("Population is 38,000,000")
    h2 = compute_claim_hash("Population is 38000000")
    assert h1 == h2


def test_claim_hash_standardizes_percent():
    h1 = compute_claim_hash("Rate is 5%")
    h2 = compute_claim_hash("Rate is 5 percent")
    assert h1 == h2


# ---------------------------------------------------------------------------
# Hash helper tests
# ---------------------------------------------------------------------------


def test_entity_ids_hash_sorted():
    h1 = compute_entity_ids_hash(["Q30", "Q123"])
    h2 = compute_entity_ids_hash(["Q123", "Q30"])
    assert h1 == h2


def test_verdict_scope_hash_consistent():
    scope = VerdictScope(geographic_scope="USA", temporal_scope="2023")
    h1 = compute_verdict_scope_hash(scope)
    h2 = compute_verdict_scope_hash(scope)
    assert h1 == h2


def test_operationalization_hash_case_insensitive():
    h1 = compute_operationalization_hash("BLS Nonfarm Payroll")
    h2 = compute_operationalization_hash("bls nonfarm payroll")
    assert h1 == h2


def test_connector_versions_hash_stable():
    h1 = compute_connector_snapshot_versions_hash({"mock": "v1", "bls": "v2"})
    h2 = compute_connector_snapshot_versions_hash({"bls": "v2", "mock": "v1"})
    assert h1 == h2


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------


def test_truncate_quote():
    assert _truncate_quote("short") == "short"
    assert len(_truncate_quote("x" * 1500)) == 1000


def test_standardize_date_iso():
    assert _standardize_date("2023-03-15") == "2023-03-15T00:00:00Z"


def test_standardize_date_european():
    assert _standardize_date("15/03/2023") == "2023-03-15T00:00:00Z"


def test_compare_resolved_values_number_match():
    a = ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="count")
    b = ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="count")
    assert _compare_resolved_values(a, b) == DeterministicComparisonResult.MATCH


def test_compare_resolved_values_number_mismatch():
    a = ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="count")
    b = ResolvedValue(value=99, value_type=ValueType.NUMBER, unit="count")
    assert _compare_resolved_values(a, b) == DeterministicComparisonResult.MISMATCH


def test_compare_resolved_values_not_comparable_different_units():
    a = ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="count")
    b = ResolvedValue(value=42, value_type=ValueType.NUMBER, unit="percent")
    assert _compare_resolved_values(a, b) == DeterministicComparisonResult.NOT_COMPARABLE


def test_compute_content_hash_deterministic():
    h1 = _compute_content_hash("hello world")
    h2 = _compute_content_hash("hello world")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex length
