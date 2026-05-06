"""Admin blueprint — moderation templates, snapshot admin, audit export."""
import json

from flask import Blueprint, g, jsonify, request

from backend import extensions
from backend.modulation import ModulationEngine
from backend.utils.decorators import admin_required, log_admin_action
from backend.utils.helpers import get_session_debate_id
from backend.utils.validators import normalize_moderation_template_payload, ValidationError, validate_string

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/api/admin/moderation-template/current', methods=['GET'])
@admin_required
def get_current_admin_moderation_template():
    """Get the active moderation template and live moderation outcomes."""
    from backend.utils.decorators import get_admin_access_mode
    template = extensions.db.get_active_moderation_template()
    debate_id = get_session_debate_id()
    moderation_outcomes = extensions.db.get_moderation_outcome_summary(debate_id=debate_id)
    latest_snapshot = extensions.db.get_latest_snapshot(debate_id) if debate_id else extensions.db.get_latest_snapshot_any()
    suppression_policy = {}
    if latest_snapshot:
        suppression_policy = json.loads(latest_snapshot.get('suppression_policy_json', '{}') or '{}')
    return jsonify({
        'template': template,
        'moderation_outcomes': moderation_outcomes,
        'suppression_policy': suppression_policy or {
            'k': 5,
            'affected_buckets': [],
            'affected_bucket_count': 0,
        },
        'available_bases': ModulationEngine.list_builtin_templates(),
        'admin_access_mode': get_admin_access_mode(),
    })


@admin_bp.route('/api/admin/moderation-template/history', methods=['GET'])
@admin_required
def get_admin_moderation_template_history():
    """List moderation template drafts/applied versions."""
    from backend.utils.decorators import get_admin_access_mode
    limit = request.args.get('limit', 50, type=int)
    limit = max(1, min(limit, 200))
    history = extensions.db.get_moderation_template_history(limit=limit)
    return jsonify({
        'history': history,
        'count': len(history),
        'admin_access_mode': get_admin_access_mode(),
    })


@admin_bp.route('/api/admin/moderation-template/draft', methods=['POST'])
@admin_required
def save_admin_moderation_template_draft():
    """Save moderation settings as a versioned draft template."""
    data = request.get_json() or {}
    payload = normalize_moderation_template_payload(data)
    author_user_id = (getattr(g, 'user', None) or {}).get('user_id')
    draft = extensions.db.create_moderation_template_version(
        base_template_id=payload['base_template_id'],
        template_name=payload['template_name'],
        version=payload['version'],
        status='draft',
        topic_requirements=payload['topic_requirements'],
        toxicity_settings=payload['toxicity_settings'],
        pii_settings=payload['pii_settings'],
        spam_rate_limit_settings=payload['spam_rate_limit_settings'],
        prompt_injection_settings=payload['prompt_injection_settings'],
        author_user_id=author_user_id,
        notes=payload['notes'],
    )
    return jsonify({
        'message': 'Draft template saved',
        'template': draft,
    }), 201


@admin_bp.route('/api/admin/moderation-template/apply', methods=['POST'])
@admin_required
def apply_admin_moderation_template():
    """Apply a moderation template version and update the active pointer."""
    data = request.get_json() or {}
    author_user_id = (getattr(g, 'user', None) or {}).get('user_id')
    template_record_id = (data.get('template_record_id') or '').strip()
    if template_record_id:
        applied = extensions.db.activate_moderation_template(
            template_record_id,
            author_user_id=author_user_id,
        )
        if not applied:
            return jsonify({'error': 'Template record not found'}), 404
    else:
        payload = normalize_moderation_template_payload(data)
        applied = extensions.db.create_moderation_template_version(
            base_template_id=payload['base_template_id'],
            template_name=payload['template_name'],
            version=payload['version'],
            status='active',
            topic_requirements=payload['topic_requirements'],
            toxicity_settings=payload['toxicity_settings'],
            pii_settings=payload['pii_settings'],
            spam_rate_limit_settings=payload['spam_rate_limit_settings'],
            prompt_injection_settings=payload['prompt_injection_settings'],
            author_user_id=author_user_id,
            notes=payload['notes'],
        )
    extensions.debate_engine.refresh_active_modulation_template(force=True)
    moderation_outcomes = extensions.db.get_moderation_outcome_summary(debate_id=get_session_debate_id())
    return jsonify({
        'message': 'Template applied and set active',
        'template': applied,
        'moderation_outcomes': moderation_outcomes,
    })


@admin_bp.route('/api/admin/snapshots/<snapshot_id>/verify', methods=['POST'])
@admin_required
def verify_snapshot_endpoint(snapshot_id):
    """Verify snapshot determinism by recomputing input/output hashes."""
    result = extensions.debate_engine.verify_snapshot(snapshot_id)
    return jsonify(result)


@admin_bp.route('/api/admin/snapshots/<snapshot_id>/verify-job', methods=['POST'])
@admin_required
def enqueue_verify_job(snapshot_id):
    """Enqueue a background verification job for a snapshot."""
    job_id = extensions.job_queue.create_job(
        'verify',
        {
            'snapshot_id': snapshot_id,
            'user_id': g.user['user_id'],
        },
        runtime_profile_id=extensions.current_runtime_profile["runtime_profile_id"],
        request_id=getattr(g, 'request_id', None),
    )
    log_admin_action('verify_job_enqueue', f"Enqueued verification job {job_id} for snapshot {snapshot_id}")
    return jsonify({'job_id': job_id, 'status': 'queued'}), 202


@admin_bp.route('/api/audit/export/<snapshot_id>', methods=['GET'])
@admin_required
def export_audit_bundle(snapshot_id):
    """Export a verifiable audit bundle for authorized auditors."""
    bundle = extensions.debate_engine.export_audit_bundle(snapshot_id)
    if 'error' in bundle:
        return jsonify(bundle), 404
    return jsonify(bundle)


@admin_bp.route('/api/admin/snapshots/<snapshot_id>/mark-incident', methods=['POST'])
@admin_required
def mark_snapshot_incident(snapshot_id):
    """Mark a snapshot as incident without deleting or mutating prior outputs."""
    snapshot = extensions.debate_engine.get_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({'error': 'Snapshot not found'}), 404
    payload = request.get_json() or {}
    severity_raw = (payload.get('severity') or 'medium').lower()
    from backend.governance import IncidentSeverity
    try:
        severity = IncidentSeverity(severity_raw)
    except ValueError:
        return jsonify({'error': 'Invalid severity'}), 400
    description = validate_string(payload.get('description'), 'Description', min_length=10, max_length=2000)
    remediation_plan = validate_string(payload.get('remediation_plan') or 'Publish additive correction snapshot after review.', 'Remediation plan', min_length=5, max_length=2000)
    actor = (getattr(g, 'user', None) or {}).get('user_id') or 'admin'
    incident_id = extensions.debate_engine.governance.report_incident(
        severity=severity,
        reported_by=actor,
        description=description,
        affected_debates=[snapshot['debate_id']],
        trigger_snapshot_ids=[snapshot_id],
        snapshot_id=snapshot_id,
        affected_outputs=payload.get('affected_outputs') or {},
        remediation_plan=remediation_plan,
    )
    extensions.db.update_snapshot_status(snapshot_id, 'incident')
    return jsonify({
        'incident_id': incident_id,
        'snapshot_id': snapshot_id,
        'status': 'incident',
    }), 201
