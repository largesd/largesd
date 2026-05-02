"""
Source connectors and ground-truth database for the Perfect Fact Checking Skill.

Each connector knows how to query one approved source and return
a discrete CONFIRMS / CONTRADICTS / SILENT / AMBIGUOUS result.
"""
import os
import json
import hashlib
import random
import re
from typing import Optional, List, Dict, Any, Protocol
from datetime import datetime
from dataclasses import dataclass

from .models import SourceConfidence, SourceResult, EvidenceTier


class SourceConnector:
    """
    Protocol for source connectors.
    """

    def query(self, normalized_claim: str, claim_hash: str) -> Optional[SourceResult]:
        raise NotImplementedError

    @property
    def source_id(self) -> str:
        raise NotImplementedError

    @property
    def tier(self) -> EvidenceTier:
        raise NotImplementedError


class GroundTruthDB:
    """
    Persistent ground-truth database for known claims.

    In production this is a curated table. For the prototype,
    it loads from a JSON file and falls back to source connectors
    for unknown claims.

    Schema (v1.0):
    {
      "<claim_hash>": {
        "schema_version": "1.0",
        "verdict": "SUPPORTED" | "REFUTED" | "INSUFFICIENT",
        "p_true": 1.0 | 0.0 | 0.5,
        "operationalization": str,
        "tier_counts": {"TIER_1": int, "TIER_2": int, "TIER_3": int},
        "evidence": [EvidenceRecord-dict, ...],
        "stored_at": ISO-8601,
        "reviewed_at": ISO-8601 | null,
        "reviewed_by": str | null,
        "review_rationale": str | null
      }
    }
    """

    SCHEMA_VERSION = "1.0"
    MIN_SCHEMA_VERSION = "1.0"

    def __init__(self, db_path: str = "data/ground_truth.json"):
        self.db_path = db_path
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                    if raw:
                        self._entries = json.loads(raw)
            except (json.JSONDecodeError, OSError):
                self._entries = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, indent=2, sort_keys=True)

    def lookup(self, claim_hash: str) -> Optional[Dict[str, Any]]:
        entry = self._entries.get(claim_hash)
        if entry is None:
            return None
        # Backward compat: entries without schema_version are treated as legacy
        sv = entry.get("schema_version", "0.0")
        if sv < self.MIN_SCHEMA_VERSION:
            # Allow legacy entries but note they lack review metadata
            pass
        return entry

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
            "reviewed_at": now if reviewed_by else None,
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
        # Seed RNG deterministically from source_id for stable behavior
        self._rng = random.Random(hashlib.sha256(source_id.encode()).hexdigest())

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def tier(self) -> EvidenceTier:
        if self._priority >= 8:
            return EvidenceTier.TIER_1
        elif self._priority >= 4:
            return EvidenceTier.TIER_2
        return EvidenceTier.TIER_3

    def query(self, normalized_claim: str, claim_hash: str) -> Optional[SourceResult]:
        # Deterministic behavior based on BOTH source_id and claim hash.
        # This ensures different connectors can disagree on the same claim,
        # which is required for meaningful consensus/disagreement tests.
        combined = f"{self._source_id}:{claim_hash}"
        hash_int = int(hashlib.sha256(combined.encode()).hexdigest()[:16], 16)
        has_evidence = (hash_int % 100) > 30  # 70% chance

        if not has_evidence:
            return None

        # Determine support level deterministically
        support_level = (hash_int % 100) / 100.0

        if support_level > 0.70:
            confidence = SourceConfidence.CONFIRMS
        elif support_level < 0.30:
            confidence = SourceConfidence.CONTRADICTS
        elif support_level > 0.45 and support_level < 0.55:
            confidence = SourceConfidence.AMBIGUOUS
        else:
            confidence = SourceConfidence.SILENT

        # Simulate content hash for drift detection
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
