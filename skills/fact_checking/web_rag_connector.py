"""
Web RAG Connector — Tier 2/3 conservative implementation.

Implements a 3-step workflow:
1. Search for candidate pages.
2. Fetch and extract text from each page independently.
3. Classify EACH source independently with the LLM.
4. Return per-source SourceResult objects (aggregated by the caller).

Design principles:
- No bundled LLM prompt over multiple pages directly decides p.
- Each source is cited, tiered, and classified separately.
- Aggregation happens in the evidence-policy layer, not here.
- Conservative: when in doubt, return SILENT.
"""

import hashlib
from datetime import datetime
from typing import Any, Protocol

from .connectors import SourceConfidence, SourceConnector, SourceResult
from .models import EvidenceTier


class SearchBackend(Protocol):
    """Protocol for search abstraction."""

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        """Return list of results, each with at least 'url' and optionally 'title'."""
        ...


class LLMClient(Protocol):
    """Minimal protocol for LLM generate interface."""

    class Response:
        content: str

    def generate(self, prompt: str, temperature: float, max_tokens: int) -> Response: ...


class WebRAGConnector(SourceConnector):
    """
    .. deprecated:: 1.5.0
        Use BraveSearchConnector (v15_connectors.py) instead.
        This connector implements the legacy v1 interface and will be removed
        in a future release.
    """

    """
    Conservative web-retrieval connector.

    Parameters
    ----------
    llm_client : LLMClient
        Object with ``generate(prompt, temperature, max_tokens) -> Response``.
    search_backend : SearchBackend
        Object with ``search(query, top_k) -> list[dict]``.
    source_id : str
        Identifier for this connector instance.
    tier : EvidenceTier
        Tier to assign to all returned evidence (default TIER_2).
    max_pages : int
        Maximum pages to fetch and classify.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        search_backend: SearchBackend,
        source_id: str = "web_rag",
        tier: EvidenceTier = EvidenceTier.TIER_2,
        max_pages: int = 3,
    ):
        import warnings

        warnings.warn(
            "WebRAGConnector is deprecated since v1.5.0. Use BraveSearchConnector instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.llm = llm_client
        self.search = search_backend
        self._source_id = source_id
        self._tier = tier
        self._max_pages = max_pages

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def tier(self) -> EvidenceTier:
        return self._tier

    def query(self, normalized_claim: str, claim_hash: str) -> SourceResult | None:
        # Step 1: Search
        results = self.search.search(normalized_claim, top_k=self._max_pages)
        if not results:
            return None

        # Step 2: Fetch each page independently
        documents: list[dict[str, str]] = []
        for r in results[: self._max_pages]:
            content = self._fetch_clean(r["url"])
            if content:
                documents.append(
                    {
                        "url": r["url"],
                        "title": r.get("title", "Unknown"),
                        "content": content[:3000],
                    }
                )

        if not documents:
            return None

        # Step 3: Per-source classification
        per_source_labels: list[SourceConfidence] = []
        for doc in documents:
            label = self._llm_classify_single_source(normalized_claim, doc)
            per_source_labels.append(label)

        # Step 4: Aggregate conservatively
        # If any source is AMBIGUOUS → overall AMBIGUOUS
        # If sources disagree → AMBIGUOUS
        # If all agree → that label
        # If all SILENT → None
        final_label = self._aggregate_labels(per_source_labels)
        if final_label is None or final_label == SourceConfidence.SILENT:
            return None

        # Return the top document as the canonical citation,
        # but the caller should note that the label was derived
        # from multiple independent pages.
        top_doc = documents[0]
        return SourceResult(
            source_id=self.source_id,
            source_url=top_doc["url"],
            source_title=top_doc["title"],
            confidence=final_label,
            excerpt=top_doc["content"][:300],
            content_hash=hashlib.sha256(top_doc["content"].encode()).hexdigest()[:32],
            retrieved_at=datetime.now(),
            tier=self.tier,
        )

    def _fetch_clean(self, url: str) -> str | None:
        try:
            import requests

            resp = requests.get(url, timeout=10, headers={"User-Agent": "FactBot/1.0"})
            if resp.status_code != 200:
                return None
            try:
                import trafilatura

                return trafilatura.extract(resp.text, include_comments=False)
            except ImportError:
                return resp.text[:5000]
        except Exception:
            return None

    def _llm_classify_single_source(self, claim: str, document: dict[str, str]) -> SourceConfidence:
        prompt = f"""You have read the source below. Assess whether it supports or contradicts the claim.

CLAIM: {claim}

SOURCE: {document['title']}
URL: {document['url']}
{document['content'][:2000]}

Respond with exactly one word from this list: CONFIRMS, CONTRADICTS, AMBIGUOUS, SILENT.
Do not output numbers. Do not explain."""

        try:
            response = self.llm.generate(prompt, temperature=0.0, max_tokens=10)
            text = response.content.strip().upper()
        except Exception:
            return SourceConfidence.AMBIGUOUS

        mapping = {
            "CONFIRMS": SourceConfidence.CONFIRMS,
            "CONTRADICTS": SourceConfidence.CONTRADICTS,
            "AMBIGUOUS": SourceConfidence.AMBIGUOUS,
            "SILENT": SourceConfidence.SILENT,
        }
        return mapping.get(text, SourceConfidence.AMBIGUOUS)

    @staticmethod
    def _aggregate_labels(labels: list[SourceConfidence]) -> SourceConfidence | None:
        if not labels:
            return None
        unique = set(labels)
        if unique == {SourceConfidence.SILENT}:
            return SourceConfidence.SILENT
        # Remove silent from consideration
        non_silent = {label for label in unique if label != SourceConfidence.SILENT}
        if not non_silent:
            return SourceConfidence.SILENT
        if len(non_silent) == 1:
            return non_silent.pop()
        # Disagreement or ambiguity present
        if SourceConfidence.AMBIGUOUS in non_silent:
            return SourceConfidence.AMBIGUOUS
        if SourceConfidence.CONFIRMS in non_silent and SourceConfidence.CONTRADICTS in non_silent:
            return SourceConfidence.AMBIGUOUS
        # Should not reach here
        return SourceConfidence.AMBIGUOUS
