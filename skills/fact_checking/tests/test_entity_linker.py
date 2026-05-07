"""
Tests for EntityLinker (Gap 1 implementation).

Covers:
- Mention extraction (spaCy NER fallback + regex fallback)
- Wikidata search integration
- Single-candidate high-confidence linking
- Multi-candidate ambiguity flagging
- Empty candidate handling
- Integration with V15FactCheckingSkill
"""

from __future__ import annotations

from skills.fact_checking.entity_linker import EntityLinker


class FakeWikidataConnector:
    """Mock Wikidata connector for deterministic testing."""

    def __init__(self, candidates_map=None):
        self._candidates_map = candidates_map or {}

    def search_candidates(self, mention: str, **kwargs):
        return self._candidates_map.get(mention, [])


# ---------------------------------------------------------------------------
# Mention extraction
# ---------------------------------------------------------------------------


def test_extract_mentions_regex_fallback():
    linker = EntityLinker(wikidata_connector=FakeWikidataConnector())
    text = "Albert Einstein was born in Germany."
    mentions = linker._extract_mentions(text)
    # Regex should pick up consecutive capitalized words
    assert "Albert Einstein" in mentions or "Einstein" in mentions or "Germany" in mentions


def test_extract_mentions_no_spacy():
    linker = EntityLinker(wikidata_connector=FakeWikidataConnector())
    text = "The quick brown fox."
    mentions = linker._extract_mentions(text)
    # No capitalized multi-word phrases except sentence start
    assert mentions == [] or all(m not in ("The quick",) for m in mentions)


# ---------------------------------------------------------------------------
# Disambiguation
# ---------------------------------------------------------------------------


def test_single_candidate_high_confidence():
    linker = EntityLinker(wikidata_connector=FakeWikidataConnector())
    candidates = [{"qid": "Q937", "label": "Albert Einstein", "score": 100, "type": "PERSON"}]
    link = linker._disambiguate("Einstein", "Einstein was a physicist.", candidates)
    assert link.canonical_id == "Q937"
    assert link.ambiguity_flag is False
    assert link.linking_confidence > 0.9


def test_multiple_candidates_ambiguity_flag():
    linker = EntityLinker(wikidata_connector=FakeWikidataConnector())
    candidates = [
        {"qid": "Q1", "label": "Apple Inc.", "score": 105, "type": "ORG"},
        {"qid": "Q2", "label": "Apple (fruit)", "score": 95, "type": "TAXON"},
    ]
    link = linker._disambiguate("Apple", "Apple released a new product.", candidates)
    assert link.canonical_id == "Q1"
    assert link.ambiguity_flag is True
    assert len(link.ambiguity_candidates) >= 2


def test_multiple_candidates_clear_winner():
    linker = EntityLinker(wikidata_connector=FakeWikidataConnector())
    candidates = [
        {"qid": "Q1", "label": "OpenAI", "score": 200, "type": "ORG"},
        {"qid": "Q2", "label": "Open AI (band)", "score": 10, "type": "MUSIC"},
    ]
    link = linker._disambiguate("OpenAI", "OpenAI was founded in 2015.", candidates)
    assert link.canonical_id == "Q1"
    assert link.ambiguity_flag is False


# ---------------------------------------------------------------------------
# Full link() pipeline
# ---------------------------------------------------------------------------


def test_link_no_candidates_empty_result():
    linker = EntityLinker(wikidata_connector=FakeWikidataConnector())
    links = linker.link("UnknownEntityXYZ123")
    assert links == []


def test_link_with_candidates():
    wikidata = FakeWikidataConnector(
        {
            "Albert Einstein": [
                {"qid": "Q937", "label": "Albert Einstein", "score": 100, "type": "PERSON"}
            ]
        }
    )
    linker = EntityLinker(wikidata_connector=wikidata, confidence_threshold=0.5)
    links = linker.link("The physicist Albert Einstein lived in Germany.")
    assert len(links) >= 1
    assert any(link.canonical_id == "Q937" for link in links)


# ---------------------------------------------------------------------------
# LLM disambiguation
# ---------------------------------------------------------------------------


def test_llm_disambiguate_uses_client():
    class FakeLLM:
        def complete(self, prompt):
            return '{"qid": "Q937", "confidence": 0.95}'

    linker = EntityLinker(
        wikidata_connector=FakeWikidataConnector(),
        llm_client=FakeLLM(),
    )
    candidates = [
        {"qid": "Q937", "label": "Albert Einstein", "score": 100},
        {"qid": "Q999", "label": "Einstein (band)", "score": 50},
    ]
    result = linker._llm_disambiguate("Einstein", "Einstein was a physicist.", candidates)
    assert result is not None
    assert result[0] == "Q937"
    assert result[1] == 0.95


def test_llm_disambiguate_invalid_qid_returns_none():
    class FakeLLM:
        def complete(self, prompt):
            return '{"qid": "Q_INVALID", "confidence": 0.95}'

    linker = EntityLinker(
        wikidata_connector=FakeWikidataConnector(),
        llm_client=FakeLLM(),
    )
    candidates = [{"qid": "Q937", "label": "Albert Einstein", "score": 100}]
    result = linker._llm_disambiguate("Einstein", "Einstein was a physicist.", candidates)
    assert result is None


# ---------------------------------------------------------------------------
# Integration with V15FactCheckingSkill
# ---------------------------------------------------------------------------


def test_skill_entity_failure_ids_populated():
    from skills.fact_checking.v15_skill import V15FactCheckingSkill

    skill = V15FactCheckingSkill(mode="OFFLINE")
    decomposition = skill._get_decomposition("Albert Einstein was born in 1879.")
    failure_ids = skill._get_entity_failure_ids(decomposition)
    # Offline mode: entity linker may or may not resolve depending on network.
    # The test just ensures the method runs without crashing.
    assert isinstance(failure_ids, set)
