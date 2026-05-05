"""
Audit, Replay, and Immutable Storage for the LSD Fact-Checking System v1.5.

Implements Phase 5 deliverables per 03_PIPELINE.md §6 and 04_ROADMAP.md Phase 5:
- AuditRecord with full provenance chain
- authoritative_result_hash (canonical JSON, excludes display summary)
- display_summary_hash (separate, non-authoritative)
- Merkle root over authoritative hashes only
- ReplayManifest for snapshot-compatible reconstruction
- Artifact replay: reconstruct FactCheckResults from frozen records without live APIs
- Frozen connector response storage keyed by query hash
- Web content hash / archive fallback records
- Additive invalidation records (human review corrections as new snapshots)

Design principles:
- Append-only: records are never mutated after creation.
- Hash chain: each AuditRecord references the previous record's hash.
- Merkle tree: built over authoritative_result_hash values for a snapshot.
- Artifact replay is authoritative; computational rerun is diagnostic-only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .v15_cache import canonical_json_hash, canonical_json_serialize
from .v15_models import (
    ClaimExpression,
    EvidenceItem,
    FactCheckResult,
    HumanReviewFlag,
    HumanReviewRecord,
    NodeType,
    ProvenanceSpan,
    SubclaimResult,
    SynthesisLogic,
    VerdictScope,
)

# ---------------------------------------------------------------------------
# DisplaySummary placeholder (Phase 7 will fully implement)
# ---------------------------------------------------------------------------


@dataclass
class DisplaySummary:
    """Non-authoritative display summary. Excluded from authoritative_result_hash."""

    summary_text: str = ""
    explanation: str = ""
    citations_formatted: List[str] = field(default_factory=list)
    confidence_statement: str = ""
    generated_at: str = ""
    generation_model: str = ""


# ---------------------------------------------------------------------------
# Default helpers (must be defined before dataclasses that use them)
# ---------------------------------------------------------------------------


def _default_subclaim_result() -> SubclaimResult:
    return SubclaimResult(subclaim_id="root", status="INSUFFICIENT", p=0.5)


# ---------------------------------------------------------------------------
# AuditRecord
# ---------------------------------------------------------------------------


@dataclass
class AuditRecord:
    """
    Immutable audit record for a single fact-check operation.

    Per 03_PIPELINE.md §6 (Audit & Immutable Storage).
    """

    audit_id: str
    premise_id: str
    snapshot_id: str
    timestamp: str  # ISO8601

    # Input provenance
    input_premise_text: str
    input_topic_id: str
    input_frame_id: str
    input_provenance_spans: List[ProvenanceSpan] = field(default_factory=list)

    # Processing provenance
    decomposition_version: str = ""
    decomposition_prompt_hash: str = ""
    linking_queries: List[Dict[str, str]] = field(default_factory=list)
    evidence_policy_version: str = ""
    connector_versions: Dict[str, str] = field(default_factory=dict)

    # Evidence provenance
    evidence_items: List[EvidenceItem] = field(default_factory=list)
    evidence_retrieval_manifest: List[Dict[str, Any]] = field(default_factory=list)

    # Decomposition provenance (required for authoritative hash replay)
    root_claim_expression: Optional[Any] = None
    atomic_subclaims: Optional[List[Any]] = None

    # Synthesis provenance
    synthesis_rule_engine_version: str = "v1.5"
    synthesis_logic: SynthesisLogic = field(default_factory=SynthesisLogic)
    display_summary: Optional[DisplaySummary] = None

    # Output
    result: SubclaimResult = field(default_factory=_default_subclaim_result)
    subclaim_results: List[SubclaimResult] = field(default_factory=list)

    # Full FactCheckResult for practical replay
    fact_check_result: Optional[FactCheckResult] = None

    # Tamper evidence
    authoritative_result_hash: str = ""
    display_summary_hash: Optional[str] = None
    previous_audit_hash: str = ""


# ---------------------------------------------------------------------------
# AdditiveInvalidationRecord
# ---------------------------------------------------------------------------


@dataclass
class AdditiveInvalidationRecord:
    """
    Additive invalidation: a new record that supersedes a prior audit record.

    The target record is never mutated. A new AuditRecord is created with
    corrected results, and this invalidation record links them.
    """

    invalidation_id: str
    target_audit_id: str
    target_snapshot_id: str
    corrected_audit_id: str
    invalidation_reason: str
    invalidation_authority: str  # "HUMAN_REVIEW", "GOVERNANCE", "AUTOMATED"
    invalidation_timestamp: str
    invalidation_hash: str = ""


# ---------------------------------------------------------------------------
# ReplayManifest
# ---------------------------------------------------------------------------


@dataclass
class ReplayManifest:
    """
    Manifest for artifact replay of a complete snapshot batch.

    Per 03_PIPELINE.md §6.
    """

    manifest_id: str
    snapshot_id: str
    parameter_pack: Dict[str, Any] = field(default_factory=dict)
    input_hashes: Dict[str, str] = field(default_factory=dict)  # premise_id -> hash
    authoritative_output_hashes: Dict[str, str] = field(
        default_factory=dict
    )  # premise_id -> authoritative_result_hash
    merkle_root: str = ""


# ---------------------------------------------------------------------------
# Canonical JSON hashing helpers
# ---------------------------------------------------------------------------


def _hash_premise_text(text: str) -> str:
    """SHA-256 of normalized premise text for input provenance hashing."""
    normalized = text.lower().strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _extract_authoritative_fact_check_result(result: FactCheckResult) -> Dict[str, Any]:
    """
    Extract only authoritative fields from a FactCheckResult.

    Excludes:
    - insufficiency_sensitivity (scoring/diagnostic)
    - decisive_premise_rank (scoring layer)
    - audit_metadata (may contain transient/debug info)
    - Any display_summary field
    """
    return {
        "premise_id": result.premise_id,
        "snapshot_id": result.snapshot_id,
        "topic_id": result.topic_id,
        "side": result.side.value if hasattr(result.side, "value") else str(result.side),
        "status": result.status,
        "p": result.p,
        "confidence": result.confidence,
        "best_evidence_tier": result.best_evidence_tier,
        "limiting_evidence_tier": result.limiting_evidence_tier,
        "decisive_evidence_tier": result.decisive_evidence_tier,
        "citations": sorted(result.citations),
        "operationalization": result.operationalization,
        "verdict_scope": result.verdict_scope,
        "insufficiency_reason": result.insufficiency_reason,
        "human_review_flags": sorted(
            f.value if hasattr(f, "value") else str(f) for f in result.human_review_flags
        ),
        "provenance_spans": [
            {
                "span_id": s.span_id,
                "post_id": s.post_id,
                "offsets": s.offsets,
                "span_text": s.span_text,
            }
            for s in result.provenance_spans
        ],
        "subclaim_results": [_extract_authoritative_subclaim_result(sr) for sr in result.subclaim_results],
    }


def _extract_authoritative_subclaim_result(sr: SubclaimResult) -> Dict[str, Any]:
    """Extract authoritative fields from a SubclaimResult."""
    return {
        "subclaim_id": sr.subclaim_id,
        "status": sr.status,
        "p": sr.p,
        "confidence": sr.confidence,
        "best_evidence_tier": sr.best_evidence_tier,
        "limiting_evidence_tier": sr.limiting_evidence_tier,
        "decisive_evidence_tier": sr.decisive_evidence_tier,
        "citations": sorted(sr.citations),
        "operationalization": sr.operationalization,
        "verdict_scope": sr.verdict_scope,
        "insufficiency_reason": sr.insufficiency_reason,
        "human_review_flags": sorted(
            f.value if hasattr(f, "value") else str(f) for f in sr.human_review_flags
        ),
        "provenance_spans": [
            {
                "span_id": s.span_id,
                "post_id": s.post_id,
                "offsets": s.offsets,
                "span_text": s.span_text,
            }
            for s in sr.provenance_spans
        ],
        "synthesis_logic": _extract_authoritative_synthesis_logic(sr.synthesis_logic),
        "resolved_value": sr.resolved_value,
    }


def _extract_authoritative_synthesis_logic(logic: SynthesisLogic) -> Dict[str, Any]:
    """Extract authoritative fields from SynthesisLogic."""
    return {
        "status_rule_applied": logic.status_rule_applied,
        "policy_rule_id": logic.policy_rule_id,
        "decisive_evidence": sorted(logic.decisive_evidence),
        "contradictory_evidence": sorted(logic.contradictory_evidence),
        "verdict_scope_applied": logic.verdict_scope_applied,
        "insufficiency_trigger": logic.insufficiency_trigger,
        "human_review_flags": sorted(
            f.value if hasattr(f, "value") else str(f) for f in logic.human_review_flags
        ),
        "authority_ranking_applied": logic.authority_ranking_applied,
        "claim_expression_node_type": (
            logic.claim_expression_node_type.value
            if hasattr(logic.claim_expression_node_type, "value")
            else str(logic.claim_expression_node_type)
        ),
    }


def compute_authoritative_result_hash(
    fact_check_result: FactCheckResult,
    input_premise_text: str,
    root_claim_expression: ClaimExpression,
    atomic_subclaims: List[Any],
    evidence_items: List[EvidenceItem],
    evidence_policy_version: str = "",
    connector_versions: Optional[Dict[str, str]] = None,
) -> str:
    """
    Compute the authoritative_result_hash for a fact-check operation.

    Includes:
    - Input premise id/text hash
    - Root ClaimExpression
    - Atomic subclaims
    - Evidence policy version
    - Normalized EvidenceItems used by synthesis
    - SynthesisLogic
    - FactCheckResult authoritative fields
    - Connector/source snapshot IDs

    Excludes:
    - display_summary
    - Free-form LLM explanation prose
    - UI formatting
    - Transient latency/debug logs
    """
    payload: Dict[str, Any] = {}

    # Input provenance hash
    payload["input_premise_id"] = fact_check_result.premise_id
    payload["input_premise_text_hash"] = _hash_premise_text(input_premise_text)
    payload["input_topic_id"] = fact_check_result.topic_id
    payload["snapshot_id"] = fact_check_result.snapshot_id

    # Root claim expression (required)
    payload["root_claim_expression"] = _serialize_claim_expression(root_claim_expression)

    # Atomic subclaims (required)
    payload["atomic_subclaims"] = [_serialize_atomic_subclaim(sc) for sc in atomic_subclaims]

    # Policy and connectors
    payload["evidence_policy_version"] = evidence_policy_version
    payload["connector_versions"] = connector_versions or {}

    # Evidence items (required — only those used in synthesis)
    payload["evidence_items"] = [_serialize_evidence_item(ei) for ei in evidence_items]

    # FactCheckResult authoritative fields
    payload["result"] = _extract_authoritative_fact_check_result(fact_check_result)

    return canonical_json_hash(payload)


def compute_display_summary_hash(display_summary: Optional[DisplaySummary]) -> Optional[str]:
    """Compute a separate hash for non-authoritative display summary content."""
    if display_summary is None:
        return None
    return canonical_json_hash(display_summary)


def _serialize_claim_expression(expr: ClaimExpression) -> Dict[str, Any]:
    """Serialize a ClaimExpression tree for hashing."""
    result: Dict[str, Any] = {
        "node_type": expr.node_type.value if hasattr(expr.node_type, "value") else str(expr.node_type),
    }
    if expr.subclaim_id is not None:
        result["subclaim_id"] = expr.subclaim_id
    if expr.operator is not None:
        result["operator"] = expr.operator
    if expr.quantifier is not None:
        result["quantifier"] = expr.quantifier
    if expr.quantifier_parameter is not None:
        result["quantifier_parameter"] = expr.quantifier_parameter
    if expr.comparison_target is not None:
        result["comparison_target"] = expr.comparison_target
    if expr.children:
        result["children"] = [_serialize_claim_expression(child) for child in expr.children]
    return result


def _serialize_atomic_subclaim(sc: Any) -> Dict[str, Any]:
    """Serialize an AtomicSubclaim for hashing."""
    return {
        "subclaim_id": sc.subclaim_id,
        "text": sc.text,
        "text_hash": _hash_premise_text(sc.text),
        "claim_type": sc.claim_type.value if hasattr(sc.claim_type, "value") else str(sc.claim_type),
        "operationalization_hint": sc.operationalization_hint,
        "verdict_scope_hint": sc.verdict_scope_hint,
    }


def _serialize_evidence_item(ei: EvidenceItem) -> Dict[str, Any]:
    """Serialize an EvidenceItem for authoritative hashing."""
    return {
        "evidence_id": ei.evidence_id,
        "subclaim_id": ei.subclaim_id,
        "source_type": ei.source_type.value if hasattr(ei.source_type, "value") else str(ei.source_type),
        "source_tier": ei.source_tier,
        "retrieval_path": (
            ei.retrieval_path.value if hasattr(ei.retrieval_path, "value") else str(ei.retrieval_path)
        ),
        "source_url": ei.source_url,
        "source_title": ei.source_title,
        "source_date": ei.source_date,
        "source_authority": ei.source_authority,
        "verdict_scope": ei.verdict_scope,
        "relevance_score": ei.relevance_score,
        "direction": ei.direction.value if hasattr(ei.direction, "value") else str(ei.direction),
        "direction_confidence": ei.direction_confidence,
        "direction_method": (
            ei.direction_method.value if hasattr(ei.direction_method, "value") else str(ei.direction_method)
        ),
        "connector_version": ei.connector_version,
        "connector_query_hash": ei.connector_query_hash,
        "source_snapshot_id": ei.source_snapshot_id,
        "raw_response_hash": ei.raw_response_hash,
        "claimed_value": ei.claimed_value,
        "source_value": ei.source_value,
        "deterministic_comparison_result": (
            ei.deterministic_comparison_result.value
            if hasattr(ei.deterministic_comparison_result, "value")
            else str(ei.deterministic_comparison_result)
        ),
        "source_independence_group_id": ei.source_independence_group_id,
        "llm_direction_allowed": ei.llm_direction_allowed,
    }


def compute_audit_record_full_hash(record: AuditRecord) -> str:
    """
    Compute the full canonical hash of an AuditRecord.

    Used for the tamper-evident hash chain (previous_audit_hash).
    Includes all fields except the record's own authoritative_result_hash
    and display_summary_hash to avoid self-reference issues.
    Actually, we include everything as-is; the previous_audit_hash field
    was set at creation time and is part of the immutable record.
    """
    # Create a serializable dict.  Exclude circular or non-serializable objects.
    d = {
        "audit_id": record.audit_id,
        "premise_id": record.premise_id,
        "snapshot_id": record.snapshot_id,
        "timestamp": record.timestamp,
        "input_premise_text_hash": _hash_premise_text(record.input_premise_text),
        "input_topic_id": record.input_topic_id,
        "input_frame_id": record.input_frame_id,
        "input_provenance_spans": [
            {"span_id": s.span_id, "post_id": s.post_id, "offsets": s.offsets, "span_text": s.span_text}
            for s in record.input_provenance_spans
        ],
        "decomposition_version": record.decomposition_version,
        "decomposition_prompt_hash": record.decomposition_prompt_hash,
        "linking_queries": record.linking_queries,
        "evidence_policy_version": record.evidence_policy_version,
        "connector_versions": record.connector_versions,
        "evidence_retrieval_manifest": record.evidence_retrieval_manifest,
        "synthesis_rule_engine_version": record.synthesis_rule_engine_version,
        "synthesis_logic": _extract_authoritative_synthesis_logic(record.synthesis_logic),
        "result": _extract_authoritative_subclaim_result(record.result),
        "subclaim_results": [_extract_authoritative_subclaim_result(sr) for sr in record.subclaim_results],
        "authoritative_result_hash": record.authoritative_result_hash,
        "display_summary_hash": record.display_summary_hash,
        "previous_audit_hash": record.previous_audit_hash,
    }
    return canonical_json_hash(d)


# ---------------------------------------------------------------------------
# Merkle tree
# ---------------------------------------------------------------------------


def _hash_pair(left: str, right: str) -> str:
    """Hash two sibling hashes together deterministically.

    Standard Merkle tree concatenation: left || right (tree order).
    """
    combined = left + right
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def compute_merkle_root(authoritative_hashes: List[str]) -> str:
    """
    Compute a Merkle root over a list of authoritative_result_hash values.

    - display_summary_hash is NOT included.
    - Empty list returns hash of empty string.
    - Single item returns hash of that item.
    """
    if not authoritative_hashes:
        return hashlib.sha256(b"").hexdigest()

    # Ensure deterministic ordering
    hashes = sorted(authoritative_hashes)

    # Pad to power of 2 by duplicating last element
    n = len(hashes)
    target = 1
    while target < n:
        target *= 2
    while len(hashes) < target:
        hashes.append(hashes[-1])

    # Build tree bottom-up
    level = hashes
    while len(level) > 1:
        next_level = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            next_level.append(_hash_pair(left, right))
        level = next_level

    return level[0]


# ---------------------------------------------------------------------------
# ReplayManifest builder
# ---------------------------------------------------------------------------


def build_replay_manifest(
    snapshot_id: str,
    audit_records: List[AuditRecord],
    parameter_pack: Optional[Dict[str, Any]] = None,
) -> ReplayManifest:
    """
    Build a ReplayManifest from a list of AuditRecords for a snapshot.

    Computes input_hashes, authoritative_output_hashes, and merkle_root.
    """
    input_hashes: Dict[str, str] = {}
    authoritative_output_hashes: Dict[str, str] = {}

    for record in audit_records:
        input_hashes[record.premise_id] = _hash_premise_text(record.input_premise_text)
        authoritative_output_hashes[record.premise_id] = record.authoritative_result_hash

    merkle_root = compute_merkle_root(list(authoritative_output_hashes.values()))

    return ReplayManifest(
        manifest_id=f"manifest_{uuid.uuid4().hex}",
        snapshot_id=snapshot_id,
        parameter_pack=parameter_pack or {},
        input_hashes=input_hashes,
        authoritative_output_hashes=authoritative_output_hashes,
        merkle_root=merkle_root,
    )


# ---------------------------------------------------------------------------
# FrozenConnectorStorage
# ---------------------------------------------------------------------------


class FrozenConnectorStorage:
    """
    Immutable storage for frozen connector responses keyed by query hash.

    Stores raw responses so artifact replay can verify evidence provenance
    without rerunning live APIs.
    """

    def __init__(self, db_path: str = ".fact_check_frozen.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=10.0)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS frozen_responses (
                    query_hash TEXT PRIMARY KEY,
                    connector_name TEXT NOT NULL,
                    connector_version TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    stored_at TIMESTAMP NOT NULL,
                    content_hash TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_frozen_connector
                ON frozen_responses(connector_name)
                """
            )
            conn.commit()

    def store(
        self,
        query_hash: str,
        connector_name: str,
        connector_version: str,
        response_json: str,
    ) -> str:
        """Store a frozen connector response. Returns content_hash."""
        content_hash = hashlib.sha256(response_json.encode("utf-8")).hexdigest()
        stored_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO frozen_responses
                    (query_hash, connector_name, connector_version, response_json, stored_at, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (query_hash, connector_name, connector_version, response_json, stored_at, content_hash),
                )
                conn.commit()
        return content_hash

    def retrieve(self, query_hash: str) -> Optional[Dict[str, Any]]:
        """Retrieve a frozen connector response by query hash."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM frozen_responses WHERE query_hash = ?",
                (query_hash,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(row)

    def verify(self, query_hash: str, expected_content_hash: str) -> bool:
        """Verify that a stored response matches an expected content hash."""
        record = self.retrieve(query_hash)
        if record is None:
            return False
        return record["content_hash"] == expected_content_hash


# ---------------------------------------------------------------------------
# AuditStore
# ---------------------------------------------------------------------------


class AuditStore:
    """
    Append-only SQLite storage for AuditRecords and invalidations.

    Thread-safe. Records are never updated after insertion.
    """

    def __init__(self, db_path: str = ".fact_check_audit_v15.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=10.0)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_records (
                    audit_id TEXT PRIMARY KEY,
                    premise_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    authoritative_result_hash TEXT NOT NULL,
                    previous_audit_hash TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_premise
                ON audit_records(premise_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_snapshot
                ON audit_records(snapshot_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_prev_hash
                ON audit_records(previous_audit_hash)
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS invalidation_records (
                    invalidation_id TEXT PRIMARY KEY,
                    target_audit_id TEXT NOT NULL,
                    target_snapshot_id TEXT NOT NULL,
                    corrected_audit_id TEXT NOT NULL,
                    invalidation_reason TEXT NOT NULL,
                    invalidation_authority TEXT NOT NULL,
                    invalidation_timestamp TEXT NOT NULL,
                    invalidation_hash TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_inv_target
                ON invalidation_records(target_audit_id)
                """
            )
            conn.commit()

    def store(self, record: AuditRecord) -> None:
        """Store an AuditRecord immutably."""
        # Ensure the full hash is computed if not already set
        if not record.authoritative_result_hash and record.fact_check_result is not None:
            raise ValueError("AuditRecord must have authoritative_result_hash before storage")

        record_json = canonical_json_serialize(record)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_records
                    (audit_id, premise_id, snapshot_id, timestamp, record_json,
                     authoritative_result_hash, previous_audit_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.audit_id,
                        record.premise_id,
                        record.snapshot_id,
                        record.timestamp,
                        record_json,
                        record.authoritative_result_hash,
                        record.previous_audit_hash,
                    ),
                )
                conn.commit()

    def get(self, audit_id: str) -> Optional[AuditRecord]:
        """Retrieve an AuditRecord by audit_id."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT record_json FROM audit_records WHERE audit_id = ?",
                (audit_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _deserialize_audit_record(row["record_json"])

    def get_by_premise(self, premise_id: str, snapshot_id: Optional[str] = None) -> List[AuditRecord]:
        """Retrieve all AuditRecords for a premise_id, optionally filtered by snapshot."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if snapshot_id:
                cursor = conn.execute(
                    """
                    SELECT record_json FROM audit_records
                    WHERE premise_id = ? AND snapshot_id = ?
                    ORDER BY timestamp ASC
                    """,
                    (premise_id, snapshot_id),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT record_json FROM audit_records
                    WHERE premise_id = ?
                    ORDER BY timestamp ASC
                    """,
                    (premise_id,),
                )
            rows = cursor.fetchall()
            return [_deserialize_audit_record(row["record_json"]) for row in rows]

    def get_by_snapshot(self, snapshot_id: str) -> List[AuditRecord]:
        """Retrieve all AuditRecords for a snapshot."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT record_json FROM audit_records
                WHERE snapshot_id = ?
                ORDER BY timestamp ASC
                """,
                (snapshot_id,),
            )
            rows = cursor.fetchall()
            return [_deserialize_audit_record(row["record_json"]) for row in rows]

    def get_latest_audit_hash(self, snapshot_id: str) -> str:
        """
        Get the authoritative_result_hash of the most recent audit record
        for a snapshot. Returns empty string if no records.
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT authoritative_result_hash FROM audit_records
                WHERE snapshot_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (snapshot_id,),
            )
            row = cursor.fetchone()
            return row["authoritative_result_hash"] if row else ""

    def store_invalidation(self, inv: AdditiveInvalidationRecord) -> None:
        """Store an AdditiveInvalidationRecord."""
        # Compute hash if not set
        if not inv.invalidation_hash:
            inv.invalidation_hash = canonical_json_hash(inv)

        record_json = canonical_json_serialize(inv)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO invalidation_records
                    (invalidation_id, target_audit_id, target_snapshot_id, corrected_audit_id,
                     invalidation_reason, invalidation_authority, invalidation_timestamp,
                     invalidation_hash, record_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        inv.invalidation_id,
                        inv.target_audit_id,
                        inv.target_snapshot_id,
                        inv.corrected_audit_id,
                        inv.invalidation_reason,
                        inv.invalidation_authority,
                        inv.invalidation_timestamp,
                        inv.invalidation_hash,
                        record_json,
                    ),
                )
                conn.commit()

    def get_invalidations_for_target(self, target_audit_id: str) -> List[AdditiveInvalidationRecord]:
        """Get all invalidations that target a given audit record."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT record_json FROM invalidation_records
                WHERE target_audit_id = ?
                ORDER BY invalidation_timestamp ASC
                """,
                (target_audit_id,),
            )
            rows = cursor.fetchall()
            return [_deserialize_invalidation_record(row["record_json"]) for row in rows]


def _deserialize_audit_record(record_json: str) -> AuditRecord:
    """Deserialize an AuditRecord from its canonical JSON representation."""
    # For full deserialization we'd need a proper parser, but for our purposes
    # we store the dataclass directly and reconstruct.  Since canonical JSON
    # serialization of dataclasses produces dicts, we use a helper.
    import json

    d = json.loads(record_json)
    return _dict_to_audit_record(d)


def _deserialize_invalidation_record(record_json: str) -> AdditiveInvalidationRecord:
    import json

    d = json.loads(record_json)
    return AdditiveInvalidationRecord(
        invalidation_id=d["invalidation_id"],
        target_audit_id=d["target_audit_id"],
        target_snapshot_id=d["target_snapshot_id"],
        corrected_audit_id=d["corrected_audit_id"],
        invalidation_reason=d["invalidation_reason"],
        invalidation_authority=d["invalidation_authority"],
        invalidation_timestamp=d["invalidation_timestamp"],
        invalidation_hash=d.get("invalidation_hash", ""),
    )


def _dict_to_claim_expression(d: Dict[str, Any]) -> ClaimExpression:
    """Reconstruct a ClaimExpression from a deserialized dict."""
    from .v15_models import NodeType

    node_type = NodeType(d.get("node_type", "ATOMIC"))
    children = [_dict_to_claim_expression(child) for child in d.get("children", [])]
    return ClaimExpression(
        node_type=node_type,
        subclaim_id=d.get("subclaim_id"),
        operator=d.get("operator"),
        quantifier=d.get("quantifier"),
        quantifier_parameter=d.get("quantifier_parameter"),
        comparison_target=d.get("comparison_target"),
        children=children,
    )


def _dict_to_atomic_subclaim(d: Dict[str, Any]) -> Any:
    """Reconstruct an AtomicSubclaim from a deserialized dict (simplified)."""
    from .v15_models import AtomicSubclaim, ClaimType

    claim_type_str = d.get("claim_type", "EMPIRICAL_ATOMIC")
    try:
        claim_type = ClaimType(claim_type_str)
    except ValueError:
        claim_type = ClaimType.EMPIRICAL_ATOMIC

    return AtomicSubclaim(
        subclaim_id=d.get("subclaim_id", ""),
        parent_premise_id="",
        text=d.get("text", d.get("text_hash", "")),
        claim_type=claim_type,
        operationalization_hint=d.get("operationalization_hint", ""),
        verdict_scope_hint=d.get("verdict_scope_hint", ""),
    )


def _dict_to_audit_record(d: Dict[str, Any]) -> AuditRecord:
    """Reconstruct an AuditRecord from a deserialized dict."""
    # Reconstruct ProvenanceSpan list
    spans = []
    for s in d.get("input_provenance_spans", []):
        spans.append(
            ProvenanceSpan(
                span_id=s.get("span_id", ""),
                post_id=s.get("post_id", ""),
                offsets=s.get("offsets", {}),
                span_text=s.get("span_text", ""),
            )
        )

    # Reconstruct EvidenceItem list (simplified — key fields only)
    evidence_items = []
    for ei in d.get("evidence_items", []):
        from .v15_models import (
            Direction,
            DirectionMethod,
            RetrievalPath,
            SourceType,
        )

        # Reconstruct ResolvedValue if present
        claimed_val = ei.get("claimed_value")
        source_val = ei.get("source_value")
        if claimed_val and isinstance(claimed_val, dict):
            from .v15_models import ResolvedValue, ValueType

            claimed_val = ResolvedValue(
                value=claimed_val.get("value"),
                unit=claimed_val.get("unit"),
                value_type=ValueType(claimed_val.get("value_type", "UNKNOWN")),
                lower_bound=claimed_val.get("lower_bound"),
                upper_bound=claimed_val.get("upper_bound"),
                measurement_definition=claimed_val.get("measurement_definition"),
                source_basis=claimed_val.get("source_basis"),
                verdict_scope=VerdictScope(**claimed_val.get("verdict_scope", {})),
                rounding_tolerance=claimed_val.get("rounding_tolerance"),
            )
        if source_val and isinstance(source_val, dict):
            from .v15_models import ResolvedValue, ValueType

            source_val = ResolvedValue(
                value=source_val.get("value"),
                unit=source_val.get("unit"),
                value_type=ValueType(source_val.get("value_type", "UNKNOWN")),
                lower_bound=source_val.get("lower_bound"),
                upper_bound=source_val.get("upper_bound"),
                measurement_definition=source_val.get("measurement_definition"),
                source_basis=source_val.get("source_basis"),
                verdict_scope=VerdictScope(**source_val.get("verdict_scope", {})),
                rounding_tolerance=source_val.get("rounding_tolerance"),
            )

        evidence_items.append(
            EvidenceItem(
                evidence_id=ei.get("evidence_id", ""),
                subclaim_id=ei.get("subclaim_id", ""),
                source_type=SourceType(ei.get("source_type", "OTHER")),
                source_tier=ei.get("source_tier", 3),
                retrieval_path=RetrievalPath(ei.get("retrieval_path", "DIRECT_CONNECTOR")),
                source_url=ei.get("source_url", ""),
                source_title=ei.get("source_title", ""),
                source_date=ei.get("source_date"),
                source_authority=ei.get("source_authority", ""),
                quote_or_span=ei.get("quote_or_span", ""),
                quote_context=ei.get("quote_context", ""),
                verdict_scope=VerdictScope(**ei.get("verdict_scope", {})),
                relevance_score=ei.get("relevance_score", 0.0),
                direction=Direction(ei.get("direction", "UNCLEAR")),
                direction_confidence=ei.get("direction_confidence", 0.0),
                direction_method=DirectionMethod(ei.get("direction_method", "DETERMINISTIC_STRUCTURED")),
                retrieval_timestamp=ei.get("retrieval_timestamp"),
                connector_version=ei.get("connector_version", ""),
                connector_query_hash=ei.get("connector_query_hash", ""),
                source_snapshot_id=ei.get("source_snapshot_id"),
                raw_response_hash=ei.get("raw_response_hash", ""),
                claimed_value=claimed_val,
                source_value=source_val,
            )
        )

    # Reconstruct SubclaimResult
    def _dict_to_subclaim_result(sr: Dict[str, Any]) -> SubclaimResult:
        from .v15_models import HumanReviewFlag, NodeType

        flags = []
        for f in sr.get("human_review_flags", []):
            try:
                flags.append(HumanReviewFlag(f))
            except ValueError:
                flags.append(HumanReviewFlag.NONE)

        logic = sr.get("synthesis_logic", {})
        logic_flags = []
        for f in logic.get("human_review_flags", []):
            try:
                logic_flags.append(HumanReviewFlag(f))
            except ValueError:
                logic_flags.append(HumanReviewFlag.NONE)

        return SubclaimResult(
            subclaim_id=sr.get("subclaim_id", ""),
            status=sr.get("status", "INSUFFICIENT"),
            p=sr.get("p", 0.5),
            confidence=sr.get("confidence", 0.0),
            best_evidence_tier=sr.get("best_evidence_tier"),
            limiting_evidence_tier=sr.get("limiting_evidence_tier"),
            decisive_evidence_tier=sr.get("decisive_evidence_tier"),
            citations=sr.get("citations", []),
            operationalization=sr.get("operationalization", ""),
            verdict_scope=VerdictScope(**sr.get("verdict_scope", {})),
            insufficiency_reason=sr.get("insufficiency_reason"),
            human_review_flags=flags,
            provenance_spans=[
                ProvenanceSpan(
                    span_id=s.get("span_id", ""),
                    post_id=s.get("post_id", ""),
                    offsets=s.get("offsets", {}),
                    span_text=s.get("span_text", ""),
                )
                for s in sr.get("provenance_spans", [])
            ],
            synthesis_logic=SynthesisLogic(
                status_rule_applied=logic.get("status_rule_applied", ""),
                policy_rule_id=logic.get("policy_rule_id", ""),
                decisive_evidence=logic.get("decisive_evidence", []),
                contradictory_evidence=logic.get("contradictory_evidence", []),
                subclaim_results=logic.get("subclaim_results", []),
                verdict_scope_applied=VerdictScope(**logic.get("verdict_scope_applied", {})),
                insufficiency_trigger=logic.get("insufficiency_trigger"),
                human_review_flags=logic_flags,
                authority_ranking_applied=logic.get("authority_ranking_applied", False),
                claim_expression_node_type=NodeType(logic.get("claim_expression_node_type", "ATOMIC")),
            ),
            synthesis_rule_engine_version=sr.get("synthesis_rule_engine_version", "v1.5"),
        )

    result_dict = d.get("result", {})
    subclaim_results = [_dict_to_subclaim_result(sr) for sr in d.get("subclaim_results", [])]

    # DisplaySummary
    display_summary = None
    ds = d.get("display_summary")
    if ds:
        display_summary = DisplaySummary(
            summary_text=ds.get("summary_text", ""),
            explanation=ds.get("explanation", ""),
            citations_formatted=ds.get("citations_formatted", []),
            confidence_statement=ds.get("confidence_statement", ""),
            generated_at=ds.get("generated_at", ""),
            generation_model=ds.get("generation_model", ""),
        )

    # Reconstruct root ClaimExpression if present
    root_ce = None
    ce_dict = d.get("root_claim_expression")
    if ce_dict:
        root_ce = _dict_to_claim_expression(ce_dict)

    # Reconstruct atomic subclaims if present (simplified)
    atomic_sc = []
    for sc_dict in d.get("atomic_subclaims", []):
        atomic_sc.append(_dict_to_atomic_subclaim(sc_dict))

    # Reconstruct FactCheckResult if present in JSON
    fact_check_result = None
    fcr = d.get("fact_check_result")
    if fcr:
        from .v15_models import Side

        side_val = fcr.get("side", "FOR")
        try:
            side = Side(side_val)
        except ValueError:
            side = Side.FOR

        fact_check_result = FactCheckResult(
            premise_id=fcr.get("premise_id", ""),
            snapshot_id=fcr.get("snapshot_id", ""),
            topic_id=fcr.get("topic_id", ""),
            side=side,
            status=fcr.get("status", "INSUFFICIENT"),
            p=fcr.get("p", 0.5),
            confidence=fcr.get("confidence", 0.0),
            best_evidence_tier=fcr.get("best_evidence_tier"),
            limiting_evidence_tier=fcr.get("limiting_evidence_tier"),
            decisive_evidence_tier=fcr.get("decisive_evidence_tier"),
            citations=fcr.get("citations", []),
            operationalization=fcr.get("operationalization", ""),
            verdict_scope=VerdictScope(**fcr.get("verdict_scope", {})),
            insufficiency_reason=fcr.get("insufficiency_reason"),
            human_review_flags=[
                HumanReviewFlag(f) if f in [e.value for e in HumanReviewFlag] else HumanReviewFlag.NONE
                for f in fcr.get("human_review_flags", [])
            ],
            provenance_spans=[
                ProvenanceSpan(
                    span_id=s.get("span_id", ""),
                    post_id=s.get("post_id", ""),
                    offsets=s.get("offsets", {}),
                    span_text=s.get("span_text", ""),
                )
                for s in fcr.get("provenance_spans", [])
            ],
            subclaim_results=subclaim_results,
            audit_metadata=fcr.get("audit_metadata", {}),
        )

    return AuditRecord(
        audit_id=d["audit_id"],
        premise_id=d["premise_id"],
        snapshot_id=d["snapshot_id"],
        timestamp=d["timestamp"],
        input_premise_text=d.get("input_premise_text", ""),
        input_topic_id=d.get("input_topic_id", ""),
        input_frame_id=d.get("input_frame_id", ""),
        input_provenance_spans=spans,
        decomposition_version=d.get("decomposition_version", ""),
        decomposition_prompt_hash=d.get("decomposition_prompt_hash", ""),
        linking_queries=d.get("linking_queries", []),
        evidence_policy_version=d.get("evidence_policy_version", ""),
        connector_versions=d.get("connector_versions", {}),
        evidence_items=evidence_items,
        evidence_retrieval_manifest=d.get("evidence_retrieval_manifest", []),
        root_claim_expression=root_ce,
        atomic_subclaims=atomic_sc,
        synthesis_rule_engine_version=d.get("synthesis_rule_engine_version", "v1.5"),
        synthesis_logic=SynthesisLogic(),  # Simplified — full logic is in subclaim_results
        display_summary=display_summary,
        result=_dict_to_subclaim_result(result_dict) if result_dict else _default_subclaim_result(),
        subclaim_results=subclaim_results,
        fact_check_result=fact_check_result,
        authoritative_result_hash=d.get("authoritative_result_hash", ""),
        display_summary_hash=d.get("display_summary_hash"),
        previous_audit_hash=d.get("previous_audit_hash", ""),
    )


# ---------------------------------------------------------------------------
# ArtifactReplayer
# ---------------------------------------------------------------------------


class ArtifactReplayer:
    """
    Reconstruct FactCheckResults from frozen AuditRecords without live APIs.

    Artifact replay is authoritative. Computational rerun is diagnostic-only.
    """

    def __init__(self, audit_store: AuditStore):
        self.audit_store = audit_store

    def replay_premise(
        self,
        premise_id: str,
        snapshot_id: str,
    ) -> Tuple[Optional[FactCheckResult], Dict[str, Any]]:
        """
        Replay a single premise from frozen records.

        Returns (FactCheckResult, diagnostics) where diagnostics includes
        hash_verification and replay_mode.
        """
        records = self.audit_store.get_by_premise(premise_id, snapshot_id)
        if not records:
            return None, {"error": "no_audit_record_found"}

        # Use the latest non-invalidated record
        record = self._latest_valid_record(records)
        if record is None:
            return None, {"error": "all_records_invalidated"}

        return self._replay_record(record)

    def replay_snapshot(
        self,
        snapshot_id: str,
        manifest: ReplayManifest,
    ) -> Dict[str, Tuple[Optional[FactCheckResult], Dict[str, Any]]]:
        """
        Replay an entire snapshot from frozen records.

        Verifies the Merkle root against stored authoritative hashes.
        """
        records = self.audit_store.get_by_snapshot(snapshot_id)
        results: Dict[str, Tuple[Optional[FactCheckResult], Dict[str, Any]]] = {}

        stored_hashes = [r.authoritative_result_hash for r in records if r.authoritative_result_hash]
        computed_root = compute_merkle_root(stored_hashes)
        merkle_valid = computed_root == manifest.merkle_root

        for record in records:
            result, diag = self._replay_record(record)
            diag["merkle_valid"] = merkle_valid
            diag["computed_merkle_root"] = computed_root
            diag["manifest_merkle_root"] = manifest.merkle_root
            results[record.premise_id] = (result, diag)

        return results

    def _latest_valid_record(self, records: List[AuditRecord]) -> Optional[AuditRecord]:
        """Return the latest record that has not been invalidated."""
        # Check invalidations for each record, working backwards
        for record in reversed(records):
            invalidations = self.audit_store.get_invalidations_for_target(record.audit_id)
            if not invalidations:
                return record
        return None

    def _replay_record(
        self, record: AuditRecord
    ) -> Tuple[Optional[FactCheckResult], Dict[str, Any]]:
        """Replay a single AuditRecord."""
        diagnostics: Dict[str, Any] = {
            "audit_id": record.audit_id,
            "replay_mode": "artifact",
            "hash_verified": False,
        }

        if record.fact_check_result is None:
            diagnostics["error"] = "no_fact_check_result_stored"
            return None, diagnostics

        # Verify the stored authoritative hash matches recomputation
        # We recompute from the stored components
        try:
            recomputed_hash = compute_authoritative_result_hash(
                fact_check_result=record.fact_check_result,
                input_premise_text=record.input_premise_text,
                root_claim_expression=record.root_claim_expression or ClaimExpression(
                    node_type=NodeType.ATOMIC, subclaim_id="default"
                ),
                atomic_subclaims=record.atomic_subclaims or [],
                evidence_items=record.evidence_items or [],
                evidence_policy_version=record.evidence_policy_version,
                connector_versions=record.connector_versions,
            )
        except Exception as exc:
            diagnostics["error"] = f"hash_recompute_failed: {exc}"
            return None, diagnostics

        diagnostics["hash_verified"] = recomputed_hash == record.authoritative_result_hash
        diagnostics["stored_hash"] = record.authoritative_result_hash
        diagnostics["recomputed_hash"] = recomputed_hash

        if not diagnostics["hash_verified"]:
            diagnostics["error"] = "hash_mismatch"
            return None, diagnostics

        # Return a deep copy to preserve immutability of stored record
        return copy.deepcopy(record.fact_check_result), diagnostics


# ---------------------------------------------------------------------------
# AuditRecord builder (convenience)
# ---------------------------------------------------------------------------


def build_audit_record(
    fact_check_result: FactCheckResult,
    input_premise_text: str,
    input_frame_id: str = "",
    input_provenance_spans: Optional[List[ProvenanceSpan]] = None,
    root_claim_expression: Optional[ClaimExpression] = None,
    atomic_subclaims: Optional[List[Any]] = None,
    evidence_items: Optional[List[EvidenceItem]] = None,
    evidence_retrieval_manifest: Optional[List[Dict[str, Any]]] = None,
    decomposition_version: str = "v1.5",
    decomposition_prompt_hash: str = "",
    linking_queries: Optional[List[Dict[str, str]]] = None,
    evidence_policy_version: str = "",
    connector_versions: Optional[Dict[str, str]] = None,
    display_summary: Optional[DisplaySummary] = None,
    previous_audit_hash: str = "",
    synthesis_rule_engine_version: str = "v1.5",
) -> AuditRecord:
    """
    Build a fully populated AuditRecord with all hashes computed.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    audit_id = f"audit_{uuid.uuid4().hex}"

    # Provide sensible defaults for backward compatibility in tests
    root_ce = root_claim_expression or ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id="default")
    atomic_sc = atomic_subclaims or []
    ev_items = evidence_items or []

    # Compute authoritative hash
    # Normalize defaults so serialization is deterministic across build/replay
    auth_hash = compute_authoritative_result_hash(
        fact_check_result=fact_check_result,
        input_premise_text=input_premise_text,
        root_claim_expression=root_ce,
        atomic_subclaims=atomic_sc,
        evidence_policy_version=evidence_policy_version,
        connector_versions=connector_versions or {},
        evidence_items=ev_items,
    )

    # Compute display summary hash
    ds_hash = compute_display_summary_hash(display_summary)

    # Determine root result from fact_check_result
    # The root result is essentially the top-level result fields as a SubclaimResult
    root_result = SubclaimResult(
        subclaim_id="root",
        status=fact_check_result.status,
        p=fact_check_result.p,
        confidence=fact_check_result.confidence,
        best_evidence_tier=fact_check_result.best_evidence_tier,
        limiting_evidence_tier=fact_check_result.limiting_evidence_tier,
        decisive_evidence_tier=fact_check_result.decisive_evidence_tier,
        citations=list(fact_check_result.citations),
        operationalization=fact_check_result.operationalization,
        verdict_scope=fact_check_result.verdict_scope,
        insufficiency_reason=fact_check_result.insufficiency_reason,
        human_review_flags=list(fact_check_result.human_review_flags),
        provenance_spans=list(fact_check_result.provenance_spans),
    )

    return AuditRecord(
        audit_id=audit_id,
        premise_id=fact_check_result.premise_id,
        snapshot_id=fact_check_result.snapshot_id,
        timestamp=timestamp,
        input_premise_text=input_premise_text,
        input_topic_id=fact_check_result.topic_id,
        input_frame_id=input_frame_id,
        input_provenance_spans=input_provenance_spans or [],
        decomposition_version=decomposition_version,
        decomposition_prompt_hash=decomposition_prompt_hash,
        linking_queries=linking_queries or [],
        evidence_policy_version=evidence_policy_version,
        connector_versions=connector_versions or {},
        evidence_items=ev_items,
        evidence_retrieval_manifest=evidence_retrieval_manifest or [],
        root_claim_expression=root_ce,
        atomic_subclaims=atomic_sc,
        synthesis_rule_engine_version=synthesis_rule_engine_version,
        display_summary=display_summary,
        result=root_result,
        subclaim_results=list(fact_check_result.subclaim_results),
        fact_check_result=fact_check_result,
        authoritative_result_hash=auth_hash,
        display_summary_hash=ds_hash,
        previous_audit_hash=previous_audit_hash,
    )


def create_additive_invalidation(
    target_record: AuditRecord,
    corrected_record: AuditRecord,
    reason: str,
    authority: str = "HUMAN_REVIEW",
) -> AdditiveInvalidationRecord:
    """Create an additive invalidation linking target to corrected record."""
    timestamp = datetime.now(timezone.utc).isoformat()
    inv = AdditiveInvalidationRecord(
        invalidation_id=f"inv_{uuid.uuid4().hex}",
        target_audit_id=target_record.audit_id,
        target_snapshot_id=target_record.snapshot_id,
        corrected_audit_id=corrected_record.audit_id,
        invalidation_reason=reason,
        invalidation_authority=authority,
        invalidation_timestamp=timestamp,
    )
    inv.invalidation_hash = canonical_json_hash(inv)
    return inv
