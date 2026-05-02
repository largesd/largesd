"""
Wikidata SPARQL Connector — Tier 1 primary source (when real).

PROTOTYPE STATUS:
The current implementation is a deterministic Tier-3 simulation.
It does NOT perform real SPARQL queries.  It exists only to exercise
connector wiring and policy behavior in tests.

When promoted to production:
1. Implement real entity extraction (claim → QID) and property
   extraction (claim → PID).
2. Run SPARQL against query.wikidata.org.
3. Only emit CONFIRMS or CONTRADICTS when a structured triple match
   is unambiguous.
4. If extraction fails or the query returns no match, return SILENT.
5. Change ``tier`` to EvidenceTier.TIER_1.

Until then, this connector is Tier 3 and must never be treated as
authoritative in adjudication.
"""

import hashlib
from datetime import datetime
from typing import Optional
from .connectors import SourceConnector, SourceResult, SourceConfidence
from .models import EvidenceTier


class WikidataConnector(SourceConnector):
    """
    Deterministic simulation of a Wikidata connector.

    TODO: Replace with real SPARQL query builder before using in
    production adjudication.
    """

    def __init__(self, silence_rate: float = 0.20):
        self._silence_rate = silence_rate

    @property
    def source_id(self) -> str:
        return "wikidata_sim"

    @property
    def tier(self) -> EvidenceTier:
        # IMPORTANT: Prototype is Tier 3.  Real implementation upgrades to Tier 1.
        return EvidenceTier.TIER_3

    def query(self, normalized_claim: str, claim_hash: str) -> Optional[SourceResult]:
        hash_int = int(claim_hash[:8], 16)

        # Simulate silence rate
        if (hash_int % 100) < int(self._silence_rate * 100):
            return None

        # Deterministic fixture — parity decides confirm/contradict
        is_confirms = (hash_int % 2) == 0
        confidence = SourceConfidence.CONFIRMS if is_confirms else SourceConfidence.CONTRADICTS

        return SourceResult(
            source_id=self.source_id,
            source_url=f"https://www.wikidata.org/wiki/Special:EntityData/{claim_hash[:8]}.json",
            source_title="Wikidata Entity Data (SIMULATED)",
            confidence=confidence,
            excerpt=f"[SIMULATED] Wikidata property match for: {normalized_claim[:60]}...",
            content_hash=hashlib.sha256(normalized_claim.encode()).hexdigest()[:32],
            retrieved_at=datetime.now(),
            tier=self.tier,
        )
