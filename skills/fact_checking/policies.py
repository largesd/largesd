"""
EvidencePolicy registry for the LSD Fact-Checking System v1.5.

Registers default policies per claim type and provides lookup helpers.
Per 01_DATA_MODELS.md and 02_SYNTHESIS_ENGINE.md.
"""

from .v15_models import ClaimType, EvidencePolicy, SourceType

# ---------------------------------------------------------------------------
# Default policies (01_DATA_MODELS.md §7)
# ---------------------------------------------------------------------------

_DEFAULT_POLICIES: list[EvidencePolicy] = [
    EvidencePolicy(
        policy_id="default_numeric_statistical",
        claim_type=ClaimType.NUMERIC_STATISTICAL,
        required_source_types=[SourceType.OFFICIAL_STAT, SourceType.GOV_DB],
        preferred_source_types=[SourceType.SCIENTIFIC_DB],
        minimum_acceptable_tier=2,
        cross_verification_required=False,
        cross_verification_minimum_sources=1,
    ),
    EvidencePolicy(
        policy_id="default_legal_regulatory",
        claim_type=ClaimType.LEGAL_REGULATORY,
        required_source_types=[SourceType.LEGAL_DB, SourceType.GOV_DB],
        preferred_source_types=[SourceType.OFFICIAL_STAT],
        minimum_acceptable_tier=1,
        cross_verification_required=False,
        cross_verification_minimum_sources=1,
    ),
    EvidencePolicy(
        policy_id="default_scientific",
        claim_type=ClaimType.SCIENTIFIC,
        required_source_types=[SourceType.SCIENTIFIC_DB],
        preferred_source_types=[SourceType.OFFICIAL_STAT],
        minimum_acceptable_tier=2,
        cross_verification_required=True,
        cross_verification_minimum_sources=2,
    ),
    EvidencePolicy(
        policy_id="default_geographic_demographic",
        claim_type=ClaimType.GEOGRAPHIC_DEMOGRAPHIC,
        required_source_types=[SourceType.OFFICIAL_STAT, SourceType.GOV_DB],
        preferred_source_types=[SourceType.WIKIDATA],
        minimum_acceptable_tier=2,
        cross_verification_required=False,
        cross_verification_minimum_sources=1,
    ),
    EvidencePolicy(
        policy_id="default_current_event",
        claim_type=ClaimType.CURRENT_EVENT,
        required_source_types=[SourceType.NEWS, SourceType.OFFICIAL_STAT],
        preferred_source_types=[SourceType.GOV_DB],
        minimum_acceptable_tier=2,
        cross_verification_required=True,
        cross_verification_minimum_sources=2,
    ),
    EvidencePolicy(
        policy_id="default_causal",
        claim_type=ClaimType.CAUSAL,
        required_source_types=[SourceType.SCIENTIFIC_DB],
        preferred_source_types=[SourceType.OFFICIAL_STAT],
        minimum_acceptable_tier=2,
        cross_verification_required=True,
        cross_verification_minimum_sources=2,
    ),
    EvidencePolicy(
        policy_id="default_empirical_atomic",
        claim_type=ClaimType.EMPIRICAL_ATOMIC,
        required_source_types=[],
        preferred_source_types=[SourceType.WIKIDATA, SourceType.OFFICIAL_STAT],
        minimum_acceptable_tier=2,
        cross_verification_required=False,
        cross_verification_minimum_sources=1,
    ),
]

_POLICY_MAP: dict[ClaimType, EvidencePolicy] = {p.claim_type: p for p in _DEFAULT_POLICIES}


def get_default_policy(claim_type: ClaimType) -> EvidencePolicy | None:
    """Return the default EvidencePolicy for a claim type, or None if not defined."""
    return _POLICY_MAP.get(claim_type)


def register_policy(policy: EvidencePolicy) -> None:
    """Register or override a policy in the global registry."""
    _POLICY_MAP[policy.claim_type] = policy


def list_registered_policies() -> list[EvidencePolicy]:
    """Return all registered policies."""
    return list(_POLICY_MAP.values())
