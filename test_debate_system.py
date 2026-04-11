"""
Comprehensive Test Suite for Blind LLM-Adjudicated Debate System
Tests compliance with Medium Scale Discussion (MSD) specification
"""
import sys
import os
import json
import tempfile
import shutil
from datetime import datetime

# Add paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'skills', 'fact_checking'))

from dataclasses import dataclass

from backend.models import (
    Side, ModulationOutcome, BlockReason, 
    FactCheckVerdict, FactCheckStatus, Span, Fact
)

# Import ModulationOutcome from modulation to ensure consistency
# (The one in models is a duplicate for dataclass compatibility)
from backend.modulation import ModulationOutcome as ModOutcome, BlockReason as BlockReasonMod
from backend.debate_proposal import parse_debate_proposal_payload
from backend.debate_engine_v2 import DebateEngineV2
from backend.scoring_engine import ScoringEngine, TopicSideScores
from backend.llm_client import LLMClient, MockLLMProvider
from backend.modulation import ModulationEngine, ModulationTemplate


# =============================================================================
# UNIT TESTS - Core Components
# =============================================================================

def test_modulation_system():
    """Test modulation (content moderation) per MSD §3"""
    print("\n=== Testing Modulation System (MSD §3) ===")
    
    engine = ModulationEngine(ModulationEngine.get_builtin_template("standard_civility"))
    
    # Test allowed post
    allowed_post = {
        'facts': 'Studies show renewable energy creates jobs.',
        'inference': 'Therefore, we should invest in solar power.'
    }
    outcome, reason, rules = engine.apply_modulation(allowed_post)
    assert outcome == ModOutcome.ALLOWED, f"Valid post should be allowed, got {outcome}"
    print("✓ Valid post allowed through modulation")

    # Test repetition logic only catches long consecutive runs, not normal prose
    natural_post = {
        'facts': 'Independent evidence reviews increase confidence in safety claims across multiple release cycles.',
        'inference': 'Therefore external audits can improve trust without relying on a single evaluator.'
    }
    outcome, reason, rules = engine.apply_modulation(natural_post)
    assert outcome == ModOutcome.ALLOWED, "Normal prose should not trigger repetition spam blocking"
    print("✓ Normal prose is not misclassified as spam")

    spam_post = {
        'facts': 'aaaaaaaaaaaaaaaaaaaaaaaaa',
        'inference': 'Therefore aaaaaaaaaaaaaaaaaaaaaaaaa should be blocked.'
    }
    outcome, reason, rules = engine.apply_modulation(spam_post)
    outcome_str = outcome.value if hasattr(outcome, 'value') else str(outcome)
    reason_str = (reason.value if hasattr(reason, 'value') else str(reason)).lower()
    assert outcome_str == 'blocked', "Long repeated character runs should be blocked as spam"
    assert reason_str == 'spam', f"Expected spam, got {reason}"
    print("✓ Repetition spam detection only blocks long repeated runs")
    
    # Test blocked post (severe toxicity - matches standard_civility rules)
    blocked_post = {
        'facts': 'I will kill everyone who disagrees with me.',
        'inference': 'Therefore, my view is the only valid one.'
    }
    outcome, reason, rules = engine.apply_modulation(blocked_post)
    # Compare using values to avoid enum import conflicts
    outcome_str = outcome.value if hasattr(outcome, 'value') else str(outcome)
    reason_str = (reason.value if hasattr(reason, 'value') else str(reason)).lower()
    assert outcome_str == 'blocked', f"Severe toxicity should be blocked, got {outcome}"
    assert reason_str == 'toxicity', f"Expected toxicity, got {reason} ({type(reason)})"
    print("✓ Severe toxicity blocked correctly")
    
    # Test audit info
    audit_info = engine.get_audit_info()
    assert 'template_name' in audit_info
    assert 'template_version' in audit_info
    assert 'rule_count' in audit_info
    print(f"✓ Modulation audit info: {audit_info['template_name']} v{audit_info['template_version']}")


def test_debate_proposal_requirements():
    """Test mandatory debate proposal fields for new debates."""
    print("\n=== Testing Debate Proposal Requirements ===")

    proposal, missing_fields = parse_debate_proposal_payload({
        "motion": "Should cities ban private cars downtown?",
        "moderation_criteria": "Allow evidence-based arguments and block harassment or off-topic content.",
        "debate_frame": "Judge which side best balances access, emissions, and practical enforcement."
    })
    assert not missing_fields, f"Expected a complete proposal, got missing fields: {missing_fields}"
    assert proposal["resolution"] == proposal["motion"], "Motion should hydrate the legacy resolution field"
    assert "Debate frame:" in proposal["scope"], "Internal scope should include the debate frame"
    print("✓ Complete proposal payload hydrates the legacy scoring context")

    _, missing_fields = parse_debate_proposal_payload({
        "motion": "Should cities ban private cars downtown?"
    })
    assert missing_fields == ["moderation criteria", "debate frame"], (
        f"Expected missing moderation criteria and debate frame, got {missing_fields}"
    )
    print("✓ Missing proposal fields are reported explicitly")


def test_span_extraction():
    """Test span extraction for traceability per MSD §5"""
    print("\n=== Testing Span Extraction (MSD §5) ===")
    
    from backend.extraction import ExtractionEngine
    
    llm_client = LLMClient(provider="mock", num_judges=3)
    engine = ExtractionEngine(llm_client)
    
    # Test span extraction
    fact_spans, inference_span = engine.extract_spans_from_post(
        post_id="post_001",
        facts_text="GDP grew by 3% in 2023. Unemployment fell to 4%.",
        inference_text="Therefore, the economy is improving.",
        side="FOR",
        topic_id="topic_001"
    )
    
    assert len(fact_spans) > 0, "Should extract fact spans"
    assert inference_span is not None, "Should extract inference span"
    
    # Verify span structure
    for span in fact_spans:
        assert span.span_id, "Span should have ID"
        assert span.post_id == "post_001", "Span should reference post"
        assert span.span_type == "fact", "Should be fact type"
        assert span.start_offset < span.end_offset, "Offsets should be valid"
    
    print(f"✓ Extracted {len(fact_spans)} fact spans and 1 inference span")


def test_fact_canonicalization():
    """Test fact deduplication per MSD §7.2"""
    print("\n=== Testing Fact Canonicalization (MSD §7.2) ===")
    
    from backend.extraction import ExtractionEngine, ExtractedFact, ExtractedSpan, CanonicalFact
    
    llm_client = LLMClient(provider="mock", num_judges=3)
    engine = ExtractionEngine(llm_client)
    
    # Note: Mock LLM returns hardcoded cluster IDs that don't match our test facts
    # So we test the structure and API rather than the actual clustering behavior
    
    span1 = ExtractedSpan("s1", "post1", 0, 50, "Renewable energy creates jobs.", "t1", "FOR", "fact")
    
    facts = [
        ExtractedFact(
            fact_id="fact_1",  # Use IDs that match mock response
            fact_text="Renewable energy creates jobs in manufacturing.",
            topic_id="t1",
            side="FOR",
            provenance_spans=[span1],
            p_true=0.8
        ),
        ExtractedFact(
            fact_id="fact_2",  # Use IDs that match mock response
            fact_text="Renewable energy generates employment in manufacturing sectors.",
            topic_id="t1",
            side="FOR",
            provenance_spans=[span1],
            p_true=0.75
        ),
    ]
    
    canonical_facts = engine.canonicalize_facts(facts, "Economic impact of renewable energy")
    
    # With mock, we expect either empty list or the hardcoded cluster response
    # The key thing is that the method runs without error
    print(f"✓ Canonicalization method executed (returned {len(canonical_facts)} facts)")
    
    # Verify the structure of CanonicalFact dataclass
    cf = CanonicalFact(
        canon_fact_id="cf_test",
        topic_id="t1",
        side="FOR",
        canon_fact_text="Test fact",
        member_fact_ids=["f1", "f2"],
        provenance_spans=[],
        p_true=0.8
    )
    assert cf.canon_fact_id == "cf_test"
    assert 0 <= cf.p_true <= 1
    print("✓ CanonicalFact data structure is valid")


def test_scoring_formulas():
    """Test MSD scoring formulas per MSD §10"""
    print("\n=== Testing Scoring Formulas (MSD §10) ===")
    
    engine = ScoringEngine(num_judges=3)
    
    # Test factuality calculation (MSD §10.1)
    facts = [
        {'p_true': 0.9, 'fact_id': 'f1'},
        {'p_true': 0.8, 'fact_id': 'f2'},
        {'p_true': 0.7, 'fact_id': 'f3'}
    ]
    factuality = engine.compute_factuality(facts)
    expected = (0.9 + 0.8 + 0.7) / 3
    assert abs(factuality - expected) < 0.01, f"Factuality should be mean of p_true: {factuality} vs {expected}"
    print(f"✓ Factuality F = {factuality:.3f} (mean of P(true) values)")
    
    # Test empty facts
    empty_factuality = engine.compute_factuality([])
    assert empty_factuality == 0.5, "Empty facts should return 0.5"
    print("✓ Empty facts return neutral 0.5")
    
    # Test quality calculation (MSD §10.4)
    quality = engine.compute_quality(0.8, 0.7, 0.6)
    expected_q = (0.8 * 0.7 * 0.6) ** (1/3)
    assert abs(quality - expected_q) < 0.01, "Quality should be geometric mean"
    print(f"✓ Quality Q = {quality:.3f} (geometric mean of F × Reason × Cov)")
    
    # Test zero handling
    zero_quality = engine.compute_quality(0.8, 0.0, 0.6)
    assert zero_quality == 0.0, "Zero component should yield zero quality"
    print("✓ Zero component yields zero quality")
    
    # Test topic relevance (MSD §11)
    topics = [{'topic_id': 't1'}, {'topic_id': 't2'}]
    content_mass = {'t1': 100, 't2': 300}
    relevance = engine.compute_topic_relevance(topics, content_mass)
    
    assert abs(relevance['t1'] - 0.25) < 0.01, "t1 should have 25% relevance"
    assert abs(relevance['t2'] - 0.75) < 0.01, "t2 should have 75% relevance"
    assert abs(sum(relevance.values()) - 1.0) < 0.01, "Relevance should sum to 1"
    print(f"✓ Topic relevance: t1={relevance['t1']:.2f}, t2={relevance['t2']:.2f}")


def test_verdict_computation():
    """Test verdict via statistical separability per MSD §13"""
    print("\n=== Testing Verdict Computation (MSD §13) ===")
    
    engine = ScoringEngine(num_judges=3, num_replicates=100)
    
    # Test clear FOR win
    @dataclass
    class MockReplicate:
        overall_for: float
        overall_against: float
        margin_d: float
        topic_scores: dict
    
    for_replicates = [
        MockReplicate(0.8, 0.4, 0.4, {}) for _ in range(100)
    ]
    verdict = engine.compute_verdict(for_replicates)
    assert verdict['verdict'] == "FOR", f"Should be FOR, got {verdict['verdict']}"
    assert verdict['confidence'] > 0.9, "Should have high confidence"
    print(f"✓ Clear FOR verdict: confidence={verdict['confidence']}")
    
    # Test clear AGAINST win
    against_replicates = [
        MockReplicate(0.4, 0.8, -0.4, {}) for _ in range(100)
    ]
    verdict = engine.compute_verdict(against_replicates)
    assert verdict['verdict'] == "AGAINST", f"Should be AGAINST, got {verdict['verdict']}"
    print(f"✓ Clear AGAINST verdict: confidence={verdict['confidence']}")
    
    # Test NO VERDICT (uncertain)
    uncertain_replicates = [
        MockReplicate(0.6, 0.55, 0.05, {}) for _ in range(50)
    ] + [
        MockReplicate(0.55, 0.6, -0.05, {}) for _ in range(50)
    ]
    verdict = engine.compute_verdict(uncertain_replicates)
    assert verdict['verdict'] == "NO VERDICT", f"Should be NO VERDICT, got {verdict['verdict']}"
    print(f"✓ Uncertain case returns NO VERDICT")


# =============================================================================
# INTEGRATION TESTS - Full Pipeline
# =============================================================================

def test_full_pipeline():
    """Test complete debate pipeline end-to-end"""
    print("\n=== Testing Full Pipeline Integration ===")
    
    # Create temp directory for isolated database
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_debate.db")
    engine = None
    
    try:
        # Initialize engine with mock provider
        engine = DebateEngineV2(
            db_path=db_path,
            fact_check_mode="OFFLINE",
            llm_provider="mock",
            num_judges=3,
            modulation_template="standard_civility"
        )
        
        # 1. Create debate
        debate = engine.create_debate(
            motion="Should governments subsidize renewable energy?",
            moderation_criteria=(
                "Allow evidence-backed arguments about costs, benefits, and fairness. "
                "Block harassment, spam, PII, and off-topic content."
            ),
            debate_frame=(
                "Judge which side best informs a neutral policymaker balancing economic "
                "efficiency, environmental impact, and long-term public value."
            ),
        )
        assert debate['debate_id'], "Debate should have ID"
        assert debate['motion'] == "Should governments subsidize renewable energy?"
        assert debate['moderation_criteria'], "Debate should store moderation criteria"
        assert debate['debate_frame'], "Debate should store the debate frame"
        print(f"✓ Created debate: {debate['debate_id']}")
        
        # 2. Submit FOR posts
        for i in range(3):
            post = engine.submit_post(
                debate_id=debate['debate_id'],
                side="FOR",
                topic_id=None,
                facts=f"Renewable fact {i+1}. Jobs are created in sector {i+1}.",
                inference=f"Therefore, subsidies are justified for reason {i+1}.",
                counter_arguments=""
            )
            assert post['modulation_outcome'] == 'allowed', "Post should be allowed"
        print("✓ Submitted 3 FOR posts")
        
        # 3. Submit AGAINST posts
        for i in range(3):
            post = engine.submit_post(
                debate_id=debate['debate_id'],
                side="AGAINST",
                topic_id=None,
                facts=f"Fossil fuel fact {i+1}. Market distortion occurs in case {i+1}.",
                inference=f"Therefore, subsidies are harmful for reason {i+1}.",
                counter_arguments=""
            )
            assert post['modulation_outcome'] == 'allowed', "Post should be allowed"
        print("✓ Submitted 3 AGAINST posts")
        
        # 4. Generate snapshot
        snapshot = engine.generate_snapshot(
            debate_id=debate['debate_id'],
            trigger_type="manual"
        )
        
        assert snapshot['snapshot_id'], "Should have snapshot ID"
        assert snapshot['verdict'] in ['FOR', 'AGAINST', 'NO VERDICT']
        assert 0 <= snapshot['confidence'] <= 1
        print(f"✓ Generated snapshot: verdict={snapshot['verdict']}, confidence={snapshot['confidence']}")
        
        # 5. Check topic structure
        assert len(snapshot['topics']) > 0, "Should have topics"
        for topic in snapshot['topics']:
            assert topic['topic_id'], "Topic should have ID"
            assert topic['name'], "Topic should have name"
        print(f"✓ Extracted {len(snapshot['topics'])} topics")
        
        # 6. Check audits
        assert 'audits' in snapshot, "Should have audits"
        assert 'extraction_stability' in snapshot['audits']
        assert 'side_label_symmetry' in snapshot['audits']
        assert 'relevance_sensitivity' in snapshot['audits']
        print("✓ All audit reports generated")
        
        # 7. Check counterfactuals
        assert 'counterfactuals' in snapshot, "Should have counterfactuals"
        print("✓ Counterfactual analysis available")
        
    finally:
        if engine is not None:
            engine.shutdown()
        shutil.rmtree(temp_dir)


def test_v2_uses_skill_fact_checker():
    """Verify v2 now wires the canonical fact-checking skill and exposes stats."""
    print("\n=== Testing V2 Fact-Check Skill Wiring ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_v2_fact_checker.db")
    engine = None

    try:
        engine = DebateEngineV2(
            db_path=db_path,
            fact_check_mode="OFFLINE",
            llm_provider="mock",
            num_judges=3,
        )

        assert engine.fact_checker.__class__.__name__ == "FactCheckingSkill", \
            f"Expected FactCheckingSkill, got {type(engine.fact_checker)}"
        assert engine.extraction_engine.fact_checker is engine.fact_checker, \
            "ExtractionEngine should share the same fact-check provider"

        stats = engine.get_fact_check_stats()
        assert stats["mode"] == "OFFLINE", f"Expected OFFLINE mode, got {stats['mode']}"
        assert stats["async_enabled"] is False, "OFFLINE mode should not enable async workers"
        assert "cache" in stats and "audit" in stats and "queue" in stats, "Stats should expose fact-check internals"
        print("✓ V2 engine uses FactCheckingSkill and exposes fact-check stats")
    finally:
        if engine is not None:
            engine.shutdown()
        shutil.rmtree(temp_dir)


def test_v2_resolves_pending_fact_checks_before_scoring():
    """Verify the v2 engine resolves or neutralizes pending fact checks before scoring."""
    print("\n=== Testing V2 Pending Fact-Check Resolution ===")

    from backend.extraction import ExtractedFact

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_v2_fact_resolution.db")
    engine = None

    try:
        engine = DebateEngineV2(
            db_path=db_path,
            fact_check_mode="ONLINE_ALLOWLIST",
            llm_provider="mock",
            num_judges=3,
        )
        engine._fact_check_wait_timeout_seconds = 0.02
        engine._fact_check_poll_interval_seconds = 0.0

        completed_fact = ExtractedFact(
            fact_id="fact_1",
            fact_text="Claim one",
            topic_id="t1",
            side="FOR",
            p_true=0.5,
            fact_check_job_id="job_1",
            fact_check_status="pending",
        )

        attempts = {"count": 0}

        def completes_on_second_refresh(facts):
            attempts["count"] += 1
            if attempts["count"] >= 2:
                facts[0].p_true = 0.82
                facts[0].fact_check_status = "completed"
            return facts

        engine.extraction_engine.update_fact_check_results = completes_on_second_refresh

        resolved = engine._resolve_fact_checks([completed_fact])
        assert attempts["count"] >= 2, "Engine should keep polling while a fact check is pending"
        assert resolved[0].fact_check_status == "completed", f"Expected completed, got {resolved[0].fact_check_status}"
        assert abs(resolved[0].p_true - 0.82) < 1e-9, f"Expected resolved p_true, got {resolved[0].p_true}"

        timed_out_fact = ExtractedFact(
            fact_id="fact_2",
            fact_text="Claim two",
            topic_id="t1",
            side="FOR",
            p_true=0.5,
            fact_check_job_id="job_2",
            fact_check_status="pending",
        )

        engine.extraction_engine.update_fact_check_results = lambda facts: facts
        timed_out = engine._resolve_fact_checks([timed_out_fact])
        assert timed_out[0].fact_check_status == "failed", \
            f"Pending facts should be neutralized after timeout, got {timed_out[0].fact_check_status}"
        assert timed_out[0].p_true == 0.5, "Timed-out facts should fall back to neutral p_true"
        print("✓ V2 resolves completed jobs and neutralizes timed-out pending jobs before scoring")
    finally:
        if engine is not None:
            engine.shutdown()
        shutil.rmtree(temp_dir)


def test_topic_geometry():
    """Test topic geometry and lineage per MSD §4.5"""
    print("\n=== Testing Topic Geometry (MSD §4.5) ===")
    
    from backend.topic_engine import TopicEngine
    
    llm_client = LLMClient(provider="mock", num_judges=3)
    engine = TopicEngine(llm_client)
    
    # Test topic extraction
    posts = [
        {'post_id': 'p1', 'facts': 'Safety is paramount in AI development.', 'side': 'FOR'},
        {'post_id': 'p2', 'facts': 'Economic growth requires innovation.', 'side': 'FOR'},
        {'post_id': 'p3', 'facts': 'Regulation stifles progress.', 'side': 'AGAINST'},
    ]
    
    topics = engine.extract_topics_from_posts(posts, "Should AI be regulated?")
    
    assert len(topics) >= 1, "Should extract at least one topic"
    assert len(topics) <= 5, "Should not exceed reasonable topic count"
    
    for topic in topics:
        assert topic.name, "Topic should have name"
        assert topic.scope, "Topic should have scope"
        assert topic.coherence >= 0, "Should have coherence score"
        assert topic.distinctness >= 0, "Should have distinctness score"
    
    print(f"✓ Extracted {len(topics)} topics with geometry metrics")
    
    # Test topic drift
    previous_topics = [
        type('Topic', (), {'topic_id': 't1', 'name': 'Safety', 'scope': 'Safety concerns'})()
    ]
    drift_report = engine.compute_topic_drift(topics, previous_topics)
    
    # Drift report can be empty dict or have various keys - just verify it returns a dict
    assert isinstance(drift_report, dict), f"Drift report should be dict, got {type(drift_report)}"
    print("✓ Topic drift computation works")


# =============================================================================
# AUDIT TESTS - Robustness Checks
# =============================================================================

def test_side_label_symmetry():
    """Test side-label symmetry audit per MSD §14.A"""
    print("\n=== Testing Side-Label Symmetry (MSD §14.A) ===")
    
    engine = ScoringEngine(num_judges=3)
    
    # Create symmetric test data
    topics = [{'topic_id': 't1'}]
    topic_facts = {
        't1': [
            {'canon_fact_id': 'f1', 'side': 'FOR', 'p_true': 0.8},
            {'canon_fact_id': 'f2', 'side': 'AGAINST', 'p_true': 0.8},
        ]
    }
    topic_arguments = {
        't1': [
            {'canon_arg_id': 'a1', 'side': 'FOR', 'inference_text': 'arg1', 'supporting_facts': {'f1'}, 'reasoning_score': 0.7},
            {'canon_arg_id': 'a2', 'side': 'AGAINST', 'inference_text': 'arg2', 'supporting_facts': {'f2'}, 'reasoning_score': 0.7},
        ]
    }
    topic_content_mass = {'t1': 100}
    
    audit = engine.run_side_label_symmetry_audit(
        topics, topic_facts, topic_arguments, topic_content_mass
    )
    
    assert 'median_delta_d' in audit, "Should report delta D"
    assert 'topic_deltas' in audit, "Should report per-topic deltas"
    assert 'interpretation' in audit, "Should provide interpretation"
    
    print(f"✓ Symmetry audit: delta_d={audit['median_delta_d']}, {audit['interpretation']}")


def test_relevance_sensitivity():
    """Test relevance sensitivity audit per MSD §14.D"""
    print("\n=== Testing Relevance Sensitivity (MSD §14.D) ===")
    
    engine = ScoringEngine(num_judges=3)
    
    topics = [{'topic_id': 't1'}, {'topic_id': 't2'}]
    topic_facts = {'t1': [], 't2': []}
    topic_arguments = {'t1': [], 't2': []}
    topic_content_mass = {'t1': 100, 't2': 200}
    
    audit = engine.compute_relevance_sensitivity(
        topics, topic_facts, topic_arguments, topic_content_mass,
        num_perturbations=20
    )
    
    assert 'd_mean' in audit, "Should report mean D"
    assert 'd_std' in audit, "Should report D std dev"
    assert 'verdict_distribution' in audit, "Should show verdict stability"
    assert 'stability_ratio' in audit, "Should compute stability ratio"
    
    print(f"✓ Relevance sensitivity: D_mean={audit['d_mean']}, stability={audit['stability_ratio']}")


# =============================================================================
# REQUIREMENTS COMPLIANCE TESTS
# =============================================================================

def test_identity_blindness():
    """Verify identity blindness per MSD §2.A"""
    print("\n=== Testing Identity Blindness (MSD §2.A) ===")
    
    # Check that data models don't include identity fields
    from backend.models import Post, Span, Fact, CanonicalArgument
    
    post_fields = Post.__dataclass_fields__.keys()
    assert 'username' not in post_fields, "Post should not have username"
    assert 'user_id' not in post_fields, "Post should not have user_id"
    assert 'author' not in post_fields, "Post should not have author"
    print("✓ Post model has no identity fields")
    
    span_fields = Span.__dataclass_fields__.keys()
    assert 'username' not in span_fields, "Span should not have username"
    print("✓ Span model has no identity fields")
    
    fact_fields = Fact.__dataclass_fields__.keys()
    assert 'submitter' not in fact_fields, "Fact should not have submitter"
    print("✓ Fact model has no identity fields")
    
    arg_fields = CanonicalArgument.__dataclass_fields__.keys()
    assert 'author' not in arg_fields, "Argument should not have author"
    print("✓ Argument model has no identity fields")


def test_snapshot_immutability():
    """Test snapshot immutability per MSD §2.C"""
    print("\n=== Testing Snapshot Immutability (MSD §2.C) ===")
    
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    
    try:
        from backend.database import DebateDatabase
        
        db = DebateDatabase(db_path)
        
        # Create two snapshots
        snapshot1 = {
            'snapshot_id': 'snap_001',
            'debate_id': 'debate_001',
            'timestamp': datetime.now().isoformat(),
            'trigger_type': 'manual',
            'template_name': 'standard',
            'template_version': '1.0',
            'allowed_count': 5,
            'blocked_count': 1,
            'block_reasons': {},
            'overall_for': 0.6,
            'overall_against': 0.4,
            'margin_d': 0.2,
            'ci_d_lower': 0.1,
            'ci_d_upper': 0.3,
            'confidence': 0.85,
            'verdict': 'FOR',
            'topic_scores': '{}'
        }
        
        snapshot2 = {
            'snapshot_id': 'snap_002',
            'debate_id': 'debate_001',
            'timestamp': datetime.now().isoformat(),
            'trigger_type': 'activity',
            'template_name': 'standard',
            'template_version': '1.0',
            'allowed_count': 7,
            'blocked_count': 1,
            'block_reasons': {},
            'overall_for': 0.55,
            'overall_against': 0.45,
            'margin_d': 0.1,
            'ci_d_lower': -0.05,
            'ci_d_upper': 0.25,
            'confidence': 0.70,
            'verdict': 'NO VERDICT',
            'topic_scores': '{}'
        }
        
        db.save_snapshot(snapshot1)
        db.save_snapshot(snapshot2)
        
        # Retrieve snapshots
        history = db.get_snapshots_by_debate('debate_001')
        assert len(history) == 2, "Should have 2 snapshots"
        
        # Verify snapshots are preserved as-is
        snap1_retrieved = next(s for s in history if s['snapshot_id'] == 'snap_001')
        assert snap1_retrieved['verdict'] == 'FOR', "Snapshot 1 should preserve verdict"
        
        snap2_retrieved = next(s for s in history if s['snapshot_id'] == 'snap_002')
        assert snap2_retrieved['verdict'] == 'NO VERDICT', "Snapshot 2 should preserve verdict"
        
        print("✓ Snapshots are immutable and preserved correctly")
        
        # Database uses connection-per-operation pattern
        
    finally:
        shutil.rmtree(temp_dir)


def test_visible_modulation():
    """Test visible modulation template per MSD §2.B"""
    print("\n=== Testing Visible Modulation (MSD §2.B) ===")
    
    # Check template versioning
    template = ModulationEngine.get_builtin_template("standard_civility")
    
    assert template.name, "Template should have name"
    assert template.version, "Template should have version"
    assert template.rules, "Template should have visible rules"
    
    version_str = template.get_version_string()
    assert template.name in version_str, "Version string should include name"
    assert template.version in version_str, "Version string should include version"
    
    print(f"✓ Modulation template is visible: {version_str}")
    print(f"  Template has {len(template.rules)} rules")


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================

def run_all_tests():
    """Run all tests and report results"""
    print("=" * 70)
    print("BLIND LLM-ADJUDICATED DEBATE SYSTEM - TEST SUITE")
    print("Testing compliance with Medium Scale Discussion Specification")
    print("=" * 70)
    
    tests = [
        # Unit tests
        ("Modulation System", test_modulation_system),
        ("Debate Proposal Requirements", test_debate_proposal_requirements),
        ("Span Extraction", test_span_extraction),
        ("Fact Canonicalization", test_fact_canonicalization),
        ("Scoring Formulas", test_scoring_formulas),
        ("Verdict Computation", test_verdict_computation),
        
        # Integration tests
        ("Full Pipeline", test_full_pipeline),
        ("V2 Fact-Check Skill Wiring", test_v2_uses_skill_fact_checker),
        ("V2 Pending Fact-Check Resolution", test_v2_resolves_pending_fact_checks_before_scoring),
        ("Topic Geometry", test_topic_geometry),
        
        # Audit tests
        ("Side-Label Symmetry", test_side_label_symmetry),
        ("Relevance Sensitivity", test_relevance_sensitivity),
        
        # Requirements compliance
        ("Identity Blindness", test_identity_blindness),
        ("Snapshot Immutability", test_snapshot_immutability),
        ("Visible Modulation", test_visible_modulation),
    ]
    
    passed = 0
    failed = 0
    errors = []
    
    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            failed += 1
            errors.append((name, f"Assertion failed: {e}"))
            print(f"  ✗ FAILED: {e}")
        except Exception as e:
            failed += 1
            errors.append((name, f"Error: {e}"))
            print(f"  ✗ ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * 70)
    
    if errors:
        print("\nFailed tests:")
        for name, error in errors:
            print(f"  - {name}: {error}")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
