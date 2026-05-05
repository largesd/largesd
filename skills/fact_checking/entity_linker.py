"""
Entity / Concept Linking for v1.5.

Resolves entities in subclaim text to stable identifiers (Wikidata QIDs, DOIs, etc.).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class EntityLink:
    entity_id: str
    mention_span: str
    canonical_id: str
    canonical_type: str
    canonical_label: str
    linking_confidence: float
    ambiguity_flag: bool
    ambiguity_candidates: List[str]


class WikidataEntityConnector:
    """Lightweight Wikidata wbsearchentities client for entity linking."""

    def __init__(self, timeout_seconds: float = 10.0):
        self._timeout = timeout_seconds

    def search_candidates(self, mention: str, language: str = "en", limit: int = 5) -> List[Dict[str, Any]]:
        """Query Wikidata wbsearchentities for candidate QIDs."""
        import json
        import urllib.parse
        import urllib.request

        qs = urllib.parse.urlencode({
            "action": "wbsearchentities",
            "format": "json",
            "search": mention,
            "language": language,
            "limit": limit,
        })
        url = f"https://www.wikidata.org/w/api.php?{qs}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LSD-FactCheck/1.5 (entity-linker)"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []

        candidates = []
        for result in data.get("search", []):
            candidates.append({
                "qid": result.get("id", ""),
                "label": result.get("label", ""),
                "description": result.get("description", ""),
                "score": result.get("score", 0.0),
                "type": result.get("match", {}).get("type", "UNKNOWN"),
            })
        return candidates


class EntityLinker:
    """Production entity linker: NER → Wikidata search → disambiguation."""

    def __init__(
        self,
        wikidata_connector: Optional[WikidataEntityConnector] = None,
        llm_client: Optional[Any] = None,
        confidence_threshold: float = 0.7,
    ):
        self.wikidata = wikidata_connector or WikidataEntityConnector()
        self.llm_client = llm_client
        self.confidence_threshold = confidence_threshold
        # --- new caching fields ---
        self._nlp: Optional[Any] = None
        self._nlp_failed: bool = False

    def _get_spacy_nlp(self) -> Optional[Any]:
        """Return cached spaCy nlp object, or None if unavailable."""
        if self._nlp is not None:
            return self._nlp
        if self._nlp_failed:
            return None
        try:
            import spacy
            self._nlp = spacy.load("en_core_web_sm")
            return self._nlp
        except Exception:
            self._nlp_failed = True
            return None

    def link(self, subclaim_text: str) -> List[EntityLink]:
        """Extract mentions and link each to a canonical Wikidata entity."""
        mentions = self._extract_mentions(subclaim_text)
        links = []
        for mention in mentions:
            candidates = self.wikidata.search_candidates(mention)
            if not candidates:
                continue
            link = self._disambiguate(mention, subclaim_text, candidates)
            links.append(link)
        return links

    def _extract_mentions(self, text: str) -> List[str]:
        """
        Strategy 1 (preferred): spaCy NER (PERSON, ORG, GPE, PRODUCT, EVENT)
        Strategy 2 (fallback): Capitalized phrase regex
        Strategy 3 (minimal): None — we skip LLM extraction to avoid latency
        """
        # Try spaCy if available
        nlp = self._get_spacy_nlp()
        if nlp is not None:
            try:
                doc = nlp(text)
                ents = [ent.text for ent in doc.ents
                        if ent.label_ in ("PERSON", "ORG", "GPE", "PRODUCT",
                                          "EVENT", "WORK_OF_ART", "LAW")]
                if ents:
                    return ents
            except Exception:
                pass

        # Fallback: regex for capitalized phrases (2+ words)
        matches = re.findall(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+\b", text)
        # Also capture single capitalized words that aren't sentence starts
        words = text.split()
        single_word_ents = []
        for i, word in enumerate(words):
            clean = word.strip(".,;:!?()[]{}'\"")
            if clean and clean[0].isupper() and len(clean) > 1:
                # Skip if it's the first word of the sentence
                if i == 0 or words[i - 1].endswith((".", "!", "?")):
                    continue
                single_word_ents.append(clean)
        return list(dict.fromkeys(matches + single_word_ents))  # preserve order, dedup

    def _disambiguate(
        self, mention: str, context: str, candidates: List[Dict[str, Any]]
    ) -> EntityLink:
        """
        If only one candidate → high confidence direct link.
        If multiple candidates and llm_client available → LLM disambiguation.
        If multiple candidates and no LLM → pick highest wbsearchentities score,
            flag ambiguity if scores are close (< 0.2 apart).
        """
        entity_id = f"entity_{hashlib.sha256(mention.encode()).hexdigest()[:12]}"

        if len(candidates) == 1:
            c = candidates[0]
            return EntityLink(
                entity_id=entity_id,
                mention_span=mention,
                canonical_id=c["qid"],
                canonical_type=c.get("type", "UNKNOWN"),
                canonical_label=c["label"],
                linking_confidence=min(c.get("score", 0.9) / 100, 0.95),
                ambiguity_flag=False,
                ambiguity_candidates=[],
            )

        # Sort by score descending
        candidates = sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)
        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None

        # If LLM client available, try LLM disambiguation
        if self.llm_client and len(candidates) > 1:
            llm_result = self._llm_disambiguate(mention, context, candidates)
            if llm_result:
                qid, confidence = llm_result
                for c in candidates:
                    if c["qid"] == qid:
                        return EntityLink(
                            entity_id=entity_id,
                            mention_span=mention,
                            canonical_id=c["qid"],
                            canonical_type=c.get("type", "UNKNOWN"),
                            canonical_label=c["label"],
                            linking_confidence=confidence,
                            ambiguity_flag=False,
                            ambiguity_candidates=[cand["qid"] for cand in candidates[:3]],
                        )

        # If scores are close, flag ambiguity
        if second and (top.get("score", 0) - second.get("score", 0)) < 20:
            return EntityLink(
                entity_id=entity_id,
                mention_span=mention,
                canonical_id=top["qid"],
                canonical_type=top.get("type", "UNKNOWN"),
                canonical_label=top["label"],
                linking_confidence=0.55,
                ambiguity_flag=True,
                ambiguity_candidates=[c["qid"] for c in candidates[:3]],
            )

        # Clear winner
        return EntityLink(
            entity_id=entity_id,
            mention_span=mention,
            canonical_id=top["qid"],
            canonical_type=top.get("type", "UNKNOWN"),
            canonical_label=top["label"],
            linking_confidence=min(top.get("score", 85) / 100, 0.9),
            ambiguity_flag=False,
            ambiguity_candidates=[c["qid"] for c in candidates[:3]],
        )

    def _llm_disambiguate(
        self, mention: str, context: str, candidates: List[Dict[str, Any]]
    ) -> Optional[Tuple[str, float]]:
        """Use LLM to pick the best candidate QID."""
        import json

        prompt = f'''Given the claim: "{context}"
The mention "{mention}" could refer to:
{chr(10).join(f"{i+1}. QID={c['qid']}, Label={c['label']}, Description={c.get('description', 'N/A')}" for i, c in enumerate(candidates))}

Which candidate best matches the mention in this context?
Respond with ONLY the QID and a confidence score (0.0–1.0) in JSON:
{{"qid": "Q...", "confidence": 0.92}}'''

        try:
            response = self.llm_client.complete(prompt)
            parsed = json.loads(response)
            qid = parsed.get("qid", "")
            confidence = float(parsed.get("confidence", 0.0))
            # Validate QID is in candidates
            if any(c["qid"] == qid for c in candidates):
                return qid, confidence
        except Exception:
            pass
        return None
