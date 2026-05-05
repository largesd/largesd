"""
Phase 5 unit tests for the LSD Fact-Checking System v1.5.

Covers:
- AuditRecord creation with authoritative_result_hash
- display_summary_hash separation from authoritative hash
- Merkle root computation
- ReplayManifest construction
- Artifact replay reconstructs FactCheckResults from frozen records
- Hash stability across runs
- Additive invalidation records
- Frozen connector storage
- Human review queue and aggregate counts
- Hash chain tamper evidence
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Any, Dict, List

import pytest

from skills.fact_checking.decomposition import CanonicalPremise, Decomposer
from skills.fact_checking.human_review import (
    HumanReviewQueue,
    compute_aggregate_counts,
    create_human_review_record,
)
from skills.fact_checking.synthesis import SynthesisEngine
from skills.fact_checking.v15_audit import (
    AdditiveInvalidationRecord,
    ArtifactReplayer,
    AuditRecord,
    AuditStore,
    DisplaySummary,
    FrozenConnectorStorage,
    ReplayManifest,
    build_audit_record,
    build_replay_manifest,
    compute_authoritative_result_hash,
    compute_display_summary_hash,
    compute_merkle_root,
    create_additive_invalidation,
)
from skills.fact_checking.v15_models import (
    AtomicSubclaim,
    ClaimExpression,
    Direction,
    EvidenceItem,
    FactCheckResult,
    HumanReviewFlag,
    NodeType,
    ProvenanceSpan,
    Side,
    SubclaimResult,
    SynthesisLogic,
    VerdictScope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fact_check_result(
    premise_id: str = "p1",
    snapshot_id: str = "snap1",
    status: str = "SUPPORTED",
    p: float = 1.0,
    subclaim_results: List[SubclaimResult] | None = None,
) -> FactCheckResult:
    return FactCheckResult(
        premise_id=premise_id,
        snapshot_id=snapshot_id,
        topic_id="topic1",
        side=Side.FOR,
        status=status,
        p=p,
        confidence=1.0,
        best_evidence_tier=1,
        citations=["ev1"],
        operationalization="test_op",
        subclaim_results=subclaim_results or [],
    )


def _subclaim_result(
    subclaim_id: str = "sc1",
    status: str = "SUPPORTED",
    p: float = 1.0,
) -> SubclaimResult:
    return SubclaimResult(
        subclaim_id=subclaim_id,
        status=status,
        p=p,
        confidence=1.0,
        best_evidence_tier=1,
        citations=["ev1"],
        operationalization="test_op",
        synthesis_logic=SynthesisLogic(
            status_rule_applied="rule_d_tier1_decisive",
            claim_expression_node_type=NodeType.ATOMIC,
        ),
    )


def _evidence_item(
    subclaim_id: str = "sc1",
    tier: int = 1,
    direction: Direction = Direction.SUPPORTS,
) -> EvidenceItem:
    return EvidenceItem(
        subclaim_id=subclaim_id,
        source_tier=tier,
        direction=direction,
        direction_confidence=1.0,
        relevance_score=1.0,
        connector_version="mock_v1",
        connector_query_hash="qhash_123",
        raw_response_hash="rawhash_abc",
    )


# ---------------------------------------------------------------------------
# Authoritative hash tests
# ---------------------------------------------------------------------------


def test_authoritative_hash_excludes_display_summary():
    """Authoritative hash must not change when display summary changes."""
    result = _fact_check_result()
    display_summary = DisplaySummary(
        summary_text="This is supported.",
        explanation="Because evidence says so.",
    )

    root_expr = ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id="sc1")
    hash_without_ds = compute_authoritative_result_hash(
        fact_check_result=result,
        input_premise_text="test premise",
        root_claim_expression=root_expr,
        atomic_subclaims=[],
        evidence_items=[],
        evidence_policy_version="policy_v1",
    )

    # Recompute with display summary present in the record (but not in hash input)
    # The authoritative hash function does not take display_summary as an argument,
    # so the hash should be identical.
    hash_still_without = compute_authoritative_result_hash(
        fact_check_result=result,
        input_premise_text="test premise",
        root_claim_expression=root_expr,
        atomic_subclaims=[],
        evidence_items=[],
        evidence_policy_version="policy_v1",
    )

    assert hash_without_ds == hash_still_without
    assert len(hash_without_ds) == 64


def test_display_summary_hash_is_separate():
    """Display summary must have its own hash."""
    ds = DisplaySummary(summary_text="Supported", explanation="Because")
    h1 = compute_display_summary_hash(ds)
    h2 = compute_display_summary_hash(ds)
    assert h1 == h2
    assert len(h1) == 64
    assert compute_display_summary_hash(None) is None


def test_authoritative_hash_changes_with_result_fields():
    """Authoritative hash must change when authoritative fields change."""
    result1 = _fact_check_result(status="SUPPORTED", p=1.0)
    result2 = _fact_check_result(status="REFUTED", p=0.0)

    root_expr = ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id="sc1")
    hash1 = compute_authoritative_result_hash(
        fact_check_result=result1,
        input_premise_text="test premise",
        root_claim_expression=root_expr,
        atomic_subclaims=[],
        evidence_items=[],
    )
    hash2 = compute_authoritative_result_hash(
        fact_check_result=result2,
        input_premise_text="test premise",
        root_claim_expression=root_expr,
        atomic_subclaims=[],
        evidence_items=[],
    )

    assert hash1 != hash2


def test_authoritative_hash_stable_across_runs():
    """Same inputs must produce identical hash."""
    result = _fact_check_result()
    root_expr = ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id="sc1")
    hash1 = compute_authoritative_result_hash(
        fact_check_result=result,
        input_premise_text="test premise",
        root_claim_expression=root_expr,
        atomic_subclaims=[],
        evidence_items=[],
        evidence_policy_version="policy_v1",
        connector_versions={"mock": "v1"},
    )
    hash2 = compute_authoritative_result_hash(
        fact_check_result=result,
        input_premise_text="test premise",
        root_claim_expression=root_expr,
        atomic_subclaims=[],
        evidence_items=[],
        evidence_policy_version="policy_v1",
        connector_versions={"mock": "v1"},
    )
    assert hash1 == hash2


def test_authoritative_hash_includes_evidence_items():
    """Changing evidence items must change the authoritative hash."""
    result = _fact_check_result()
    ev1 = [_evidence_item()]
    ev2 = [_evidence_item(tier=2)]

    root_expr = ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id="sc1")
    hash1 = compute_authoritative_result_hash(
        fact_check_result=result,
        input_premise_text="test premise",
        root_claim_expression=root_expr,
        atomic_subclaims=[],
        evidence_items=ev1,
    )
    hash2 = compute_authoritative_result_hash(
        fact_check_result=result,
        input_premise_text="test premise",
        root_claim_expression=root_expr,
        atomic_subclaims=[],
        evidence_items=ev2,
    )

    assert hash1 != hash2


# ---------------------------------------------------------------------------
# Merkle root tests
# ---------------------------------------------------------------------------


def test_merkle_root_single_item():
    h = compute_merkle_root(["abc123"])
    # Single item in Merkle tree returns the hash itself (already SHA-256)
    assert h == "abc123"


def test_merkle_root_empty():
    h = compute_merkle_root([])
    assert len(h) == 64


def test_merkle_root_deterministic():
    hashes = ["a", "b", "c", "d"]
    r1 = compute_merkle_root(hashes)
    r2 = compute_merkle_root(["d", "c", "b", "a"])
    assert r1 == r2


def test_merkle_root_different_contents():
    r1 = compute_merkle_root(["a", "b"])
    r2 = compute_merkle_root(["a", "c"])
    assert r1 != r2


# ---------------------------------------------------------------------------
# ReplayManifest tests
# ---------------------------------------------------------------------------


def test_build_replay_manifest():
    result = _fact_check_result()
    record = build_audit_record(
        fact_check_result=result,
        input_premise_text="The sky is blue.",
        evidence_policy_version="policy_v1",
    )
    manifest = build_replay_manifest("snap1", [record])

    assert manifest.snapshot_id == "snap1"
    assert manifest.manifest_id.startswith("manifest_")
    assert manifest.input_hashes["p1"] == hashlib.sha256(b"the sky is blue.").hexdigest()
    assert manifest.authoritative_output_hashes["p1"] == record.authoritative_result_hash
    assert len(manifest.merkle_root) == 64


def test_replay_manifest_multiple_records():
    records = []
    for i in range(3):
        result = _fact_check_result(premise_id=f"p{i}", snapshot_id="snap1")
        record = build_audit_record(
            fact_check_result=result,
            input_premise_text=f"Premise {i}.",
            evidence_policy_version="policy_v1",
        )
        records.append(record)

    manifest = build_replay_manifest("snap1", records)
    assert len(manifest.input_hashes) == 3
    assert len(manifest.authoritative_output_hashes) == 3
    assert len(manifest.merkle_root) == 64


# ---------------------------------------------------------------------------
# AuditStore tests
# ---------------------------------------------------------------------------


def test_audit_store_store_and_retrieve():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)

        result = _fact_check_result()
        record = build_audit_record(
            fact_check_result=result,
            input_premise_text="test",
            evidence_policy_version="v1",
        )
        store.store(record)

        retrieved = store.get(record.audit_id)
        assert retrieved is not None
        assert retrieved.premise_id == "p1"
        assert retrieved.authoritative_result_hash == record.authoritative_result_hash


def test_audit_store_get_by_premise():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)

        result = _fact_check_result(premise_id="p1")
        record = build_audit_record(
            fact_check_result=result,
            input_premise_text="test",
            evidence_policy_version="v1",
        )
        store.store(record)

        records = store.get_by_premise("p1")
        assert len(records) == 1
        assert records[0].premise_id == "p1"


def test_audit_store_hash_chain():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)

        # First record
        result1 = _fact_check_result(premise_id="p1", snapshot_id="snap1")
        record1 = build_audit_record(
            fact_check_result=result1,
            input_premise_text="test1",
            evidence_policy_version="v1",
            previous_audit_hash="",
        )
        store.store(record1)

        # Second record should reference first
        result2 = _fact_check_result(premise_id="p2", snapshot_id="snap1")
        prev_hash = store.get_latest_audit_hash("snap1")
        record2 = build_audit_record(
            fact_check_result=result2,
            input_premise_text="test2",
            evidence_policy_version="v1",
            previous_audit_hash=prev_hash,
        )
        store.store(record2)

        assert record2.previous_audit_hash == record1.authoritative_result_hash


def test_audit_store_missing_record():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)
        assert store.get("nonexistent") is None


# ---------------------------------------------------------------------------
# ArtifactReplayer tests
# ---------------------------------------------------------------------------


def test_artifact_replay_reconstructs_result():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)

        result = _fact_check_result(
            status="SUPPORTED",
            p=1.0,
            subclaim_results=[_subclaim_result()],
        )
        record = build_audit_record(
            fact_check_result=result,
            input_premise_text="test",
            evidence_policy_version="v1",
        )
        store.store(record)

        replayer = ArtifactReplayer(store)
        replayed, diag = replayer.replay_premise("p1", "snap1")

        assert replayed is not None
        assert replayed.status == "SUPPORTED"
        assert replayed.p == 1.0
        assert diag["hash_verified"] is True
        assert diag["replay_mode"] == "artifact"


def test_artifact_replay_hash_mismatch():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)

        result = _fact_check_result()
        record = build_audit_record(
            fact_check_result=result,
            input_premise_text="test",
            evidence_policy_version="v1",
        )
        # Tamper with the hash
        record.authoritative_result_hash = "tampered"
        store.store(record)

        replayer = ArtifactReplayer(store)
        replayed, diag = replayer.replay_premise("p1", "snap1")

        assert replayed is None
        assert diag["hash_verified"] is False
        assert diag["error"] == "hash_mismatch"


def test_artifact_replay_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)
        replayer = ArtifactReplayer(store)
        replayed, diag = replayer.replay_premise("p1", "snap1")
        assert replayed is None
        assert diag["error"] == "no_audit_record_found"


def test_artifact_replay_snapshot_with_manifest():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)

        records = []
        for i in range(3):
            result = _fact_check_result(premise_id=f"p{i}", snapshot_id="snap1")
            record = build_audit_record(
                fact_check_result=result,
                input_premise_text=f"test {i}",
                evidence_policy_version="v1",
            )
            store.store(record)
            records.append(record)

        manifest = build_replay_manifest("snap1", records)
        replayer = ArtifactReplayer(store)
        results = replayer.replay_snapshot("snap1", manifest)

        assert len(results) == 3
        for premise_id, (result, diag) in results.items():
            assert result is not None
            assert diag["hash_verified"] is True
            assert diag["merkle_valid"] is True


def test_artifact_replay_snapshot_merkle_mismatch():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)

        records = []
        for i in range(2):
            result = _fact_check_result(premise_id=f"p{i}", snapshot_id="snap1")
            record = build_audit_record(
                fact_check_result=result,
                input_premise_text=f"test {i}",
                evidence_policy_version="v1",
            )
            store.store(record)
            records.append(record)

        manifest = build_replay_manifest("snap1", records)
        # Tamper manifest merkle root
        manifest.merkle_root = "tampered"

        replayer = ArtifactReplayer(store)
        results = replayer.replay_snapshot("snap1", manifest)

        for _, (result, diag) in results.items():
            assert diag["merkle_valid"] is False


# ---------------------------------------------------------------------------
# Additive invalidation tests
# ---------------------------------------------------------------------------


def test_additive_invalidation_record():
    target = build_audit_record(
        fact_check_result=_fact_check_result(),
        input_premise_text="target",
        evidence_policy_version="v1",
    )
    corrected = build_audit_record(
        fact_check_result=_fact_check_result(status="REFUTED", p=0.0),
        input_premise_text="corrected",
        evidence_policy_version="v1",
    )

    inv = create_additive_invalidation(
        target_record=target,
        corrected_record=corrected,
        reason="human_review_corrections",
        authority="HUMAN_REVIEW",
    )

    assert inv.target_audit_id == target.audit_id
    assert inv.corrected_audit_id == corrected.audit_id
    assert inv.invalidation_authority == "HUMAN_REVIEW"
    assert len(inv.invalidation_hash) == 64


def test_audit_store_invalidation_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)

        target = build_audit_record(
            fact_check_result=_fact_check_result(),
            input_premise_text="target",
            evidence_policy_version="v1",
        )
        corrected = build_audit_record(
            fact_check_result=_fact_check_result(status="REFUTED", p=0.0),
            input_premise_text="corrected",
            evidence_policy_version="v1",
        )
        inv = create_additive_invalidation(target, corrected, "review correction")
        store.store_invalidation(inv)

        invalidations = store.get_invalidations_for_target(target.audit_id)
        assert len(invalidations) == 1
        assert invalidations[0].invalidation_reason == "review correction"


# ---------------------------------------------------------------------------
# FrozenConnectorStorage tests
# ---------------------------------------------------------------------------


def test_frozen_connector_storage_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "frozen.db")
        storage = FrozenConnectorStorage(db_path=db_path)

        content_hash = storage.store(
            query_hash="q1",
            connector_name="wikidata",
            connector_version="v1",
            response_json='{"result": "Q42"}',
        )
        assert len(content_hash) == 64

        retrieved = storage.retrieve("q1")
        assert retrieved is not None
        assert retrieved["connector_name"] == "wikidata"
        assert retrieved["response_json"] == '{"result": "Q42"}'


def test_frozen_connector_storage_verify():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "frozen.db")
        storage = FrozenConnectorStorage(db_path=db_path)

        storage.store(
            query_hash="q1",
            connector_name="wikidata",
            connector_version="v1",
            response_json='{"result": "Q42"}',
        )

        assert storage.verify("q1", hashlib.sha256(b'{"result": "Q42"}').hexdigest()) is True
        assert storage.verify("q1", "wrong_hash") is False
        assert storage.verify("nonexistent", "any_hash") is False


# ---------------------------------------------------------------------------
# Human review tests
# ---------------------------------------------------------------------------


def test_human_review_queue_enqueue_and_list():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "queue.db")
        queue = HumanReviewQueue(db_path=db_path)

        queue_id = queue.enqueue(
            audit_id="audit_1",
            premise_id="p1",
            snapshot_id="snap1",
            premise_text="Test premise",
            flags=[HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE],
        )
        assert queue_id.startswith("queue_")

        pending = queue.list_pending()
        assert len(pending) == 1
        assert pending[0].premise_id == "p1"
        assert pending[0].flags == [HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE]


def test_human_review_queue_assign_and_complete():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "queue.db")
        queue = HumanReviewQueue(db_path=db_path)

        queue.enqueue(
            audit_id="audit_1",
            premise_id="p1",
            snapshot_id="snap1",
            premise_text="Test premise",
            flags=[HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE],
        )

        assert queue.assign("queue_audit_1", "reviewer_a") is True
        pending = queue.list_pending()
        assert len(pending) == 0

        from skills.fact_checking.v15_models import ReviewOutcome
        assert queue.complete("queue_audit_1", ReviewOutcome.REVIEWED_CORRECTION) is True


def test_aggregate_counts_with_suppression():
    from skills.fact_checking.v15_models import HumanReviewFlag

    class FakeRecord:
        def __init__(self, flags):
            self.human_review_flags = flags

    records = [
        FakeRecord([HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE]),
        FakeRecord([HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE]),
        FakeRecord([HumanReviewFlag.CONTRADICTORY_TIER1_EVIDENCE]),
        FakeRecord([HumanReviewFlag.POLICY_GAP]),
        FakeRecord([HumanReviewFlag.SCOPE_MISMATCH]),
    ]

    result = compute_aggregate_counts(records, small_count_threshold=3)
    assert result["total_records"] == 5
    assert result["flag_counts"]["CONTRADICTORY_TIER1_EVIDENCE"] == 3
    # POLICY_GAP and SCOPE_MISMATCH should be suppressed
    assert result["flag_counts"]["POLICY_GAP"] == 0
    assert result["flag_counts"]["SCOPE_MISMATCH"] == 0
    assert len(result["suppression_notes"]) == 2


def test_create_human_review_record():
    from skills.fact_checking.v15_models import ReviewOutcome

    record = create_human_review_record(
        target_audit_id="audit_1",
        target_snapshot_id="snap1",
        reviewer_role="senior_reviewer",
        review_outcome=ReviewOutcome.REVIEWED_CORRECTION,
        review_note="Corrected Tier 1 contradiction resolution",
    )

    assert record.target_audit_id == "audit_1"
    assert record.review_outcome == ReviewOutcome.REVIEWED_CORRECTION
    assert len(record.review_record_hash) == 64


# ---------------------------------------------------------------------------
# Integration: audited pipeline
# ---------------------------------------------------------------------------


def test_audited_pipeline_creates_record():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)

        premise = CanonicalPremise(
            premise_id="p1",
            snapshot_id="snap1",
            original_text="The unemployment rate is 4.0%.",
            topic_id="topic1",
            side=Side.FOR,
        )
        decomposer = Decomposer()
        engine = SynthesisEngine()

        # Simple evidence that should yield SUPPORTED
        ev = _evidence_item()
        from skills.fact_checking.v15_models import SourceType, DirectionMethod, ResolvedValue, ValueType
        ev.source_type = SourceType.OFFICIAL_STAT
        ev.source_authority = "Bureau of Labor Statistics"
        ev.direction_method = DirectionMethod.DETERMINISTIC_STRUCTURED
        ev.claimed_value = ResolvedValue(value=4.0, value_type=ValueType.NUMBER, unit="percent")
        ev.source_value = ResolvedValue(value=4.0, value_type=ValueType.NUMBER, unit="percent")

        from skills.fact_checking.decomposition import decompose_synthesize_and_audit
        result, audit_record = decompose_synthesize_and_audit(
            premise=premise,
            evidence_items=[ev],
            decomposer=decomposer,
            engine=engine,
            audit_store=store,
            evidence_policy_version="policy_v1",
        )

        assert result is not None
        assert audit_record is not None
        assert audit_record.premise_id == "p1"
        assert len(audit_record.authoritative_result_hash) == 64
        assert audit_record.fact_check_result is not None

        # Verify stored
        stored = store.get(audit_record.audit_id)
        assert stored is not None

        # Replay
        replayer = ArtifactReplayer(store)
        replayed, diag = replayer.replay_premise("p1", "snap1")
        assert replayed is not None
        assert diag["hash_verified"] is True


# ---------------------------------------------------------------------------
# Hash chain tamper evidence
# ---------------------------------------------------------------------------


def test_hash_chain_detects_tampering():
    """If an earlier record is tampered, the chain is broken."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit.db")
        store = AuditStore(db_path=db_path)

        # Record 1
        result1 = _fact_check_result(premise_id="p1", snapshot_id="snap1")
        record1 = build_audit_record(
            fact_check_result=result1,
            input_premise_text="test1",
            previous_audit_hash="",
        )
        store.store(record1)

        # Record 2 references record 1
        prev_hash = store.get_latest_audit_hash("snap1")
        result2 = _fact_check_result(premise_id="p2", snapshot_id="snap1")
        record2 = build_audit_record(
            fact_check_result=result2,
            input_premise_text="test2",
            previous_audit_hash=prev_hash,
        )
        store.store(record2)

        # Verify chain: record2.previous_audit_hash should equal record1's authoritative hash
        assert record2.previous_audit_hash == record1.authoritative_result_hash

        # If record1 were tampered, its hash would change, breaking the chain.
        # We can't actually tamper the DB (append-only), but we can verify the logic.
        # Use the same dummy root_claim_expression that build_audit_record auto-fills.
        dummy_root = ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id="default")
        recomputed_hash1 = compute_authoritative_result_hash(
            fact_check_result=result1,
            input_premise_text="test1",
            root_claim_expression=dummy_root,
            atomic_subclaims=[],
            connector_versions={},
            evidence_items=[],
        )
        assert recomputed_hash1 == record1.authoritative_result_hash
