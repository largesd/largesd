"""
Deterministic connector routing for fact checking v1.

The planner is intentionally conservative: it only routes supported atomic
claim families to an allowed Tier-1 path and otherwise records why the claim
must remain INSUFFICIENT.
"""

from typing import Iterable, List

from .models import EvidenceTier, PlannerDecision, Subclaim


class ConnectorPlanner:
    """Choose a narrow, inspectable connector path for each subclaim."""

    @staticmethod
    def plan_claim(subclaims: List[Subclaim], connectors: Iterable[object], mode: str) -> List[PlannerDecision]:
        decisions: List[PlannerDecision] = []
        for subclaim in subclaims:
            decisions.append(ConnectorPlanner.plan_subclaim(subclaim, connectors, mode))
        return decisions

    @staticmethod
    def plan_subclaim(subclaim: Subclaim, connectors: Iterable[object], mode: str) -> PlannerDecision:
        if subclaim.claim_family == "unsupported":
            return PlannerDecision(
                supported=False,
                claim_family=subclaim.claim_family,
                connector_path=[],
                reason_code="unsupported_claim_family",
                reason="The claim family is outside the frozen v1 support contract.",
            )

        tier1_connectors = [
            connector.source_id
            for connector in connectors
            if getattr(connector, "tier", None) == EvidenceTier.TIER_1
        ]
        tier2_connectors = [
            connector.source_id
            for connector in connectors
            if getattr(connector, "tier", None) == EvidenceTier.TIER_2
        ]

        if not tier1_connectors:
            return PlannerDecision(
                supported=False,
                claim_family=subclaim.claim_family,
                connector_path=[],
                reason_code="no_tier1_source",
                reason="No Tier-1 connector is available for this supported claim family.",
            )

        connector_path = tier1_connectors[:1]
        web_corroboration_allowed = mode == "ONLINE_ALLOWLIST" or bool(tier2_connectors)
        if web_corroboration_allowed and tier2_connectors:
            connector_path.extend(tier2_connectors[:1])

        return PlannerDecision(
            supported=True,
            claim_family=subclaim.claim_family,
            connector_path=connector_path,
            reason_code="supported_claim_family",
            reason="The claim matches the frozen v1 contract and has a Tier-1 retrieval path.",
            web_corroboration_allowed=web_corroboration_allowed,
        )
