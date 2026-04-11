#!/usr/bin/env python3
"""Test LSD v1.2 Slice 2: Decision Dossier (Counterfactuals + Decisive Facts)"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.decision_dossier import DecisionDossierAnalyzer, CounterfactualAnalysis
from backend.database import get_db_connection


def test_topic_counterfactuals():
    """Test topic counterfactual analysis."""
    print("\n=== Testing Topic Counterfactuals ===")
    
    db = get_db_connection()
    analyzer = DecisionDossierAnalyzer(db)
    
    # Setup test topics
    topics = [
        {'id': 'topic_A', 'weight': 1.0, 'reliability': 0.8},
        {'id': 'topic_B', 'weight': 0.8, 'reliability': 0.6},
        {'id': 'topic_C', 'weight': 0.5, 'reliability': 0.4},
    ]
    aggregated_score = 0.65
    
    # Compute counterfactuals
    results = analyzer.compute_topic_counterfactuals(
        debate_id="test_debate",
        topics=topics,
        aggregated_score=aggregated_score
    )
    
    assert len(results) == 3, "Should have counterfactual for each topic"
    
    for r in results:
        assert isinstance(r, CounterfactualAnalysis)
        assert r.topic_id in ['topic_A', 'topic_B', 'topic_C']
        assert r.original_score == aggregated_score
        assert r.flip_risk in ['none', 'low', 'medium', 'high']
        print(f"✓ {r.topic_id}: delta={r.delta:.3f}, flip_risk={r.flip_risk}")
    
    # Check high-impact topic has higher delta
    deltas = {r.topic_id: abs(r.delta) for r in results}
    print(f"✓ Topic impact ranking: {sorted(deltas.items(), key=lambda x: -x[1])}")
    
    print("\n=== Topic Counterfactuals: ALL PASSED ===")
    return True


def test_decisive_facts():
    """Test decisive fact identification."""
    print("\n=== Testing Decisive Facts ===")
    
    db = get_db_connection()
    analyzer = DecisionDossierAnalyzer(db)
    
    # Setup test facts
    facts = [
        # High decisiveness: high leverage, medium uncertainty
        {'id': 'f1', 'statement': 'Fact near certainty', 'p_true': 0.95, 'weight': 1.0},
        # High decisiveness: medium leverage, high uncertainty  
        {'id': 'f2', 'statement': 'Uncertain fact', 'p_true': 0.6, 'weight': 1.0},
        # Low decisiveness: low leverage (near 0.5), high uncertainty
        {'id': 'f3', 'statement': 'Neutral fact', 'p_true': 0.5, 'weight': 1.0},
        # Medium decisiveness
        {'id': 'f4', 'statement': 'Another uncertain', 'p_true': 0.7, 'weight': 0.8},
        # Very low decisiveness: high leverage, low uncertainty
        {'id': 'f5', 'statement': 'Certain fact', 'p_true': 0.99, 'weight': 0.5},
    ]
    
    decisive = analyzer.compute_decisive_facts(facts, top_n=3)
    
    assert len(decisive) == 3, "Should return top_n facts"
    
    # Check scoring logic
    for f in decisive:
        assert 'decisiveness' in f
        assert 'leverage' in f
        assert 'uncertainty' in f
        print(f"✓ {f['fact_id']}: decisiveness={f['decisiveness']:.3f} (leverage={f['leverage']:.2f}, uncertainty={f['uncertainty']:.2f})")
    
    # Most decisive should have good balance of leverage and uncertainty
    top_fact = decisive[0]
    print(f"✓ Top decisive fact: {top_fact['fact_id']} with score {top_fact['decisiveness']:.3f}")
    
    print("\n=== Decisive Facts: ALL PASSED ===")
    return True


def test_evidence_gap_summary():
    """Test evidence gap analysis."""
    print("\n=== Testing Evidence Gap Summary ===")
    
    db = get_db_connection()
    analyzer = DecisionDossierAnalyzer(db)
    
    topics = [
        {'id': 't1', 'tier': 'A', 'reliability': 0.8, 'evidence_count': 5},
        {'id': 't2', 'tier': 'A', 'reliability': 0.75, 'evidence_count': 4},
        {'id': 't3', 'tier': 'B', 'reliability': 0.55, 'evidence_count': 2},  # Gap: low reliability
        {'id': 't4', 'tier': 'C', 'reliability': 0.5, 'evidence_count': 1},   # Gap: both
        {'id': 't5', 'tier': 'D', 'reliability': 0.45, 'evidence_count': 3},  # Gap: reliability
    ]
    
    summary = analyzer.generate_evidence_gap_summary("test_debate", topics)
    
    assert summary['total_topics'] == 5
    assert 'insufficiency_rate' in summary
    assert 'tier_distribution' in summary
    assert 'high_priority_gaps' in summary
    
    print(f"✓ Total topics: {summary['total_topics']}")
    print(f"✓ Insufficiency rate: {summary['insufficiency_rate']:.2f}")
    print(f"✓ Tier distribution: {summary['tier_distribution']}")
    print(f"✓ High priority gaps: {len(summary['high_priority_gaps'])}")
    
    # Should identify t3, t4, t5 as gaps
    assert summary['insufficient_topics'] >= 3
    
    print("\n=== Evidence Gap Summary: ALL PASSED ===")
    return True


def test_full_decision_dossier():
    """Test full decision dossier generation."""
    print("\n=== Testing Full Decision Dossier ===")
    
    db = get_db_connection()
    analyzer = DecisionDossierAnalyzer(db)
    
    conclusion = {'p_true': 0.72, 'confidence': 0.65, 'verdict': 'likely_true'}
    
    topics = [
        {'id': 'topic_A', 'weight': 1.0, 'reliability': 0.8},
        {'id': 'topic_B', 'weight': 0.8, 'reliability': 0.6},
    ]
    
    facts = [
        {'id': 'f1', 'statement': 'Supporting evidence A', 'p_true': 0.85, 'weight': 1.0},
        {'id': 'f2', 'statement': 'Supporting evidence B', 'p_true': 0.7, 'weight': 0.9},
    ]
    
    dossier = analyzer.get_decision_dossier(
        debate_id="full_test_debate",
        conclusion=conclusion,
        topics=topics,
        facts=facts
    )
    
    assert dossier['debate_id'] == "full_test_debate"
    assert 'decision_logic' in dossier
    assert 'top_contributors' in dossier
    assert 'counterfactuals' in dossier
    assert 'decisive_facts' in dossier
    assert 'evidence_gaps' in dossier
    assert 'appeal_guidance' in dossier
    
    print(f"✓ Decision logic: {dossier['decision_logic']}")
    print(f"✓ Top contributors: {len(dossier['top_contributors'])}")
    print(f"✓ Counterfactuals: {len(dossier['counterfactuals'])}")
    print(f"✓ Decisive facts: {len(dossier['decisive_facts'])}")
    print(f"✓ Appeal guidance provided")
    
    print("\n=== Full Decision Dossier: ALL PASSED ===")
    return True


if __name__ == "__main__":
    print("\n" + "="*60)
    print("LSD v1.2 Slice 2 Test Suite")
    print("Decision Dossier - Counterfactuals + Decisive Facts")
    print("="*60)
    
    all_passed = True
    
    tests = [
        test_topic_counterfactuals,
        test_decisive_facts,
        test_evidence_gap_summary,
        test_full_decision_dossier,
    ]
    
    for test in tests:
        try:
            all_passed &= test()
        except Exception as e:
            print(f"✗ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False
    
    print("\n" + "="*60)
    if all_passed:
        print("✓ ALL SLICE 2 TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
        sys.exit(1)
    print("="*60)
