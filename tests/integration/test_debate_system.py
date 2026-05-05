"""
Comprehensive Test Suite for Blind LLM-Adjudicated Debate System
Tests compliance with Medium Scale Discussion (MSD) specification
"""
import sys
import os
import json
import copy
import tempfile
import shutil
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

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
from backend.topic_engine import TopicEngine, Topic
from backend.lsd_v1_2 import merge_sensitivity
from backend.published_results import PublishedResultsBuilder


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
        "debate_frame": "Judge which side best balances access, emissions, and practical enforcement.",
        "frame_sides": "FOR | Supports the downtown ban.\nAGAINST | Opposes the downtown ban.",
        "frame_evaluation_criteria": "Logical coherence\nFeasibility\nNet public benefit",
        "frame_definitions": "Downtown: the city center business district",
        "frame_scope_constraints": "Focus on the next 10 years\nAssume current transit funding remains constant",
    })
    assert not missing_fields, f"Expected a complete proposal, got missing fields: {missing_fields}"
    assert proposal["resolution"] == proposal["motion"], "Motion should hydrate the legacy resolution field"
    assert "Frame summary:" in proposal["scope"], "Internal scope should include the frame summary"
    assert len(proposal["active_frame"]["sides"]) == 2, "Structured frame should normalize sides"
    assert proposal["active_frame"]["evaluation_criteria"], "Structured frame should include evaluation criteria"
    assert proposal["active_frame"]["definitions"], "Structured frame should include definitions"
    print("✓ Complete proposal payload hydrates the legacy scoring context")

    _, missing_fields = parse_debate_proposal_payload({
        "motion": "Should cities ban private cars downtown?"
    })
    assert missing_fields == ["moderation criteria", "debate frame"], (
        f"Expected missing moderation criteria and debate frame, got {missing_fields}"
    )
    print("✓ Missing proposal fields are reported explicitly")


def test_frame_versioning_and_multiside_snapshot():
    """Test frame versioning and multi-sided scoring."""
    print("\n=== Testing DebateFrame Versioning & Multi-Side Snapshot ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_frames.db")

    try:
        engine = DebateEngineV2(
            db_path=db_path,
            fact_check_mode="OFFLINE",
            llm_provider="mock",
            num_judges=3,
        )

        debate = engine.create_debate({
            "motion": "What should governments do about frontier AI deployment?",
            "moderation_criteria": (
                "Allow arguments directly engaging the policy choice. Block harassment, spam, "
                "PII, and off-topic content."
            ),
            "debate_frame": "Compare the most decision-useful policy option for a neutral regulator.",
            "frame": {
                "stage": "substantive",
                "sides": [
                    {"label": "PAUSE", "description": "Temporarily pause frontier deployment."},
                    {"label": "REGULATE", "description": "Allow deployment under tighter regulation."},
                    {"label": "OPEN", "description": "Allow broad deployment with minimal new restrictions."},
                ],
                "evaluation_criteria": [
                    "Risk reduction",
                    "Economic feasibility",
                    "Decision usefulness for a regulator",
                ],
                "definitions": [
                    {"term": "Frontier AI", "definition": "Models at the capability frontier for general-purpose use."}
                ],
                "scope_constraints": [
                    "Focus on national policy choices over the next five years.",
                    "Assume current compute trends continue.",
                ],
            },
        })

        assert debate["active_frame"]["version"] == 1, "Initial frame should be version 1"
        assert len(debate["active_frame"]["sides"]) == 3, "Initial frame should retain all sides"

        updated = engine.create_frame_version(debate["debate_id"], {
            "debate_frame": "Refine the frame around immediate deployment policy rather than long-run governance.",
            "frame": {
                "stage": "substantive",
                "sides": [
                    {"label": "PAUSE", "description": "Pause new deployment until evaluations improve."},
                    {"label": "REGULATE", "description": "Permit deployment with stronger licensing and audits."},
                    {"label": "OPEN", "description": "Permit broad deployment with minimal new constraints."},
                ],
                "evaluation_criteria": [
                    "Risk reduction",
                    "Implementability",
                    "Quality of evidence",
                ],
                "definitions": [
                    {"term": "Deployment", "definition": "Releasing a frontier model for public or enterprise use."}
                ],
                "scope_constraints": [
                    "Focus on immediate policy choices for the next two years.",
                ],
            },
        })

        assert updated["active_frame"]["version"] == 2, "New frame should increment the version"
        assert updated["active_frame"]["supersedes_frame_id"], "Frame versions should preserve lineage"

        frames = engine.get_debate_frames(debate["debate_id"])
        assert len(frames) == 2, "Debate should retain both frame versions"

        for side in ["PAUSE", "REGULATE", "OPEN"]:
            engine.submit_post(
                debate_id=debate["debate_id"],
                side=side,
                topic_id=None,
                facts=f"{side} factual premise about deployment risk and implementation.",
                inference=f"Therefore the {side} policy is the strongest option under the active frame.",
                counter_arguments="",
            )

        snapshot = engine.generate_snapshot(debate["debate_id"], trigger_type="manual")
        assert snapshot["frame_id"] == updated["active_frame_id"], "Snapshot should bind to the active frame"
        assert snapshot["side_order"] == ["PAUSE", "REGULATE", "OPEN"], "Snapshot should preserve frame side order"
        assert len(snapshot["overall_scores"]) == 3, "Snapshot should score all active sides"
        print("✓ Frame versions persist and multi-sided snapshots score the active frame only")

    finally:
        shutil.rmtree(temp_dir)


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
    
    # Test empty facts (per v1.5 spec: no empirical premises → F=null)
    empty_factuality = engine.compute_factuality([])
    assert empty_factuality is None, "Empty facts should return None per v1.5 spec"
    print("✓ Empty facts return None per v1.5 spec")
    
    # Test quality calculation (MSD §10.4)
    quality = engine.compute_quality(0.8, 0.7, 0.6)
    expected_q = (0.8 * 0.7 * 0.6) ** (1/3)
    assert abs(quality - expected_q) < 0.01, "Quality should be geometric mean"
    print(f"✓ Quality Q = {quality:.3f} (geometric mean of F × Reason × Cov)")
    
    # Test epsilon floor handling (v1.5: epsilon floor prevents zero collapse)
    zero_quality = engine.compute_quality(0.8, 0.0, 0.6)
    # Per v1.5 spec: max(Ck, epsilon) applied to each component
    # 0.0 becomes Q_EPSILON (0.01), so Q = (0.8 * 0.01 * 0.6)^(1/3) ≈ 0.169
    assert zero_quality > 0.0, "Epsilon floor should prevent zero collapse"
    print(f"✓ Epsilon floor prevents zero collapse: Q={zero_quality:.3f}")
    
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

        assert engine.fact_checker.__class__.__name__ == "V15FactCheckingSkill", \
            f"Expected V15FactCheckingSkill, got {type(engine.fact_checker)}"
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


def test_merge_variant_deterministic_ids():
    """Test that merge_variant_replicate produces deterministic IDs."""
    print("\n=== Testing Merge Variant Deterministic IDs ===")

    engine = TopicEngine()
    topics = [
        Topic(topic_id="tA", name="A", scope="apple banana cherry", relevance=0.25),
        Topic(topic_id="tB", name="B", scope="apple banana cherry date", relevance=0.25),
        Topic(topic_id="tC", name="C", scope="xylophone zebra", relevance=0.25),
        Topic(topic_id="tD", name="D", scope="quantum physics", relevance=0.25),
    ]

    variant1 = engine.merge_variant_replicate(topics, variant_seed=99)
    variant2 = engine.merge_variant_replicate(topics, variant_seed=99)

    ids1 = {t.topic_id for t in variant1}
    ids2 = {t.topic_id for t in variant2}
    assert ids1 == ids2, f"Variant IDs not deterministic: {ids1} vs {ids2}"

    # Also verify a different seed produces different IDs
    variant3 = engine.merge_variant_replicate(topics, variant_seed=42)
    ids3 = {t.topic_id for t in variant3}
    # With high probability the hash IDs differ; assert they are not identical set
    assert ids1 != ids3 or len(ids1 & ids3) < len(ids1), "Different seeds should produce different IDs"

    print("✓ Merge variant IDs are deterministic for identical seed")


def test_merge_variant_produces_different_structure():
    """Test that min_sim variant produces a different merge than max_sim primary."""
    print("\n=== Testing Merge Variant Different Structure ===")

    engine = TopicEngine()
    topics = [
        Topic(topic_id="tA", name="A", scope="apple banana cherry", relevance=0.25),
        Topic(topic_id="tB", name="B", scope="apple banana cherry date", relevance=0.25),
        Topic(topic_id="tC", name="C", scope="xylophone zebra", relevance=0.25),
        Topic(topic_id="tD", name="D", scope="quantum physics", relevance=0.25),
    ]

    # Primary merge (max_sim) with target=3
    primary_merged = engine._merge_topics([copy.deepcopy(t) for t in topics], target_count=3)
    # Variant merge (min_sim) with target=3
    variant_merged = engine.merge_variant_replicate(topics, variant_seed=99)

    # Build sets of merged parent pairs
    def get_merge_pairs(topic_list):
        pairs = set()
        for t in topic_list:
            if len(t.parent_topic_ids) == 2:
                pairs.add(tuple(sorted(t.parent_topic_ids)))
        return pairs

    primary_pairs = get_merge_pairs(primary_merged)
    variant_pairs = get_merge_pairs(variant_merged)

    assert primary_pairs != variant_pairs, (
        f"Variant should merge a different pair than primary. "
        f"Primary: {primary_pairs}, Variant: {variant_pairs}"
    )
    print(f"✓ Primary merged {primary_pairs}, Variant merged {variant_pairs}")


def test_merge_sensitivity_ancestry_stability():
    """Test that mapping stability is computed from ancestry, not synthetic scopes."""
    print("\n=== Testing Merge Sensitivity Ancestry Stability ===")

    primary_topics = [
        {"topic_id": "t1", "parent_topic_ids": []},
        {"topic_id": "t2", "parent_topic_ids": []},
        {"topic_id": "t3", "parent_topic_ids": []},
    ]
    # Variant: t1 and t2 merged into r1; t3 survives
    replicate_topics = [
        {"topic_id": "r1", "parent_topic_ids": ["t1", "t2"]},
        {"topic_id": "t3", "parent_topic_ids": []},
    ]
    topic_content_mass = {"t1": 10.0, "t2": 10.0, "t3": 5.0}
    primary_to_replicate = {"t1": "r1", "t2": "r1", "t3": "t3"}

    result = merge_sensitivity(
        primary_topics,
        replicate_topics,
        topic_content_mass,
        baseline_d=0.5,
        replicate_d=0.6,
        primary_to_replicate=primary_to_replicate,
    )

    # Stability: t1=10*0.5=5, t2=10*0.5=5, t3=5*1.0=5 -> total_stable=15, total_mass=25 -> 0.6
    expected_stability = round(15.0 / 25.0, 4)
    assert result["mapping_stability"] == expected_stability, (
        f"Expected stability {expected_stability}, got {result['mapping_stability']}"
    )
    assert result["score_deltas_per_frame"]["active"]["delta_d"] == round(0.6 - 0.5, 4)
    assert result["score_deltas_per_frame"]["active"]["baseline_d"] == 0.5
    assert result["score_deltas_per_frame"]["active"]["replicate_d"] == 0.6

    print(f"✓ Ancestry stability computed correctly: {result['mapping_stability']}")


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


def test_admin_template_persistence_and_engine_sync():
    """Ensure admin template drafts persist and active template syncs into runtime engine."""
    print("\n=== Testing Admin Template Persistence + Engine Sync ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_admin_templates.db")
    engine = None

    try:
        from backend.database import DebateDatabase

        db = DebateDatabase(db_path)
        active_before = db.get_active_moderation_template()
        assert active_before is not None, "Database should seed an active moderation template"

        draft = db.create_moderation_template_version(
            base_template_id="minimal",
            template_name="Minimal Acceptance Template",
            version="9.9.1",
            status="draft",
            topic_requirements={
                "required_keywords": ["audit"],
                "relevance_threshold": "moderate",
                "enforce_scope": True,
            },
            toxicity_settings={
                "sensitivity_level": 2,
                "block_personal_attacks": True,
                "block_hate_speech": True,
                "block_threats": True,
                "block_sexual_harassment": True,
                "block_mild_profanity": False,
            },
            pii_settings={
                "detect_email": True,
                "detect_phone": True,
                "detect_address": True,
                "detect_full_names": False,
                "detect_social_handles": False,
                "action": "block",
            },
            spam_rate_limit_settings={
                "min_length": 20,
                "max_length": 4000,
                "flood_threshold_per_hour": 12,
                "duplicate_detection": True,
                "rate_limiting": True,
            },
            prompt_injection_settings={
                "enabled": True,
                "block_markdown_hiding": True,
                "custom_patterns": ["ignore previous instructions"],
            },
            author_user_id="admin_test",
            notes="Regression test draft",
        )

        assert draft["status"] == "draft", "Draft template should persist as draft"

        activated = db.activate_moderation_template(draft["template_record_id"], author_user_id="admin_test")
        assert activated is not None, "Activating a draft should return the activated row"
        assert activated["is_current"] is True, "Activated template should become current pointer target"
        assert activated["version"] == "9.9.1"

        engine = DebateEngineV2(
            db_path=db_path,
            fact_check_mode="OFFLINE",
            llm_provider="mock",
            num_judges=3,
        )
        engine.refresh_active_modulation_template(force=True)
        modulation_info = engine.get_modulation_info()

        assert modulation_info["template_version"] == "9.9.1", (
            "Engine should reflect active moderation template version from DB"
        )
        assert modulation_info["template_name"] == "Minimal Acceptance Template", (
            "Engine should reflect active moderation template name from DB"
        )
        print("✓ Admin template persistence and runtime sync verified")
    finally:
        if engine is not None:
            engine.shutdown()
        shutil.rmtree(temp_dir)


def test_api_auth_session_and_admin_access_consistency():
    """Verify API auth/session behavior for 401/403 and active-debate persistence."""
    print("\n=== Testing API Auth + Session Consistency ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_api_auth_session.db")
    env_keys = (
        "DEBATE_DB_PATH",
        "SECRET_KEY",
        "ADMIN_ACCESS_MODE",
        "ADMIN_USER_EMAILS",
        "ADMIN_USER_IDS",
        "DISABLE_JOB_WORKER",
    )
    old_env = {key: os.environ.get(key) for key in env_keys}
    app_module = None

    try:
        os.environ["DEBATE_DB_PATH"] = db_path
        os.environ["SECRET_KEY"] = "test-secret-auth-session-32-bytes-min"
        os.environ["ADMIN_ACCESS_MODE"] = "restricted"
        os.environ["ADMIN_USER_EMAILS"] = ""
        os.environ["ADMIN_USER_IDS"] = ""
        os.environ["DISABLE_JOB_WORKER"] = "1"

        try:
            import backend.app_v3 as app_v3
        except ModuleNotFoundError as exc:
            if exc.name == "jwt":
                print("⚠ Skipping API auth/session consistency test: PyJWT not available in this interpreter.")
                return
            raise
        app_module = importlib.reload(app_v3)
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        unauthorized_create = client.post(
            "/api/debates",
            json={
                "resolution": "Resolved: Third-party AI audits should be mandatory.",
                "scope": "Evaluate safety, governance, and implementation costs over five years.",
            },
        )
        assert unauthorized_create.status_code == 401, "Unauthenticated debate creation should be rejected"
        assert unauthorized_create.get_json().get("code") == "AUTH_REQUIRED"

        # Pre-seed a dummy admin so the real test user does NOT get auto-admin
        # (database_v3 auto-promotes the first registered user to admin)
        dummy_reg = client.post("/api/auth/register", json={
            "email": "dummy.admin@example.com",
            "password": "password123",
            "display_name": "Dummy Admin",
        })
        assert dummy_reg.status_code == 201

        registration_payload = {
            "email": "auth.session.user@example.com",
            "password": "password123",
            "display_name": "Auth Session User",
        }
        registration = client.post("/api/auth/register", json=registration_payload)
        assert registration.status_code == 201, f"Registration failed: {registration.get_data(as_text=True)}"
        auth_data = registration.get_json()
        # Verify the test user is NOT auto-admin (the auto-admin slot was taken by dummy)
        assert auth_data.get("is_admin") is False, "Test user should not be auto-admin"
        token = auth_data["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # Grant admin access via restricted-mode allowlist so the authenticated user
        # can create debates (POST /api/debates is admin_required)
        os.environ["ADMIN_USER_EMAILS"] = registration_payload["email"]
        # Reload app module to pick up new env
        app_module = importlib.reload(app_module)
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        create = client.post(
            "/api/debates",
            headers=auth_headers,
            json={
                "resolution": "Resolved: Mandatory audits improve frontier AI deployment safety.",
                "scope": "Assess expected safety gains and compliance burdens for cross-border deployment.",
            },
        )
        assert create.status_code == 201, f"Authenticated debate creation failed: {create.get_data(as_text=True)}"
        debate_id = create.get_json()["debate_id"]

        active_for_user = client.get("/api/debate", headers=auth_headers)
        assert active_for_user.status_code == 200
        active_payload = active_for_user.get_json()
        assert active_payload.get("has_debate") is True
        assert active_payload.get("debate_id") == debate_id, "Active debate should persist per authenticated user"

        anonymous_view = client.get("/api/debate")
        assert anonymous_view.status_code == 200
        assert anonymous_view.get_json().get("has_debate") is False, (
            "Anonymous viewer should not inherit authenticated user's active debate context"
        )

        # Temporarily clear allowlist to verify 403 for non-allowlisted users
        os.environ["ADMIN_USER_EMAILS"] = ""
        app_module = importlib.reload(app_module)
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        admin_forbidden = client.get("/api/admin/moderation-template/current", headers=auth_headers)
        assert admin_forbidden.status_code == 403, "Restricted admin mode should block non-allowlisted users"
        assert admin_forbidden.get_json().get("code") == "ADMIN_RESTRICTED"

        os.environ["ADMIN_USER_EMAILS"] = registration_payload["email"]
        app_module = importlib.reload(app_module)
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        admin_allowed = client.get("/api/admin/moderation-template/current", headers=auth_headers)
        assert admin_allowed.status_code == 200, "Allowlisted restricted admin user should gain access"
        assert admin_allowed.get_json().get("template"), "Admin response should include active template"

        logout = client.post("/api/auth/logout", headers=auth_headers)
        assert logout.status_code == 200, "Logout endpoint should succeed for authenticated sessions"

        expired_token_payload = {
            "user_id": auth_data["user_id"],
            "email": auth_data["email"],
            "display_name": auth_data["display_name"],
            "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
            "iat": datetime.now(timezone.utc) - timedelta(hours=1),
            "type": "access",
        }
        expired_token = app_module.jwt.encode(
            expired_token_payload,
            app_module.app.config["SECRET_KEY"],
            algorithm="HS256",
        )
        expired_check = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert expired_check.status_code == 401, "Expired token should be rejected"
        assert expired_check.get_json().get("code") == "AUTH_INVALID", "Expired token should map to AUTH_INVALID"
        print("✓ API auth/session/admin access checks are consistent")
    finally:
        if app_module is not None:
            try:
                app_module.debate_engine.shutdown()
            except Exception:
                pass

        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value

        shutil.rmtree(temp_dir)


def test_legacy_password_hashes_authenticate_and_migrate():
    """Legacy password hashes should verify cleanly and upgrade to bcrypt."""
    import hashlib
    from werkzeug.security import generate_password_hash
    from backend.database_v3 import Database

    print("\n=== Testing Legacy Password Hash Compatibility ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_legacy_auth.db")

    try:
        db = Database(db_path)
        now = datetime.now().isoformat()

        db.save_user({
            "user_id": "user_legacy_scrypt",
            "email": "legacy.scrypt@example.com",
            "password_hash": generate_password_hash("legacy-pass-123"),
            "display_name": "Legacy Scrypt",
            "created_at": now,
            "is_active": True,
            "is_verified": False,
            "last_login": None,
        })
        db.save_user({
            "user_id": "user_legacy_sha256",
            "email": "legacy.sha256@example.com",
            "password_hash": hashlib.sha256("legacy-pass-456".encode("utf-8")).hexdigest(),
            "display_name": "Legacy Sha256",
            "created_at": now,
            "is_active": True,
            "is_verified": False,
            "last_login": None,
        })

        assert db.verify_user("legacy.scrypt@example.com", "wrong-pass") is None
        assert db.verify_user("legacy.sha256@example.com", "wrong-pass") is None

        scrypt_user = db.verify_user("legacy.scrypt@example.com", "legacy-pass-123")
        sha256_user = db.verify_user("legacy.sha256@example.com", "legacy-pass-456")

        assert scrypt_user is not None, "Legacy werkzeug/scrypt user should authenticate"
        assert sha256_user is not None, "Legacy SHA-256 user should authenticate"

        migrated_scrypt = db.get_user_by_email("legacy.scrypt@example.com")
        migrated_sha256 = db.get_user_by_email("legacy.sha256@example.com")

        assert migrated_scrypt["password_hash"].startswith("$2"), "Legacy scrypt hash should be upgraded to bcrypt"
        assert migrated_sha256["password_hash"].startswith("$2"), "Legacy SHA-256 hash should be upgraded to bcrypt"
        print("✓ Legacy password hashes authenticate without 500s and migrate to bcrypt")
    finally:
        shutil.rmtree(temp_dir)


def test_rate_limiter_exempts_navigation_and_read_only_requests():
    """Navigation and GET endpoints should not consume the default mutating API limit."""
    print("\n=== Testing Rate Limiter Exempts Navigation + Read-Only Requests ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_rate_limits.db")
    env_keys = (
        "DEBATE_DB_PATH",
        "SECRET_KEY",
        "ENABLE_RATE_LIMITER",
        "DISABLE_JOB_WORKER",
    )
    old_env = {key: os.environ.get(key) for key in env_keys}
    app_module = None

    try:
        os.environ["DEBATE_DB_PATH"] = db_path
        os.environ["SECRET_KEY"] = "test-secret-rate-limit-32-bytes-min"
        os.environ["ENABLE_RATE_LIMITER"] = "true"
        os.environ["DISABLE_JOB_WORKER"] = "1"

        try:
            import backend.app_v3 as app_v3
        except ModuleNotFoundError as exc:
            if exc.name == "jwt":
                print("⚠ Skipping rate limiter test: PyJWT not available in this interpreter.")
                return
            raise

        app_module = importlib.reload(app_v3)
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        for _ in range(55):
            response = client.get("/")
            assert response.status_code == 200, "Static navigation should not be rate limited"

        for _ in range(55):
            response = client.get("/api/health")
            assert response.status_code == 200, "Read-only API GETs should not be rate limited"

        last_response = None
        for idx in range(51):
            last_response = client.post(
                "/api/auth/register",
                json={
                    "email": f"rate-limit-user-{idx}@example.com",
                    "password": "password123",
                    "display_name": f"Rate User {idx}",
                },
            )
            if idx < 50:
                assert last_response.status_code == 201, (
                    f"Expected write request {idx + 1} to succeed, got {last_response.status_code}: "
                    f"{last_response.get_data(as_text=True)}"
                )

        assert last_response is not None
        assert last_response.status_code == 429, "Mutating API requests should still hit the default rate limit"
        print("✓ Navigation/GETs are exempt while mutating API requests remain protected")
    finally:
        if app_module is not None:
            try:
                app_module.debate_engine.shutdown()
            except Exception:
                pass

        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value

        shutil.rmtree(temp_dir)


def test_debate_proposal_lifecycle():
    """Test debate proposal submission, queue, accept, and reject."""
    import uuid as _uuid
    print("\n=== Testing Debate Proposal Lifecycle ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_proposals.db")

    try:
        engine = DebateEngineV2(
            db_path=db_path,
            fact_check_mode="OFFLINE",
            llm_provider="mock",
            num_judges=3,
        )

        # Simulate a proposer user
        proposer_id = "user_proposer_001"
        db = engine.db
        db.save_user({
            "user_id": proposer_id,
            "email": "proposer@example.com",
            "password_hash": "hash",
            "display_name": "Proposer",
            "created_at": datetime.now().isoformat(),
        })

        proposal_id = f"prop_{_uuid.uuid4().hex[:10]}"
        now = datetime.now().isoformat()
        db.save_debate_proposal({
            "proposal_id": proposal_id,
            "proposer_user_id": proposer_id,
            "motion": "Should cities ban private cars downtown?",
            "moderation_criteria": "Allow evidence-based arguments.",
            "debate_frame": "Judge which side best balances access and emissions.",
            "frame_payload_json": {"stage": "substantive"},
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        })

        proposal = db.get_debate_proposal(proposal_id)
        assert proposal is not None, "Proposal should be retrievable"
        assert proposal["status"] == "pending", "New proposal should be pending"

        user_proposals = db.get_debate_proposals_by_user(proposer_id)
        assert any(p["proposal_id"] == proposal_id for p in user_proposals), "Proposal should be in user's list"

        pending_queue = db.get_debate_proposals_by_status("pending")
        assert any(p["proposal_id"] == proposal_id for p in pending_queue), "Proposal should be in pending queue"

        # Accept the proposal
        debate = engine.create_debate({
            "motion": proposal["motion"],
            "moderation_criteria": proposal["moderation_criteria"],
            "debate_frame": proposal["debate_frame"],
            "frame": proposal.get("frame_payload_json", {}),
        }, user_id=proposer_id)

        db.update_debate_proposal_status(
            proposal_id,
            status="accepted",
            reviewer_user_id="admin_001",
            accepted_debate_id=debate["debate_id"],
        )

        updated = db.get_debate_proposal(proposal_id)
        assert updated["status"] == "accepted", "Proposal should be accepted"
        assert updated["accepted_debate_id"] == debate["debate_id"], "Accepted debate ID should be stored"

        print("✓ Debate proposal lifecycle works end-to-end")
    finally:
        shutil.rmtree(temp_dir)


def test_accepting_proposal_activates_debate_for_proposer():
    """Accepted proposals should become the proposer's active debate, not only the admin's."""
    print("\n=== Testing Proposal Acceptance Activates Proposer Debate Context ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_proposal_activation.db")

    old_env = {
        "DEBATE_DB_PATH": os.environ.get("DEBATE_DB_PATH"),
        "FACT_CHECK_MODE": os.environ.get("FACT_CHECK_MODE"),
        "LLM_PROVIDER": os.environ.get("LLM_PROVIDER"),
        "NUM_JUDGES": os.environ.get("NUM_JUDGES"),
        "ADMIN_ACCESS_MODE": os.environ.get("ADMIN_ACCESS_MODE"),
        "DISABLE_JOB_WORKER": os.environ.get("DISABLE_JOB_WORKER"),
    }
    os.environ["DEBATE_DB_PATH"] = db_path
    os.environ["FACT_CHECK_MODE"] = "OFFLINE"
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["NUM_JUDGES"] = "3"
    os.environ["ADMIN_ACCESS_MODE"] = "authenticated"
    os.environ["DISABLE_JOB_WORKER"] = "1"

    app_module = None
    try:
        import backend.app_v3 as app_v3

        app_module = importlib.reload(app_v3)
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        admin = client.post("/api/auth/register", json={
            "email": "proposal.admin@example.com",
            "password": "password123",
            "display_name": "Proposal Admin",
        })
        assert admin.status_code == 201, admin.get_data(as_text=True)
        admin_token = admin.get_json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        proposer = client.post("/api/auth/register", json={
            "email": "proposal.proposer@example.com",
            "password": "password123",
            "display_name": "Proposal Proposer",
        })
        assert proposer.status_code == 201, proposer.get_data(as_text=True)
        proposer_token = proposer.get_json()["access_token"]
        proposer_headers = {"Authorization": f"Bearer {proposer_token}"}

        proposal_response = client.post(
            "/api/debate-proposals",
            headers=proposer_headers,
            json={
                "motion": "Resolved: Independent AI audits should be required before frontier deployment.",
                "moderation_criteria": "Allow evidence-based arguments and block spam or harassment.",
                "debate_frame": "Judge which side best balances safety, accountability, and practical burden.",
            },
        )
        assert proposal_response.status_code == 201, proposal_response.get_data(as_text=True)
        proposal_id = proposal_response.get_json()["proposal_id"]

        accept_response = client.post(
            f"/api/admin/debate-proposals/{proposal_id}/accept",
            headers=admin_headers,
        )
        assert accept_response.status_code == 200, accept_response.get_data(as_text=True)
        debate_id = accept_response.get_json()["debate_id"]

        proposer_active = client.get("/api/debate", headers=proposer_headers)
        assert proposer_active.status_code == 200, proposer_active.get_data(as_text=True)
        proposer_active_payload = proposer_active.get_json()
        assert proposer_active_payload.get("has_debate") is True
        assert proposer_active_payload.get("debate_id") == debate_id, (
            "Accepted proposal should become the proposer's active debate"
        )

        proposer_debates = client.get("/api/debates", headers=proposer_headers)
        assert proposer_debates.status_code == 200, proposer_debates.get_data(as_text=True)
        debate_ids = {item["debate_id"] for item in proposer_debates.get_json().get("debates", [])}
        assert debate_id in debate_ids, "Accepted debate should appear in the proposer's debate list"

        print("✓ Accepted proposals activate debate context for the proposer")
    finally:
        if app_module is not None:
            try:
                app_module.debate_engine.shutdown()
            except Exception:
                pass

        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value

        shutil.rmtree(temp_dir)


def test_snapshot_append_only_and_integrity_fields():
    """Test snapshots reject duplicates and include integrity fields."""
    print("\n=== Testing Snapshot Append-Only + Integrity Fields ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_snapshot_integrity.db")

    try:
        engine = DebateEngineV2(
            db_path=db_path,
            fact_check_mode="OFFLINE",
            llm_provider="mock",
            num_judges=3,
        )

        debate = engine.create_debate({
            "motion": "Resolved: Test motion for snapshot integrity.",
            "moderation_criteria": "Allow on-topic arguments.",
            "debate_frame": "Judge strength of case.",
        })

        # Submit posts to have non-empty input bundle
        engine.submit_post(debate["debate_id"], "FOR", "t1",
                           "Fact one.", "Therefore one.")
        engine.submit_post(debate["debate_id"], "AGAINST", "t1",
                           "Fact two.", "Therefore two.")

        snapshot = engine.generate_snapshot(debate["debate_id"], trigger_type="manual")

        # Verify integrity fields present
        assert "replay_manifest_json" in snapshot or "replay_manifest" in snapshot, "Snapshot should include replay manifest"
        assert snapshot.get("input_hash_root"), "Snapshot should include input_hash_root"
        assert snapshot.get("output_hash_root"), "Snapshot should include output_hash_root"
        assert snapshot.get("recipe_versions_json") or snapshot.get("recipe_versions"), "Snapshot should include recipe_versions"

        # Verify append-only: duplicate save should raise
        from backend.database import DebateDatabase
        db = DebateDatabase(db_path)
        duplicate_raised = False
        try:
            db.save_snapshot({
                "snapshot_id": snapshot["snapshot_id"],
                "debate_id": debate["debate_id"],
                "timestamp": datetime.now().isoformat(),
                "trigger_type": "manual",
                "template_name": "test",
                "template_version": "1.0",
            })
        except ValueError as exc:
            if "already exists" in str(exc):
                duplicate_raised = True
        assert duplicate_raised, "Duplicate snapshot_id should raise ValueError"

        print("✓ Snapshot append-only and integrity fields verified")
    finally:
        shutil.rmtree(temp_dir)


def test_published_bundle_uses_engine_for_diff_and_targets():
    """Test that PublishedResultsBuilder uses DebateEngineV2 when wired."""
    print("\n=== Testing Published Bundle Uses Engine for Diff and Targets ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_published_bundle.db")
    engine = None

    try:
        engine = DebateEngineV2(
            db_path=db_path,
            fact_check_mode="OFFLINE",
            llm_provider="mock",
            num_judges=3,
        )

        debate = engine.create_debate({
            "motion": "Should governments subsidize renewable energy?",
            "moderation_criteria": "Allow evidence-backed arguments. Block harassment.",
            "debate_frame": "Judge which side best informs a neutral policymaker.",
        })
        debate_id = debate["debate_id"]

        # Submit posts and generate first snapshot
        engine.submit_post(debate_id, "FOR", None,
                           "Renewables create jobs.", "Therefore subsidize.")
        engine.submit_post(debate_id, "AGAINST", None,
                           "Subsidies distort markets.", "Therefore do not subsidize.")
        snap1 = engine.generate_snapshot(debate_id, trigger_type="manual")

        # Submit more posts and generate second snapshot so diff has two snapshots
        engine.submit_post(debate_id, "FOR", None,
                           "Solar costs have dropped 80%.", "Therefore subsidies are efficient.")
        snap2 = engine.generate_snapshot(debate_id, trigger_type="activity")

        # Build bundle with engine-wired builder
        builder = PublishedResultsBuilder(db_path=db_path, engine=engine)
        bundle = builder.build_bundle(debate_id)

        # Verify snapshot_diff uses engine shape
        diff = bundle["snapshot_diff"]
        assert diff is not None, "Expected snapshot_diff with two snapshots"
        assert "topics" in diff, "Engine diff should include 'topics'"
        assert "facts" in diff, "Engine diff should include 'facts'"
        assert "arguments" in diff, "Engine diff should include 'arguments'"
        assert "scores" in diff, "Engine diff should include 'scores'"
        assert "note" not in diff, "Engine-backed diff should not contain placeholder 'note'"

        # Verify evidence_targets uses flat engine shape
        targets = bundle["evidence_targets"]
        assert "high_impact_targets" in targets, "Engine targets should include 'high_impact_targets'"
        assert "medium_impact_targets" in targets, "Engine targets should include 'medium_impact_targets'"
        assert "margin_needed_for_flip" in targets, "Engine targets should include 'margin_needed_for_flip'"
        assert "verdict" in targets, "Engine targets should include 'verdict'"
        assert "confidence" in targets, "Engine targets should include 'confidence'"
        assert "note" not in targets, "Engine-backed targets should not contain placeholder 'note'"
        assert "verdict_sensitivity" not in targets, "Targets should remain flat, not nested under 'verdict_sensitivity'"

        print("✓ Published bundle uses engine-shaped diff and flat evidence targets")
    finally:
        if engine is not None:
            engine.shutdown()
        shutil.rmtree(temp_dir)


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
        ("DebateFrame Versioning & Multi-Side Snapshot", test_frame_versioning_and_multiside_snapshot),
        ("V2 Fact-Check Skill Wiring", test_v2_uses_skill_fact_checker),
        ("V2 Pending Fact-Check Resolution", test_v2_resolves_pending_fact_checks_before_scoring),
        ("Topic Geometry", test_topic_geometry),
        
        # Audit tests
        ("Side-Label Symmetry", test_side_label_symmetry),
        ("Relevance Sensitivity", test_relevance_sensitivity),
        ("Merge Sensitivity Deterministic IDs", test_merge_variant_deterministic_ids),
        ("Merge Sensitivity Different Structure", test_merge_variant_produces_different_structure),
        ("Merge Sensitivity Ancestry Stability", test_merge_sensitivity_ancestry_stability),
        
        # Requirements compliance
        ("Identity Blindness", test_identity_blindness),
        ("Snapshot Immutability", test_snapshot_immutability),
        ("Visible Modulation", test_visible_modulation),
        ("Admin Template Persistence + Engine Sync", test_admin_template_persistence_and_engine_sync),
        ("API Auth + Session Consistency", test_api_auth_session_and_admin_access_consistency),
        ("Legacy Password Hash Compatibility", test_legacy_password_hashes_authenticate_and_migrate),
        ("Rate Limiter Exemptions", test_rate_limiter_exempts_navigation_and_read_only_requests),
        ("Debate Proposal Lifecycle", test_debate_proposal_lifecycle),
        ("Snapshot Append-Only + Integrity", test_snapshot_append_only_and_integrity_fields),
        ("Published Bundle Uses Engine", test_published_bundle_uses_engine_for_diff_and_targets),
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


def test_rate_limit_json_body_shape():
    """Rate-limit responses must return structured JSON with error, code, and retry_after."""
    print("\n=== Testing Rate Limit JSON Body Shape ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_rate_limit_json.db")
    env_keys = (
        "DEBATE_DB_PATH",
        "SECRET_KEY",
        "ENABLE_RATE_LIMITER",
        "DISABLE_JOB_WORKER",
    )
    old_env = {key: os.environ.get(key) for key in env_keys}
    app_module = None

    try:
        os.environ["DEBATE_DB_PATH"] = db_path
        os.environ["SECRET_KEY"] = "test-secret-rate-limit-32-bytes-min"
        os.environ["ENABLE_RATE_LIMITER"] = "true"
        os.environ["DISABLE_JOB_WORKER"] = "1"

        import backend.app_v3 as app_v3
        app_module = importlib.reload(app_v3)
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        # Exhaust the write limit
        for idx in range(51):
            last_response = client.post(
                "/api/auth/register",
                json={
                    "email": f"rate-limit-body-{idx}@example.com",
                    "password": "password123",
                    "display_name": f"Rate User {idx}",
                },
            )

        assert last_response.status_code == 429
        data = last_response.get_json()
        assert data is not None, "429 response must be JSON"
        assert data.get("error") == "Rate limit exceeded. Please slow down and retry."
        assert data.get("code") == "RATE_LIMITED"
        assert "retry_after" in data
        print("✓ Rate-limit JSON body has correct shape")
    finally:
        if app_module is not None:
            try:
                app_module.debate_engine.shutdown()
            except Exception:
                pass
        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value
        shutil.rmtree(temp_dir)


def test_sufficiency_checks_return_insufficient_data():
    """Verdict and dossier endpoints must return INSUFFICIENT_DATA when no posts are allowed."""
    print("\n=== Testing Sufficiency Checks Return INSUFFICIENT_DATA ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_sufficiency.db")
    old_env = {
        "DEBATE_DB_PATH": os.environ.get("DEBATE_DB_PATH"),
        "FACT_CHECK_MODE": os.environ.get("FACT_CHECK_MODE"),
        "LLM_PROVIDER": os.environ.get("LLM_PROVIDER"),
        "NUM_JUDGES": os.environ.get("NUM_JUDGES"),
        "ADMIN_ACCESS_MODE": os.environ.get("ADMIN_ACCESS_MODE"),
    }
    app_module = None

    try:
        os.environ["DEBATE_DB_PATH"] = db_path
        os.environ["FACT_CHECK_MODE"] = "OFFLINE"
        os.environ["LLM_PROVIDER"] = "mock"
        os.environ["NUM_JUDGES"] = "3"
        os.environ["ADMIN_ACCESS_MODE"] = "authenticated"
        os.environ["DISABLE_JOB_WORKER"] = "1"

        import backend.app_v3 as app_v3
        app_module = importlib.reload(app_v3)
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        # Register and create a debate
        reg = client.post("/api/auth/register", json={
            "email": "sufficiency@example.com",
            "password": "password123",
            "display_name": "Sufficiency Tester",
        })
        assert reg.status_code == 201
        token = reg.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        create = client.post("/api/debates", headers=headers, json={
            "resolution": "Should sufficiency checks work? This is the resolution text.",
            "scope": "Test whether empty adjudication data returns INSUFFICIENT_DATA correctly.",
        })
        assert create.status_code == 201
        debate_id = create.get_json()["debate_id"]

        # Insert an empty snapshot directly (allowed_count=0, no scores)
        from backend.database import DebateDatabase
        ddb = DebateDatabase(db_path)
        ddb.save_snapshot({
            "snapshot_id": "snap_empty_001",
            "debate_id": debate_id,
            "timestamp": datetime.now().isoformat(),
            "trigger_type": "manual",
            "template_name": "test",
            "template_version": "1.0",
            "allowed_count": 0,
            "blocked_count": 0,
            "overall_for": None,
            "overall_against": None,
            "margin_d": None,
            "ci_d_lower": None,
            "ci_d_upper": None,
            "confidence": None,
            "verdict": "NO VERDICT",
        })

        # Test verdict endpoint
        verdict_resp = client.get(f"/api/debate/verdict?debate_id={debate_id}", headers=headers)
        assert verdict_resp.status_code == 200
        vdata = verdict_resp.get_json()
        assert vdata.get("verdict") == "INSUFFICIENT_DATA", f"Expected INSUFFICIENT_DATA, got {vdata.get('verdict')}"
        assert vdata.get("insufficient_data") is True
        assert vdata.get("message") is not None
        assert vdata.get("replicate_composition_metadata") is not None
        assert vdata["replicate_composition_metadata"]["structural_replicate_count"] == 0

        # Test dossier endpoint
        dossier_resp = client.get(f"/api/debate/decision-dossier?debate_id={debate_id}", headers=headers)
        assert dossier_resp.status_code == 200
        ddata = dossier_resp.get_json()
        assert ddata.get("verdict") == "INSUFFICIENT_DATA"
        assert ddata.get("insufficient_data") is True
        assert ddata.get("message") is not None
        assert "formula_metadata" in ddata

        # Test snapshot endpoint still returns frame metadata even when empty
        snap_resp = client.get(f"/api/debate/snapshot?debate_id={debate_id}", headers=headers)
        assert snap_resp.status_code == 200
        sdata = snap_resp.get_json()
        assert sdata.get("has_snapshot") is False or sdata.get("allowed_count") == 0
        assert "frame_mode" in sdata

        print("✓ Sufficiency checks return INSUFFICIENT_DATA correctly")
    finally:
        if app_module is not None:
            try:
                app_module.debate_engine.shutdown()
            except Exception:
                pass
        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value
        shutil.rmtree(temp_dir)


def test_replicate_composition_metadata_on_sufficient_snapshot():
    """A real snapshot with data must include replicate_composition_metadata with correct counts."""
    print("\n=== Testing Replicate Composition Metadata on Sufficient Snapshot ===")

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_replicate_meta.db")
    old_env = {
        "DEBATE_DB_PATH": os.environ.get("DEBATE_DB_PATH"),
        "FACT_CHECK_MODE": os.environ.get("FACT_CHECK_MODE"),
        "LLM_PROVIDER": os.environ.get("LLM_PROVIDER"),
        "NUM_JUDGES": os.environ.get("NUM_JUDGES"),
        "ADMIN_ACCESS_MODE": os.environ.get("ADMIN_ACCESS_MODE"),
    }
    app_module = None

    try:
        os.environ["DEBATE_DB_PATH"] = db_path
        os.environ["FACT_CHECK_MODE"] = "OFFLINE"
        os.environ["LLM_PROVIDER"] = "mock"
        os.environ["NUM_JUDGES"] = "3"
        os.environ["ADMIN_ACCESS_MODE"] = "authenticated"
        os.environ["DISABLE_JOB_WORKER"] = "1"

        import backend.app_v3 as app_v3
        app_module = importlib.reload(app_v3)
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        # Register and create a debate
        reg = client.post("/api/auth/register", json={
            "email": "replicate@example.com",
            "password": "password123",
            "display_name": "Replicate Tester",
        })
        assert reg.status_code == 201
        token = reg.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        create = client.post("/api/debates", headers=headers, json={
            "resolution": "Should replicate metadata appear? This is the resolution text.",
            "scope": "Test whether replicate composition metadata is present in verdict responses.",
        })
        assert create.status_code == 201
        debate_id = create.get_json()["debate_id"]

        # Use engine directly to generate a real snapshot with posts
        engine = DebateEngineV2(
            db_path=db_path,
            fact_check_mode="OFFLINE",
            llm_provider="mock",
            num_judges=3,
        )
        engine.submit_post(debate_id, "FOR", None,
                           "Renewables create jobs.", "Therefore subsidize.")
        engine.submit_post(debate_id, "AGAINST", None,
                           "Subsidies distort markets.", "Therefore do not subsidize.")
        snap = engine.generate_snapshot(debate_id, trigger_type="manual")
        assert snap["allowed_count"] > 0
        engine.shutdown()

        # Call verdict endpoint
        verdict_resp = client.get(f"/api/debate/verdict?debate_id={debate_id}", headers=headers)
        assert verdict_resp.status_code == 200
        vdata = verdict_resp.get_json()
        assert vdata.get("verdict") != "INSUFFICIENT_DATA"
        meta = vdata.get("replicate_composition_metadata")
        assert meta is not None, "replicate_composition_metadata must be present"
        assert "judge_count" in meta
        assert "replicate_count" in meta
        assert "structural_replicate_count" in meta
        assert "extraction_reruns" in meta
        assert "bootstrap_samples" in meta
        assert "merge_sensitivity_channel" in meta
        print(f"✓ Replicate composition metadata present: {meta}")
    finally:
        if app_module is not None:
            try:
                app_module.debate_engine.shutdown()
            except Exception:
                pass
        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value
        shutil.rmtree(temp_dir)
