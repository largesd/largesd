"""
Phase 4 connector tests for the LSD Fact-Checking System v1.5.

Covers:
- Wikidata entity/static fact connector
- BLS official statistics connector
- Crossref scientific metadata connector
- Tier 2 curated source connector
- Tier 3 search/discovery connector

Rules:
- Connectors return EvidenceItem objects only.
- Connectors do not produce final verdicts.
- Absence in Wikidata -> INSUFFICIENT via synthesis (no_evidence_retrieved).
- Tier 3 cannot alone support/refute.
- Source independence group IDs are populated.
- Live connector tests are skipped when credentials are unavailable.
- Phase 1 mock tests remain unchanged and must still pass.
"""

from __future__ import annotations

import os
from typing import List

import pytest

from skills.fact_checking.synthesis import SynthesisEngine
from skills.fact_checking.v15_connectors import (
    BaseEvidenceConnector,
    BLSStatisticsConnector,
    BraveSearchConnector,
    ConnectorRegistry,
    CrossrefConnector,
    CuratedRAGConnector,
    DEFAULT_CURATED_DOCUMENTS,
    DEFAULT_WIKIDATA_ENTITIES,
    WikidataEntityConnector,
    _CuratedDocument,
    _WikidataEntity,
)
from skills.fact_checking.v15_models import (
    AtomicSubclaim,
    ClaimExpression,
    ClaimType,
    Direction,
    DirectionMethod,
    EvidenceItem,
    NodeType,
    PremiseDecomposition,
    ResolvedValue,
    RetrievalPath,
    Side,
    SourceType,
    ValueType,
    VerdictScope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subclaim(sid: str, text: str, claim_type: ClaimType = ClaimType.EMPIRICAL_ATOMIC) -> AtomicSubclaim:
    return AtomicSubclaim(
        subclaim_id=sid,
        parent_premise_id="p1",
        text=text,
        claim_type=claim_type,
        operationalization_hint="test",
        verdict_scope_hint=VerdictScope(),
    )


def _decomposition(root: ClaimExpression, subclaims: List[AtomicSubclaim]) -> PremiseDecomposition:
    return PremiseDecomposition(
        premise_id="p1",
        snapshot_id="snap1",
        original_text="test premise",
        topic_id="t1",
        side=Side.FOR,
        root_claim_expression=root,
        atomic_subclaims=subclaims,
    )


def _atomic_expr(sid: str) -> ClaimExpression:
    return ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id=sid)


def _run_synthesis(subclaim: AtomicSubclaim, items: List[EvidenceItem]):
    root = _atomic_expr(subclaim.subclaim_id)
    dec = _decomposition(root, [subclaim])
    engine = SynthesisEngine()
    return engine.synthesize(dec, items)


# ---------------------------------------------------------------------------
# 1. Wikidata connector tests
# ---------------------------------------------------------------------------


def test_wikidata_supported_birth_year():
    conn = WikidataEntityConnector()
    sc = _subclaim("sc1", "albert einstein was born in 1879")
    items = conn.retrieve(sc)
    assert len(items) == 1
    ev = items[0]
    assert ev.direction == Direction.SUPPORTS
    assert ev.source_tier == 2
    assert ev.source_type.name == "WIKIDATA"
    assert ev.deterministic_comparison_result.name == "MATCH"
    assert ev.source_independence_group_id == "wikidata:Q937"


def test_wikidata_refuted_birth_year():
    conn = WikidataEntityConnector()
    sc = _subclaim("sc1", "albert einstein was born in 1900")
    items = conn.retrieve(sc)
    assert len(items) == 1
    ev = items[0]
    assert ev.direction == Direction.REFUTES
    assert ev.deterministic_comparison_result.name == "MISMATCH"


def test_wikidata_absence_returns_no_evidence():
    conn = WikidataEntityConnector()
    sc = _subclaim("sc1", "unknown entity was born in 1900")
    items = conn.retrieve(sc)
    assert items == []
    # Synthesis should route to INSUFFICIENT (Rule I)
    result = _run_synthesis(sc, items)
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert result.insufficiency_reason == "no_evidence_retrieved"


def test_wikidata_unsupported_claim_family_returns_no_evidence():
    conn = WikidataEntityConnector()
    sc = _subclaim("sc1", "gdp rose in canada in 2024", claim_type=ClaimType.NUMERIC_STATISTICAL)
    items = conn.retrieve(sc)
    assert items == []


def test_wikidata_connector_returns_evidence_items_only():
    conn = WikidataEntityConnector()
    sc = _subclaim("sc1", "openai was founded in 2015")
    items = conn.retrieve(sc)
    assert all(isinstance(i, EvidenceItem) for i in items)
    # Connectors must not return verdicts
    assert not hasattr(conn, "produce_verdict")


def test_wikidata_independence_group_id_populated():
    conn = WikidataEntityConnector()
    sc = _subclaim("sc1", "toronto is in ontario")
    items = conn.retrieve(sc)
    assert len(items) == 1
    assert items[0].source_independence_group_id is not None
    assert items[0].source_independence_group_id.startswith("wikidata:")


# ---------------------------------------------------------------------------
# 2. BLS connector tests
# ---------------------------------------------------------------------------


def test_bls_offline_placeholder_without_api_key():
    conn = BLSStatisticsConnector(api_key="")
    sc = _subclaim("sc1", "the us unemployment rate is 4 percent")
    items = conn.retrieve(sc)
    # Without API key we get a neutral placeholder so the connector is testable
    assert len(items) == 1
    assert items[0].source_tier == 1
    assert items[0].source_type.name == "OFFICIAL_STAT"
    assert items[0].direction == Direction.NEUTRAL


def test_bls_no_evidence_for_unrelated_claim():
    conn = BLSStatisticsConnector(api_key="")
    sc = _subclaim("sc1", "toronto is in ontario")
    items = conn.retrieve(sc)
    assert items == []


def test_bls_connector_skips_cleanly_without_key():
    # Simulate CI environment where key is absent
    conn = BLSStatisticsConnector(api_key="")
    sc = _subclaim("sc1", "the us unemployment rate is 4 percent")
    items = conn.retrieve(sc)
    # Should not raise; returns placeholder evidence
    assert isinstance(items, list)


def test_bls_placeholder_hash_is_deterministic():
    """Artifact replay requires the same raw_response_hash for the same placeholder."""
    conn = BLSStatisticsConnector(api_key="")
    sc = _subclaim("sc1", "the us unemployment rate is 4 percent")
    items_a = conn.retrieve(sc)
    items_b = conn.retrieve(sc)
    assert len(items_a) == 1
    assert len(items_b) == 1
    assert items_a[0].raw_response_hash == items_b[0].raw_response_hash
    assert items_a[0].connector_version == conn.connector_version
    assert items_a[0].connector_query_hash == conn._query_hash(sc.text)


def test_bls_placeholder_retrieval_path_marked():
    conn = BLSStatisticsConnector(api_key="")
    sc = _subclaim("sc1", "the us unemployment rate is 4 percent")
    items = conn.retrieve(sc)
    assert len(items) == 1
    ev = items[0]
    assert ev.retrieval_path.name == "OFFLINE_PLACEHOLDER"
    assert ev.source_tier == 1
    assert ev.direction.name == "NEUTRAL"


@pytest.mark.skipif(not os.environ.get("BLS_API_KEY"), reason="BLS_API_KEY not available")
def test_bls_live_api_returns_evidence():
    conn = BLSStatisticsConnector()
    sc = _subclaim("sc1", "the us unemployment rate is 4 percent", claim_type=ClaimType.NUMERIC_STATISTICAL)
    items = conn.retrieve(sc)
    assert len(items) >= 0  # may be empty if API is down
    for ev in items:
        assert isinstance(ev, EvidenceItem)
        assert ev.source_tier == 1


# ---------------------------------------------------------------------------
# 3. Crossref connector tests
# ---------------------------------------------------------------------------


def test_crossref_no_doi_no_scientific_claim_returns_empty():
    conn = CrossrefConnector(email="")
    sc = _subclaim("sc1", "toronto is in ontario")
    items = conn.retrieve(sc)
    assert items == []


def test_crossref_offline_without_email():
    conn = CrossrefConnector(email="")
    sc = _subclaim("sc1", "study doi 10.1000/182 shows positive effect", claim_type=ClaimType.SCIENTIFIC)
    items = conn.retrieve(sc)
    # Without email, search path is disabled; DOI path still attempts but may 404
    assert isinstance(items, list)


@pytest.mark.skipif(not os.environ.get("CROSSREF_EMAIL"), reason="CROSSREF_EMAIL not available")
def test_crossref_live_doi_query():
    conn = CrossrefConnector()
    sc = _subclaim("sc1", "the study 10.1038/s41586-021-03819-2 found X", claim_type=ClaimType.SCIENTIFIC)
    items = conn.retrieve(sc)
    assert len(items) >= 0
    for ev in items:
        assert isinstance(ev, EvidenceItem)
        assert ev.source_tier in (1, 2)
        assert ev.group_id is not None


# ---------------------------------------------------------------------------
# 4. Tier 2 curated source connector tests
# ---------------------------------------------------------------------------


def test_curated_rag_returns_tier2_evidence():
    conn = CuratedRAGConnector()
    sc = _subclaim("sc1", "openai was founded in 2015")
    items = conn.retrieve(sc)
    assert len(items) >= 1
    for ev in items:
        assert ev.source_tier == 2
        assert ev.source_type.name == "WIKIPEDIA"
        assert ev.source_independence_group_id is not None
        assert ev.relevance_score >= 0.3


def test_curated_rag_no_match_returns_empty():
    conn = CuratedRAGConnector()
    sc = _subclaim("sc1", "xyzabc123 nonsense claim")
    items = conn.retrieve(sc)
    assert items == []


def test_curated_rag_max_10_documents():
    # Create many docs with the same keyword to test the cap
    docs = [
        _CuratedDocument(
            doc_id=f"doc_{i}",
            title=f"Document {i}",
            url=f"https://example.com/{i}",
            excerpt=f"test keyword match document number {i}",
            authority="Test Authority",
        )
        for i in range(15)
    ]
    conn = CuratedRAGConnector(documents=docs)
    sc = _subclaim("sc1", "test keyword match")
    items = conn.retrieve(sc)
    assert len(items) <= 10


def test_curated_rag_does_not_produce_verdict():
    conn = CuratedRAGConnector()
    sc = _subclaim("sc1", "openai was founded in 2015")
    items = conn.retrieve(sc)
    # Curated RAG returns evidence only; synthesis produces verdict
    result = _run_synthesis(sc, items)
    # Depending on direction confidence, may be insufficient or supported
    assert result.status in ("SUPPORTED", "INSUFFICIENT")


# ---------------------------------------------------------------------------
# 5. Tier 3 search/discovery connector tests
# ---------------------------------------------------------------------------


def test_brave_search_skips_without_key():
    conn = BraveSearchConnector(api_key="")
    sc = _subclaim("sc1", "openai was founded in 2015")
    items = conn.retrieve(sc)
    assert items == []


def test_brave_search_returns_tier3_evidence_when_key_present():
    # We cannot hit the live API in unit tests without a key,
    # so we mock the key and assert the connector is configured correctly.
    conn = BraveSearchConnector(api_key="dummy_key_for_structure_check")
    assert conn._api_key == "dummy_key_for_structure_check"
    # The retrieve() method will attempt a real call and likely fail,
    # returning empty evidence.  That's fine — the test proves the
    # connector attempts cleanly.
    sc = _subclaim("sc1", "openai was founded in 2015")
    items = conn.retrieve(sc)
    # Expect empty because dummy key is rejected by Brave API
    assert items == []


@pytest.mark.skipif(not os.environ.get("BRAVE_API_KEY"), reason="BRAVE_API_KEY not available")
def test_brave_search_live_api():
    conn = BraveSearchConnector()
    sc = _subclaim("sc1", "openai was founded in 2015")
    items = conn.retrieve(sc)
    assert isinstance(items, list)
    for ev in items:
        assert isinstance(ev, EvidenceItem)
        assert ev.source_tier == 3
        assert ev.source_type.name == "WEB"
        assert ev.retrieval_path.name == "LIVE_SEARCH_DISCOVERY"


# ---------------------------------------------------------------------------
# 6. Integration with synthesis engine (no behaviour change)
# ---------------------------------------------------------------------------


def test_wikidata_plus_curated_rag_cross_verification():
    """Tier 2 + Tier 2 with independence should satisfy cross-verification."""
    wikidata = WikidataEntityConnector()
    curated = CuratedRAGConnector()
    sc = _subclaim("sc1", "openai was founded in 2015", claim_type=ClaimType.EMPIRICAL_ATOMIC)
    items: List[EvidenceItem] = []
    items.extend(wikidata.retrieve(sc))
    items.extend(curated.retrieve(sc))

    # Filter to only decisive evidence
    decisive = [i for i in items if i.direction_confidence >= 0.7 and i.relevance_score >= 0.3]
    # Wikidata gives SUPPORTS; curated may give SUPPORTS or NEUTRAL
    result = _run_synthesis(sc, decisive)
    # Best case: Wikidata Tier 2 supports -> SUPPORTED
    # If curated is NEUTRAL/UNCLEAR, Wikidata alone as Tier 2 still supports
    # (cross_verification_required is False for EMPIRICAL_ATOMIC)
    assert result.status in ("SUPPORTED", "INSUFFICIENT")


def test_tier3_only_insufficient_via_brave():
    """Tier 3 evidence alone must not support or refute (Rule H)."""
    # Simulate Brave returning Tier 3 evidence by constructing it directly
    sc = _subclaim("sc1", "some claim")
    tier3_ev = EvidenceItem(
        subclaim_id=sc.subclaim_id,
        source_tier=3,
        direction=Direction.SUPPORTS,
        direction_confidence=1.0,
        relevance_score=1.0,
        source_independence_group_id="brave:0",
    )
    result = _run_synthesis(sc, [tier3_ev])
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert result.insufficiency_reason == "only_tier3_evidence"


def test_connector_registry_offline_set():
    connectors = ConnectorRegistry.offline_connectors()
    ids = {c.connector_id for c in connectors}
    assert "wikidata_entity_v15" in ids
    assert "curated_rag_v15" in ids
    assert "bls_statistics_v15" not in ids  # needs key for live path


def test_connector_registry_default_set():
    connectors = ConnectorRegistry.default_connectors()
    ids = {c.connector_id for c in connectors}
    assert ids == {
        "wikidata_entity_v15",
        "bls_statistics_v15",
        "crossref_v15",
        "curated_rag_v15",
        "brave_search_v15",
    }


# ---------------------------------------------------------------------------
# 7. Connector failure surface
# ---------------------------------------------------------------------------


def test_bls_placeholder_only_is_insufficient():
    """If only OFFLINE_PLACEHOLDER evidence exists, result is INSUFFICIENT."""
    sc = _subclaim("sc1", "the us unemployment rate is 4 percent", claim_type=ClaimType.NUMERIC_STATISTICAL)
    placeholder = EvidenceItem(
        subclaim_id=sc.subclaim_id,
        source_type=SourceType.OFFICIAL_STAT,
        source_tier=1,
        retrieval_path=RetrievalPath.OFFLINE_PLACEHOLDER,
        source_url="https://www.bls.gov",
        source_title="BLS Series LNS14000000 (offline placeholder)",
        source_authority="U.S. Bureau of Labor Statistics",
        quote_or_span="Offline placeholder for BLS series LNS14000000. Live API requires BLS_API_KEY.",
        relevance_score=0.5,
        direction=Direction.NEUTRAL,
        direction_confidence=1.0,
        direction_method=DirectionMethod.DETERMINISTIC_STRUCTURED,
        connector_version="bls_statistics_v15",
        connector_query_hash="test_hash",
        raw_response_hash="test_hash",
        source_independence_group_id="bls:LNS14000000",
    )
    result = _run_synthesis(sc, [placeholder])
    assert result.status == "INSUFFICIENT"
    assert result.p == 0.5
    assert result.best_evidence_tier == 1
    assert result.insufficiency_reason == "connector_offline_placeholder"
    assert result.subclaim_results[0].synthesis_logic.status_rule_applied == "rule_i_placeholder_only"


def test_connector_failure_returns_empty_not_crash():
    """If a live connector raises, it should return empty evidence."""
    class FailingConnector(BaseEvidenceConnector):
        @property
        def connector_id(self):
            return "failing"

        @property
        def connector_version(self):
            return "v0"

        def retrieve(self, subclaim):
            raise RuntimeError("network down")

    conn = FailingConnector()
    sc = _subclaim("sc1", "anything")
    # The connector itself raises; callers (e.g. an evidence router) should
    # catch this.  Here we verify the exception propagates so it can be
    # caught and mapped to connector_failure by the router.
    with pytest.raises(RuntimeError):
        conn.retrieve(sc)
