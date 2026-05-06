"""Governance blueprint — frames, appeals, judge pool, fairness, incidents."""
import json
import uuid

from flask import Blueprint, g, jsonify, request

from backend import extensions
from backend.lsd_v1_2 import frame_mode as get_frame_mode_flag
from backend.utils.decorators import admin_required, login_required, log_admin_action, optional_auth
from backend.utils.helpers import get_session_debate_id
from backend.utils.validators import ValidationError, validate_string

governance_bp = Blueprint('governance', __name__)
@governance_bp.route('/api/governance/frames', methods=['GET'])
@optional_auth
def get_frames():
    """Get active frame and available frames"""
    debate_id = get_session_debate_id()
    active_frame = extensions.db.get_active_debate_frame(debate_id) if debate_id else None
    frames = extensions.db.get_debate_frames(debate_id) if debate_id else []
    registry_frame = extensions.debate_engine.get_frame_info()
    frame_info = active_frame or registry_frame
    if frame_info and "statement" not in frame_info:
        dossier = {
            "statement": frame_info.get("frame_summary", ""),
            "scope": "; ".join(frame_info.get("scope_constraints", [])),
            "grounding_rationale": "Published active debate frame selected through the governance workflow.",
            "inclusion_justification": "; ".join(frame_info.get("evaluation_criteria", [])),
            "exclusion_note": frame_info.get("notes", ""),
            "known_tensions": frame_info.get("scope_constraints", []),
            "prioritized_values": frame_info.get("evaluation_criteria", [])[:4],
        }
        frame_info = {
            **frame_info,
            "statement": frame_info.get("frame_summary", ""),
            "scope": dossier["scope"],
            "dossier": dossier,
            "next_review_date": frame_info.get("review_date"),
            "review_cadence_months": frame_info.get("review_cadence_months", 6),
            "emergency_override_path": "Use /api/governance/emergency-override with a published rationale.",
        }
    return jsonify({
        'active_frame': frame_info,
        'frames': frames,
        'mode': get_frame_mode_flag(),
        'frame_set_version': frame_info.get('version') if frame_info else None,
        'review_schedule': [
            {
                'frame_id': frame.get('frame_id'),
                'debate_id': frame.get('debate_id'),
                'review_date': frame.get('review_date'),
                'review_cadence_months': frame.get('review_cadence_months', 6),
            }
            for frame in frames
        ],
    })

@governance_bp.route('/api/admin/frame-petitions/<petition_id>/accept', methods=['POST'])
@admin_required
def accept_frame_petition(petition_id):
    """Accept a frame petition and activate a new frame version."""
    petition = extensions.db.get_frame_petition(petition_id)
    if not petition:
        return jsonify({'error': 'Petition not found'}), 404
    reviewer_user_id = (getattr(g, 'user', None) or {}).get('user_id') or 'admin'
    candidate = petition.get('candidate_frame') or {}
    try:
        debate = extensions.debate_engine.create_frame_version(petition['debate_id'], candidate)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400
    decision = {
        'decision': 'accepted',
        'reason': (request.get_json() or {}).get('reason', 'Accepted by admin governance review'),
        'activated_frame_id': debate.get('active_frame_id'),
    }
    updated = extensions.db.update_frame_petition_status(petition_id, 'accepted', decision, reviewer_user_id)
    extensions.debate_engine.governance.log_change(
        change_type='frame',
        description=f"Accepted frame petition {petition_id}",
        changed_by=reviewer_user_id,
        justification=decision['reason'],
        new_value=debate.get('active_frame_id'),
    )
    return jsonify({'petition': updated, 'debate': debate})

@governance_bp.route('/api/admin/frame-petitions/<petition_id>/reject', methods=['POST'])
@admin_required
def reject_frame_petition(petition_id):
    """Reject a frame petition with a published governance decision."""
    petition = extensions.db.get_frame_petition(petition_id)
    if not petition:
        return jsonify({'error': 'Petition not found'}), 404
    reviewer_user_id = (getattr(g, 'user', None) or {}).get('user_id') or 'admin'
    payload = request.get_json() or {}
    decision = {
        'decision': 'rejected',
        'reason': payload.get('reason', 'Rejected by admin governance review'),
    }
    updated = extensions.db.update_frame_petition_status(petition_id, 'rejected', decision, reviewer_user_id)
    extensions.debate_engine.governance.log_change(
        change_type='frame',
        description=f"Rejected frame petition {petition_id}",
        changed_by=reviewer_user_id,
        justification=decision['reason'],
        previous_value=petition_id,
    )
    return jsonify({'petition': updated})

@governance_bp.route('/api/governance/frame-cadence', methods=['GET'])
@optional_auth
def get_frame_cadence():
    """Get frame review cadence"""
    debate_id = get_session_debate_id()
    frames = extensions.db.get_debate_frames(debate_id) if debate_id else []
    return jsonify({
        'debate_id': debate_id,
        'review_schedule': [
            {
                'frame_id': frame.get('frame_id'),
                'version': frame.get('version'),
                'review_date': frame.get('review_date'),
                'review_cadence_months': frame.get('review_cadence_months', 6),
                'governance_decision_id': frame.get('governance_decision_id'),
            }
            for frame in frames
        ],
    })

@governance_bp.route('/api/governance/frame-cadence', methods=['POST'])
@admin_required
def set_frame_cadence():
    """Set frame review cadence"""
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    payload = request.get_json() or {}
    cadence = int(payload.get('review_cadence_months') or 6)
    review_date = payload.get('review_date')
    extensions.db.update_frame_review_schedule(debate_id, review_date, cadence)
    extensions.debate_engine.governance.log_change(
        change_type='frame_cadence',
        description=f"Updated frame review cadence for {debate_id}",
        changed_by=(getattr(g, 'user', None) or {}).get('user_id') or 'admin',
        justification=payload.get('justification', 'Frame stability review cadence update'),
        new_value=json.dumps({'review_date': review_date, 'review_cadence_months': cadence}),
    )
    return get_frame_cadence()

@governance_bp.route('/api/governance/emergency-override', methods=['POST'])
@admin_required
def emergency_frame_override():
    """Emergency frame override"""
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    payload = request.get_json() or {}
    reason = validate_string(payload.get('reason'), 'Emergency reason', min_length=10, max_length=2000)
    target_frame_id = payload.get('frame_id')
    active = extensions.db.get_active_debate_frame(debate_id)
    frame_id = target_frame_id or (active or {}).get('frame_id')
    if not frame_id:
        return jsonify({'error': 'No active frame'}), 404
    if target_frame_id:
        extensions.db.set_active_frame(debate_id, target_frame_id)
    actor = (getattr(g, 'user', None) or {}).get('user_id') or 'admin'
    governance_decision_id = f"gov_{uuid.uuid4().hex[:10]}"
    extensions.db.apply_emergency_override(frame_id, reason, actor, governance_decision_id)
    extensions.debate_engine.governance.log_change(
        change_type='emergency_override',
        description=f"Emergency frame override for {debate_id}",
        changed_by=actor,
        justification=reason,
        new_value=frame_id,
        approval_references=[governance_decision_id],
    )
    return jsonify({
        'governance_decision_id': governance_decision_id,
        'frame_id': frame_id,
        'reason': reason,
    })

@governance_bp.route('/api/governance/changelog', methods=['GET'])
@optional_auth
def get_changelog():
    """Get system changelog"""
    change_type = request.args.get('change_type')
    limit = request.args.get('limit', 100, type=int)
    entries = extensions.debate_engine.governance.get_changelog(change_type=change_type, limit=limit)
    return jsonify({'entries': entries})

@governance_bp.route('/api/governance/appeals', methods=['GET'])
@login_required
def get_appeals():
    """Get appeals"""
    debate_id = get_session_debate_id()
    status = request.args.get('status')
    limit = request.args.get('limit', 100, type=int)
    from backend.governance import AppealStatus
    status_enum = None
    if status:
        try:
            status_enum = AppealStatus(status)
        except ValueError:
            return jsonify({'error': 'Invalid status'}), 400
    appeals = extensions.debate_engine.governance.get_appeals(
        debate_id=debate_id,
        status=status_enum,
        limit=limit
    )
    return jsonify({'appeals': appeals})

@governance_bp.route('/api/debate/<debate_id>/appeals', methods=['POST'])
@login_required
def submit_appeal(debate_id):
    """Submit a new appeal for a specific debate."""
    snapshot = extensions.db.get_latest_snapshot(debate_id)
    if not snapshot:
        return jsonify({'error': 'No snapshot available'}), 404
    data = request.get_json() or {}
    appeal_type = validate_string(
        data.get('appeal_type', 'moderation_error'),
        'Appeal type',
        max_length=50
    )
    valid_types = ['moderation_error', 'topic_misframing', 'missing_argument', 'provenance_error']
    if appeal_type not in valid_types:
        return jsonify({'error': f'Invalid appeal type. Must be one of: {valid_types}'}), 400
    description = validate_string(data.get('description') or data.get('grounds'), 'Description', min_length=10, max_length=2000)
    evidence = data.get('evidence_references', [])
    relief = validate_string(data.get('requested_relief') or 'Review and correct snapshot.', 'Requested relief', min_length=5, max_length=500)
    appeal_id = extensions.debate_engine.governance.submit_appeal(
        debate_id=debate_id,
        snapshot_id=snapshot['snapshot_id'],
        claimant_id=g.user['user_id'],
        grounds=f"[{appeal_type}] {description}",
        evidence_references=evidence if isinstance(evidence, list) else [],
        requested_relief=relief
    )
    return jsonify({'appeal_id': appeal_id, 'status': 'submitted'}), 201

@governance_bp.route('/api/debate/<debate_id>/appeals/mine', methods=['GET'])
@login_required
def get_my_appeals(debate_id):
    """Get appeals submitted by the current user for a debate."""
    appeals = extensions.debate_engine.governance.get_appeals(debate_id=debate_id, limit=500)
    my_appeals = [a for a in appeals if a.get('claimant_id') == g.user['user_id']]
    return jsonify({'appeals': my_appeals})

@governance_bp.route('/api/admin/appeals', methods=['GET'])
@admin_required
def get_admin_appeals():
    """Admin queue: get all appeals."""
    status = request.args.get('status')
    from backend.governance import AppealStatus
    status_enum = None
    if status:
        try:
            status_enum = AppealStatus(status)
        except ValueError:
            return jsonify({'error': 'Invalid status'}), 400
    appeals = extensions.debate_engine.governance.get_appeals(status=status_enum, limit=500)
    return jsonify({'appeals': appeals})

@governance_bp.route('/api/admin/appeals/<appeal_id>/resolve', methods=['POST'])
@admin_required
def resolve_appeal(appeal_id):
    """Admin action: resolve an appeal with published rationale."""
    data = request.get_json() or {}
    decision = validate_string(data.get('decision'), 'Decision', max_length=20)
    valid_decisions = ['accepted', 'rejected']
    if decision not in valid_decisions:
        return jsonify({'error': f'Decision must be one of: {valid_decisions}'}), 400
    decision_reason = validate_string(data.get('decision_reason'), 'Decision reason', min_length=10, max_length=2000)
    resolution = data.get('resolution', '')
    from backend.governance import AppealStatus
    status = AppealStatus.ACCEPTED if decision == 'accepted' else AppealStatus.REJECTED
    success = extensions.debate_engine.governance.review_appeal(
        appeal_id=appeal_id,
        reviewer_id=g.user['user_id'],
        decision=status,
        decision_reason=decision_reason,
        resolution=resolution
    )
    if not success:
        return jsonify({'error': 'Appeal not found or already resolved'}), 404
    if decision == 'accepted':
        appeals = extensions.debate_engine.governance.get_appeals(limit=500)
        appeal = next((a for a in appeals if a['appeal_id'] == appeal_id), None)
        if appeal:
            extensions.db.update_snapshot_status(appeal['snapshot_id'], 'superseded')
    log_admin_action('appeal_resolve', f"Resolved appeal {appeal_id} as {decision}")
    return jsonify({'appeal_id': appeal_id, 'status': decision, 'reason': decision_reason}), 200

@governance_bp.route('/api/governance/judge-pool', methods=['GET'])
@optional_auth
def get_judge_pool():
    """Get judge pool summary"""
    summary = extensions.debate_engine.governance.get_judge_pool_summary()
    return jsonify(summary)

@governance_bp.route('/api/governance/judge-pool/composition', methods=['POST'])
@admin_required
def record_judge_pool_composition():
    """Record judge pool composition entry."""
    payload = request.get_json() or {}
    composition_id = extensions.debate_engine.governance.record_judge_pool_composition(
        category=payload.get('category', 'general'),
        count=payload.get('count', 0),
        qualification_rubric=payload.get('qualification_rubric', {}),
        snapshot_id=payload.get('snapshot_id'),
    )
    return jsonify({'composition_id': composition_id}), 201

@governance_bp.route('/api/governance/judge-pool/rotation-policy', methods=['GET'])
@optional_auth
def get_rotation_policy():
    """Get active rotation policy."""
    policy = extensions.debate_engine.governance.get_rotation_policy()
    return jsonify(policy or {})

@governance_bp.route('/api/governance/judge-pool/rotation-policy', methods=['POST'])
@admin_required
def set_rotation_policy():
    """Set rotation policy."""
    payload = request.get_json() or {}
    policy_id = extensions.debate_engine.governance.set_rotation_policy(
        max_consecutive_snapshots=payload.get('max_consecutive_snapshots', 5),
        cooldown_snapshots=payload.get('cooldown_snapshots', 2),
    )
    return jsonify({'policy_id': policy_id}), 201

@governance_bp.route('/api/governance/judge-pool/calibration-protocol', methods=['GET'])
@optional_auth
def get_calibration_protocol():
    """Get active calibration protocol."""
    protocol = extensions.debate_engine.governance.get_calibration_protocol()
    return jsonify(protocol or {})

@governance_bp.route('/api/governance/judge-pool/calibration-protocol', methods=['POST'])
@admin_required
def set_calibration_protocol():
    """Set calibration protocol."""
    payload = request.get_json() or {}
    protocol_id = extensions.debate_engine.governance.set_calibration_protocol(
        guideline_version=payload.get('guideline_version', 'v1.0'),
        shared_guidelines=payload.get('shared_guidelines', {}),
        inter_judge_consistency_check=payload.get('inter_judge_consistency_check', {}),
    )
    return jsonify({'protocol_id': protocol_id}), 201

@governance_bp.route('/api/governance/judge-pool/conflict-of-interest', methods=['POST'])
@admin_required
def log_conflict_of_interest():
    """Log a conflict-of-interest entry."""
    payload = request.get_json() or {}
    entry_id = extensions.debate_engine.governance.log_conflict_of_interest(
        judge_id=payload.get('judge_id'),
        conflict_type=payload.get('conflict_type', 'recusal'),
        description=payload.get('description', ''),
        debate_id=payload.get('debate_id'),
        topic_id=payload.get('topic_id'),
    )
    return jsonify({'entry_id': entry_id}), 201

@governance_bp.route('/api/governance/fairness-audits', methods=['GET'])
@optional_auth
def get_fairness_audits():
    """Get fairness audit summary"""
    limit = request.args.get('limit', 100, type=int)
    summary = extensions.debate_engine.governance.get_fairness_audit_summary(limit=limit)
    return jsonify(summary)

@governance_bp.route('/api/governance/incidents', methods=['GET'])
@optional_auth
def get_incidents():
    """Get incidents"""
    status = request.args.get('status')
    limit = request.args.get('limit', 100, type=int)
    from backend.governance import IncidentSeverity
    severity_enum = None
    severity = request.args.get('severity')
    if severity:
        try:
            severity_enum = IncidentSeverity(severity)
        except ValueError:
            return jsonify({'error': 'Invalid severity'}), 400
    incidents = extensions.debate_engine.governance.get_incidents(
        status=status,
        severity=severity_enum,
        limit=limit
    )
    return jsonify({'incidents': incidents})

@governance_bp.route('/api/governance/summary', methods=['GET'])
@optional_auth
def get_governance_summary():
    """Get complete governance summary"""
    summary = extensions.debate_engine.governance.get_governance_summary()
    return jsonify(summary)
