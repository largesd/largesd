"""
Test script for the Fact Checking Skill
Verifies compliance with both:
- Fact Checking Skill Design Specification
- Large Scale Discussion requirements
"""
import os
import sys
import json
import time
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

from skills.fact_checking import (
    ClaimDecomposer,
    ConnectorPlanner,
    EvidencePolicy,
    EvidenceTier,
    FactCheckingSkill,
    GroundTruthDB,
    FactCheckVerdict,
    FactCheckStatus,
    RequestContext,
    SourceConfidence,
    SourceResult,
    TemporalContext,
    WikidataConnector,
)


class StaticConnector:
    """Deterministic connector used for behavioral tests."""

    def __init__(self, source_id: str, confidence: SourceConfidence,
                 tier: EvidenceTier = EvidenceTier.TIER_1, sleep_seconds: float = 0.0):
        self._source_id = source_id
        self._confidence = confidence
        self._tier = tier
        self._sleep_seconds = sleep_seconds

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def tier(self) -> EvidenceTier:
        return self._tier

    def query(self, normalized_claim: str, claim_hash: str):
        if self._sleep_seconds:
            time.sleep(self._sleep_seconds)
        return SourceResult(
            source_id=self._source_id,
            source_url=f"https://example.test/{self._source_id}/{claim_hash[:8]}",
            source_title=f"Static evidence from {self._source_id}",
            confidence=self._confidence,
            excerpt=f"{self._source_id} says: {normalized_claim}",
            content_hash=f"{self._source_id}:{claim_hash[:8]}",
            retrieved_at=datetime.now(),
            tier=self._tier,
        )


def _wait_for_job(skill: FactCheckingSkill, job_id: str, timeout_seconds: float = 3.0):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = skill.get_job_result(job_id)
        if result is not None:
            return result
        time.sleep(0.05)
    return None


def _gold_fixture_path() -> str:
    return str(
        REPO_ROOT
        / "skills"
        / "fact_checking"
        / "testdata"
        / "fact_check_gold_v1.jsonl"
    )


def _load_gold_cases():
    with open(_gold_fixture_path(), "r", encoding="utf-8") as handle:
        return [
            json.loads(line)
            for line in handle
            if line.strip()
        ]


def test_offline_mode():
    """Test OFFLINE mode returns neutral results"""
    print("\n=== Testing OFFLINE Mode ===")
    
    skill = FactCheckingSkill(mode="OFFLINE", allowlist_version="v1")
    
    result = skill.check_fact("GDP grew 3% in 2023")
    
    assert result.fact_mode == "OFFLINE", "Mode should be OFFLINE"
    assert result.status == FactCheckStatus.UNVERIFIED_OFFLINE, "Status should be UNVERIFIED_OFFLINE"
    assert result.verdict == FactCheckVerdict.UNVERIFIED, "Verdict should be UNVERIFIED"
    assert result.factuality_score == 0.5, "Factuality score should be 0.5"
    assert result.confidence == 0.0, "Confidence should be 0.0"
    
    print("✓ OFFLINE mode returns correct neutral values")
    skill.shutdown()


def test_normalization():
    """Test claim normalization"""
    print("\n=== Testing Claim Normalization ===")
    
    from skills.fact_checking.normalization import ClaimNormalizer
    
    # Test basic normalization
    text1 = "  The   GDP grew  3.5 percent  in 2023  "
    norm1 = ClaimNormalizer.normalize(text1)
    assert norm1 == "the gdp grew 3.5% in 2023", f"Got: {norm1}"
    print("✓ Basic normalization works")
    
    # Test number normalization
    text2 = "Population is 1,000,000"
    norm2 = ClaimNormalizer.normalize(text2)
    assert norm2 == "population is 1000000", f"Got: {norm2}"
    print("✓ Number normalization works")

    # Test repeated thousands separators
    text3 = "Budget is 1,234,567"
    norm3 = ClaimNormalizer.normalize(text3)
    assert norm3 == "budget is 1234567", f"Got: {norm3}"
    print("✓ Repeated thousands separators normalize iteratively")

    # Test alternate percent spelling
    text4 = "Inflation rose 3.5 per cent"
    norm4 = ClaimNormalizer.normalize(text4)
    assert norm4 == "inflation rose 3.5%", f"Got: {norm4}"
    print("✓ 'per cent' normalization works")

    # Test non-breaking spaces and unicode punctuation
    text5 = "\u00a0“AI\u2014safety”\u00a0matters\u00a0"
    norm5 = ClaimNormalizer.normalize(text5)
    assert norm5 == '"ai-safety" matters', f"Got: {norm5}"
    print("✓ Unicode punctuation and non-breaking spaces normalize correctly")
    
    # Test hash stability
    hash1 = ClaimNormalizer.compute_hash(norm1)
    hash2 = ClaimNormalizer.compute_hash(norm1)
    assert hash1 == hash2, "Hash should be deterministic"
    print("✓ Hash is deterministic")
    
    # Test case insensitivity
    norm_upper = ClaimNormalizer.normalize("GDP GREW 3%")
    norm_lower = ClaimNormalizer.normalize("gdp grew 3%")
    assert norm_upper == norm_lower, "Normalization should be case insensitive"
    print("✓ Case normalization works")


def test_cache():
    """Test multi-layer caching"""
    print("\n=== Testing Multi-Layer Cache ===")
    import tempfile
    import shutil
    
    # Create temp directory for isolated cache
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_cache.db")
    
    try:
        from skills.fact_checking.cache import MultiLayerCache
        
        cache = MultiLayerCache(ttl_seconds=3600, db_path=db_path)
        
        # First get should miss
        result, layer = cache.get("test_key")
        assert result is None, "First get should be cache miss"
        print("✓ First get is cache miss")
        
        # Create a mock result to store
        from skills.fact_checking.models import FactCheckResult, FactCheckStatus, FactCheckVerdict
        mock_result = FactCheckResult(
            claim_text="test",
            normalized_claim_text="test",
            claim_hash="abc123",
            fact_mode="OFFLINE",
            allowlist_version="v1",
            status=FactCheckStatus.UNVERIFIED_OFFLINE,
            verdict=FactCheckVerdict.UNVERIFIED,
            factuality_score=0.5,
            confidence=0.0,
            confidence_explanation="test",
        )
        
        # Store in cache
        cache.set("test_key", mock_result)
        print("✓ Stored result in cache")
        
        # Second get should hit
        result, layer = cache.get("test_key")
        assert result is not None, "Second get should be cache hit"
        print(f"✓ Second get is {layer.value}")
        
        # Results should match
        assert result.factuality_score == mock_result.factuality_score, "Cached results should match"
        print("✓ Cached results are identical")
        
    finally:
        shutil.rmtree(temp_dir)


def test_pii_detection():
    """Test PII detection and redaction"""
    print("\n=== Testing PII Detection ===")
    
    from skills.fact_checking.pii import PIIDetector
    
    # Test email detection
    text_with_email = "Contact john@example.com for details"
    result = PIIDetector.detect(text_with_email)
    assert result.contains_pii, "Should detect email as PII"
    assert 'email' in result.detected_types, "Should identify as email"
    print("✓ Email PII detection works")
    
    # Test phone detection
    text_with_phone = "Call 555-123-4567 for info"
    result = PIIDetector.detect(text_with_phone)
    assert result.contains_pii, "Should detect phone as PII"
    assert 'phone' in result.detected_types, "Should identify as phone"
    print("✓ Phone PII detection works")
    
    # Test sanitization
    sanitized = PIIDetector.sanitize_for_external_query(text_with_email)
    assert "@" not in sanitized, "Email should be removed from query"
    print("✓ PII sanitization works")

    # Detection types should be deterministic when multiple PII categories are present
    multi_pii_text = "Email john@example.com or call 555-123-4567"
    multi_result = PIIDetector.detect(multi_pii_text)
    assert multi_result.detected_types == ["email", "phone"], f"Got: {multi_result.detected_types}"
    print("✓ PII detected types are returned in deterministic order")

    # Query sanitization should remove multiple supported PII categories
    mixed_query = "Reach john@example.com from 10.0.0.1 or use card 4111 1111 1111 1111"
    mixed_sanitized = PIIDetector.sanitize_for_external_query(mixed_query)
    assert "@" not in mixed_sanitized, "Email should be removed"
    assert "10.0.0.1" not in mixed_sanitized, "IP address should be removed"
    assert "4111" not in mixed_sanitized, "Credit card should be removed"
    print("✓ Query sanitization removes multiple PII categories")


def test_online_allowlist_simulation():
    """Test ONLINE_ALLOWLIST mode with simulated sources"""
    print("\n=== Testing ONLINE_ALLOWLIST Mode ===")
    
    skill = FactCheckingSkill(
        mode="ONLINE_ALLOWLIST", 
        allowlist_version="v1",
        enable_async=False  # Sync for testing
    )
    
    result = skill.check_fact("AI capabilities can lower the cost of generating misinformation")
    
    assert result.fact_mode == "ONLINE_ALLOWLIST", "Mode should be ONLINE_ALLOWLIST"
    assert result.status in [FactCheckStatus.CHECKED, FactCheckStatus.NO_ALLOWLIST_EVIDENCE], \
        f"Status should be CHECKED or NO_ALLOWLIST_EVIDENCE, got {result.status}"
    assert 0.0 <= result.factuality_score <= 1.0, "Factuality score should be in [0,1]"
    assert 0.0 <= result.confidence <= 1.0, "Confidence should be in [0,1]"
    
    print(f"✓ ONLINE_ALLOWLIST returns valid result: {result.verdict.value}, "
          f"score={result.factuality_score}, confidence={result.confidence}")
    
    # Check evidence structure if present
    if result.evidence:
        ev = result.evidence[0]
        assert ev.source_url, "Evidence should have source_url"
        assert ev.content_hash, "Evidence should have content_hash for drift detection"
        print(f"✓ Evidence record has required fields: source_url, content_hash")
    
    skill.shutdown()


def test_verdict_thresholds():
    """Test verdict determination based on thresholds"""
    print("\n=== Testing Verdict Thresholds ===")
    
    from skills.fact_checking.skill import FactCheckingSkill
    
    skill = FactCheckingSkill.__new__(FactCheckingSkill)
    skill.config = type('obj', (object,), {
        'support_threshold': 0.70,
        'contradiction_threshold': 0.70,
        'mixed_threshold': 0.40,
        'confidence_penalty_threshold': 0.30,
    })()
    
    # Test SUPPORTED
    verdict = skill._determine_verdict(0.75, 0.20)
    assert verdict == FactCheckVerdict.SUPPORTED, f"Expected SUPPORTED, got {verdict}"
    print("✓ SUPPORTED verdict works")
    
    # Test REFUTED
    verdict = skill._determine_verdict(0.20, 0.75)
    assert verdict == FactCheckVerdict.REFUTED, f"Expected REFUTED, got {verdict}"
    print("✓ REFUTED verdict works")
    
    # Test INSUFFICIENT (mixed signals)
    verdict = skill._determine_verdict(0.50, 0.50)
    assert verdict == FactCheckVerdict.INSUFFICIENT, f"Expected INSUFFICIENT, got {verdict}"
    print("✓ INSUFFICIENT verdict works")
    
    # Test INSUFFICIENT (weak signals)
    verdict = skill._determine_verdict(0.10, 0.10)
    assert verdict == FactCheckVerdict.INSUFFICIENT, f"Expected INSUFFICIENT, got {verdict}"
    print("✓ INSUFFICIENT verdict works")


def test_async_processing():
    """Test async processing queue"""
    print("\n=== Testing Async Processing ===")
    
    skill = FactCheckingSkill(
        mode="ONLINE_ALLOWLIST",
        allowlist_version="v1",
        enable_async=True,
        async_worker_count=2
    )
    
    # Submit multiple async requests
    jobs = []
    for i in range(3):
        job = skill.check_fact_async(
            f"Test claim {i}",
            request_context=RequestContext(post_id=f"post_{i}")
        )
        jobs.append(job)
        print(f"  Submitted job {job.job_id}")
    
    # Check initial status
    for job in jobs:
        status = skill.get_job_status(job.job_id)
        assert status in ["queued", "processing", "completed"], f"Job should be queued, processing, or already completed, got {status}"
    print("✓ Jobs are queued/processing/completed as expected")
    
    # Wait a bit and check results
    import time
    time.sleep(0.5)
    
    completed = 0
    for job in jobs:
        result = skill.get_job_result(job.job_id)
        if result:
            completed += 1
    
    print(f"✓ {completed}/{len(jobs)} jobs completed")
    
    # Check queue stats
    stats = skill.get_queue_stats()
    assert stats is not None, "Should have queue stats"
    print(f"✓ Queue stats: {stats}")
    
    skill.shutdown()


def test_async_pii_propagation():
    """Test that async processing preserves PII context and sanitizes retrieval queries"""
    print("\n=== Testing Async PII Propagation ===")

    import uuid

    captured_queries = []

    skill = FactCheckingSkill(
        mode="ONLINE_ALLOWLIST",
        allowlist_version="v1",
        enable_async=True,
        async_worker_count=1
    )

    original_retrieve = skill._evidence_retriever.retrieve_evidence

    def capture_retrieve(normalized_claim: str, claim_hash: str, allowlist_version: str):
        captured_queries.append(normalized_claim)
        return [], 0, []

    skill._evidence_retriever.retrieve_evidence = capture_retrieve

    try:
        unique_claim = (
            f"Contact john+{uuid.uuid4().hex[:8]}@example.com "
            f"or call 555-123-4567 for details"
        )
        job = skill.check_fact_async(
            unique_claim,
            request_context=RequestContext(post_id="post_async_pii")
        )

        assert job.contains_pii, "Async job should preserve PII detection state"

        import time
        deadline = time.time() + 3.0
        result = None
        while time.time() < deadline:
            result = skill.get_job_result(job.job_id)
            if result is not None:
                break
            time.sleep(0.05)

        assert result is not None, "Async result should complete"
        assert result.contains_pii, "Async result should preserve contains_pii"
        assert captured_queries, "Evidence retrieval should have been called"
        assert "@" not in captured_queries[0], f"Sanitized async query still contains email: {captured_queries[0]}"
        assert "555" not in captured_queries[0], f"Sanitized async query still contains phone digits: {captured_queries[0]}"
        print("✓ Async processing preserves PII state and sanitizes the retrieval query")
    finally:
        skill._evidence_retriever.retrieve_evidence = original_retrieve
        skill.shutdown()


def test_cache_isolation_between_skill_instances():
    """Identical claims in different skill instances should not share cached verdicts."""
    print("\n=== Testing Cache Isolation Between Skill Instances ===")

    claim = "OpenAI was founded in 2015"
    skill_a = FactCheckingSkill(
        mode="ONLINE_ALLOWLIST",
        allowlist_version="v1",
        enable_async=False,
        connectors=[StaticConnector("support_a", SourceConfidence.CONFIRMS, EvidenceTier.TIER_1)],
    )
    skill_b = FactCheckingSkill(
        mode="ONLINE_ALLOWLIST",
        allowlist_version="v1",
        enable_async=False,
        connectors=[StaticConnector("refute_b", SourceConfidence.CONTRADICTS, EvidenceTier.TIER_1)],
    )

    try:
        result_a = skill_a.check_fact(claim)
        result_b = skill_b.check_fact(claim)
        assert result_a.verdict == FactCheckVerdict.SUPPORTED
        assert result_b.verdict == FactCheckVerdict.REFUTED
        print("✓ Cache keys are isolated by runtime connector/policy signature")
    finally:
        skill_a.shutdown()
        skill_b.shutdown()


def test_async_queue_isolation_between_skill_instances():
    """Async jobs should be processed by the owning skill instance only."""
    print("\n=== Testing Async Queue Isolation Between Skill Instances ===")

    claim = "OpenAI was founded in 2015"
    skill_a = FactCheckingSkill(
        mode="ONLINE_ALLOWLIST",
        allowlist_version="v1",
        enable_async=True,
        async_worker_count=1,
        connectors=[StaticConnector("async_support", SourceConfidence.CONFIRMS, EvidenceTier.TIER_1)],
    )
    skill_b = FactCheckingSkill(
        mode="ONLINE_ALLOWLIST",
        allowlist_version="v1",
        enable_async=True,
        async_worker_count=1,
        connectors=[StaticConnector("async_refute", SourceConfidence.CONTRADICTS, EvidenceTier.TIER_1)],
    )

    try:
        job_a = skill_a.check_fact_async(claim, request_context=RequestContext(post_id="queue_a"))
        job_b = skill_b.check_fact_async(claim, request_context=RequestContext(post_id="queue_b"))

        result_a = _wait_for_job(skill_a, job_a.job_id)
        result_b = _wait_for_job(skill_b, job_b.job_id)

        assert result_a is not None, "Skill A job should complete"
        assert result_b is not None, "Skill B job should complete"
        assert result_a.verdict == FactCheckVerdict.SUPPORTED
        assert result_b.verdict == FactCheckVerdict.REFUTED
        print("✓ Async jobs stay isolated to their owning skill instance")
    finally:
        skill_a.shutdown()
        skill_b.shutdown()


def test_async_shutdown_isolation_between_skill_instances():
    """Shutting down one async skill should not stop another skill's workers."""
    print("\n=== Testing Async Shutdown Isolation Between Skill Instances ===")

    skill_a = FactCheckingSkill(
        mode="ONLINE_ALLOWLIST",
        allowlist_version="v1",
        enable_async=True,
        async_worker_count=1,
        connectors=[StaticConnector("shutdown_a", SourceConfidence.CONFIRMS, EvidenceTier.TIER_1)],
    )
    skill_b = FactCheckingSkill(
        mode="ONLINE_ALLOWLIST",
        allowlist_version="v1",
        enable_async=True,
        async_worker_count=1,
        connectors=[StaticConnector("shutdown_b", SourceConfidence.CONFIRMS, EvidenceTier.TIER_1)],
    )

    try:
        skill_a.shutdown()
        job_b = skill_b.check_fact_async(
            "Toronto is in Ontario",
            request_context=RequestContext(post_id="queue_shutdown_b"),
        )
        result_b = _wait_for_job(skill_b, job_b.job_id)
        assert result_b is not None, "Remaining skill should still process jobs"
        assert result_b.verdict == FactCheckVerdict.SUPPORTED
        print("✓ Shutting down one skill does not kill another skill's queue")
    finally:
        skill_b.shutdown()


def test_tier1_unanimity_flag_changes_runtime_behavior():
    """tier1_require_unanimity should materially change adjudication behavior."""
    print("\n=== Testing Tier-1 Unanimity Policy Flag ===")

    connectors = [
        StaticConnector("tier1_confirm_a", SourceConfidence.CONFIRMS, EvidenceTier.TIER_1),
        StaticConnector("tier1_confirm_b", SourceConfidence.CONFIRMS, EvidenceTier.TIER_1),
        StaticConnector("tier1_contradict", SourceConfidence.CONTRADICTS, EvidenceTier.TIER_1),
    ]
    strict = FactCheckingSkill(
        mode="PERFECT_CHECKER",
        allowlist_version="v1",
        enable_async=False,
        connectors=connectors,
        policy=EvidencePolicy(tier1_min_sources=2, tier1_require_unanimity=True, tier2_can_resolve=False),
    )
    relaxed = FactCheckingSkill(
        mode="PERFECT_CHECKER",
        allowlist_version="v1",
        enable_async=False,
        connectors=connectors,
        policy=EvidencePolicy(tier1_min_sources=2, tier1_require_unanimity=False, tier2_can_resolve=False),
    )

    try:
        claim = "OpenAI was founded in 2015"
        strict_result = strict.check_fact(claim)
        relaxed_result = relaxed.check_fact(claim)
        assert strict_result.verdict == FactCheckVerdict.INSUFFICIENT
        assert relaxed_result.verdict == FactCheckVerdict.SUPPORTED
        print("✓ tier1_require_unanimity toggles the runtime verdict")
    finally:
        strict.shutdown()
        relaxed.shutdown()


def test_tier2_unanimity_flag_changes_runtime_behavior():
    """tier2_require_unanimity should materially change lower-tier resolution behavior."""
    print("\n=== Testing Tier-2 Unanimity Policy Flag ===")

    connectors = [
        StaticConnector("tier2_confirm_a", SourceConfidence.CONFIRMS, EvidenceTier.TIER_2),
        StaticConnector("tier2_confirm_b", SourceConfidence.CONFIRMS, EvidenceTier.TIER_2),
        StaticConnector("tier2_contradict", SourceConfidence.CONTRADICTS, EvidenceTier.TIER_2),
    ]
    strict = FactCheckingSkill(
        mode="PERFECT_CHECKER",
        allowlist_version="v1",
        enable_async=False,
        connectors=connectors,
        policy=EvidencePolicy(
            tier2_can_resolve=True,
            tier2_min_sources=2,
            tier2_require_unanimity=True,
            strict_mode=False,
        ),
    )
    relaxed = FactCheckingSkill(
        mode="PERFECT_CHECKER",
        allowlist_version="v1",
        enable_async=False,
        connectors=connectors,
        policy=EvidencePolicy(
            tier2_can_resolve=True,
            tier2_min_sources=2,
            tier2_require_unanimity=False,
            strict_mode=False,
        ),
    )

    try:
        claim = "OpenAI was founded in 2015"
        strict_result = strict.check_fact(claim)
        relaxed_result = relaxed.check_fact(claim)
        assert strict_result.verdict == FactCheckVerdict.INSUFFICIENT
        assert relaxed_result.verdict == FactCheckVerdict.SUPPORTED
        print("✓ tier2_require_unanimity toggles the runtime verdict")
    finally:
        strict.shutdown()
        relaxed.shutdown()


def test_ground_truth_sufficient_flag_changes_runtime_behavior():
    """ground_truth_sufficient should determine whether one curated entry is decisive."""
    print("\n=== Testing Ground-Truth Sufficiency Policy Flag ===")

    claim = "OpenAI was founded in 2015"
    from skills.fact_checking.normalization import ClaimNormalizer
    normalized = ClaimNormalizer.normalize(claim)
    claim_hash = ClaimNormalizer.compute_hash(normalized)

    with tempfile.TemporaryDirectory() as temp_dir:
        db = GroundTruthDB(os.path.join(temp_dir, "ground_truth.json"))
        db.store(
            claim_hash=claim_hash,
            verdict="SUPPORTED",
            p_true=1.0,
            operationalization="Check the recorded inception date.",
            tier_counts={"TIER_1": 1, "TIER_2": 0, "TIER_3": 0},
            evidence=[{
                "source_url": "https://www.wikidata.org/wiki/Q24283660",
                "source_id": "ground_truth_openai",
                "source_title": "OpenAI ground truth",
                "snippet": "OpenAI inception year is 2015.",
            }],
            reviewed_by="reviewer@example.com",
            review_rationale="Curated historical record.",
        )

        sufficient = FactCheckingSkill(
            mode="PERFECT",
            allowlist_version="v1",
            enable_async=False,
            connectors=[],
            ground_truth_db=db,
            policy=EvidencePolicy(
                ground_truth_sufficient=True,
                tier1_require_second_source=True,
                tier2_can_resolve=False,
            ),
        )
        insufficient = FactCheckingSkill(
            mode="PERFECT",
            allowlist_version="v1",
            enable_async=False,
            connectors=[],
            ground_truth_db=db,
            policy=EvidencePolicy(
                ground_truth_sufficient=False,
                tier1_require_second_source=True,
                tier2_can_resolve=False,
            ),
        )

        try:
            sufficient_result = sufficient.check_fact(claim)
            insufficient_result = insufficient.check_fact(claim)
            assert sufficient_result.verdict == FactCheckVerdict.SUPPORTED
            assert insufficient_result.verdict == FactCheckVerdict.INSUFFICIENT
            print("✓ ground_truth_sufficient toggles whether one curated entry resolves")
        finally:
            sufficient.shutdown()
            insufficient.shutdown()


def test_ground_truth_legacy_rows_load_safely_and_preserve_mode_label():
    """Legacy ground-truth rows should not crash and should preserve caller mode labels."""
    print("\n=== Testing Ground-Truth Legacy Compatibility ===")

    claim = "Albert Einstein died in 1955"
    from skills.fact_checking.normalization import ClaimNormalizer
    claim_hash = ClaimNormalizer.compute_hash(ClaimNormalizer.normalize(claim))

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "legacy_ground_truth.json")
        with open(db_path, "w", encoding="utf-8") as handle:
            json.dump({
                claim_hash: {
                    "verdict": "SUPPORTED",
                    "p_true": 1.0,
                    "operationalization": "Check the death-year record.",
                    "tier_counts": {"TIER_1": 1, "TIER_2": 0, "TIER_3": 0},
                    "evidence": [{
                        "source_id": "legacy_einstein",
                        "source_title": "Legacy Einstein row",
                        "snippet": "Albert Einstein died in 1955."
                    }],
                    "stored_at": "2025-01-01T00:00:00Z",
                }
            }, handle)

        db = GroundTruthDB(db_path)
        checker = FactCheckingSkill(
            mode="PERFECT_CHECKER",
            allowlist_version="v1",
            enable_async=False,
            connectors=[],
            ground_truth_db=db,
        )
        try:
            result = checker.check_fact(claim)
            assert result.verdict == FactCheckVerdict.SUPPORTED
            assert result.fact_mode == "PERFECT_CHECKER"
            assert result.evidence and result.evidence[0].retrieved_at is not None
            print("✓ Legacy ground-truth rows load safely and preserve the caller mode")
        finally:
            checker.shutdown()


def test_empty_and_malformed_ground_truth_files_degrade_to_empty_store():
    """Empty or malformed ground-truth files should degrade safely."""
    print("\n=== Testing Empty/Malformed Ground-Truth Files ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        empty_path = os.path.join(temp_dir, "empty_ground_truth.json")
        malformed_path = os.path.join(temp_dir, "malformed_ground_truth.json")

        with open(empty_path, "w", encoding="utf-8") as handle:
            handle.write("")
        with open(malformed_path, "w", encoding="utf-8") as handle:
            handle.write("{not valid json")

        assert GroundTruthDB(empty_path).lookup("missing") is None
        assert GroundTruthDB(malformed_path).lookup("missing") is None
        print("✓ Empty and malformed ground-truth stores degrade to empty state")


def test_claim_decomposition_and_planner_diagnostics():
    """Compound unsupported claims should decompose deterministically and route honestly."""
    print("\n=== Testing Claim Decomposition And Planner Diagnostics ===")

    subclaims = ClaimDecomposer.decompose("GDP rose and unemployment fell in Canada in 2024")
    assert len(subclaims) == 2, f"Expected 2 subclaims, got {len(subclaims)}"
    assert subclaims[0].normalized_claim_text == "gdp rose in canada in 2024"
    assert subclaims[1].normalized_claim_text == "unemployment fell in canada in 2024"

    decisions = ConnectorPlanner.plan_claim(subclaims, [WikidataConnector()], mode="PERFECT")
    assert all(decision.reason_code == "unsupported_claim_family" for decision in decisions)
    print("✓ Compound unsupported claims decompose deterministically and route to INSUFFICIENT")


def test_gold_fixture_schema_and_coverage():
    """The gold fixture should satisfy the minimum schema and coverage targets."""
    print("\n=== Testing Gold Fixture Schema And Coverage ===")

    cases = _load_gold_cases()
    assert 50 <= len(cases) <= 100, f"Expected 50-100 cases, got {len(cases)}"

    required_fields = {
        "id", "claim_text", "expected_verdict", "claim_family",
        "authoritative_source_type", "temporal", "scoped", "compound", "notes",
    }
    verdict_counts = {"SUPPORTED": 0, "REFUTED": 0, "INSUFFICIENT": 0}
    temporal_count = 0
    scoped_count = 0
    compound_count = 0

    for case in cases:
        assert required_fields.issubset(case.keys()), f"Missing fields in {case}"
        verdict_counts[case["expected_verdict"]] += 1
        temporal_count += int(bool(case["temporal"]))
        scoped_count += int(bool(case["scoped"]))
        compound_count += int(bool(case["compound"]))

    assert verdict_counts["SUPPORTED"] >= 15
    assert verdict_counts["REFUTED"] >= 15
    assert verdict_counts["INSUFFICIENT"] >= 15
    assert temporal_count >= 10
    assert scoped_count >= 10
    assert compound_count >= 10
    print("✓ Gold fixture meets schema and coverage targets")


def test_wikidata_connector_and_perfect_mode_resolution():
    """PERFECT should resolve the supported family and reject unsupported families."""
    print("\n=== Testing Wikidata Connector And PERFECT Mode ===")

    skill = FactCheckingSkill(
        mode="PERFECT",
        allowlist_version="v1",
        enable_async=False,
        connectors=[WikidataConnector()],
    )
    try:
        supported = skill.check_fact("OpenAI was founded in 2015")
        refuted = skill.check_fact("OpenAI was founded in 2014")
        unsupported = skill.check_fact("GDP rose in Canada in 2024")
        compound = skill.check_fact("OpenAI was founded in 2015 and Toronto is in Ontario")

        assert supported.verdict == FactCheckVerdict.SUPPORTED
        assert refuted.verdict == FactCheckVerdict.REFUTED
        assert unsupported.verdict == FactCheckVerdict.INSUFFICIENT
        assert unsupported.diagnostics.get("reason_code") == "unsupported_claim_family"
        assert compound.verdict == FactCheckVerdict.INSUFFICIENT
        assert compound.diagnostics.get("reason_code") == "compound_claim"
        print("✓ PERFECT resolves the supported family and rejects unsupported/compound claims honestly")
    finally:
        skill.shutdown()

def test_lsd_requirements():
    """Verify compliance with Large Scale Discussion requirements"""
    print("\n=== Verifying LSD Requirements ===")

    from backend.models import (
        Debate, Post, Topic, CanonicalFact, Snapshot,
        Side, ModulationOutcome
    )
    from backend.debate_engine_v2 import DebateEngineV2
    
    # Test debate creation
    engine = DebateEngineV2(fact_check_mode="OFFLINE")
    debate = engine.create_debate(
        motion="Should advanced AI development be paused?",
        moderation_criteria=(
            "Allow evidence-backed arguments about governance and safety. Block harassment, "
            "spam, PII, and off-topic content."
        ),
        debate_frame=(
            "Judge which side best informs a neutral policymaker balancing safety, innovation, "
            "and enforceability."
        ),
    )
    assert debate['debate_id'], "Debate should have ID"
    print("✓ Debate creation works")
    
    # Test post submission
    post = engine.submit_post(
        debate_id=debate['debate_id'],
        side="FOR",
        topic_id="t1",
        facts="AI systems can be used to generate convincing misinformation.",
        inference="Therefore, development should be paused until safeguards exist."
    )
    assert post['post_id'], "Post should have ID"
    assert post['modulation_outcome'] == ModulationOutcome.ALLOWED.value, "Post should be allowed"
    print("✓ Post submission and modulation works")
    
    # Test snapshot generation
    snapshot = engine.generate_snapshot(debate['debate_id'])
    assert snapshot['snapshot_id'], "Snapshot should have ID"
    assert snapshot['verdict'] in ["FOR", "AGAINST", "NO VERDICT"], "Should have valid verdict"
    assert 0.0 <= snapshot['confidence'] <= 1.0, "Confidence should be in [0,1]"
    print(f"✓ Snapshot generation works: verdict={snapshot['verdict']}, confidence={snapshot['confidence']}")
    
    # Test fact check stats
    stats = engine.get_fact_check_stats()
    assert 'cache' in stats, "Should have cache stats"
    assert 'mode' in stats, "Should have mode info"
    print(f"✓ Fact check stats available: mode={stats['mode']}")
    
    engine.shutdown()


def test_temporal_claims():
    """Test temporal claim handling"""
    print("\n=== Testing Temporal Claims ===")
    
    from datetime import datetime, timedelta
    
    # Create expired temporal context
    expired_temporal = TemporalContext(
        is_temporal=True,
        observation_date=datetime.now() - timedelta(days=100),
        expiration_policy="30_DAYS"
    )
    
    assert expired_temporal.is_expired(), "Should detect expired claim"
    print("✓ Expired temporal claim detection works")
    
    # Create non-expired temporal context
    valid_temporal = TemporalContext(
        is_temporal=True,
        observation_date=datetime.now() - timedelta(days=10),
        expiration_policy="30_DAYS"
    )
    
    assert not valid_temporal.is_expired(), "Should not flag valid claim as expired"
    print("✓ Valid temporal claim passes")


def test_audit_logging():
    """Test audit logging"""
    print("\n=== Testing Audit Logging ===")
    
    skill = FactCheckingSkill(mode="OFFLINE", allowlist_version="v1")
    
    # Perform some fact checks
    for i in range(3):
        skill.check_fact(
            f"Audit test claim {i}",
            request_context=RequestContext(
                post_id=f"post_{i}",
                submission_id="sub_001"
            )
        )
    
    # Check audit stats
    stats = skill.get_audit_stats()
    assert stats['total_entries'] >= 3, f"Should have at least 3 audit entries, got {stats['total_entries']}"
    print(f"✓ Audit logging works: {stats['total_entries']} entries")
    
    skill.shutdown()


class FailingConnector:
    """Connector that always raises, for testing failure visibility."""

    def __init__(self, source_id: str):
        self._source_id = source_id

    @property
    def source_id(self) -> str:
        return self._source_id

    def query(self, normalized_claim: str, claim_hash: str):
        raise RuntimeError(f"{self._source_id} is down")


def test_connector_failure_is_visible():
    """Connector exceptions must surface in diagnostics, not vanish silently."""
    print("\n=== Testing Connector Failure Visibility ===")
    import os
    for db in (".fact_check_cache.db", ".fact_check_audit.db"):
        if os.path.exists(db):
            os.remove(db)
    skill = FactCheckingSkill(
        mode="ONLINE_ALLOWLIST",
        allowlist_version="v1",
        enable_async=False,
        connectors=[
            FailingConnector("fail_source"),
            StaticConnector("ok_source", SourceConfidence.CONFIRMS, EvidenceTier.TIER_1),
        ],
    )
    result = skill.check_fact("OpenAI was founded in 2015")
    assert "connector_errors" in result.diagnostics, "Diagnostics should record connector failures"
    assert any("fail_source" in err for err in result.diagnostics["connector_errors"]), (
        "Error message should name the failing connector"
    )
    print("✓ Connector failures are visible in diagnostics")


def test_empty_decisions_diagnostics():
    """_build_diagnostics must tolerate an empty decisions list."""
    print("\n=== Testing Empty Decisions Diagnostics ===")
    skill = FactCheckingSkill(mode="OFFLINE", enable_async=False)
    diagnostics = skill._build_diagnostics([], [], "OFFLINE")
    assert diagnostics["connector_path"] == []
    assert diagnostics["reason_code"] == "no_planner_decision"
    assert diagnostics["claim_truncated"] is False
    print("✓ Empty decisions produce safe diagnostic defaults")


def test_memory_cache_returns_copy():
    """MemoryCache.get() must return a deep copy to prevent cache corruption."""
    print("\n=== Testing Memory Cache Returns Copy ===")
    from skills.fact_checking.cache import MemoryCache
    from skills.fact_checking.models import FactCheckResult, FactCheckStatus, FactCheckVerdict

    cache = MemoryCache(max_size=10)
    original = FactCheckResult(
        claim_text="original",
        normalized_claim_text="original",
        claim_hash="abc",
        fact_mode="OFFLINE",
        allowlist_version="v1",
        status=FactCheckStatus.UNVERIFIED_OFFLINE,
        verdict=FactCheckVerdict.UNVERIFIED,
        factuality_score=0.5,
        confidence=0.0,
        confidence_explanation="test",
    )
    cache.set("key", original, ttl_seconds=3600)

    fetched = cache.get("key")
    assert fetched is not None
    fetched.claim_text = "mutated"

    fetched_again = cache.get("key")
    assert fetched_again.claim_text == "original", "Cache entry was corrupted by caller mutation"
    print("✓ Memory cache returns independent copies")


def test_claim_truncation_diagnostic():
    """Oversized claims must set claim_truncated=True in diagnostics."""
    print("\n=== Testing Claim Truncation Diagnostic ===")
    import os
    for db in (".fact_check_cache.db", ".fact_check_audit.db"):
        if os.path.exists(db):
            os.remove(db)
    from skills.fact_checking.config import FactCheckConfig

    config = FactCheckConfig(max_claim_length=10)
    skill = FactCheckingSkill(mode="OFFLINE", enable_async=False, config=config)
    result = skill.check_fact("This claim is way too long")
    assert result.diagnostics.get("claim_truncated") is True, (
        "Diagnostics should flag truncated claims"
    )
    assert len(result.claim_text) <= 10
    print("✓ Claim truncation is flagged in diagnostics")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("Fact Checking Skill Test Suite")
    print("=" * 60)
    
    tests = [
        test_offline_mode,
        test_normalization,
        test_cache,
        test_pii_detection,
        test_online_allowlist_simulation,
        test_verdict_thresholds,
        test_async_processing,
        test_async_pii_propagation,
        test_cache_isolation_between_skill_instances,
        test_async_queue_isolation_between_skill_instances,
        test_async_shutdown_isolation_between_skill_instances,
        test_tier1_unanimity_flag_changes_runtime_behavior,
        test_tier2_unanimity_flag_changes_runtime_behavior,
        test_ground_truth_sufficient_flag_changes_runtime_behavior,
        test_ground_truth_legacy_rows_load_safely_and_preserve_mode_label,
        test_empty_and_malformed_ground_truth_files_degrade_to_empty_store,
        test_claim_decomposition_and_planner_diagnostics,
        test_gold_fixture_schema_and_coverage,
        test_wikidata_connector_and_perfect_mode_resolution,
        test_lsd_requirements,
        test_temporal_claims,
        test_audit_logging,
        test_connector_failure_is_visible,
        test_empty_decisions_diagnostics,
        test_memory_cache_returns_copy,
        test_claim_truncation_diagnostic,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
