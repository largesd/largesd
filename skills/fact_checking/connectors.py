"""
Source connectors and ground-truth storage for the fact-checking skill.

Ground truth is treated as curated Tier-1 evidence, but its decisive effect is
still governed by the evidence policy. Legacy and partially populated rows are
loaded defensively so older stores degrade to an empty or best-effort state
instead of crashing the runtime.
"""

import hashlib
import json
import os
import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import (
    EvidenceRecord,
    EvidenceTier,
    SourceConfidence,
    SourceResult,
)


class SourceConnector:
    """Protocol-like base class for source connectors."""

    def query(self, normalized_claim: str, claim_hash: str) -> Optional[SourceResult]:
        raise NotImplementedError

    @property
    def source_id(self) -> str:
        raise NotImplementedError

    @property
    def tier(self) -> EvidenceTier:
        raise NotImplementedError


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _coerce_tier(value: Any, default: EvidenceTier = EvidenceTier.TIER_1) -> EvidenceTier:
    if isinstance(value, EvidenceTier):
        return value
    if isinstance(value, str):
        try:
            return EvidenceTier(value)
        except ValueError:
            return default
    return default


def _verdict_to_confidence(verdict: str) -> SourceConfidence:
    if verdict == "SUPPORTED":
        return SourceConfidence.CONFIRMS
    if verdict == "REFUTED":
        return SourceConfidence.CONTRADICTS
    return SourceConfidence.SILENT


class GroundTruthDB:
    """
    Persistent ground-truth database for curated fact-check outcomes.

    The store is intentionally lenient with legacy rows:
    - missing ``schema_version`` is treated as legacy, not fatal
    - missing ``retrieved_at`` falls back to review/store timestamps
    - missing review metadata is treated as absent metadata
    - malformed files degrade to an empty store
    """

    SCHEMA_VERSION = "1.0"
    MIN_SCHEMA_VERSION = "1.0"

    def __init__(self, db_path: str = "data/ground_truth.json"):
        self.db_path = db_path
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.db_path):
            self._entries = {}
            return

        try:
            with open(self.db_path, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
        except OSError:
            self._entries = {}
            return

        if not raw:
            self._entries = {}
            return

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            self._entries = {}
            return

        self._entries = parsed if isinstance(parsed, dict) else {}

    def _save(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with open(self.db_path, "w", encoding="utf-8") as handle:
            json.dump(self._entries, handle, indent=2, sort_keys=True)

    def lookup(self, claim_hash: str) -> Optional[Dict[str, Any]]:
        entry = self._entries.get(claim_hash)
        if not isinstance(entry, dict):
            return None
        return entry

    def build_source_results(self, claim_hash: str) -> List[SourceResult]:
        entry = self.lookup(claim_hash)
        return self.entry_to_source_results(entry) if entry else []

    def build_evidence_records(self, claim_hash: str) -> List[EvidenceRecord]:
        entry = self.lookup(claim_hash)
        return self.entry_to_evidence_records(entry) if entry else []

    @staticmethod
    def entry_to_source_results(entry: Optional[Dict[str, Any]]) -> List[SourceResult]:
        if not entry:
            return []

        verdict = str(entry.get("verdict", "INSUFFICIENT"))
        confidence = _verdict_to_confidence(verdict)
        if confidence == SourceConfidence.SILENT:
            return []

        evidence_rows = entry.get("evidence", [])
        if not isinstance(evidence_rows, list):
            evidence_rows = []

        fallback_timestamp = (
            _coerce_datetime(entry.get("reviewed_at"))
            or _coerce_datetime(entry.get("stored_at"))
            or datetime.utcnow()
        )

        results: List[SourceResult] = []
        for index, row in enumerate(evidence_rows):
            if not isinstance(row, dict):
                continue

            retrieved_at = (
                _coerce_datetime(row.get("retrieved_at"))
                or _coerce_datetime(row.get("reviewed_at"))
                or fallback_timestamp
            )
            source_id = str(row.get("source_id") or f"ground_truth:{index + 1}")
            source_title = str(row.get("source_title") or "Ground Truth Entry")
            snippet = str(row.get("snippet") or row.get("excerpt") or "")
            content_hash = str(
                row.get("content_hash")
                or hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:32]
            )

            results.append(
                SourceResult(
                    source_id=source_id,
                    source_url=str(row.get("source_url") or ""),
                    source_title=source_title,
                    confidence=confidence,
                    excerpt=snippet,
                    content_hash=content_hash,
                    retrieved_at=retrieved_at,
                    tier=_coerce_tier(row.get("evidence_tier") or row.get("tier")),
                )
            )

        if results:
            return results

        synthetic_excerpt = str(entry.get("review_rationale") or "Curated ground-truth entry.")
        return [
            SourceResult(
                source_id="ground_truth",
                source_url="",
                source_title="Ground Truth Entry",
                confidence=confidence,
                excerpt=synthetic_excerpt,
                content_hash=hashlib.sha256(synthetic_excerpt.encode("utf-8")).hexdigest()[:32],
                retrieved_at=fallback_timestamp,
                tier=EvidenceTier.TIER_1,
            )
        ]

    @staticmethod
    def entry_to_evidence_records(entry: Optional[Dict[str, Any]]) -> List[EvidenceRecord]:
        source_results = GroundTruthDB.entry_to_source_results(entry)
        evidence: List[EvidenceRecord] = []

        for index, result in enumerate(source_results):
            evidence.append(
                EvidenceRecord(
                    source_url=result.source_url,
                    source_id=result.source_id,
                    source_version="v1",
                    source_title=result.source_title,
                    snippet=result.excerpt,
                    content_hash=result.content_hash,
                    retrieved_at=result.retrieved_at,
                    relevance_score=1.0,
                    support_score=1.0 if result.confidence == SourceConfidence.CONFIRMS else 0.0,
                    contradiction_score=1.0 if result.confidence == SourceConfidence.CONTRADICTS else 0.0,
                    selected_rank=index + 1,
                    evidence_tier=result.tier,
                )
            )

        return evidence

    def store(
        self,
        claim_hash: str,
        verdict: str,
        p_true: float,
        operationalization: str,
        tier_counts: Dict[str, int],
        evidence: List[Dict[str, Any]],
        reviewed_by: Optional[str] = None,
        review_rationale: Optional[str] = None,
        reviewed_at: Optional[str] = None,
    ):
        now = datetime.utcnow().isoformat() + "Z"
        self._entries[claim_hash] = {
            "schema_version": self.SCHEMA_VERSION,
            "verdict": verdict,
            "p_true": p_true,
            "operationalization": operationalization,
            "tier_counts": tier_counts,
            "evidence": evidence,
            "stored_at": now,
            "reviewed_at": reviewed_at or (now if reviewed_by else None),
            "reviewed_by": reviewed_by,
            "review_rationale": review_rationale,
        }
        self._save()


class SimulatedSourceConnector(SourceConnector):
    """
    Deterministic simulated source connector for testing and prototyping.
    Generates evidence based on claim hash for reproducible results.
    """

    def __init__(self, source_id: str, domain: str, priority: int = 5):
        self._source_id = source_id
        self._domain = domain
        self._priority = priority
        self._rng = random.Random(hashlib.sha256(source_id.encode()).hexdigest())

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def tier(self) -> EvidenceTier:
        if self._priority >= 8:
            return EvidenceTier.TIER_1
        if self._priority >= 4:
            return EvidenceTier.TIER_2
        return EvidenceTier.TIER_3

    def query(self, normalized_claim: str, claim_hash: str) -> Optional[SourceResult]:
        combined = f"{self._source_id}:{claim_hash}"
        hash_int = int(hashlib.sha256(combined.encode()).hexdigest()[:16], 16)
        has_evidence = (hash_int % 100) > 30

        if not has_evidence:
            return None

        support_level = (hash_int % 100) / 100.0

        if support_level > 0.70:
            confidence = SourceConfidence.CONFIRMS
        elif support_level < 0.30:
            confidence = SourceConfidence.CONTRADICTS
        elif 0.45 < support_level < 0.55:
            confidence = SourceConfidence.AMBIGUOUS
        else:
            confidence = SourceConfidence.SILENT

        content = f"{self._source_id}:{normalized_claim}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

        return SourceResult(
            source_id=self._source_id,
            source_url=f"https://{self._domain}/evidence/{claim_hash[:16]}",
            source_title=f"Reference from {self._source_id}",
            confidence=confidence,
            excerpt=f"Evidence related to claim: {normalized_claim[:50]}...",
            content_hash=content_hash,
            retrieved_at=datetime.now(),
            tier=self.tier,
        )
