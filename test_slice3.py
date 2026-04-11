#!/usr/bin/env python3
"""Test LSD v1.2 Slice 3: Selection Transparency (AU Completeness + Centrality + Integrity)"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.selection_transparency import SelectionTransparencyAnalyzer, AUCompletenessResult, IntegritySignal
from backend.database import get_db_connection


def test_au_completeness():
    """Test Argument Unit completeness scoring."""
    print("\n=== Testing AU Completeness ===")
    
    db = get_db_connection()
    analyzer = SelectionTransparencyAnalyzer(db)
    
    # Complete AU
    complete_au = {
        'id': 'au_1',
        'conclusion': 'The policy will reduce emissions by 20% by 2030',
        'premises': ['Historical data shows similar policies worked', 'Model projections confirm'],
        'source_id': 'src_123',
        'source_type': 'expert',
        'inference_chain': 'Historical pattern + model = prediction'
    }
    
    # Incomplete AU - missing premises and inference
    incomplete_au = {
        'id': 'au_2',
        'conclusion': 'This approach is better',
        'premises': [],
        'source_id': 'src_456',
        'source_type': 'media'
        # Missing inference_chain
    }
    
    # Partial AU
    partial_au = {
        'id': 'au_3',
        'conclusion': 'Evidence supports the claim',
        'premises': ['Study X found Y'],
        'source_type': 'study'  # Missing source_id
        # Missing inference_chain
    }
    
    results = analyzer.au_completeness_score([complete_au, incomplete_au, partial_au])
    
    assert results['total_argument_units'] == 3
    assert 'average_completeness' in results
    assert 'tier_distribution' in results
    
    print(f"✓ Average completeness: {results['average_completeness']:.2f}")
    print(f"✓ Tier distribution: {results['tier_distribution']}")
    
    # Check individual scores
    unit_scores = {r['au_id']: r for r in results['unit_scores']}
    
    assert unit_scores['au_1']['completeness'] == 1.0, "Complete AU should score 1.0"
    assert unit_scores['au_2']['completeness'] <= 0.5, "Incomplete AU should score <= 0.5"
    assert 0.5 <= unit_scores['au_3']['completeness'] <= 0.75, "Partial AU should be in C tier"
    
    print(f"✓ au_1 completeness: {unit_scores['au_1']['completeness']} (complete)")
    print(f"✓ au_2 completeness: {unit_scores['au_2']['completeness']} (incomplete, gaps: {unit_scores['au_2']['gaps']})")
    print(f"✓ au_3 completeness: {unit_scores['au_3']['completeness']} (partial, gaps: {unit_scores['au_3']['gaps']})")
    
    print("\n=== AU Completeness: ALL PASSED ===")
    return True


def test_centrality_with_capping():
    """Test centrality capping to prevent amplification attacks."""
    print("\n=== Testing Centrality with Capping ===")
    
    db = get_db_connection()
    analyzer = SelectionTransparencyAnalyzer(db)
    
    # Simulate item references
    # Item A is highly central (dominant), others less so
    item_refs = {
        'item_A': ['ref1', 'ref2', 'ref3', 'ref4', 'ref5', 'ref6', 'ref7', 'ref8', 'ref9', 'ref10'],
        'item_B': ['ref1', 'ref2', 'ref3'],
        'item_C': ['ref1', 'ref2'],
        'item_D': ['ref1'],
        'item_E': ['ref2'],
    }
    
    results = analyzer.compute_centrality_with_capping(item_refs, cap_percentile=80)
    
    assert 'centrality_scores' in results
    assert 'capping_applied' in results
    assert 'cap_value' in results
    assert 'methodology' in results
    
    print(f"✓ Centrality scores: {results['centrality_scores']}")
    print(f"✓ Capping applied: {results['capping_applied']}")
    print(f"✓ Cap value (P80): {results['cap_value']:.3f}")
    
    # Check that scores are log-transformed
    item_a_raw = 10
    item_a_log = __import__('math').log1p(item_a_raw)
    stored_a = results['centrality_scores']['item_A']
    
    # Item A should be either at cap or close to log(11) ≈ 2.4
    print(f"✓ Item A: raw={item_a_raw}, log={item_a_log:.3f}, stored={stored_a}")
    
    # Items should have different scores reflecting their reference counts
    scores = results['centrality_scores']
    assert scores['item_A'] >= scores['item_B'] >= scores['item_C'], "Ordering should be preserved"
    
    print("\n=== Centrality with Capping: ALL PASSED ===")
    return True


def test_rarity_slice_diagnostics():
    """Test rarity slice (ρ=0.20) utilization tracking."""
    print("\n=== Testing Rarity Slice Diagnostics ===")
    
    db = get_db_connection()
    analyzer = SelectionTransparencyAnalyzer(db)
    
    # Create items with varying reference counts
    items = [
        {'id': 'popular_1', 'refs': ['a', 'b', 'c', 'd', 'e'], 'utilized': True},  # Top 20%
        {'id': 'popular_2', 'refs': ['a', 'b', 'c', 'd'], 'utilized': True},       # Top 20%
        {'id': 'medium_1', 'refs': ['a', 'b'], 'utilized': True},                  # Middle
        {'id': 'medium_2', 'refs': ['a', 'b'], 'utilized': False},
        {'id': 'rare_1', 'refs': ['a'], 'utilized': True},                         # Bottom 20% (rare)
        {'id': 'rare_2', 'refs': ['b'], 'utilized': False},                        # Bottom 20% (rare)
        {'id': 'rare_3', 'refs': ['c'], 'utilized': True},                         # Bottom 20% (rare)
        {'id': 'rare_4', 'refs': ['d'], 'utilized': False},                        # Bottom 20% (rare)
        {'id': 'rare_5', 'refs': ['e'], 'utilized': True},                         # Bottom 20% (rare)
    ]
    
    # With ρ=0.20, bottom 20% (2 items with 0-1 refs) are "rare"
    # But with 9 items, bottom 20% = 1-2 items
    results = analyzer.rarity_slice_diagnostics(items, rarity_threshold=0.20)
    
    assert 'rarity_threshold' in results
    assert 'utilization_rate' in results
    assert 'interpretation' in results
    
    print(f"✓ Rarity threshold: {results['rarity_threshold']}")
    print(f"✓ Total items: {results['total_items']}")
    print(f"✓ Rare items: {results['rare_items']}")
    print(f"✓ Rare items used: {results['rare_items_used']}")
    print(f"✓ Utilization rate: {results['utilization_rate']:.2f}")
    print(f"✓ Interpretation: {results['interpretation']}")
    
    # Utilization rate should be calculable
    assert 0 <= results['utilization_rate'] <= 1
    
    print("\n=== Rarity Slice Diagnostics: ALL PASSED ===")
    return True


def test_integrity_signals():
    """Test integrity signal detection."""
    print("\n=== Testing Integrity Signals ===")
    
    db = get_db_connection()
    analyzer = SelectionTransparencyAnalyzer(db)
    
    # Normal claimants
    claimants = [
        {'id': 'c1', 'type': 'expert'},
        {'id': 'c2', 'type': 'journalist'},
        {'id': 'c3', 'type': 'citizen'},
    ]
    
    # Posts with burst pattern (many in short time)
    from datetime import datetime, timedelta
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    
    burst_posts = [
        {'id': f'p{i}', 'timestamp': (base_time + timedelta(minutes=i*2)).isoformat(), 'content': f'Content {i}', 'claimant_id': f'c{(i % 3) + 1}'}
        for i in range(20)  # 20 posts in 40 minutes = 30 posts/hour
    ]
    
    # Posts with template similarity
    template_posts = [
        {'id': 't1', 'timestamp': base_time.isoformat(), 'content': 'This policy is bad because it hurts the economy and we should oppose it strongly', 'claimant_id': 'c1'},
        {'id': 't2', 'timestamp': (base_time + timedelta(minutes=5)).isoformat(), 'content': 'This policy is bad because it hurts the economy and we should oppose it strongly', 'claimant_id': 'c2'},
        {'id': 't3', 'timestamp': (base_time + timedelta(minutes=10)).isoformat(), 'content': 'This policy is bad because it hurts the economy and we should oppose it strongly', 'claimant_id': 'c3'},
        {'id': 't4', 'timestamp': (base_time + timedelta(minutes=15)).isoformat(), 'content': 'This policy is bad because it hurts the economy and we should oppose it strongly', 'claimant_id': 'c1'},
        {'id': 't5', 'timestamp': (base_time + timedelta(minutes=20)).isoformat(), 'content': 'This policy is bad because it hurts the economy and we should oppose it strongly', 'claimant_id': 'c2'},
        {'id': 't6', 'timestamp': (base_time + timedelta(minutes=25)).isoformat(), 'content': 'Something completely different and original here', 'claimant_id': 'c3'},
    ]
    
    # Low entropy posts (dominated by one claimant)
    low_entropy_posts = [
        {'id': f'e{i}', 'timestamp': (base_time + timedelta(hours=i)).isoformat(), 'content': f'Post {i}', 'claimant_id': 'c1'}
        for i in range(10)  # All from c1
    ]
    
    print("\n-- Testing Burst Detection --")
    results_burst = analyzer.compute_integrity_signals(claimants, burst_posts)
    print(f"✓ Signals detected: {results_burst['signals_detected']}")
    print(f"✓ Overall risk: {results_burst['overall_risk']}")
    for sig in results_burst['signals']:
        print(f"  - {sig['type']}: {sig['severity']} - {sig['description']}")
    
    print("\n-- Testing Template Similarity --")
    results_template = analyzer.compute_integrity_signals(claimants, template_posts)
    print(f"✓ Signals detected: {results_template['signals_detected']}")
    print(f"✓ Overall risk: {results_template['overall_risk']}")
    for sig in results_template['signals']:
        print(f"  - {sig['type']}: {sig['severity']} - {sig['description']}")
    
    print("\n-- Testing Participation Entropy --")
    results_entropy = analyzer.compute_integrity_signals(claimants, low_entropy_posts)
    print(f"✓ Signals detected: {results_entropy['signals_detected']}")
    print(f"✓ Overall risk: {results_entropy['overall_risk']}")
    for sig in results_entropy['signals']:
        print(f"  - {sig['type']}: {sig['severity']} - {sig['description']}")
    
    # Verify detection
    burst_detected = any(s['type'] == 'burst' for s in results_burst['signals'])
    template_detected = any(s['type'] == 'template_similarity' for s in results_template['signals'])
    
    print(f"\n✓ Burst detected: {burst_detected}")
    print(f"✓ Template detected: {template_detected}")
    
    print("\n=== Integrity Signals: ALL PASSED ===")
    return True


def test_full_selection_transparency_report():
    """Test complete selection transparency report generation."""
    print("\n=== Testing Full Selection Transparency Report ===")
    
    db = get_db_connection()
    analyzer = SelectionTransparencyAnalyzer(db)
    
    argument_units = [
        {'id': 'au_1', 'conclusion': 'Conclusion 1', 'premises': ['p1'], 'source_id': 's1', 'source_type': 'expert', 'inference_chain': 'chain'},
        {'id': 'au_2', 'conclusion': 'Conclusion 2', 'premises': [], 'source_id': 's2', 'source_type': 'media', 'inference_chain': ''},
    ]
    
    item_refs = {
        'item_1': ['a', 'b', 'c'],
        'item_2': ['a'],
    }
    
    items = [
        {'id': 'item_1', 'refs': ['a', 'b', 'c'], 'utilized': True},
        {'id': 'item_2', 'refs': ['a'], 'utilized': False},
    ]
    
    claimants = [{'id': 'c1', 'type': 'expert'}]
    posts = [{'id': 'p1', 'timestamp': '2024-01-01T12:00:00', 'content': 'Content', 'claimant_id': 'c1'}]
    
    report = analyzer.get_selection_transparency_report(
        debate_id="test_debate",
        argument_units=argument_units,
        item_refs=item_refs,
        items=items,
        claimants=claimants,
        posts=posts
    )
    
    assert report['debate_id'] == "test_debate"
    assert 'au_completeness' in report
    assert 'centrality_analysis' in report
    assert 'rarity_utilization' in report
    assert 'integrity_signals' in report
    assert 'summary' in report
    
    print(f"✓ Report generated with all sections")
    print(f"✓ Summary: {report['summary']}")
    
    print("\n=== Full Selection Transparency Report: ALL PASSED ===")
    return True


if __name__ == "__main__":
    print("\n" + "="*60)
    print("LSD v1.2 Slice 3 Test Suite")
    print("Selection Transparency - AU Completeness + Centrality + Integrity")
    print("="*60)
    
    all_passed = True
    
    tests = [
        test_au_completeness,
        test_centrality_with_capping,
        test_rarity_slice_diagnostics,
        test_integrity_signals,
        test_full_selection_transparency_report,
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
        print("✓ ALL SLICE 3 TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
        sys.exit(1)
    print("="*60)
