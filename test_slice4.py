#!/usr/bin/env python3
"""Test LSD v1.2 Slice 4: Governance and Incident Hooks"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.governance import GovernanceManager, AppealStatus, IncidentSeverity
from backend.database import DebateDatabase


def test_changelog():
    """Test changelog functionality."""
    print("\n=== Testing Changelog ===")
    
    db = DebateDatabase(db_path="/tmp/test_slice4.db")
    gov = GovernanceManager(db)
    
    # Log a frame change
    entry_id = gov.log_change(
        change_type='frame',
        description='Updated frame statement to clarify scope',
        changed_by='admin_001',
        justification='Community feedback indicated scope ambiguity',
        previous_value='Original scope text',
        new_value='Clarified scope text',
        approval_references=['PR #123', 'Issue #456']
    )
    
    assert entry_id.startswith('chg_')
    print(f"✓ Changelog entry created: {entry_id}")
    
    # Log a moderation rule change
    entry_id2 = gov.log_change(
        change_type='moderation',
        description='Updated spam detection threshold',
        changed_by='moderator_002',
        justification='Reducing false positives',
        previous_value='0.85',
        new_value='0.90'
    )
    print(f"✓ Moderation change logged: {entry_id2}")
    
    # Get all changelog
    all_changes = gov.get_changelog()
    assert len(all_changes) >= 2
    print(f"✓ Retrieved {len(all_changes)} changelog entries")
    
    # Filter by type
    frame_changes = gov.get_changelog(change_type='frame')
    assert len(frame_changes) >= 1
    assert frame_changes[0]['change_type'] == 'frame'
    print(f"✓ Filtered to {len(frame_changes)} frame changes")
    
    # Verify structure
    entry = all_changes[0]
    assert 'entry_id' in entry
    assert 'timestamp' in entry
    assert 'justification' in entry
    print(f"✓ Entry structure correct")
    
    print("\n=== Changelog: ALL PASSED ===")
    return True


def test_appeals():
    """Test appeal submission and review."""
    print("\n=== Testing Appeals ===")
    
    db = DebateDatabase(db_path="/tmp/test_slice4.db")
    gov = GovernanceManager(db)
    
    # Submit an appeal
    appeal_id = gov.submit_appeal(
        debate_id="debate_123",
        snapshot_id="snap_abc",
        claimant_id="user_456",
        grounds="New evidence contradicts the conclusion",
        evidence_references=['evidence_doc_1', 'new_study_x'],
        requested_relief="Reconsider conclusion with new evidence"
    )
    
    assert appeal_id.startswith('apl_')
    print(f"✓ Appeal submitted: {appeal_id}")
    
    # Get pending appeals
    pending = gov.get_appeals(status=AppealStatus.PENDING)
    assert len(pending) >= 1
    assert pending[0]['status'] == 'pending'
    print(f"✓ Found {len(pending)} pending appeals")
    
    # Review the appeal
    gov.review_appeal(
        appeal_id=appeal_id,
        reviewer_id="judge_789",
        decision=AppealStatus.ACCEPTED,
        decision_reason="New evidence is material and credible",
        resolution="Appeal accepted; debate reopened for new evidence"
    )
    
    # Verify status changed
    all_appeals = gov.get_appeals()
    # Get by ID
    all_appeals = gov.get_appeals()
    accepted = [a for a in all_appeals if a['appeal_id'] == appeal_id]
    assert len(accepted) == 1
    assert accepted[0]['status'] == 'accepted'
    assert accepted[0]['reviewer_id'] == 'judge_789'
    print(f"✓ Appeal reviewed and accepted")
    
    # Test filter by debate
    debate_appeals = gov.get_appeals(debate_id="debate_123")
    assert len(debate_appeals) >= 1
    print(f"✓ Found {len(debate_appeals)} appeals for debate_123")
    
    print("\n=== Appeals: ALL PASSED ===")
    return True


def test_judge_pool():
    """Test judge pool management."""
    print("\n=== Testing Judge Pool ===")
    
    db = DebateDatabase(db_path="/tmp/test_slice4.db")
    gov = GovernanceManager(db)
    
    # Add judges
    judge1 = gov.add_judge(
        name="Dr. Alice Smith",
        role="senior_assessor",
        appointed_by="governance_board",
        term_expires="2026-12-31",
        specialties=['economics', 'climate_policy']
    )
    print(f"✓ Judge 1 added: {judge1}")
    
    judge2 = gov.add_judge(
        name="Prof. Bob Jones",
        role="domain_expert",
        appointed_by="governance_board",
        specialties=['medicine', 'ethics']
    )
    print(f"✓ Judge 2 added: {judge2}")
    
    # Update judge stats (correct decisions)
    gov.update_judge_stats(judge1, decision_outcome='upheld', was_correct=True)
    gov.update_judge_stats(judge1, decision_outcome='upheld', was_correct=True)
    gov.update_judge_stats(judge1, decision_outcome='overturned', was_correct=False)
    print(f"✓ Judge stats updated")
    
    # Get pool summary
    summary = gov.get_judge_pool_summary()
    
    assert summary['total_judges'] >= 2
    assert 'judges' in summary
    assert 'average_accuracy' in summary
    print(f"✓ Pool summary: {summary['total_judges']} judges")
    print(f"✓ Average accuracy: {summary['average_accuracy']:.3f}")
    print(f"✓ Overturn rate: {summary['overturn_rate']:.4f}")
    
    # Verify individual judge
    judges = summary['judges']
    alice = [j for j in judges if j['name'] == "Dr. Alice Smith"]
    assert len(alice) == 1
    assert alice[0]['decisions_count'] == 3
    assert alice[0]['overturned_count'] == 1
    assert alice[0]['specialties'] == ['economics', 'climate_policy']
    print(f"✓ Judge details verified: {alice[0]['decisions_count']} decisions")
    
    print("\n=== Judge Pool: ALL PASSED ===")
    return True


def test_fairness_audits():
    """Test fairness audit functionality."""
    print("\n=== Testing Fairness Audits ===")
    
    db = DebateDatabase(db_path="/tmp/test_slice4.db")
    gov = GovernanceManager(db)
    
    # Record fairness metrics
    audit1 = gov.record_fairness_metric(
        metric_name='demographic_parity',
        metric_value=0.05,
        demographic_slice='source_type:expert',
        benchmark_value=0.1,
        details={'group_a_rate': 0.72, 'group_b_rate': 0.77}
    )
    print(f"✓ Fairness metric recorded: {audit1}")
    
    audit2 = gov.record_fairness_metric(
        metric_name='demographic_parity',
        metric_value=0.15,  # Above threshold
        demographic_slice='topic_domain:healthcare',
        benchmark_value=0.1,
        details={'group_a_rate': 0.60, 'group_b_rate': 0.75}
    )
    print(f"✓ Warning metric recorded: {audit2}")
    
    # Compute demographic parity
    outcomes = {
        'expert': [True, True, False, True, True],
        'citizen': [True, False, True, False, False],
        'media': [True, True, True, False, True]
    }
    
    parity = gov.compute_demographic_parity(
        debate_id="debate_fairness_test",
        demographic_attribute="source_type",
        outcomes=outcomes
    )
    
    assert 'max_disparity' in parity
    assert 'group_rates' in parity
    assert 'parity_violated' in parity
    print(f"✓ Demographic parity computed: max_disparity={parity['max_disparity']:.3f}")
    print(f"✫ Group rates: {parity['group_rates']}")
    print(f"✓ Parity violated: {parity['parity_violated']}")
    
    # Get audit summary
    summary = gov.get_fairness_audit_summary()
    assert summary['total_audits'] >= 3
    assert 'status_breakdown' in summary
    print(f"✓ Audit summary: {summary['total_audits']} total audits")
    print(f"✓ Status breakdown: {summary['status_breakdown']}")
    
    print("\n=== Fairness Audits: ALL PASSED ===")
    return True


def test_incidents():
    """Test incident reporting and resolution."""
    print("\n=== Testing Incidents ===")
    
    db = DebateDatabase(db_path="/tmp/test_slice4.db")
    gov = GovernanceManager(db)
    
    # Report an incident
    incident_id = gov.report_incident(
        severity=IncidentSeverity.HIGH,
        reported_by="moderator_001",
        description="Coordinated inauthentic behavior detected in debate climate_2024",
        affected_debates=["climate_2024", "energy_policy_12"],
        trigger_snapshot_ids=["snap_before", "snap_after"]
    )
    print(f"✓ Incident reported: {incident_id}")
    
    # Report another incident
    incident_id2 = gov.report_incident(
        severity=IncidentSeverity.MEDIUM,
        reported_by="user_reporter",
        description="Potential bias in topic selection algorithm",
        affected_debates=["ai_ethics_1"],
        trigger_snapshot_ids=["snap_abc"]
    )
    print(f"✓ Second incident reported: {incident_id2}")
    
    # Get open incidents
    open_incidents = gov.get_incidents(status='open')
    assert len(open_incidents) >= 2
    print(f"✓ Found {len(open_incidents)} open incidents")
    
    # Resolve incident with additive snapshot
    gov.resolve_incident(
        incident_id=incident_id,
        resolution_notes="Investigation confirmed CIB. Additive snapshot generated with cleaned data.",
        additive_snapshot_id="snap_additive_cleaned_001"
    )
    
    # Verify resolution
    resolved = [i for i in gov.get_incidents() if i['incident_id'] == incident_id]
    assert len(resolved) == 1
    assert resolved[0]['status'] == 'resolved'
    assert resolved[0]['additive_snapshot_id'] == "snap_additive_cleaned_001"
    print(f"✓ Incident resolved with additive snapshot")
    
    # Filter by severity
    high_severity = gov.get_incidents(severity=IncidentSeverity.HIGH)
    assert len(high_severity) >= 1
    print(f"✓ Found {len(high_severity)} high severity incidents")
    
    print("\n=== Incidents: ALL PASSED ===")
    return True


def test_governance_summary():
    """Test complete governance summary."""
    print("\n=== Testing Governance Summary ===")
    
    db = DebateDatabase(db_path="/tmp/test_slice4.db")
    gov = GovernanceManager(db)
    
    # Add some data
    gov.log_change('frame', 'Test change', 'admin', 'testing')
    gov.submit_appeal('d1', 's1', 'c1', 'test', [], 'test')
    gov.add_judge('Test Judge', 'assessor', 'admin')
    gov.record_fairness_metric('accuracy', 0.85, benchmark_value=0.80)
    gov.report_incident(IncidentSeverity.LOW, 'admin', 'Test', ['d1'], ['s1'])
    
    # Get full summary
    summary = gov.get_governance_summary()
    
    assert 'changelog_summary' in summary
    assert 'appeals_summary' in summary
    assert 'judge_pool' in summary
    assert 'fairness_audits' in summary
    assert 'incidents' in summary
    
    print(f"✓ Changelog entries: {summary['changelog_summary']['total_changes']}")
    print(f"✓ Appeals: {summary['appeals_summary']['total_appeals']} total, {summary['appeals_summary']['pending_count']} pending")
    print(f"✓ Judges: {summary['judge_pool']['total_judges']}")
    print(f"✓ Fairness audits: {summary['fairness_audits']['total_audits']}")
    print(f"✓ Open incidents: {summary['incidents']['open_count']}")
    
    print("\n=== Governance Summary: ALL PASSED ===")
    return True


if __name__ == "__main__":
    print("\n" + "="*60)
    print("LSD v1.2 Slice 4 Test Suite")
    print("Governance and Incident Hooks")
    print("="*60)
    
    all_passed = True
    
    tests = [
        test_changelog,
        test_appeals,
        test_judge_pool,
        test_fairness_audits,
        test_incidents,
        test_governance_summary,
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
        print("✓ ALL SLICE 4 TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
        sys.exit(1)
    print("="*60)
