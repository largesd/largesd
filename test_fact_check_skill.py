"""
Test script for the Fact Checking Skill
Verifies compliance with both:
- Fact Checking Skill Design Specification
- Medium Scale Discussion requirements
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'skills', 'fact_checking'))

from skills.fact_checking import (
    FactCheckingSkill,
    FactCheckVerdict,
    FactCheckStatus,
    RequestContext,
    TemporalContext,
)


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
    
    # Test CONTRADICTED
    verdict = skill._determine_verdict(0.20, 0.75)
    assert verdict == FactCheckVerdict.CONTRADICTED, f"Expected CONTRADICTED, got {verdict}"
    print("✓ CONTRADICTED verdict works")
    
    # Test MIXED
    verdict = skill._determine_verdict(0.50, 0.50)
    assert verdict == FactCheckVerdict.MIXED, f"Expected MIXED, got {verdict}"
    print("✓ MIXED verdict works")
    
    # Test INSUFFICIENT_EVIDENCE
    verdict = skill._determine_verdict(0.10, 0.10)
    assert verdict == FactCheckVerdict.INSUFFICIENT_EVIDENCE, f"Expected INSUFFICIENT_EVIDENCE, got {verdict}"
    print("✓ INSUFFICIENT_EVIDENCE verdict works")


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
        assert status in ["queued", "processing"], f"Job should be queued or processing, got {status}"
    print("✓ Jobs are queued/processing")
    
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

    from skills.fact_checking.queue import reset_global_queue
    import uuid

    reset_global_queue()

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
        return [], 0

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
        reset_global_queue()


def test_msd_requirements():
    """Verify compliance with Medium Scale Discussion requirements"""
    print("\n=== Verifying MSD Requirements ===")
    
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
    from models import (
        Debate, Post, Topic, CanonicalFact, Snapshot,
        Side, ModulationOutcome
    )
    from debate_engine import DebateEngine
    
    # Test debate creation
    engine = DebateEngine(fact_check_mode="OFFLINE")
    debate = engine.create_debate(
        resolution="Should advanced AI development be paused?",
        scope="Discussion of AI governance and safety"
    )
    assert debate.debate_id, "Debate should have ID"
    print("✓ Debate creation works")
    
    # Test post submission
    post = engine.submit_post(
        debate_id=debate.debate_id,
        side="FOR",
        topic_id="t1",
        facts="AI systems can be used to generate convincing misinformation.",
        inference="Therefore, development should be paused until safeguards exist."
    )
    assert post.post_id, "Post should have ID"
    assert post.modulation_outcome == ModulationOutcome.ALLOWED, "Post should be allowed"
    print("✓ Post submission and modulation works")
    
    # Test snapshot generation
    snapshot = engine.generate_snapshot(debate.debate_id)
    assert snapshot.snapshot_id, "Snapshot should have ID"
    assert snapshot.verdict in ["FOR", "AGAINST", "NO VERDICT"], "Should have valid verdict"
    assert 0.0 <= snapshot.confidence <= 1.0, "Confidence should be in [0,1]"
    print(f"✓ Snapshot generation works: verdict={snapshot.verdict}, confidence={snapshot.confidence}")
    
    # Check that facts have P(true) values
    for topic_id, facts in snapshot.canonical_facts.items():
        for fact in facts:
            assert 0.0 <= fact.p_true <= 1.0, f"Fact {fact.canon_fact_id} should have valid P(true)"
    print("✓ All facts have P(true) values from fact checker")
    
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
        test_msd_requirements,
        test_temporal_claims,
        test_audit_logging,
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
